"""Ultima version de la app que cada usuario vio en ESTA estacion (para mostrar las novedades una sola vez).

Vive en QSettings (en Windows, registro del usuario de Windows): por estacion y por usuario de la app, sin tocar la
base de datos ni requerir migraciones. Si el usuario entra desde otro equipo vera las novedades una vez alli tambien.
"""

from PySide6.QtCore import QSettings

_ORGANIZACION = "DistribuidoraDJ"
_APLICACION = "App"


def _settings() -> QSettings:
    return QSettings(_ORGANIZACION, _APLICACION)


def _clave(id_usuario: int) -> str:
    return f"novedades/usuario_{int(id_usuario)}/ultima_version"


def ultima_version_vista(id_usuario: int) -> str | None:
    valor = _settings().value(_clave(id_usuario))
    return str(valor) if valor else None


def marcar_version_vista(id_usuario: int, version: str) -> None:
    settings = _settings()
    settings.setValue(_clave(id_usuario), version)
    settings.sync()
