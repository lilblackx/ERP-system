"""Tests de TasaRegistroDialog tras migrar bcv_input/paralelo_input/cop_input de
QDoubleSpinBox a NumericLineEdit (NumericFieldType.RATE, con min_value/max_value
explicitos para preservar el rango original de cada campo -- ver
app/ui/tasa_registro_dialog.py). No requiere Session: el dialogo no toca la base."""

from decimal import Decimal

from app.ui.tasa_registro_dialog import TasaRegistroDialog


def _dar_foco(qtbot, campo):
    # Un campo anidado dentro de un QDialog no shown() nunca resuelve el foco logico de
    # Qt bajo QT_QPA_PLATFORM=offscreen -- hay que exponer tambien la ventana top-level
    # (el dialogo), no solo el campo, antes de pedirle el foco (ver
    # tests/ui/test_proveedor_form_dialog.py, mismo gotcha).
    campo.window().show()
    qtbot.waitExposed(campo.window())
    campo.setFocus()
    qtbot.waitUntil(campo.hasFocus)


def test_campos_arrancan_en_cero_formateados(qtbot):
    dialogo = TasaRegistroDialog()
    qtbot.addWidget(dialogo)
    assert dialogo.bcv_input.text() == "0,00"
    assert dialogo.paralelo_input.text() == "0,00"
    assert dialogo.cop_input.text() == "0,00"


def test_bcv_formatea_miles_al_perder_foco(qtbot):
    dialogo = TasaRegistroDialog()
    qtbot.addWidget(dialogo)
    _dar_foco(qtbot, dialogo.bcv_input)
    qtbot.keyClicks(dialogo.bcv_input, "123456,78")
    dialogo.bcv_input.clearFocus()
    assert dialogo.bcv_input.get_value() == Decimal("123456.78")
    assert dialogo.bcv_input.text() == "123.456,78"


def test_get_data_convierte_paralelo_y_cop_en_cero_a_none(qtbot):
    dialogo = TasaRegistroDialog()
    qtbot.addWidget(dialogo)
    _dar_foco(qtbot, dialogo.bcv_input)
    qtbot.keyClicks(dialogo.bcv_input, "45,50")
    dialogo.bcv_input.clearFocus()

    datos = dialogo.get_data()

    assert datos["tasa_bcv"] == Decimal("45.50")
    assert datos["tasa_paralelo"] is None
    assert datos["tasa_cop"] is None


def test_get_data_incluye_paralelo_y_cop_cuando_se_completan(qtbot):
    dialogo = TasaRegistroDialog()
    qtbot.addWidget(dialogo)
    _dar_foco(qtbot, dialogo.bcv_input)
    qtbot.keyClicks(dialogo.bcv_input, "45,50")
    dialogo.bcv_input.clearFocus()

    _dar_foco(qtbot, dialogo.paralelo_input)
    qtbot.keyClicks(dialogo.paralelo_input, "60,25")
    dialogo.paralelo_input.clearFocus()

    _dar_foco(qtbot, dialogo.cop_input)
    qtbot.keyClicks(dialogo.cop_input, "15000")
    dialogo.cop_input.clearFocus()

    datos = dialogo.get_data()

    assert datos["tasa_bcv"] == Decimal("45.50")
    assert datos["tasa_paralelo"] == Decimal("60.25")
    assert datos["tasa_cop"] == Decimal("15000")


def test_validar_y_aceptar_rechaza_bcv_en_cero(qtbot, monkeypatch):
    # MessageBox.warning() abre un QDialog modal (.exec()) -- se reemplaza por un no-op
    # para no bloquear el test esperando un click que nunca llega bajo offscreen.
    monkeypatch.setattr("app.ui.tasa_registro_dialog.MessageBox.warning", lambda *a, **k: None)
    dialogo = TasaRegistroDialog()
    qtbot.addWidget(dialogo)
    aceptado = []
    dialogo.accept = lambda: aceptado.append(True)
    dialogo._validar_y_aceptar()
    assert not aceptado
