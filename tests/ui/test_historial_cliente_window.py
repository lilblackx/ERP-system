"""historial_cliente_window.py no tenia ningun test de UI hasta ahora. Cobertura minima:
el guard anti-reentrancia de ver_detalle_factura() agregado en el hallazgo 3.3 (auditoria
2026-09-05) -- ver test_bancos_panel.py para el motivo completo."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import app.ui.historial_cliente_window as hcw


def _crear_ventana(qtbot, monkeypatch):
    # A diferencia de los paneles de listado, __init__ llama cargar_historial() de forma
    # SINCRONICA (no diferida via QTimer) -- hace falta mockear sus 3 dependencias para
    # que la construccion no dependa de que una sesion MagicMock se comporte como una real.
    monkeypatch.setattr(hcw, "obtener_historial_cliente", lambda *a, **k: [])
    monkeypatch.setattr(hcw, "obtener_saldo_total_pendiente", lambda *a, **k: Decimal("0.00"))
    monkeypatch.setattr(hcw.NotaCreditoService, "listar_notas_credito_cliente", staticmethod(lambda *a, **k: []))
    monkeypatch.setattr(hcw.MessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(hcw.MessageBox, "warning", lambda *a, **k: None)
    cliente = SimpleNamespace(nombre_razon_social="Cliente de Prueba")
    ventana = hcw.HistorialClienteWindow(MagicMock(), id_cliente=1, cliente=cliente, id_usuario=1)
    qtbot.addWidget(ventana)
    return ventana


def test_ver_detalle_factura_bloquea_reentrada_pero_no_queda_trabado(qtbot, monkeypatch):
    ventana = _crear_ventana(qtbot, monkeypatch)
    ventana._fila_seleccionada_id_factura = lambda: 1
    monkeypatch.setattr(hcw.VentaService, "obtener_factura", staticmethod(lambda *a, **k: {}))

    llamadas_sesion = []

    def session_factory():
        llamadas_sesion.append(1)
        return MagicMock()

    ventana.session_factory = session_factory

    dialogo_mock = MagicMock()

    def fake_exec():
        # Simula un segundo doble-click mientras el primero todavia esta abriendo el
        # detalle de la factura -- sin el guard, reentraria y abriria una segunda sesion.
        ventana.ver_detalle_factura()
        return 0

    dialogo_mock.exec.side_effect = fake_exec
    monkeypatch.setattr(hcw, "FacturaDetalleDialog", lambda *a, **k: dialogo_mock)

    ventana.ver_detalle_factura()

    assert len(llamadas_sesion) == 1
    assert ventana._abriendo_dialogo is False

    ventana.ver_detalle_factura()
    assert len(llamadas_sesion) == 2
