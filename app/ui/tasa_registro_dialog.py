"""Dialogo minimo para registrar la tasa de cambio del dia -- mismo patron que
caja_apertura_dialog.py (tarjeta unica + footer). A diferencia de otros formularios de
alta, TasaService no tiene actualizar/eliminar: cada registro es un snapshot historico
inmutable (ver app/services/tasas.py), asi que este dialogo tampoco tiene modo edicion."""

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
QDoubleSpinBox {{
    background-color: #FFFFFF;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
    min-height: 20px;
}}
QDoubleSpinBox:focus {{
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


class TasaRegistroDialog(QDialog):
    """Tras exec() == Accepted, `get_data()` devuelve los 3 valores listos para pasar a
    TasaService.registrar_tasa(). Paralelo/COP quedan en None si se dejan en 0 -- son
    opcionales (no toda venta se cobra en esas monedas)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Registrar Tasa del Día")
        self.setFixedSize(420, 380)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.exchange-alt", color=COLOR_PRIMARY).pixmap(QSize(20, 20)))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(34, 34)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        titulos = QVBoxLayout()
        titulos.setSpacing(1)
        lbl_titulo = QLabel("Registrar Tasa del Día")
        lbl_titulo.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        lbl_subtitulo = QLabel("Queda como un registro histórico nuevo, no reemplaza el anterior.")
        lbl_subtitulo.setWordWrap(True)
        lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        titulos.addWidget(lbl_titulo)
        titulos.addWidget(lbl_subtitulo)
        header.addWidget(icon_lbl)
        header.addLayout(titulos, stretch=1)
        root.addLayout(header)

        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        lbl_bcv = QLabel("Tasa BCV (Bs./USD) <span style='color: #DC2626;'>*</span>")
        lbl_bcv.setProperty("class", "FormLabel")
        self.bcv_input = QDoubleSpinBox()
        self.bcv_input.setRange(0, 9_999_999.99)
        self.bcv_input.setDecimals(2)
        self.bcv_input.setFixedHeight(32)
        layout.addWidget(lbl_bcv)
        layout.addWidget(self.bcv_input)

        lbl_paralelo = QLabel("Dólar paralelo (Bs./USD)")
        lbl_paralelo.setProperty("class", "FormLabel")
        self.paralelo_input = QDoubleSpinBox()
        self.paralelo_input.setRange(0, 9_999_999.99)
        self.paralelo_input.setDecimals(2)
        self.paralelo_input.setFixedHeight(32)
        layout.addWidget(lbl_paralelo)
        layout.addWidget(self.paralelo_input)

        lbl_cop = QLabel("Peso colombiano (COP/USD)")
        lbl_cop.setProperty("class", "FormLabel")
        self.cop_input = QDoubleSpinBox()
        self.cop_input.setRange(0, 99_999_999.99)
        self.cop_input.setDecimals(2)
        self.cop_input.setFixedHeight(32)
        layout.addWidget(lbl_cop)
        layout.addWidget(self.cop_input)

        root.addWidget(card, stretch=1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 4, 0, 0)
        footer.setSpacing(10)
        footer.addStretch()

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setIcon(qta.icon("fa5s.times", color="#475569"))
        btn_cancelar.setObjectName("BtnSecondary")
        btn_cancelar.setFixedHeight(36)
        btn_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancelar.setAutoDefault(False)
        btn_cancelar.clicked.connect(self.reject)

        btn_guardar = QPushButton("Registrar")
        btn_guardar.setIcon(qta.icon("fa5s.save", color="#FFFFFF"))
        btn_guardar.setObjectName("BtnPrimary")
        btn_guardar.setFixedHeight(36)
        btn_guardar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_guardar.setAutoDefault(False)
        btn_guardar.clicked.connect(self._validar_y_aceptar)

        footer.addWidget(btn_cancelar)
        footer.addWidget(btn_guardar)
        root.addLayout(footer)

    def _validar_y_aceptar(self) -> None:
        if self.bcv_input.value() <= 0:
            QMessageBox.warning(self, "Dato requerido", "La tasa BCV es obligatoria y debe ser mayor a cero.")
            self.bcv_input.setFocus()
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "tasa_bcv": self.bcv_input.value(),
            "tasa_paralelo": self.paralelo_input.value() or None,
            "tasa_cop": self.cop_input.value() or None,
        }
