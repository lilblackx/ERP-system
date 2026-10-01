-- Agregar inventario.cantidad_caja_unidad en entornos creados con un baseline anterior.
-- schema_sqlserver.sql ya la incluye, pero ninguna migracion la creaba, y 0063 en
-- adelante (trigger trg_calcular_cajas_totales) la usan. Debe correr antes de 0063.
-- Se pobla en 0066 (residuo de cantidad_unidad % cantidad_caja).

IF NOT EXISTS (
	SELECT 1 FROM sys.columns
	WHERE object_id = OBJECT_ID('dbo.inventario')
	AND name = 'cantidad_caja_unidad'
)
BEGIN
	ALTER TABLE dbo.inventario
	ADD [cantidad_caja_unidad] DECIMAL(12,2) NOT NULL DEFAULT 0.000;
END
GO
