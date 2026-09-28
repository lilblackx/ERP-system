-- Agregar campos dias_credito y fecha_emision a la tabla cuentas_por_cobrar_bcv
-- Estos campos son necesarios para mostrar información completa en el módulo de cuentas por cobrar BCV

IF EXISTS (SELECT * FROM sys.tables WHERE name = 'cuentas_por_cobrar_bcv')
BEGIN
    -- Verificar si el campo dias_credito ya existe
    IF NOT EXISTS (
        SELECT * FROM sys.columns 
        WHERE object_id = OBJECT_ID('dbo.cuentas_por_cobrar_bcv') 
        AND name = 'dias_credito'
    )
    BEGIN
        ALTER TABLE dbo.cuentas_por_cobrar_bcv
        ADD dias_credito INT NULL;
        
        PRINT 'Campo dias_credito agregado a cuentas_por_cobrar_bcv.';
    END
    ELSE
    BEGIN
        PRINT 'El campo dias_credito ya existe en cuentas_por_cobrar_bcv.';
    END
    
    -- Verificar si el campo fecha_emision ya existe
    IF NOT EXISTS (
        SELECT * FROM sys.columns 
        WHERE object_id = OBJECT_ID('dbo.cuentas_por_cobrar_bcv') 
        AND name = 'fecha_emision'
    )
    BEGIN
        ALTER TABLE dbo.cuentas_por_cobrar_bcv
        ADD fecha_emision DATE NULL;
        
        PRINT 'Campo fecha_emision agregado a cuentas_por_cobrar_bcv.';
    END
    ELSE
    BEGIN
        PRINT 'El campo fecha_emision ya existe en cuentas_por_cobrar_bcv.';
    END
END
ELSE
BEGIN
    PRINT 'La tabla cuentas_por_cobrar_bcv no existe.';
END
GO

-- Actualizar registros existentes con valores predeterminados
-- Necesitamos separar esto en un batch diferente porque SQL Server no permite
-- actualizar una columna que acaba de ser agregada en el mismo batch
IF EXISTS (SELECT * FROM sys.tables WHERE name = 'cuentas_por_cobrar_bcv')
BEGIN
    IF EXISTS (
        SELECT * FROM sys.columns 
        WHERE object_id = OBJECT_ID('dbo.cuentas_por_cobrar_bcv') 
        AND name = 'fecha_emision'
    )
    BEGIN
        UPDATE dbo.cuentas_por_cobrar_bcv
        SET fecha_emision = ISNULL(fecha_emision, CAST(fecha_creacion AS DATE))
        WHERE fecha_emision IS NULL;
        
        PRINT 'Registros existentes actualizados con fecha_emision basada en fecha_creacion.';
    END
END
