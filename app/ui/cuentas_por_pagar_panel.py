"""
Panel del modulo Cuentas por Pagar (CxP): modulo aparte, no vive dentro de Compras
(app/ui/compras.py) -- pedido explicito del usuario de no mezclar "pagar" con "comprar"
en la misma pantalla. Mismo patron visual que app/ui/proveedores_panel.py (paleta y
tipografia de app/ui/styles.py): barra de herramientas, tabla estilizada, paginacion.

Las cuentas por pagar se generan solas (trigger trg_compras_cxp al facturar una compra a
credito, tanto por el flujo directo -- CompraService.registrar_compra -- como por el
flujo OC -- CompraService.crear_compra_desde_oc); este panel es puramente de consulta +
pago, no crea/edita cuentas por pagar directamente.
"""

import logging
from decimal import Decimal

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from app.db.models import CuentaPorPagar, Usuario
from app.services.db_utils import reintentar_en_deadlock
from app.services.pagos import PagoService
from app.services.permisos import PermisoDenegadoError
from app.services.tasas import TasaService
from app.services.tesoreria import BancoService, CajaService
from app.ui.message_box import MessageBox
from app.ui.numeric_inputs import NumericFieldType, NumericLineEdit
from app.ui.pago_linea_dialog import METODOS_PAGO, METODOS_QUE_REQUIEREN_CAJA
from app.ui.styles import (
    ASTERISCO_REQUERIDO,
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
    COLOR_TEXT_DARK_SLATE,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MEDIUM,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
    COLOR_WHITE,
    FONT_FAMILY,
    ICON_CHEVRON_DOWN_URL,
    TABLE_QSS,
    EstadoBadge,
    alinear_encabezados,
    aplicar_sombra,
)
from app.ui.toolbar_popups import BotonFiltros

logger = logging.getLogger(__name__)

POR_PAGINA = 20

COLORES_ESTADO_CXP = {
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
    color: {COLOR_TEXT_DARK_SLATE};
    margin-bottom: 2px;
}}
QLineEdit, QComboBox {{
    background-color: {COLOR_WHITE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
    min-height: 20px;
}}
QLineEdit:focus, QComboBox:focus {{
    border: 1.5px solid {COLOR_PRIMARY};
}}
QLineEdit:disabled, QComboBox:disabled {{
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
QPushButton#BtnPrimary {{
    background-color: {COLOR_PRIMARY};
    color: {COLOR_WHITE};
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
    color: {COLOR_TEXT_MEDIUM};
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


class PagoProveedorDialog(QDialog):
    """Un unico pago (sin conversion de moneda -- PagoService.registrar_pago_proveedor no
    la maneja, a diferencia de PagoLineaDialog/pagos_cobros) contra el saldo_pendiente de
    una CuentaPorPagar. Mismo patron de origen caja/cuenta que PagoLineaDialog."""

    def __init__(
        self,
        session: Session,
        id_usuario: int | None,
        cuenta: CuentaPorPagar,
        tasa_bcv: float | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.session = session
        self.id_usuario = id_usuario
        self.cuenta = cuenta
        self.tasa_bcv = tasa_bcv
        self.pago_creado = None
        self._cajas_abiertas: list = []
        self._cuentas_activas: list = []

        self.setWindowTitle("Pagar a Proveedor")
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

        proveedor = self.cuenta.compra.proveedor if self.cuenta.compra else None
        lbl_titulo = QLabel(f"Pagar a {proveedor.nombre_razon_social if proveedor else 'proveedor'}")
        lbl_titulo.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        root.addWidget(lbl_titulo)

        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        texto_saldo = f"Saldo pendiente: ${float(self.cuenta.saldo_pendiente):,.2f}"
        if self.tasa_bcv:
            texto_saldo += f"  (Bs {float(self.cuenta.saldo_pendiente) * self.tasa_bcv:,.2f})"
        lbl_saldo = QLabel(texto_saldo)
        lbl_saldo.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_MUTED};")
        layout.addWidget(lbl_saldo)

        lbl_metodo = QLabel(f"Método de Pago {ASTERISCO_REQUERIDO}")
        lbl_metodo.setProperty("class", "FormLabel")
        self.metodo_combo = QComboBox()
        for etiqueta, valor in METODOS_PAGO:
            self.metodo_combo.addItem(etiqueta, valor)
        self.metodo_combo.setFixedHeight(32)
        self.metodo_combo.currentIndexChanged.connect(self._toggle_origen)
        layout.addWidget(lbl_metodo)
        layout.addWidget(self.metodo_combo)

        lbl_monto = QLabel(f"Monto (USD) {ASTERISCO_REQUERIDO}")
        lbl_monto.setProperty("class", "FormLabel")
        self.monto_input = NumericLineEdit(
            NumericFieldType.AMOUNT, min_value=Decimal("0.01"), max_value=self.cuenta.saldo_pendiente, prefix="$ "
        )
        self.monto_input.set_value(self.cuenta.saldo_pendiente)
        self.monto_input.setFixedHeight(32)
        layout.addWidget(lbl_monto)
        layout.addWidget(self.monto_input)

        lbl_origen = QLabel(f"Origen {ASTERISCO_REQUERIDO}")
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
        self.referencia_input.setMaxLength(100)  # columna referencia VARCHAR(100)
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
        self.btn_pagar = QPushButton("Registrar Pago")
        self.btn_pagar.setObjectName("BtnPrimary")
        self.btn_pagar.setFixedHeight(34)
        self.btn_pagar.setAutoDefault(False)
        self.btn_pagar.clicked.connect(self._validar_y_aceptar)
        footer.addWidget(btn_cancelar)
        footer.addWidget(self.btn_pagar)
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
            MessageBox.warning(self, "Origen requerido", "No hay ninguna caja/cuenta disponible para este método.")
            return
        tipo_origen, id_origen = origen

        self.btn_pagar.setEnabled(False)
        try:
            self.pago_creado = reintentar_en_deadlock(
                lambda: PagoService.registrar_pago_proveedor(
                    self.session,
                    id_cuenta_por_pagar=self.cuenta.id_cuenta,
                    monto=self.monto_input.get_value(),
                    metodo_pago=self.metodo_combo.currentData(),
                    id_caja=id_origen if tipo_origen == "caja" else None,
                    id_cuenta_bancaria=id_origen if tipo_origen == "banco" else None,
                    referencia=self.referencia_input.text().strip() or None,
                    id_usuario=self.id_usuario,
                )
            )
        except ValueError as exc:
            self.session.rollback()
            MessageBox.warning(self, "No se pudo registrar el pago", str(exc))
            return
        except PermisoDenegadoError:
            self.session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para aplicar pagos.")
            return
        except Exception:
            self.session.rollback()
            logger.exception("Fallo al registrar pago a proveedor")
            MessageBox.critical(self, "Error", "No se pudo registrar el pago.")
            return
        finally:
            self.btn_pagar.setEnabled(True)

        self.accept()


class CuentasPorPagarPanel(QWidget):
    """Panel principal del modulo Cuentas por Pagar: listado con filtro por estado,
    paginacion y pago contra PagoService.registrar_pago_proveedor."""

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.pagina_actual = 1
        self.total_paginas = 1
        self._tasa_bcv: float | None = None
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

        lbl = QLabel("Cuentas por Pagar")
        lbl.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        self.lbl_total = QLabel("Cargando…")
        self.lbl_total.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 13px;"
            f" background-color: {COLOR_TABLE_HEADER}; border-radius: 10px;"
            " padding: 3px 10px;"
        )

        # Tasa BCV vigente -- mismo patron informativo que factura_form_dialog.py/
        # cuentas_por_cobrar_panel.py: se oculta si el usuario no tiene 'tasas'/'ver' o no
        # hay ninguna tasa registrada, nunca bloquea el panel.
        self.lbl_tasa = QLabel()
        self.lbl_tasa.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 13px;"
            f" background-color: {COLOR_TABLE_HEADER}; border-radius: 10px;"
            " padding: 3px 10px;"
        )
        self.lbl_tasa.setVisible(False)

        h.addWidget(lbl)
        h.addWidget(self.lbl_total)
        h.addWidget(self.lbl_tasa)
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
        self.tabla = self._crear_tabla(
            ["ID", "Compra", "Proveedor", "Saldo Pendiente", "Saldo Pendiente (Bs)", "Vencimiento", "Estado"]
        )
        alinear_encabezados(
            self.tabla,
            {
                1: Qt.AlignmentFlag.AlignLeft,
                2: Qt.AlignmentFlag.AlignLeft,
                3: Qt.AlignmentFlag.AlignRight,
                4: Qt.AlignmentFlag.AlignRight,
                5: Qt.AlignmentFlag.AlignLeft,
                6: Qt.AlignmentFlag.AlignCenter,
            },
        )
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

        btn_pagar = QPushButton("Pagar")
        btn_pagar.setIcon(qta.icon("fa5s.money-bill-wave", color=COLOR_TEXT_DARK))
        btn_pagar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_pagar.clicked.connect(self.pagar_seleccionada)

        h.addWidget(self.lbl_pagina)
        h.addWidget(self.btn_anterior)
        h.addWidget(self.btn_siguiente)
        h.addStretch()
        h.addWidget(btn_pagar)
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

    def _cargar_tasa_actual(self, session) -> float | None:
        """Tasa BCV vigente, solo para mostrar el equivalente en Bs -- nunca bloquea el
        panel. Mismo patron que factura_form_dialog.py::_cargar_tasa_vigente()."""
        try:
            tasa = TasaService.obtener_tasa_actual(session, id_usuario=self.usuario.id_usuario)
        except PermisoDenegadoError:
            self.lbl_tasa.setVisible(False)
            return None
        if tasa is None:
            self.lbl_tasa.setVisible(False)
            return None
        fecha = tasa["fecha_tasa"].strftime("%d/%m/%Y")
        self.lbl_tasa.setText(f"Tasa BCV: {tasa['tasa_bcv']:,.2f} Bs/USD ({fecha})")
        self.lbl_tasa.setVisible(True)
        return float(tasa["tasa_bcv"])

    def cargar_cuentas(self) -> None:
        session = self.session_factory()
        try:
            self._tasa_bcv = self._cargar_tasa_actual(session)
            resultado = PagoService.listar_cuentas_por_pagar(
                session,
                estado=self.estado_combo.currentData(),
                pagina=self.pagina_actual,
                por_pagina=POR_PAGINA,
                id_usuario=self.usuario.id_usuario,
            )
            self._poblar_tabla(resultado)
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar cuentas por pagar.")
        except Exception:
            logger.exception("Fallo al cargar el listado de cuentas por pagar")
            MessageBox.critical(self, "Error de conexión", "No se pudo cargar el listado de cuentas por pagar.")
        finally:
            session.close()

    def _poblar_tabla(self, resultado: dict) -> None:
        cuentas: list[CuentaPorPagar] = resultado["items"]
        self.tabla.setRowCount(len(cuentas))
        for fila, cuenta in enumerate(cuentas):
            compra = cuenta.compra
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(cuenta.id_cuenta)))
            self.tabla.setItem(fila, 1, QTableWidgetItem(compra.numero_compra if compra else ""))
            self.tabla.setItem(
                fila, 2, QTableWidgetItem(compra.proveedor.nombre_razon_social if compra and compra.proveedor else "")
            )
            item_saldo = QTableWidgetItem(f"${float(cuenta.saldo_pendiente):,.2f}")
            item_saldo.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 3, item_saldo)

            # Equivalente en Bs, informativo (mismo criterio que factura_pdf.py/CxC): usa
            # la tasa BCV vigente al momento de consultar, no una tasa historica de cuando
            # nacio la deuda -- no hay ninguna guardada por cuenta.
            texto_bs = f"Bs {float(cuenta.saldo_pendiente) * self._tasa_bcv:,.2f}" if self._tasa_bcv else "—"
            item_saldo_bs = QTableWidgetItem(texto_bs)
            item_saldo_bs.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 4, item_saldo_bs)

            vencimiento = cuenta.fecha_vencimiento.strftime("%d/%m/%Y") if cuenta.fecha_vencimiento else "Sin definir"
            self.tabla.setItem(fila, 5, QTableWidgetItem(vencimiento))
            color = COLORES_ESTADO_CXP.get(cuenta.estado, COLOR_TEXT_MUTED)
            self.tabla.setCellWidget(fila, 6, EstadoBadge(cuenta.estado.capitalize(), color))

        total = resultado["total"]
        self.total_paginas = max(1, -(-total // POR_PAGINA))
        self.pagina_actual = min(self.pagina_actual, self.total_paginas)

        self.lbl_total.setText(f"{total} cuenta{'s' if total != 1 else ''} por pagar")
        self.lbl_pagina.setText(f"Página {self.pagina_actual} de {self.total_paginas}")
        self.btn_anterior.setEnabled(self.pagina_actual > 1)
        self.btn_siguiente.setEnabled(self.pagina_actual < self.total_paginas)

    def _fila_seleccionada_id(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            MessageBox.information(self, "Selección requerida", "Selecciona una cuenta por pagar de la lista.")
            return None
        item = self.tabla.item(filas[0].row(), 0)
        return int(item.text()) if item is not None else None

    def pagar_seleccionada(self) -> None:
        id_cuenta = self._fila_seleccionada_id()
        if id_cuenta is None:
            return
        session = self.session_factory()
        try:
            cuenta = session.get(CuentaPorPagar, id_cuenta)
            if cuenta is None:
                return
            if cuenta.estado == "pagada":
                MessageBox.information(self, "Ya pagada", "Esta cuenta por pagar ya está saldada.")
                return
            dialogo = PagoProveedorDialog(
                session, self.usuario.id_usuario, cuenta, tasa_bcv=self._tasa_bcv, parent=self
            )
            if dialogo.exec() and dialogo.pago_creado is not None:
                self.cargar_cuentas()
                MessageBox.information(self, "Pago registrado", "El pago se registró con éxito.")
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para aplicar pagos.")
        finally:
            session.close()
