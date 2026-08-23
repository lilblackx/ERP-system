"""
Widget genérico de placeholder para módulos sin implementación completa.
Sirve como vista temporal mostrando el nombre del módulo y un mensaje de estado.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.ui.styles import (
    COLOR_BORDER,
    COLOR_CONTENT_BG,
    COLOR_PRIMARY,
    COLOR_TEXT_MUTED,
)


class PlaceholderView(QWidget):
    """Vista genérica reutilizable para módulos en construcción."""

    def __init__(self, modulo_nombre: str, parent=None):
        super().__init__(parent)
        self.setObjectName("ContentArea")
        self._build_ui(modulo_nombre)

    def _build_ui(self, nombre: str) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(16)

        container = QWidget()
        container.setObjectName("Card")
        container.setFixedSize(420, 200)
        container.setStyleSheet(f"""
            QWidget#Card {{
                background-color: white;
                border: 1px solid {COLOR_BORDER};
                border-radius: 16px;
            }}
        """)

        inner = QVBoxLayout(container)
        inner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.setSpacing(14)

        lbl_titulo = QLabel(nombre)
        lbl_titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_titulo.setStyleSheet(
            f"font-size: 22px; font-weight: bold; color: {COLOR_PRIMARY};"
            " background: transparent; border: none;"
        )

        lbl_desc = QLabel("Este modulo esta en desarrollo.\nPronto estara disponible.")
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(
            f"font-size: 13px; color: {COLOR_TEXT_MUTED}; line-height: 1.5;"
            " background: transparent; border: none;"
        )

        inner.addWidget(lbl_titulo)
        inner.addWidget(lbl_desc)

        layout.addWidget(container)
        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

