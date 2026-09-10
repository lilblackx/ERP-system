"""Tests de MovimientoManualDialog (app/ui/cajas_panel.py) tras migrar monto_input de
QDoubleSpinBox (rango 0.01-999999999.99) a NumericLineEdit
(NumericFieldType.AMOUNT, min_value=Decimal("0.01")). El dialogo no toma Session -- es
un formulario minimo sin consultas contra la base."""

from decimal import Decimal

from app.ui.cajas_panel import MovimientoManualDialog


def _dar_foco(qtbot, campo):
    campo.window().show()
    qtbot.waitExposed(campo.window())
    campo.setFocus()
    qtbot.waitUntil(campo.hasFocus)


def _escribir_y_perder_foco(qtbot, campo, texto):
    _dar_foco(qtbot, campo)
    qtbot.keyClicks(campo, texto)
    campo.clearFocus()


def test_monto_input_arranca_en_cero_formateado(qtbot):
    dialogo = MovimientoManualDialog()
    qtbot.addWidget(dialogo)
    assert dialogo.monto_input.text() == "$ 0,00"
    assert dialogo.monto_input.get_value() == Decimal("0")


def test_monto_input_formatea_miles_al_perder_foco(qtbot):
    dialogo = MovimientoManualDialog()
    qtbot.addWidget(dialogo)
    _escribir_y_perder_foco(qtbot, dialogo.monto_input, "125000,75")
    assert dialogo.monto_input.get_value() == Decimal("125000.75")
    assert dialogo.monto_input.text() == "$ 125.000,75"


def test_monto_input_se_ajusta_al_minimo_de_0_01(qtbot):
    dialogo = MovimientoManualDialog()
    qtbot.addWidget(dialogo)
    _escribir_y_perder_foco(qtbot, dialogo.monto_input, "0")
    assert dialogo.monto_input.get_value() == Decimal("0.01")
    assert dialogo.monto_input.toolTip() != ""


def test_monto_input_no_admite_negativos(qtbot):
    dialogo = MovimientoManualDialog()
    qtbot.addWidget(dialogo)
    _dar_foco(qtbot, dialogo.monto_input)
    qtbot.keyClicks(dialogo.monto_input, "-5")
    assert dialogo.monto_input.text() == "5"


def test_get_data_incluye_monto_decimal(qtbot):
    dialogo = MovimientoManualDialog()
    qtbot.addWidget(dialogo)
    _escribir_y_perder_foco(qtbot, dialogo.monto_input, "300")

    datos = dialogo.get_data()

    assert datos["monto"] == Decimal("300.00")
