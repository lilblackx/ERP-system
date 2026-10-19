-- Agregar campo tipo_venta a factura_detalle para distinguir entre venta por bulto y venta por unidad
-- Esto permite que el trigger de stock descuentes correctamente (bulto = cantidad_caja unidades)

IF NOT EXISTS (
	SELECT 1 FROM sys.columns
	WHERE object_id = OBJECT_ID('dbo.factura_detalle')
	AND name = 'tipo_venta'
)
BEGIN
	ALTER TABLE dbo.factura_detalle
	ADD [tipo_venta] VARCHAR(10) NULL CONSTRAINT CK_factura_detalle_tipo_venta CHECK ([tipo_venta] IN ('bulto','unidad'));
END
GO
