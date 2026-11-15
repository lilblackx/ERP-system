"""Campo de fecha y calendario de toda la app.

Antes cada pantalla armaba su propio QDateEdit con su propio QSS (hasta tres copias distintas), el calendario era el
nativo con una barra azul encima, y el campo dejaba ver el cursor de texto aunque la fecha se elige en el calendario.
Ahora hay una sola pieza:

  * `CalendarioApp`: calendario de fondo blanco, con el dia elegido en un circulo azul y el de hoy con un aro.
  * `preparar_campo_fecha(date_edit)`: le da al campo el aspecto estandar (borde e icono de calendario), pone ese
    calendario, lo deja de solo lectura (sin cursor de texto ni escritura) y hace que un clic en cualquier parte del
    campo abra el calendario, no solo la flechita.
"""

import qtawesome as qta
from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCalendarWidget,
    QDateEdit,
    QSpinBox,
    QStyle,
    QStyleOptionComboBox,
    QToolButton,
)

from app.ui.styles import (
    CAMPO_FECHA_QSS,
    COLOR_BLUE_LIGHT,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_PRIMARY,
    COLOR_TEXT_DARK,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MUTED,
    COLOR_WHITE,
    FONT_FAMILY,
)

# El calendario se pinta celda por celda (ver CalendarioApp.paintCell); el QSS solo cubre la barra de navegacion y el
# marco. Sin esquinas redondeadas a proposito: el calendario se abre en una ventana emergente propia y con el borde
# redondeado las esquinas de esa ventana se veian negras. Los nombres qt_calendar_* son los objectName fijos que Qt
# le da a esas piezas.
CALENDARIO_QSS = f"""
QCalendarWidget {{
    background-color: {COLOR_CARD_BG};
    border: 1px solid {COLOR_BORDER};
    font-family: '{FONT_FAMILY}', Arial, sans-serif;
}}
QCalendarWidget QWidget#qt_calendar_navigationbar {{
    background-color: {COLOR_CARD_BG};
    border: none;
    padding: 4px 6px 0px 6px;
}}
QCalendarWidget QToolButton {{
    color: {COLOR_TEXT_DARK};
    background-color: transparent;
    border: none;
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 14px;
    font-weight: 600;
}}
QCalendarWidget QToolButton:hover {{
    background-color: {COLOR_CONTENT_BG};
}}
QCalendarWidget QToolButton#qt_calendar_prevmonth, QCalendarWidget QToolButton#qt_calendar_nextmonth {{
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
    border-radius: 14px;
    padding: 0px;
}}
QCalendarWidget QToolButton::menu-indicator {{
    image: none;
}}
QCalendarWidget QSpinBox {{
    color: {COLOR_TEXT_DARK};
    background-color: {COLOR_CARD_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 2px 6px;
    min-width: 52px;
    font-size: 14px;
    font-weight: 600;
    selection-background-color: {COLOR_BLUE_LIGHT};
    selection-color: {COLOR_PRIMARY};
}}
QCalendarWidget QSpinBox:focus {{
    border-color: {COLOR_PRIMARY};
}}
QCalendarWidget QSpinBox::up-button, QCalendarWidget QSpinBox::down-button {{
    width: 0px;
    border: none;
}}
QCalendarWidget QMenu {{
    background-color: {COLOR_CARD_BG};
    border: 1px solid {COLOR_BORDER};
    color: {COLOR_TEXT_DARK};
    padding: 4px;
}}
QCalendarWidget QMenu::item {{
    padding: 5px 18px;
    border-radius: 4px;
}}
QCalendarWidget QMenu::item:selected {{
    background-color: {COLOR_CONTENT_BG};
    color: {COLOR_PRIMARY};
}}
QCalendarWidget QAbstractItemView {{
    background-color: {COLOR_CARD_BG};
    alternate-background-color: {COLOR_CARD_BG};
    outline: none;
    selection-background-color: transparent;
}}
QCalendarWidget QHeaderView {{
    background-color: {COLOR_CARD_BG};
}}
QCalendarWidget QHeaderView::section {{
    background-color: {COLOR_CARD_BG};
    color: {COLOR_TEXT_MUTED};
    border: none;
    padding: 6px 0px 4px 0px;
    font-size: 11px;
    font-weight: 600;
}}
"""


class CalendarioApp(QCalendarWidget):
    """Calendario de la app: celdas pintadas a mano (circulo para el dia elegido, aro para hoy)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)  # sin esto el QSS no dibuja el borde del calendario
        self.setContentsMargins(1, 1, 1, 1)  # deja libre el pixel del borde: los hijos lo tapaban
        self.setGridVisible(False)
        self.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.setStyleSheet(CALENDARIO_QSS)
        formato_semana = self.weekdayTextFormat(Qt.DayOfWeek.Monday)
        formato_semana.setForeground(QColor(COLOR_TEXT_MUTED))  # sin el rojo del sabado/domingo
        for dia in Qt.DayOfWeek:
            self.setWeekdayTextFormat(dia, formato_semana)
        for nombre, icono in (
            ("qt_calendar_prevmonth", "fa5s.chevron-left"),
            ("qt_calendar_nextmonth", "fa5s.chevron-right"),
        ):
            boton = self.findChild(QToolButton, nombre)
            if boton is not None:
                boton.setIcon(qta.icon(icono, color=COLOR_TEXT_MUTED))
        anio = self.findChild(QSpinBox, "qt_calendar_yearedit")
        if anio is not None:
            anio.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)  # se cambia de anio con las flechas del mes
        self.setMinimumSize(310, 270)

    def paintCell(self, painter: QPainter, rect, date) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        habilitada = self.minimumDate() <= date <= self.maximumDate()
        del_mes = date.month() == self.monthShown() and date.year() == self.yearShown()
        elegida = date == self.selectedDate()
        es_hoy = date == date.currentDate()
        lado = max(min(rect.width(), rect.height()) - 6, 10)
        circulo = QRectF(0, 0, lado, lado)
        circulo.moveCenter(QPointF(rect.center()) + QPointF(0.5, 0.5))

        fuente = QFont(painter.font())
        fuente.setPixelSize(13)
        color_texto = QColor(COLOR_TEXT_DARK)
        if elegida and habilitada:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLOR_PRIMARY))
            painter.drawEllipse(circulo)
            color_texto = QColor(COLOR_WHITE)
            fuente.setBold(True)
        elif es_hoy:
            painter.setPen(QPen(QColor(COLOR_PRIMARY), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(circulo)
            color_texto = QColor(COLOR_PRIMARY)
            fuente.setBold(True)
        if not habilitada:
            color_texto = QColor(COLOR_BORDER)
        elif not del_mes and not elegida:
            color_texto = QColor(COLOR_TEXT_LIGHT)
        painter.setFont(fuente)
        painter.setPen(color_texto)
        painter.drawText(QRectF(rect), Qt.AlignmentFlag.AlignCenter, str(date.day()))
        painter.restore()


class _AbrirAlClic(QObject):
    """Un clic en cualquier parte del campo abre el calendario. QDateEdit solo lo abre al pulsar la flecha; el resto
    del campo (el texto, el relleno) no hacia nada, y con el cursor de texto parecia un campo editable."""

    def __init__(self, date_edit: QDateEdit):
        super().__init__(date_edit)
        self._campo = date_edit

    def _flecha(self):
        opcion = QStyleOptionComboBox()
        opcion.initFrom(self._campo)
        opcion.subControls = QStyle.SubControl.SC_All
        return self._campo.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox, opcion, QStyle.SubControl.SC_ComboBoxArrow, self._campo
        )

    def eventFilter(self, objeto, evento) -> bool:
        if (
            evento.type() != QEvent.Type.MouseButtonPress
            or evento.button() != Qt.MouseButton.LeftButton
            or not self._campo.isEnabled()
        ):
            return False
        flecha = self._flecha()
        if objeto is self._campo and flecha.contains(evento.position().toPoint()):
            return False  # el campo ya abre el calendario si el clic cae en la flecha: solo se ayuda al resto
        centro = QPointF(flecha.center())
        pulsacion = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            centro,
            self._campo.mapToGlobal(centro),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(self._campo, pulsacion)
        return True


_LISTO = "_campo_fecha_listo"


def preparar_campo_fecha(date_edit: QDateEdit) -> None:
    """Campo de fecha de la app: calendario propio, solo lectura (sin cursor de texto) y se abre con un clic en
    cualquier parte. Se puede seguir cambiando con el teclado (flechas arriba/abajo). Es idempotente: el filtro de la
    aplicacion (estilo_selectores.py) lo llama solo para cualquier campo con calendario que no lo haya recibido."""
    if date_edit.property(_LISTO):
        return
    date_edit.setProperty(_LISTO, True)
    date_edit.setStyleSheet(CAMPO_FECHA_QSS)  # un solo aspecto en toda la app, sea cual sea el QSS de su pantalla
    date_edit.setCalendarPopup(True)
    date_edit.setCalendarWidget(CalendarioApp())
    editor = date_edit.lineEdit()
    editor.setReadOnly(True)
    editor.setCursor(Qt.CursorShape.PointingHandCursor)
    date_edit.setCursor(Qt.CursorShape.PointingHandCursor)
    filtro = _AbrirAlClic(date_edit)
    editor.installEventFilter(filtro)
    date_edit.installEventFilter(filtro)
