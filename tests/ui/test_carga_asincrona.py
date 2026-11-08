"""CargaAsincronaMixin: los listados se piden en un hilo aparte y solo se pinta lo ultimo que se pidio."""

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QWidget

import app.ui.carga_asincrona as ca
from app.services.permisos import PermisoDenegadoError


class _WorkerFalso:
    """No lanza ningun hilo: registra con que se lo creo y deja que el test entregue la respuesta."""

    creados: list = []

    def __init__(self, session_factory, tarea, *args, **kwargs):
        self.tarea, self.args = tarea, args
        self.silencioso = False
        self.resultado, self.finished = MagicMock(), MagicMock()
        _WorkerFalso.creados.append(self)

    def start(self):
        self.iniciado = True

    def isFinished(self):
        return True

    def wait(self, _ms):
        return True


class _Panel(ca.CargaAsincronaMixin, QWidget):
    def __init__(self):
        super().__init__()
        self.session_factory = MagicMock()
        self.pintado = []


@pytest.fixture()
def panel(qtbot, monkeypatch):
    _WorkerFalso.creados = []
    monkeypatch.setattr(ca, "QueryWorker", _WorkerFalso)
    monkeypatch.setattr(ca.MessageBox, "warning", lambda *a, **k: panel_avisos.append(("warning", a[2])))
    monkeypatch.setattr(ca.MessageBox, "critical", lambda *a, **k: panel_avisos.append(("critical", a[2])))
    panel_avisos.clear()
    widget = _Panel()
    qtbot.addWidget(widget)
    return widget


panel_avisos: list = []


def _pedir(panel, **kwargs):
    panel.cargar_async(
        "lista",
        lambda s, **f: f,
        panel.pintado.append,
        texto_error="No se pudo cargar.",
        texto_sin_permiso="Sin permiso.",
        **kwargs,
    )
    return _WorkerFalso.creados[-1]


def test_la_carga_corre_en_un_hilo_y_pinta_al_llegar(panel):
    worker = _pedir(panel)

    assert worker.iniciado and worker.silencioso is False
    panel._recibir_carga({"id_carga": 1, "clave": "lista", "resultado": "datos"})
    assert panel.pintado == ["datos"]


def test_la_busqueda_mientras_se_escribe_no_enciende_la_barra_de_carga(panel):
    assert _pedir(panel, silencioso=True).silencioso is True


def test_una_respuesta_vieja_se_descarta(panel):
    _pedir(panel)
    _pedir(panel)

    panel._recibir_carga({"id_carga": 1, "clave": "lista", "resultado": "viejo"})
    panel._recibir_carga({"id_carga": 2, "clave": "lista", "resultado": "vigente"})

    assert panel.pintado == ["vigente"]


def test_las_claves_distintas_no_se_pisan(panel):
    otro = []
    _pedir(panel)
    panel.cargar_async("otra", lambda s: 1, otro.append, texto_error="x")

    panel._recibir_carga({"id_carga": 2, "clave": "otra", "resultado": "b"})
    panel._recibir_carga({"id_carga": 1, "clave": "lista", "resultado": "a"})

    assert panel.pintado == ["a"] and otro == ["b"]


def test_sincrono_pinta_en_el_acto_sin_hilo_e_invalida_lo_que_iba_en_vuelo(panel):
    _pedir(panel)  # en vuelo (id 1)
    panel.cargar_async("lista", lambda s, **f: "nuevo", panel.pintado.append, texto_error="x", sincrono=True)

    panel._recibir_carga({"id_carga": 1, "clave": "lista", "resultado": "viejo"})

    assert panel.pintado == ["nuevo"]
    assert len(_WorkerFalso.creados) == 1


def test_la_tarea_convierte_permiso_y_errores_en_datos():
    def sin_permiso(session, **f):
        raise PermisoDenegadoError("x", "ver")

    def falla(session, **f):
        raise RuntimeError("boom")

    assert ca._tarea_carga(None, 3, "k", sin_permiso, {}) == {"id_carga": 3, "clave": "k", "sin_permiso": True}
    assert ca._tarea_carga(None, 3, "k", falla, {}) == {"id_carga": 3, "clave": "k", "error": "boom"}


def test_sin_permiso_y_error_avisan_al_usuario(panel):
    _pedir(panel)

    panel._recibir_carga({"id_carga": 1, "clave": "lista", "sin_permiso": True})
    panel._recibir_carga({"id_carga": 1, "clave": "lista", "error": "boom"})

    assert panel_avisos[0] == ("warning", "Sin permiso.")
    assert panel_avisos[1][0] == "critical" and "boom" in panel_avisos[1][1]
    assert panel.pintado == []


def test_el_debounce_lanza_una_sola_busqueda_tras_varias_teclas(panel, qtbot):
    llamadas = []
    for _ in range(5):
        panel.buscar_con_pausa(lambda: llamadas.append(1), ms=30)

    qtbot.waitUntil(lambda: bool(llamadas), timeout=2000)
    qtbot.wait(80)

    assert llamadas == [1]


def test_al_terminar_se_llama_despues_de_pintar_y_el_refresco_es_silencioso(panel):
    orden = []
    panel.cargar_async(
        "lista", lambda s: "datos", orden.append, texto_error="x", al_terminar=lambda: orden.append("fin")
    )

    assert _WorkerFalso.creados[-1].silencioso is True  # un refresco automatico no enciende la barra de carga
    panel._recibir_carga({"id_carga": 1, "clave": "lista", "resultado": "datos"})

    assert orden == ["datos", "fin"]


def test_al_terminar_no_se_llama_si_la_respuesta_llega_tarde(panel):
    llamadas = []
    panel.cargar_async("lista", lambda s: 1, lambda r: None, texto_error="x", al_terminar=lambda: llamadas.append(1))
    _pedir(panel)  # el usuario pidio otra cosa antes de que llegara la respuesta del refresco

    panel._recibir_carga({"id_carga": 1, "clave": "lista", "resultado": "viejo"})

    assert llamadas == []
