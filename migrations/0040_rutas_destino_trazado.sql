-- Convierte la ruta de "un punto de referencia" (migrations/0039) a un recorrido real
-- origen -> destino (decision de producto, 2026-09-01): latitud/longitud (ya existentes)
-- pasan a significar el ORIGEN de la ruta -- no se renombran para no romper datos/tests
-- existentes -- y se agrega destino_latitud/destino_longitud como el segundo punto.
--
-- trazado_geojson cachea el recorrido calculado por calles (OSRM, ver
-- app/ui/geo_http.py::calcular_ruta_por_calles) como una lista JSON [[lat,lng], ...] --
-- se calcula una sola vez en RutaFormDialog cuando se fija/cambia origen o destino, para
-- que ver el mapa general (app/ui/mapa_rutas_panel.py) nunca dependa de la disponibilidad
-- del servicio publico de OSRM (gratuito, sin SLA).
--
-- Todas NULLABLE en BD -- igual criterio que 0039: RutaService.crear()/actualizar() son
-- quienes exigen destino_latitud/destino_longitud para toda ruta NUEVA o editada, sin
-- forzar un backfill sobre rutas existentes que solo tienen el punto de origen.

ALTER TABLE dbo.rutas
ADD [destino_latitud] DECIMAL(10,7) NULL,
    [destino_longitud] DECIMAL(10,7) NULL,
    [trazado_geojson] VARCHAR(MAX) NULL;
GO
