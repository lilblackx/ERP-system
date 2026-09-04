"""Geolocalizacion precisa nativa de Windows para el boton "Mi ubicacion" de
app/ui/mapa_widget.py -- reemplaza a `navigator.geolocation` de Chromium/QtWebEngine
(2026-09-03, hallazgo del usuario: "el boton no esta funcionando bien").

Motivo del reemplazo: en escritorio, sin GPS dedicado, `navigator.geolocation` depende
del "proveedor de ubicacion por red" de Chromium, que necesita una clave de API de Google
incrustada en el build del navegador -- los builds oficiales de QtWebEngine (a diferencia
de Chrome/Edge) no la traen configurada, asi que `getCurrentPosition()` falla casi
siempre con `POSITION_UNAVAILABLE` en este entorno. Es una limitacion conocida de
QtWebEngine, no arreglable desde JS.

`Geolocator` (WinRT, `winrt.windows.devices.geolocation` -- paquetes `winrt-Windows.*` en
requirements.txt, sucesores de `winsdk` que ya no tiene wheels para Python 3.13+) consulta
en cambio el proveedor de ubicacion del propio sistema operativo (Configuracion >
Privacidad > Ubicacion de Windows -- GPS si el equipo lo tiene, o triangulacion por WiFi/
red que Windows ya resuelve internamente), sin depender de ninguna clave de terceros. Es
la mayor precision alcanzable en un desktop sin GPS -- lo mas parecido a como una app como
Google Maps ubica un dispositivo sin GPS propio. Probado 2026-09-03 contra el Geolocator
real: `access status: ALLOWED`, devuelve lat/lng/accuracy validos (la precision en si
depende de que hardware/red tenga el equipo -- WiFi da un radio de decenas de metros,
sin WiFi cae a resolucion por IP, mismo orden de magnitud que cualquier otro metodo
sin GPS).

Bloqueante y solo para Windows: se ejecuta con `app/ui/geo_http.py::HttpWorker` (QThread
generico, mismo patron que las llamadas HTTP de ese modulo) para no congelar la UI. Los
paquetes `winrt-Windows.*` no tienen wheel para Linux/Mac -- ver el marcador de entorno en
requirements.txt -- asi que el import es perezoso (dentro de la funcion, no a nivel de
modulo) para que importar este archivo no reviente en un entorno no-Windows (ej. CI)
aunque nunca se llegue a invocar la funcion ahi."""

import asyncio
import logging
import sys

logger = logging.getLogger(__name__)

# Mismo vocabulario de error que ya esperaba _on_geoerror_js en mapa_widget.py (antes de
# este cambio) para no tener que tocar los textos de UI: "denied" (permiso negado, a nivel
# de Windows o de la propia app), "timeout" (no respondio a tiempo), "unavailable"
# (Windows no pudo resolver una ubicacion -- Ubicacion desactivada globalmente, sin
# proveedor disponible, paquetes winrt-Windows.* no instalados, etc.).
_TIMEOUT_SEGUNDOS = 10


def obtener_ubicacion_precisa_windows() -> dict:
    """Devuelve `{"lat": float, "lng": float, "accuracy": float}` (accuracy en metros) o
    `{"error": "denied" | "timeout" | "unavailable"}`. Nunca lanza -- ver criterio general
    de este tipo de funciones en geo_http.py."""
    if sys.platform != "win32":
        return {"error": "unavailable"}
    try:
        from winrt.windows.devices.geolocation import GeolocationAccessStatus, Geolocator, PositionAccuracy
    except ImportError:
        logger.warning("winrt-Windows.Devices.Geolocation no esta instalado -- geolocalizacion precisa no disponible")
        return {"error": "unavailable"}

    async def _consultar() -> dict:
        try:
            status = await Geolocator.request_access_async()
        except Exception:
            logger.exception("Geolocator.request_access_async() fallo")
            return {"error": "unavailable"}
        if status != GeolocationAccessStatus.ALLOWED:
            return {"error": "denied"}

        geolocator = Geolocator()
        geolocator.desired_accuracy = PositionAccuracy.HIGH
        try:
            posicion = await asyncio.wait_for(geolocator.get_geoposition_async(), timeout=_TIMEOUT_SEGUNDOS)
        except TimeoutError:
            return {"error": "timeout"}
        except Exception:
            logger.exception("Geolocator.get_geoposition_async() fallo")
            return {"error": "unavailable"}

        punto = posicion.coordinate.point.position
        return {
            "lat": punto.latitude,
            "lng": punto.longitude,
            "accuracy": posicion.coordinate.accuracy,
        }

    try:
        return asyncio.run(_consultar())
    except Exception:
        logger.exception("Fallo la geolocalizacion nativa de Windows")
        return {"error": "unavailable"}
