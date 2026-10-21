import pytest
from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtWidgets import QWidget

from app.ui import animaciones, notificaciones_leidas, permisos_ui

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
    # Procesa todos los eventos pendientes antes de destruir widgets
    QCoreApplication.processEvents()
    # Forzar garbage collection para liberar objetos Qt
    import gc

    gc.collect()
    # Segunda pasada de eventos después de GC
    QCoreApplication.processEvents()
