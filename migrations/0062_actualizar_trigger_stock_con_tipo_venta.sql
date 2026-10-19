-- Actualizar triggers de stock para considerar tipo_venta (bulto vs unidad)
-- Cuando tipo_venta = 'bulto', multiplica cantidad_producto por cantidad_caja del inventario
-- para obtener las unidades reales a descontar del stock

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

-- Crear trigger de INSERT con conversión de bultos a unidades
CREATE TRIGGER trg_factura_detalle_stock_ins ON dbo.factura_detalle
AFTER INSERT AS
BEGIN
	SET NOCOUNT ON;
	
	-- Ventas por unidad: descuenta cantidad_producto directamente
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] - agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT [id_producto_factura], SUM([cantidad_producto]) AS [total_cant]
		FROM inserted
		WHERE [tipo_venta] = 'unidad' OR [tipo_venta] IS NULL
		GROUP BY [id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto];
	
	-- Ventas por bulto: descuenta cantidad_producto * cantidad_caja
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] - agg.[total_cant_bultos]
	FROM dbo.inventario inv
	JOIN (
		SELECT i.[id_producto_factura], SUM(i.[cantidad_producto] * COALESCE(inv.[cantidad_caja], 1)) AS [total_cant_bultos]
		FROM inserted i
		JOIN dbo.inventario inv ON inv.[id_producto] = i.[id_producto_factura]
		WHERE i.[tipo_venta] = 'bulto'
		GROUP BY i.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto];
END
GO

-- Crear trigger de UPDATE con conversión de bultos a unidades
CREATE TRIGGER trg_factura_detalle_stock_upd ON dbo.factura_detalle
AFTER UPDATE AS
BEGIN
	SET NOCOUNT ON;
	
	-- Revertir valores anteriores (deleted)
	-- Ventas por unidad: restaura cantidad_producto
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] + agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT d.[id_producto_factura], SUM(d.[cantidad_producto]) AS [total_cant]
		FROM deleted d
		WHERE d.[tipo_venta] = 'unidad' OR d.[tipo_venta] IS NULL
		GROUP BY d.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto];
	
	-- Ventas por bulto: restaura cantidad_producto * cantidad_caja
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] + agg.[total_cant_bultos]
	FROM dbo.inventario inv
	JOIN (
		SELECT d.[id_producto_factura], SUM(d.[cantidad_producto] * COALESCE(inv.[cantidad_caja], 1)) AS [total_cant_bultos]
		FROM deleted d
		JOIN dbo.inventario inv ON inv.[id_producto] = d.[id_producto_factura]
		WHERE d.[tipo_venta] = 'bulto'
		GROUP BY d.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto];
	
	-- Aplicar nuevos valores (inserted)
	-- Ventas por unidad: descuenta cantidad_producto
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] - agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT i.[id_producto_factura], SUM(i.[cantidad_producto]) AS [total_cant]
		FROM inserted i
		WHERE i.[tipo_venta] = 'unidad' OR i.[tipo_venta] IS NULL
		GROUP BY i.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto];
	
	-- Ventas por bulto: descuenta cantidad_producto * cantidad_caja
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] - agg.[total_cant_bultos]
	FROM dbo.inventario inv
	JOIN (
		SELECT i.[id_producto_factura], SUM(i.[cantidad_producto] * COALESCE(inv.[cantidad_caja], 1)) AS [total_cant_bultos]
		FROM inserted i
		JOIN dbo.inventario inv ON inv.[id_producto] = i.[id_producto_factura]
		WHERE i.[tipo_venta] = 'bulto'
		GROUP BY i.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto];
END
GO

-- Crear trigger de DELETE con conversión de bultos a unidades
CREATE TRIGGER trg_factura_detalle_stock_del ON dbo.factura_detalle
AFTER DELETE AS
BEGIN
	SET NOCOUNT ON;
	
	-- Ventas por unidad: restaura cantidad_producto
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] + agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT d.[id_producto_factura], SUM(d.[cantidad_producto]) AS [total_cant]
		FROM deleted d
		WHERE d.[tipo_venta] = 'unidad' OR d.[tipo_venta] IS NULL
		GROUP BY d.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto];
	
	-- Ventas por bulto: restaura cantidad_producto * cantidad_caja
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] + agg.[total_cant_bultos]
	FROM dbo.inventario inv
	JOIN (
		SELECT d.[id_producto_factura], SUM(d.[cantidad_producto] * COALESCE(inv.[cantidad_caja], 1)) AS [total_cant_bultos]
		FROM deleted d
		JOIN dbo.inventario inv ON inv.[id_producto] = d.[id_producto_factura]
		WHERE d.[tipo_venta] = 'bulto'
		GROUP BY d.[id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto];
END
GO
