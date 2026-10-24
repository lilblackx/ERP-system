"""La barra de carga (app/ui/carga.py) tiene que apagarse despues de abrir CADA modulo.

La cuenta de actividad es global: si un solo QueryWorker deja la cuenta en 1, la barra queda encendida "para
siempre" en todos los modulos. Aqui se arma la MainWindow real contra la base de pruebas, se abre cada modulo
(despacio y a toda prisa) y, cuando ya no queda ningun hilo en marcha, la cuenta tiene que ser 0."""

import time

import pytest

from app import config
from app.db.session import SessionLocal
from app.services import cifrado_servidor
from app.ui import message_box
from app.ui.carga import GestorActividad
from app.ui.main_window import MODULOS_CONFIG, MainWindow
from app.ui.workers import QueryWorker
from tests.factories import crear_usuario_admin

ESPERA_MAX_MS = 30_000
REPOSO_SEG = 0.5


@pytest.fixture(autouse=True)
def _sin_cargas_iniciales_diferidas():
    """Aqui SI se quieren las cargas iniciales de cada panel (QTimer.singleShot de 100 ms que el conftest de UI
    omite): son justo las que encienden la barra."""
    yield


@pytest.fixture()
def avisos(monkeypatch):
    """Los paneles avisan sus errores con dialogos modales, que colgarian el test: se anotan en vez de abrirse."""
    anotados: list[str] = []
    for nombre in ("information", "warning", "critical"):
        monkeypatch.setattr(
            message_box.MessageBox,
            nombre,
            staticmethod(lambda parent, titulo, texto, _n=nombre: anotados.append(f"{_n}: {titulo} - {texto}")),
        )
    return anotados


@pytest.fixture()
def workers(monkeypatch):
    """Cada QueryWorker que arranca durante el test (en orden), para saber cuales encienden la barra."""
    arrancados: list[QueryWorker] = []
    start = QueryWorker.start

    def _start(self, *args, **kwargs):
        arrancados.append(self)
        return start(self, *args, **kwargs)

    monkeypatch.setattr(QueryWorker, "start", _start)
    return arrancados


@pytest.fixture()
def ventana(qtbot, db_session, test_engine, monkeypatch, avisos, workers):
    """MainWindow real de un ADMIN, contra la base de pruebas y sin efectos fuera de ella."""
    monkeypatch.setitem(SessionLocal.kw, "bind", test_engine)  # los paneles abren sesiones con SessionLocal
    monkeypatch.setattr(config, "LICENCIA_URL", "")  # sin licenciamiento: nada de red
    monkeypatch.setattr(config, "LICENCIA_PUBLIC_KEY_B64", "")
    monkeypatch.setattr(cifrado_servidor, "es_servidor", lambda: False)  # sin despacho de correos ni llaves
    admin = crear_usuario_admin(db_session)
    ventana = MainWindow(admin)
    qtbot.addWidget(ventana)
    ventana.show()
    qtbot.waitExposed(ventana)
    return ventana


def _esperar_reposo(qtbot, workers) -> None:
    """Hasta que no quede ningun hilo en marcha y no arranque otro durante REPOSO_SEG (los paneles recargan con
    temporizadores). Ahi la cuenta de la barra tiene que ser 0: si no, un cierre se perdio."""
    estado = {"cantidad": -1, "desde": time.monotonic()}

    def _quieto() -> bool:
        if len(workers) != estado["cantidad"] or any(w.isRunning() for w in workers):
            estado["cantidad"], estado["desde"] = len(workers), time.monotonic()
            return False
        return time.monotonic() - estado["desde"] >= REPOSO_SEG

    qtbot.waitUntil(_quieto, timeout=ESPERA_MAX_MS)


def test_cada_modulo_deja_la_barra_apagada(qtbot, ventana, avisos, workers):
    gestor = GestorActividad.instancia()
    _esperar_reposo(qtbot, workers)  # la carga inicial de la ventana (panel general, tasas, etc.)
    assert gestor._cuenta == 0, "la ventana recien abierta ya deja la barra encendida"

    cargas_por_modulo: dict[str, int] = {}
    for clave in MODULOS_CONFIG:
        antes = len(workers)
        ventana.navegar_a(clave)
        qtbot.wait(200)
        _esperar_reposo(qtbot, workers)
        cargas_por_modulo[clave] = sum(1 for w in workers[antes:] if not w.silencioso)
        assert gestor._cuenta == 0, f"tras abrir '{clave}' la barra queda encendida (cuenta {gestor._cuenta})"
        assert ventana.barra_carga.visible_ocupada is False

    print("\ncargas que encienden la barra, por modulo:", cargas_por_modulo)
    print("avisos de error de los paneles:", avisos)


def test_navegar_a_toda_prisa_entre_modulos_deja_la_barra_apagada(qtbot, ventana, workers):
    gestor = GestorActividad.instancia()
    _esperar_reposo(qtbot, workers)
    for _ in range(4):
        for clave in MODULOS_CONFIG:
            ventana.navegar_a(clave)
            qtbot.wait(3)  # sin dar tiempo a que termine la carga anterior: el caso que dejaba la cuenta en 1
    _esperar_reposo(qtbot, workers)
    assert gestor._cuenta == 0, f"con todos los hilos terminados la cuenta de la barra es {gestor._cuenta}"
    assert ventana.barra_carga.visible_ocupada is False
