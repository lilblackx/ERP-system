-- Actualizar triggers de stock para NUEVO modelo de inventario
-- cantidad_caja: unidades por caja (configuración)
-- cantidad_caja_unidad: unidades totales (stock)
-- cantidad_caja_total: cajas completas (calculado: cantidad_caja_unidad / cantidad_caja)
-- tipo_venta = 'bulto' → descuenta 1 de cantidad_caja_total y cantidad_caja de cantidad_caja_unidad
-- tipo_venta = 'unidad' → descuenta 1 de cantidad_caja_unidad

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

-- Crear trigger de INSERT para nuevo modelo
CREATE TRIGGER trg_factura_detalle_stock_ins ON dbo.factura_detalle
AFTER INSERT AS
BEGIN
	SET NOCOUNT ON;
	
	-- Ventas por unidad: descuenta cantidad_producto de cantidad_caja_unidad
	UPDATE inv
	SET inv.[cantidad_caja_unidad] = inv.[cantidad_caja_unidad] - agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT [id_producto_factura], SUM([cantidad_producto]) AS [total_cant]
		FROM inserted
		WHERE [tipo_venta] = 'unidad' OR [tipo_venta] IS NULL
		GROUP BY [id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto]
	WHERE inv.[cantidad_caja_unidad] IS NOT NULL;
	
	-- Ventas por bulto: descuenta cantidad_producto de cantidad_caja_total 
	-- y cantidad_producto * cantidad_caja de cantidad_caja_unidad
	UPDATE inv
	SET 
		inv.[cantidad_caja_total] = inv.[cantidad_caja_total] - agg.[total_bultos],
		inv.[cantidad_caja_unidad] = inv.[cantidad_caja_unidad] - agg.[total_unidades]
	FROM dbo.inventario inv
	JOIN (
		SELECT 
			i.[id_producto_factura], 
			SUM(i.[cantidad_producto]) AS [total_bultos],
			SUM(i.[cantidad_producto] * COALESCE(inv.[cantidad_caja], 1)) AS [total_unidades]
		FROM inserted i
		JOIN dbo.inventario inv ON inv.[id_producto] = i.[id_producto_factura]
		WHERE i.[tipo_venta] = 'bulto'
		GROUP BY i.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto]
	WHERE inv.[cantidad_caja_unidad] IS NOT NULL;
END
GO

-- Crear trigger de UPDATE para nuevo modelo
CREATE TRIGGER trg_factura_detalle_stock_upd ON dbo.factura_detalle
AFTER UPDATE AS
BEGIN
	SET NOCOUNT ON;
	
	-- Revertir valores anteriores (deleted)
	-- Ventas por unidad: restaura cantidad_producto de cantidad_caja_unidad
	UPDATE inv
	SET inv.[cantidad_caja_unidad] = inv.[cantidad_caja_unidad] + agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT d.[id_producto_factura], SUM(d.[cantidad_producto]) AS [total_cant]
		FROM deleted d
		WHERE d.[tipo_venta] = 'unidad' OR d.[tipo_venta] IS NULL
		GROUP BY d.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto]
	WHERE inv.[cantidad_caja_unidad] IS NOT NULL;
	
	-- Ventas por bulto: restaura cantidad_producto de cantidad_caja_total 
	-- y cantidad_producto * cantidad_caja de cantidad_caja_unidad
	UPDATE inv
	SET 
		inv.[cantidad_caja_total] = inv.[cantidad_caja_total] + agg.[total_bultos],
		inv.[cantidad_caja_unidad] = inv.[cantidad_caja_unidad] + agg.[total_unidades]
	FROM dbo.inventario inv
	JOIN (
		SELECT 
			d.[id_producto_factura], 
			SUM(d.[cantidad_producto]) AS [total_bultos],
			SUM(d.[cantidad_producto] * COALESCE(inv.[cantidad_caja], 1)) AS [total_unidades]
		FROM deleted d
		JOIN dbo.inventario inv ON inv.[id_producto] = d.[id_producto_factura]
		WHERE d.[tipo_venta] = 'bulto'
		GROUP BY d.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto]
	WHERE inv.[cantidad_caja_unidad] IS NOT NULL;
	
	-- Aplicar nuevos valores (inserted)
	-- Ventas por unidad: descuenta cantidad_producto de cantidad_caja_unidad
	UPDATE inv
	SET inv.[cantidad_caja_unidad] = inv.[cantidad_caja_unidad] - agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT i.[id_producto_factura], SUM(i.[cantidad_producto]) AS [total_cant]
		FROM inserted i
		WHERE i.[tipo_venta] = 'unidad' OR i.[tipo_venta] IS NULL
		GROUP BY i.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto]
	WHERE inv.[cantidad_caja_unidad] IS NOT NULL;
	
	-- Ventas por bulto: descuenta cantidad_producto de cantidad_caja_total 
	-- y cantidad_producto * cantidad_caja de cantidad_caja_unidad
	UPDATE inv
	SET 
		inv.[cantidad_caja_total] = inv.[cantidad_caja_total] - agg.[total_bultos],
		inv.[cantidad_caja_unidad] = inv.[cantidad_caja_unidad] - agg.[total_unidades]
	FROM dbo.inventario inv
	JOIN (
		SELECT 
			i.[id_producto_factura], 
			SUM(i.[cantidad_producto]) AS [total_bultos],
			SUM(i.[cantidad_producto] * COALESCE(inv.[cantidad_caja], 1)) AS [total_unidades]
		FROM inserted i
		JOIN dbo.inventario inv ON inv.[id_producto] = i.[id_producto_factura]
		WHERE i.[tipo_venta] = 'bulto'
		GROUP BY i.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto]
	WHERE inv.[cantidad_caja_unidad] IS NOT NULL;
END
GO

-- Crear trigger de DELETE para nuevo modelo
CREATE TRIGGER trg_factura_detalle_stock_del ON dbo.factura_detalle
AFTER DELETE AS
BEGIN
	SET NOCOUNT ON;
	
	-- Ventas por unidad: restaura cantidad_producto de cantidad_caja_unidad
	UPDATE inv
	SET inv.[cantidad_caja_unidad] = inv.[cantidad_caja_unidad] + agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT d.[id_producto_factura], SUM(d.[cantidad_producto]) AS [total_cant]
		FROM deleted d
		WHERE d.[tipo_venta] = 'unidad' OR d.[tipo_venta] IS NULL
		GROUP BY d.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto]
	WHERE inv.[cantidad_caja_unidad] IS NOT NULL;
	
	-- Ventas por bulto: restaura cantidad_producto de cantidad_caja_total 
	-- y cantidad_producto * cantidad_caja de cantidad_caja_unidad
	UPDATE inv
	SET 
		inv.[cantidad_caja_total] = inv.[cantidad_caja_total] + agg.[total_bultos],
		inv.[cantidad_caja_unidad] = inv.[cantidad_caja_unidad] + agg.[total_unidades]
	FROM dbo.inventario inv
	JOIN (
		SELECT 
			d.[id_producto_factura], 
			SUM(d.[cantidad_producto]) AS [total_bultos],
			SUM(d.[cantidad_producto] * COALESCE(inv.[cantidad_caja], 1)) AS [total_unidades]
		FROM deleted d
		JOIN dbo.inventario inv ON inv.[id_producto] = d.[id_producto_factura]
		WHERE d.[tipo_venta] = 'bulto'
		GROUP BY d.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto]
	WHERE inv.[cantidad_caja_unidad] IS NOT NULL;
END
GO
