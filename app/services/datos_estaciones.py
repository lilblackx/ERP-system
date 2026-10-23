"""datos_estaciones.txt: el archivo con la clave SQL de la app que el instalador del SERVIDOR deja
para instalar las estaciones.

Contiene la contrasena en claro, asi que no debe quedarse: se borra solo a las 24 horas de
creado. Lo ejecutan el servicio de Windows del servidor (app/servicio_licencia.py, cada pocos
segundos) y la app abierta en el servidor (app/ui/main_window.py): si ninguno de los dos corre,
el archivo sigue ahi hasta que alguno arranque -- el propio archivo lo avisa.

Antes de borrarlo se sobrescribe su contenido: en un disco magnetico evita recuperar la clave del
archivo borrado; en un SSD no es una garantia, pero tampoco cuesta nada.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

from app.rutas import ARCHIVO_CONFIG

logger = logging.getLogger(__name__)

NOMBRE_ARCHIVO = "datos_estaciones.txt"
HORAS_VIGENCIA = 24


def ruta_por_defecto() -> Path:
    """Junto al config.env de esta instalacion (en ProgramData cuando esta instalada)."""
    return ARCHIVO_CONFIG.parent / NOMBRE_ARCHIVO


def fecha_de_borrado(desde: datetime | None = None) -> datetime:
    return (desde or datetime.now()) + timedelta(hours=HORAS_VIGENCIA)


def borrar_si_vencido(ruta: Path | None = None, ahora: datetime | None = None) -> bool:
    """Borra el archivo si ya paso la vigencia (por su fecha de modificacion). Nunca lanza:
    corre en el bucle del servicio y un archivo en uso o sin permisos no debe tumbarlo.
    Devuelve True si lo borro."""
    ruta = ruta or ruta_por_defecto()
    ahora = ahora or datetime.now()
    try:
        if not ruta.exists():
            return False
        if ahora - datetime.fromtimestamp(ruta.stat().st_mtime) < timedelta(hours=HORAS_VIGENCIA):
            return False
        ruta.write_text("(contenido eliminado)\n", encoding="utf-8")
        ruta.unlink()
        logger.info("Se elimino %s (pasaron %s horas desde su creacion)", ruta, HORAS_VIGENCIA)
        return True
    except OSError:
        logger.exception("No se pudo eliminar %s", ruta)
        return False
