from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import app.ui.notas_credito_proveedor_dialog as mod
from app.ui.notas_credito_proveedor_dialog import (
    AplicarNotaCreditoProveedorDialog,
    NotasCreditoProveedorDialog,
    ReembolsoNotaCreditoProveedorDialog,
)


def _nota(saldo="40.00"):
    return SimpleNamespace(
        id_nota_credito=3,
        id_proveedor=1,
        monto=Decimal("40.00"),
        saldo_disponible=Decimal(saldo),
        fecha_creacion=datetime(2026, 10, 1),
        proveedor=SimpleNamespace(nombre_razon_social="Proveedor Uno"),
        compra_origen=SimpleNamespace(numero_compra="OC-000009"),
        estado="disponible",
    )


def test_listado_muestra_notas_y_total_a_favor(qtbot, monkeypatch):
    monkeypatch.setattr(
        mod.NotaCreditoService,
        "listar_notas_credito_proveedor_disponibles",
        staticmethod(lambda *a, **k: [_nota("40.00"), _nota("10.00")]),
    )
    dialogo = NotasCreditoProveedorDialog(MagicMock(), id_usuario=1)
    qtbot.addWidget(dialogo)

    assert dialogo.tabla.rowCount() == 2
    assert dialogo.tabla.item(0, 2).text() == "OC-000009"
    assert dialogo.lbl_total.text() == "Total a favor: $50.00"
    assert dialogo.btn_aplicar.isEnabled()


def test_listado_vacio_deshabilita_acciones(qtbot, monkeypatch):
    monkeypatch.setattr(
        mod.NotaCreditoService, "listar_notas_credito_proveedor_disponibles", staticmethod(lambda *a, **k: [])
    )
    dialogo = NotasCreditoProveedorDialog(MagicMock(), id_usuario=1)
    qtbot.addWidget(dialogo)

    assert not dialogo.btn_aplicar.isEnabled()
    assert not dialogo.btn_reembolso.isEnabled()


def test_aplicar_tope_es_el_menor_entre_nota_y_deuda(qtbot, monkeypatch):
    cuenta = SimpleNamespace(
        id_cuenta=8, estado="pendiente", saldo_pendiente=Decimal("25.00"), compra=SimpleNamespace(numero_compra="OC-1")
    )
    monkeypatch.setattr(mod.PagoService, "listar_cuentas_por_pagar", staticmethod(lambda *a, **k: {"items": [cuenta]}))
    llamada = {}
    monkeypatch.setattr(
        mod.NotaCreditoService,
        "aplicar_nota_credito_proveedor",
        staticmethod(lambda session, **kwargs: llamada.update(kwargs)),
    )
    dialogo = AplicarNotaCreditoProveedorDialog(MagicMock(), id_usuario=1, nota=_nota("40.00"))
    qtbot.addWidget(dialogo)

    assert dialogo.monto_input.get_value() == Decimal("25.00")
    dialogo._validar_y_aceptar()
    assert llamada["id_cuenta_por_pagar"] == 8
    assert llamada["monto"] == Decimal("25.00")
    assert dialogo.aplicada


def test_reembolso_en_efectivo_oculta_referencia_y_usa_la_caja(qtbot, monkeypatch):
    caja = SimpleNamespace(id_caja=5, nombre_caja="Caja 1", fecha_apertura=datetime.now(), fecha_cierre=None)
    monkeypatch.setattr(mod.CajaService, "listar_cajas", staticmethod(lambda *a, **k: [caja]))
    monkeypatch.setattr(mod.BancoService, "listar_cuentas", staticmethod(lambda *a, **k: []))
    llamada = {}
    monkeypatch.setattr(
        mod.NotaCreditoService,
        "reembolsar_nota_credito_proveedor",
        staticmethod(lambda session, **kwargs: llamada.update(kwargs)),
    )
    dialogo = ReembolsoNotaCreditoProveedorDialog(MagicMock(), id_usuario=1, nota=_nota("40.00"))
    qtbot.addWidget(dialogo)

    assert dialogo.referencia_input.isHidden()
    dialogo._validar_y_aceptar()
    assert llamada["id_caja"] == 5
    assert llamada["id_cuenta_bancaria"] is None
    assert llamada["metodo_reembolso"] == "efectivo"
    assert llamada["monto"] == Decimal("40.00")


def test_reembolso_bancario_sin_cuentas_no_permite_registrar(qtbot, monkeypatch):
    monkeypatch.setattr(mod.CajaService, "listar_cajas", staticmethod(lambda *a, **k: []))
    monkeypatch.setattr(mod.BancoService, "listar_cuentas", staticmethod(lambda *a, **k: []))
    dialogo = ReembolsoNotaCreditoProveedorDialog(MagicMock(), id_usuario=1, nota=_nota())
    qtbot.addWidget(dialogo)

    dialogo.metodo_combo.setCurrentIndex(dialogo.metodo_combo.findData("transferencia"))

    assert not dialogo.btn_registrar.isEnabled()
    assert not dialogo.referencia_input.isHidden()
