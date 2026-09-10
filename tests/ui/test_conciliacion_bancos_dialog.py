"""Tests de ConciliacionBancosDialog tras migrar saldo_final_input (AMOUNT,
allow_negative=True -- el QDoubleSpinBox original permitia rango
(-999999999.99, 999999999.99)) y MovimientoManualDialog.monto_input (AMOUNT, sin
negativos) de QDoubleSpinBox a NumericLineEdit. Ver app/ui/conciliacion_bancos_dialog.py.

ConciliacionBancosDialog._cargar_cuentas() hace una consulta ORM real
(session.query(CuentaBancaria).join(Banco).filter(...).order_by(...).all()) -- se mockea
esa cadena para que devuelva una lista vacia, dejando cuenta_combo sin seleccion (lo que
hace que _calcular_conciliacion(), conectado al valueChanged de saldo_final_input,
retorne temprano sin tocar la sesion)."""

from decimal import Decimal
from unittest.mock import MagicMock

from app.ui.conciliacion_bancos_dialog import ConciliacionBancosDialog, MovimientoManualDialog


def _dar_foco(qtbot, campo):
    campo.window().show()
    qtbot.waitExposed(campo.window())
    campo.setFocus()
    qtbot.waitUntil(campo.hasFocus)


def _escribir_y_perder_foco(qtbot, campo, texto):
    _dar_foco(qtbot, campo)
    qtbot.keyClicks(campo, texto)
    campo.clearFocus()


def _session_sin_cuentas() -> MagicMock:
    session = MagicMock()
    session.query.return_value.join.return_value.filter.return_value.order_by.return_value.all.return_value = []
    return session


def test_saldo_final_input_arranca_en_cero_formateado(qtbot):
    dialogo = ConciliacionBancosDialog(_session_sin_cuentas(), MagicMock())
    qtbot.addWidget(dialogo)
    assert dialogo.saldo_final_input.text() == "$ 0,00"
    assert dialogo.saldo_final_input.get_value() == Decimal("0")


def test_saldo_final_input_admite_valores_negativos(qtbot):
    dialogo = ConciliacionBancosDialog(_session_sin_cuentas(), MagicMock())
    qtbot.addWidget(dialogo)
    _escribir_y_perder_foco(qtbot, dialogo.saldo_final_input, "-1500,25")
    assert dialogo.saldo_final_input.get_value() == Decimal("-1500.25")
    assert dialogo.saldo_final_input.text() == "$ -1.500,25"


def test_saldo_final_input_formatea_miles_al_perder_foco(qtbot):
    dialogo = ConciliacionBancosDialog(_session_sin_cuentas(), MagicMock())
    qtbot.addWidget(dialogo)
    _escribir_y_perder_foco(qtbot, dialogo.saldo_final_input, "250000")
    assert dialogo.saldo_final_input.get_value() == Decimal("250000.00")
    assert dialogo.saldo_final_input.text() == "$ 250.000,00"


def test_movimiento_manual_monto_input_arranca_en_cero_formateado(qtbot):
    dialogo = MovimientoManualDialog("abono")
    qtbot.addWidget(dialogo)
    assert dialogo.monto_input.text() == "$ 0,00"
    assert dialogo.monto_input.get_value() == Decimal("0")


def test_movimiento_manual_monto_input_no_admite_negativos(qtbot):
    dialogo = MovimientoManualDialog("cargo")
    qtbot.addWidget(dialogo)
    _dar_foco(qtbot, dialogo.monto_input)
    qtbot.keyClicks(dialogo.monto_input, "-5")
    assert dialogo.monto_input.text() == "5"


def test_movimiento_manual_get_data_devuelve_monto_float(qtbot):
    dialogo = MovimientoManualDialog("abono")
    qtbot.addWidget(dialogo)
    _escribir_y_perder_foco(qtbot, dialogo.monto_input, "1234,56")

    datos = dialogo.get_data()

    assert datos["monto"] == 1234.56
    assert isinstance(datos["monto"], float)
