"""
Panel del modulo Cuentas por Cobrar (CxC): analogo a app/ui/cuentas_por_pagar_panel.py,
mismo patron visual (paleta y tipografia de app/ui/styles.py) y misma relacion con su
modulo de origen -- las cuentas por cobrar se generan solas (trigger trg_factura_venta_cxc
al emitir una factura a credito o de contado, ver VentaService.emitir_factura), este panel
es puramente de consulta + cobro, no crea/edita cuentas por cobrar directamente.

PagoCobroDialog cobra en USD unicamente (sin conversion de moneda), mismo alcance que
PagoProveedorDialog en el modulo CxP -- PagoService.registrar_pago_cobro SI acepta
moneda/monto_moneda_origen como metadatos, pero la conversion real (_convertir_a_usd) hoy
solo la resuelve VentaService.emitir_factura con la tasa vigente en el momento de facturar;
agregarla aca duplicaria esa logica sin tests que la cubran. Cobrar una cuenta ya abierta
en VES/COP sigue siendo posible calculando el equivalente USD a mano antes de escribirlo
en el campo de monto.
"""

import logging

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
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
from sqlalchemy.orm import Session

from app.db.models import CuentaPorCobrar, Usuario
from app.services.pagos import PagoService
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import BancoService, CajaService
from app.ui.pago_linea_dialog import METODOS_PAGO, METODOS_QUE_REQUIEREN_CAJA
from app.ui.styles import (
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_FIELD_BG,
    COLOR_PRIMARY,
    COLOR_PRIMARY_DARK,
    COLOR_PRIMARY_LIGHT,
    COLOR_SUCCESS,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
    FONT_FAMILY,
    ICON_CHEVRON_DOWN_URL,
    ICON_CHEVRON_UP_URL,
    TABLE_QSS,
    EstadoBadge,
    aplicar_sombra,
)
from app.ui.toolbar_popups import BotonFiltros

logger = logging.getLogger(__name__)

POR_PAGINA = 20

COLORES_ESTADO_CXC = {
    "pendiente": COLOR_WARNING,
    "parcial": COLOR_PRIMARY,
    "pagada": COLOR_SUCCESS,
    "vencida": COLOR_DANGER,
}

ESTADOS_FILTRO = [
    ("Todos los estados", None),
    ("Pendiente", "pendiente"),
    ("Parcial", "parcial"),
    ("Vencida", "vencida"),
    ("Pagada", "pagada"),
]

DIALOG_STYLE = f"""
QDialog {{
    background-color: {COLOR_CONTENT_BG};
    font-family: '{FONT_FAMILY}', Arial, sans-serif;
}}
QWidget#SectionCard {{
    background-color: {COLOR_CARD_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
}}
QLabel.FormLabel {{
    font-size: 12px;
    font-weight: 600;
    color: #334155;
    margin-bottom: 2px;
}}
QLineEdit, QComboBox, QDoubleSpinBox {{
    background-color: #FFFFFF;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
    min-height: 20px;
}}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{
    border: 1.5px solid {COLOR_PRIMARY};
}}
QLineEdit:disabled, QComboBox:disabled, QDoubleSpinBox:disabled {{
    background-color: {COLOR_CONTENT_BG};
    color: {COLOR_TEXT_LIGHT};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox::down-arrow {{
    image: url({ICON_CHEVRON_DOWN_URL});
    width: 12px;
    height: 12px;
    margin-right: 6px;
}}
QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    border: none;
    border-left: 1px solid {COLOR_BORDER};
}}
QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    border: none;
    border-left: 1px solid {COLOR_BORDER};
}}
QDoubleSpinBox::up-arrow {{
    image: url({ICON_CHEVRON_UP_URL});
    width: 10px;
    height: 10px;
}}
QDoubleSpinBox::down-arrow {{
    image: url({ICON_CHEVRON_DOWN_URL});
    width: 10px;
    height: 10px;
}}
QPushButton#BtnPrimary {{
    background-color: {COLOR_PRIMARY};
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 8px 22px;
    font-size: 13px;
    font-weight: bold;
}}
QPushButton#BtnPrimary:hover {{
    background-color: {COLOR_PRIMARY_LIGHT};
}}
QPushButton#BtnPrimary:pressed {{
    background-color: {COLOR_PRIMARY_DARK};
}}
QPushButton#BtnSecondary {{
    background-color: {COLOR_FIELD_BG};
    color: #475569;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#BtnSecondary:hover {{
    background-color: {COLOR_TABLE_HEADER};
    color: {COLOR_TEXT_DARK};
}}
"""


class PagoCobroDialog(QDialog):
    """Un unico pago en USD contra el saldo_pendiente de una CuentaPorCobrar. Mismo patron
    de origen caja/cuenta que PagoProveedorDialog (app/ui/cuentas_por_pagar_panel.py)."""

    def __init__(self, session: Session, id_usuario: int | None, cuenta: CuentaPorCobrar, parent=None):
        super().__init__(parent)
        self.session = session
        self.id_usuario = id_usuario
        self.cuenta = cuenta
        self.pago_creado = None
        self._cajas_abiertas: list = []
        self._cuentas_activas: list = []

        self.setWindowTitle("Registrar Cobro")
        self.setFixedSize(420, 420)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._build_ui()
        self._cargar_origenes()
        self._toggle_origen()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        cliente = self.cuenta.factura.cliente if self.cuenta.factura else None
        lbl_titulo = QLabel(f"Cobrar a {cliente.nombre_razon_social if cliente else 'cliente'}")
        lbl_titulo.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        root.addWidget(lbl_titulo)

        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        numero_factura = self.cuenta.factura.numero_factura if self.cuenta.factura else ""
        lbl_factura = QLabel(f"Factura: {numero_factura}")
        lbl_factura.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        layout.addWidget(lbl_factura)

        lbl_saldo = QLabel(f"Saldo pendiente: ${float(self.cuenta.saldo_pendiente):,.2f}")
        lbl_saldo.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_MUTED};")
        layout.addWidget(lbl_saldo)

        lbl_metodo = QLabel("Método de Pago <span style='color: #DC2626;'>*</span>")
        lbl_metodo.setProperty("class", "FormLabel")
        self.metodo_combo = QComboBox()
        for etiqueta, valor in METODOS_PAGO:
            self.metodo_combo.addItem(etiqueta, valor)
        self.metodo_combo.setFixedHeight(32)
        self.metodo_combo.currentIndexChanged.connect(self._toggle_origen)
        layout.addWidget(lbl_metodo)
        layout.addWidget(self.metodo_combo)

        lbl_monto = QLabel("Monto (USD) <span style='color: #DC2626;'>*</span>")
        lbl_monto.setProperty("class", "FormLabel")
        self.monto_input = QDoubleSpinBox()
        self.monto_input.setRange(0.01, float(self.cuenta.saldo_pendiente))
        self.monto_input.setDecimals(2)
        self.monto_input.setPrefix("$ ")
        self.monto_input.setValue(float(self.cuenta.saldo_pendiente))
        self.monto_input.setFixedHeight(32)
        layout.addWidget(lbl_monto)
        layout.addWidget(self.monto_input)

        lbl_origen = QLabel("Origen <span style='color: #DC2626;'>*</span>")
        lbl_origen.setProperty("class", "FormLabel")
        self.origen_combo = QComboBox()
        self.origen_combo.setFixedHeight(32)
        layout.addWidget(lbl_origen)
        layout.addWidget(self.origen_combo)

        lbl_ref = QLabel("Referencia")
        lbl_ref.setProperty("class", "FormLabel")
        self.referencia_input = QLineEdit()
        self.referencia_input.setPlaceholderText("Opcional")
        self.referencia_input.setFixedHeight(32)
        layout.addWidget(lbl_ref)
        layout.addWidget(self.referencia_input)

        root.addWidget(card, stretch=1)

        footer = QHBoxLayout()
        footer.addStretch()
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setObjectName("BtnSecondary")
        btn_cancelar.setFixedHeight(34)
        btn_cancelar.setAutoDefault(False)
        btn_cancelar.clicked.connect(self.reject)
        self.btn_cobrar = QPushButton("Registrar Cobro")
        self.btn_cobrar.setObjectName("BtnPrimary")
        self.btn_cobrar.setFixedHeight(34)
        self.btn_cobrar.setAutoDefault(False)
        self.btn_cobrar.clicked.connect(self._validar_y_aceptar)
        footer.addWidget(btn_cancelar)
        footer.addWidget(self.btn_cobrar)
        root.addLayout(footer)

    def _cargar_origenes(self) -> None:
        try:
            cajas = CajaService.listar_cajas(self.session, id_usuario=self.id_usuario)
        except PermisoDenegadoError:
            cajas = []
        self._cajas_abiertas = [c for c in cajas if c.fecha_apertura is not None and c.fecha_cierre is None]
        try:
            cuentas = BancoService.listar_cuentas(self.session, id_usuario=self.id_usuario)
        except PermisoDenegadoError:
            cuentas = []
        self._cuentas_activas = [c for c in cuentas if (c.estado_cuenta or "ACTIVO") == "ACTIVO"]

    def _toggle_origen(self) -> None:
        metodo = self.metodo_combo.currentData()
        requiere_caja = metodo in METODOS_QUE_REQUIEREN_CAJA
        self.origen_combo.blockSignals(True)
        self.origen_combo.clear()
        if requiere_caja:
            if not self._cajas_abiertas:
                self.origen_combo.addItem("Sin cajas abiertas", None)
                self.origen_combo.setEnabled(False)
            else:
                self.origen_combo.setEnabled(True)
                for caja in self._cajas_abiertas:
                    self.origen_combo.addItem(caja.nombre_caja or f"Caja {caja.id_caja}", ("caja", caja.id_caja))
        else:
            if not self._cuentas_activas:
                self.origen_combo.addItem("Sin cuentas bancarias activas", None)
                self.origen_combo.setEnabled(False)
            else:
                self.origen_combo.setEnabled(True)
                for cuenta in self._cuentas_activas:
                    nombre_banco = cuenta.banco.nombre_banco if cuenta.banco else "Banco"
                    self.origen_combo.addItem(
                        f"{nombre_banco} - ...{cuenta.numero_cuenta[-4:]}", ("banco", cuenta.id_cuenta)
                    )
        self.origen_combo.blockSignals(False)

    def _validar_y_aceptar(self) -> None:
        origen = self.origen_combo.currentData()
        if origen is None:
            QMessageBox.warning(self, "Origen requerido", "No hay ninguna caja/cuenta disponible para este método.")
            return
        tipo_origen, id_origen = origen

        try:
            self.pago_creado = PagoService.registrar_pago_cobro(
                self.session,
                id_cuenta_por_cobrar=self.cuenta.id_cuenta_por_cobrar,
                monto=self.monto_input.value(),
                metodo_pago=self.metodo_combo.currentData(),
                id_caja=id_origen if tipo_origen == "caja" else None,
                id_cuenta_bancaria=id_origen if tipo_origen == "banco" else None,
                referencia=self.referencia_input.text().strip() or None,
                id_usuario=self.id_usuario,
            )
        except ValueError as exc:
            self.session.rollback()
            QMessageBox.warning(self, "No se pudo registrar el cobro", str(exc))
            return
        except PermisoDenegadoError:
            self.session.rollback()
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para aplicar cobros.")
            return
        except Exception:
            self.session.rollback()
            logger.exception("Fallo al registrar cobro de cliente")
            QMessageBox.critical(self, "Error", "No se pudo registrar el cobro.")
            return

        self.accept()


class CuentasPorCobrarPanel(QWidget):
    """Panel principal del modulo Cuentas por Cobrar: listado con filtro por estado,
    paginacion y cobro contra PagoService.registrar_pago_cobro."""

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.pagina_actual = 1
        self.total_paginas = 1
        self.setObjectName("ContentArea")
        self._setup_ui()
        QTimer.singleShot(100, self.cargar_cuentas)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.cargar_cuentas()

    # ── Construccion de la UI ─────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        root.addWidget(self._make_header())
        root.addWidget(self._make_toolbar())
        root.addWidget(self._make_table())
        root.addWidget(self._make_footer())

        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

    def _make_header(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("Cuentas por Cobrar")
        lbl.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        self.lbl_total = QLabel("Cargando…")
        self.lbl_total.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 13px;"
            f" background-color: {COLOR_TABLE_HEADER}; border-radius: 10px;"
            " padding: 3px 10px;"
        )

        h.addWidget(lbl)
        h.addWidget(self.lbl_total)
        h.addStretch()
        return w

    def _make_toolbar(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(
            f"background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 8px; padding: 4px;"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)

        self.estado_combo = QComboBox()
        for etiqueta, valor in ESTADOS_FILTRO:
            self.estado_combo.addItem(etiqueta, valor)
        self.estado_combo.currentIndexChanged.connect(self._buscar_desde_inicio)
        self.btn_filtrar = BotonFiltros([("Estado", self.estado_combo)])

        h.addStretch()
        h.addWidget(self.btn_filtrar)
        return w

    def _make_table(self) -> QWidget:
        self.tabla = self._crear_tabla(["ID", "Factura", "Cliente", "Saldo Pendiente", "Vencimiento", "Estado"])
        return self.tabla

    def _crear_tabla(self, columnas: list[str]):
        tabla = QTableWidget(0, len(columnas))
        tabla.setHorizontalHeaderLabels(columnas)
        tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabla.setAlternatingRowColors(True)
        tabla.setShowGrid(False)
        tabla.verticalHeader().setVisible(False)
        tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(tabla)
        tabla.setColumnHidden(0, True)
        tabla.verticalHeader().setDefaultSectionSize(45)
        return tabla

    def _make_footer(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        self.lbl_pagina = QLabel("Página 1")
        self.lbl_pagina.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")

        self.btn_anterior = QPushButton()
        self.btn_anterior.setIcon(qta.icon("fa5s.chevron-left", color=COLOR_TEXT_DARK))
        self.btn_anterior.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_anterior.setFixedWidth(40)
        self.btn_anterior.clicked.connect(self._pagina_anterior)

        self.btn_siguiente = QPushButton()
        self.btn_siguiente.setIcon(qta.icon("fa5s.chevron-right", color=COLOR_TEXT_DARK))
        self.btn_siguiente.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_siguiente.setFixedWidth(40)
        self.btn_siguiente.clicked.connect(self._pagina_siguiente)

        btn_cobrar = QPushButton("Cobrar")
        btn_cobrar.setIcon(qta.icon("fa5s.hand-holding-usd", color=COLOR_TEXT_DARK))
        btn_cobrar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_cobrar.clicked.connect(self.cobrar_seleccionada)

        h.addWidget(self.lbl_pagina)
        h.addWidget(self.btn_anterior)
        h.addWidget(self.btn_siguiente)
        h.addStretch()
        h.addWidget(btn_cobrar)
        return w

    # ── Paginacion ───────────────────────────────────────────────────────

    def _buscar_desde_inicio(self) -> None:
        self.pagina_actual = 1
        self.cargar_cuentas()

    def _pagina_anterior(self) -> None:
        if self.pagina_actual > 1:
            self.pagina_actual -= 1
            self.cargar_cuentas()

    def _pagina_siguiente(self) -> None:
        if self.pagina_actual < self.total_paginas:
            self.pagina_actual += 1
            self.cargar_cuentas()

    # ── Logica de datos ────────────────────────────────────────────────────

    def cargar_cuentas(self) -> None:
        session = self.session_factory()
        try:
            resultado = PagoService.listar_cuentas_por_cobrar(
                session,
                estado=self.estado_combo.currentData(),
                pagina=self.pagina_actual,
                por_pagina=POR_PAGINA,
                id_usuario=self.usuario.id_usuario,
            )
            self._poblar_tabla(resultado)
        except PermisoDenegadoError:
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar cuentas por cobrar.")
        except Exception:
            logger.exception("Fallo al cargar el listado de cuentas por cobrar")
            QMessageBox.critical(self, "Error de conexión", "No se pudo cargar el listado de cuentas por cobrar.")
        finally:
            session.close()

    def _poblar_tabla(self, resultado: dict) -> None:
        cuentas: list[CuentaPorCobrar] = resultado["items"]
        self.tabla.setRowCount(len(cuentas))
        for fila, cuenta in enumerate(cuentas):
            factura = cuenta.factura
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(cuenta.id_cuenta_por_cobrar)))
            self.tabla.setItem(fila, 1, QTableWidgetItem(factura.numero_factura if factura else ""))
            self.tabla.setItem(
                fila, 2, QTableWidgetItem(factura.cliente.nombre_razon_social if factura and factura.cliente else "")
            )
            self.tabla.setItem(fila, 3, QTableWidgetItem(f"${float(cuenta.saldo_pendiente):,.2f}"))
            vencimiento = cuenta.fecha_vencimiento.strftime("%d/%m/%Y") if cuenta.fecha_vencimiento else "Sin definir"
            self.tabla.setItem(fila, 4, QTableWidgetItem(vencimiento))
            estado_visual = getattr(cuenta, "estado_visual", cuenta.estado)
            color = COLORES_ESTADO_CXC.get(estado_visual, COLOR_TEXT_MUTED)
            self.tabla.setCellWidget(fila, 5, EstadoBadge(estado_visual.capitalize(), color))

        total = resultado["total"]
        self.total_paginas = max(1, -(-total // POR_PAGINA))
        self.pagina_actual = min(self.pagina_actual, self.total_paginas)

        self.lbl_total.setText(f"{total} cuenta{'s' if total != 1 else ''} por cobrar")
        self.lbl_pagina.setText(f"Página {self.pagina_actual} de {self.total_paginas}")
        self.btn_anterior.setEnabled(self.pagina_actual > 1)
        self.btn_siguiente.setEnabled(self.pagina_actual < self.total_paginas)

    def _fila_seleccionada_id(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            QMessageBox.information(self, "Selección requerida", "Selecciona una cuenta por cobrar de la lista.")
            return None
        item = self.tabla.item(filas[0].row(), 0)
        return int(item.text()) if item is not None else None

    def cobrar_seleccionada(self) -> None:
        id_cuenta = self._fila_seleccionada_id()
        if id_cuenta is None:
            return
        session = self.session_factory()
        try:
            cuenta = session.get(CuentaPorCobrar, id_cuenta)
            if cuenta is None:
                return
            if cuenta.estado == "pagada":
                QMessageBox.information(self, "Ya pagada", "Esta cuenta por cobrar ya está saldada.")
                return
            dialogo = PagoCobroDialog(session, self.usuario.id_usuario, cuenta, parent=self)
            if dialogo.exec() and dialogo.pago_creado is not None:
                self.cargar_cuentas()
                QMessageBox.information(self, "Cobro registrado", "El cobro se registró con éxito.")
        except PermisoDenegadoError:
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para aplicar cobros.")
        finally:
            session.close()
