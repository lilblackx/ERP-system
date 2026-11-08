"""Cada estacion factura de forma independiente: la caja que abre es la suya, y las abiertas por otras
estaciones no cuentan para el gate de Facturacion ni para cobrar en efectivo."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import app.ui.facturacion_panel as fp
from app.ui.pago_linea_dialog import PagoLineaDialog
from app.utils.caja_local import cajas_de_esta_estacion, guardar_caja_local, obtener_caja_local


def _caja(id_caja, abierta=True):
    return SimpleNamespace(
        id_caja=id_caja,
        nombre_caja=f"Caja {id_caja}",
        fecha_apertura=datetime(2026, 1, 1),
        fecha_cierre=None if abierta else datetime(2026, 1, 2),
    )


def _session_con_tasa():
    tasa = SimpleNamespace(
        id_tasa=1, tasa_dolar_bcv=Decimal("36.50"), tasa_dolar_paralelo=None, tasa_cop=Decimal("4000.00")
    )
    session = MagicMock()
    session.query.return_value.order_by.return_value.first.return_value = tasa
    return session


def _panel(qtbot, monkeypatch):
    monkeypatch.setattr(fp.MessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(fp.MessageBox, "warning", lambda *a, **k: None)
    panel = fp.FacturacionPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    return panel


def test_una_estacion_sin_caja_propia_no_tiene_ninguna_aunque_otras_esten_abiertas():
    assert obtener_caja_local() is None
    assert cajas_de_esta_estacion([_caja(1), _caja(2)]) == []


def test_la_estacion_solo_ve_su_caja():
    guardar_caja_local(2)

    assert [c.id_caja for c in cajas_de_esta_estacion([_caja(1), _caja(2), _caja(3)])] == [2]


def test_si_el_turno_de_la_caja_de_la_estacion_se_cerro_no_queda_ninguna():
    guardar_caja_local(2)

    assert cajas_de_esta_estacion([_caja(1)]) == []


def test_el_gate_pide_abrir_caja_aunque_otra_estacion_ya_tenga_una_abierta(qtbot, monkeypatch):
    panel = _panel(qtbot, monkeypatch)
    abiertos = []

    class _Dialogo:
        caja_abierta = _caja(2)

        def __init__(self, session, parent=None):
            abiertos.append(1)

        def exec(self):
            guardar_caja_local(2)  # lo que hace CajaAperturaDialog al abrir
            return fp.QDialog.DialogCode.Accepted

    monkeypatch.setattr(fp, "CajaAperturaDialog", _Dialogo)
    monkeypatch.setattr(
        fp.CajaService,
        "listar_cajas",
        staticmethod(lambda *a, **k: [_caja(1), _caja(2)]),
    )

    # Antes de abrir la suya, la estacion no tiene caja pese a que la 1 y la 2 estan abiertas en la BD.
    guardar_caja_local(None)
    assert panel._cajas_con_turno_abierto() == []

    assert panel._verificar_caja_abierta(ofrecer_apertura=True) is True
    assert abiertos == [1]
    assert [c.id_caja for c in panel._cajas_con_turno_abierto()] == [2]


def test_el_gate_no_vuelve_a_pedir_apertura_si_la_estacion_ya_tiene_su_caja(qtbot, monkeypatch):
    panel = _panel(qtbot, monkeypatch)
    guardar_caja_local(1)
    monkeypatch.setattr(fp.CajaService, "listar_cajas", staticmethod(lambda *a, **k: [_caja(1), _caja(2)]))
    monkeypatch.setattr(fp, "CajaAperturaDialog", MagicMock(side_effect=AssertionError("no debe abrirse")))

    assert panel._verificar_caja_abierta(ofrecer_apertura=True) is True


def test_el_pago_en_efectivo_de_facturacion_solo_ofrece_la_caja_de_la_estacion(qtbot):
    guardar_caja_local(2)
    with (
        patch("app.ui.pago_linea_dialog.CajaService.listar_cajas", return_value=[_caja(1), _caja(2)]),
        patch("app.ui.pago_linea_dialog.BancoService.listar_cuentas", return_value=[]),
    ):
        facturacion = PagoLineaDialog(_session_con_tasa(), id_usuario=1, solo_caja_estacion=True)
        general = PagoLineaDialog(_session_con_tasa(), id_usuario=1)
    qtbot.addWidget(facturacion)
    qtbot.addWidget(general)

    assert [c.id_caja for c in facturacion._cajas_abiertas] == [2]
    assert [c.id_caja for c in general._cajas_abiertas] == [1, 2]
