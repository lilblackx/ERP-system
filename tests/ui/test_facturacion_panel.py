"""facturacion_panel.py no tenia ningun test de UI hasta ahora. Cobertura minima: el
guard anti-reentrancia de ver_detalle_factura() agregado en el hallazgo 3.3 (auditoria
2026-09-05) -- ver test_bancos_panel.py para el motivo completo."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import app.ui.facturacion_panel as fp


def _crear_panel(qtbot, monkeypatch):
    # cargar_facturas() esta diferido via QTimer.singleShot en __init__ -- no corre
    # sincronicamente durante la construccion.
    monkeypatch.setattr(fp.MessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(fp.MessageBox, "warning", lambda *a, **k: None)
    panel = fp.FacturacionPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    return panel


def test_ver_detalle_factura_bloquea_reentrada_pero_no_queda_trabado(qtbot, monkeypatch):
    panel = _crear_panel(qtbot, monkeypatch)
    panel._fila_seleccionada_id = lambda: 1
    monkeypatch.setattr(fp.VentaService, "obtener_factura", staticmethod(lambda *a, **k: {}))

    llamadas_sesion = []

    def session_factory():
        llamadas_sesion.append(1)
        return MagicMock()

    panel.session_factory = session_factory

    dialogo_mock = MagicMock()

    def fake_exec():
        # Simula un segundo doble-click mientras el primero todavia esta abriendo el
        # detalle de la factura -- sin el guard, reentraria y abriria una segunda sesion.
        panel.ver_detalle_factura()
        return 0

    dialogo_mock.exec.side_effect = fake_exec
    monkeypatch.setattr(fp, "FacturaDetalleDialog", lambda *a, **k: dialogo_mock)

    panel.ver_detalle_factura()

    assert len(llamadas_sesion) == 1
    assert panel._abriendo_dialogo is False

    panel.ver_detalle_factura()
    assert len(llamadas_sesion) == 2
