"""
TopBar: barra superior del ERP con breadcrumb del módulo activo, búsqueda global
y notificaciones. La info del usuario autenticado vive en el pie de la sidebar
(ver `sidebar.py`), no aquí.
"""

import qtawesome as qta
from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QWidget,
)

from app.db.models import Usuario
from app.ui.styles import (
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    TOPBAR_HEIGHT,
    TOPBAR_QSS,
)

# Títulos presentables para cada módulo
TITULOS = {
    "panel_general": "Panel General",
    "clientes": "Clientes",
    "proveedores": "Proveedores",
    "inventario": "Inventario",
    "facturacion": "Facturación / Ventas",
    "compras": "Compras",
    "bancos": "Bancos",
    "cuentas_bancarias": "Cuentas Bancarias",
    "cajas": "Cajas",
    "vendedores": "Vendedores",
    "comisiones": "Comisiones",
    "control_tasas": "Tasas de Cambio",
    "config_empresa": "Configuración de Empresa",
    "usuarios": "Usuarios",
}


class TopBar(QWidget):
    """Barra superior con breadcrumb de módulo activo, búsqueda y notificaciones."""

    busqueda_global = Signal(str)

    def __init__(self, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.setObjectName("TopBar")
        self.setFixedHeight(TOPBAR_HEIGHT)
        self.setStyleSheet(TOPBAR_QSS)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(16)

        layout.addWidget(self._make_breadcrumb())

        spacer = QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout.addSpacerItem(spacer)

        self.buscar_input = QLineEdit()
        self.buscar_input.setPlaceholderText("Buscar en el sistema…")
        self.buscar_input.addAction(qta.icon("fa5s.search", color="#94A3B8"), QLineEdit.ActionPosition.LeadingPosition)
        self.buscar_input.setObjectName("TopBarSearch")
        self.buscar_input.setFixedWidth(240)
        self.buscar_input.setFixedHeight(36)
        self.buscar_input.textChanged.connect(self.busqueda_global.emit)
        layout.addWidget(self.buscar_input)

        btn_notif = QPushButton()
        btn_notif.setIcon(qta.icon("fa5s.bell", color="#64748B"))
        btn_notif.setIconSize(QSize(18, 18))
        btn_notif.setObjectName("TopBarBtn")
        btn_notif.setFixedSize(38, 38)
        btn_notif.setToolTip("Notificaciones")
        layout.addWidget(btn_notif)

    def _make_breadcrumb(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        lbl_raiz = QLabel("Módulos")
        lbl_raiz.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED}; background: transparent;")

        lbl_sep = QLabel("›")
        lbl_sep.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED}; background: transparent;")

        self.lbl_titulo = QLabel("Panel General")
        self.lbl_titulo.setObjectName("TopBarTitle")
        self.lbl_titulo.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {COLOR_TEXT_DARK}; background: transparent;"
        )

        h.addWidget(lbl_raiz)
        h.addWidget(lbl_sep)
        h.addWidget(self.lbl_titulo)
        return w

    def actualizar_modulo(self, clave: str) -> None:
        """Actualiza el título del módulo activo en el breadcrumb."""
        titulo = TITULOS.get(clave, clave.replace("_", " ").title())
        self.lbl_titulo.setText(titulo)
