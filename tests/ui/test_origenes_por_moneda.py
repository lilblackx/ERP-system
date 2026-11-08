"""Facturacion (PagoLineaDialog), pago a proveedores y vuelto: la cuenta bancaria de origen debe estar en la moneda
del pago (Zelle/Binance -> USD, resto de metodos bancarios -> VES, pagos en pesos -> COP)."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.ui.pago_linea_dialog import PagoLineaDialog


def _cuenta(id_cuenta, moneda):
    return SimpleNamespace(
        id_cuenta=id_cuenta,
        numero_cuenta=f"0102000000{id_cuenta:04d}",
        moneda=moneda,
        estado_cuenta="ACTIVO",
        banco=SimpleNamespace(nombre_banco=f"Banco {moneda}"),
    )


CUENTAS = [_cuenta(1, "VES"), _cuenta(2, "USD"), _cuenta(3, "COP")]


def _session_con_tasa():
    tasa = SimpleNamespace(
        id_tasa=1, tasa_dolar_bcv=Decimal("36.50"), tasa_dolar_paralelo=None, tasa_cop=Decimal("4000.00")
    )
    session = MagicMock()
    session.query.return_value.order_by.return_value.first.return_value = tasa
    return session


def _dialogo_de_pago(qtbot, cuentas=None):
    with (
        patch("app.ui.pago_linea_dialog.CajaService.listar_cajas", return_value=[]),
        patch("app.ui.pago_linea_dialog.BancoService.listar_cuentas", return_value=list(cuentas or CUENTAS)),
    ):
        dialogo = PagoLineaDialog(_session_con_tasa(), id_usuario=1)
    qtbot.addWidget(dialogo)
    return dialogo


def _origenes(dialogo):
    combo = dialogo.origen_combo
    return [combo.itemData(i)[1] for i in range(combo.count()) if combo.itemData(i)]


def _elegir(combo, valor):
    combo.setCurrentIndex(combo.findData(valor))


def test_facturacion_zelle_y_binance_solo_ofrecen_cuentas_en_dolares(qtbot):
    dialogo = _dialogo_de_pago(qtbot)

    for metodo in ("zelle", "binance"):
        _elegir(dialogo.metodo_combo, metodo)
        assert _origenes(dialogo) == [2], metodo


def test_facturacion_transferencia_y_punto_de_venta_solo_ofrecen_cuentas_en_bolivares(qtbot):
    dialogo = _dialogo_de_pago(qtbot)

    for metodo in ("transferencia", "punto_de_venta"):
        _elegir(dialogo.metodo_combo, metodo)
        assert _origenes(dialogo) == [1], metodo


def test_facturacion_un_pago_en_pesos_solo_ofrece_cuentas_en_pesos(qtbot):
    dialogo = _dialogo_de_pago(qtbot)
    _elegir(dialogo.metodo_combo, "zelle")  # un metodo que deja elegir la moneda

    _elegir(dialogo.moneda_combo, "COP")

    assert _origenes(dialogo) == [3]


def test_facturacion_sin_cuentas_en_la_moneda_avisa_cual_falta(qtbot):
    dialogo = _dialogo_de_pago(qtbot, cuentas=[_cuenta(1, "VES")])

    _elegir(dialogo.metodo_combo, "zelle")

    assert _origenes(dialogo) == []
    assert "dólares" in dialogo.origen_combo.currentText()
    assert not dialogo.origen_combo.isEnabled()


def test_facturacion_el_efectivo_no_usa_cuentas_bancarias(qtbot):
    dialogo = _dialogo_de_pago(qtbot)

    _elegir(dialogo.metodo_combo, "efectivo")

    assert _origenes(dialogo) == []
    assert "cajas" in dialogo.origen_combo.currentText().lower()


# -- Pago a proveedores ---------------------------------------------------------------------------------------


def test_pago_a_proveedor_filtra_las_cuentas_por_la_moneda_del_metodo(qtbot, monkeypatch):
    import app.ui.cuentas_por_pagar_panel as cxp

    monkeypatch.setattr(cxp.PagoProveedorDialog, "_cargar_tasas", lambda self: None)
    monkeypatch.setattr(cxp.CajaService, "listar_cajas", staticmethod(lambda *a, **k: []))
    monkeypatch.setattr(cxp.BancoService, "listar_cuentas", staticmethod(lambda *a, **k: list(CUENTAS)))
    cuenta = SimpleNamespace(
        id_cuenta=1,
        saldo_pendiente=Decimal("100.00"),
        compra=SimpleNamespace(numero_compra="C-1", proveedor=SimpleNamespace(nombre_razon_social="Prov")),
    )
    dialogo = cxp.PagoProveedorDialog(MagicMock(), 1, cuenta)
    qtbot.addWidget(dialogo)

    _elegir(dialogo.metodo_combo, "zelle")
    en_zelle = _origenes(dialogo)
    _elegir(dialogo.metodo_combo, "transferencia")
    en_transferencia = _origenes(dialogo)

    assert en_zelle == [2]
    assert en_transferencia == [1]
