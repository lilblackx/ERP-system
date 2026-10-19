-- Numero de control fiscal (factura digital, sin impresora fiscal certificada) +
-- desglose de IVA snapshoteado por factura. Mismo patron que
-- migrations/0003_correlativo_notas_credito_clientes.sql: se agrega NULL, se backfillea
-- por si ya hay filas, y despues se pasa a NOT NULL + UNIQUE.

ALTER TABLE dbo.factura_venta ADD [numero_control] VARCHAR(20) NULL;
GO

UPDATE dbo.factura_venta
SET [numero_control] = '00-' + RIGHT('00000000' + CAST([id_factura] AS VARCHAR(10)), 8)
WHERE [numero_control] IS NULL;
GO

ALTER TABLE dbo.factura_venta ALTER COLUMN [numero_control] VARCHAR(20) NOT NULL;
GO

ALTER TABLE dbo.factura_venta ADD CONSTRAINT UQ_factura_venta_numero_control UNIQUE ([numero_control]);
GO

ALTER TABLE dbo.factura_venta ADD [iva_aplicado] BIT NOT NULL CONSTRAINT DF_factura_venta_iva_aplicado DEFAULT (0);
GO

ALTER TABLE dbo.factura_venta ADD [porcentaje_iva_aplicado] DECIMAL(5,2) NOT NULL CONSTRAINT DF_factura_venta_porcentaje_iva_aplicado DEFAULT (0.00);
GO

ALTER TABLE dbo.factura_venta ADD [monto_iva] DECIMAL(18,2) NOT NULL CONSTRAINT DF_factura_venta_monto_iva DEFAULT (0.00);
GO
