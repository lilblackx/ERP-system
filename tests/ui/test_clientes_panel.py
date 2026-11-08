"""clientes_panel.py no tenia ningun test de UI hasta ahora. Cobertura minima: el guard
anti-reentrancia de ver_historial_cliente() agregado en el hallazgo 3.3 (auditoria
2026-09-05) -- ver test_bancos_panel.py para el motivo completo."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import app.ui.clientes_panel as cp


def _crear_panel(qtbot, monkeypatch):
    # cargar_clientes() esta diferido via QTimer.singleShot en __init__ -- no corre
    # sincronicamente durante la construccion, asi que no hace falta mockear el listado.
    monkeypatch.setattr(cp.MessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(cp.MessageBox, "warning", lambda *a, **k: None)
    panel = cp.ClientesPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    return panel


def test_ver_historial_cliente_bloquea_reentrada_pero_no_queda_trabado(qtbot, monkeypatch):
    panel = _crear_panel(qtbot, monkeypatch)
    panel._fila_seleccionada_id = lambda: 1

    llamadas_sesion = []

    def session_factory():
        llamadas_sesion.append(1)
        return MagicMock()

    panel.session_factory = session_factory

    dialogo_mock = MagicMock()

    def fake_exec():
        # Simula un segundo doble-click mientras el primero todavia esta abriendo la
        # ventana de historial -- sin el guard, reentraria y abriria una segunda sesion.
        panel.ver_historial_cliente()
        return 0

    dialogo_mock.exec.side_effect = fake_exec
    monkeypatch.setattr(cp, "HistorialClienteWindow", lambda *a, **k: dialogo_mock)

    panel.ver_historial_cliente()

    assert len(llamadas_sesion) == 1
    assert panel._abriendo_dialogo is False

    panel.ver_historial_cliente()
    assert len(llamadas_sesion) == 2


# ── Busqueda en un hilo aparte, sin congelar la ventana ───────────────────────────────────────────


class _WorkerFalso:
    """Reemplaza a QueryWorker: registra con que se lo creo y no lanza ningun hilo."""

    creados: list = []

    def __init__(self, session_factory, tarea, *args, **kwargs):
        self.tarea, self.args, self.kwargs = tarea, args, kwargs
        self.silencioso = False
        self.resultado, self.error, self.finished = MagicMock(), MagicMock(), MagicMock()
        _WorkerFalso.creados.append(self)

    def start(self):
        self.iniciado = True

    def wait(self, _ms):
        return True


def _panel_con_worker_falso(qtbot, monkeypatch):
    _WorkerFalso.creados = []
    monkeypatch.setattr(cp, "QueryWorker", _WorkerFalso)
    monkeypatch.setattr(cp.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    return _crear_panel(qtbot, monkeypatch)


def test_cargar_clientes_no_consulta_en_el_hilo_de_la_ventana(qtbot, monkeypatch):
    panel = _panel_con_worker_falso(qtbot, monkeypatch)
    panel.buscar_input.setText("  Gonzalez ")

    panel.cargar_clientes()

    worker = _WorkerFalso.creados[-1]
    assert worker.iniciado
    assert worker.tarea is cp._tarea_cargar_clientes
    assert worker.kwargs["texto_busqueda"] == "Gonzalez"
    assert worker.kwargs["pagina"] == 1 and worker.kwargs["por_pagina"] == cp.POR_PAGINA
    assert worker.silencioso is False


def test_la_busqueda_mientras_se_escribe_no_enciende_la_barra_de_carga(qtbot, monkeypatch):
    panel = _panel_con_worker_falso(qtbot, monkeypatch)

    panel._buscar_desde_inicio()

    assert _WorkerFalso.creados[-1].silencioso is True


def test_una_respuesta_vieja_se_descarta(qtbot, monkeypatch):
    panel = _panel_con_worker_falso(qtbot, monkeypatch)
    pintados = []
    panel._poblar_tabla = pintados.append
    panel.cargar_clientes()  # pide el 1
    panel.cargar_clientes()  # el usuario siguio escribiendo: pide el 2

    panel._on_clientes_cargados({"id_carga": 1, "resultado": "viejo"})
    panel._on_clientes_cargados({"id_carga": 2, "resultado": "vigente"})

    assert pintados == ["vigente"]


def test_sin_permiso_avisa_y_no_pinta(qtbot, monkeypatch):
    panel = _panel_con_worker_falso(qtbot, monkeypatch)
    avisos, pintados = [], []
    monkeypatch.setattr(cp.MessageBox, "warning", lambda *a, **k: avisos.append(a[1]))
    panel._poblar_tabla = pintados.append
    panel.cargar_clientes()

    panel._on_clientes_cargados({"id_carga": panel._id_carga, "sin_permiso": True})

    assert avisos == ["Sin permiso"] and pintados == []


def test_la_tarea_devuelve_el_listado_con_su_id_de_carga(monkeypatch):
    monkeypatch.setattr(cp, "list_clientes", lambda session, **filtros: {"items": [], "filtros": filtros})

    respuesta = cp._tarea_cargar_clientes(MagicMock(), 7, texto_busqueda="x")

    assert respuesta == {"id_carga": 7, "resultado": {"items": [], "filtros": {"texto_busqueda": "x"}}}


def test_la_tarea_convierte_la_falta_de_permiso_en_un_resultado(monkeypatch):
    def _sin_permiso(session, **filtros):
        raise cp.PermisoDenegadoError("clientes", "ver")

    monkeypatch.setattr(cp, "list_clientes", _sin_permiso)

    assert cp._tarea_cargar_clientes(MagicMock(), 3) == {"id_carga": 3, "sin_permiso": True}
