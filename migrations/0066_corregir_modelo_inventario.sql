-- Corregir el modelo de inventario para el cálculo correcto
-- cantidad_caja_total = floor(cantidad_unidad / cantidad_caja)
-- cantidad_caja_unidad = cantidad_unidad % cantidad_caja (solo residuo)

-- Actualizar trigger de cálculo de cajas totales
IF OBJECT_ID('dbo.trg_calcular_cajas_totales', 'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_calcular_cajas_totales;
GO

CREATE TRIGGER trg_calcular_cajas_totales ON dbo.inventario
AFTER INSERT, UPDATE AS
BEGIN
	SET NOCOUNT ON;
	
	-- Calcular cajas totales y residuo cuando se actualiza cantidad_unidad o cantidad_caja
	UPDATE inv
	SET 
		inv.[cantidad_caja_total] = CASE 
			WHEN inv.[cantidad_caja] > 0 THEN FLOOR(inv.[cantidad_unidad] / inv.[cantidad_caja])
			ELSE 0
		END,
		inv.[cantidad_caja_unidad] = CASE 
			WHEN inv.[cantidad_caja] > 0 THEN (inv.[cantidad_unidad] % inv.[cantidad_caja])
			ELSE inv.[cantidad_unidad]
		END
	FROM dbo.inventario inv
	JOIN inserted i ON inv.[id_producto] = i.[id_producto]
	WHERE inv.[cantidad_unidad] <> i.[cantidad_unidad] 
	   OR inv.[cantidad_caja] <> i.[cantidad_caja]
	   OR inv.[cantidad_caja_total] IS NULL
	   OR inv.[cantidad_caja_unidad] IS NULL;
END
GO

-- Recalcular todos los valores existentes
UPDATE dbo.inventario
SET 
	[cantidad_caja_total] = CASE 
		WHEN [cantidad_caja] > 0 THEN FLOOR([cantidad_unidad] / [cantidad_caja])
		ELSE 0
	END,
	[cantidad_caja_unidad] = CASE 
		WHEN [cantidad_caja] > 0 THEN ([cantidad_unidad] % [cantidad_caja])
		ELSE [cantidad_unidad]
	END
WHERE [cantidad_caja_total] IS NULL 
   OR [cantidad_caja_unidad] IS NULL;
GO
