"""
Pestaña "Apariencia" del módulo Configuración: preferencias de esta PC (no de la empresa), como
reducir las animaciones. Se guardan en un JSON local (ver app/ui/animaciones.py), así que cada
estación elige las suyas y no hace falta ningún permiso.
"""

from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWidget

from app.ui import animaciones
from app.ui.styles import COLOR_BORDER, COLOR_CARD_BG, COLOR_CONTENT_BG, COLOR_TEXT_DARK, COLOR_TEXT_MUTED


class ConfigAparienciaPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

        tarjeta = QWidget()
        tarjeta.setObjectName("SectionCard")
        tarjeta.setStyleSheet(
            f"QWidget#SectionCard {{ background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER};"
            " border-radius: 10px; }"
        )
        layout_tarjeta = QVBoxLayout(tarjeta)
        layout_tarjeta.setContentsMargins(20, 18, 20, 18)
        layout_tarjeta.setSpacing(10)

        titulo = QLabel("Animaciones")
        titulo.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {COLOR_TEXT_DARK}; border: none; background: transparent;"
        )
        layout_tarjeta.addWidget(titulo)

        self.chk_reducir = QCheckBox("Reducir animaciones en esta PC")
        self.chk_reducir.setStyleSheet(f"color: {COLOR_TEXT_DARK}; font-size: 13px; border: none;")
        self.chk_reducir.setChecked(animaciones.reducir_animaciones())
        self.chk_reducir.toggled.connect(animaciones.establecer_reducir_animaciones)
        layout_tarjeta.addWidget(self.chk_reducir)

        nota = QLabel(
            "Desactiva los avisos con movimiento, la aparición suave de ventanas y los efectos del panel general. "
            "Conviene en equipos lentos. En una sesión de Escritorio remoto ya van desactivadas."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px; border: none; background: transparent;")
        layout_tarjeta.addWidget(nota)

        if animaciones.sesion_remota():
            remota = QLabel("Esta sesión es de Escritorio remoto: las animaciones están desactivadas.")
            remota.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px; border: none; background: transparent;")
            layout_tarjeta.addWidget(remota)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 16, 0, 0)
        raiz.addWidget(tarjeta)
        raiz.addStretch()
