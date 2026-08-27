"""
Paleta de colores y hojas de estilo globales para el ERP moderno.
Centraliza todos los QSS en un solo lugar para facilitar el mantenimiento.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QTableWidget, QWidget

# ── Paleta principal ────────────────────────────────────────────────────────
COLOR_PRIMARY = "#0D47A1"  # Azul corporativo principal
COLOR_PRIMARY_DARK = "#0A3A83"  # Azul oscuro (hover / pressed)
COLOR_PRIMARY_LIGHT = "#1565C0"  # Azul medio (elementos activos)
COLOR_SIDEBAR_BG = "#0D47A1"
COLOR_SIDEBAR_TEXT = "#FFFFFF"
COLOR_SIDEBAR_ACTIVE = "#1565C0"
COLOR_SIDEBAR_HOVER = "#0B4F9F"

COLOR_TOPBAR_BG = "#FFFFFF"
COLOR_TOPBAR_BORDER = "#E2E8F0"

COLOR_CONTENT_BG = "#F8FAFC"
COLOR_CARD_BG = "#FFFFFF"
# Antes #E2E8F0 -- se notaba casi identico a COLOR_CONTENT_BG, los bordes de
# tarjetas/tablas/inputs desaparecian visualmente. #CBD5E1 es el tono que ya se
# usaba como literal ad-hoc en varios dialogos (cliente_form_dialog.py,
# factura_form_dialog.py, etc.) para "un borde un poco mas marcado" -- se
# promueve aca a la constante real en vez de mantenerlo duplicado.
COLOR_BORDER = "#CBD5E1"
# Fondo de "chips" de campo individuales dentro de una tarjeta (ver
# FieldChip en factura_detalle_dialog.py) -- un escalon entre COLOR_CONTENT_BG
# y el nuevo COLOR_BORDER.
COLOR_FIELD_BG = "#F1F5F9"

COLOR_TEXT_DARK = "#1E293B"
COLOR_TEXT_MUTED = "#64748B"
COLOR_TEXT_LIGHT = "#94A3B8"

COLOR_SUCCESS = "#16A34A"
COLOR_WARNING = "#D97706"
COLOR_DANGER = "#DC2626"
COLOR_INFO = "#0284C7"

# Antes #F1F5F9 (identico a COLOR_FIELD_BG) -- se sube un escalon para que el
# encabezado de tabla se distinga de los chips de campo y del fondo de pagina.
COLOR_TABLE_HEADER = "#E2E8F0"
COLOR_TABLE_ALT_ROW = "#F8FAFC"
# Antes #DBEAFE (azul) -- se notaba como un resaltado ajeno a la paleta gris/blanco
# intercalada del resto de la tabla (hallazgo del usuario en Usuarios, 2026-08-27, pero
# es una constante compartida por TABLE_QSS: aplica a TODAS las tablas de la app, no solo
# esa). Mismo tono que COLOR_TABLE_HEADER -- se nota lo suficiente contra el blanco y el
# gris de fila alterna sin salirse de la paleta neutra.
COLOR_TABLE_SELECTED = "#E2E8F0"
COLOR_TABLE_HOVER = "#EFF6FF"

# ── Dimensiones ─────────────────────────────────────────────────────────────
SIDEBAR_WIDTH = 230  # expanded width; collapsed = 58 (see sidebar.py)
TOPBAR_HEIGHT = 60
FONT_FAMILY = "Segoe UI"


# ── Hojas de estilo (QSS) ───────────────────────────────────────────────────
GLOBAL_QSS = f"""
* {{
    font-family: '{FONT_FAMILY}', Arial, sans-serif;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
}}
QMainWindow, QWidget#ContentArea {{
    background-color: {COLOR_CONTENT_BG};
}}
QScrollBar:vertical {{
    background: {COLOR_BORDER};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {COLOR_TEXT_LIGHT};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QToolTip {{
    background-color: {COLOR_TEXT_DARK};
    color: white;
    border: none;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 12px;
}}
"""

SIDEBAR_QSS = f"""
QWidget#Sidebar {{
    background-color: {COLOR_SIDEBAR_BG};
    border-right: none;
}}
QLabel#SidebarLogo {{
    color: {COLOR_SIDEBAR_TEXT};
    font-size: 15px;
    font-weight: bold;
    padding: 0px 16px;
    letter-spacing: 1px;
}}
QLabel#SidebarSection {{
    color: rgba(255,255,255,0.55);
    font-size: 10px;
    font-weight: bold;
    letter-spacing: 1.5px;
    padding: 0px 16px;
    text-transform: uppercase;
}}
QPushButton#SidebarBtn {{
    background-color: transparent;
    color: rgba(255,255,255,0.85);
    border: none;
    border-radius: 8px;
    padding: 10px 14px;
    text-align: left;
    font-size: 13px;
    margin: 1px 8px;
}}
QPushButton#SidebarBtn:hover {{
    background-color: rgba(255,255,255,0.12);
    color: {COLOR_SIDEBAR_TEXT};
}}
QPushButton#SidebarBtn[active="true"] {{
    background-color: rgba(255,255,255,0.20);
    color: {COLOR_SIDEBAR_TEXT};
    font-weight: bold;
}}
"""

TOPBAR_QSS = f"""
QWidget#TopBar {{
    background-color: {COLOR_TOPBAR_BG};
    border-bottom: 1px solid {COLOR_TOPBAR_BORDER};
}}
QLabel#TopBarTitle {{
    font-size: 17px;
    font-weight: bold;
    color: {COLOR_TEXT_DARK};
}}
QLineEdit#TopBarSearch {{
    background-color: {COLOR_CONTENT_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 20px;
    padding: 6px 14px 6px 36px;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
    min-width: 200px;
}}
QLineEdit#TopBarSearch:focus {{
    border-color: {COLOR_PRIMARY};
    background-color: white;
}}
QPushButton#TopBarBtn {{
    background-color: transparent;
    border: none;
    border-radius: 20px;
    padding: 6px 10px;
    font-size: 18px;
    color: {COLOR_TEXT_MUTED};
}}
QPushButton#TopBarBtn:hover {{
    background-color: {COLOR_CONTENT_BG};
    color: {COLOR_TEXT_DARK};
}}
QLabel#UserLabel {{
    color: {COLOR_TEXT_DARK};
    font-weight: bold;
    font-size: 13px;
}}
QLabel#UserRole {{
    color: {COLOR_TEXT_MUTED};
    font-size: 11px;
}}
"""

TABLE_QSS = f"""
QTableWidget {{
    background-color: {COLOR_CARD_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    gridline-color: {COLOR_BORDER};
    selection-background-color: {COLOR_TABLE_SELECTED};
    selection-color: {COLOR_TEXT_DARK};
    alternate-background-color: {COLOR_TABLE_ALT_ROW};
    outline: none;
}}
QTableWidget::item {{
    padding: 8px 12px;
    border-bottom: 1px solid {COLOR_BORDER};
    color: {COLOR_TEXT_DARK};
}}
QTableWidget::item:selected {{
    background-color: {COLOR_TABLE_SELECTED};
    color: {COLOR_TEXT_DARK};
}}
QTableWidget::item:hover {{
    background-color: {COLOR_TABLE_HOVER};
}}
QHeaderView::section {{
    background-color: {COLOR_TABLE_HEADER};
    color: {COLOR_TEXT_DARK};
    font-weight: bold;
    font-size: 11px;
    letter-spacing: 0.5px;
    padding: 10px 12px;
    border: none;
    border-bottom: 2px solid {COLOR_BORDER};
    text-transform: uppercase;
}}
QHeaderView::section:first {{
    border-top-left-radius: 8px;
}}
QHeaderView::section:last {{
    border-top-right-radius: 8px;
}}
QTableCornerButton::section {{
    background-color: {COLOR_TABLE_HEADER};
    border: none;
    border-top-left-radius: 8px;
}}
"""

BUTTON_PRIMARY_QSS = f"""
QPushButton {{
    background-color: {COLOR_PRIMARY};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: bold;
    font-size: 13px;
}}
QPushButton:hover {{
    background-color: {COLOR_PRIMARY_LIGHT};
}}
QPushButton:pressed {{
    background-color: {COLOR_PRIMARY_DARK};
}}
QPushButton:disabled {{
    background-color: {COLOR_TEXT_LIGHT};
    color: white;
}}
"""

BUTTON_SECONDARY_QSS = f"""
QPushButton {{
    background-color: {COLOR_CARD_BG};
    color: {COLOR_TEXT_DARK};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
}}
QPushButton:hover {{
    background-color: {COLOR_CONTENT_BG};
    border-color: {COLOR_TEXT_MUTED};
}}
QPushButton:pressed {{
    background-color: {COLOR_BORDER};
}}
"""

BUTTON_DANGER_QSS = f"""
QPushButton {{
    background-color: {COLOR_DANGER};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: bold;
}}
QPushButton:hover {{
    background-color: #B91C1C;
}}
"""

SEARCH_QSS = f"""
QLineEdit {{
    background-color: {COLOR_CARD_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 7px 12px;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
}}
QLineEdit:focus {{
    border-color: {COLOR_PRIMARY};
    outline: none;
}}
"""

CARD_QSS = f"""
QWidget#Card {{
    background-color: {COLOR_CARD_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
}}
"""

# QTabWidget/QTabBar sin estilo propio renderiza el tema nativo de Windows (una caja
# gris solida en la pestaña activa) -- no se nota que son pestañas clickeables, ajeno al
# resto de la paleta. Antes solo factura_form_dialog.py lo definia, local dentro de su
# propio DIALOG_STYLE; se promovio aca cuando usuarios_panel.py necesito el mismo
# QTabWidget con pestañas por primera vez FUERA de un dialogo (2026-08-27) -- para no
# repetir una tercera copia que termine divergiendo (mismo motivo que EstadoBadge/
# TABLE_QSS, ver GUIA_ESTILO_UI.md secciones 5 y 9). Subrayado azul en la pestaña activa,
# sin caja/fondo, mismo criterio visual que el resto de la app (acento de color en vez de
# relleno solido).
TABS_QSS = f"""
QTabWidget::pane {{
    border: none;
    top: -1px;
}}
QTabBar::tab {{
    background-color: transparent;
    color: {COLOR_TEXT_MUTED};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 4px;
    margin-right: 22px;
    font-size: 13px;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    color: {COLOR_PRIMARY};
    border-bottom: 2px solid {COLOR_PRIMARY};
}}
QTabBar::tab:disabled {{
    color: #CBD5E1;
}}
"""

# ── Estados de factura de venta ─────────────────────────────────────────────
# Compartido entre dashboard_panel.py y facturacion_panel.py para que el mismo
# estado se pinte igual en toda la app. Fallback gris para cualquier valor no
# listado aca.
COLORES_ESTADO_FACTURA = {
    "EMITIDA": COLOR_INFO,
    "PAGADA": COLOR_SUCCESS,
    "PARCIAL": COLOR_WARNING,
    "VENCIDA": COLOR_DANGER,
    "ANULADA": COLOR_TEXT_MUTED,
}


def color_con_alpha(color_hex: str, alpha: int = 26) -> str:
    """Version translucida de `color_hex` para fondos de badges/iconos.

    Qt QSS solo acepta alfa via `rgba()` o el formato `#AARRGGBB` (alfa
    primero) -- pegar dos digitos hex al final de un `#RRGGBB` (`#RRGGBBAA`)
    no es un formato valido y Qt lo ignora silenciosamente.
    """
    c = QColor(color_hex)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def aplicar_sombra(widget: QWidget, blur: int = 18, y_offset: int = 3, alpha: int = 35) -> None:
    """Sombra sutil de elevacion para tarjetas/tablas (QSS no soporta box-shadow en
    widgets normales -- esto es QGraphicsDropShadowEffect, nativo de Qt, sin
    dependencias nuevas). Color fijo tono slate-900 translucido para que la sombra
    se vea consistente sin importar el color de fondo del widget."""
    sombra = QGraphicsDropShadowEffect(widget)
    sombra.setBlurRadius(blur)
    sombra.setXOffset(0)
    sombra.setYOffset(y_offset)
    sombra.setColor(QColor(15, 23, 42, alpha))
    widget.setGraphicsEffect(sombra)


def alinear_encabezados(tabla: QTableWidget, alineaciones: dict[int, Qt.AlignmentFlag]) -> None:
    """QHeaderView centra el texto de sus secciones por defecto, mientras que
    QTableWidgetItem se alinea a la izquierda por defecto -- sin esto, el encabezado de
    cada columna de texto queda corrido respecto a sus datos (ver GUIA_ESTILO_UI.md §5).
    `alineaciones` mapea indice de columna -> la misma alineacion que ya usan los
    QTableWidgetItem de esa columna (columnas no listadas quedan con el default de Qt)."""
    for columna, alineacion in alineaciones.items():
        item = tabla.horizontalHeaderItem(columna)
        if item is not None:
            item.setTextAlignment(int(alineacion | Qt.AlignmentFlag.AlignVCenter))


class ComboBoxSinScroll(QComboBox):
    """QComboBox que ignora la rueda del mouse salvo que ya tenga foco (click previo).
    Por defecto, Qt cambia el valor seleccionado con solo pasar el mouse por encima y
    girar la rueda mientras se hace scroll de la pantalla que lo contiene -- un combo
    dentro de un formulario largo puede terminar con un valor distinto al que el usuario
    veia sin que haya hecho click en el, un problema de usabilidad conocido de Qt.
    Ignorar el evento sin foco hace que se propague normalmente al widget padre
    (QScrollArea, etc.), que sí debe scrollear."""

    def wheelEvent(self, event) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class EstadoBadge(QWidget):
    """Badge de estado unico para toda la app (tablas de clientes/inventario/vendedores/
    usuarios/facturacion): texto sobre un fondo translucido del mismo color, sin icono.
    Antes cada panel tenia su propia version -- clientes_panel.py/inventario_panel.py/
    vendedores_panel.py/usuarios_panel.py repetian una version identica con icono dentro
    de un contenedor de ancho fijo (en Usuarios, con la columna angosta que le tocaba,
    quedaba con el texto cortado: "Act" en vez de "Activo") -- facturacion_panel.py ya
    tenia esta version mas simple (EstadoFacturaBadge) para sus 5 estados posibles, y es
    la que el usuario pidio como estandar (2026-08-27). Consolidado aca en vez de
    mantener 5 clases identicas repetidas."""

    def __init__(self, texto: str, color: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl = QLabel(texto)
        lbl.setStyleSheet(
            f"background-color: {color_con_alpha(color)}; color: {color}; border-radius: 10px;"
            " padding: 2px 10px; font-size: 11px; font-weight: bold;"
        )
        layout.addWidget(lbl)
