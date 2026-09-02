"""Dialogo para devolver en efectivo/banco (total o parcialmente) el saldo disponible de
una nota de credito de cliente -- ver NotaCreditoService.devolver_nota_credito_cliente().

A diferencia de AplicarNotaCreditoDialog (transferencia contable interna, sin
autorizacion), esto SI mueve dinero real y SIEMPRE exige autorizacion de un supervisor sin
importar el metodo -- reusa AutorizacionDialog tal cual, mismo patron que el vuelto
bancario de facturacion (app/ui/factura_form_dialog.py)."""

import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from app.db.models import NotaCreditoCliente
from app.services.notas_credito import NotaCreditoService
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import BancoService, CajaService
from app.ui.autorizacion_dialog import AutorizacionDialog
from app.ui.message_box import MessageBox
from app.ui.styles import (
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_FIELD_BG,
    COLOR_PRIMARY,
    COLOR_PRIMARY_DARK,
    COLOR_PRIMARY_LIGHT,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_LIGHT,
    ICON_CHEVRON_DOWN_URL,
    ICON_CHEVRON_UP_URL,
    ComboBoxSinScroll,
    aplicar_sombra,
)

METODOS_DEVOLUCION = [
    ("Efectivo", "efectivo"),
    ("Pago Móvil", "pago_movil"),
    ("Transferencia", "transferencia"),
]

DIALOG_STYLE = f"""
QDialog {{
    background-color: {COLOR_CONTENT_BG};
    font-family: Arial, sans-serif;
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
QComboBox, QDoubleSpinBox {{
    background-color: #FFFFFF;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
    min-height: 20px;
}}
QComboBox:focus, QDoubleSpinBox:focus {{
    border: 1.5px solid {COLOR_PRIMARY};
}}
QComboBox:disabled, QDoubleSpinBox:disabled {{
    background-color: {COLOR_CONTENT_BG};
    color: {COLOR_TEXT_LIGHT};
}}
QComboBox {{
    padding-right: 24px;
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
}}
"""


class DevolverNotaCreditoDialog(QDialog):
    """Al aceptar, `nota_actualizada` queda poblada con el resultado de
    NotaCreditoService.devolver_nota_credito_cliente()."""

    def __init__(
        self,
        session: Session,
        id_usuario: int | None,
        notas_disponibles: list[NotaCreditoCliente],
        parent=None,
    ):
        super().__init__(parent)
        self.session = session
        self.id_usuario = id_usuario
        self.notas_disponibles = notas_disponibles
        self.nota_actualizada: NotaCreditoCliente | None = None
        self._cajas_abiertas: list = []
        self._cuentas_activas: list = []

        self.setWindowTitle("Devolver Nota de Crédito")
        self.setMinimumWidth(420)
        self.resize(420, 400)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()
        self._cargar_origenes()
        self._toggle_origen()
        self._on_nota_cambiada()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.hand-holding-usd", color=COLOR_PRIMARY).pixmap(QSize(20, 20)))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(34, 34)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_titulo = QLabel("Devolver Nota de Crédito")
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

        lbl_nota = QLabel("Nota de crédito <span style='color: #DC2626;'>*</span>")
        lbl_nota.setProperty("class", "FormLabel")
        self.nota_combo = ComboBoxSinScroll()
        self.nota_combo.setFixedHeight(32)
        for nota in self.notas_disponibles:
            etiqueta = f"{nota.numero_nota_credito} — disponible ${float(nota.saldo_disponible):,.2f}"
            self.nota_combo.addItem(etiqueta, nota.id_nota_credito)
        self.nota_combo.currentIndexChanged.connect(self._on_nota_cambiada)
        card_layout.addWidget(lbl_nota)
        card_layout.addWidget(self.nota_combo)

        lbl_monto = QLabel("Monto a devolver <span style='color: #DC2626;'>*</span>")
        lbl_monto.setProperty("class", "FormLabel")
        self.monto_input = QDoubleSpinBox()
        self.monto_input.setDecimals(2)
        self.monto_input.setFixedHeight(32)
        card_layout.addWidget(lbl_monto)
        card_layout.addWidget(self.monto_input)

        lbl_metodo = QLabel("Método de devolución <span style='color: #DC2626;'>*</span>")
        lbl_metodo.setProperty("class", "FormLabel")
        self.metodo_combo = ComboBoxSinScroll()
        self.metodo_combo.setFixedHeight(32)
        for etiqueta, valor in METODOS_DEVOLUCION:
            self.metodo_combo.addItem(etiqueta, valor)
        self.metodo_combo.currentIndexChanged.connect(self._toggle_origen)
        card_layout.addWidget(lbl_metodo)
        card_layout.addWidget(self.metodo_combo)

        lbl_origen = QLabel("Origen <span style='color: #DC2626;'>*</span>")
        lbl_origen.setProperty("class", "FormLabel")
        self.origen_combo = ComboBoxSinScroll()
        self.origen_combo.setFixedHeight(32)
        card_layout.addWidget(lbl_origen)
        card_layout.addWidget(self.origen_combo)

        self.lbl_aviso = QLabel("Toda devolución requiere autorización de un supervisor.")
        self.lbl_aviso.setStyleSheet(f"color: {COLOR_DANGER}; font-size: 11px; font-style: italic;")
        card_layout.addWidget(self.lbl_aviso)

        root.addWidget(card, stretch=1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 4, 0, 0)
        footer.setSpacing(10)
        footer.addStretch()

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setIcon(qta.icon("fa5s.times", color="#475569"))
        btn_cancelar.setObjectName("BtnSecondary")
        btn_cancelar.setFixedHeight(34)
        btn_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancelar.setAutoDefault(False)
        btn_cancelar.clicked.connect(self.reject)

        self.btn_devolver = QPushButton("Devolver")
        self.btn_devolver.setIcon(qta.icon("fa5s.check", color="#FFFFFF"))
        self.btn_devolver.setObjectName("BtnPrimary")
        self.btn_devolver.setFixedHeight(34)
        self.btn_devolver.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_devolver.setAutoDefault(False)
        self.btn_devolver.clicked.connect(self._confirmar)

        footer.addWidget(btn_cancelar)
        footer.addWidget(self.btn_devolver)
        root.addLayout(footer)

    # ── Nota seleccionada / origen (caja o cuenta segun metodo) ──────────────

    def _on_nota_cambiada(self) -> None:
        nota = self._nota_seleccionada()
        maximo = float(nota.saldo_disponible) if nota else 0.0
        self.monto_input.setRange(0.01, maximo if maximo > 0 else 0.01)
        self.monto_input.setValue(maximo)

    def _nota_seleccionada(self) -> NotaCreditoCliente | None:
        id_nota = self.nota_combo.currentData()
        return next((n for n in self.notas_disponibles if n.id_nota_credito == id_nota), None)

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
        es_efectivo = metodo == "efectivo"
        self.origen_combo.blockSignals(True)
        self.origen_combo.clear()
        if es_efectivo:
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
                    etiqueta = f"{nombre_banco} - {cuenta.numero_cuenta}"
                    self.origen_combo.addItem(etiqueta, ("banco", cuenta.id_cuenta))
        self.origen_combo.blockSignals(False)

    # ── Confirmar ─────────────────────────────────────────────────────────

    def _confirmar(self) -> None:
        nota = self._nota_seleccionada()
        origen = self.origen_combo.currentData()
        if nota is None:
            return
        if origen is None:
            MessageBox.warning(self, "Origen requerido", "No hay caja abierta ni cuenta bancaria activa disponible.")
            return

        metodo = self.metodo_combo.currentData()
        monto = self.monto_input.value()
        tipo_origen, id_origen = origen

        mensaje = (
            f"Se va a devolver ${monto:,.2f} de la nota {nota.numero_nota_credito}. "
            "Un supervisor debe autorizar esta devolución."
        )
        es_bancario = metodo != "efectivo"
        motivo_label = "Número de referencia bancaria" if es_bancario else "Motivo de la devolución"
        dialogo = AutorizacionDialog(
            self.session,
            recurso="notas_credito",
            accion="editar",
            mensaje=mensaje,
            titulo="Autorización de devolución requerida",
            motivo_label=motivo_label,
            motivo_min_length=4 if es_bancario else 1,
            motivo_max_length=50 if es_bancario else None,
            parent=self,
        )
        if dialogo.exec() != QDialog.DialogCode.Accepted or dialogo.usuario_autorizador is None:
            return

        try:
            self.nota_actualizada = NotaCreditoService.devolver_nota_credito_cliente(
                self.session,
                id_nota_credito=nota.id_nota_credito,
                monto=monto,
                metodo_devolucion=metodo,
                id_caja=id_origen if tipo_origen == "caja" else None,
                id_cuenta_bancaria=id_origen if tipo_origen == "banco" else None,
                referencia=dialogo.motivo if metodo != "efectivo" else None,
                id_autorizador=dialogo.usuario_autorizador.id_usuario,
                id_usuario=self.id_usuario,
            )
        except ValueError as exc:
            self.session.rollback()
            MessageBox.warning(self, "No se pudo devolver la nota de crédito", str(exc))
            return
        except PermisoDenegadoError:
            self.session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tiene permiso para devolver notas de crédito.")
            return

        self.accept()
