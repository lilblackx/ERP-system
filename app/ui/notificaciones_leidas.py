"""Estado "leida" de las alertas de la campana (app/ui/topbar.py).

Las alertas no viven en una tabla: se calculan en cada consulta (ver
app/services/notificaciones.py), asi que lo unico que se guarda es CUALES ya vio cada usuario,
en un JSON local por estacion (DIR_DATOS/notificaciones_leidas.json). Es una comodidad de UX:
si el archivo no se puede leer o escribir, la campana sigue funcionando (todo queda como no
leido) -- nunca debe tumbar el shell.

La firma de una alerta incluye su detalle ("clave|detalle"): si la condicion cambia (hay mas
facturas vencidas que antes) la firma es otra y vuelve a contar como no leida.
"""

import json
import logging
from pathlib import Path

from app.rutas import DIR_DATOS
from app.services.notificaciones import Notificacion

logger = logging.getLogger(__name__)

ARCHIVO_LEIDAS = DIR_DATOS / "notificaciones_leidas.json"


def firma(notificacion: Notificacion) -> str:
    return f"{notificacion.clave}|{notificacion.detalle}"


def _leer_archivo(archivo: Path) -> dict:
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        logger.warning("No se pudo leer %s; las alertas quedan como no leidas", archivo, exc_info=True)
        return {}
    return datos if isinstance(datos, dict) else {}


def cargar(id_usuario: int | None, archivo: Path | None = None) -> set[str]:
    """Firmas de las alertas que `id_usuario` ya marco como leidas."""
    archivo = archivo or ARCHIVO_LEIDAS
    firmas = _leer_archivo(archivo).get(str(id_usuario), [])
    return {f for f in firmas if isinstance(f, str)} if isinstance(firmas, list) else set()


def guardar(id_usuario: int | None, firmas: set[str], archivo: Path | None = None) -> None:
    archivo = archivo or ARCHIVO_LEIDAS
    datos = _leer_archivo(archivo)
    if firmas:
        datos[str(id_usuario)] = sorted(firmas)
    else:
        datos.pop(str(id_usuario), None)
    try:
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        logger.warning("No se pudo guardar %s; el estado de lectura no se conserva", archivo, exc_info=True)
