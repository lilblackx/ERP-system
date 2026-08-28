"""Dialogo para aplicar (total o parcialmente) una nota de credito de cliente disponible
como abono a otra factura del mismo cliente que todavia tenga saldo pendiente -- ver
NotaCreditoService.aplicar_nota_credito_cliente(). Es una transferencia contable interna
(no mueve caja/banco: el dinero ya entro fisicamente cuando se cobro la factura que
origino la nota), asi que a diferencia de PagoLineaDialog no pide metodo de pago ni
origen, solo que nota y que factura.

`notas_disponibles`/`facturas_pendientes` se cargan afuera (HistorialClienteWindow, que
ya tiene ambas listas del cliente) para no reconsultar la base desde este dialogo."""

import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from app.db.models import NotaCreditoCliente
from app.services.notas_credito import NotaCreditoService
from app.services.permisos import PermisoDenegadoError
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
    COLOR_TEXT_MUTED,
    FONT_FAMILY,
    ICON_CHEVRON_DOWN_URL,
    ICON_CHEVRON_UP_URL,
    ComboBoxSinScroll,
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


class AplicarNotaCreditoDialog(QDialog):
    """Al aceptar, `nota_actualizada` queda poblada con el resultado de
    NotaCreditoService.aplicar_nota_credito_cliente()."""

    def __init__(
        self,
        session: Session,
        id_usuario: int | None,
        notas_disponibles: list[NotaCreditoCliente],
        facturas_pendientes: list[dict],
        parent=None,
    ):
        super().__init__(parent)
        self.session = session
        self.id_usuario = id_usuario
        self.notas_disponibles = notas_disponibles
        self.facturas_pendientes = facturas_pendientes
        self.nota_actualizada: NotaCreditoCliente | None = None

        self.setWindowTitle("Aplicar Nota de Crédito")
        self.setMinimumWidth(420)
        self.resize(420, 340)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()
        self._on_seleccion_cambiada()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.receipt", color=COLOR_PRIMARY).pixmap(QSize(20, 20)))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(34, 34)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_titulo = QLabel("Aplicar Nota de Crédito")
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
        self.nota_combo.currentIndexChanged.connect(self._on_seleccion_cambiada)
        card_layout.addWidget(lbl_nota)
        card_layout.addWidget(self.nota_combo)

        lbl_factura = QLabel("Factura destino <span style='color: #DC2626;'>*</span>")
        lbl_factura.setProperty("class", "FormLabel")
        self.factura_combo = ComboBoxSinScroll()
        self.factura_combo.setFixedHeight(32)
        for factura in self.facturas_pendientes:
            etiqueta = f"{factura['numero_factura']} — pendiente ${float(factura['saldo_pendiente']):,.2f}"
            self.factura_combo.addItem(etiqueta, (factura["id_factura"], float(factura["saldo_pendiente"])))
        self.factura_combo.currentIndexChanged.connect(self._on_seleccion_cambiada)
        card_layout.addWidget(lbl_factura)
        card_layout.addWidget(self.factura_combo)

        lbl_monto = QLabel("Monto a aplicar <span style='color: #DC2626;'>*</span>")
        lbl_monto.setProperty("class", "FormLabel")
        self.monto_input = QDoubleSpinBox()
        self.monto_input.setDecimals(2)
        self.monto_input.setFixedHeight(32)
        card_layout.addWidget(lbl_monto)
        card_layout.addWidget(self.monto_input)

        self.lbl_ayuda = QLabel()
        self.lbl_ayuda.setWordWrap(True)
        self.lbl_ayuda.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_MUTED};")
        card_layout.addWidget(self.lbl_ayuda)

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

        self.btn_aplicar = QPushButton("Aplicar")
        self.btn_aplicar.setIcon(qta.icon("fa5s.check", color="#FFFFFF"))
        self.btn_aplicar.setObjectName("BtnPrimary")
        self.btn_aplicar.setFixedHeight(34)
        self.btn_aplicar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_aplicar.setAutoDefault(False)
        self.btn_aplicar.clicked.connect(self._confirmar)

        footer.addWidget(btn_cancelar)
        footer.addWidget(self.btn_aplicar)
        root.addLayout(footer)

    def _on_seleccion_cambiada(self) -> None:
        id_nota = self.nota_combo.currentData()
        origen_factura = self.factura_combo.currentData()
        nota = next((n for n in self.notas_disponibles if n.id_nota_credito == id_nota), None)
        if nota is None or origen_factura is None:
            self.monto_input.setRange(0, 0)
            self.btn_aplicar.setEnabled(False)
            self.lbl_ayuda.setText("No hay notas de crédito o facturas con saldo pendiente disponibles.")
            return

        _, saldo_pendiente_factura = origen_factura
        maximo = min(float(nota.saldo_disponible), saldo_pendiente_factura)
        self.monto_input.setRange(0.01, maximo if maximo > 0 else 0.01)
        self.monto_input.setValue(maximo)
        self.btn_aplicar.setEnabled(maximo > 0)
        self.lbl_ayuda.setText(
            f"Disponible en la nota: ${float(nota.saldo_disponible):,.2f} · "
            f"Pendiente en la factura: ${saldo_pendiente_factura:,.2f}"
        )

    def _confirmar(self) -> None:
        id_nota = self.nota_combo.currentData()
        origen_factura = self.factura_combo.currentData()
        if id_nota is None or origen_factura is None:
            return
        id_factura_destino, _ = origen_factura

        try:
            self.nota_actualizada = NotaCreditoService.aplicar_nota_credito_cliente(
                self.session,
                id_nota_credito=id_nota,
                id_factura_destino=id_factura_destino,
                monto=self.monto_input.value(),
                id_usuario=self.id_usuario,
            )
        except ValueError as exc:
            self.session.rollback()
            QMessageBox.warning(self, "No se pudo aplicar la nota de crédito", str(exc))
            return
        except PermisoDenegadoError:
            self.session.rollback()
            QMessageBox.warning(self, "Sin permiso", "No tiene permiso para aplicar notas de crédito.")
            return

        self.accept()
