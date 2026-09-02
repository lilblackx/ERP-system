"""Tests de las funciones puras de app/ui/geo_http.py -- sin base de datos (no usan
db_session): mockean urllib.request.urlopen en vez de golpear ipwho.is/Nominatim/OSRM de
verdad, para no depender de internet ni de esos servicios publicos durante la corrida de
tests. HttpWorker (el QThread que las envuelve) no se prueba aca -- requeriria un
QApplication corriendo, y el valor de estos tests esta en la logica de parseo/fallback de
cada funcion, no en el hilo en si. Hallazgo de auditoria, 2026-09-02 (sin cobertura
previa)."""

import json
from unittest.mock import MagicMock, patch

from app.ui import geo_http


def _mock_response(payload) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


# --- obtener_ubicacion_dispositivo ----------------------------------------------------


def test_obtener_ubicacion_dispositivo_ok():
    payload = {"success": True, "latitude": 10.5, "longitude": -66.9}
    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        assert geo_http.obtener_ubicacion_dispositivo() == (10.5, -66.9)


def test_obtener_ubicacion_dispositivo_success_false_devuelve_none():
    with patch("urllib.request.urlopen", return_value=_mock_response({"success": False})):
        assert geo_http.obtener_ubicacion_dispositivo() is None


def test_obtener_ubicacion_dispositivo_falla_devuelve_none():
    with patch("urllib.request.urlopen", side_effect=OSError("sin red")):
        assert geo_http.obtener_ubicacion_dispositivo() is None


# --- buscar_lugares --------------------------------------------------------------------


def test_buscar_lugares_ok():
    payload = [{"display_name": "Caracas, Venezuela", "lat": "10.5", "lon": "-66.9"}]
    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        resultados = geo_http.buscar_lugares("Caracas")
    assert resultados == [{"nombre": "Caracas, Venezuela", "lat": 10.5, "lng": -66.9}]


def test_buscar_lugares_sin_resultados():
    with patch("urllib.request.urlopen", return_value=_mock_response([])):
        assert geo_http.buscar_lugares("xyzxyzxyz") == []


def test_buscar_lugares_falla_devuelve_lista_vacia():
    with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
        assert geo_http.buscar_lugares("Caracas") == []


# --- calcular_ruta_por_calles ------------------------------------------------------------


def test_calcular_ruta_por_calles_ok_invierte_lng_lat_a_lat_lng():
    """OSRM devuelve [lng, lat] (GeoJSON) -- la funcion debe invertirlo a (lat, lng),
    el formato usado en todo el resto del proyecto."""
    payload = {"code": "Ok", "routes": [{"geometry": {"coordinates": [[-66.9, 10.5], [-66.8, 10.6]]}}]}
    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        puntos = geo_http.calcular_ruta_por_calles((10.5, -66.9), (10.6, -66.8))
    assert puntos == [(10.5, -66.9), (10.6, -66.8)]


def test_calcular_ruta_por_calles_sin_rutas_devuelve_none():
    with patch("urllib.request.urlopen", return_value=_mock_response({"code": "NoRoute", "routes": []})):
        assert geo_http.calcular_ruta_por_calles((10.5, -66.9), (10.6, -66.8)) is None


def test_calcular_ruta_por_calles_falla_devuelve_none():
    with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
        assert geo_http.calcular_ruta_por_calles((10.5, -66.9), (10.6, -66.8)) is None
