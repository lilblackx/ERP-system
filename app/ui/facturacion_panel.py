"""
Panel completo del módulo Facturación / Ventas.
Mismo patrón visual y de interacción que app/ui/clientes_panel.py e
app/ui/inventario_panel.py (paleta y tipografía de app/ui/styles.py): barra de
herramientas, tabla estilizada, paginación (ya provista por
VentaService.listar_facturas()) y exportación a Excel/PDF (R-10).
"""

import logging
from collections.abc import Callable

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
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

from app.db.models import Caja, FacturaVenta, NotaCreditoCliente, Usuario
from app.services.empresa import EmpresaService
from app.services.exportacion import exportar_excel, exportar_pdf
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import CajaService
from app.services.ventas import VentaService
from app.ui.animaciones import liberar_boton, ocupar_boton
from app.ui.auto_refresco import AutoRefresco
from app.ui.caja_apertura_dialog import CajaAperturaDialog
from app.ui.carga_asincrona import CargaAsincronaMixin
from app.ui.devolver_nota_credito_dialog import DevolverNotaCreditoDialog
from app.ui.factura_detalle_dialog import FacturaDetalleDialog, tarea_cargar_factura
from app.ui.factura_form_dialog import FacturaFormDialog
from app.ui.factura_pdf import imprimir_factura
from app.ui.filtros_catalogo import llenar_combo_vendedores, tarea_vendedores_para_filtro
from app.ui.message_box import MessageBox
from app.ui.paginacion import ControlPaginacion, MixinPaginacion
from app.ui.permisos_ui import MixinPermisos
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MUTED,
    COLORES_ESTADO_FACTURA,
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
from app.utils.caja_local import cajas_de_esta_estacion
from app.utils.impresora_local import obtener_impresora_local

logger = logging.getLogger(__name__)

COLS_VISIBLES = [
    "ID",
    "N° FACTURA",
    "CLIENTE",
    "VENDEDOR",
    "FECHA",
    "CONDICIÓN",
    "MÉTODO PAGO",
    "TOTAL",
    "ESTADO",
]
COL_ID_INTERNO = 0  # oculto
POR_PAGINA = 20


def _etiqueta_metodo_pago(valor: str | None) -> str:
    """ "mixto" es el sentinel que VentaService.listar_facturas() usa cuando una factura
    tuvo mas de una forma de pago con metodo distinto (ver PagoLineaDialog) -- se traduce
    aca para no mostrar el valor crudo en la tabla/exportacion. El resto de los valores
    (efectivo, transferencia, etc.) se muestran tal cual, sin mas cambios."""
    return "Mixto" if valor == "mixto" else (valor or "—")


def _imprimir_factura_en_predeterminada(session, id_factura: int, id_usuario: int | None) -> str | None:
    """Envia la factura a la impresora predeterminada configurada en Configuracion >
    Empresa. Devuelve el nombre de la impresora usada, o None si no hay ninguna
    configurada (no es un error: sin impresora no se imprime nada).

    Debe correr en el hilo de GUI, NO en un QThread/QueryWorker: QTextDocument.print_()
    sobre un QPrinter de un driver real (Windows) no es seguro fuera del hilo principal
    y fallaba sin imprimir nada -- ver FacturacionPanel._disparar_impresion_automatica.
    """
    config_empresa = EmpresaService.obtener_configuracion(session, id_usuario=id_usuario)
    nombre_impresora = obtener_impresora_local(config_empresa)
    if not config_empresa or not nombre_impresora:
        return None
    datos_factura = VentaService.obtener_factura(session, id_factura, id_usuario=id_usuario)
    imprimir_factura(datos_factura, config_empresa, nombre_impresora)
    return nombre_impresora


def _filas_facturas_query(
    session,
    texto_busqueda: str | None,
    estado: str | None,
    condicion_pago: str | None,
    id_usuario: int | None,
    id_vendedor: int | None = None,
) -> list[list]:
    # Paginado en chunks (en vez de por_pagina=1_000_000 de una sola vez): reduce el
    # pico de memoria -- cada página se convierte a listas simples y se descarta el
    # batch de objetos ORM antes de pedir el siguiente, en vez de mantener 1M filas
    # de FacturaVenta (con sus relaciones cliente/vendedor) vivas en memoria a la vez.
    TAMANO_PAGINA = 5_000
    filas: list[list] = []
    pagina = 1
    while True:
        resultado = VentaService.listar_facturas(
            session,
            texto_busqueda=texto_busqueda,
            estado=estado,
            condicion_pago=condicion_pago,
            id_vendedor=id_vendedor,
            pagina=pagina,
            por_pagina=TAMANO_PAGINA,
            id_usuario=id_usuario,
        )
        items = resultado["items"]
        if not items:
            break
        filas.extend(
            [
                f.id_factura,
                f.numero_factura,
                f.cliente.nombre_razon_social if f.cliente else None,
                f.vendedor.nombre_vendedor if f.vendedor else None,
                f.fecha_emision.strftime("%d/%m/%Y") if f.fecha_emision else None,
                "Contado" if f.condicion_pago == "contado" else "Crédito",
                ("N/A" if f.condicion_pago != "contado" else _etiqueta_metodo_pago(getattr(f, "metodo_pago", None))),
                float(f.total_a_cobrar),
                f.estado_visual,
            ]
            for f in items
        )
        if len(items) < TAMANO_PAGINA:
            break
        pagina += 1
    return filas


def _tarea_exportar_facturas_excel(
    session,
    ruta: str,
    texto_busqueda: str | None,
    estado: str | None,
    condicion_pago: str | None,
    id_usuario: int | None,
    id_vendedor: int | None = None,
) -> tuple[str, int]:
    """Corre en un QThread aparte (QueryWorker) -- consultar y volcar potencialmente
    miles de facturas a un archivo (openpyxl) es lo bastante lento como para congelar
    la ventana si se hace en el hilo de GUI."""
    filas = _filas_facturas_query(session, texto_busqueda, estado, condicion_pago, id_usuario, id_vendedor)
    exportar_excel(ruta, COLS_VISIBLES, filas)
    return ruta, len(filas)


def _tarea_exportar_facturas_pdf(
    session,
    ruta: str,
    texto_busqueda: str | None,
    estado: str | None,
    condicion_pago: str | None,
    id_usuario: int | None,
    id_vendedor: int | None = None,
) -> tuple[str, int]:
    filas = _filas_facturas_query(session, texto_busqueda, estado, condicion_pago, id_usuario, id_vendedor)
    exportar_pdf(ruta, "Facturas de Venta", COLS_VISIBLES, filas)
    return ruta, len(filas)


ESTADOS_FILTRO = [
    ("Todos los estados", None),
    ("Emitida", "EMITIDA"),
    ("Pagada", "PAGADA"),
    ("Parcial", "PARCIAL"),
    ("Vencida", "VENCIDA"),
    ("Anulada", "ANULADA"),
]
CONDICIONES_FILTRO = [
    ("Contado y crédito", None),
    ("Contado", "contado"),
    ("Crédito", "credito"),
]


def _tarea_estado_caja(session, id_usuario: int | None) -> dict:
    """Corre en un hilo aparte: la caja de ESTA estacion si tiene turno abierto (`None` si no). Si la consulta falla
    devuelve `fallo`: el badge se queda como estaba, sin un mensaje de error cada vez que se refresca."""
    try:
        cajas = CajaService.listar_cajas(session, id_usuario=id_usuario)
    except PermisoDenegadoError:
        cajas = []
    except Exception:
        logger.exception("Fallo al consultar el estado de la caja")
        return {"fallo": True}
    abiertas = cajas_de_esta_estacion([c for c in cajas if c.fecha_apertura is not None and c.fecha_cierre is None])
    return {"caja": abiertas[0] if abiertas else None}


def _tarea_cargar_facturas(session, id_carga: int, **filtros) -> dict:
    """Corre en un hilo aparte (QueryWorker): el listado de facturas no congela la ventana mientras se escribe en
    la busqueda. `id_carga` vuelve en el resultado para descartar lo que llega fuera de turno."""
    try:
        return {"id_carga": id_carga, "resultado": VentaService.listar_facturas(session, **filtros)}
    except PermisoDenegadoError:
        return {"id_carga": id_carga, "sin_permiso": True}


class FacturacionPanel(CargaAsincronaMixin, MixinPermisos, MixinPaginacion, QWidget):
    """Panel principal del módulo Facturación: listado de facturas con búsqueda por
    número, filtro por estado/condición de pago, paginación, emisión de nuevas
    facturas (carrito), ver detalle y anulación."""

    recurso_permisos = "ventas"

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self._verificando_caja = False
        # Guard anti-reentrancia para ver_detalle_factura() -- ver bancos_panel.py para
        # el motivo (hallazgo 3.3, auditoria 2026-09-05).
        self._abriendo_dialogo = False
        self._id_carga = 0
        self._al_terminar_carga: Callable[[], None] | None = None
        self._workers_carga: set[QueryWorker] = set()
        self.setObjectName("ContentArea")
        self._setup_ui()
        self._cargar_vendedores()
        QTimer.singleShot(100, self.cargar_facturas)
        # Facturas emitidas/anuladas/cobradas en otras estaciones y estado de caja, sin
        # salir y volver a entrar al modulo (ver app/ui/auto_refresco.py).
        self._auto_refresco = AutoRefresco(
            self, self._refresco_periodico, lambda: self.tabla, COL_ID_INTERNO, asincrono=True
        )

    def _cargar_vendedores(self) -> None:
        """Pide en un hilo aparte la lista de vendedores del combo de filtro (la ventana no espera a la base)."""
        self.cargar_async(
            "vendedores",
            tarea_vendedores_para_filtro,
            self._llenar_vendedores,
            texto_error="No se pudo cargar la lista de vendedores.",
            silencioso=True,
        )

    def _llenar_vendedores(self, vendedores: list) -> None:
        llenar_combo_vendedores(self.vendedor_combo, vendedores, self.usuario)

    def _refresco_periodico(self, al_terminar: Callable[[], None]) -> None:
        # En un hilo aparte (listado y estado de la caja): la ventana no se detiene mientras la base responde.
        # AutoRefresco vuelve a seleccionar la fila (por id) cuando la tabla ya esta repoblada (`al_terminar`).
        self.cargar_facturas(silencioso=True, al_terminar=al_terminar)
        self._refrescar_estado_caja()

    def _refrescar_estado_caja(self) -> None:
        """Actualiza el badge "Caja abierta"/"Sin caja abierta" sin detener la ventana (no ofrece abrir turno)."""
        self.cargar_async(
            "estado_caja",
            _tarea_estado_caja,
            self._mostrar_estado_caja,
            texto_error="No se pudo consultar el estado de la caja.",
            silencioso=True,
            id_usuario=self.usuario.id_usuario,
        )

    def _mostrar_estado_caja(self, datos: dict) -> None:
        if not datos.get("fallo"):
            self._actualizar_estado_caja(datos["caja"])

    def showEvent(self, event: QShowEvent) -> None:
        # Mismo problema que DashboardPanel (ver su showEvent): MainWindow
        # cachea el panel y lo reutiliza via QStackedWidget, asi que sin esto
        # volver a "Facturacion" desde otro modulo mostraba el listado viejo.
        super().showEvent(event)
        self.cargar_facturas()
        # Solo actualiza el badge "Caja abierta"/"Sin caja abierta" -- NO ofrece abrir
        # turno aca (ofrecer_apertura=False). Antes se lanzaba CajaAperturaDialog cada
        # vez que se entraba al modulo mientras no hubiera ninguna caja abierta: un
        # cajero sin rol ADMIN (que ya no puede abrir turnos, ver CajaService.
        # _require_admin) quedaba interrumpido por ese modal cada vez que volvia a la
        # pestana sin poder resolverlo el mismo -- solo cancelarlo (hallazgo #4 de la
        # auditoria de facturacion). El gate real sigue intacto: nueva_factura() pide
        # la apertura explicitamente (ofrecer_apertura=True) recien cuando hace falta
        # de verdad, no solo por navegar al modulo.
        self._refrescar_estado_caja()

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

        lbl = QLabel("Facturación de Ventas")
        lbl.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        self.lbl_total = QLabel("Cargando…")
        self.lbl_total.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 13px;"
            f" background-color: {COLOR_TABLE_HEADER}; border-radius: 10px;"
            " padding: 3px 10px;"
        )

        self.lbl_caja_estado = QLabel()
        self._actualizar_estado_caja(None)

        h.addWidget(lbl)
        h.addWidget(self.lbl_total)
        h.addWidget(self.lbl_caja_estado)
        h.addStretch()
        return w

    def _make_toolbar(self) -> QWidget:
        w = QWidget()
        estilizar_tarjeta(w, padding=4, radio=8)
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)

        # Barra de busqueda unica: matchea numero de factura, cliente o vendedor (ver
        # VentaService.listar_facturas(texto_busqueda=...)) -- antes eran dos cajas
        # separadas (N° factura / cliente) que se combinaban con AND, obligando a saber
        # en cual escribir cada dato.
        self.buscar_input = QLineEdit()
        self.buscar_input.setPlaceholderText("Buscar por N° de factura, cliente o vendedor…")
        self.buscar_input.addAction(
            qta.icon("fa5s.search", color=COLOR_TEXT_LIGHT),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.buscar_input.setObjectName("SearchInput")
        self.buscar_input.setStyleSheet(SEARCH_QSS)
        self.buscar_input.setFixedWidth(320)
        self.buscar_input.returnPressed.connect(self._buscar_desde_inicio)
        self.buscar_input.textChanged.connect(self._busqueda_dinamica)

        self.estado_combo = QComboBox()
        for etiqueta, valor in ESTADOS_FILTRO:
            self.estado_combo.addItem(etiqueta, valor)
        self.estado_combo.currentIndexChanged.connect(self._buscar_desde_inicio)

        self.condicion_combo = QComboBox()
        for etiqueta, valor in CONDICIONES_FILTRO:
            self.condicion_combo.addItem(etiqueta, valor)
        self.condicion_combo.currentIndexChanged.connect(self._buscar_desde_inicio)
        self.vendedor_combo = QComboBox()
        self.vendedor_combo.addItem("Todos los vendedores")
        self.vendedor_combo.currentIndexChanged.connect(self._buscar_desde_inicio)

        self.btn_filtrar = BotonFiltros(
            [
                ("Estado", self.estado_combo),
                ("Condición de pago", self.condicion_combo),
                ("Vendedor", self.vendedor_combo),
            ]
        )

        self.btn_nueva_factura = QPushButton("Nueva Factura")
        self.btn_nueva_factura.setIcon(qta.icon("fa5s.plus", color="white"))
        self.btn_nueva_factura.setStyleSheet(BUTTON_PRIMARY_QSS)
        self.btn_nueva_factura.clicked.connect(self.nueva_factura)

        self.btn_exportar = BotonExportar(on_excel=self.exportar_excel_facturas, on_pdf=self.exportar_pdf_facturas)

        h.addWidget(self.buscar_input)
        h.addSpacerItem(QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        if self._puede("crear"):
            h.addWidget(self.btn_nueva_factura)
        h.addWidget(self.btn_filtrar)
        h.addWidget(self.btn_exportar)
        return w

    def _make_table(self) -> QTableWidget:
        self.tabla = QTableWidget(0, len(COLS_VISIBLES))
        self.tabla.setHorizontalHeaderLabels(COLS_VISIBLES)
        alinear_encabezados(
            self.tabla,
            {
                1: Qt.AlignmentFlag.AlignLeft,
                2: Qt.AlignmentFlag.AlignLeft,
                3: Qt.AlignmentFlag.AlignLeft,
                4: Qt.AlignmentFlag.AlignLeft,
                5: Qt.AlignmentFlag.AlignLeft,
                6: Qt.AlignmentFlag.AlignCenter,
                7: Qt.AlignmentFlag.AlignRight,
                8: Qt.AlignmentFlag.AlignCenter,
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
        self.tabla.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)
        self.tabla.setColumnWidth(8, 110)
        self.tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(self.tabla)
        self.tabla.setColumnHidden(COL_ID_INTERNO, True)
        self.tabla.verticalHeader().setDefaultSectionSize(48)
        self.tabla.doubleClicked.connect(self.ver_detalle_factura)
        return self.tabla

    def _make_footer(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        self.paginacion = ControlPaginacion()
        self.paginacion.pagina_cambiada.connect(lambda _pagina: self.cargar_facturas())

        btn_detalle = QPushButton("Ver detalle")
        btn_detalle.setIcon(qta.icon("fa5s.eye", color=COLOR_TEXT_DARK))
        btn_detalle.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_detalle.clicked.connect(self.ver_detalle_factura)

        btn_anular = QPushButton("Anular factura")
        btn_anular.setIcon(qta.icon("fa5s.ban", color=COLOR_TEXT_DARK))
        btn_anular.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_anular.clicked.connect(self.anular_factura_seleccionada)

        h.addWidget(self.paginacion)
        h.addStretch()
        h.addWidget(btn_detalle)
        if self._puede("eliminar"):
            h.addWidget(btn_anular)
        return w

    # ── Timer para búsqueda dinámica (300 ms debounce) ────────────────────

    def _busqueda_dinamica(self) -> None:
        if not hasattr(self, "_timer_busqueda"):
            self._timer_busqueda = QTimer()
            self._timer_busqueda.setSingleShot(True)
            self._timer_busqueda.timeout.connect(self._buscar_desde_inicio)
        self._timer_busqueda.start(300)

    def _buscar_desde_inicio(self) -> None:
        self.pagina_actual = 1
        self.cargar_facturas(silencioso=True)  # busqueda mientras se escribe: no enciende la barra de carga

    # ── Lógica de datos ───────────────────────────────────────────────────

    def _filtros_listado(self) -> dict:
        return {
            "texto_busqueda": self.buscar_input.text().strip() or None,
            "estado": self.estado_combo.currentData(),
            "condicion_pago": self.condicion_combo.currentData(),
            "id_vendedor": self.vendedor_combo.currentData(),
            "pagina": self.pagina_actual,
            "por_pagina": POR_PAGINA,
            "id_usuario": self.usuario.id_usuario,
        }

    def cargar_facturas(
        self, silencioso: bool = False, sincrono: bool = False, al_terminar: Callable[[], None] | None = None
    ) -> None:
        """Carga la pagina de facturas. Por defecto en un hilo aparte: si el usuario sigue escribiendo, la
        respuesta anterior se descarta al llegar (`_id_carga`) y solo se pinta la de lo ultimo que se pidio.
        `al_terminar` se llama cuando la tabla ya esta repoblada (lo usa el refresco periodico para volver a
        seleccionar la fila); `sincrono=True` carga en el hilo de la interfaz."""
        if sincrono:
            self._cargar_facturas_sincrono()
            if al_terminar is not None:
                al_terminar()
            return
        self._id_carga += 1
        self._al_terminar_carga = al_terminar
        worker = QueryWorker(self.session_factory, _tarea_cargar_facturas, self._id_carga, **self._filtros_listado())
        worker.silencioso = silencioso
        worker.resultado.connect(self._on_facturas_cargadas)
        worker.error.connect(self._on_facturas_error)
        worker.finished.connect(lambda w=worker: self._workers_carga.discard(w))
        self._workers_carga.add(worker)  # referencia viva mientras corre (ver workers.py)
        worker.start()

    def _on_facturas_cargadas(self, respuesta: dict) -> None:
        if respuesta["id_carga"] != self._id_carga:
            return  # llego tarde: ya se pidio otro listado
        if respuesta.get("sin_permiso"):
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar facturas.")
            return
        self._poblar_tabla(respuesta["resultado"])
        al_terminar, self._al_terminar_carga = self._al_terminar_carga, None
        if al_terminar is not None:
            al_terminar()

    def _on_facturas_error(self, mensaje: str) -> None:
        # QueryWorker ya dejo el detalle en el log.
        MessageBox.critical(self, "Error de conexión", "No se pudo cargar el listado de facturas.")

    def _cargar_facturas_sincrono(self) -> None:
        # Invalida lo que haya en vuelo: si no, una respuesta anterior llegaria despues y pisaria esta.
        self._id_carga += 1
        session = self.session_factory()
        try:
            self._poblar_tabla(VentaService.listar_facturas(session, **self._filtros_listado()))
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar facturas.")
        except Exception:
            logger.exception("Fallo al cargar el listado de facturas")
            MessageBox.critical(self, "Error de conexión", "No se pudo cargar el listado de facturas.")
        finally:
            session.close()

    def closeEvent(self, event) -> None:
        for worker in list(self._workers_carga):
            worker.wait(2000)  # un hilo vivo al destruirse el panel haria caer el proceso
        super().closeEvent(event)

    def _poblar_tabla(self, resultado: dict) -> None:
        facturas: list[FacturaVenta] = resultado["items"]
        self.tabla.setRowCount(len(facturas))
        for fila, f in enumerate(facturas):
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(f.id_factura)))
            self.tabla.setItem(fila, 1, QTableWidgetItem(f.numero_factura))
            self.tabla.setItem(
                fila,
                2,
                QTableWidgetItem(f.cliente.nombre_razon_social if f.cliente else ""),
            )
            self.tabla.setItem(
                fila,
                3,
                QTableWidgetItem(f.vendedor.nombre_vendedor if f.vendedor else ""),
            )

            fecha = f.fecha_emision.strftime("%d/%m/%Y") if f.fecha_emision else ""
            self.tabla.setItem(fila, 4, QTableWidgetItem(fecha))

            condicion = "Contado" if f.condicion_pago == "contado" else "Crédito"
            self.tabla.setItem(fila, 5, QTableWidgetItem(condicion))

            # Método de pago
            metodo_pago = (
                "N/A" if f.condicion_pago != "contado" else _etiqueta_metodo_pago(getattr(f, "metodo_pago", None))
            )
            item_metodo = QTableWidgetItem(metodo_pago)
            item_metodo.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 6, item_metodo)

            # total_a_cobrar (descuento e IVA incluidos), no total_venta: ese es solo el
            # subtotal de las lineas y no coincide con lo que paga el cliente.
            item_total = QTableWidgetItem(f"${float(f.total_a_cobrar):,.2f}")
            item_total.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 7, item_total)

            estado_visual = getattr(f, "estado_visual", "EMITIDA") or "EMITIDA"
            color_estado = COLORES_ESTADO_FACTURA.get(estado_visual, COLOR_TEXT_MUTED)
            badge = EstadoBadge(estado_visual.capitalize(), color_estado)
            self.tabla.setCellWidget(fila, 8, badge)

        total = resultado["total"]
        # pagina y total_paginas vienen ya corregidos por el servicio (paginar()).
        self.paginacion.actualizar_desde(resultado)

        self.lbl_total.setText(f"{total} factura{'s' if total != 1 else ''}")

    def _fila_seleccionada_id(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            MessageBox.information(self, "Selección requerida", "Selecciona una factura de la lista.")
            return None
        item = self.tabla.item(filas[0].row(), 0)
        if item is None:
            MessageBox.warning(self, "Error", "No se pudo obtener el ID de la factura seleccionada.")
            return None
        return int(item.text())

    # ── Gate de caja (sin turno abierto no se puede facturar) ─────────────

    def _cajas_con_turno_abierto(self) -> list[Caja]:
        """La caja de ESTA estacion si tiene turno abierto (vacio si no). Las cajas que abrieron otras
        estaciones no cuentan: cada estacion factura de forma independiente."""
        session = self.session_factory()
        try:
            cajas = CajaService.listar_cajas(session, id_usuario=self.usuario.id_usuario)
        except PermisoDenegadoError:
            cajas = []
        finally:
            session.close()
        return cajas_de_esta_estacion([c for c in cajas if c.fecha_apertura is not None and c.fecha_cierre is None])

    def _actualizar_estado_caja(self, caja: Caja | None) -> None:
        if caja is not None:
            self.lbl_caja_estado.setText(f"Caja abierta: {caja.nombre_caja or caja.id_caja}")
            self.lbl_caja_estado.setStyleSheet(
                f"color: {COLOR_SUCCESS}; font-size: 13px; background-color: #DCFCE7;"
                " border-radius: 10px; padding: 3px 10px;"
            )
        else:
            self.lbl_caja_estado.setText("Sin caja abierta")
            self.lbl_caja_estado.setStyleSheet(
                f"color: {COLOR_DANGER}; font-size: 13px; background-color: #FEE2E2;"
                " border-radius: 10px; padding: 3px 10px;"
            )

    def _verificar_caja_abierta(self, ofrecer_apertura: bool = False) -> bool:
        """Sin ninguna caja con turno abierto no se puede facturar -- solo se puede
        seguir viendo el listado de facturas ya emitidas. Si ofrecer_apertura=True y no
        hay ninguna abierta, se lanza el gate de identificacion + apertura de turno
        (CajaAperturaDialog); si el usuario lo completa, se vuelve a verificar."""
        if self._verificando_caja:
            return bool(self._cajas_con_turno_abierto())
        self._verificando_caja = True
        try:
            abiertas = self._cajas_con_turno_abierto()
            if not abiertas and ofrecer_apertura:
                session = self.session_factory()
                try:
                    dialogo = CajaAperturaDialog(session, parent=self)
                    if dialogo.exec() == QDialog.DialogCode.Accepted and dialogo.caja_abierta is not None:
                        abiertas = self._cajas_con_turno_abierto()
                finally:
                    session.close()
            self._actualizar_estado_caja(abiertas[0] if abiertas else None)
            return bool(abiertas)
        finally:
            self._verificando_caja = False

    def nueva_factura(self) -> None:
        if not self._exigir_permiso("crear", "No tienes permiso para emitir facturas."):
            return
        if not self._verificar_caja_abierta(ofrecer_apertura=True):
            MessageBox.information(
                self,
                "Caja requerida",
                "Debe abrir el turno de una caja para poder emitir facturas.",
            )
            return

        self.btn_nueva_factura.setEnabled(False)
        session = self.session_factory()
        factura_emitida = None
        try:
            # FacturaFormDialog emite la factura el mismo adentro (ver
            # FacturaFormDialog._validar_y_aceptar/self.factura_emitida) -- si
            # VentaService.emitir_factura falla server-side, el dialogo se queda abierto
            # con el error mostrado y el carrito/formas de pago intactos, en vez de
            # cerrarse y perder todo lo cargado (hallazgo #3 de la auditoria de
            # facturacion). Aca solo queda reaccionar a un exec() exitoso.
            dialogo = FacturaFormDialog(
                session, self.usuario.id_usuario, parent=self, session_factory=self.session_factory
            )
            if dialogo.exec() and dialogo.factura_emitida is not None:
                factura_emitida = dialogo.factura_emitida
                # Solo id/numero: `factura_emitida` esta desligada de su sesion (ver
                # FacturaFormDialog.id_factura_emitida) y leer cualquiera de sus campos
                # lanzaba DetachedInstanceError -- la impresion nunca se disparaba.
                id_factura = dialogo.id_factura_emitida
                numero_factura = dialogo.numero_factura_emitida
                self.cargar_facturas()
                # La impresion se agenda en el hilo de GUI (no bloquea este mensaje) -- ver
                # _disparar_impresion_automatica.
                if id_factura is not None:
                    self._disparar_impresion_automatica(id_factura)
                MessageBox.information(
                    self,
                    "Factura emitida",
                    f"Factura {numero_factura} emitida con éxito.",
                )
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para emitir facturas.")
        except Exception:
            logger.exception("Fallo al procesar la emision de la factura")
            # Solo mostrar error si la factura no fue emitida exitosamente
            if factura_emitida is None:
                MessageBox.critical(self, "Error", "No se pudo emitir la factura.")
        finally:
            session.close()
            self.btn_nueva_factura.setEnabled(True)

    def _disparar_impresion_automatica(self, id_factura: int) -> None:
        """Agenda la impresion en el hilo de GUI (QTimer.singleShot(0)) para que corra
        en cuanto el bucle de eventos quede libre, sin bloquear el flujo de "Facturar".
        No se usa un QThread: imprimir via QPrinter con un driver real fuera del hilo
        principal fallaba sin imprimir. Si no hay impresora configurada, no hace nada."""
        QTimer.singleShot(0, lambda: self._imprimir_automaticamente(id_factura))

    def _imprimir_automaticamente(self, id_factura: int) -> None:
        session = self.session_factory()
        try:
            nombre_impresora = _imprimir_factura_en_predeterminada(session, id_factura, self.usuario.id_usuario)
        except Exception as exc:
            logger.exception("Fallo la impresion automatica de la factura %s", id_factura)
            detalle = f"\n\n{exc}" if isinstance(exc, ValueError) else ""
            MessageBox.warning(
                self,
                "No se pudo imprimir",
                "La factura se emitió correctamente, pero no se pudo enviar a la impresora "
                "predeterminada configurada. Puede imprimirla manualmente desde el detalle." + detalle,
            )
        else:
            if nombre_impresora:
                logger.info("Factura enviada automaticamente a la impresora '%s'", nombre_impresora)
        finally:
            session.close()

    def ver_detalle_factura(self) -> None:
        id_factura = self._fila_seleccionada_id()
        if id_factura is None:
            return
        if self._abriendo_dialogo:
            return
        self._abriendo_dialogo = True
        # La factura se consulta en un hilo aparte (ver carga_asincrona.py); el dialogo se abre al llegar.
        self.cargar_async(
            "detalle_factura",
            tarea_cargar_factura,
            self._abrir_detalle_factura,
            texto_error="No se pudo cargar el detalle de la factura.",
            session_factory=self.session_factory,
            id_factura=id_factura,
            id_usuario=self.usuario.id_usuario,
        )

    def _abrir_detalle_factura(self, cargado: dict) -> None:
        session = cargado.get("session")
        error = cargado.get("error")
        try:
            if isinstance(error, PermisoDenegadoError):
                MessageBox.warning(self, "Sin permiso", "No tienes permiso para ver el detalle de facturas.")
            elif isinstance(error, ValueError):
                MessageBox.warning(self, "No se pudo abrir la factura", str(error))
            elif error is not None:
                logger.error("Fallo al cargar el detalle de la factura", exc_info=error)
                MessageBox.critical(self, "Error", "No se pudo cargar el detalle de la factura.")
            else:
                FacturaDetalleDialog(cargado["datos"], session, self.usuario.id_usuario, parent=self).exec()
        except Exception:
            logger.exception("Fallo al abrir el detalle de la factura")
            MessageBox.critical(self, "Error", "No se pudo cargar el detalle de la factura.")
        finally:
            if session is not None:
                session.close()
            self._abriendo_dialogo = False

    def anular_factura_seleccionada(self) -> None:
        if not self._exigir_permiso("eliminar", "No tienes permiso para anular facturas."):
            return
        id_factura = self._fila_seleccionada_id()
        if id_factura is None:
            return

        motivo, ok = QInputDialog.getText(self, "Anular factura", "Motivo de la anulación:")
        motivo = motivo.strip()
        if not ok or not motivo:
            return

        respuesta = MessageBox.question(
            self,
            "Confirmar",
            "¿Anular esta factura? Se repondrá el stock vendido y no se puede deshacer.",
        )
        if respuesta != QMessageBox.StandardButton.Yes:
            return

        session = self.session_factory()
        id_factura_anulada = None
        try:
            factura = VentaService.anular_factura(
                session, id_factura, id_usuario=self.usuario.id_usuario, motivo=motivo
            )
            id_factura_anulada = factura.id_factura
            self.cargar_facturas()
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, "No se pudo anular la factura", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para anular facturas.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al anular la factura %s", id_factura)
            MessageBox.critical(self, "Error", "No se pudo anular la factura.")
        finally:
            session.close()

        # Fuera del try/finally de arriba (con su propia sesion) para no arriesgar que un
        # rollback/cierre de la sesion de la anulacion interfiera con esta consulta -- ver
        # comentario de _ofrecer_devolver_nota_credito.
        if id_factura_anulada is not None:
            self._ofrecer_devolver_nota_credito(id_factura_anulada)

    def _ofrecer_devolver_nota_credito(self, id_factura: int) -> None:
        """Seguimiento inmediato tras anular una factura de contado con pago aplicado:
        en vez de dejar al cajero que se entere de la nota de credito generada navegando
        a otro modulo (Clientes > Historial), se le ofrece devolverla en el momento. El
        proceso contable sigue siendo el mismo de 2 pasos (anular = reversion fiscal,
        devolver = operacion de tesoreria aparte, con su propia autorizacion) -- esto
        solo evita la navegacion, no salta ningun paso ni ninguna validacion."""
        session = self.session_factory()
        try:
            nota = session.query(NotaCreditoCliente).filter(NotaCreditoCliente.id_factura_origen == id_factura).first()
            if nota is None or nota.saldo_disponible <= 0:
                return

            respuesta = MessageBox.question(
                self,
                "Nota de crédito generada",
                f"Se generó la nota de crédito {nota.numero_nota_credito} por "
                f"${float(nota.saldo_disponible):,.2f}. ¿Deseas devolver el dinero al cliente ahora?",
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return

            dialogo = DevolverNotaCreditoDialog(session, self.usuario.id_usuario, [nota], parent=self)
            dialogo.exec()
        except Exception:
            logger.exception(
                "Fallo al ofrecer la devolucion de la nota de credito de la factura %s",
                id_factura,
            )
        finally:
            session.close()

    def _filtros_actuales_exportar(self) -> dict:
        return {
            "texto_busqueda": self.buscar_input.text().strip() or None,
            "estado": self.estado_combo.currentData(),
            "condicion_pago": self.condicion_combo.currentData(),
            "id_vendedor": self.vendedor_combo.currentData(),
            "id_usuario": self.usuario.id_usuario,
        }

    def exportar_excel_facturas(self) -> None:
        # Mismo guard que reportes_panel.py: reasignar self._worker_export a un QThread
        # nuevo mientras el viejo sigue corriendo lo destruye a mitad de ejecucion.
        if getattr(self, "_worker_export", None) is not None and self._worker_export.isRunning():
            return
        # R-09: se pide el destino ANTES de generar el archivo -- se escribe directo ahi,
        # nunca a un temporal.
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar facturas", "facturas.xlsx", "Excel (*.xlsx)")
        if not ruta:
            return

        ocupar_boton(self.btn_exportar)
        self._worker_export = QueryWorker(
            self.session_factory,
            _tarea_exportar_facturas_excel,
            ruta=ruta,
            **self._filtros_actuales_exportar(),
        )
        self._worker_export.resultado.connect(self._on_exportar_ok)
        self._worker_export.error.connect(self._on_exportar_error)
        self._worker_export.start()

    def exportar_pdf_facturas(self) -> None:
        if getattr(self, "_worker_export", None) is not None and self._worker_export.isRunning():
            return
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar facturas", "facturas.pdf", "PDF (*.pdf)")
        if not ruta:
            return

        ocupar_boton(self.btn_exportar)
        self._worker_export = QueryWorker(
            self.session_factory,
            _tarea_exportar_facturas_pdf,
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
            f"Se exportaron {cantidad} facturas a:\n{ruta}",
        )

    def _on_exportar_error(self, mensaje: str) -> None:
        liberar_boton(self.btn_exportar)
        logger.error("Fallo al exportar el listado de facturas: %s", mensaje)
        MessageBox.critical(self, "Error", "No se pudo exportar el listado de facturas.")
