"""Tests de CuentaBancariaFormDialog tras migrar saldo_input de QDoubleSpinBox a
NumericLineEdit (NumericFieldType.AMOUNT, prefix="$ "). La Session se mockea (no se
golpea la base real) -- _cargar_bancos() hace
session.query(Banco).filter(...).order_by(...).all() al construir el dialogo, asi que
esa cadena se deja vacia en el mock."""

from decimal import Decimal
from unittest.mock import MagicMock

from app.ui.cuenta_bancaria_form_dialog import CuentaBancariaFormDialog


def _session_vacia() -> MagicMock:
    session = MagicMock()
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    return session


def _dar_foco(qtbot, campo):
    # Un campo anidado dentro de un QDialog no shown() nunca resuelve el foco logico de
    # Qt bajo QT_QPA_PLATFORM=offscreen -- hay que exponer tambien la ventana top-level
    # (el dialogo), no solo el campo, antes de pedirle el foco (ver
    # tests/ui/test_proveedor_form_dialog.py, mismo gotcha).
    campo.window().show()
    qtbot.waitExposed(campo.window())
    campo.setFocus()
    qtbot.waitUntil(campo.hasFocus)


def test_saldo_input_arranca_en_cero_formateado(qtbot):
    dialogo = CuentaBancariaFormDialog(_session_vacia())
    qtbot.addWidget(dialogo)
    assert dialogo.saldo_input.text() == "$ 0,00"
    assert dialogo.saldo_input.get_value() == Decimal("0")


def test_saldo_input_formatea_al_perder_foco(qtbot):
    dialogo = CuentaBancariaFormDialog(_session_vacia())
    qtbot.addWidget(dialogo)
    _dar_foco(qtbot, dialogo.saldo_input)
    qtbot.keyClicks(dialogo.saldo_input, "12345,6")
    dialogo.saldo_input.clearFocus()
    assert dialogo.saldo_input.get_value() == Decimal("12345.60")
    assert dialogo.saldo_input.text() == "$ 12.345,60"


def test_get_data_incluye_saldo_tecleado_al_crear(qtbot):
    dialogo = CuentaBancariaFormDialog(_session_vacia())
    qtbot.addWidget(dialogo)
    _dar_foco(qtbot, dialogo.saldo_input)
    qtbot.keyClicks(dialogo.saldo_input, "999,99")
    dialogo.saldo_input.clearFocus()

    datos = dialogo.get_data()

    assert datos["saldo_total_banco"] == Decimal("999.99")


def test_precargar_deshabilita_saldo_y_no_lo_incluye_en_get_data(qtbot):
    session = _session_vacia()
    cuenta = MagicMock()
    cuenta.numero_cuenta = "0134-0001-123456789"
    cuenta.nombre_titular = "Juan Perez"
    cuenta.identificacion_titular = "V-12345678"
    cuenta.saldo_total_banco = Decimal("1000.00")
    cuenta.id_banco = None
    cuenta.tipo_cuenta_banco = "CORRIENTE"
    cuenta.fecha_creacion = None
    cuenta.creador = None

    dialogo = CuentaBancariaFormDialog(session, cuenta=cuenta)
    qtbot.addWidget(dialogo)

    assert dialogo.saldo_input.get_value() == Decimal("1000.00")
    assert dialogo.saldo_input.text() == "$ 1.000,00"
    assert not dialogo.saldo_input.isEnabled()

    datos = dialogo.get_data()
    assert "saldo_total_banco" not in datos
