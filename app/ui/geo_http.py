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


_workers_activos: set["HttpWorker"] = set()


def esperar_workers_pendientes(timeout_ms: int = 6000) -> None:
    """Conectar a `QApplication.aboutToQuit` (ver app/main.py). Un `HttpWorker` nunca
    tiene un padre Qt (ver comentario en `__init__`), asi que nada mas lo destruye
    automaticamente al cerrar la ventana -- sin este `wait()` explicito, cerrar la app
    mientras una busqueda/geolocalizacion/calculo de trazado sigue en vuelo (timeout de
    `_TIMEOUT_SEGUNDOS` cada una) desmonta el proceso con un QThread todavia corriendo,
    lo cual Qt trata como fatal. En la practica hay 0 o 1 worker pendiente a la vez, asi
    que este bloqueo es casi siempre instantaneo -- reportado como riesgo de crash en
    auditoria, 2026-09-02."""
    for worker in list(_workers_activos):
        worker.wait(timeout_ms)


class HttpWorker(QThread):
    """Ejecuta `funcion()` (sin argumentos, tipicamente `functools.partial` de una de las
    funciones de arriba) en un hilo aparte y emite su valor de retorno -- generico para
    no duplicar el boilerplate de QThread entre las llamadas de este modulo."""

    resultado = Signal(object)

    def __init__(self, funcion: Callable[[], Any], parent=None):
        super().__init__(parent)
        self._funcion = funcion
        # Sin padre Qt: los llamadores (MapaWidget, RutaFormDialog) ya NO pasan `self`
        # como parent a proposito. Este worker puede seguir corriendo hasta 5s
        # (_TIMEOUT_SEGUNDOS) despues de que el usuario cierre el dialogo que lo lanzo --
        # si fuera hijo Qt de ese widget, Qt intentaria destruirlo junto con su padre
        # mientras el hilo sigue activo, lo cual es fatal ("QThread: Destroyed while
        # thread is still running"). Este set a nivel de modulo lo mantiene vivo con vida
        # propia hasta que termina solo (ver _limpiar), sin importar que paso con quien lo
        # creo -- hallazgo de auditoria, 2026-09-02.
        _workers_activos.add(self)
        self.finished.connect(self._limpiar)

    def _limpiar(self) -> None:
        _workers_activos.discard(self)
        self.deleteLater()

    def run(self) -> None:
        self.resultado.emit(self._funcion())
