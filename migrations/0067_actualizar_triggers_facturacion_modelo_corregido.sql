-- Actualizar triggers de facturación para el modelo corregido
-- cantidad_caja_total = floor(cantidad_unidad / cantidad_caja) (calculado)
-- cantidad_caja_unidad = cantidad_unidad % cantidad_caja (calculado - solo residuo)
-- cantidad_unidad: stock total en unidades (valor base que se actualiza)
-- tipo_venta = 'bulto' → descuenta cantidad_caja unidades de cantidad_unidad
-- tipo_venta = 'unidad' → descuenta 1 unidad de cantidad_unidad
-- Después del descuento, el trigger trg_calcular_cajas_totales recalcula los campos derivados

-- Eliminar triggers existentes
IF OBJECT_ID('dbo.trg_factura_detalle_stock_ins', 'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_factura_detalle_stock_ins;
GO

IF OBJECT_ID('dbo.trg_factura_detalle_stock_upd', 'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_factura_detalle_stock_upd;
GO

IF OBJECT_ID('dbo.trg_factura_detalle_stock_del', 'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_factura_detalle_stock_del;
GO

-- Crear trigger de INSERT para modelo corregido
CREATE TRIGGER trg_factura_detalle_stock_ins ON dbo.factura_detalle
AFTER INSERT AS
BEGIN
	SET NOCOUNT ON;
	
	-- Ventas por bulto: descuenta cantidad_caja unidades de cantidad_unidad
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] - agg.[total_unidades]
	FROM dbo.inventario inv
	JOIN (
		SELECT 
			i.[id_producto_factura], 
			SUM(i.[cantidad_producto] * COALESCE(inv.[cantidad_caja], 1)) AS [total_unidades]
		FROM inserted i
		JOIN dbo.inventario inv ON inv.[id_producto] = i.[id_producto_factura]
		WHERE i.[tipo_venta] = 'bulto'
		GROUP BY i.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto];
	
	-- Ventas por unidad: descuenta 1 unidad de cantidad_unidad
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] - agg.[total_unidades]
	FROM dbo.inventario inv
	JOIN (
		SELECT 
			i.[id_producto_factura], 
			SUM(i.[cantidad_producto]) AS [total_unidades]
		FROM inserted i
		WHERE i.[tipo_venta] = 'unidad' OR i.[tipo_venta] IS NULL
		GROUP BY i.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto];
	
	-- Recalcular cantidad_caja_total y cantidad_caja_unidad para todos los productos afectados
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
	WHERE inv.[id_producto] IN (SELECT DISTINCT [id_producto_factura] FROM inserted);
END
GO

-- Crear trigger de UPDATE para modelo corregido
CREATE TRIGGER trg_factura_detalle_stock_upd ON dbo.factura_detalle
AFTER UPDATE AS
BEGIN
	SET NOCOUNT ON;
	
	-- Revertir valores anteriores (deleted)
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] + agg.[total_unidades]
	FROM dbo.inventario inv
	JOIN (
		SELECT 
			d.[id_producto_factura], 
			SUM(d.[cantidad_producto] * COALESCE(inv.[cantidad_caja], 1)) AS [total_unidades]
		FROM deleted d
		JOIN dbo.inventario inv ON inv.[id_producto] = d.[id_producto_factura]
		WHERE d.[tipo_venta] = 'bulto'
		GROUP BY d.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto];
	
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] + agg.[total_unidades]
	FROM dbo.inventario inv
	JOIN (
		SELECT d.[id_producto_factura], SUM(d.[cantidad_producto]) AS [total_unidades]
		FROM deleted d
		WHERE d.[tipo_venta] = 'unidad' OR d.[tipo_venta] IS NULL
		GROUP BY d.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto];
	
	-- Aplicar nuevos valores (inserted)
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] - agg.[total_unidades]
	FROM dbo.inventario inv
	JOIN (
		SELECT 
			i.[id_producto_factura], 
			SUM(i.[cantidad_producto] * COALESCE(inv.[cantidad_caja], 1)) AS [total_unidades]
		FROM inserted i
		JOIN dbo.inventario inv ON inv.[id_producto] = i.[id_producto_factura]
		WHERE i.[tipo_venta] = 'bulto'
		GROUP BY i.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto];
	
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] - agg.[total_unidades]
	FROM dbo.inventario inv
	JOIN (
		SELECT i.[id_producto_factura], SUM(i.[cantidad_producto]) AS [total_unidades]
		FROM inserted i
		WHERE i.[tipo_venta] = 'unidad' OR i.[tipo_venta] IS NULL
		GROUP BY i.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto];
	
	-- Recalcular cantidad_caja_total y cantidad_caja_unidad para todos los productos afectados
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
	WHERE inv.[id_producto] IN (SELECT DISTINCT [id_producto_factura] FROM inserted UNION SELECT DISTINCT [id_producto_factura] FROM deleted);
END
GO

-- Crear trigger de DELETE para modelo corregido
CREATE TRIGGER trg_factura_detalle_stock_del ON dbo.factura_detalle
AFTER DELETE AS
BEGIN
	SET NOCOUNT ON;
	
	-- Restaurar unidades
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] + agg.[total_unidades]
	FROM dbo.inventario inv
	JOIN (
		SELECT 
			d.[id_producto_factura], 
			SUM(d.[cantidad_producto] * COALESCE(inv.[cantidad_caja], 1)) AS [total_unidades]
		FROM deleted d
		JOIN dbo.inventario inv ON inv.[id_producto] = d.[id_producto_factura]
		WHERE d.[tipo_venta] = 'bulto'
		GROUP BY d.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto];
	
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] + agg.[total_unidades]
	FROM dbo.inventario inv
	JOIN (
		SELECT d.[id_producto_factura], SUM(d.[cantidad_producto]) AS [total_unidades]
		FROM deleted d
		WHERE d.[tipo_venta] = 'unidad' OR d.[tipo_venta] IS NULL
		GROUP BY d.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto];
	
	-- Recalcular cantidad_caja_total y cantidad_caja_unidad para todos los productos afectados
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
	WHERE inv.[id_producto] IN (SELECT DISTINCT [id_producto_factura] FROM deleted);
END
GO
