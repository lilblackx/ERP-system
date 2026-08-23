"""
TopBar: barra superior del ERP con título de vista activa, búsqueda global,
notificaciones y perfil de usuario.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from app.db.models import Usuario
from app.ui.styles import (
    COLOR_PRIMARY,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    TOPBAR_HEIGHT,
    TOPBAR_QSS,
)

# Títulos presentables para cada módulo
TITULOS = {
    "clientes":          "Clientes",
    "proveedores":       "Proveedores",
    "inventario":        "Inventario",
    "facturacion":       "Facturación / Ventas",
    "compras":           "Compras",
    "bancos":            "Bancos",
    "cuentas_bancarias": "Cuentas Bancarias",
    "cajas":             "Cajas",
    "vendedores":        "Vendedores",
    "comisiones":        "Comisiones",
    "control_tasas":     "Control de Tasas",
    "config_empresa":    "Configuración de Empresa",
    "usuarios":          "Usuarios",
}


class TopBar(QWidget):
    """Barra superior con título de módulo, búsqueda, notificaciones y perfil."""

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

        # Título del módulo activo
        self.lbl_titulo = QLabel("Panel de Control")
        self.lbl_titulo.setObjectName("TopBarTitle")
        self.lbl_titulo.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};"
        )

        # Spacer flexible
        spacer = QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        # Barra de búsqueda global
        self.buscar_input = QLineEdit()
        self.buscar_input.setPlaceholderText("   🔍  Buscar en el sistema…")
        self.buscar_input.setObjectName("TopBarSearch")
        self.buscar_input.setFixedWidth(240)
        self.buscar_input.setFixedHeight(36)
        self.buscar_input.textChanged.connect(self.busqueda_global.emit)

        # Botón de notificaciones
        btn_notif = QPushButton("🔔")
        btn_notif.setObjectName("TopBarBtn")
        btn_notif.setFixedSize(38, 38)
        btn_notif.setToolTip("Notificaciones")

        # Info de usuario
        user_widget = self._make_user_widget()

        layout.addWidget(self.lbl_titulo)
        layout.addSpacerItem(spacer)
        layout.addWidget(self.buscar_input)
        layout.addWidget(btn_notif)
        layout.addWidget(user_widget)

    def _make_user_widget(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        avatar = QLabel("👤")
        avatar.setStyleSheet(
            f"font-size: 22px; background-color: #EFF6FF;"
            f" border: 2px solid #BFDBFE; border-radius: 18px;"
            " width: 36px; height: 36px; padding: 2px;"
        )
        avatar.setFixedSize(38, 38)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        info_w = QWidget()
        info_w.setStyleSheet("background: transparent;")
        info_v = QVBoxLayout(info_w)
        info_v.setContentsMargins(0, 0, 0, 0)
        info_v.setSpacing(0)

        nombre = self.usuario.nombre or self.usuario.nombre_usuario
        rol = self.usuario.rol.nombre if self.usuario.rol else "Usuario"

        lbl_nombre = QLabel(nombre[:20])
        lbl_nombre.setObjectName("UserLabel")

        lbl_rol = QLabel(rol)
        lbl_rol.setObjectName("UserRole")

        info_v.addWidget(lbl_nombre)
        info_v.addWidget(lbl_rol)

        h.addWidget(avatar)
        h.addWidget(info_w)
        return w

    def actualizar_modulo(self, clave: str) -> None:
        """Actualiza el título del módulo activo en la topbar."""
        titulo = TITULOS.get(clave, clave.replace("_", " ").title())
        self.lbl_titulo.setText(titulo)
