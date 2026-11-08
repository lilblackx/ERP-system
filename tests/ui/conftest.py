import pytest
from PySide6.QtCore import QCoreApplication, QSettings, QTimer
from PySide6.QtWidgets import QWidget

from app.ui import animaciones, carga_asincrona, notificaciones_leidas, permisos_ui
from app.utils import caja_local, impresora_local, novedades_local

_single_shot_original = QTimer.singleShot


@pytest.fixture(autouse=True)
def _sin_animaciones(monkeypatch, tmp_path):
    """Las animaciones apagadas por defecto: los tiempos de una animacion no tienen lugar en un test. Los tests
    de app/ui/animaciones.py las activan a mano con animaciones.forzar(True). La preferencia guardada va a un
    directorio temporal para no leer ni ensuciar la de la PC real."""
    monkeypatch.setattr(animaciones, "ARCHIVO_PREFERENCIAS", tmp_path / "preferencias_ui.json")
    monkeypatch.setattr(animaciones, "_reducir_cache", None)
    animaciones.forzar(False)
    yield
    animaciones.forzar(None)


@pytest.fixture(autouse=True)
def _archivo_de_leidas_aislado(tmp_path, monkeypatch):
    """El estado leido/no leido de la campana se guarda en un JSON local: en los tests va a un
    directorio temporal para no leer ni ensuciar el archivo real de la instalacion."""
    monkeypatch.setattr(notificaciones_leidas, "ARCHIVO_LEIDAS", tmp_path / "notificaciones_leidas.json")


@pytest.fixture(autouse=True)
def _impresora_local_aislada(tmp_path, monkeypatch):
    """La impresora de la estacion vive en QSettings (registro de Windows): en los tests va a un .ini
    temporal para no leer ni pisar la configuracion de la PC real."""
    ruta = str(tmp_path / "estacion.ini")
    monkeypatch.setattr(impresora_local, "_settings", lambda: QSettings(ruta, QSettings.Format.IniFormat))


@pytest.fixture(autouse=True)
def _caja_local_aislada(tmp_path, monkeypatch):
    """La caja de la estacion tambien vive en QSettings: va a un .ini temporal."""
    ruta = str(tmp_path / "caja_estacion.ini")
    monkeypatch.setattr(caja_local, "_settings", lambda: QSettings(ruta, QSettings.Format.IniFormat))


@pytest.fixture(autouse=True)
def _novedades_local_aislada(tmp_path, monkeypatch):
    """Lo "ya visto" de las novedades tambien va a un .ini temporal, para no leer ni pisar el registro de la PC real."""
    ruta = str(tmp_path / "novedades.ini")
    monkeypatch.setattr(novedades_local, "_settings", lambda: QSettings(ruta, QSettings.Format.IniFormat))


class _SenalInmediata:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)


class WorkerInmediato:
    """Reemplaza a QueryWorker en carga_asincrona: corre la tarea en el acto y entrega el resultado, sin hilo."""

    def __init__(self, session_factory, tarea, *args, **kwargs):
        self._session_factory, self._tarea, self._args, self._kwargs = session_factory, tarea, args, kwargs
        self.silencioso = False
        self.resultado, self.error, self.finished = _SenalInmediata(), _SenalInmediata(), _SenalInmediata()

    def start(self):
        session = self._session_factory()
        try:
            valor = self._tarea(session, *self._args, **self._kwargs)
        finally:
            session.close()
        self.resultado.emit(valor)
        self.finished.emit()

    def isFinished(self):
        return True

    def wait(self, _ms):
        return True


@pytest.fixture(autouse=True)
def _cargas_asincronas_inmediatas(monkeypatch):
    """Los paneles piden sus listados en un hilo aparte (app/ui/carga_asincrona.py). En los tests la tarea corre
    en el acto, asi que `panel.cargar_x()` deja la tabla poblada al volver, como antes. Los tests del camino
    asincrono en si cambian esta clase por un worker falso que no ejecuta nada."""
    monkeypatch.setattr(carga_asincrona, "QueryWorker", WorkerInmediato)


@pytest.fixture(autouse=True)
def _sin_catalogos_de_reportes(monkeypatch):
    """ReportesPanel pide los catalogos de sus combos en un hilo aparte al construirse. En los tests ese hilo
    correria contra una Session de mentira en medio de otro test: se omite, y los tests del llenado llaman
    a `_llenar_catalogos` con datos propios."""
    from app.ui.reportes_panel import ReportesPanel

    monkeypatch.setattr(ReportesPanel, "_cargar_catalogos", lambda self: None)


@pytest.fixture(autouse=True)
def _sin_cargas_iniciales_diferidas(monkeypatch):
    """Los paneles arrancan su primera carga con QTimer.singleShot(100, self.cargar_...). En los
    tests el panel recibe una Session mockeada y se destruye al terminar el test, pero el timer
    sigue vivo: a los 100 ms dispara la carga contra esa Session dentro de OTRO test, y pytest-qt
    le atribuye la excepcion ("Exceptions caught in Qt event loop") -- una falla al azar que
    cambia de test segun el tiempo que tome cada uno. Esa carga inicial no se necesita en ningun
    test (los que ejercitan la carga llaman al metodo directo), asi que se omite; el resto de los
    singleShot (debounce de busqueda, etc.) sigue funcionando."""

    def single_shot(msec, *args):
        callback = args[0] if len(args) == 1 else None
        if msec == 100 and isinstance(getattr(callback, "__self__", None), QWidget):
            return None
        return _single_shot_original(msec, *args)

    monkeypatch.setattr(QTimer, "singleShot", staticmethod(single_shot))


@pytest.fixture(autouse=True)
def _permisos_concedidos_por_defecto(request, monkeypatch):
    """Los paneles muestran sus botones segun el permiso del usuario (app/ui/permisos_ui.py). Los
    tests de UI arman paneles con una Session mockeada, contra la que ese chequeo daria "sin
    permiso" y ocultaria los botones (o abriria un aviso modal que bloquea el test). Por defecto se
    conceden todos los permisos; los tests con base de datos real (fixture db_session) prueban la
    matriz de verdad y no se tocan."""
    if "db_session" in request.fixturenames:
        return
    for nombre in ("tiene_permiso", "es_admin", "tiene_permiso_en_sesion", "es_admin_en_sesion"):
        monkeypatch.setattr(permisos_ui, nombre, lambda *args, **kwargs: True)


@pytest.fixture(autouse=True)
def _limpiar_eventos_qt(qtbot):
    """Limpia eventos pendientes de Qt despues de cada test para evitar memory corruption
    en CI headless (GH Actions)."""
    yield
    # Procesa todos los eventos pendientes múltiples veces
    for _ in range(3):
        QCoreApplication.processEvents()
    # Forzar garbage collection agresivo para liberar objetos Qt
    import gc

    gc.collect()
    gc.collect()
    # Segunda pasada de eventos después de GC
    for _ in range(3):
        QCoreApplication.processEvents()
