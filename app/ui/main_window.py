"""
MainWindow — Ventana principal del ERP moderno.
Arquitectura:
    ┌─────────────────────────────────────────────┐
    │  Sidebar (fijo)  │  TopBar                  │
    │                  ├──────────────────────────│
    │                  │  ContentArea (QStackedWidget) │
    └─────────────────────────────────────────────┘

La sidebar emite la señal `modulo_seleccionado` → MainWindow conmuta la vista
en el QStackedWidget.  Los paneles se crean con lazy-loading la primera vez
que se accede a cada módulo para minimizar el tiempo de arranque.
"""

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.db.models import ConfiguracionEmpresa, Usuario
from app.db.session import SessionLocal
from app.ui.clientes_panel import ClientesPanel
from app.ui.config_empresa_panel import ConfigEmpresaPanel
from app.ui.placeholder_view import PlaceholderView
from app.ui.sidebar import Sidebar
from app.ui.styles import GLOBAL_QSS, TOPBAR_HEIGHT
from app.ui.topbar import TopBar

logger = logging.getLogger(__name__)

# Configuración de cada módulo: (clave, nombre_display, icono, clase_panel|None)
# Si clase_panel es None → se usa PlaceholderView automáticamente.
MODULOS_CONFIG = {
    "clientes":          ("Clientes",               ClientesPanel),
    "proveedores":       ("Proveedores",             None),
    "inventario":        ("Inventario",              None),
    "facturacion":       ("Facturación",             None),
    "compras":           ("Compras",                 None),
    "bancos":            ("Bancos",                  None),
    "cuentas_bancarias": ("Cuentas Bancarias",        None),
    "cajas":             ("Cajas",                   None),
    "vendedores":        ("Vendedores",              None),
    "comisiones":        ("Comisiones",              None),
    "control_tasas":     ("Control de Tasas",        None),
    "config_empresa":    ("Configuración de Empresa", ConfigEmpresaPanel),
    "usuarios":          ("Usuarios",                None),
}


class MainWindow(QMainWindow):
    def __init__(self, usuario: Usuario):
        super().__init__()
        self.usuario = usuario
        self._paneles: dict[str, QWidget] = {}   # cache lazy de paneles

        self.setWindowTitle("ERP — Sistema de Gestión Administrativa")
        self.resize(1200, 720)
        self.setMinimumSize(900, 600)

        # Aplicar estilos globales
        self.setStyleSheet(GLOBAL_QSS)

        empresa = self._obtener_nombre_empresa()
        self._setup_ui(empresa)
        self._ir_a_modulo("clientes")

    # ── Construcción del layout principal ────────────────────────────────

    def _setup_ui(self, empresa_nombre: str) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        main_h = QHBoxLayout(central)
        main_h.setContentsMargins(0, 0, 0, 0)
        main_h.setSpacing(0)

        # Sidebar
        self.sidebar = Sidebar(empresa_nombre)
        self.sidebar.modulo_seleccionado.connect(self._ir_a_modulo)
        main_h.addWidget(self.sidebar)

        # Área derecha: TopBar + contenido
        right_w = QWidget()
        right_v = QVBoxLayout(right_w)
        right_v.setContentsMargins(0, 0, 0, 0)
        right_v.setSpacing(0)

        self.topbar = TopBar(self.usuario)
        right_v.addWidget(self.topbar)

        self.stack = QStackedWidget()
        right_v.addWidget(self.stack)

        main_h.addWidget(right_w)

    # ── Conmutador de vistas ─────────────────────────────────────────────

    def _ir_a_modulo(self, clave: str) -> None:
        panel = self._obtener_o_crear_panel(clave)
        self.stack.setCurrentWidget(panel)
        self.topbar.actualizar_modulo(clave)

    def _obtener_o_crear_panel(self, clave: str) -> QWidget:
        """Lazy-load: crea el panel solo la primera vez que se solicita."""
        if clave not in self._paneles:
            nombre, clase_panel = MODULOS_CONFIG.get(clave, (clave.title(), None))
            if clase_panel is not None:
                panel = clase_panel(SessionLocal, self.usuario)
            else:
                panel = PlaceholderView(nombre)

            self._paneles[clave] = panel
            self.stack.addWidget(panel)

        return self._paneles[clave]

    # ── Helpers ──────────────────────────────────────────────────────────

    def _obtener_nombre_empresa(self) -> str:
        """Obtiene el nombre de la empresa desde la tabla configuracion_empresa."""
        session = SessionLocal()
        try:
            config = session.query(ConfiguracionEmpresa).first()
            if config and config.razon_social_empresa:
                return config.razon_social_empresa
        except Exception:
            logger.exception("No se pudo cargar el nombre de la empresa")
        finally:
            session.close()
        return "Mi Empresa"
