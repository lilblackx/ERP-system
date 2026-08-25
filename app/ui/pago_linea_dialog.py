"""Dialogo de una sola linea de "forma de pago" para una factura de contado (ver
FacturaFormDialog._make_card_pagos): metodo + moneda + monto + origen (caja o cuenta
bancaria, segun el metodo) + referencia opcional. Puede agregarse mas de una linea a la
misma factura -- ver VentaService.emitir_factura(pagos=[...]).

No ofrece abrir un turno de caja desde aca: FacturacionPanel exige una caja con turno
abierto para poder entrar a facturar (ver FacturacionPanel._verificar_caja_abierta /
CajaAperturaDialog), asi que si se llego hasta este dialogo ya deberia existir una."""

import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import BancoService, CajaService
from app.ui.styles import (
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_FIELD_BG,
    COLOR_PRIMARY,
    COLOR_PRIMARY_DARK,
    COLOR_PRIMARY_LIGHT,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    FONT_FAMILY,
    aplicar_sombra,
)

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

METODOS_PAGO = [
    ("Efectivo", "efectivo"),
    ("Transferencia", "transferencia"),
    ("Zelle", "zelle"),
    ("Binance (USDT)", "binance"),
    ("Punto de Venta", "punto_de_venta"),
]
MONEDAS = [
    ("Dólares (USD)", "USD"),
    ("Bolívares (VES)", "VES"),
    ("Pesos colombianos (COP)", "COP"),
    ("USDT", "USDT"),
]
METODOS_MONEDA_SUGERIDA = {"zelle": "USD", "binance": "USDT"}
METODOS_QUE_REQUIEREN_CAJA = {"efectivo"}


def _enmascarar(numero: str | None) -> str:
    if not numero:
        return "s/n"
    visibles = numero[-4:]
    return "*" * max(len(numero) - len(visibles), 0) + visibles


class PagoLineaDialog(QDialog):
    """Al aceptar, get_data() devuelve el dict listo para VentaService.emitir_factura
    (pagos=[...]): metodo_pago, moneda, monto_moneda_origen, id_cuenta_bancaria/id_caja
    (exactamente uno), referencia."""

    def __init__(self, session: Session, id_usuario: int | None, monto_sugerido: float | None = None, parent=None):
        super().__init__(parent)
        self.session = session
        self.id_usuario = id_usuario
        self._cajas_abiertas: list = []
        self._cuentas_activas: list = []

        self.setWindowTitle("Agregar Forma de Pago")
        self.setMinimumWidth(420)
        self.resize(420, 420)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()
        self._cargar_origenes()
        self._toggle_origen()

        # Precarga el saldo pendiente de la factura (auditoria UX de facturacion,
        # cajero): sin esto, el caso mas comun -- un solo pago en efectivo por el total
        # exacto -- igual obligaba a recordar y tipear el monto a mano. Preseleccionado
        # (selectAll) para poder sobreescribirlo de un tiro si el cajero va a repartir el
        # pago entre varias formas/monedas.
        if monto_sugerido is not None and monto_sugerido > 0:
            self.monto_input.setValue(monto_sugerido)
            self.monto_input.setFocus()
            self.monto_input.selectAll()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.money-bill-wave", color=COLOR_PRIMARY).pixmap(QSize(20, 20)))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(34, 34)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_titulo = QLabel("Agregar Forma de Pago")
        lbl_titulo.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        header.addWidget(icon_lbl)
        header.addWidget(lbl_titulo)
        header.addStretch()
        root.addLayout(header)

        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(8)

        lbl_metodo = QLabel("Método de Pago <span style='color: #DC2626;'>*</span>")
        lbl_metodo.setProperty("class", "FormLabel")
        self.metodo_combo = QComboBox()
        self.metodo_combo.setFixedHeight(32)
        for etiqueta, valor in METODOS_PAGO:
            self.metodo_combo.addItem(etiqueta, valor)
        self.metodo_combo.currentIndexChanged.connect(self._on_metodo_cambiado)
        card_layout.addWidget(lbl_metodo)
        card_layout.addWidget(self.metodo_combo)

        fila_monto = QHBoxLayout()
        fila_monto.setSpacing(8)

        col_moneda = QVBoxLayout()
        lbl_moneda = QLabel("Moneda")
        lbl_moneda.setProperty("class", "FormLabel")
        self.moneda_combo = QComboBox()
        self.moneda_combo.setFixedHeight(32)
        for etiqueta, valor in MONEDAS:
            self.moneda_combo.addItem(etiqueta, valor)
        col_moneda.addWidget(lbl_moneda)
        col_moneda.addWidget(self.moneda_combo)

        col_monto = QVBoxLayout()
        lbl_monto = QLabel("Monto <span style='color: #DC2626;'>*</span>")
        lbl_monto.setProperty("class", "FormLabel")
        self.monto_input = QDoubleSpinBox()
        self.monto_input.setRange(0.01, 999999999.99)
        self.monto_input.setDecimals(2)
        self.monto_input.setFixedHeight(32)
        # Con el monto ya precargado (ver __init__/monto_sugerido) y seleccionado, Enter
        # aca confirma de una -- para el caso comun (efectivo, monto sugerido correcto)
        # el flujo completo queda en "Agregar forma de pago" + Enter, sin mouse
        # (auditoria UX de facturacion, cajero).
        self.monto_input.lineEdit().returnPressed.connect(self._validar_y_aceptar)
        col_monto.addWidget(lbl_monto)
        col_monto.addWidget(self.monto_input)

        fila_monto.addLayout(col_moneda, stretch=1)
        fila_monto.addLayout(col_monto, stretch=1)
        card_layout.addLayout(fila_monto)

        lbl_origen = QLabel("Origen <span style='color: #DC2626;'>*</span>")
        lbl_origen.setProperty("class", "FormLabel")
        self.origen_combo = QComboBox()
        self.origen_combo.setFixedHeight(32)
        card_layout.addWidget(lbl_origen)
        card_layout.addWidget(self.origen_combo)

        lbl_ref = QLabel("Referencia")
        lbl_ref.setProperty("class", "FormLabel")
        self.referencia_input = QLineEdit()
        self.referencia_input.setPlaceholderText("Opcional (confirmación, últimos dígitos, etc.)")
        self.referencia_input.setFixedHeight(32)
        card_layout.addWidget(lbl_ref)
        card_layout.addWidget(self.referencia_input)

        root.addWidget(card, stretch=1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 4, 0, 0)
        footer.setSpacing(10)
        footer.addStretch()

        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.setIcon(qta.icon("fa5s.times", color="#475569"))
        self.btn_cancelar.setObjectName("BtnSecondary")
        self.btn_cancelar.setFixedHeight(34)
        self.btn_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancelar.setAutoDefault(False)
        self.btn_cancelar.clicked.connect(self.reject)

        self.btn_agregar = QPushButton("Agregar")
        self.btn_agregar.setIcon(qta.icon("fa5s.check", color="#FFFFFF"))
        self.btn_agregar.setObjectName("BtnPrimary")
        self.btn_agregar.setFixedHeight(34)
        self.btn_agregar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_agregar.setAutoDefault(False)
        self.btn_agregar.clicked.connect(self._validar_y_aceptar)

        footer.addWidget(self.btn_cancelar)
        footer.addWidget(self.btn_agregar)
        root.addLayout(footer)

    # ── Origen (caja/cuenta bancaria segun metodo) ───────────────────────────

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

    def _on_metodo_cambiado(self) -> None:
        metodo = self.metodo_combo.currentData()
        moneda_sugerida = METODOS_MONEDA_SUGERIDA.get(metodo)
        if moneda_sugerida:
            indice = self.moneda_combo.findData(moneda_sugerida)
            if indice >= 0:
                self.moneda_combo.setCurrentIndex(indice)
        self._toggle_origen()
        # Un pago en efectivo no tiene "referencia" que registrar (a diferencia de una
        # transferencia/Zelle/Binance/punto de venta, donde suele ser la confirmacion o
        # los ultimos digitos) -- se deshabilita y limpia para no dejar un valor cargado
        # que no aplica si el usuario cambia de metodo despues.
        es_efectivo = metodo == "efectivo"
        self.referencia_input.setEnabled(not es_efectivo)
        if es_efectivo:
            self.referencia_input.clear()

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
                    etiqueta = f"{nombre_banco} - {_enmascarar(cuenta.numero_cuenta)}"
                    self.origen_combo.addItem(etiqueta, ("banco", cuenta.id_cuenta))
        self.origen_combo.blockSignals(False)

    # ── Validación / datos ────────────────────────────────────────────────

    def _validar_y_aceptar(self) -> None:
        if self.monto_input.value() <= 0:
            QMessageBox.warning(self, "Monto requerido", "Ingrese un monto mayor a cero.")
            return
        origen = self.origen_combo.currentData()
        if origen is None:
            metodo = self.metodo_combo.currentData()
            if metodo in METODOS_QUE_REQUIEREN_CAJA:
                QMessageBox.warning(
                    self,
                    "Caja requerida",
                    "No hay ninguna caja con turno abierto. Cierre este formulario y verifique el turno de caja.",
                )
            else:
                QMessageBox.warning(
                    self, "Cuenta requerida", "No hay ninguna cuenta bancaria activa para este método de pago."
                )
            return
        self.accept()

    def get_data(self) -> dict:
        tipo_origen, id_origen = self.origen_combo.currentData()
        return {
            "metodo_pago": self.metodo_combo.currentData(),
            "moneda": self.moneda_combo.currentData(),
            "monto_moneda_origen": self.monto_input.value(),
            "id_caja": id_origen if tipo_origen == "caja" else None,
            "id_cuenta_bancaria": id_origen if tipo_origen == "banco" else None,
            "referencia": self.referencia_input.text().strip() or None,
        }
