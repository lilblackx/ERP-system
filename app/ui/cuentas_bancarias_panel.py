import logging
from collections.abc import Callable

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (  # type: ignore
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import IntegrityError

from app.db.models import Banco, BancoMovimiento, ControlDeTasa, CuentaBancaria, Usuario
from app.services.cuentas_bancarias import CuentaBancariaService
from app.services.exportacion import exportar_excel, exportar_pdf
from app.services.moneda_cuentas import MONEDAS_CUENTA, etiqueta_moneda, nombre_moneda
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import BancoService, _enmascarar_numero_cuenta
from app.ui.animaciones import liberar_boton, ocupar_boton
from app.ui.auto_refresco import AutoRefresco
from app.ui.carga_asincrona import CargaAsincronaMixin, sesion_para_dialogo
from app.ui.conciliacion_bancos_dialog import ConciliacionBancosDialog
from app.ui.cuenta_bancaria_form_dialog import CuentaBancariaFormDialog
from app.ui.message_box import MessageBox
from app.ui.movimientos_cuenta_dialog import MovimientosCuentaDialog
from app.ui.paginacion import ControlPaginacion, MixinPaginacion
from app.ui.permisos_ui import MixinPermisos
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_SUCCESS,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MUTED,
    SEARCH_QSS,
    TABLE_QSS,
    EstadoBadge,
    alinear_encabezados,
    aplicar_fondo_panel,
    aplicar_sombra,
    dar_ancho_a_texto,
    estilizar_tarjeta,
)
from app.ui.toolbar_popups import BotonExportar, BotonFiltros
from app.ui.workers import QueryWorker

logger = logging.getLogger(__name__)

ESTADOS_VALIDOS = {"ACTIVO", "INACTIVO"}
COLS_VISIBLES = [
    "ID",
    "BANCO",
    "NÚMERO DE CUENTA",
    "TIPO",
    "MONEDA",
    "TITULAR",
    "IDENTIFICACIÓN",
    "SALDO",
    "MONTO EN BS",
    "SALDO COP",
    "ESTADO",
]

ESTADOS_FILTRO = [
    ("Todos los estados", None),
    ("Activos", "ACTIVO"),
    ("Inactivos", "INACTIVO"),
]

COLORES_ESTADO_CUENTA = {
    "ACTIVO": COLOR_SUCCESS,
    "INACTIVO": "#dc3545",  # Rojo para estado inactivo
}


# Columnas de saldo que no aplican a la moneda filtrada: una cuenta en dolares no tiene monto en Bs y una en
# pesos no tiene ni saldo en USD ni monto en Bs. Las cuentas en bolivares si muestran las dos: el saldo en Bs y
# su equivalente en USD (calculado al crearla, Bs / tasa). Con "Todas las monedas" (o COP) se ven las dos.
_COLUMNAS_OCULTAS_POR_MONEDA = {
    "VES": {"SALDO COP"},
    "USD": {"MONTO EN BS", "SALDO COP"},
    "COP": {"SALDO", "MONTO EN BS"},
}
COL_SALDO_USD = "SALDO"
COL_MONTO_BS = "MONTO EN BS"


def _indices_columnas_visibles(moneda: str | None) -> list[int]:
    ocultas = _COLUMNAS_OCULTAS_POR_MONEDA.get(moneda or "", set())
    return [i for i, nombre in enumerate(COLS_VISIBLES) if nombre not in ocultas]


def _filas_cuentas_bancarias_query(
    session, texto_busqueda, estado_cuenta, id_banco, id_usuario, moneda=None
) -> list[list]:
    resultado = CuentaBancariaService.listar(
        session,
        texto_busqueda=texto_busqueda,
        estado_cuenta=estado_cuenta,
        id_banco=id_banco,
        id_usuario=id_usuario,
        moneda=moneda,
        pagina=1,
        por_pagina=1_000_000,
    )
    cuentas = resultado["items"]

    return [
        [
            cuenta.id_cuenta,
            cuenta.banco.nombre_banco if cuenta.banco else None,
            _enmascarar_numero_cuenta(cuenta.numero_cuenta),
            cuenta.tipo_cuenta_banco,
            cuenta.moneda or "VES",
            cuenta.nombre_titular,
            cuenta.identificacion_titular,
            float(cuenta.saldo_total_banco or 0),
            float(cuenta.saldo_total_banco_bs or 0),
            float(cuenta.saldo_total_banco_cop or 0),
            cuenta.estado_cuenta,
        ]
        for cuenta in cuentas
    ]


def _tarea_exportar_cuentas_bancarias_excel(
    session, ruta: str, texto_busqueda, estado_cuenta, id_banco, id_usuario, moneda=None
) -> tuple[str, int]:
    """Corre en un QThread aparte (QueryWorker) -- consultar y volcar la lista completa
    de cuentas bancarias a un archivo (openpyxl) es lo bastante lento como para
    congelar la ventana si se hace en el hilo de GUI."""
    filas = _filas_cuentas_bancarias_query(session, texto_busqueda, estado_cuenta, id_banco, id_usuario, moneda)
    indices = _indices_columnas_visibles(moneda)
    exportar_excel(ruta, [COLS_VISIBLES[i] for i in indices], [[fila[i] for i in indices] for fila in filas])
    return ruta, len(filas)


def _tarea_exportar_cuentas_bancarias_pdf(
    session,
    ruta: str,
    texto_busqueda,
    estado_cuenta,
    id_banco,
    id_usuario,
    filtros,
    col_widths,
    moneda=None,
) -> tuple[str, int]:
    filas = _filas_cuentas_bancarias_query(session, texto_busqueda, estado_cuenta, id_banco, id_usuario, moneda)
    indices = _indices_columnas_visibles(moneda)
    exportar_pdf(
        ruta,
        "Reporte de Cuentas Bancarias",
        [COLS_VISIBLES[i] for i in indices],
        [[fila[i] for i in indices] for fila in filas],
        filtros=filtros,
        col_widths=[col_widths[i] for i in indices],
    )
    return ruta, len(filas)


def _tarea_listar_cuentas_bancarias(session, **filtros):
    """Corre en un hilo aparte (ver carga_asincrona.py): solo consulta, sin tocar widgets."""
    return CuentaBancariaService.listar(session, **filtros)


def _tarea_form_cuenta(session, session_factory, id_cuenta: int | None = None) -> dict:
    """Corre en un hilo aparte (ver carga_asincrona.py): bancos activos (y, al editar, la cuenta y si tiene
    movimientos) para el formulario. Devuelve la sesion usada, que el panel usa para guardar y cierra al terminar."""
    sesion = sesion_para_dialogo(session_factory)
    try:
        bancos = sesion.query(Banco).filter(Banco.estado_banco == "ACTIVO").order_by(Banco.nombre_banco).all()
        tasa = sesion.query(ControlDeTasa).order_by(ControlDeTasa.fecha_tasa.desc()).first()
        precargado = {"bancos": bancos, "tasa": tasa.tasa_dolar_bcv if tasa is not None else None}
        cuenta = None
        if id_cuenta is not None:
            cuenta = sesion.query(CuentaBancaria).filter(CuentaBancaria.id_cuenta == id_cuenta).first()
            if cuenta is not None:
                precargado["tiene_movimientos"] = (
                    sesion.query(BancoMovimiento.id_movimiento).filter(BancoMovimiento.id_cuenta == id_cuenta).first()
                    is not None
                )
        return {"session": sesion, "cuenta": cuenta, "precargado": precargado}
    except BaseException:
        sesion.close()
        raise


class CuentasBancariasPanel(CargaAsincronaMixin, MixinPermisos, MixinPaginacion, QWidget):
    """Panel de gestión de cuentas bancarias."""

    recurso_permisos = "bancos"

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self._cuentas = []
        self._por_pagina = 20
        self._total_registros = 0
        self._filtro_estado = None
        self._filtro_banco = None
        self._filtro_moneda = None
        self._texto_busqueda = ""

        self._setup_ui()
        self._cargar_bancos()
        self._cargar_datos()

        # Saldos al dia cada 30 s, en un hilo aparte y sin perder la cuenta seleccionada ni el scroll (ver
        # app/ui/auto_refresco.py: solo corre si el panel se ve y no hay un dialogo abierto).
        self._auto_refresco = AutoRefresco(self, self._refresco_periodico, lambda: self.table, 0, asincrono=True)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # ── Header ── (mismo patrón que bancos_panel.py/vendedores_panel.py: título +
        # badge de conteo -- el encabezado con ícono en caja azul es el patrón de
        # DIALOG_STYLE de un QDialog, ver GUIA_ESTILO_UI.md §7, no el de un panel).
        header = QWidget()
        header.setStyleSheet("background: transparent;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)

        lbl_titulo = QLabel("Cuentas Bancarias")
        lbl_titulo.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        self.lbl_total = QLabel("Cargando…")
        self.lbl_total.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 13px;"
            f" background-color: {COLOR_TABLE_HEADER}; border-radius: 10px;"
            " padding: 3px 10px;"
        )

        header_layout.addWidget(lbl_titulo)
        header_layout.addWidget(self.lbl_total)
        header_layout.addStretch()
        layout.addWidget(header)

        # ── Toolbar ── (GUIA_ESTILO_UI.md §3.4: Buscar — stretch — Nuevo X — Filtrar —
        # Exportar; banco+estado agrupados en un solo BotonFiltros, no dropdowns sueltos)
        toolbar = QWidget()
        estilizar_tarjeta(toolbar, padding=4, radio=8)
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 8, 12, 8)
        toolbar_layout.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar por número, titular o identificación…")
        self.search_input.addAction(
            qta.icon("fa5s.search", color=COLOR_TEXT_LIGHT),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.search_input.setObjectName("SearchInput")
        self.search_input.setStyleSheet(SEARCH_QSS)
        self.search_input.setFixedWidth(280)
        self.search_input.textChanged.connect(self._on_busqueda_cambiada)
        toolbar_layout.addWidget(self.search_input)
        toolbar_layout.addStretch()

        btn_nuevo = QPushButton("Nueva cuenta")
        btn_nuevo.setIcon(qta.icon("fa5s.plus", color="#FFFFFF"))
        btn_nuevo.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_nuevo.clicked.connect(self._on_nueva_cuenta)
        if self._puede("crear"):
            toolbar_layout.addWidget(btn_nuevo)

        # Filtros (banco + estado) agrupados detras de "Filtrar" -- GUIA_ESTILO_UI.md §3.3,
        # ningun dropdown suelto en la barra, ni siquiera uno solo.
        self.banco_combo = QComboBox()
        self.banco_combo.addItem("Todos los bancos")
        self.banco_combo.currentIndexChanged.connect(self._on_banco_cambiado)

        self.estado_combo = QComboBox()
        for etiqueta, valor in ESTADOS_FILTRO:
            self.estado_combo.addItem(etiqueta, valor)
        self.estado_combo.currentIndexChanged.connect(self._on_estado_cambiado)

        self.moneda_combo = QComboBox()
        self.moneda_combo.addItem("Todas las monedas", None)
        for moneda in MONEDAS_CUENTA:
            self.moneda_combo.addItem(etiqueta_moneda(moneda), moneda)
        self.moneda_combo.currentIndexChanged.connect(self._on_moneda_cambiada)

        self.btn_filtrar = BotonFiltros(
            [("Banco", self.banco_combo), ("Moneda", self.moneda_combo), ("Estado", self.estado_combo)]
        )
        toolbar_layout.addWidget(self.btn_filtrar)

        self.btn_exportar = BotonExportar(on_excel=self._exportar_excel, on_pdf=self._exportar_pdf)
        toolbar_layout.addWidget(self.btn_exportar)

        layout.addWidget(toolbar)

        # ── Tabla ── (GUIA_ESTILO_UI.md §5: setup estandar)
        self.table = QTableWidget(0, len(COLS_VISIBLES))
        self.table.setHorizontalHeaderLabels(COLS_VISIBLES)
        alinear_encabezados(
            self.table,
            {
                1: Qt.AlignmentFlag.AlignLeft,
                2: Qt.AlignmentFlag.AlignLeft,
                3: Qt.AlignmentFlag.AlignLeft,
                4: Qt.AlignmentFlag.AlignCenter,
                5: Qt.AlignmentFlag.AlignLeft,
                6: Qt.AlignmentFlag.AlignLeft,
                7: Qt.AlignmentFlag.AlignRight,
                8: Qt.AlignmentFlag.AlignRight,
                9: Qt.AlignmentFlag.AlignRight,
                10: Qt.AlignmentFlag.AlignCenter,
            },
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        dar_ancho_a_texto(self.table)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setStyleSheet(TABLE_QSS)
        aplicar_sombra(self.table)
        self.table.verticalHeader().setDefaultSectionSize(45)
        layout.addWidget(self.table, stretch=1)

        # ── Footer ──
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(12)

        self.lbl_paginacion = QLabel("Mostrando 0 de 0 registros")
        self.lbl_paginacion.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 13px;")
        footer_layout.addWidget(self.lbl_paginacion)

        # Antes: botones propios y "Página N" sin el total de paginas. Ahora el control central.
        self.paginacion = ControlPaginacion()
        self.paginacion.pagina_cambiada.connect(lambda _pagina: self._cargar_datos())
        footer_layout.addWidget(self.paginacion)

        footer_layout.addStretch()

        # Botones de acción
        btn_conciliacion = QPushButton("Conciliación de bancos")
        btn_conciliacion.setIcon(qta.icon("fa5s.balance-scale", color=COLOR_TEXT_DARK))
        btn_conciliacion.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_conciliacion.clicked.connect(self._on_conciliacion)
        if self._puede("crear"):
            footer_layout.addWidget(btn_conciliacion)

        btn_ver_movimientos = QPushButton("Ver movimientos")
        btn_ver_movimientos.setIcon(qta.icon("fa5s.exchange-alt", color=COLOR_TEXT_DARK))
        btn_ver_movimientos.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_ver_movimientos.clicked.connect(self._on_ver_movimientos)
        footer_layout.addWidget(btn_ver_movimientos)

        btn_editar = QPushButton("Editar seleccionado")
        btn_editar.setIcon(qta.icon("fa5s.edit", color=COLOR_TEXT_DARK))
        btn_editar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_editar.clicked.connect(self._on_editar)
        if self._puede("editar"):
            footer_layout.addWidget(btn_editar)

        btn_cambiar_estado = QPushButton("Cambiar estado")
        btn_cambiar_estado.setIcon(qta.icon("fa5s.sync-alt", color=COLOR_TEXT_DARK))
        btn_cambiar_estado.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_cambiar_estado.clicked.connect(self._on_cambiar_estado)
        if self._puede("eliminar"):
            footer_layout.addWidget(btn_cambiar_estado)

        layout.addWidget(footer)

        # Sin esto el panel no fija su propio fondo y hereda el negro por defecto de Qt
        # en los pixeles que TABLE_QSS deja fuera del border-radius de la tabla (las
        # "esquinas negras" reportadas por el usuario, 2026-09-02) -- todos los demas
        # paneles del sistema (bancos_panel.py, vendedores_panel.py, etc.) ya lo hacen.
        aplicar_fondo_panel(self)

    def _cargar_bancos(self):
        """Carga la lista de bancos en el combo de filtro via BancoService (antes hacia
        session.query(Banco) directo, sin pasar por require_permiso -- mismo hallazgo de
        auditoria que bancos_panel.py, 2026-09-02)."""
        session = self.session_factory()
        try:
            bancos = BancoService.listar_bancos(session, id_usuario=self.usuario.id_usuario)
            self.banco_combo.clear()
            self.banco_combo.addItem("Todos los bancos")
            for banco in bancos:
                if banco.estado_banco == "ACTIVO":
                    self.banco_combo.addItem(f"{banco.nombre_banco} ({banco.codigo_banco})", banco.id_banco)
        except PermisoDenegadoError:
            pass
        finally:
            session.close()

    def _cargar_datos(
        self, silencioso: bool = False, sincrono: bool = False, al_terminar: Callable[[], None] | None = None
    ):
        """Pide las cuentas segun los filtros actuales en un hilo aparte (ver carga_asincrona.py)."""
        self.cargar_async(
            "cuentas",
            _tarea_listar_cuentas_bancarias,
            self._mostrar_cuentas,
            texto_error="No se pudo cargar la lista de cuentas bancarias.",
            texto_sin_permiso="No tienes permiso para consultar cuentas bancarias.",
            silencioso=silencioso,
            sincrono=sincrono,
            al_terminar=al_terminar,
            texto_busqueda=self._texto_busqueda or None,
            estado_cuenta=self._filtro_estado,
            id_banco=self._filtro_banco,
            moneda=self._filtro_moneda,
            id_usuario=self.usuario.id_usuario,
            pagina=self.pagina_actual,
            por_pagina=self._por_pagina,
        )

    def _mostrar_cuentas(self, resultado: dict) -> None:
        self._cuentas = resultado["items"]
        self._total_registros = resultado["total"]
        self.paginacion.actualizar_desde(resultado)
        self._actualizar_tabla()
        self._actualizar_paginacion()

    def _refresco_periodico(self, al_terminar: Callable[[], None]) -> None:
        # `al_terminar` vuelve a seleccionar la fila (por id) cuando la tabla ya se repueblo.
        self._cargar_datos(silencioso=True, al_terminar=al_terminar)

    def _actualizar_tabla(self):
        """Actualiza la tabla con las cuentas cargadas."""
        self.table.setRowCount(0)
        for row, cuenta in enumerate(self._cuentas):
            self.table.insertRow(row)

            self.table.setItem(row, 0, QTableWidgetItem(str(cuenta.id_cuenta)))
            self.table.setItem(
                row,
                1,
                QTableWidgetItem(cuenta.banco.nombre_banco if cuenta.banco else "N/A"),
            )
            self.table.setItem(
                row,
                2,
                QTableWidgetItem(_enmascarar_numero_cuenta(cuenta.numero_cuenta) or "N/A"),
            )
            self.table.setItem(row, 3, QTableWidgetItem(cuenta.tipo_cuenta_banco or "N/A"))
            item_moneda = QTableWidgetItem(cuenta.moneda or "VES")
            item_moneda.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 4, item_moneda)
            self.table.setItem(row, 5, QTableWidgetItem(cuenta.nombre_titular or "N/A"))
            self.table.setItem(row, 6, QTableWidgetItem(cuenta.identificacion_titular or "N/A"))
            item_saldo = QTableWidgetItem(f"${float(cuenta.saldo_total_banco):,.2f}")
            item_saldo.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 7, item_saldo)

            # Usar el saldo en BS directamente de la base de datos, no multiplicar por tasa
            saldo_bs = float(cuenta.saldo_total_banco_bs or 0)
            item_saldo_bs = QTableWidgetItem(f"{saldo_bs:,.2f}" if saldo_bs > 0 else "0.00")
            item_saldo_bs.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 8, item_saldo_bs)

            saldo_cop = float(cuenta.saldo_total_banco_cop or 0)
            item_saldo_cop = QTableWidgetItem(f"{saldo_cop:,.2f}")
            item_saldo_cop.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 9, item_saldo_cop)

            estado = cuenta.estado_cuenta or "N/A"
            color_estado = COLORES_ESTADO_CUENTA.get(estado, COLOR_TEXT_MUTED)
            estado_widget = EstadoBadge(estado, color_estado)
            self.table.setCellWidget(row, 10, estado_widget)

    def _actualizar_paginacion(self):
        """Actualiza los controles de paginación."""
        if self._total_registros == 0:
            self.lbl_paginacion.setText("Mostrando 0 de 0 registros")  # antes salia "1-0"
            return
        inicio = (self.pagina_actual - 1) * self._por_pagina + 1
        fin = min(inicio + self._por_pagina - 1, self._total_registros)
        self.lbl_paginacion.setText(f"Mostrando {inicio}-{fin} de {self._total_registros} registros")

    def _on_busqueda_cambiada(self, texto: str):
        """Maneja el cambio en el texto de búsqueda."""
        self._texto_busqueda = texto.strip()
        self.buscar_con_pausa(self._buscar_tecleando)

    def _buscar_tecleando(self):
        self.pagina_actual = 1
        self._cargar_datos(silencioso=True)  # no enciende la barra de carga

    def _on_banco_cambiado(self, index: int):
        """Maneja el cambio en el filtro de banco."""
        self._filtro_banco = self.banco_combo.currentData()
        self.pagina_actual = 1
        self._cargar_datos()

    def _on_moneda_cambiada(self, index: int):
        """Filtra por moneda y deja visibles solo las columnas de saldo que aplican a esa moneda."""
        self._filtro_moneda = self.moneda_combo.currentData()
        self._aplicar_columnas_por_moneda()
        self.pagina_actual = 1
        self._cargar_datos()

    def _aplicar_columnas_por_moneda(self) -> None:
        ocultas = _COLUMNAS_OCULTAS_POR_MONEDA.get(self._filtro_moneda or "", set())
        for indice, nombre in enumerate(COLS_VISIBLES):
            self.table.setColumnHidden(indice, nombre in ocultas)

    def _on_estado_cambiado(self, index: int):
        """Maneja el cambio en el filtro de estado."""
        self._filtro_estado = self.estado_combo.currentData()
        self.pagina_actual = 1
        self._cargar_datos()

    def _on_nueva_cuenta(self):
        """Abre el diálogo para crear una nueva cuenta bancaria."""
        if not self._exigir_permiso("crear", "No tienes permiso para crear cuentas bancarias."):
            return
        self.cargar_async(
            "form_cuenta",
            _tarea_form_cuenta,
            self._abrir_nueva_cuenta,
            texto_error="No se pudo abrir el formulario de cuenta bancaria.",
            texto_sin_permiso="No tienes permiso para crear cuentas bancarias.",
            session_factory=self.session_factory,
        )

    def _abrir_nueva_cuenta(self, datos_previos: dict):
        session = datos_previos["session"]
        try:
            dialog = CuentaBancariaFormDialog(session, parent=self, precargado=datos_previos["precargado"])
            if dialog.exec() == QDialog.DialogCode.Accepted:
                datos = dialog.get_data()
                datos["creado_por"] = self.usuario.id_usuario
                CuentaBancariaService.crear(session, **datos)
                self._cargar_datos()
        except IntegrityError:
            session.rollback()
            MessageBox.warning(
                self,
                "Dato inválido",
                "No se pudo guardar la cuenta bancaria: verifica el banco seleccionado.",
            )
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para crear cuentas bancarias.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al crear cuenta bancaria")
            MessageBox.critical(self, "Error", "No se pudo crear la cuenta bancaria.")
        finally:
            session.close()

    def _on_editar(self):
        """Abre el diálogo para editar la cuenta seleccionada."""
        if not self._exigir_permiso("editar", "No tienes permiso para editar cuentas bancarias."):
            return
        row = self.table.currentRow()
        if row < 0:
            MessageBox.information(self, "Selección requerida", "Selecciona una cuenta de la lista.")
            return

        item = self.table.item(row, 0)
        if item is None:
            return

        self.cargar_async(
            "form_cuenta",
            _tarea_form_cuenta,
            self._abrir_editar_cuenta,
            texto_error="No se pudo abrir el formulario de cuenta bancaria.",
            texto_sin_permiso="No tienes permiso para editar cuentas bancarias.",
            session_factory=self.session_factory,
            id_cuenta=int(item.text()),
        )

    def _abrir_editar_cuenta(self, datos_previos: dict):
        session = datos_previos["session"]
        cuenta = datos_previos["cuenta"]
        try:
            if cuenta is None:
                MessageBox.warning(self, "No encontrado", "La cuenta bancaria no existe.")
                return

            dialog = CuentaBancariaFormDialog(session, cuenta, parent=self, precargado=datos_previos["precargado"])
            if dialog.exec() == QDialog.DialogCode.Accepted:
                datos = dialog.get_data()
                confirmar_cambio_moneda = False
                if datos.get("moneda") != (cuenta.moneda or "VES"):
                    resumen = CuentaBancariaService.resumen_uso(session, cuenta.id_cuenta, self.usuario.id_usuario)
                    if resumen["movimientos"] > 0:
                        if not self._confirmar_cambio_de_moneda(cuenta, datos["moneda"], resumen):
                            return
                        confirmar_cambio_moneda = True
                CuentaBancariaService.actualizar(
                    session,
                    cuenta.id_cuenta,
                    id_usuario=self.usuario.id_usuario,
                    confirmar_cambio_moneda=confirmar_cambio_moneda,
                    **datos,
                )
                self._cargar_datos()
        except IntegrityError:
            session.rollback()
            MessageBox.warning(
                self,
                "Dato inválido",
                "No se pudo guardar la cuenta bancaria: verifica el banco seleccionado.",
            )
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError as exc:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", str(exc) or "No tienes permiso para editar cuentas bancarias.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al editar cuenta bancaria")
            MessageBox.critical(self, "Error", "No se pudo guardar los cambios de la cuenta bancaria.")
        finally:
            session.close()

    def _confirmar_cambio_de_moneda(self, cuenta, moneda_nueva: str, resumen: dict) -> bool:
        """Cambiar la moneda de una cuenta con historial no toca los movimientos, pero cambia que pagos futuros
        puede recibir: se muestra el uso que ha tenido para que quien lo hace lo decida con los datos a la vista."""
        etiquetas = {
            "zelle": "Zelle",
            "binance": "Binance",
            "transferencia": "transferencia",
            "punto_de_venta": "punto de venta",
            "pago_movil": "pago móvil",
            "efectivo": "efectivo",
        }
        por_metodo = ", ".join(
            f"{cantidad} por {etiquetas.get(metodo, metodo)}" for metodo, cantidad in resumen["por_metodo"].items()
        )
        detalle = f"\nPagos registrados: {por_metodo}." if por_metodo else ""
        texto = (
            f"La cuenta ...{(cuenta.numero_cuenta or '')[-4:]} tiene {resumen['movimientos']} movimiento(s) "
            f"y hoy es en {nombre_moneda(cuenta.moneda)}.{detalle}\n\n"
            f"Pasarla a {nombre_moneda(moneda_nueva)} no modifica el historial, pero desde ahora solo recibirá "
            "pagos en esa moneda (por ejemplo, Zelle y Binance solo a cuentas en dólares).\n\n"
            "El cambio queda registrado en la auditoría. ¿Confirmar?"
        )
        return MessageBox.question(self, "Cambiar la moneda de la cuenta", texto) == QMessageBox.StandardButton.Yes

    def _on_cambiar_estado(self):
        """Cambia el estado de la cuenta seleccionada."""
        if not self._exigir_permiso("eliminar", "No tienes permiso para cambiar el estado de cuentas bancarias."):
            return
        row = self.table.currentRow()
        if row < 0:
            MessageBox.information(self, "Selección requerida", "Selecciona una cuenta de la lista.")
            return

        item = self.table.item(row, 0)
        if item is None:
            return

        cuenta_id = int(item.text())
        cuenta = None
        session = self.session_factory()
        try:
            from app.db.models import CuentaBancaria

            cuenta = session.query(CuentaBancaria).filter(CuentaBancaria.id_cuenta == cuenta_id).first()
            if cuenta is None:
                MessageBox.warning(self, "No encontrado", "La cuenta bancaria no existe.")
                return

            nuevo_estado = "INACTIVO" if cuenta.estado_cuenta == "ACTIVO" else "ACTIVO"
            respuesta = MessageBox.question(
                self,
                "Confirmar",
                f"¿Cambiar el estado de la cuenta '{cuenta.numero_cuenta}' a {nuevo_estado}?",
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return

            CuentaBancariaService.cambiar_estado(
                session,
                cuenta.id_cuenta,
                nuevo_estado,
                id_usuario=self.usuario.id_usuario,
            )
            self._cargar_datos()
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(
                self,
                "Sin permiso",
                "No tienes permiso para cambiar el estado de cuentas bancarias.",
            )
        except Exception:
            session.rollback()
            cuenta_id_log = cuenta.id_cuenta if cuenta else cuenta_id
            logger.exception("Fallo al cambiar el estado de la cuenta bancaria %s", cuenta_id_log)
            MessageBox.critical(self, "Error", "No se pudo cambiar el estado de la cuenta bancaria.")
        finally:
            session.close()

    def _on_ver_movimientos(self):
        """Abre el diálogo para ver los movimientos de la cuenta seleccionada."""
        row = self.table.currentRow()
        if row < 0:
            MessageBox.information(
                self,
                "Selección requerida",
                "Selecciona una cuenta bancaria para ver sus movimientos.",
            )
            return

        cuenta = self._cuentas[row]
        session = self.session_factory()
        try:
            dialog = MovimientosCuentaDialog(session, cuenta, self.usuario, parent=self)
            dialog.exec()
            self._cargar_datos()
        except PermisoDenegadoError:
            MessageBox.warning(
                self,
                "Sin permiso",
                "No tienes permiso para consultar movimientos bancarios.",
            )
        except Exception:
            logger.exception(
                "Fallo al abrir los movimientos de la cuenta bancaria %s",
                cuenta.id_cuenta,
            )
            MessageBox.critical(self, "Error", "No se pudo abrir los movimientos de la cuenta.")
        finally:
            session.close()

    def _on_conciliacion(self):
        """Abre el diálogo de conciliación de bancos."""
        if not self._exigir_permiso("crear", "No tienes permiso para conciliar bancos."):
            return
        session = self.session_factory()
        try:
            dialog = ConciliacionBancosDialog(session, self.usuario, parent=self)
            dialog.exec()
            self._cargar_datos()
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para conciliar bancos.")
        except Exception:
            logger.exception("Fallo al abrir la conciliación de bancos")
            MessageBox.critical(self, "Error", "No se pudo abrir la conciliación de bancos.")
        finally:
            session.close()

    def _filtros_actuales_exportar(self) -> dict:
        return {
            "texto_busqueda": self._texto_busqueda or None,
            "estado_cuenta": self._filtro_estado,
            "id_banco": self._filtro_banco,
            "moneda": self._filtro_moneda,
            "id_usuario": self.usuario.id_usuario,
        }

    def _exportar_excel(self):
        if getattr(self, "_worker_export", None) is not None and self._worker_export.isRunning():
            return
        ruta, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar cuentas bancarias",
            "cuentas_bancarias.xlsx",
            "Excel (*.xlsx)",
        )
        if not ruta:
            return

        ocupar_boton(self.btn_exportar)
        self._worker_export = QueryWorker(
            self.session_factory,
            _tarea_exportar_cuentas_bancarias_excel,
            ruta=ruta,
            **self._filtros_actuales_exportar(),
        )
        self._worker_export.resultado.connect(self._on_exportar_ok)
        self._worker_export.error.connect(self._on_exportar_error)
        self._worker_export.start()

    def _exportar_pdf(self):
        if getattr(self, "_worker_export", None) is not None and self._worker_export.isRunning():
            return
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Exportar cuentas bancarias", "cuentas_bancarias.pdf", "PDF (*.pdf)"
        )
        if not ruta:
            return

        texto_busqueda = self.search_input.text().strip()
        filtros = {
            "Búsqueda": texto_busqueda if texto_busqueda else "Todos",
            "Banco": self.banco_combo.currentText(),
            "Moneda": self.moneda_combo.currentText(),
            "Estado": self.estado_combo.currentText(),
        }
        col_widths = [0.5, 1.5, 1.5, 1.0, 0.8, 1.5, 1.3, 1.0, 1.0, 1.0, 1.0]

        ocupar_boton(self.btn_exportar)
        self._worker_export = QueryWorker(
            self.session_factory,
            _tarea_exportar_cuentas_bancarias_pdf,
            ruta=ruta,
            filtros=filtros,
            col_widths=col_widths,
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
            f"Se exportaron {cantidad} cuentas bancarias a:\n{ruta}",
        )

    def _on_exportar_error(self, mensaje: str) -> None:
        liberar_boton(self.btn_exportar)
        logger.error("Fallo al exportar cuentas bancarias: %s", mensaje)
        MessageBox.critical(self, "Error", "No se pudo exportar la lista de cuentas bancarias.")

    def closeEvent(self, event):
        """Detiene el timer de auto-refresh cuando se cierra el panel."""
        self._auto_refresco.timer.stop()
        super().closeEvent(event)
