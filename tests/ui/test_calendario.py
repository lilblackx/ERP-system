"""Campo de fecha y calendario de la app (app/ui/calendario.py)."""

import pytest
from PySide6.QtCore import QDate, QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDateEdit

from app.ui.calendario import CalendarioApp, preparar_campo_fecha
from app.ui.styles import COLOR_BORDER, COLOR_PRIMARY


@pytest.fixture()
def campo(qtbot):
    campo = QDateEdit()
    campo.setDisplayFormat("dd/MM/yyyy")
    campo.setDate(QDate(2026, 10, 16))
    preparar_campo_fecha(campo)
    qtbot.addWidget(campo)
    campo.show()
    qtbot.waitExposed(campo)
    return campo


def test_el_campo_usa_el_calendario_de_la_app_y_no_deja_escribir_ni_muestra_cursor_de_texto(campo):
    editor = campo.lineEdit()

    assert isinstance(campo.calendarWidget(), CalendarioApp)
    assert editor.isReadOnly()
    assert editor.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert campo.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_la_fecha_se_sigue_cambiando_con_el_teclado_aunque_el_texto_sea_de_solo_lectura(campo):
    campo.stepBy(1)

    assert campo.date() == QDate(2026, 10, 17)


@pytest.mark.parametrize("zona", ["texto", "borde_izquierdo"])
def test_un_clic_en_cualquier_parte_del_campo_abre_el_calendario(campo, qtbot, zona):
    if zona == "texto":
        QTest.mouseClick(campo.lineEdit(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, 8))
    else:
        QTest.mouseClick(
            campo, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(2, campo.height() // 2)
        )

    qtbot.waitUntil(campo.calendarWidget().isVisible, timeout=2000)
    assert QApplication.activePopupWidget() is not None


def test_un_campo_deshabilitado_no_abre_el_calendario(campo, qtbot):
    campo.setEnabled(False)

    QTest.mouseClick(campo.lineEdit(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, 8))
    qtbot.wait(300)

    assert not campo.calendarWidget().isVisible()


def test_el_calendario_respeta_el_rango_de_fechas_del_campo(qtbot):
    campo = QDateEdit()
    preparar_campo_fecha(campo)
    qtbot.addWidget(campo)

    campo.setMinimumDate(QDate(2026, 10, 10))
    campo.setMaximumDate(QDate(2026, 10, 20))

    calendario = campo.calendarWidget()
    assert (calendario.minimumDate(), calendario.maximumDate()) == (QDate(2026, 10, 10), QDate(2026, 10, 20))


def _pixeles_del_color(imagen, color: QColor) -> int:
    return sum(
        1
        for x in range(imagen.width())
        for y in range(imagen.height())
        if QColor(imagen.pixel(x, y)).rgb() == color.rgb()
    )


def test_el_dia_elegido_se_pinta_como_un_circulo_azul(qtbot):
    calendario = CalendarioApp()
    qtbot.addWidget(calendario)
    calendario.show()
    qtbot.waitExposed(calendario)
    calendario.setSelectedDate(QDate(2026, 10, 16))
    qtbot.wait(100)
    azul = QColor(COLOR_PRIMARY)

    con_seleccion = _pixeles_del_color(calendario.grab().toImage(), azul)

    # un circulo de ~28 px de diametro son cientos de pixeles; el resto del calendario casi no usa ese azul
    assert con_seleccion > 300


def test_preparar_dos_veces_un_campo_no_cambia_su_calendario(qtbot):
    campo = QDateEdit()
    qtbot.addWidget(campo)
    preparar_campo_fecha(campo)
    calendario = campo.calendarWidget()

    preparar_campo_fecha(campo)

    assert campo.calendarWidget() is calendario


def test_los_campos_de_fecha_de_las_barras_de_filtros_llevan_borde_e_icono_de_calendario(qtbot):
    """Sin borde se confundian con un texto suelto: ahora son el campo estandar de la app, como los combos."""
    import app.ui.reportes_panel as rp
    from app.ui.styles import CAMPO_FECHA_QSS

    campo = rp._crear_fecha_edit()
    qtbot.addWidget(campo)

    assert campo.styleSheet() == CAMPO_FECHA_QSS
    assert "border: 1px solid" in campo.styleSheet()
    assert "calendar.png" in campo.styleSheet()


def test_el_calendario_lleva_borde_en_los_cuatro_lados(qtbot):
    """La barra de navegacion y la tabla tapaban el borde (sobre todo el de arriba): parecia un calendario sin marco."""
    calendario = CalendarioApp()
    qtbot.addWidget(calendario)
    calendario.show()
    qtbot.waitExposed(calendario)
    imagen = calendario.grab().toImage()
    borde = QColor(COLOR_BORDER).rgb()
    ancho, alto = imagen.width(), imagen.height()

    puntos = {
        "arriba": (ancho // 2, 0),
        "abajo": (ancho // 2, alto - 1),
        "izquierda": (0, alto // 2),
        "derecha": (ancho - 1, alto // 2),
    }
    for lado, (x, y) in puntos.items():
        assert QColor(imagen.pixel(x, y)).rgb() == borde, lado


def test_el_campo_del_anio_del_calendario_no_lleva_flechitas_nativas_ni_seleccion_oscura(qtbot):
    from PySide6.QtWidgets import QAbstractSpinBox, QSpinBox

    from app.ui.calendario import CALENDARIO_QSS

    calendario = CalendarioApp()
    qtbot.addWidget(calendario)

    anio = calendario.findChild(QSpinBox, "qt_calendar_yearedit")

    assert anio.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
    assert "selection-background-color" in CALENDARIO_QSS
