-- Actualizar triggers de compras para el modelo corregido
-- cantidad_caja_total = floor(cantidad_unidad / cantidad_caja) (calculado)
-- cantidad_caja_unidad = cantidad_unidad % cantidad_caja (calculado - solo residuo)
-- cantidad_unidad: stock total en unidades (valor base que se actualiza)
-- stock_ya_contabilizado: si es True, NO actualizar stock (ya fue contabilizado en NR)

-- Eliminar triggers existentes de compras
IF OBJECT_ID('dbo.trg_compra_detalle_stock_ins', 'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_compra_detalle_stock_ins;
GO

IF OBJECT_ID('dbo.trg_compra_detalle_stock_upd', 'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_compra_detalle_stock_upd;
GO

IF OBJECT_ID('dbo.trg_compra_detalle_stock_del', 'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_compra_detalle_stock_del;
GO

-- Crear trigger de INSERT para compras
CREATE TRIGGER trg_compra_detalle_stock_ins ON dbo.compra_detalle
AFTER INSERT AS
BEGIN
	SET NOCOUNT ON;
	
	-- Solo actualizar stock si stock_ya_contabilizado es False o NULL
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] + agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT [id_producto_compra], SUM([cantidad_producto]) AS [total_cant]
		FROM inserted
		WHERE [stock_ya_contabilizado] = 0 OR [stock_ya_contabilizado] IS NULL
		GROUP BY [id_producto_compra]
	) agg ON agg.[id_producto_compra] = inv.[id_producto];
	
	-- Recalcular cantidad_caja_total y cantidad_caja_unidad para productos afectados
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
	WHERE inv.[id_producto] IN (SELECT DISTINCT [id_producto_compra] FROM inserted WHERE [stock_ya_contabilizado] = 0 OR [stock_ya_contabilizado] IS NULL);
END
GO

-- Crear trigger de UPDATE para compras
CREATE TRIGGER trg_compra_detalle_stock_upd ON dbo.compra_detalle
AFTER UPDATE AS
BEGIN
	SET NOCOUNT ON;
	
	-- Solo actualizar stock si stock_ya_contabilizado es False o NULL
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] - agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT [id_producto_compra], SUM([cantidad_producto]) AS [total_cant]
		FROM deleted
		WHERE [stock_ya_contabilizado] = 0 OR [stock_ya_contabilizado] IS NULL
		GROUP BY [id_producto_compra]
	) agg ON agg.[id_producto_compra] = inv.[id_producto];

	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] + agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT [id_producto_compra], SUM([cantidad_producto]) AS [total_cant]
		FROM inserted
		WHERE [stock_ya_contabilizado] = 0 OR [stock_ya_contabilizado] IS NULL
		GROUP BY [id_producto_compra]
	) agg ON agg.[id_producto_compra] = inv.[id_producto];
	
	-- Recalcular cantidad_caja_total y cantidad_caja_unidad para productos afectados
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
	WHERE inv.[id_producto] IN (
		SELECT DISTINCT [id_producto_compra] FROM deleted WHERE [stock_ya_contabilizado] = 0 OR [stock_ya_contabilizado] IS NULL
		UNION
		SELECT DISTINCT [id_producto_compra] FROM inserted WHERE [stock_ya_contabilizado] = 0 OR [stock_ya_contabilizado] IS NULL
	);
END
GO

-- Crear trigger de DELETE para compras
CREATE TRIGGER trg_compra_detalle_stock_del ON dbo.compra_detalle
AFTER DELETE AS
BEGIN
	SET NOCOUNT ON;
	
	-- Solo actualizar stock si stock_ya_contabilizado es False o NULL
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] - agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT [id_producto_compra], SUM([cantidad_producto]) AS [total_cant]
		FROM deleted
		WHERE [stock_ya_contabilizado] = 0 OR [stock_ya_contabilizado] IS NULL
		GROUP BY [id_producto_compra]
	) agg ON agg.[id_producto_compra] = inv.[id_producto];
	
	-- Recalcular cantidad_caja_total y cantidad_caja_unidad para productos afectados
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
	WHERE inv.[id_producto] IN (SELECT DISTINCT [id_producto_compra] FROM deleted WHERE [stock_ya_contabilizado] = 0 OR [stock_ya_contabilizado] IS NULL);
END
GO
