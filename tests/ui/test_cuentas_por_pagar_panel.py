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

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.ui.cuentas_por_pagar_panel as cpp
from app.services.permisos import PermisoDenegadoError
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


# -- DetalleCuentaPorPagarDialog: historial de pagos de una cuenta ------------------------

COL_FECHA, COL_MONTO_USD, COL_MONTO_BS, COL_TASA, COL_METODO, COL_ORIGEN, COL_REFERENCIA = range(1, 8)


def _cuenta_detalle(saldo=Decimal("120.00"), vencimiento=date(2026, 11, 5)):
    compra = SimpleNamespace(
        numero_compra="C-0001",
        proveedor=SimpleNamespace(nombre_razon_social="Proveedor Uno"),
    )
    return SimpleNamespace(id_cuenta=3, compra=compra, saldo_pendiente=saldo, fecha_vencimiento=vencimiento)


def _pago(id_pago=1, monto="30.00", monto_bs="1200.00", tasa="40.00", metodo="transferencia", **overrides):
    datos = {
        "id_pago_proveedor": id_pago,
        "fecha_pago": datetime(2026, 10, 16, 14, 30),
        "monto": Decimal(monto),
        "monto_bolivares": Decimal(monto_bs) if monto_bs is not None else None,
        "tasa_cambio": Decimal(tasa) if tasa is not None else None,
        "metodo_pago": metodo,
        "caja": None,
        "cuenta_bancaria": None,
        "referencia": "REF-9",
    }
    datos.update(overrides)
    return SimpleNamespace(**datos)


def _dialogo_detalle(qtbot, monkeypatch, pagos=None, error=None, cuenta=None):
    llamadas = {}

    def fake_listar(session, **kwargs):
        llamadas.update(kwargs)
        if error is not None:
            raise error
        return pagos or []

    monkeypatch.setattr(cpp.PagoService, "listar_pagos_proveedor", staticmethod(fake_listar))
    dialogo = cpp.DetalleCuentaPorPagarDialog(MagicMock(), cuenta or _cuenta_detalle(), 9)
    qtbot.addWidget(dialogo)
    return dialogo, llamadas


def _celdas(dialogo, fila):
    return [dialogo.tabla_pagos.item(fila, c).text() for c in range(1, 8)]


def test_detalle_pide_los_pagos_de_esa_cuenta_con_el_usuario_actual(qtbot, monkeypatch):
    _, llamadas = _dialogo_detalle(qtbot, monkeypatch, pagos=[])

    assert llamadas == {"id_cuenta_por_pagar": 3, "id_usuario": 9}


def test_detalle_muestra_monto_usd_bs_tasa_metodo_y_referencia(qtbot, monkeypatch):
    dialogo, _ = _dialogo_detalle(qtbot, monkeypatch, pagos=[_pago()])

    assert dialogo.tabla_pagos.rowCount() == 1
    assert _celdas(dialogo, 0) == [
        "16/10/2026 14:30",
        "$30.00",
        "1,200.00",
        "40.00",
        "Transferencia",
        "N/A",
        "REF-9",
    ]


def test_detalle_pago_en_dolares_sin_bs_ni_tasa_muestra_guiones(qtbot, monkeypatch):
    pago = _pago(monto_bs=None, tasa=None, metodo="efectivo")

    dialogo, _ = _dialogo_detalle(qtbot, monkeypatch, pagos=[pago])

    celdas = _celdas(dialogo, 0)
    assert celdas[COL_MONTO_BS - 1] == "-"
    assert celdas[COL_TASA - 1] == "-"
    assert celdas[COL_MONTO_USD - 1] == "$30.00"


def test_detalle_origen_caja_usa_el_nombre_de_la_caja(qtbot, monkeypatch):
    pago = _pago(caja=SimpleNamespace(id_caja=4, nombre_caja="Caja Principal"))

    dialogo, _ = _dialogo_detalle(qtbot, monkeypatch, pagos=[pago])

    assert _celdas(dialogo, 0)[COL_ORIGEN - 1] == "Caja: Caja Principal"


def test_detalle_origen_banco_muestra_banco_y_ultimos_4_digitos(qtbot, monkeypatch):
    cuenta_bancaria = SimpleNamespace(
        numero_cuenta="01340000001234567890",
        banco=SimpleNamespace(nombre_banco="Banesco"),
    )
    pago = _pago(cuenta_bancaria=cuenta_bancaria)

    dialogo, _ = _dialogo_detalle(qtbot, monkeypatch, pagos=[pago])

    assert _celdas(dialogo, 0)[COL_ORIGEN - 1] == "Banesco - ...7890"


def test_detalle_con_varios_pagos_los_lista_en_orden(qtbot, monkeypatch):
    pagos = [_pago(1, monto="10.00"), _pago(2, monto="20.00"), _pago(3, monto="45.50")]

    dialogo, _ = _dialogo_detalle(qtbot, monkeypatch, pagos=pagos)

    assert [dialogo.tabla_pagos.item(f, COL_MONTO_USD).text() for f in range(3)] == ["$10.00", "$20.00", "$45.50"]


def test_detalle_sin_pagos_muestra_mensaje_en_una_sola_fila(qtbot, monkeypatch):
    dialogo, _ = _dialogo_detalle(qtbot, monkeypatch, pagos=[])

    assert dialogo.tabla_pagos.rowCount() == 1
    assert dialogo.tabla_pagos.item(0, 0).text() == "No hay pagos registrados"
    assert dialogo.tabla_pagos.columnSpan(0, 0) == 8


def test_detalle_sin_permiso_avisa_y_deja_la_tabla_vacia(qtbot, monkeypatch):
    avisos = []
    monkeypatch.setattr(cpp.MessageBox, "warning", lambda *a, **k: avisos.append(a[1]))

    dialogo, _ = _dialogo_detalle(qtbot, monkeypatch, error=PermisoDenegadoError("sin permiso"))

    assert avisos == ["Sin permiso"]
    assert dialogo.tabla_pagos.rowCount() == 0


def test_detalle_ante_un_error_inesperado_avisa_sin_romper(qtbot, monkeypatch):
    avisos = []
    monkeypatch.setattr(cpp.MessageBox, "warning", lambda *a, **k: avisos.append((a[1], a[2])))

    _dialogo_detalle(qtbot, monkeypatch, error=RuntimeError("se cayo la base"))

    assert avisos[0][0] == "Error"
    assert "se cayo la base" in avisos[0][1]


def test_detalle_con_compra_o_vencimiento_ausentes_no_revienta(qtbot, monkeypatch):
    cuenta = SimpleNamespace(id_cuenta=3, compra=None, saldo_pendiente=Decimal("0.00"), fecha_vencimiento=None)

    dialogo, _ = _dialogo_detalle(qtbot, monkeypatch, pagos=[], cuenta=cuenta)

    assert dialogo.windowTitle() == "Detalle de Cuenta por Pagar"


# -- Boton "Ver detalle de pagos" del panel -------------------------------------------------


@pytest.fixture()
def panel_cxp(qtbot, monkeypatch):
    # Sin el QTimer.singleShot(100, ...) del constructor: correria (ya sin el parche) contra la
    # Session mockeada en medio de otro test y pytest-qt lo reportaria como falla de ese test.
    monkeypatch.setattr(cpp.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(cpp.CuentasPorPagarPanel, "cargar_cuentas", lambda self: None)
    panel = cpp.CuentasPorPagarPanel(MagicMock(), SimpleNamespace(id_usuario=5))
    qtbot.addWidget(panel)
    return panel


def test_ver_detalle_pagos_abre_el_dialogo_con_la_cuenta_y_cierra_la_sesion(panel_cxp, monkeypatch):
    sesion = MagicMock()
    cuenta = _cuenta_detalle()
    sesion.get.return_value = cuenta
    panel_cxp.session_factory = lambda: sesion
    abiertos = []

    class DialogoFalso:
        def __init__(self, session, cuenta_, id_usuario, parent=None):
            abiertos.append((session, cuenta_, id_usuario))

        def exec(self):
            return 0

    monkeypatch.setattr(cpp, "DetalleCuentaPorPagarDialog", DialogoFalso)

    panel_cxp._ver_detalle_pagos(3)

    assert abiertos == [(sesion, cuenta, 5)]
    sesion.close.assert_called_once()


def test_ver_detalle_pagos_cuenta_inexistente_avisa_y_no_abre_dialogo(panel_cxp, monkeypatch):
    sesion = MagicMock()
    sesion.get.return_value = None
    panel_cxp.session_factory = lambda: sesion
    avisos = []
    monkeypatch.setattr(cpp.MessageBox, "warning", lambda *a, **k: avisos.append(a[1]))
    monkeypatch.setattr(cpp, "DetalleCuentaPorPagarDialog", lambda *a, **k: pytest.fail("no debe abrirse"))

    panel_cxp._ver_detalle_pagos(99)

    assert avisos == ["Cuenta no encontrada"]
    sesion.close.assert_called_once()
