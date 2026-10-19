-- Aumentar la precisión de campos numéricos para manejar valores grandes en BS
-- Esto soluciona el error de arithmetic overflow al guardar valores como 179,558,224.92

-- banco_movimientos
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.banco_movimientos') AND name = 'monto_bolivares')
BEGIN
    ALTER TABLE dbo.banco_movimientos 
    ALTER COLUMN monto_bolivares DECIMAL(20,2) NULL;
END
GO

IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.banco_movimientos') AND name = 'tasa_cambio')
BEGIN
    ALTER TABLE dbo.banco_movimientos 
    ALTER COLUMN tasa_cambio DECIMAL(18,2) NULL;
END
GO

-- pagos_cobros
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.pagos_cobros') AND name = 'monto_bolivares')
BEGIN
    ALTER TABLE dbo.pagos_cobros 
    ALTER COLUMN monto_bolivares DECIMAL(20,2) NULL;
END
GO

IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.pagos_cobros') AND name = 'tasa_cambio')
BEGIN
    ALTER TABLE dbo.pagos_cobros 
    ALTER COLUMN tasa_cambio DECIMAL(18,2) NULL;
END
GO

-- pagos_proveedores
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.pagos_proveedores') AND name = 'monto_bolivares')
BEGIN
    ALTER TABLE dbo.pagos_proveedores 
    ALTER COLUMN monto_bolivares DECIMAL(20,2) NULL;
END
GO

IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.pagos_proveedores') AND name = 'tasa_cambio')
BEGIN
    ALTER TABLE dbo.pagos_proveedores 
    ALTER COLUMN tasa_cambio DECIMAL(18,2) NULL;
END
GO

-- cuentas_bancarias
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.cuentas_bancarias') AND name = 'saldo_total_banco_bs')
BEGIN
    -- First update any NULL values to 0.00
    UPDATE dbo.cuentas_bancarias SET saldo_total_banco_bs = 0.00 WHERE saldo_total_banco_bs IS NULL;
    
    -- Then alter the column to NOT NULL
    ALTER TABLE dbo.cuentas_bancarias 
    ALTER COLUMN saldo_total_banco_bs DECIMAL(20,2) NOT NULL;
END
GO