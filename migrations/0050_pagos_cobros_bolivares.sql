-- Agregar campos para manejar conversiones a bolívares en pagos_cobros
-- Esto permite registrar el monto en bolívares y la tasa de cambio cuando un cliente paga

-- Agregar campos de bolívares y tasa a pagos_cobros
IF NOT EXISTS (
    SELECT * FROM sys.columns 
    WHERE object_id = OBJECT_ID('dbo.pagos_cobros') 
    AND name = 'monto_bolivares'
)
BEGIN
    ALTER TABLE dbo.pagos_cobros 
    ADD [monto_bolivares] DECIMAL(18,2) NULL;
END
GO

IF NOT EXISTS (
    SELECT * FROM sys.columns 
    WHERE object_id = OBJECT_ID('dbo.pagos_cobros') 
    AND name = 'tasa_cambio'
)
BEGIN
    ALTER TABLE dbo.pagos_cobros 
    ADD [tasa_cambio] DECIMAL(10,2) NULL;
END
GO
