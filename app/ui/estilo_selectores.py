"""Aspecto unico de los selectores de toda la app: la lista de los desplegables (QComboBox) y los campos de fecha.

Es un filtro de eventos de la aplicacion: cada combo y cada campo de fecha (QDateEdit con calendario) recibe su aspecto
la primera vez que se pule, sin tener que tocar los sitios que los crean ni acordarse de llamar un ayudante en los
nuevos.

Desplegables: la lista que se abre al pulsar un combo es una ventana emergente aparte: no hereda bien el QSS de la
pantalla y cada formulario tenia su propia copia de la regla `QComboBox QAbstractItemView` (nueve), asi que la lista
salia con el aspecto generico del sistema. Ahora tiene opciones mas altas y con las esquinas redondeadas, la elegida
en azul suave, y la lista dentro de un marco redondeado (el marco lo pinta la lista; la ventana que la contiene queda
transparente).

Fechas: ver calendario.py (calendario propio, texto de solo lectura y clic en todo el campo).
"""

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QComboBox, QDateEdit, QStyledItemDelegate

from app.ui.calendario import preparar_campo_fecha
from app.ui.styles import (
    COLOR_BLUE_LIGHT,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_PRIMARY,
    COLOR_TABLE_HOVER,
    COLOR_TEXT_DARK,
    FONT_FAMILY,
)

# Va en la propia lista (view) del combo: un QSS puesto directamente en un widget gana a cualquiera heredado, incluidas
# las reglas `QComboBox QAbstractItemView` que traen los formularios.
VISTA_QSS = f"""
QListView {{
    background-color: {COLOR_CARD_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
    outline: none;
    padding: 4px;
    font-family: '{FONT_FAMILY}', Arial, sans-serif;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
}}
QListView::item {{
    min-height: 30px;
    padding: 0px 10px;
    border-radius: 6px;
    color: {COLOR_TEXT_DARK};
}}
QListView::item:hover {{
    background-color: {COLOR_TABLE_HOVER};
}}
QListView::item:selected {{
    background-color: {COLOR_BLUE_LIGHT};
    color: {COLOR_PRIMARY};
}}
"""

_LISTO = "_desplegable_listo"


def preparar_desplegable(combo: QComboBox) -> None:
    """Aplica a la lista de `combo` el aspecto de la app. Es idempotente."""
    if combo.property(_LISTO):
        return
    combo.setProperty(_LISTO, True)
    # Con el estilo nativo de Windows la lista pinta las opciones con un delegado propio que ignora el QSS de las
    # opciones (altura, relleno, esquinas): con el delegado estandar si lo respeta.
    combo.setItemDelegate(QStyledItemDelegate(combo))
    vista = combo.view()
    vista.setStyleSheet(VISTA_QSS)
    contenedor = vista.window()
    if contenedor is not vista and contenedor is not combo.window():
        contenedor.setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
        )
        contenedor.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


class EstiloSelectores(QObject):
    """Prepara cada QComboBox y cada QDateEdit con calendario la primera vez que se pulen."""

    def eventFilter(self, objeto, evento) -> bool:
        if evento.type() == QEvent.Type.Polish:
            if isinstance(objeto, QComboBox):
                preparar_desplegable(objeto)
            elif isinstance(objeto, QDateEdit) and objeto.calendarPopup():
                preparar_campo_fecha(objeto)
        return False


def instalar_estilo_selectores(app: QApplication) -> EstiloSelectores:
    filtro = EstiloSelectores(app)
    app.installEventFilter(filtro)
    return filtro
