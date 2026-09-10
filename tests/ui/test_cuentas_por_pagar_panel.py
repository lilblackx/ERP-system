"""Tests de PagoProveedorDialog (app/ui/cuentas_por_pagar_panel.py) tras migrar
monto_input de QDoubleSpinBox a NumericLineEdit. A diferencia del monto_input de
PagoCobroDialog (app/ui/cuentas_por_cobrar_panel.py, mismo patron de origen
caja/cuenta pero sin campos de bolivares/tasa -- este dialogo no permite conversion de
moneda), el maximo de este campo es dinamico: el saldo_pendiente de la cuenta que se
esta pagando, no un tope fijo -- de ahi max_value=self.cuenta.saldo_pendiente en vez de
un Decimal literal.

Se prueba el dialogo, no CuentasPorPagarPanel: el panel dispara un QueryWorker en un
hilo aparte al construirse (QTimer.singleShot(100, self.cargar_cuentas)), que no aporta
cobertura extra sobre este campo."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.ui.cuentas_por_pagar_panel import PagoProveedorDialog


def _dar_foco(qtbot, campo):
    campo.window().show()
    qtbot.waitExposed(campo.window())
    campo.setFocus()
    qtbot.waitUntil(campo.hasFocus)


def _escribir_y_perder_foco(qtbot, campo, texto):
    _dar_foco(qtbot, campo)
    campo.selectAll()
    qtbot.keyClicks(campo, texto)
    campo.clearFocus()


def _crear_cuenta(saldo=Decimal("850.00")) -> SimpleNamespace:
    compra = SimpleNamespace(proveedor=SimpleNamespace(nombre_razon_social="Proveedor Uno"))
    return SimpleNamespace(id_cuenta=1, compra=compra, saldo_pendiente=saldo)


def test_monto_input_arranca_en_saldo_pendiente(qtbot):
    dialogo = PagoProveedorDialog(MagicMock(), None, _crear_cuenta(Decimal("850.00")))
    qtbot.addWidget(dialogo)
    assert dialogo.monto_input.get_value() == Decimal("850.00")
    assert dialogo.monto_input.text() == "$ 850,00"


def test_monto_input_respeta_minimo_de_0_01(qtbot):
    dialogo = PagoProveedorDialog(MagicMock(), None, _crear_cuenta(Decimal("850.00")))
    qtbot.addWidget(dialogo)
    _escribir_y_perder_foco(qtbot, dialogo.monto_input, "0")
    assert dialogo.monto_input.get_value() == Decimal("0.01")


def test_monto_input_no_permite_superar_el_saldo_pendiente(qtbot):
    dialogo = PagoProveedorDialog(MagicMock(), None, _crear_cuenta(Decimal("500.00")))
    qtbot.addWidget(dialogo)
    _escribir_y_perder_foco(qtbot, dialogo.monto_input, "999999")
    # max_value es dinamico: el saldo_pendiente de ESTA cuenta, no un tope generico.
    assert dialogo.monto_input.get_value() == Decimal("500.00")


def test_validar_y_aceptar_pasa_decimal_al_servicio(qtbot, monkeypatch):
    dialogo = PagoProveedorDialog(MagicMock(), 1, _crear_cuenta(Decimal("500.00")))
    qtbot.addWidget(dialogo)
    _escribir_y_perder_foco(qtbot, dialogo.monto_input, "123,45")

    dialogo._cajas_abiertas = [SimpleNamespace(id_caja=1, nombre_caja="Caja 1", fecha_apertura=1, fecha_cierre=None)]
    dialogo._toggle_origen()
    dialogo.origen_combo.setCurrentIndex(0)

    llamada = {}

    def fake_registrar(*args, **kwargs):
        llamada.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(
        "app.ui.cuentas_por_pagar_panel.PagoService.registrar_pago_proveedor",
        fake_registrar,
    )
    monkeypatch.setattr(
        "app.ui.cuentas_por_pagar_panel.reintentar_en_deadlock",
        lambda fn: fn(),
    )

    dialogo._validar_y_aceptar()

    assert llamada["monto"] == Decimal("123.45")
    assert isinstance(llamada["monto"], Decimal)
