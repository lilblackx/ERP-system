"""
Sidebar izquierda del ERP — versión con toggle collapse/expand.
- Fondo azul corporativo forzado con paleta + QSS explícito en cada widget.
- Fuente de módulos agrandada a 15px.
- Botón hamburguesa que colapsa la sidebar a 58px (solo íconos) y la expande a 230px.
- Emite `modulo_seleccionado(str)` al hacer clic en un módulo.
- Emite `toggled(bool)` cuando se abre o cierra (True = abierto).
"""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.styles import COLOR_SIDEBAR_BG

# ── Constantes de tamaño ────────────────────────────────────────────────────
SIDEBAR_EXPANDED = 230  # px cuando está abierto
SIDEBAR_COLLAPSED = 58  # px cuando está cerrado (solo íconos)
ANIM_DURATION_MS = 220  # velocidad de la animación

# ── Módulos ─────────────────────────────────────────────────────────────────
# (clave_interna, texto_visible)
MODULOS = [
    ("clientes", "Clientes"),
    ("proveedores", "Proveedores"),
    ("inventario", "Inventario"),
    ("facturacion", "Facturación"),
    ("compras", "Compras"),
    ("bancos", "Bancos"),
    ("cuentas_bancarias", "Cuentas Bancarias"),
    ("cajas", "Cajas"),
    ("vendedores", "Vendedores"),
    ("comisiones", "Comisiones"),
    ("control_tasas", "Control de Tasas"),
    ("config_empresa", "Config. de Empresa"),
    ("usuarios", "Usuarios"),
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
        background-color: rgba(0,0,0,0.20);
    }}
    QLabel#SidebarSub {{
        color: rgba(255,255,255,0.55);
        font-size: 10px;
        background-color: rgba(0,0,0,0.20);
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

    def __init__(self, empresa_nombre: str = "Mi Empresa", parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self._expandido = True
        self._botones: dict[str, SidebarButton] = {}
        self._activo = "inicio"
        self._empresa = empresa_nombre

        # ── Paleta + stylesheet forzados ──────────────────────────────────
        self.setAutoFillBackground(True)
        self.setPalette(_paleta_azul())
        self.setStyleSheet(_SIDEBAR_CSS)
        self.setFixedWidth(SIDEBAR_EXPANDED)

        self._build_ui()
        self._activar("inicio")

    # ── Construcción de la UI ─────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_header())
        root.addWidget(self._make_nav())

    def _make_header(self) -> QWidget:
        self._header = QWidget()
        self._header.setFixedHeight(76)
        self._header.setAutoFillBackground(True)
        self._header.setPalette(_paleta_azul())
        self._header.setStyleSheet(
            "background-color: rgba(0,0,0,0.20); border-bottom: 1px solid rgba(255,255,255,0.10);"
        )

        lay = QVBoxLayout(self._header)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.setSpacing(2)

        # Fila superior: toggle ☰ + nombre empresa
        top_row = QWidget()
        top_row.setStyleSheet("background: transparent;")
        from PySide6.QtWidgets import QHBoxLayout

        h = QHBoxLayout(top_row)
        h.setContentsMargins(8, 0, 8, 0)
        h.setSpacing(6)

        self.btn_toggle = QPushButton("☰")
        self.btn_toggle.setObjectName("ToggleBtn")
        self.btn_toggle.setFixedSize(32, 32)
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setToolTip("Colapsar menú")
        self.btn_toggle.clicked.connect(self.toggle)

        self._lbl_empresa = QLabel(self._empresa.upper()[:16])
        self._lbl_empresa.setObjectName("SidebarLogo")
        self._lbl_empresa.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        h.addWidget(self.btn_toggle)
        h.addWidget(self._lbl_empresa)
        h.addStretch()

        self._lbl_sub = QLabel("Sistema ERP")
        self._lbl_sub.setObjectName("SidebarSub")
        self._lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lay.addWidget(top_row)
        lay.addWidget(self._lbl_sub)
        return self._header

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

        self._lbl_seccion = QLabel("   ADMINISTRA")
        self._lbl_seccion.setObjectName("SidebarSection")
        self._lbl_seccion.setFixedHeight(24)
        self._nav_layout.addWidget(self._lbl_seccion)

        for clave, texto in MODULOS:
            btn = SidebarButton(clave, texto)
            btn.clicked.connect(lambda checked, k=clave: self._on_click(k))
            self._botones[clave] = btn
            self._nav_layout.addWidget(btn)

        self._nav_layout.addSpacerItem(QSpacerItem(1, 1, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))
        scroll.setWidget(content)
        return scroll

    # ── Toggle colapsar / expandir ────────────────────────────────────────

    def toggle(self) -> None:
        if self._expandido:
            self._colapsar()
        else:
            self._expandir()

    def _colapsar(self) -> None:
        self._expandido = False
        self._lbl_empresa.setVisible(False)
        self._lbl_sub.setVisible(False)
        self._lbl_seccion.setVisible(False)
        self.btn_toggle.setToolTip("Expandir menu")

        for btn in self._botones.values():
            btn.set_expanded(False)

        self._animar(SIDEBAR_EXPANDED, SIDEBAR_COLLAPSED)
        self.toggled.emit(False)

    def _expandir(self) -> None:
        self._expandido = True
        self._lbl_empresa.setVisible(True)
        self._lbl_sub.setVisible(True)
        self._lbl_seccion.setVisible(True)
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
        self._lbl_empresa.setText(nombre.upper()[:16])
