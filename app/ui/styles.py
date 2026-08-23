"""
Paleta de colores y hojas de estilo globales para el ERP moderno.
Centraliza todos los QSS en un solo lugar para facilitar el mantenimiento.
"""

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
COLOR_BORDER = "#E2E8F0"

COLOR_TEXT_DARK = "#1E293B"
COLOR_TEXT_MUTED = "#64748B"
COLOR_TEXT_LIGHT = "#94A3B8"

COLOR_SUCCESS = "#16A34A"
COLOR_WARNING = "#D97706"
COLOR_DANGER = "#DC2626"
COLOR_INFO = "#0284C7"

COLOR_TABLE_HEADER = "#F1F5F9"
COLOR_TABLE_ALT_ROW = "#F8FAFC"
COLOR_TABLE_SELECTED = "#DBEAFE"
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
    outline: none;
}}
QTableWidget::item {{
    padding: 8px 12px;
    border-bottom: 1px solid {COLOR_BORDER};
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
    color: {COLOR_TEXT_MUTED};
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

BADGE_ACTIVE_QSS = f"""
QLabel {{
    background-color: #DCFCE7;
    color: {COLOR_SUCCESS};
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: bold;
}}
"""

BADGE_INACTIVE_QSS = f"""
QLabel {{
    background-color: #FEF2F2;
    color: {COLOR_DANGER};
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: bold;
}}
"""
