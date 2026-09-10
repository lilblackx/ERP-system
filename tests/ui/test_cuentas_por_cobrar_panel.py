"""Tests de PagoCobroDialog (app/ui/cuentas_por_cobrar_panel.py) tras migrar
monto_input/bolivares_input/tasa_input de QDoubleSpinBox a NumericLineEdit:
- monto_input: NumericFieldType.AMOUNT, min_value=0.01, prefix "$ " (min original), con
  el saldo_pendiente de la cuenta como valor inicial (no 0 -- ver set_value tras
  construir el campo).
- bolivares_input: NumericFieldType.AMOUNT, max_value=999999999999 (rango original).
- tasa_input: NumericFieldType.RATE (0.01-999999, igual al rango original).

Se prueba el dialogo completo, no el panel: CuentasPorCobrarPanel dispara un
QueryWorker en un hilo aparte al construirse (QTimer.singleShot(100,
self.cargar_cuentas)), que no aporta cobertura sobre estos 3 campos y complica el test
sin necesidad. PagoCobroDialog en cambio solo necesita una Session mockeada -- sus
_cargar_origenes()/_cargar_tasas() ya manejan tanto PermisoDenegadoError (id_usuario=None
cae ahi, ver require_permiso en app/services/permisos.py) como cualquier excepcion de la
consulta de tasas, pero *no* validan el tipo de lo que devuelve `session.query(...).first()`
-- con un MagicMock() liso eso devuelve otro MagicMock "verdadero" que revienta el
formateo de tasas (`f"{...:,.2f}"`), asi que hay que fijar ese `.first()` a None a mano."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.ui.cuentas_por_cobrar_panel import PagoCobroDialog


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


def _crear_sesion() -> MagicMock:
    session = MagicMock()
    # _cargar_tasas() hace session.query(ControlDeTasa).order_by(...).first(): sin fijar
    # esto a None devuelve un MagicMock "verdadero" que revienta el f"{...:,.2f}" de mas
    # abajo en ese metodo.
    session.query.return_value.order_by.return_value.first.return_value = None
    return session


def _crear_cuenta(saldo=Decimal("1250.75")) -> SimpleNamespace:
    factura = SimpleNamespace(numero_factura="F-001", cliente=SimpleNamespace(nombre_razon_social="Cliente Uno"))
    return SimpleNamespace(id_cuenta_por_cobrar=1, factura=factura, saldo_pendiente=saldo)


def test_monto_input_arranca_en_saldo_pendiente(qtbot):
    dialogo = PagoCobroDialog(_crear_sesion(), None, _crear_cuenta(Decimal("1250.75")))
    qtbot.addWidget(dialogo)
    assert dialogo.monto_input.get_value() == Decimal("1250.75")
    assert dialogo.monto_input.text() == "$ 1.250,75"


def test_monto_input_respeta_minimo_de_0_01(qtbot):
    dialogo = PagoCobroDialog(_crear_sesion(), None, _crear_cuenta())
    qtbot.addWidget(dialogo)
    _escribir_y_perder_foco(qtbot, dialogo.monto_input, "0")
    assert dialogo.monto_input.get_value() == Decimal("0.01")


def _mostrar_campos_bolivares(dialogo) -> None:
    # bolivares_input/tasa_input viven en campos_bolivares_widget, oculto salvo que el
    # metodo de pago sea "transferencia" (_toggle_campos_bolivares) -- un campo oculto
    # nunca puede recibir foco, hay que seleccionar ese metodo primero.
    idx = dialogo.metodo_combo.findData("transferencia")
    assert idx >= 0
    dialogo.metodo_combo.setCurrentIndex(idx)


def test_bolivares_input_arranca_en_cero_y_admite_rango_amplio(qtbot):
    dialogo = PagoCobroDialog(_crear_sesion(), None, _crear_cuenta())
    qtbot.addWidget(dialogo)
    assert dialogo.bolivares_input.get_value() == Decimal("0")
    _mostrar_campos_bolivares(dialogo)
    _escribir_y_perder_foco(qtbot, dialogo.bolivares_input, "999999999999")
    assert dialogo.bolivares_input.get_value() == Decimal("999999999999.00")


def test_tasa_input_es_de_tipo_rate(qtbot):
    dialogo = PagoCobroDialog(_crear_sesion(), None, _crear_cuenta())
    qtbot.addWidget(dialogo)
    _mostrar_campos_bolivares(dialogo)
    _escribir_y_perder_foco(qtbot, dialogo.tasa_input, "0")
    # RATE tiene min_value=0.01 por defecto -- un 0 tecleado se ajusta al piso.
    assert dialogo.tasa_input.get_value() == Decimal("0.01")


def test_calcular_monto_usd_divide_bolivares_entre_tasa(qtbot):
    dialogo = PagoCobroDialog(_crear_sesion(), None, _crear_cuenta())
    qtbot.addWidget(dialogo)
    _mostrar_campos_bolivares(dialogo)  # tambien fuerza metodo "transferencia"

    _escribir_y_perder_foco(qtbot, dialogo.tasa_input, "50")
    _escribir_y_perder_foco(qtbot, dialogo.bolivares_input, "500")

    assert dialogo.monto_input.get_value() == Decimal("10")


def test_validar_y_aceptar_pasa_decimal_al_servicio(qtbot, monkeypatch):
    dialogo = PagoCobroDialog(_crear_sesion(), 1, _crear_cuenta(Decimal("300")))
    qtbot.addWidget(dialogo)
    dialogo._cajas_abiertas = [SimpleNamespace(id_caja=1, nombre_caja="Caja 1", fecha_apertura=1, fecha_cierre=None)]
    dialogo._toggle_origen()
    dialogo.origen_combo.setCurrentIndex(0)

    llamada = {}

    def fake_registrar(*args, **kwargs):
        llamada.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(
        "app.ui.cuentas_por_cobrar_panel.PagoService.registrar_pago_cobro",
        fake_registrar,
    )
    monkeypatch.setattr(
        "app.ui.cuentas_por_cobrar_panel.reintentar_en_deadlock",
        lambda fn: fn(),
    )

    dialogo._validar_y_aceptar()

    assert llamada["monto"] == Decimal("300")
    assert isinstance(llamada["monto"], Decimal)
