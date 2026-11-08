"""Dialogos de cobro a clientes (pago de una cuenta y abono general, CxC y CxC BCV): tasa del dia, una sola fuente
para el monto y cuentas de origen segun la moneda del pago.

  * Efectivo: sin tasa ni bloque de Bs.
  * Zelle/Binance (dolares): se escribe el monto en $, no hay bloque de Bs y solo se ofrecen cuentas en USD.
  * Transferencia/punto de venta (bolivares): se escribe el monto en Bs, el $ sale de la tasa y solo se ofrecen
    cuentas en VES. Con la tasa COP el bloque habla de pesos y solo se ofrecen cuentas en COP.
"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.ui.cuentas_por_cobrar_bcv_panel as bcv
import app.ui.cuentas_por_cobrar_panel as cxc

TASA = 871.36
TASA_COP = 4000.0


def _cuenta_bancaria(id_cuenta, moneda, banco):
    return SimpleNamespace(
        id_cuenta=id_cuenta,
        numero_cuenta=f"0102000000{id_cuenta:04d}",
        moneda=moneda,
        banco=SimpleNamespace(nombre_banco=banco),
    )


CUENTAS = [
    _cuenta_bancaria(1, "VES", "Bancamiga"),
    _cuenta_bancaria(2, "USD", "Bank of America"),
    _cuenta_bancaria(3, "COP", "Bancolombia"),
]


def _cargar_origenes(self):
    self._cajas_abiertas = []
    self._cuentas_activas = list(CUENTAS)


def _cargar_tasas(self):
    self.tasa_combo.blockSignals(True)
    self.tasa_combo.clear()
    self.tasa_combo.addItem("-- Seleccionar --")
    self.tasa_combo.addItem(f"BCV: {TASA:,.2f}", (7, TASA))
    self.tasa_combo.addItem(f"COP: {TASA_COP:,.2f}", (7, TASA_COP))
    self.tasa_combo.blockSignals(False)


def _crear_bcv(sesion, cliente):
    return bcv.AbonoGeneralBCVDialog(lambda: sesion, cliente, 1, TASA)


def _crear_cxc(sesion, cliente):
    return cxc.AbonoGeneralDialog(sesion, cliente, 1, TASA)


@pytest.fixture(params=[(bcv.AbonoGeneralBCVDialog, _crear_bcv), (cxc.AbonoGeneralDialog, _crear_cxc)])
def dialogo(request, qtbot, monkeypatch):
    clase, crear = request.param
    monkeypatch.setattr(clase, "_cargar_origenes", _cargar_origenes)
    monkeypatch.setattr(clase, "_cargar_tasas", _cargar_tasas)
    sesion = MagicMock()
    sesion.query.return_value.join.return_value.filter.return_value.first.return_value = None
    dlg = crear(sesion, SimpleNamespace(id_cliente=1, nombre_razon_social="Cliente Demo"))
    qtbot.addWidget(dlg)
    return dlg


def _elegir_metodo(dlg, valor):
    dlg.metodo_combo.setCurrentIndex(dlg.metodo_combo.findData(valor))


def _elegir_tasa_cop(dlg):
    indice = next(i for i in range(dlg.tasa_combo.count()) if dlg.tasa_combo.itemText(i).startswith("COP"))
    dlg.tasa_combo.setCurrentIndex(indice)


def _editar(campo, valor):
    """Lo que hace el usuario al escribir: set_value() solo refleja el valor; valueChanged (que dispara el
    recalculo del otro campo) se emite unicamente cuando se edita a mano."""
    campo.set_value(valor)
    campo.valueChanged.emit(campo.get_value())


def _con_deuda(dlg, monto="2708.99"):
    dlg.monto_input.set_value(Decimal(monto))


def _origenes(dlg) -> list[int]:
    """Ids de las cuentas bancarias que ofrece el combo de origen."""
    return [dlg.origen_combo.itemData(i)[1] for i in range(dlg.origen_combo.count()) if dlg.origen_combo.itemData(i)]


# -- Tasa ---------------------------------------------------------------------------------------------------------


def test_abre_en_efectivo_con_la_tasa_deshabilitada(dialogo):
    assert dialogo.metodo_combo.currentData() == "efectivo"
    assert not dialogo.tasa_input.isEnabled()


def test_al_pasar_a_transferencia_la_tasa_se_puede_modificar(dialogo):
    _elegir_metodo(dialogo, "transferencia")

    assert dialogo.tasa_input.isEnabled()
    assert dialogo.tasa_input.get_value() == Decimal(str(TASA))


def test_ida_y_vuelta_por_efectivo_recupera_la_tasa(dialogo):
    _elegir_metodo(dialogo, "transferencia")
    _elegir_metodo(dialogo, "efectivo")
    _elegir_metodo(dialogo, "zelle")

    assert dialogo.tasa_input.isEnabled()
    assert dialogo.tasa_input.get_value() == Decimal(str(TASA))


def test_la_tasa_nunca_muestra_el_0_01_del_piso_al_pasar_por_efectivo(dialogo):
    _elegir_metodo(dialogo, "transferencia")
    _elegir_metodo(dialogo, "efectivo")

    assert dialogo.tasa_input.get_value() in (None, Decimal("0"))
    assert dialogo.tasa_input.text() == ""


# -- Cuentas de origen segun la moneda ----------------------------------------------------------------------------


@pytest.mark.parametrize("metodo", ["zelle", "binance"])
def test_en_dolares_solo_se_ofrecen_cuentas_en_usd(dialogo, metodo):
    _elegir_metodo(dialogo, metodo)

    assert _origenes(dialogo) == [2]


@pytest.mark.parametrize("metodo", ["transferencia", "punto_de_venta"])
def test_en_bolivares_solo_se_ofrecen_cuentas_en_ves(dialogo, metodo):
    _elegir_metodo(dialogo, metodo)

    assert _origenes(dialogo) == [1]


def test_con_la_tasa_cop_solo_se_ofrecen_cuentas_en_pesos(dialogo):
    _elegir_metodo(dialogo, "transferencia")
    _elegir_tasa_cop(dialogo)

    assert _origenes(dialogo) == [3]
    assert dialogo.lbl_bolivares.text() == "Monto (COP)"
    assert dialogo.lbl_tasa_campo.text() == "Tasa del día (COP/USD)"


def test_al_volver_a_la_tasa_bcv_vuelven_las_cuentas_en_bolivares(dialogo):
    _elegir_metodo(dialogo, "transferencia")
    _elegir_tasa_cop(dialogo)
    dialogo.tasa_combo.setCurrentIndex(1)

    assert _origenes(dialogo) == [1]
    assert dialogo.lbl_bolivares.text() == "Monto (Bs)"


def test_sin_cuentas_en_la_moneda_del_pago_avisa_y_no_deja_elegir(dialogo, monkeypatch):
    dialogo._cuentas_activas = [c for c in CUENTAS if c.moneda == "VES"]

    _elegir_metodo(dialogo, "zelle")

    assert _origenes(dialogo) == []
    assert "dólares" in dialogo.origen_combo.currentText()
    assert not dialogo.origen_combo.isEnabled()


# -- Metodos en dolares (Zelle/Binance): el monto en $ se escribe, no hay Bs ----------------------------------------


@pytest.mark.parametrize("metodo", ["zelle", "binance"])
def test_en_dolares_el_monto_usd_es_editable_conserva_la_deuda_y_no_hay_bloque_de_bs(dialogo, metodo):
    _con_deuda(dialogo)

    _elegir_metodo(dialogo, metodo)

    assert not dialogo.monto_input.isReadOnly()
    assert dialogo.monto_input.get_value() == Decimal("2708.99")
    assert dialogo.campos_bolivares_widget.isHidden()


def test_en_dolares_escribir_el_monto_usd_no_se_altera_solo(dialogo):
    _elegir_metodo(dialogo, "zelle")

    _editar(dialogo.monto_input, Decimal("100.00"))

    assert dialogo.monto_input.get_value() == Decimal("100.00")


# -- Metodos en bolivares: se escribe el monto en Bs y el $ sale de la tasa -----------------------------------------


def test_en_bolivares_se_escriben_los_bs_y_el_monto_usd_sale_de_la_tasa(dialogo):
    _con_deuda(dialogo)
    _elegir_metodo(dialogo, "transferencia")

    assert dialogo.monto_input.isReadOnly()
    assert not dialogo.bolivares_input.isReadOnly()
    assert not dialogo.campos_bolivares_widget.isHidden()
    assert dialogo.lbl_bolivares.text() == "Monto (Bs)"

    _editar(dialogo.bolivares_input, Decimal("87136.00"))

    assert dialogo.monto_input.get_value() == Decimal("100.00")


def test_pasar_de_zelle_a_transferencia_no_pierde_el_monto(dialogo):
    _con_deuda(dialogo)
    _elegir_metodo(dialogo, "zelle")
    _elegir_metodo(dialogo, "transferencia")

    assert dialogo.monto_input.get_value() == Decimal("2708.99")
    assert dialogo.bolivares_input.get_value() > 0


def test_en_bolivares_sin_bs_el_monto_usd_queda_vacio_en_vez_de_0_01(dialogo):
    _elegir_metodo(dialogo, "transferencia")

    _editar(dialogo.bolivares_input, None)

    assert dialogo.monto_input.get_value() in (None, Decimal("0"))


def test_con_la_tasa_cop_el_monto_usd_sale_de_dividir_los_pesos_entre_la_tasa(dialogo):
    _elegir_metodo(dialogo, "transferencia")
    _elegir_tasa_cop(dialogo)

    _editar(dialogo.bolivares_input, Decimal("400000.00"))

    assert dialogo.monto_input.get_value() == Decimal("100.00")


# -- Pago de una sola cuenta (mismo comportamiento) -------------------------------------------------------------


def _cuenta(saldo="500.00"):
    cuenta = MagicMock()
    cuenta.saldo_pendiente = Decimal(saldo)
    cuenta.porcentaje = None
    cuenta.saldo_favor = Decimal("0.00")
    cuenta.factura.total_venta = Decimal(saldo)
    cuenta.factura.numero_factura = "FV-1"
    cuenta.factura.cliente.nombre_razon_social = "Cliente Demo"
    return cuenta


@pytest.fixture(params=["cxc", "bcv"])
def pago_unico(request, qtbot, monkeypatch):
    clase = cxc.PagoCobroDialog if request.param == "cxc" else bcv.PagoCobroBCVDialog
    monkeypatch.setattr(clase, "_cargar_origenes", _cargar_origenes)
    monkeypatch.setattr(clase, "_cargar_tasas", _cargar_tasas)
    sesion = MagicMock()
    if request.param == "cxc":
        dlg = clase(sesion, 1, _cuenta(), TASA)
    else:
        dlg = clase(lambda: sesion, 1, _cuenta(), TASA)
    qtbot.addWidget(dlg)
    return dlg


def test_pago_unico_en_zelle_el_monto_usd_se_escribe_y_solo_hay_cuentas_usd(pago_unico):
    pago_unico.monto_input.set_value(Decimal("500.00"))

    _elegir_metodo(pago_unico, "zelle")

    assert not pago_unico.monto_input.isReadOnly()
    assert pago_unico.monto_input.get_value() == Decimal("500.00")
    assert pago_unico.campos_bolivares_widget.isHidden()
    assert _origenes(pago_unico) == [2]


def test_pago_unico_en_transferencia_el_monto_usd_es_derivado_y_solo_hay_cuentas_ves(pago_unico):
    _elegir_metodo(pago_unico, "transferencia")

    assert pago_unico.monto_input.isReadOnly()
    assert not pago_unico.bolivares_input.isReadOnly()
    assert _origenes(pago_unico) == [1]
