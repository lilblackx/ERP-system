-- Agregar campo cantidad_caja_total para almacenar cajas completas calculadas
-- cantidad_caja_total = cantidad_caja_unidad / cantidad_caja
-- Este campo se mantiene actualizado mediante triggers

IF NOT EXISTS (
	SELECT 1 FROM sys.columns
	WHERE object_id = OBJECT_ID('dbo.inventario')
	AND name = 'cantidad_caja_total'
)
BEGIN
	ALTER TABLE dbo.inventario
	ADD [cantidad_caja_total] DECIMAL(12,2) NOT NULL DEFAULT 0.000;
END
GO

-- Trigger para mantener cantidad_caja_total sincronizado
IF OBJECT_ID('dbo.trg_calcular_cajas_totales', 'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_calcular_cajas_totales;
GO

CREATE TRIGGER trg_calcular_cajas_totales ON dbo.inventario
AFTER INSERT, UPDATE AS
BEGIN
	SET NOCOUNT ON;
	
	-- Calcular cajas totales cuando se actualiza cantidad_caja_unidad o cantidad_caja
	UPDATE inv
	SET inv.[cantidad_caja_total] = CASE 
		WHEN inv.[cantidad_caja] > 0 THEN FLOOR(inv.[cantidad_caja_unidad] / inv.[cantidad_caja])
		ELSE 0
	END
	FROM dbo.inventario inv
	JOIN inserted i ON inv.[id_producto] = i.[id_producto]
	WHERE inv.[cantidad_caja_unidad] <> i.[cantidad_caja_unidad] 
	   OR inv.[cantidad_caja] <> i.[cantidad_caja]
	   OR inv.[cantidad_caja_total] IS NULL;
END
GO

-- Inicializar cantidad_caja_total para registros existentes
UPDATE dbo.inventario
SET [cantidad_caja_total] = CASE 
	WHEN [cantidad_caja] > 0 THEN FLOOR([cantidad_caja_unidad] / [cantidad_caja])
	ELSE 0
END
WHERE [cantidad_caja_total] = 0 OR [cantidad_caja_total] IS NULL;
GO
