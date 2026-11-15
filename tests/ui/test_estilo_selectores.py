"""Aspecto unico de desplegables y campos de fecha (app/ui/estilo_selectores.py)."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDateEdit, QStyledItemDelegate

from app.ui.calendario import CalendarioApp
from app.ui.estilo_selectores import EstiloSelectores, instalar_estilo_selectores, preparar_desplegable


def _combo(qtbot):
    combo = QComboBox()
    combo.addItems(["Todos", "Uno", "Dos"])
    qtbot.addWidget(combo)
    return combo


def test_preparar_un_desplegable_le_da_el_delegado_estandar_el_qss_y_la_lista_redondeada(qtbot):
    combo = _combo(qtbot)

    preparar_desplegable(combo)

    assert isinstance(combo.itemDelegate(), QStyledItemDelegate)
    assert "border-radius" in combo.view().styleSheet()
    assert combo.view().window().testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def test_preparar_dos_veces_no_vuelve_a_tocar_el_combo(qtbot):
    combo = _combo(qtbot)
    preparar_desplegable(combo)
    delegado = combo.itemDelegate()

    preparar_desplegable(combo)

    assert combo.itemDelegate() is delegado


def test_el_filtro_de_la_aplicacion_prepara_cada_combo_al_mostrarse(qtbot, qapp):
    filtro = EstiloSelectores(qapp)
    qapp.installEventFilter(filtro)
    try:
        combo = _combo(qtbot)
        combo.show()
        qtbot.waitExposed(combo)

        assert combo.property("_desplegable_listo") is True
        assert "border-radius" in combo.view().styleSheet()
    finally:
        qapp.removeEventFilter(filtro)


@pytest.mark.parametrize("n_items", [0, 1])
def test_un_combo_vacio_o_de_un_item_tambien_se_prepara_sin_errores(qtbot, n_items):
    combo = QComboBox()
    combo.addItems(["Unico"][:n_items])
    qtbot.addWidget(combo)

    preparar_desplegable(combo)

    assert combo.property("_desplegable_listo") is True


def test_el_filtro_tambien_da_el_calendario_de_la_app_a_cualquier_campo_de_fecha_con_calendario(qtbot, qapp):
    filtro = EstiloSelectores(qapp)
    qapp.installEventFilter(filtro)
    try:
        campo = QDateEdit()
        campo.setCalendarPopup(True)  # un campo nuevo, sin acordarse de llamar a ningun ayudante
        qtbot.addWidget(campo)
        campo.show()
        qtbot.waitExposed(campo)

        assert isinstance(campo.calendarWidget(), CalendarioApp)
        assert campo.lineEdit().isReadOnly()
    finally:
        qapp.removeEventFilter(filtro)


def test_el_filtro_no_toca_un_campo_de_fecha_sin_calendario(qtbot, qapp):
    filtro = EstiloSelectores(qapp)
    qapp.installEventFilter(filtro)
    try:
        campo = QDateEdit()  # sin popup: un simple campo de fecha editable
        qtbot.addWidget(campo)
        campo.show()
        qtbot.waitExposed(campo)

        assert not campo.lineEdit().isReadOnly()
    finally:
        qapp.removeEventFilter(filtro)


def test_instalar_el_estilo_deja_un_filtro_en_la_aplicacion(qapp):
    filtro = instalar_estilo_selectores(qapp)
    try:
        assert isinstance(filtro, EstiloSelectores)
    finally:
        qapp.removeEventFilter(filtro)


def test_el_aspecto_del_campo_de_fecha_gana_al_qss_propio_de_la_pantalla(qtbot, qapp):
    """Los formularios traen su propio QSS para QDateEdit: el campo de la app se ve igual en todas."""
    from PySide6.QtWidgets import QWidget

    from app.ui.styles import CAMPO_FECHA_QSS

    filtro = EstiloSelectores(qapp)
    qapp.installEventFilter(filtro)
    try:
        pantalla = QWidget()
        pantalla.setStyleSheet("QDateEdit { border: 3px dashed red; }")
        campo = QDateEdit(pantalla)
        campo.setCalendarPopup(True)
        campo.setEnabled(False)  # como los campos de vencimiento, que arrancan deshabilitados
        qtbot.addWidget(pantalla)
        pantalla.show()
        qtbot.waitExposed(pantalla)

        assert campo.styleSheet() == CAMPO_FECHA_QSS
        assert "QDateEdit:disabled" in CAMPO_FECHA_QSS
        assert campo.lineEdit().isReadOnly()
    finally:
        qapp.removeEventFilter(filtro)


def test_la_lista_de_un_combo_gana_a_la_regla_propia_de_la_pantalla(qtbot, qapp):
    from PySide6.QtWidgets import QWidget

    filtro = EstiloSelectores(qapp)
    qapp.installEventFilter(filtro)
    try:
        pantalla = QWidget()
        pantalla.setStyleSheet("QComboBox QAbstractItemView { background-color: red; }")
        combo = QComboBox(pantalla)
        combo.addItems(["A", "B"])
        qtbot.addWidget(pantalla)
        pantalla.show()
        qtbot.waitExposed(pantalla)

        assert "border-radius" in combo.view().styleSheet()  # el QSS del propio widget gana al heredado
    finally:
        qapp.removeEventFilter(filtro)


def test_la_app_instala_el_filtro_de_selectores_antes_de_abrir_ventanas():
    import inspect

    import app.main as principal

    fuente = inspect.getsource(principal.main)

    assert "instalar_estilo_selectores(app)" in fuente
    assert fuente.index("instalar_estilo_selectores(app)") < fuente.index("LoginWindow(")
