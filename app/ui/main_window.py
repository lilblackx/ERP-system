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

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.db.models import ConfiguracionEmpresa, Usuario
from app.db.session import SessionLocal
from app.services.usuarios import UsuarioService
from app.ui.clientes_panel import ClientesPanel
from app.ui.config_empresa_panel import ConfigEmpresaPanel
from app.ui.dashboard_panel import DashboardPanel
from app.ui.facturacion_panel import FacturacionPanel
from app.ui.inventario_panel import InventarioPanel
from app.ui.placeholder_view import PlaceholderView
from app.ui.sidebar import Sidebar
from app.ui.styles import GLOBAL_QSS
from app.ui.tasa_ticker import TasaTicker
from app.ui.tasas_panel import TasasPanel
from app.ui.topbar import TopBar
from app.ui.usuarios_panel import UsuariosPanel
from app.ui.vendedores_panel import VendedoresPanel

logger = logging.getLogger(__name__)

# Configuración de cada módulo: (clave, nombre_display, icono, clase_panel|None)
# Si clase_panel es None → se usa PlaceholderView automáticamente.
MODULOS_CONFIG = {
    "panel_general": ("Panel General", DashboardPanel),
    "clientes": ("Clientes", ClientesPanel),
    "proveedores": ("Proveedores", None),
    "inventario": ("Inventario", InventarioPanel),
    "facturacion": ("Facturación", FacturacionPanel),
    "compras": ("Compras", None),
    "bancos": ("Bancos", None),
    "cuentas_bancarias": ("Cuentas Bancarias", None),
    "cajas": ("Cajas", None),
    "vendedores": ("Vendedores", VendedoresPanel),
    "comisiones": ("Comisiones", None),
    "control_tasas": ("Control de Tasas", TasasPanel),
    "config_empresa": ("Configuración de Empresa", ConfigEmpresaPanel),
    "usuarios": ("Usuarios", UsuariosPanel),
}

# Permiso (recurso, accion) que un usuario necesita para VER cada modulo en el sidebar --
# separado del RBAC real que ya protegen los servicios (require_permiso, la unica barrera
# de seguridad de verdad): esto es solo para no mostrar en el menu un modulo al que el
# usuario va a chocar con un "sin permiso" apenas entre (2026-08-27, a raiz del rol
# CAJERO). 'ver' en todos los casos porque lo minimo para que un modulo tenga sentido en
# el menu es poder consultarlo -- un rol con 'crear' pero no 'ver' sobre algo no existe en
# ningun caso real hoy.
MODULO_PERMISO: dict[str, tuple[str, str]] = {
    "panel_general": ("dashboard", "ver"),
    "clientes": ("clientes", "ver"),
    "proveedores": ("proveedores", "ver"),
    "inventario": ("inventario", "ver"),
    "facturacion": ("ventas", "ver"),
    "compras": ("compras", "ver"),
    "bancos": ("bancos", "ver"),
    "cuentas_bancarias": ("bancos", "ver"),
    "cajas": ("cajas", "ver"),
    "vendedores": ("vendedores", "ver"),
    "comisiones": ("comisiones", "ver"),
    "control_tasas": ("tasas", "ver"),
    "config_empresa": ("empresa", "ver"),
    "usuarios": ("usuarios", "ver"),
}


class MainWindow(QMainWindow):
    def __init__(self, usuario: Usuario):
        super().__init__()
        self.usuario = usuario
        self._paneles: dict[str, QWidget] = {}  # cache lazy de paneles

        self.setWindowTitle("ERP — Sistema de Gestión Administrativa")
        self.resize(1200, 720)
        self.setMinimumSize(900, 600)

        # Aplicar estilos globales
        self.setStyleSheet(GLOBAL_QSS)

        self._modulos_visibles = self._calcular_modulos_visibles()
        empresa = self._obtener_nombre_empresa()
        self._setup_ui(empresa)
        # "panel_general" es el destino por defecto, pero un rol futuro sin 'dashboard'/
        # 'ver' no deberia aterrizar en un modulo que ni siquiera ve en el sidebar --
        # cae al primero que si tenga visible (ADMIN/CAJERO/VENDEDOR de hoy siempre lo
        # incluyen, asi que en la practica esto no cambia nada todavia).
        destino_inicial = (
            "panel_general"
            if "panel_general" in self._modulos_visibles
            else next(iter(self._modulos_visibles), "panel_general")
        )
        self._ir_a_modulo(destino_inicial)

    # ── RBAC del sidebar ───────────────────────────────────────────────────

    def _calcular_modulos_visibles(self) -> set[str]:
        """Que modulos mostrar en el sidebar segun el rol del usuario logueado -- ver
        MODULO_PERMISO. Es solo una comodidad de UX (no repetir el paseo de "entrar y
        chocar con un mensaje de sin permiso"): la barrera de seguridad real sigue siendo
        require_permiso() en cada servicio, que no depende de esto para nada."""
        session = SessionLocal()
        try:
            return {
                clave
                for clave, (recurso, accion) in MODULO_PERMISO.items()
                if UsuarioService.verificar_permiso(session, self.usuario.id_usuario, recurso, accion)
            }
        except Exception:
            logger.exception("No se pudo calcular los modulos visibles del sidebar; se muestran todos")
            return set(MODULO_PERMISO.keys())
        finally:
            session.close()

    # ── Construcción del layout principal ────────────────────────────────

    def _setup_ui(self, empresa_nombre: str) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        outer_v = QVBoxLayout(central)
        outer_v.setContentsMargins(0, 0, 0, 0)
        outer_v.setSpacing(0)

        # Franja de tasas de cambio (BCV / paralelo), full-width por encima del shell
        self.ticker_tasas = TasaTicker(SessionLocal, self.usuario)
        outer_v.addWidget(self.ticker_tasas)

        fila = QWidget()
        main_h = QHBoxLayout(fila)
        main_h.setContentsMargins(0, 0, 0, 0)
        main_h.setSpacing(0)

        # Sidebar
        self.sidebar = Sidebar(empresa_nombre, self.usuario, modulos_visibles=self._modulos_visibles)
        self.sidebar.modulo_seleccionado.connect(self._ir_a_modulo)
        self.sidebar.cerrar_sesion.connect(self._confirmar_cerrar_sesion)
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
        outer_v.addWidget(fila)

    # ── Conmutador de vistas ─────────────────────────────────────────────

    def _ir_a_modulo(self, clave: str) -> None:
        panel = self._obtener_o_crear_panel(clave)
        self.stack.setCurrentWidget(panel)
        self.topbar.actualizar_modulo(clave)

    def navegar_a(self, clave: str) -> None:
        """Navegación disparada desde dentro de un panel (ej. botón "Nueva
        factura" del Panel General) -- también refleja la selección en la sidebar."""
        self.sidebar.seleccionar(clave)
        self._ir_a_modulo(clave)

    def _obtener_o_crear_panel(self, clave: str) -> QWidget:
        """Lazy-load: crea el panel solo la primera vez que se solicita."""
        if clave not in self._paneles:
            nombre, clase_panel = MODULOS_CONFIG.get(clave, (clave.title(), None))
            if clase_panel is not None:
                panel = clase_panel(SessionLocal, self.usuario)
            else:
                panel = PlaceholderView(nombre)

            if isinstance(panel, DashboardPanel):
                panel.nueva_factura_solicitada.connect(lambda: self.navegar_a("facturacion"))

            self._paneles[clave] = panel
            self.stack.addWidget(panel)

        return self._paneles[clave]

    def closeEvent(self, event: QCloseEvent) -> None:
        # DashboardPanel y TasaTicker cargan datos en un QThread aparte
        # (QueryWorker) que puede seguir corriendo al cerrar la ventana --
        # destruir esos widgets con el hilo todavia activo aborta el proceso
        # ("QThread: Destroyed while thread is still running"). quit()+wait()
        # es un no-op si ya termino; si no, espera a que la consulta actual
        # cierre su propia sesion antes de dejar avanzar el cierre.
        candidatos = [*self._paneles.values(), self.ticker_tasas]
        for widget in candidatos:
            worker = getattr(widget, "_worker", None)
            if worker is not None and worker.isRunning():
                worker.quit()
                worker.wait(3000)
        super().closeEvent(event)

    def _confirmar_cerrar_sesion(self) -> None:
        respuesta = QMessageBox.question(self, "Cerrar sesión", "¿Cerrar la sesión actual?")
        if respuesta == QMessageBox.StandardButton.Yes:
            # Cerrar esta ventana hace que app.exec() retorne en app/main.py (es la unica
            # ventana top-level abierta) -- el bucle de main() vuelve a mostrar LoginWindow,
            # mismo mecanismo que ya dispara el boton "X" de la ventana.
            self.close()

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
