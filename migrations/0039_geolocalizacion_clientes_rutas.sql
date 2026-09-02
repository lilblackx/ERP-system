-- Geolocalizacion opcional para clientes y rutas (decision de producto, 2026-09-01):
-- permite fijar un punto de referencia (lat/lng) por cliente y por ruta para pintarlos en
-- el mapa nuevo (pestaña "Mapa" del modulo Vendedores, app/ui/mapa_rutas_panel.py). El
-- mapa se embebe con Leaflet + OpenStreetMap (sin costo, sin API key) via QWebEngineView,
-- ya incluido en el wheel completo de PySide6 -- no es una dependencia nueva.
--
-- DECIMAL(10,7): 3 digitos enteros + 7 decimales cubre latitud (-90..90) y longitud
-- (-180..180) con precision de centimetros, de sobra para ubicar un negocio/zona.
-- Ambas columnas NULLABLE en ambas tablas -- la geolocalizacion es opcional y no debe
-- bloquear ninguna alta existente de clientes/rutas.

ALTER TABLE dbo.clientes
ADD [latitud] DECIMAL(10,7) NULL,
    [longitud] DECIMAL(10,7) NULL;
GO

ALTER TABLE dbo.rutas
ADD [latitud] DECIMAL(10,7) NULL,
    [longitud] DECIMAL(10,7) NULL;
GO
