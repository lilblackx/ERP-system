"""Llamadas HTTP livianas para geolocalizacion, usadas por app/ui/mapa_widget.py:

- `obtener_ubicacion_dispositivo()`: geolocalizacion aproximada del equipo por IP (sin
  GPS, sin permisos del SO) via ipwho.is -- solo para centrar el mapa cerca del usuario
  al crear un cliente/ruta nuevo (comodidad de UX), nunca para fijar coordenadas
  automaticamente. Se probo primero con ipapi.co (2026-09-01) pero devolvia 429 (limite
  de uso excedido) de forma consistente; ipwho.is es gratuito sin limite documentado.
- `buscar_lugares(texto)`: geocoding por nombre via Nominatim (OpenStreetMap) para que el
  usuario pueda buscar un lugar o punto de referencia en vez de tener que ubicarlo a ojo
  en el mapa. Politica de uso de Nominatim (max ~1 req/seg, User-Agent identificando la
  app): https://operations.osmfoundation.org/policies/nominatim/ -- uso interactivo
  (un usuario, un click) esta dentro de esa politica.
- `calcular_ruta_por_calles(origen, destino)`: trazado real (siguiendo calles) entre dos
  puntos via OSRM (router.project-osrm.org), usado por RutaFormDialog para dibujar y
  guardar el recorrido de una ruta (migrations/0040). Es la demo publica de OSRM: gratuita
  pero sin SLA -- decision aceptada por el usuario 2026-09-01 a cambio de no pagar ni
  gestionar un servicio de ruteo propio. Si falla, el llamador cae a una linea recta entre
  origen y destino (ver RutaFormDialog) en vez de dejar la ruta sin trazado.

Todas las funciones son bloqueantes y **nunca deben llamarse desde el hilo de GUI**: usar
`HttpWorker` (QThread) para correrlas aparte, mismo motivo que
app/ui/workers.py::QueryWorker pero sin sesion de base de datos. Todas devuelven un valor
"vacio" (None o []) ante cualquier fallo -- sin internet, servicio caido, timeout, rate
limit -- en vez de lanzar: son comodidades de UX, nunca deben bloquear ni ensuciar el
guardado de un cliente/ruta.
"""

import json
import logging
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)

_USER_AGENT = "DistribuidoraDJ-ERP/1.0"
_TIMEOUT_SEGUNDOS = 5

_URL_IP_GEOLOCALIZACION = "https://ipwho.is/"
_URL_NOMINATIM_BUSQUEDA = "https://nominatim.openstreetmap.org/search"
_URL_OSRM_RUTA = "https://router.project-osrm.org/route/v1/driving"


def _get_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SEGUNDOS) as resp:  # noqa: S310 (URL fija, https)
        return json.loads(resp.read().decode("utf-8"))


def obtener_ubicacion_dispositivo() -> tuple[float, float] | None:
    try:
        datos = _get_json(_URL_IP_GEOLOCALIZACION)
        if not datos.get("success", True):
            return None
        lat, lng = datos.get("latitude"), datos.get("longitude")
        if lat is None or lng is None:
            return None
        return float(lat), float(lng)
    except Exception:
        logger.info("No se pudo determinar la ubicación aproximada del dispositivo", exc_info=True)
        return None


def buscar_lugares(texto: str) -> list[dict]:
    """Hasta 5 resultados [{'nombre': str, 'lat': float, 'lng': float}, ...], o [] si no
    hay resultados o la busqueda falla. Restringido a Venezuela (`countrycodes=ve`,
    2026-09-01, pedido del usuario): sin esto Nominatim devuelve homonimos de cualquier
    pais (ej. "Condominio 9" en Mexico/Chile), que para una distribuidora que opera solo
    en Venezuela son ruido puro -- nunca la ubicacion que el usuario esta buscando."""
    query = urllib.parse.urlencode({"q": texto, "format": "json", "limit": 5, "countrycodes": "ve"})
    try:
        datos = _get_json(f"{_URL_NOMINATIM_BUSQUEDA}?{query}")
    except Exception:
        logger.info("Falló la búsqueda de lugares '%s'", texto, exc_info=True)
        return []
    return [
        {"nombre": item["display_name"], "lat": float(item["lat"]), "lng": float(item["lon"])} for item in datos or []
    ]


def calcular_ruta_por_calles(
    origen: tuple[float, float], destino: tuple[float, float]
) -> list[tuple[float, float]] | None:
    """Trazado por calles entre `origen` y `destino` (ambos (lat, lng)) via OSRM, como
    lista de (lat, lng). `None` ante cualquier fallo -- sin ruta encontrada, timeout,
    servicio caido -- el llamador debe caer a una linea recta en ese caso."""
    lat1, lng1 = origen
    lat2, lng2 = destino
    query = urllib.parse.urlencode({"overview": "full", "geometries": "geojson"})
    url = f"{_URL_OSRM_RUTA}/{lng1},{lat1};{lng2},{lat2}?{query}"
    try:
        datos = _get_json(url)
        if datos.get("code") != "Ok" or not datos.get("routes"):
            return None
        # GeoJSON trae [lng, lat] -- se invierte al formato (lat, lng) usado en todo el
        # resto del proyecto (Cliente.latitud/longitud, Ruta.latitud/longitud, etc.).
        coordenadas = datos["routes"][0]["geometry"]["coordinates"]
        return [(lat, lng) for lng, lat in coordenadas]
    except Exception:
        logger.info("Falló el cálculo de ruta por calles (%s -> %s)", origen, destino, exc_info=True)
        return None


class HttpWorker(QThread):
    """Ejecuta `funcion()` (sin argumentos, tipicamente `functools.partial` de una de las
    funciones de arriba) en un hilo aparte y emite su valor de retorno -- generico para
    no duplicar el boilerplate de QThread entre las dos llamadas de este modulo."""

    resultado = Signal(object)

    def __init__(self, funcion: Callable[[], Any], parent=None):
        super().__init__(parent)
        self._funcion = funcion

    def run(self) -> None:
        self.resultado.emit(self._funcion())
