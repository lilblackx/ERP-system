"""
Sidebar izquierda del ERP — versión con toggle collapse/expand.
- Fondo azul corporativo forzado con paleta + QSS explícito en cada widget.
- Fuente de módulos agrandada a 15px.
- Botón hamburguesa que colapsa la sidebar a 58px (solo íconos) y la expande a 230px.
- Emite `modulo_seleccionado(str)` al hacer clic en un módulo.
- Emite `toggled(bool)` cuando se abre o cierra (True = abierto).
- Emite `cerrar_sesion()` al hacer clic en el botón de logout del pie de sidebar.
"""

import qtawesome as qta
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from app.db.models import Usuario
from app.ui.styles import COLOR_PRIMARY_DARK, COLOR_SIDEBAR_ACTIVE, COLOR_SIDEBAR_BG

# ── Constantes de tamaño ────────────────────────────────────────────────────
SIDEBAR_EXPANDED = 230  # px cuando está abierto
SIDEBAR_COLLAPSED = 58  # px cuando está cerrado (solo íconos)
ANIM_DURATION_MS = 220  # velocidad de la animación

# ── Módulos agrupados por sección ───────────────────────────────────────────
# (nombre_seccion, [(clave_interna, texto_visible), ...])
SECCIONES = [
    (
        "OPERACIONES",
        [
            ("panel_general", "Panel General"),
            ("facturacion", "Facturación"),
            ("clientes", "Clientes"),
            ("vendedores", "Vendedores"),
        ],
    ),
    (
        "COMPRAS",
        [
            ("compras", "Compras"),
            ("proveedores", "Proveedores"),
        ],
    ),
    (
        "INVENTARIO",
        [
            ("inventario", "Productos"),
        ],
    ),
    (
        "FINANZAS",
        [
            ("cuentas_bancarias", "Cuentas Bancarias"),
            ("bancos", "Bancos"),
            ("cajas", "Cajas"),
            ("comisiones", "Comisiones"),
            ("control_tasas", "Tasas de Cambio"),
        ],
    ),
    (
        "ADMINISTRACIÓN",
        [
            ("config_empresa", "Config. de Empresa"),
            ("usuarios", "Usuarios"),
        ],
    ),
]


# ── Paleta forzada (evita que Qt anule el color de fondo) ──────────────────
def _paleta_azul() -> QPalette:
    p = QPalette()
    for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base, QPalette.ColorRole.AlternateBase):
        p.setColor(role, QColor(COLOR_SIDEBAR_BG))
    p.setColor(QPalette.ColorRole.WindowText, QColor("#FFFFFF"))
    p.setColor(QPalette.ColorRole.ButtonText, QColor("#FFFFFF"))
    p.setColor(QPalette.ColorRole.Button, QColor(COLOR_SIDEBAR_BG))
    return p


# ── QSS explícito que aplica el azul a TODOS los descendientes ─────────────
_SIDEBAR_CSS = f"""
    /* Raíz */
    QWidget, QScrollArea, QScrollArea > QWidget > QWidget {{
        background-color: {COLOR_SIDEBAR_BG};
        color: #FFFFFF;
        border: none;
    }}
    QScrollBar:vertical {{
        background: rgba(255,255,255,0.08);
        width: 5px;
        border-radius: 3px;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(255,255,255,0.30);
        border-radius: 3px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

    /* Etiquetas de sección */
    QLabel#SidebarSection {{
        color: rgba(255,255,255,0.50);
        font-size: 10px;
        font-weight: bold;
        letter-spacing: 1.5px;
        background-color: {COLOR_SIDEBAR_BG};
    }}

    /* Logo / empresa */
    QLabel#SidebarLogo {{
        color: #FFFFFF;
        font-size: 14px;
        font-weight: bold;
        letter-spacing: 1px;
        background-color: transparent;
    }}

    /* Botones de módulo */
    QPushButton#SidebarBtn {{
        background-color: transparent;
        color: rgba(255,255,255,0.88);
        border: none;
        border-radius: 8px;
        padding: 11px 14px;
        text-align: left;
        font-size: 15px;
        font-weight: 500;
    }}
    QPushButton#SidebarBtn:hover {{
        background-color: rgba(255,255,255,0.14);
        color: #FFFFFF;
    }}
    QPushButton#SidebarBtn[active="true"] {{
        background-color: rgba(255,255,255,0.22);
        color: #FFFFFF;
        font-weight: bold;
    }}
    QPushButton#SidebarBtn[collapsed="true"] {{
        padding: 11px 2px;
        text-align: center;
        font-size: 12px;
    }}

    /* Botón hamburguesa */
    QPushButton#ToggleBtn {{
        background-color: transparent;
        color: rgba(255,255,255,0.80);
        border: none;
        border-radius: 6px;
        font-size: 20px;
        padding: 4px 8px;
    }}
    QPushButton#ToggleBtn:hover {{
        background-color: rgba(255,255,255,0.15);
        color: #FFFFFF;
    }}

    /* Botón cerrar sesión (pie de sidebar) */
    QPushButton#BtnCerrarSesion {{
        background-color: transparent;
        border: none;
        border-radius: 6px;
    }}
    QPushButton#BtnCerrarSesion:hover {{
        background-color: rgba(255,255,255,0.15);
    }}
"""


class SidebarButton(QPushButton):
    """Botón individual de módulo que sabe si está activo o colapsado."""

    def __init__(self, clave: str, texto: str, parent=None):
        super().__init__(parent)
        self.clave = clave
        self.texto = texto
        self.setObjectName("SidebarBtn")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(44)
        self._expanded = True
        self._refresh_text()

    # ── Estado visual ─────────────────────────────────────────────────────

    def set_active(self, activo: bool) -> None:
        self.setProperty("active", "true" if activo else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._refresh_text()
        self.setToolTip("" if expanded else self.texto)
        # Colapsado: el texto pasa de 1-2 palabras a solo iniciales -- centrarlo y
        # quitarle el padding horizontal fijo evita que se corte/superponga contra el
        # borde redondeado del boton en los 46px utiles del sidebar contraido (58px -
        # margenes de _make_nav).
        self.setProperty("collapsed", "false" if expanded else "true")
        self.style().unpolish(self)
        self.style().polish(self)

    def _refresh_text(self) -> None:
        if self._expanded:
            self.setText(f"  {self.texto}")
        else:
            # Colapsado: mostrar iniciales del módulo (máx 2 caracteres)
            iniciales = "".join(p[0].upper() for p in self.texto.split()[:2])
            self.setText(iniciales)


class Sidebar(QWidget):
    """Barra lateral de navegación del ERP con toggle colapsar/expandir."""

    modulo_seleccionado = Signal(str)
    toggled = Signal(bool)  # True = expandido, False = colapsado
    cerrar_sesion = Signal()

    def __init__(self, empresa_nombre: str = "Mi Empresa", usuario: Usuario | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self._expandido = True
        self._botones: dict[str, SidebarButton] = {}
        self._lbl_secciones: list[QLabel] = []
        self._activo = "panel_general"
        self._empresa = empresa_nombre
        self._usuario = usuario

        # ── Paleta + stylesheet forzados ──────────────────────────────────
        self.setAutoFillBackground(True)
        self.setPalette(_paleta_azul())
        self.setStyleSheet(_SIDEBAR_CSS)
        self.setFixedWidth(SIDEBAR_EXPANDED)

        self._build_ui()
        self._activar("panel_general")

    # ── Construcción de la UI ─────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_header())
        root.addWidget(self._make_nav())
        root.addWidget(self._make_footer())

    def _make_header(self) -> QWidget:
        self._header = QWidget()
        self._header.setFixedHeight(58)
        self._header.setAutoFillBackground(True)
        self._header.setPalette(_paleta_azul())
        self._header.setStyleSheet(
            f"background-color: {COLOR_PRIMARY_DARK}; border: none; border-bottom: 1px solid rgba(255,255,255,0.12);"
        )

        h = QHBoxLayout(self._header)
        h.setContentsMargins(10, 0, 10, 0)
        h.setSpacing(8)

        self.btn_toggle = QPushButton("☰")
        self.btn_toggle.setObjectName("ToggleBtn")
        self.btn_toggle.setFixedSize(30, 30)
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setToolTip("Colapsar menú")
        self.btn_toggle.clicked.connect(self.toggle)

        self._lbl_logo = QLabel(self._iniciales_empresa())
        self._lbl_logo.setFixedSize(30, 30)
        self._lbl_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_logo.setStyleSheet(
            f"background-color: #FFFFFF; color: {COLOR_PRIMARY_DARK}; border: none;"
            " border-radius: 8px; font-size: 12px; font-weight: bold;"
        )

        self._lbl_empresa = QLabel(self._empresa.upper()[:18])
        self._lbl_empresa.setObjectName("SidebarLogo")
        self._lbl_empresa.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        h.addWidget(self.btn_toggle)
        h.addWidget(self._lbl_logo)
        h.addWidget(self._lbl_empresa)
        h.addStretch()
        return self._header

    def _iniciales_empresa(self) -> str:
        return "".join(p[0].upper() for p in self._empresa.split()[:2]) or "E"

    def _make_nav(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setAutoFillBackground(True)
        scroll.setPalette(_paleta_azul())

        content = QWidget()
        content.setAutoFillBackground(True)
        content.setPalette(_paleta_azul())

        self._nav_layout = QVBoxLayout(content)
        self._nav_layout.setContentsMargins(6, 10, 6, 10)
        self._nav_layout.setSpacing(3)

        for nombre_seccion, items in SECCIONES:
            lbl_seccion = QLabel(nombre_seccion)
            lbl_seccion.setObjectName("SidebarSection")
            lbl_seccion.setFixedHeight(24)
            self._lbl_secciones.append(lbl_seccion)
            self._nav_layout.addWidget(lbl_seccion)

            for clave, texto in items:
                btn = SidebarButton(clave, texto)
                btn.clicked.connect(lambda checked, k=clave: self._on_click(k))
                self._botones[clave] = btn
                self._nav_layout.addWidget(btn)

        self._nav_layout.addSpacerItem(QSpacerItem(1, 1, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))
        scroll.setWidget(content)
        return scroll

    def _make_footer(self) -> QWidget:
        self._footer = QWidget()
        self._footer.setFixedHeight(64)
        self._footer.setAutoFillBackground(True)
        self._footer.setPalette(_paleta_azul())
        self._footer.setStyleSheet(
            f"background-color: {COLOR_PRIMARY_DARK}; border: none; border-top: 1px solid rgba(255,255,255,0.12);"
        )

        h = QHBoxLayout(self._footer)
        h.setContentsMargins(14, 8, 14, 8)
        h.setSpacing(10)

        nombre = (self._usuario.nombre or self._usuario.nombre_usuario) if self._usuario else "Usuario"
        rol = self._usuario.rol.nombre if self._usuario and self._usuario.rol else "—"
        iniciales = "".join(p[0].upper() for p in nombre.split()[:2]) or "U"

        self._lbl_avatar = QLabel(iniciales)
        self._lbl_avatar.setFixedSize(34, 34)
        self._lbl_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_avatar.setStyleSheet(
            f"background-color: {COLOR_SIDEBAR_ACTIVE}; color: #FFFFFF; border: none;"
            " border-radius: 17px; font-size: 12px; font-weight: bold;"
        )

        self._footer_info = QWidget()
        self._footer_info.setStyleSheet("background: transparent;")
        v = QVBoxLayout(self._footer_info)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        lbl_nombre = QLabel(nombre[:20])
        lbl_nombre.setStyleSheet("color: #FFFFFF; font-size: 12px; font-weight: bold; background: transparent;")
        lbl_rol = QLabel(rol)
        lbl_rol.setStyleSheet("color: rgba(255,255,255,0.60); font-size: 10px; background: transparent;")

        v.addWidget(lbl_nombre)
        v.addWidget(lbl_rol)

        self.btn_cerrar_sesion = QPushButton()
        self.btn_cerrar_sesion.setObjectName("BtnCerrarSesion")
        self.btn_cerrar_sesion.setIcon(qta.icon("fa5s.sign-out-alt", color="#FFFFFF"))
        self.btn_cerrar_sesion.setFixedSize(32, 32)
        self.btn_cerrar_sesion.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cerrar_sesion.setToolTip("Cerrar sesión")
        self.btn_cerrar_sesion.clicked.connect(self.cerrar_sesion.emit)

        h.addWidget(self._lbl_avatar)
        h.addWidget(self._footer_info)
        h.addStretch()
        h.addWidget(self.btn_cerrar_sesion)
        return self._footer

    # ── Toggle colapsar / expandir ────────────────────────────────────────

    def toggle(self) -> None:
        if self._expandido:
            self._colapsar()
        else:
            self._expandir()

    def _colapsar(self) -> None:
        self._expandido = False
        self._lbl_empresa.setVisible(False)
        for lbl in self._lbl_secciones:
            lbl.setVisible(False)
        self._footer_info.setVisible(False)
        self.btn_toggle.setToolTip("Expandir menu")

        for btn in self._botones.values():
            btn.set_expanded(False)

        self._animar(SIDEBAR_EXPANDED, SIDEBAR_COLLAPSED)
        self.toggled.emit(False)

    def _expandir(self) -> None:
        self._expandido = True
        self._lbl_empresa.setVisible(True)
        for lbl in self._lbl_secciones:
            lbl.setVisible(True)
        self._footer_info.setVisible(True)
        self.btn_toggle.setToolTip("Colapsar menu")

        for btn in self._botones.values():
            btn.set_expanded(True)

        self._animar(SIDEBAR_COLLAPSED, SIDEBAR_EXPANDED)
        self.toggled.emit(True)

    def _animar(self, desde: int, hasta: int) -> None:
        self._anim = QPropertyAnimation(self, b"minimumWidth")
        self._anim.setDuration(ANIM_DURATION_MS)
        self._anim.setStartValue(desde)
        self._anim.setEndValue(hasta)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._anim2 = QPropertyAnimation(self, b"maximumWidth")
        self._anim2.setDuration(ANIM_DURATION_MS)
        self._anim2.setStartValue(desde)
        self._anim2.setEndValue(hasta)
        self._anim2.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._anim.start()
        self._anim2.start()

    # ── Lógica de selección activa ────────────────────────────────────────

    def _on_click(self, clave: str) -> None:
        self._activar(clave)
        self.modulo_seleccionado.emit(clave)

    def _activar(self, clave: str) -> None:
        if self._activo in self._botones:
            self._botones[self._activo].set_active(False)
        self._activo = clave
        if clave in self._botones:
            self._botones[clave].set_active(True)

    # ── API pública ───────────────────────────────────────────────────────

    def actualizar_empresa(self, nombre: str) -> None:
        self._empresa = nombre
        self._lbl_empresa.setText(nombre.upper()[:18])
        self._lbl_logo.setText(self._iniciales_empresa())

    def seleccionar(self, clave: str) -> None:
        """Marca `clave` como módulo activo sin emitir `modulo_seleccionado`
        (uso: navegación disparada desde dentro de un panel, ej. botón
        "Nueva factura" del Panel General)."""
        self._activar(clave)
