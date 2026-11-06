"""Ultima version vista por usuario en la estacion (QSettings aislado por el conftest de UI)."""

from app.utils.novedades_local import marcar_version_vista, ultima_version_vista


def test_sin_nada_guardado_no_hay_version_vista():
    assert ultima_version_vista(7) is None


def test_guardar_y_leer_por_usuario():
    marcar_version_vista(7, "1.1.0")
    marcar_version_vista(8, "1.0.0")

    assert ultima_version_vista(7) == "1.1.0"
    assert ultima_version_vista(8) == "1.0.0"  # cada usuario lleva la suya
    assert ultima_version_vista(9) is None


def test_se_puede_actualizar_la_version_vista():
    marcar_version_vista(7, "1.0.0")
    marcar_version_vista(7, "1.1.0")

    assert ultima_version_vista(7) == "1.1.0"
