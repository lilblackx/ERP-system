import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from app.ui import notificaciones_leidas

_single_shot_original = QTimer.singleShot


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
