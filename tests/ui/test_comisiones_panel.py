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
    # El QTimer.singleShot(100, cargar_datos) del constructor correria contra la Session mockeada
    # en medio de otro test (de cualquier archivo) y pytest-qt lo reportaria como falla suya.
    monkeypatch.setattr(comp.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
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


# ── Filtros "Solo con porcentaje BCV" / "Solo en $" ──────────────────────────


def _panel_con_servicio_espia(qtbot, monkeypatch, gestion):
    """Panel en el modo pedido con ComisionService reemplazado por un espia que registra los
    flags BCV con que se lo llama y devuelve una comision distinta segun el filtro."""
    panel = _crear_panel(qtbot, monkeypatch, gestion=gestion)
    panel.id_vendedor_actual = 7
    llamadas = []

    def espia(*args, solo_con_porcentaje_bcv=False, solo_sin_porcentaje_bcv=False, **kwargs):
        llamadas.append((solo_con_porcentaje_bcv, solo_sin_porcentaje_bcv))
        return []

    monkeypatch.setattr(comp.ComisionService, "listar_comisiones_vendedor", staticmethod(espia))
    monkeypatch.setattr(comp.ComisionService, "listar_mis_comisiones", staticmethod(espia))
    return panel, llamadas


def test_marcar_solo_en_dolares_recarga_con_el_filtro_sin_bcv(qtbot, monkeypatch):
    panel, llamadas = _panel_con_servicio_espia(qtbot, monkeypatch, gestion=True)

    panel.chk_sin_porcentaje_bcv.setChecked(True)

    assert llamadas == [(False, True)]
    assert panel.solo_sin_porcentaje_bcv is True
    assert panel.solo_porcentaje_bcv is False


def test_marcar_solo_con_porcentaje_bcv_recarga_con_el_filtro_con_bcv(qtbot, monkeypatch):
    panel, llamadas = _panel_con_servicio_espia(qtbot, monkeypatch, gestion=True)

    panel.chk_porcentaje_bcv.setChecked(True)

    assert llamadas == [(True, False)]


def test_los_dos_filtros_bcv_son_mutuamente_excluyentes(qtbot, monkeypatch):
    panel, llamadas = _panel_con_servicio_espia(qtbot, monkeypatch, gestion=True)

    panel.chk_porcentaje_bcv.setChecked(True)
    panel.chk_sin_porcentaje_bcv.setChecked(True)

    assert panel.chk_sin_porcentaje_bcv.isChecked()
    assert not panel.chk_porcentaje_bcv.isChecked()
    assert llamadas[-1] == (False, True)

    panel.chk_porcentaje_bcv.setChecked(True)

    assert panel.chk_porcentaje_bcv.isChecked()
    assert not panel.chk_sin_porcentaje_bcv.isChecked()
    assert llamadas[-1] == (True, False)


def test_desmarcar_el_filtro_vuelve_a_pedir_todas_las_comisiones(qtbot, monkeypatch):
    panel, llamadas = _panel_con_servicio_espia(qtbot, monkeypatch, gestion=True)
    panel.chk_sin_porcentaje_bcv.setChecked(True)

    panel.chk_sin_porcentaje_bcv.setChecked(False)

    assert llamadas == [(False, True), (False, False)]


def test_en_mis_comisiones_el_filtro_en_dolares_usa_listar_mis_comisiones(qtbot, monkeypatch):
    panel, llamadas = _panel_con_servicio_espia(qtbot, monkeypatch, gestion=False)

    panel.chk_sin_porcentaje_bcv.setChecked(True)

    assert llamadas == [(False, True)]


def test_exportar_indica_el_filtro_activo(qtbot, monkeypatch):
    panel, _ = _panel_con_servicio_espia(qtbot, monkeypatch, gestion=True)
    panel.usuario.nombre_usuario = "admin"
    panel.vendedor_combo.addItem("Vendedor Uno", 7)

    assert "Filtro" not in panel._filtros_para_exportar()

    panel.chk_sin_porcentaje_bcv.setChecked(True)
    assert panel._filtros_para_exportar()["Filtro"] == "Solo en $"

    panel.chk_porcentaje_bcv.setChecked(True)
    assert panel._filtros_para_exportar()["Filtro"] == "Solo con porcentaje BCV"
