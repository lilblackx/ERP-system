-- Una factura de compra hecha desde una OC (CompraService.crear_compra_desde_oc) sube
-- compra_oc_detalle.cantidad_facturada, pero compra_detalle solo guardaba el producto, no
-- de que LINEA de la OC salio. Sin ese vinculo, anular la factura no podia devolverle la
-- cantidad a la linea correcta (una OC puede traer el mismo producto en varias lineas) y la
-- OC quedaba marcada como facturada para siempre: no se podia volver a facturar.

IF COL_LENGTH('dbo.compra_detalle', 'id_oc_detalle') IS NULL
BEGIN
	ALTER TABLE dbo.compra_detalle ADD [id_oc_detalle] BIGINT NULL;
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_compra_detalle_oc_detalle')
BEGIN
	ALTER TABLE dbo.compra_detalle
	ADD CONSTRAINT FK_compra_detalle_oc_detalle
		FOREIGN KEY ([id_oc_detalle]) REFERENCES dbo.compra_oc_detalle([id_detalle]);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_compra_detalle_oc_detalle' AND object_id = OBJECT_ID('dbo.compra_detalle'))
BEGIN
	CREATE INDEX IX_compra_detalle_oc_detalle ON dbo.compra_detalle ([id_oc_detalle]);
END
GO

-- Backfill de las facturas ya registradas: solo donde el vinculo es inequivoco (la OC
-- tiene UNA sola linea de ese producto). Las ambiguas quedan NULL; el servicio las
-- resuelve al anular repartiendo sobre las lineas del mismo producto con lo facturado.
UPDATE cd
SET cd.[id_oc_detalle] = x.[id_detalle]
FROM dbo.compra_detalle cd
JOIN dbo.compras c ON c.[id_compra] = cd.[id_compra]
JOIN (
	SELECT [id_oc], [id_producto], MIN([id_detalle]) AS [id_detalle]
	FROM dbo.compra_oc_detalle
	GROUP BY [id_oc], [id_producto]
	HAVING COUNT(*) = 1
) x ON x.[id_oc] = c.[id_oc] AND x.[id_producto] = cd.[id_producto_compra]
WHERE c.[id_oc] IS NOT NULL
	AND cd.[stock_ya_contabilizado] = 1
	AND cd.[id_oc_detalle] IS NULL;
GO
