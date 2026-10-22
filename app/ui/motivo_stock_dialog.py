"""Diálogo para ingresar el motivo de un movimiento de stock."""

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.message_box import MessageBox
from app.ui.pantalla import ajustar_tamano
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_DANGER,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MEDIUM,
)


class MotivoStockDialog(QDialog):
    """Diálogo para ingresar el motivo de un movimiento de stock."""

    def __init__(self, producto_nombre: str, valor_anterior: float, valor_nuevo: float, parent=None):
        super().__init__(parent)
        self.producto_nombre = producto_nombre
        self.valor_anterior = valor_anterior
        self.valor_nuevo = valor_nuevo
        self.motivo = ""

        diferencia = self.valor_nuevo - self.valor_anterior
        self.es_aumento = diferencia > 0

        self.setWindowTitle("Motivo del Movimiento de Stock")
        ajustar_tamano(self, 500, 300, 450, 250)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(24)

        # Header con icono
        header_layout = QHBoxLayout()
        header_layout.setSpacing(16)

        # Icono según tipo de movimiento
        icon_container = QWidget()
        icon_container.setFixedSize(64, 64)
        icon_container.setStyleSheet(
            f"background-color: {COLOR_SUCCESS if self.es_aumento else COLOR_DANGER}; border-radius: 32px;"
        )
        icon_layout = QVBoxLayout(icon_container)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_name = "fa5s.arrow-up" if self.es_aumento else "fa5s.arrow-down"
        icon_color = "white"
        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon(icon_name, color=icon_color).pixmap(32, 32))
        icon_layout.addWidget(icon_lbl)
        header_layout.addWidget(icon_container)

        # Título y descripción
        titulo_layout = QVBoxLayout()
        titulo_layout.setSpacing(4)

        titulo = QLabel("Movimiento de Stock")
        titulo.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        titulo_layout.addWidget(titulo)

        tipo_texto = "Aumento de Stock" if self.es_aumento else "Disminución de Stock"
        tipo_label = QLabel(tipo_texto)
        tipo_label.setStyleSheet(
            f"font-size: 13px; color: {COLOR_SUCCESS if self.es_aumento else COLOR_DANGER}; font-weight: 600;"
        )
        titulo_layout.addWidget(tipo_label)

        header_layout.addLayout(titulo_layout)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Campo de motivo
        motivo_container = QWidget()
        motivo_layout = QVBoxLayout(motivo_container)
        motivo_layout.setSpacing(8)

        lbl_motivo = QLabel("Motivo del movimiento:")
        lbl_motivo.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        motivo_layout.addWidget(lbl_motivo)

        self.motivo_input = QLineEdit()
        self.motivo_input.setPlaceholderText("Ingrese el motivo (ej: Ajuste de inventario, Devolución, etc.)")
        self.motivo_input.setMinimumHeight(50)
        self.motivo_input.setStyleSheet(
            f"""
            QLineEdit {{
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
                padding: 12px 16px;
                font-size: 13px;
                background-color: white;
            }}
            QLineEdit:focus {{
                border: 2px solid {COLOR_PRIMARY};
            }}
            """
        )
        motivo_layout.addWidget(self.motivo_input)

        layout.addWidget(motivo_container)

        # Botones
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        button_layout.addStretch()

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setIcon(qta.icon("fa5s.times", color=COLOR_TEXT_MEDIUM))
        btn_cancelar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_cancelar.setMinimumHeight(40)
        btn_cancelar.clicked.connect(self.reject)
        button_layout.addWidget(btn_cancelar)

        btn_aceptar = QPushButton("Aceptar")
        btn_aceptar.setIcon(qta.icon("fa5s.check", color="white"))
        btn_aceptar.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_aceptar.setMinimumHeight(40)
        btn_aceptar.clicked.connect(self._aceptar)
        button_layout.addWidget(btn_aceptar)

        layout.addLayout(button_layout)

    def _aceptar(self):
        motivo = self.motivo_input.text().strip()
        if not motivo:
            MessageBox.warning(self, "Dato requerido", "Debe ingresar un motivo para el movimiento de stock.")
            self.motivo_input.setFocus()
            return

        self.motivo = motivo
        self.accept()

    def get_motivo(self) -> str:
        return self.motivo
