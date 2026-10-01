"""
Módulo Configuración: contenedor de pestañas. "Empresa" es el panel que ya existía
(ConfigEmpresaPanel, sin cambios); "Licencia" es nueva. Se expone `licencia_panel` para que
MainWindow conecte su señal `estado_cambiado`.
"""

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from app.db.models import Usuario
from app.ui.config_empresa_panel import ConfigEmpresaPanel
from app.ui.config_licencia_panel import LicenciaPanel
from app.ui.styles import COLOR_CONTENT_BG, TABS_QSS


class ConfiguracionPanel(QWidget):
    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.setObjectName("ContentArea")
        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

        self.empresa_panel = ConfigEmpresaPanel(session_factory, usuario)
        self.licencia_panel = LicenciaPanel(session_factory, usuario)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(TABS_QSS)
        self.tabs.addTab(self.empresa_panel, "Empresa")
        self.tabs.addTab(self.licencia_panel, "Licencia")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 20, 40, 0)
        layout.addWidget(self.tabs)
