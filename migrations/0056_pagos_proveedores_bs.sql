-- Agregar campos monto_bolivares y tasa_cambio a pagos_proveedores
-- Esto permite registrar pagos a proveedores en bolívares con la tasa de cambio

IF NOT EXISTS (
    SELECT 1 FROM sys.columns 
    WHERE object_id = OBJECT_ID('dbo.pagos_proveedores') 
    AND name = 'monto_bolivares'
)
BEGIN
    ALTER TABLE dbo.pagos_proveedores 
    ADD [monto_bolivares] DECIMAL(18,2) NULL;
END
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.columns 
    WHERE object_id = OBJECT_ID('dbo.pagos_proveedores') 
    AND name = 'tasa_cambio'
)
BEGIN
    ALTER TABLE dbo.pagos_proveedores 
    ADD [tasa_cambio] DECIMAL(10,2) NULL;
END
GO
