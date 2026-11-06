"""Impresora predeterminada de ESTA estacion de trabajo.

Antes se guardaba en configuracion_empresa.impresora_predeterminada (BD compartida), por
lo que cambiarla en una estacion la cambiaba en todas -- y el nombre de una impresora
solo tiene sentido en el equipo donde esta instalada. Ahora vive en QSettings (en
Windows, registro del usuario: HKCU\\Software\\DistribuidoraDJ\\App), local a cada equipo.

La columna de la BD queda como valor heredado: solo se consulta, de forma de migracion
suave, mientras la estacion nunca haya guardado una impresora propia y solo si esa
impresora esta instalada en este equipo. Ya no se escribe.
"""

from PySide6.QtCore import QSettings
from PySide6.QtPrintSupport import QPrinterInfo

_ORGANIZACION = "DistribuidoraDJ"
_APLICACION = "App"
_CLAVE = "impresora/predeterminada"


def _settings() -> QSettings:
    return QSettings(_ORGANIZACION, _APLICACION)


def obtener_impresora_local(config_empresa=None) -> str | None:
    """Nombre de la impresora predeterminada de esta estacion, o None si no hay.

    `config_empresa` es opcional y solo se usa para el valor heredado de la BD (ver
    docstring del modulo). Una clave local vacia significa "Ninguna" elegida a
    proposito y NO cae al valor heredado."""
    settings = _settings()
    if settings.contains(_CLAVE):
        return str(settings.value(_CLAVE) or "") or None

    heredada = getattr(config_empresa, "impresora_predeterminada", None) if config_empresa else None
    if heredada and heredada in {p.printerName() for p in QPrinterInfo.availablePrinters()}:
        return heredada
    return None


def guardar_impresora_local(nombre: str | None) -> None:
    """Fija la impresora de esta estacion. None/"" = ninguna (no imprimir automaticamente)."""
    settings = _settings()
    settings.setValue(_CLAVE, nombre or "")
    settings.sync()
