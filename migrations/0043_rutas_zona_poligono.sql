-- Redefine una ruta de origen->destino (recorrido por calles, migrations/0040) a una
-- ZONA de cobertura (poligono de vertices) -- decision de negocio, 2026-09-03: "una ruta
-- para un vendedor no es un punto A/B, es una zona donde todos los clientes dentro de esa
-- zona son atendidos por ese vendedor". Reemplazo completo (no se mantiene el modelo
-- anterior): las rutas se crearon hace muy pocos dias (2026-09-01) y el modelo de
-- origen/destino/trazado nunca llego a usarse para nada mas que dibujar un mapa, asi que
-- no hay dato de negocio real que preservar.
--
-- zona_geojson sigue el mismo formato "no realmente GeoJSON" que trazado_geojson tenia
-- (lista plana de pares [lat,lng], no un objeto {"type":"Polygon",...}) -- consistencia
-- con la convencion ya establecida en este modulo en vez de introducir un segundo
-- formato. NULLABLE en BD, igual que id_ruta en vendedores/codigo_vendedor: una ruta sin
-- zona configurada no rompe nada a nivel de schema, RutaService.crear()/actualizar() son
-- quienes exigen al menos 3 vertices para una ruta NUEVA o editada.

ALTER TABLE dbo.rutas
DROP COLUMN [latitud], [longitud], [destino_latitud], [destino_longitud], [trazado_geojson];
GO

ALTER TABLE dbo.rutas
ADD [zona_geojson] VARCHAR(MAX) NULL;
GO
