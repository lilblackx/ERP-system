"""ComprasView (app/ui/compras.py) no tenia ningun test de UI hasta ahora. Cobertura
minima: el guard anti-reentrancia de _abrir_detalle_oc() (compartido por el doble-click
en la tabla y el boton "ver detalle") agregado en el hallazgo 3.3 (auditoria 2026-09-05)
-- ver test_bancos_panel.py para el motivo completo. No confundir con test_compras_ui.py,
que cubre sub-dialogos (OC/enmienda/recepcion/devolucion), no esta clase contenedora."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import app.ui.compras as compras_mod


def _crear_panel(qtbot, monkeypatch):
    # _cargar_tab_actual() esta diferido via QTimer.singleShot en __init__, y _setup_ui()
    # no hace ninguna consulta sincronica -- no hace falta mockear ningun servicio.
    monkeypatch.setattr(compras_mod.MessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(compras_mod.MessageBox, "warning", lambda *a, **k: None)
    panel = compras_mod.ComprasView(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    return panel


def test_ver_detalle_oc_bloquea_reentrada_pero_no_queda_trabado(qtbot, monkeypatch):
    panel = _crear_panel(qtbot, monkeypatch)
    panel._fila_seleccionada_id = lambda tabla: 1
    monkeypatch.setattr(compras_mod.CompraOCService, "obtener_oc", staticmethod(lambda *a, **k: {}))

    llamadas_sesion = []

    def session_factory():
        llamadas_sesion.append(1)
        return MagicMock()

    panel.session_factory = session_factory

    dialogo_mock = MagicMock()

    def fake_exec():
        # Simula un segundo doble-click mientras el primero todavia esta abriendo el
        # detalle de la OC -- sin el guard, reentraria y abriria una segunda sesion.
        panel.ver_detalle_oc()
        return 0

    dialogo_mock.exec.side_effect = fake_exec
    monkeypatch.setattr(compras_mod, "OrdenCompraDetalleDialog", lambda *a, **k: dialogo_mock)

    panel.ver_detalle_oc()

    assert len(llamadas_sesion) == 1
    assert panel._abriendo_dialogo is False

    panel.ver_detalle_oc()
    assert len(llamadas_sesion) == 2
