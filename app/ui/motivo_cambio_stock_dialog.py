"""Diálogo para capturar el motivo de cambio de stock."""

import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.ui.pantalla import ajustar_tamano, hacer_desplazable
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_PRIMARY,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    FONT_FAMILY,
)


class MotivoCambioStockDialog(QDialog):
    """Diálogo para ingresar el motivo del cambio de stock."""

    def __init__(self, tipo_cambio: str, parent=None):
        """
        Args:
            tipo_cambio: "AUMENTO" o "DISMINUCIÓN"
        """
        super().__init__(parent)
        self.tipo_cambio = tipo_cambio
        self.setWindowTitle(f"Motivo de {tipo_cambio.lower()} de Stock")
        ajustar_tamano(self, 500, 300)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLOR_CONTENT_BG};
                font-family: '{FONT_FAMILY}', Arial, sans-serif;
            }}
        """)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()
        hacer_desplazable(self)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # Header
        header = QWidget()
        header.setStyleSheet("background: transparent;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        icon_lbl = QLabel()
        icono = "fa5s.arrow-up" if self.tipo_cambio == "AUMENTO" else "fa5s.arrow-down"
        color = "#10B981" if self.tipo_cambio == "AUMENTO" else "#EF4444"
        icon_lbl.setPixmap(qta.icon(icono, color=color).pixmap(QSize(24, 24)))
        icon_lbl.setStyleSheet(
            f"background-color: {COLOR_CONTENT_BG}; border: 2px solid {COLOR_BORDER}; border-radius: 8px; padding: 8px;"
        )
        icon_lbl.setFixedSize(40, 40)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titulo_layout = QVBoxLayout()
        titulo_layout.setSpacing(2)
        titulo_layout.setContentsMargins(0, 0, 0, 0)

        lbl_titulo = QLabel(f"Motivo de {self.tipo_cambio.lower()} de Stock")
        lbl_titulo.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        lbl_subtitulo = QLabel("Describa el motivo de este cambio de inventario.")
        lbl_subtitulo.setStyleSheet(f"font-size: 13px; color: {COLOR_TEXT_MUTED};")

        titulo_layout.addWidget(lbl_titulo)
        titulo_layout.addWidget(lbl_subtitulo)

        header_layout.addWidget(icon_lbl)
        header_layout.addLayout(titulo_layout)
        header_layout.addStretch()

        root.addWidget(header)

        # Text area para el motivo
        card = QWidget()
        card.setStyleSheet(f"background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 8px;")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        card_layout.setSpacing(8)

        lbl_instruccion = QLabel("Motivo del cambio:")
        lbl_instruccion.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_DARK};")

        self.motivo_input = QTextEdit()
        self.motivo_input.setPlaceholderText(
            "Ej: Ajuste por inventario físico, mercancía devuelta, venta directa, etc."
        )
        self.motivo_input.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLOR_CONTENT_BG};
                border: 1px solid {COLOR_BORDER};
                border-radius: 6px;
                padding: 10px;
                font-size: 13px;
                color: {COLOR_TEXT_DARK};
            }}
            QTextEdit:focus {{
                border: 2px solid {COLOR_PRIMARY};
            }}
        """)
        self.motivo_input.setMinimumHeight(100)

        card_layout.addWidget(lbl_instruccion)
        card_layout.addWidget(self.motivo_input)

        root.addWidget(card)
        root.addStretch()

        # Footer con botones
        footer = QWidget()
        footer.setStyleSheet("background: transparent;")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(10)
        footer_layout.addStretch()

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setIcon(qta.icon("fa5s.times", color="#64748B"))
        btn_cancelar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_cancelar.setFixedHeight(38)
        btn_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancelar.clicked.connect(self.reject)

        btn_aceptar = QPushButton("Confirmar Cambio")
        btn_aceptar.setIcon(qta.icon("fa5s.check", color="#FFFFFF"))
        btn_aceptar.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_aceptar.setFixedHeight(38)
        btn_aceptar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_aceptar.clicked.connect(self._validar_y_aceptar)

        footer_layout.addWidget(btn_cancelar)
        footer_layout.addWidget(btn_aceptar)

        root.addWidget(footer)

    def _validar_y_aceptar(self):
        motivo = self.motivo_input.toPlainText().strip()
        if not motivo:
            from app.ui.message_box import MessageBox

            MessageBox.warning(self, "Dato requerido", "Debe ingresar el motivo del cambio de stock.")
            self.motivo_input.setFocus()
            return
        self.accept()

    def get_motivo(self) -> str:
        return self.motivo_input.toPlainText().strip()
