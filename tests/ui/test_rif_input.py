"""Formato automatico de RIF/cedula en los formularios (app/ui/rif_input.py)."""

from PySide6.QtWidgets import QComboBox, QLineEdit

from app.ui.rif_input import conectar_formato_identificacion


def _escribir_y_terminar(qtbot, campo, texto):
    campo.window().show()
    qtbot.waitExposed(campo.window())
    campo.setFocus()
    qtbot.waitUntil(campo.hasFocus)
    campo.selectAll()
    qtbot.keyClicks(campo, texto)
    campo.clearFocus()


def _campo_con_combo(qtbot):
    campo, combo = QLineEdit(), QComboBox()
    combo.addItems(["J", "G", "V", "E", "P"])
    qtbot.addWidget(campo)
    conectar_formato_identificacion(campo, combo)
    return campo, combo


def test_con_combo_deja_solo_el_numero_formateado(qtbot):
    campo, combo = _campo_con_combo(qtbot)

    _escribir_y_terminar(qtbot, campo, "070007508")

    assert campo.text() == "07000750-8"
    assert combo.currentText() == "J"  # sin letra escrita, el combo no se toca


def test_con_combo_una_letra_pegada_selecciona_el_tipo(qtbot):
    campo, combo = _campo_con_combo(qtbot)

    _escribir_y_terminar(qtbot, campo, "v-12345678")

    assert campo.text() == "12345678"
    assert combo.currentText() == "V"


def test_con_combo_acepta_el_rif_completo_pegado(qtbot):
    campo, combo = _campo_con_combo(qtbot)

    _escribir_y_terminar(qtbot, campo, "G-20000001-0")

    assert campo.text() == "20000001-0"
    assert combo.currentText() == "G"


def test_sin_combo_queda_el_rif_completo_y_no_se_inventa_la_letra(qtbot):
    campo = QLineEdit()
    qtbot.addWidget(campo)
    conectar_formato_identificacion(campo)

    _escribir_y_terminar(qtbot, campo, "070007508")
    assert campo.text() == "07000750-8"

    _escribir_y_terminar(qtbot, campo, "j070007508")
    assert campo.text() == "J-07000750-8"


def test_el_validador_rechaza_texto_que_no_es_un_rif(qtbot):
    campo, _ = _campo_con_combo(qtbot)

    _escribir_y_terminar(qtbot, campo, "hola")

    assert campo.text() == ""


def test_la_funcion_devuelta_fuerza_el_formato_sin_perder_foco(qtbot):
    campo, combo = _campo_con_combo(qtbot)
    formatear = conectar_formato_identificacion(campo, combo)
    campo.setText("e84555111")

    formatear()

    assert campo.text() == "84555111"
    assert combo.currentText() == "E"
