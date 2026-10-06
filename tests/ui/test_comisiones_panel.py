"""comisiones_panel.py no tenia ningun test de UI hasta ahora. Cobertura minima: el guard
anti-reentrancia de ver_detalle_factura() agregado en el hallazgo 3.3 (auditoria
2026-09-05) -- ver test_bancos_panel.py para el motivo completo."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import app.ui.comisiones_panel as comp


def _crear_panel(qtbot, monkeypatch, gestion=False):
    # __init__ consulta UsuarioService.verificar_permiso sincronicamente (para decidir
    # modo_gestion) -- cargar_datos() en si esta diferido via QTimer.singleShot.
    monkeypatch.setattr(comp.UsuarioService, "verificar_permiso", staticmethod(lambda *a, **k: gestion))
    monkeypatch.setattr(comp.MessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(comp.MessageBox, "warning", lambda *a, **k: None)
    panel = comp.ComisionesPanel(MagicMock(), SimpleNamespace(id_usuario=1, id_vendedor_usuario=None))
    qtbot.addWidget(panel)
    return panel


def test_ver_detalle_factura_bloquea_reentrada_pero_no_queda_trabado(qtbot, monkeypatch):
    panel = _crear_panel(qtbot, monkeypatch)
    panel._fila_seleccionada_id_factura = lambda: 1
    monkeypatch.setattr(comp.VentaService, "obtener_factura", staticmethod(lambda *a, **k: {}))

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
    monkeypatch.setattr(comp, "FacturaDetalleDialog", lambda *a, **k: dialogo_mock)

    panel.ver_detalle_factura()

    assert len(llamadas_sesion) == 1
    assert panel._abriendo_dialogo is False

    panel.ver_detalle_factura()
    assert len(llamadas_sesion) == 2


# ── Pago con el filtro "Solo con porcentaje BCV" ────────────────────────────


def _comision(id_comision, monto, estado="liberada"):
    return SimpleNamespace(id_comision=id_comision, monto_comision=Decimal(monto), estado_pago=estado)


def test_pagar_comisiones_paga_solo_las_que_muestra_la_pantalla(qtbot, monkeypatch):
    """Con el filtro BCV activo comisiones_cargadas es un subconjunto de lo liberado del
    vendedor: el dialogo recibe esos ids y ese total, no todo lo liberado."""
    panel = _crear_panel(qtbot, monkeypatch, gestion=True)
    panel.id_vendedor_actual = 7
    panel.comisiones_cargadas = [
        _comision(10, "3.00"),
        _comision(11, "4.00"),
        _comision(12, "5.00", estado="pendiente"),  # no pagable
        _comision(13, "0.00"),  # sin monto
    ]
    capturado = {}

    class _DialogoFalso:
        pago_creado = None

        def __init__(self, session, id_usuario, id_vendedor, monto, nombre, parent=None, ids_comision=None):
            capturado.update(id_vendedor=id_vendedor, monto=monto, ids=ids_comision)

        def exec(self):
            return 0

    monkeypatch.setattr(comp, "PagarComisionesDialog", _DialogoFalso)

    panel.pagar_comisiones()

    assert capturado["id_vendedor"] == 7
    assert capturado["monto"] == Decimal("7.00")
    assert capturado["ids"] == [10, 11]


def _dialogo_pago(qtbot, monkeypatch, ids, monto):
    monkeypatch.setattr(comp.CajaService, "listar_cajas", staticmethod(lambda *a, **k: []))
    monkeypatch.setattr(comp.BancoService, "listar_cuentas", staticmethod(lambda *a, **k: []))
    dialogo = comp.PagarComisionesDialog(MagicMock(), 1, 7, monto, "Vendedor", ids_comision=ids)
    qtbot.addWidget(dialogo)
    dialogo._cajas_abiertas = [SimpleNamespace(id_caja=1, nombre_caja="Caja 1", fecha_apertura=1, fecha_cierre=None)]
    dialogo._toggle_origen()
    dialogo.origen_combo.setCurrentIndex(0)
    return dialogo


def test_dialogo_de_pago_envia_ids_y_monto_confirmado_al_servicio(qtbot, monkeypatch):
    dialogo = _dialogo_pago(qtbot, monkeypatch, ids=[10, 11], monto=Decimal("7.00"))
    llamada = {}
    monkeypatch.setattr(
        comp.PagoComisionService,
        "pagar_comisiones_vendedor",
        staticmethod(lambda *a, **k: llamada.update(k) or SimpleNamespace(id_pago_comision=1)),
    )
    monkeypatch.setattr(comp.MessageBox, "question", lambda *a, **k: comp.QMessageBox.StandardButton.Yes)

    dialogo._validar_y_aceptar()

    assert llamada["ids_comision"] == [10, 11]
    assert llamada["monto_esperado"] == Decimal("7.00")
    assert llamada["id_vendedor"] == 7
