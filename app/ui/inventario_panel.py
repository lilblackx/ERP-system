"""
Panel completo del módulo Inventario.
Mismo patrón visual y de interacción que app/ui/clientes_panel.py (paleta y tipografía
de app/ui/styles.py) para mantener consistencia entre módulos: barra de herramientas,
tabla estilizada, paginación (D-01) y exportación a Excel (R-02/R-10).
"""

import logging
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

import qtawesome as qta
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import IntegrityError

from app.db.models import Inventario, ProductoPrecio, Usuario
from app.services.categorias import CategoriaService
from app.services.exportacion import exportar_excel, exportar_pdf
from app.services.inventario import PrecioService, ProductoService
from app.services.permisos import PermisoDenegadoError
from app.ui.animaciones import liberar_boton, ocupar_boton
from app.ui.auto_refresco import AutoRefresco
from app.ui.carga_asincrona import CargaAsincronaMixin, sesion_para_dialogo
from app.ui.message_box import MessageBox
from app.ui.paginacion import ControlPaginacion, MixinPaginacion
from app.ui.permisos_ui import MixinPermisos
from app.ui.producto_auditoria_dialog import ProductoAuditoriaDialog
from app.ui.producto_form_dialog import ProductoFormDialog
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_DANGER,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
    SEARCH_QSS,
    TABLE_QSS,
    EstadoBadge,
    alinear_encabezados,
    aplicar_fondo_panel,
    aplicar_sombra,
    estilizar_tarjeta,
)
from app.ui.toolbar_popups import BotonExportar, BotonFiltros
from app.ui.workers import QueryWorker

logger = logging.getLogger(__name__)

COLS_VISIBLES = [
    "ID",
    "CÓDIGO",
    "NOMBRE",
    "CATEGORÍA",
    "CANTIDAD",
    "CAJAS",
    "A GRANEL",
    "COSTO",
    "PRECIO 1",
    "PRECIO 2",
    "PRECIO 3",
    "ESTADO",
]
COL_ID_INTERNO = 0  # oculto
# Columna extra (indice len(COLS_VISIBLES)) para el modo "Conciliar inventario": siempre vacia, es donde el
# usuario anota el conteo fisico en la hoja exportada.
COL_INV_FISICO = len(COLS_VISIBLES)
# Modo conciliacion: las columnas que se ven en pantalla y en la exportacion (NOMBRE, CATEGORIA, CANTIDAD,
# CAJAS, A GRANEL + la columna vacia INVENTARIO FISICO).
_COLUMNAS_CONCILIACION = ["NOMBRE", "CATEGORÍA", "CANTIDAD", "CAJAS", "A GRANEL", "INVENTARIO FÍSICO"]
_INDICES_CONCILIACION = [2, 3, 4, 5, 6]  # posiciones en la fila completa de COLS_VISIBLES
POR_PAGINA = 25
# Mismo horizonte que ProductoService.obtener_alertas_stock(dias_vencimiento=30) --
# mantener sincronizado si ese default cambia.
DIAS_VENCIMIENTO_ALERTA = 30


def _filas_productos_query(session, texto, id_categoria, solo_con_stock, id_usuario) -> list[list]:
    resultado = ProductoService.buscar(
        session,
        texto=texto,
        id_categoria=id_categoria,
        solo_con_stock=solo_con_stock,
        pagina=1,
        por_pagina=1_000_000,
        id_usuario=id_usuario,
    )
    precios = InventarioPanel._obtener_precios(session, [p.id_producto for p in resultado["items"]])

    filas = []
    for p in resultado["items"]:
        cantidad_unidad = Decimal(str(p.cantidad_unidad)) if p.cantidad_unidad is not None else Decimal("0")

        # Calcular cajas y unidades sueltas dinámicamente usando Decimal
        if p.cantidad_caja is not None and p.cantidad_caja > 0 and cantidad_unidad > 0:
            cajas = cantidad_unidad // Decimal(str(p.cantidad_caja))
            unidades_sueltas = cantidad_unidad % Decimal(str(p.cantidad_caja))
        else:
            cajas = Decimal("0")
            unidades_sueltas = cantidad_unidad

        filas.append(
            [
                p.id_producto,
                p.cod_producto,
                p.nombre_producto,
                p.categoria.nombre if p.categoria else None,
                float(cantidad_unidad),
                float(cajas),
                float(unidades_sueltas),
                float(p.costo_producto) if p.costo_producto is not None else 0.0,
                precios.get(p.id_producto, {}).get("precio_1"),
                precios.get(p.id_producto, {}).get("precio_2"),
                precios.get(p.id_producto, {}).get("precio_3"),
                p.estado_producto,
            ]
        )

    return filas


def _tarea_exportar_productos_excel(
    session, ruta: str, texto, id_categoria, solo_con_stock, id_usuario, conciliar=False
) -> tuple[str, int]:
    """Corre en un QThread aparte (QueryWorker) -- consultar y volcar el catalogo
    completo de inventario a un archivo (openpyxl) es lo bastante lento como para
    congelar la ventana si se hace en el hilo de GUI."""
    filas = _filas_productos_query(session, texto, id_categoria, solo_con_stock, id_usuario)
    if conciliar:
        filas = [[fila[i] for i in _INDICES_CONCILIACION] + [""] for fila in filas]
        exportar_excel(ruta, _COLUMNAS_CONCILIACION, filas, titulo="Conciliación de Inventario")
    else:
        exportar_excel(ruta, COLS_VISIBLES, filas)
    return ruta, len(filas)


def _tarea_exportar_productos_pdf(
    session, ruta: str, texto, id_categoria, solo_con_stock, id_usuario, conciliar=False
) -> tuple[str, int]:
    filas = _filas_productos_query(session, texto, id_categoria, solo_con_stock, id_usuario)
    if conciliar:
        filas = [[fila[i] for i in _INDICES_CONCILIACION] + [""] for fila in filas]
        exportar_pdf(ruta, "Conciliación de Inventario", _COLUMNAS_CONCILIACION, filas)
    else:
        exportar_pdf(ruta, "Inventario", COLS_VISIBLES, filas)
    return ruta, len(filas)


def _tarea_cargar_productos(session, **filtros) -> dict:
    """Corre en un hilo aparte (ver carga_asincrona.py): la pagina de productos, sus precios y las alertas."""
    id_usuario = filtros["id_usuario"]
    resultado = ProductoService.buscar(session, **filtros)
    return {
        "resultado": resultado,
        "precios": InventarioPanel._obtener_precios(session, [p.id_producto for p in resultado["items"]]),
        "alertas": {
            tipo: len(productos)
            for tipo, productos in ProductoService.obtener_alertas_stock(session, id_usuario=id_usuario).items()
        },
    }


def _tarea_form_producto(session, session_factory, id_usuario: int | None, id_producto: int | None = None) -> dict:
    """Corre en un hilo aparte (ver carga_asincrona.py): categorias (y, al editar, el producto y su precio) para el
    formulario. Devuelve la sesion usada, que el panel usa para guardar y cierra al terminar."""
    sesion = sesion_para_dialogo(session_factory)
    try:
        try:
            categorias = CategoriaService.listar(sesion, id_usuario=id_usuario)
        except PermisoDenegadoError:
            categorias = None  # el formulario avisa que falta 'categorias'/'ver'
        precargado = {"categorias": categorias}
        producto = None
        if id_producto is not None:
            producto = sesion.get(Inventario, id_producto)
            if producto is not None:
                precargado["precio"] = PrecioService.obtener_precio(sesion, id_producto, id_usuario=id_usuario)
        return {"session": sesion, "producto": producto, "precargado": precargado}
    except BaseException:
        sesion.close()
        raise


class InventarioPanel(CargaAsincronaMixin, MixinPermisos, MixinPaginacion, QWidget):
    """Panel principal del módulo Inventario: catálogo de productos con búsqueda,
    filtro por categoría, paginación, alta/edición (con precio de venta) y export."""

    recurso_permisos = "inventario"

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.es_vendedor = usuario.id_vendedor_usuario is not None
        # Que botones de escritura se muestran depende del permiso real del rol, no solo de si el
        # usuario es vendedor: un CAJERO ve el catalogo (inventario:ver) pero no puede crear,
        # editar ni cambiar el estado de productos.
        self.puede_crear = self._puede("crear")
        self.puede_editar = self._puede("editar")
        self.puede_cambiar_estado = self._puede("eliminar")
        self.setObjectName("ContentArea")
        self._setup_ui()
        QTimer.singleShot(100, self._cargar_categorias_filtro)
        QTimer.singleShot(100, self.cargar_productos)
        # Stock en tiempo real: ventas, recepciones y devoluciones de otras estaciones
        # (ver app/ui/auto_refresco.py).
        self._auto_refresco = AutoRefresco(
            self, self._refresco_periodico, lambda: self.tabla, COL_ID_INTERNO, asincrono=True
        )

    def showEvent(self, event: QShowEvent) -> None:
        # Mismo problema que DashboardPanel/FacturacionPanel/ClientesPanel:
        # MainWindow cachea el panel y lo reutiliza via QStackedWidget.
        # _cargar_categorias_filtro preserva la categoria seleccionada al
        # reconstruir el combo, asi que es seguro repetirla en cada revisita.
        super().showEvent(event)
        self._cargar_categorias_filtro()
        self.cargar_productos()

    def focusInEvent(self, event) -> None:
        # Refrescar datos cuando el panel gana foco (ej: despues de crear
        # una recepcion en el modulo de compras y volver aqui)
        super().focusInEvent(event)
        self.cargar_productos()

    # ── Construcción de la UI ─────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        root.addWidget(self._make_header())
        root.addWidget(self._make_toolbar())
        root.addWidget(self._make_table())
        root.addWidget(self._make_footer())

        aplicar_fondo_panel(self)

    def _make_header(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("CATÁLOGO DE PRODUCTOS")
        lbl.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        self.lbl_total = QLabel("Cargando…")
        self.lbl_total.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 13px;"
            f" background-color: {COLOR_TABLE_HEADER}; border-radius: 10px;"
            " padding: 3px 10px;"
        )

        # Icono real (qtawesome) + texto en vez de un caracter "⚠" suelto en el string --
        # ver GUIA_ESTILO_UI.md 3.1 (todo icono de la app es qtawesome, ninguno un emoji).
        self.lbl_alertas = QWidget()
        self.lbl_alertas.setStyleSheet("background-color: #FEF3C7; border-radius: 10px;")
        alertas_layout = QHBoxLayout(self.lbl_alertas)
        alertas_layout.setContentsMargins(8, 3, 10, 3)
        alertas_layout.setSpacing(5)
        icon_alertas = QLabel()
        icon_alertas.setPixmap(qta.icon("fa5s.exclamation-triangle", color=COLOR_WARNING).pixmap(QSize(12, 12)))
        icon_alertas.setStyleSheet("background: transparent;")
        self.lbl_alertas_texto = QLabel()
        self.lbl_alertas_texto.setStyleSheet(
            f"color: {COLOR_WARNING}; font-size: 13px; font-weight: bold; background: transparent;"
        )
        alertas_layout.addWidget(icon_alertas)
        alertas_layout.addWidget(self.lbl_alertas_texto)
        self.lbl_alertas.setVisible(False)

        h.addWidget(lbl)
        h.addWidget(self.lbl_total)
        h.addWidget(self.lbl_alertas)
        h.addStretch()
        return w

    def _make_toolbar(self) -> QWidget:
        w = QWidget()
        estilizar_tarjeta(w, padding=4, radio=8)
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)

        self.buscar_input = QLineEdit()
        self.buscar_input.setPlaceholderText("Buscar por código o nombre…")
        self.buscar_input.addAction(
            qta.icon("fa5s.search", color=COLOR_TEXT_LIGHT),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.buscar_input.setObjectName("SearchInput")
        self.buscar_input.setStyleSheet(SEARCH_QSS)
        self.buscar_input.setFixedWidth(220)
        self.buscar_input.returnPressed.connect(self._buscar_desde_inicio)
        self.buscar_input.textChanged.connect(self._busqueda_dinamica)

        self.categoria_filtro_combo = QComboBox()
        self.categoria_filtro_combo.addItem("Todas las categorías")
        self.categoria_filtro_combo.currentIndexChanged.connect(self._buscar_desde_inicio)

        self.solo_stock_check = QCheckBox("Solo con stock")
        self.solo_stock_check.toggled.connect(self._buscar_desde_inicio)

        # Modo "Conciliar inventario": la tabla y las exportaciones quedan solo con las columnas del conteo
        # fisico (Nombre, Categoria, Cantidad, Cajas, A Granel + Inventario Fisico vacia).
        self.conciliar_check = QCheckBox("Conciliar inventario")
        self.conciliar_check.setToolTip("Muestra y exporta solo las columnas del conteo físico")
        self.conciliar_check.toggled.connect(self._alternar_modo_conciliacion)

        self.btn_filtrar = BotonFiltros(
            [
                ("Categoría", self.categoria_filtro_combo),
                ("", self.solo_stock_check),
                ("", self.conciliar_check),
            ]
        )

        self.btn_nuevo = QPushButton("Nuevo Producto")
        self.btn_nuevo.setIcon(qta.icon("fa5s.plus", color="white"))
        self.btn_nuevo.setStyleSheet(BUTTON_PRIMARY_QSS)
        self.btn_nuevo.clicked.connect(self.nuevo_producto)

        self.btn_auditoria = QPushButton("Auditoría")
        self.btn_auditoria.setIcon(qta.icon("fa5s.history", color=COLOR_PRIMARY))
        self.btn_auditoria.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_auditoria.clicked.connect(self.abrir_auditoria)

        self.btn_exportar = BotonExportar(on_excel=self.exportar_excel_productos, on_pdf=self.exportar_pdf_productos)

        self.btn_refresh = QPushButton()
        self.btn_refresh.setIcon(qta.icon("fa5s.sync", color=COLOR_PRIMARY))
        self.btn_refresh.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_refresh.setFixedWidth(36)
        self.btn_refresh.setToolTip("Refrescar inventario")
        self.btn_refresh.clicked.connect(lambda: self.cargar_productos())

        h.addWidget(self.buscar_input)
        h.addSpacerItem(QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        # Creación y auditoría: no para vendedores; crear, además, solo con inventario:crear
        if not self.es_vendedor:
            if self.puede_crear:
                h.addWidget(self.btn_nuevo)
            h.addWidget(self.btn_auditoria)
        h.addWidget(self.btn_filtrar)
        h.addWidget(self.btn_refresh)
        h.addWidget(self.btn_exportar)
        return w

    def _make_table(self) -> QTableWidget:
        self.tabla = QTableWidget(0, len(COLS_VISIBLES) + 1)  # +1: columna INVENTARIO FÍSICO del modo conciliación
        self.tabla.setHorizontalHeaderLabels(COLS_VISIBLES + ["INVENTARIO FÍSICO"])
        alinear_encabezados(
            self.tabla,
            {
                1: Qt.AlignmentFlag.AlignLeft,
                2: Qt.AlignmentFlag.AlignLeft,
                3: Qt.AlignmentFlag.AlignLeft,
                4: Qt.AlignmentFlag.AlignRight,
                5: Qt.AlignmentFlag.AlignRight,
                6: Qt.AlignmentFlag.AlignRight,
                7: Qt.AlignmentFlag.AlignRight,
                8: Qt.AlignmentFlag.AlignRight,
                9: Qt.AlignmentFlag.AlignRight,
                10: Qt.AlignmentFlag.AlignRight,
                11: Qt.AlignmentFlag.AlignCenter,
                COL_INV_FISICO: Qt.AlignmentFlag.AlignLeft,
            },
        )
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setShowGrid(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(11, QHeaderView.ResizeMode.Fixed)
        self.tabla.setColumnWidth(11, 110)
        self.tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(self.tabla)
        self.tabla.setColumnHidden(COL_ID_INTERNO, True)
        self.tabla.setColumnHidden(COL_INV_FISICO, True)  # solo visible en modo conciliación
        self.tabla.verticalHeader().setDefaultSectionSize(48)
        return self.tabla

    def _alternar_modo_conciliacion(self) -> None:
        """En modo conciliación la tabla muestra solo las columnas del conteo físico."""
        conciliar = self.conciliar_check.isChecked()
        visibles = {2, 3, 4, 5, 6} if conciliar else set(range(1, len(COLS_VISIBLES)))
        for col in range(len(COLS_VISIBLES)):
            self.tabla.setColumnHidden(col, col not in visibles)
        self.tabla.setColumnHidden(COL_ID_INTERNO, True)
        self.tabla.setColumnHidden(COL_INV_FISICO, not conciliar)

    def _make_footer(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        self.paginacion = ControlPaginacion()
        self.paginacion.pagina_cambiada.connect(lambda _pagina: self.cargar_productos())

        h.addWidget(self.paginacion)
        h.addStretch()
        # Edición y cambio de estado: no para vendedores y solo con el permiso correspondiente
        if not self.es_vendedor and self.puede_editar:
            self.btn_editar = QPushButton("Editar seleccionado")
            self.btn_editar.setIcon(qta.icon("fa5s.edit", color=COLOR_TEXT_DARK))
            self.btn_editar.setStyleSheet(BUTTON_SECONDARY_QSS)
            self.btn_editar.clicked.connect(self.editar_producto)
            h.addWidget(self.btn_editar)
        if not self.es_vendedor and self.puede_cambiar_estado:
            self.btn_estado = QPushButton("Cambiar estado")
            self.btn_estado.setIcon(qta.icon("fa5s.sync-alt", color=COLOR_TEXT_DARK))
            self.btn_estado.setStyleSheet(BUTTON_SECONDARY_QSS)
            self.btn_estado.clicked.connect(self.cambiar_estado_producto_seleccionado)
            h.addWidget(self.btn_estado)
        return w

    # ── Timer para búsqueda dinámica (300 ms debounce) ────────────────────

    def _busqueda_dinamica(self) -> None:
        if not hasattr(self, "_timer_busqueda"):
            self._timer_busqueda = QTimer()
            self._timer_busqueda.setSingleShot(True)
            self._timer_busqueda.timeout.connect(self._buscar_desde_inicio)
        self._timer_busqueda.start(400)

    def _buscar_desde_inicio(self) -> None:
        self.pagina_actual = 1
        self.cargar_productos(silencioso=True)  # busqueda mientras se escribe: no enciende la barra de carga

    def _refresco_periodico(self, al_terminar: Callable[[], None]) -> None:
        # En un hilo aparte: la ventana no se detiene mientras la base responde. AutoRefresco vuelve a seleccionar la
        # fila (por id) cuando la tabla ya esta repoblada (`al_terminar`).
        self.cargar_productos(silencioso=True, al_terminar=al_terminar)

    # ── Lógica de datos ───────────────────────────────────────────────────

    def _cargar_categorias_filtro(self) -> None:
        session = self.session_factory()
        try:
            actual = self.categoria_filtro_combo.currentData()
            self.categoria_filtro_combo.blockSignals(True)
            self.categoria_filtro_combo.clear()
            self.categoria_filtro_combo.addItem("Todas las categorías")
            for categoria in CategoriaService.listar(session, id_usuario=self.usuario.id_usuario):
                self.categoria_filtro_combo.addItem(categoria.nombre, categoria.id_categoria)
            idx = self.categoria_filtro_combo.findData(actual)
            self.categoria_filtro_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.categoria_filtro_combo.blockSignals(False)
        except Exception:
            logger.exception("Fallo al cargar categorías para el filtro de inventario")
        finally:
            session.close()

    def cargar_productos(
        self, silencioso: bool = False, sincrono: bool = False, al_terminar: Callable[[], None] | None = None
    ) -> None:
        self.cargar_async(
            "productos",
            _tarea_cargar_productos,
            self._mostrar_productos,
            texto_error="No se pudo cargar el catálogo de inventario.",
            texto_sin_permiso="No tienes permiso para consultar inventario.",
            silencioso=silencioso,
            sincrono=sincrono,
            al_terminar=al_terminar,
            texto=self.buscar_input.text().strip() or None,
            id_categoria=self.categoria_filtro_combo.currentData(),
            solo_con_stock=self.solo_stock_check.isChecked(),
            pagina=self.pagina_actual,
            por_pagina=POR_PAGINA,
            id_usuario=self.usuario.id_usuario,
        )

    def _mostrar_productos(self, datos: dict) -> None:
        self._poblar_tabla(datos["resultado"], datos["precios"])
        self._actualizar_alertas(datos["alertas"])

    @staticmethod
    def _obtener_precios(session, ids_producto: list[int]) -> dict[int, dict[str, float]]:
        """Lookup de solo-lectura directo (mismo criterio que cliente_form_dialog.py
        consultando Vendedor/CategoriaCliente sin pasar por un servicio): evita N
        consultas de PrecioService.obtener_precio(), una por fila de la tabla."""
        if not ids_producto:
            return {}
        filas = session.query(ProductoPrecio).filter(ProductoPrecio.id_producto.in_(ids_producto)).all()
        return {
            fila.id_producto: {
                "precio_1": float(fila.precio_1) if fila.precio_1 is not None else None,
                "precio_2": float(fila.precio_2) if fila.precio_2 is not None else None,
                "precio_3": float(fila.precio_3) if fila.precio_3 is not None else None,
            }
            for fila in filas
        }

    def _actualizar_alertas(self, alertas: dict) -> None:
        n_bajo_stock = alertas["bajo_stock"]
        n_proximos_vencer = alertas["proximos_vencer"]
        # Antes se sumaban ambos conteos en un solo numero ("3 productos con alerta")
        # sin decir de que se trataba -- confuso para el usuario, que veia stock de sobra
        # y no entendia por que el producto estaba marcado (la alerta real era por
        # vencimiento proximo, no por stock).
        partes = []
        if n_bajo_stock:
            partes.append(f"{n_bajo_stock} con stock bajo")
        if n_proximos_vencer:
            partes.append(f"{n_proximos_vencer} por vencer")
        if partes:
            self.lbl_alertas_texto.setText(" · ".join(partes))
            self.lbl_alertas.setVisible(True)
        else:
            self.lbl_alertas.setVisible(False)

    def _poblar_tabla(self, resultado: dict, precios: dict[int, dict[str, float]]) -> None:
        productos: list[Inventario] = resultado["items"]
        self.tabla.setRowCount(len(productos))
        limite_vencimiento = date.today() + timedelta(days=DIAS_VENCIMIENTO_ALERTA)
        for fila, p in enumerate(productos):
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(p.id_producto)))
            self.tabla.setItem(fila, 1, QTableWidgetItem(p.cod_producto or ""))

            # Indicador sutil de alerta (icono + tooltip) en la misma fila del producto --
            # antes la unica senal era el contador agregado del encabezado ("N con
            # alerta"), sin decir CUAL producto ni por que (stock bajo vs. por vencer).
            item_nombre = QTableWidgetItem(p.nombre_producto or "")
            motivos = []
            cantidad_minima = Decimal(str(p.cantidad_minima)) if p.cantidad_minima is not None else Decimal("0")
            if cantidad_minima > 0 and p.cantidad_unidad is not None and p.cantidad_unidad < cantidad_minima:
                motivos.append(f"Stock bajo (mínimo configurado: {float(cantidad_minima):,.2f})")
            if p.fecha_vencimiento is not None and p.fecha_vencimiento <= limite_vencimiento:
                motivos.append(f"Vence el {p.fecha_vencimiento.strftime('%d/%m/%Y')}")
            if motivos:
                item_nombre.setIcon(qta.icon("fa5s.exclamation-triangle", color=COLOR_WARNING))
                item_nombre.setToolTip(" · ".join(motivos))
            self.tabla.setItem(fila, 2, item_nombre)

            self.tabla.setItem(fila, 3, QTableWidgetItem(p.categoria.nombre if p.categoria else ""))

            cantidad_unidad = Decimal(str(p.cantidad_unidad)) if p.cantidad_unidad is not None else Decimal("0")
            item_cant = QTableWidgetItem(f"{float(cantidad_unidad):,.2f}")
            item_cant.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 4, item_cant)

            # Calcular cajas y unidades sueltas usando Decimal
            if p.cantidad_caja_total is not None and p.cantidad_caja_total > 0:
                cajas = int(p.cantidad_caja_total)
            elif p.cantidad_caja is not None and p.cantidad_caja > 0 and cantidad_unidad > 0:
                cajas = int(cantidad_unidad // Decimal(str(p.cantidad_caja)))
            else:
                cajas = 0

            if p.cantidad_caja_unidad is not None and p.cantidad_caja_unidad > 0:
                unidades_sueltas = int(p.cantidad_caja_unidad)
            elif p.cantidad_caja is not None and p.cantidad_caja > 0 and cantidad_unidad > 0:
                unidades_sueltas = int(cantidad_unidad % Decimal(str(p.cantidad_caja)))
            else:
                unidades_sueltas = int(cantidad_unidad)

            item_cajas = QTableWidgetItem(str(cajas))
            item_cajas.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 5, item_cajas)

            item_unidades_sueltas = QTableWidgetItem(str(unidades_sueltas))
            item_unidades_sueltas.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 6, item_unidades_sueltas)

            costo_producto = Decimal(str(p.costo_producto)) if p.costo_producto is not None else Decimal("0")
            item_costo = QTableWidgetItem(f"${float(costo_producto):,.2f}")
            item_costo.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 7, item_costo)

            precio_venta = precios.get(p.id_producto, {}).get("precio_1")
            item_precio = QTableWidgetItem(f"${precio_venta:,.2f}" if precio_venta is not None else "Sin precio")
            item_precio.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 8, item_precio)

            precio_2 = precios.get(p.id_producto, {}).get("precio_2")
            item_precio_2 = QTableWidgetItem(f"${precio_2:,.2f}" if precio_2 is not None and precio_2 > 0 else "-")
            item_precio_2.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 9, item_precio_2)

            precio_3 = precios.get(p.id_producto, {}).get("precio_3")
            item_precio_3 = QTableWidgetItem(f"${precio_3:,.2f}" if precio_3 is not None and precio_3 > 0 else "-")
            item_precio_3.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 10, item_precio_3)

            estado_producto = p.estado_producto or "ACTIVO"
            color_estado = COLOR_SUCCESS if estado_producto.upper() == "ACTIVO" else COLOR_DANGER
            badge = EstadoBadge(estado_producto.capitalize(), color_estado)
            self.tabla.setCellWidget(fila, 11, badge)

        total = resultado["total"]
        # pagina y total_paginas vienen ya corregidos por el servicio (paginar()).
        self.paginacion.actualizar_desde(resultado)

        self.lbl_total.setText(f"{total} producto{'s' if total != 1 else ''}")
        # Reafirmar las columnas visibles: si "Limpiar filtros" destildo el checkbox con las senales
        # bloqueadas, la proxima carga igual deja la tabla en el modo correcto.
        self._alternar_modo_conciliacion()

    def _fila_seleccionada_id(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            MessageBox.information(self, "Selección requerida", "Selecciona un producto de la lista.")
            return None
        item = self.tabla.item(filas[0].row(), 0)
        if item is None:
            MessageBox.information(
                self,
                "Error de selección",
                "No se pudo obtener el ID del producto seleccionado.",
            )
            return None
        return int(item.text())

    def nuevo_producto(self) -> None:
        if not self._exigir_permiso("crear", "No tienes permiso para crear productos."):
            return
        self.cargar_async(
            "form_producto",
            _tarea_form_producto,
            self._abrir_nuevo_producto,
            texto_error="No se pudo abrir el formulario de producto.",
            texto_sin_permiso="No tienes permiso para crear productos.",
            session_factory=self.session_factory,
            id_usuario=self.usuario.id_usuario,
        )

    def _abrir_nuevo_producto(self, datos_previos: dict) -> None:
        session = datos_previos["session"]
        try:
            dialogo = ProductoFormDialog(
                session, self.usuario.id_usuario, parent=self, precargado=datos_previos["precargado"]
            )
            if dialogo.exec():
                datos = dialogo.get_data()
                datos["creado_por"] = self.usuario.id_usuario
                producto = ProductoService.crear(session, **datos)
                precio_1, precio_2, precio_3 = dialogo.get_precios()
                if precio_1 > 0:
                    PrecioService.establecer_precio(
                        session,
                        producto.id_producto,
                        precio_1,
                        precio_2,
                        precio_3,
                        id_usuario=self.usuario.id_usuario,
                    )
                self._cargar_categorias_filtro()
                self.cargar_productos()
        except IntegrityError:
            session.rollback()
            MessageBox.warning(self, "Dato duplicado", "El código de producto ya está registrado.")
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, "Error de validación", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para crear productos.")
        finally:
            session.close()

    def abrir_auditoria(self) -> None:
        """Abre el diálogo de auditoría de productos."""
        session = self.session_factory()
        try:
            dialogo = ProductoAuditoriaDialog(session, self.usuario, None, parent=self)
            dialogo.exec()
        except Exception as exc:
            logger.exception("Error al abrir auditoría de productos")
            MessageBox.critical(self, "Error", f"No se pudo abrir la auditoría: {str(exc)}")
        finally:
            session.close()

    def editar_producto(self) -> None:
        if not self._exigir_permiso("editar", "No tienes permiso para editar productos."):
            return
        id_producto = self._fila_seleccionada_id()
        if id_producto is None:
            return

        self.cargar_async(
            "form_producto",
            _tarea_form_producto,
            self._abrir_editar_producto,
            texto_error="No se pudo abrir el formulario de producto.",
            texto_sin_permiso="No tienes permiso para editar productos.",
            session_factory=self.session_factory,
            id_usuario=self.usuario.id_usuario,
            id_producto=id_producto,
        )

    def _abrir_editar_producto(self, datos_previos: dict) -> None:
        session = datos_previos["session"]
        producto = datos_previos["producto"]
        try:
            if producto is None:
                MessageBox.warning(self, "No encontrado", "El producto seleccionado ya no existe.")
                return
            id_producto = producto.id_producto
            cantidad_anterior = producto.cantidad_unidad
            dialogo = ProductoFormDialog(
                session, self.usuario.id_usuario, producto, parent=self, precargado=datos_previos["precargado"]
            )
            if dialogo.exec():
                datos = dialogo.get_data()
                cantidad_nueva = datos.get("cantidad_unidad", cantidad_anterior)

                # Si cambió la cantidad de stock, pedir motivo
                motivo = None
                if cantidad_anterior != cantidad_nueva:
                    from app.ui.motivo_stock_dialog import MotivoStockDialog

                    motivo_dialogo = MotivoStockDialog(
                        producto.nombre_producto or "Producto desconocido",
                        float(cantidad_anterior) if cantidad_anterior else 0,
                        float(cantidad_nueva) if cantidad_nueva else 0,
                        parent=self,
                    )
                    if motivo_dialogo.exec():
                        motivo = motivo_dialogo.get_motivo()
                    else:
                        # Usuario canceló, no actualizar
                        return
                else:
                    # Sin cambio de stock no se manda cantidad_unidad: el valor del formulario
                    # es el de cuando se abrio, y reescribirlo pisaria las ventas/recepciones
                    # que entraron mientras tanto desde otra estacion.
                    datos.pop("cantidad_unidad", None)

                ProductoService.actualizar(
                    session,
                    id_producto,
                    id_usuario=self.usuario.id_usuario,
                    motivo=motivo,
                    cantidad_unidad_anterior=cantidad_anterior,
                    **datos,
                )
                precio_1, precio_2, precio_3 = dialogo.get_precios()
                if precio_1 > 0:
                    PrecioService.establecer_precio(
                        session,
                        id_producto,
                        precio_1,
                        precio_2,
                        precio_3,
                        id_usuario=self.usuario.id_usuario,
                    )
                self._cargar_categorias_filtro()
                self.cargar_productos()
        except IntegrityError:
            session.rollback()
            MessageBox.warning(self, "Dato duplicado", "El código de producto ya está registrado.")
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para editar productos.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al editar producto")
            MessageBox.critical(self, "Error", "No se pudo guardar los cambios del producto.")
        finally:
            session.close()

    def cambiar_estado_producto_seleccionado(self) -> None:
        if not self._exigir_permiso("eliminar", "No tienes permiso para cambiar el estado de productos."):
            return
        id_producto = self._fila_seleccionada_id()
        if id_producto is None:
            return

        session = self.session_factory()
        try:
            producto = session.get(Inventario, id_producto)
            estado_actual = producto.estado_producto or "ACTIVO"
            nuevo_estado = "INACTIVO" if estado_actual == "ACTIVO" else "ACTIVO"

            respuesta = MessageBox.question(
                self,
                "Confirmar",
                f"¿Cambiar el estado del producto '{producto.nombre_producto}' a {nuevo_estado}?",
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return

            ProductoService.cambiar_estado(session, id_producto, nuevo_estado, id_usuario=self.usuario.id_usuario)
            self.cargar_productos()
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(
                self,
                "Sin permiso",
                "No tienes permiso para cambiar el estado de productos.",
            )
        except Exception:
            session.rollback()
            logger.exception("Fallo al cambiar el estado del producto %s", id_producto)
            MessageBox.critical(self, "Error", "No se pudo cambiar el estado del producto.")
        finally:
            session.close()

    def _filtros_actuales_exportar(self) -> dict:
        return {
            "texto": self.buscar_input.text().strip() or None,
            "id_categoria": self.categoria_filtro_combo.currentData(),
            "solo_con_stock": self.solo_stock_check.isChecked(),
            "id_usuario": self.usuario.id_usuario,
            "conciliar": self.conciliar_check.isChecked(),
        }

    def exportar_excel_productos(self) -> None:
        if getattr(self, "_worker_export", None) is not None and self._worker_export.isRunning():
            return
        # R-09: se pide el destino ANTES de generar el archivo -- se escribe directo ahi,
        # nunca a un temporal.
        nombre = "inventario_fisico" if self.conciliar_check.isChecked() else "inventario"
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar inventario", f"{nombre}.xlsx", "Excel (*.xlsx)")
        if not ruta:
            return

        ocupar_boton(self.btn_exportar)
        self._worker_export = QueryWorker(
            self.session_factory,
            _tarea_exportar_productos_excel,
            ruta=ruta,
            **self._filtros_actuales_exportar(),
        )
        self._worker_export.resultado.connect(self._on_exportar_ok)
        self._worker_export.error.connect(self._on_exportar_error)
        self._worker_export.start()

    def exportar_pdf_productos(self) -> None:
        if getattr(self, "_worker_export", None) is not None and self._worker_export.isRunning():
            return
        nombre = "inventario_fisico" if self.conciliar_check.isChecked() else "inventario"
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar inventario", f"{nombre}.pdf", "PDF (*.pdf)")
        if not ruta:
            return

        ocupar_boton(self.btn_exportar)
        self._worker_export = QueryWorker(
            self.session_factory,
            _tarea_exportar_productos_pdf,
            ruta=ruta,
            **self._filtros_actuales_exportar(),
        )
        self._worker_export.resultado.connect(self._on_exportar_ok)
        self._worker_export.error.connect(self._on_exportar_error)
        self._worker_export.start()

    def _on_exportar_ok(self, resultado: tuple[str, int]) -> None:
        liberar_boton(self.btn_exportar)
        ruta, cantidad = resultado
        MessageBox.information(
            self,
            "Exportación completa",
            f"Se exportaron {cantidad} productos a:\n{ruta}",
        )

    def _on_exportar_error(self, mensaje: str) -> None:
        liberar_boton(self.btn_exportar)
        logger.error("Fallo al exportar el catálogo de inventario: %s", mensaje)
        MessageBox.critical(self, "Error", "No se pudo exportar el catálogo de inventario.")
