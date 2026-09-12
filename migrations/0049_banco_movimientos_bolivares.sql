-- Agregar campos para manejar conversiones a bolívares en banco_movimientos
-- Esto permite conciliar los bancos en función a los bolívares con sus respectivas tasas

-- Agregar campos de bolívares y tasa a banco_movimientos
IF NOT EXISTS (
    SELECT * FROM sys.columns 
    WHERE object_id = OBJECT_ID('dbo.banco_movimientos') 
    AND name = 'monto_bolivares'
)
BEGIN
    ALTER TABLE dbo.banco_movimientos 
    ADD [monto_bolivares] DECIMAL(18,2) NULL;
END
GO

IF NOT EXISTS (
    SELECT * FROM sys.columns 
    WHERE object_id = OBJECT_ID('dbo.banco_movimientos') 
    AND name = 'tasa_cambio'
)
BEGIN
    ALTER TABLE dbo.banco_movimientos 
    ADD [tasa_cambio] DECIMAL(10,2) NULL;
END
GO

IF NOT EXISTS (
    SELECT * FROM sys.columns 
    WHERE object_id = OBJECT_ID('dbo.banco_movimientos') 
    AND name = 'id_tasa'
)
BEGIN
    ALTER TABLE dbo.banco_movimientos 
    ADD [id_tasa] BIGINT NULL;
END
GO

-- Agregar foreign key a control_de_tasas
IF NOT EXISTS (
    SELECT * FROM sys.foreign_keys 
    WHERE name = 'FK_banco_movimientos_id_tasa'
    AND parent_object_id = OBJECT_ID('dbo.banco_movimientos')
)
BEGIN
    ALTER TABLE dbo.banco_movimientos
    ADD CONSTRAINT FK_banco_movimientos_id_tasa FOREIGN KEY([id_tasa]) 
    REFERENCES dbo.control_de_tasas([id_tasa])
    ON UPDATE NO ACTION ON DELETE NO ACTION;
END
GO
