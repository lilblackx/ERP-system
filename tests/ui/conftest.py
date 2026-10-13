import pytest

from app.ui import notificaciones_leidas


@pytest.fixture(autouse=True)
def _archivo_de_leidas_aislado(tmp_path, monkeypatch):
    """El estado leido/no leido de la campana se guarda en un JSON local: en los tests va a un
    directorio temporal para no leer ni ensuciar el archivo real de la instalacion."""
    monkeypatch.setattr(notificaciones_leidas, "ARCHIVO_LEIDAS", tmp_path / "notificaciones_leidas.json")
