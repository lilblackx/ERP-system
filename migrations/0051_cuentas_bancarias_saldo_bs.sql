-- Agregar campo saldo_total_banco_bs a cuentas_bancarias
-- Esto permite llevar el conteo de bolívares en las cuentas bancarias

IF NOT EXISTS (
    SELECT 1 FROM sys.columns 
    WHERE object_id = OBJECT_ID('dbo.cuentas_bancarias') 
    AND name = 'saldo_total_banco_bs'
)
BEGIN
    ALTER TABLE dbo.cuentas_bancarias 
    ADD [saldo_total_banco_bs] DECIMAL(18,2) NOT NULL DEFAULT 0.00;
END
GO
