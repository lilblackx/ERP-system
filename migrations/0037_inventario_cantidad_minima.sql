-- Reportes pendientes (2026-08-31): el reporte "Stock bajo minimo" de Inventario
-- necesita un umbral configurable POR PRODUCTO, no un valor generico tipeado a mano en
-- cada corrida -- distintos productos tienen escalas de stock muy distintas. Inventario
-- no tenia ninguna columna de minimo hasta ahora.

ALTER TABLE dbo.inventario
	ADD cantidad_minima NUMERIC(12, 2) NOT NULL CONSTRAINT DF_inventario_cantidad_minima DEFAULT (0.00);
GO
