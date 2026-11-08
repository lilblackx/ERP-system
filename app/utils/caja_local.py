"""Caja de turno de ESTA estacion de trabajo.

Cada estacion factura de forma independiente: la caja que abre es la suya y es la unica contra la que cobra
en efectivo y da vuelto, aunque otras estaciones tengan sus propias cajas abiertas al mismo tiempo. El
vinculo estacion -> caja vive en QSettings (en Windows, registro del usuario), local a cada equipo, igual que
la impresora (ver impresora_local.py). La BD no lo sabe: una caja es una fila compartida y cualquier estacion
podria cerrarla desde el panel Cajas.
"""

from PySide6.QtCore import QSettings

_ORGANIZACION = "DistribuidoraDJ"
_APLICACION = "App"
_CLAVE = "caja/id_caja"


def _settings() -> QSettings:
    return QSettings(_ORGANIZACION, _APLICACION)


def obtener_caja_local() -> int | None:
    """Id de la caja que esta estacion abrio, o None si nunca abrio una."""
    settings = _settings()
    if not settings.contains(_CLAVE):
        return None
    try:
        return int(settings.value(_CLAVE))
    except (TypeError, ValueError):
        return None


def guardar_caja_local(id_caja: int | None) -> None:
    """Fija la caja de esta estacion. None = ninguna."""
    settings = _settings()
    if id_caja is None:
        settings.remove(_CLAVE)
    else:
        settings.setValue(_CLAVE, int(id_caja))
    settings.sync()


def cajas_de_esta_estacion(cajas_abiertas: list) -> list:
    """De las cajas con turno abierto, deja solo la de esta estacion (vacio si no abrio ninguna o si su
    turno ya se cerro)."""
    id_local = obtener_caja_local()
    if id_local is None:
        return []
    return [c for c in cajas_abiertas if c.id_caja == id_local]
