-- Corregir tipos de datos en tabla cuentas_por_cobrar_bcv
-- Esta migración corrige el problema donde la tabla fue creada con INT en lugar de BIGINT
-- para las columnas id_cuenta_por_cobrar, id_factura, y creado_por, lo que causaba
-- errores de incompatibilidad de tipos con las foreign keys.

IF EXISTS (SELECT * FROM sys.tables WHERE name = 'cuentas_por_cobrar_bcv')
BEGIN
    -- Verificar si las columnas tienen el tipo incorrecto (INT en lugar de BIGINT)
    DECLARE @id_cuenta_tipo VARCHAR(50)
    DECLARE @id_factura_tipo VARCHAR(50)
    DECLARE @creado_por_tipo VARCHAR(50)
    
    SELECT @id_cuenta_tipo = DATA_TYPE
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'cuentas_por_cobrar_bcv' AND COLUMN_NAME = 'id_cuenta_por_cobrar'
    
    SELECT @id_factura_tipo = DATA_TYPE
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'cuentas_por_cobrar_bcv' AND COLUMN_NAME = 'id_factura'
    
    SELECT @creado_por_tipo = DATA_TYPE
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'cuentas_por_cobrar_bcv' AND COLUMN_NAME = 'creado_por'
    
    -- Si alguna columna tiene el tipo incorrecto, proceder con la corrección
    IF @id_cuenta_tipo = 'int' OR @id_factura_tipo = 'int' OR @creado_por_tipo = 'int'
    BEGIN
        PRINT 'Detectados tipos de datos incorrectos en cuentas_por_cobrar_bcv. Iniciando corrección...';
        
        -- Eliminar foreign key constraints si existen
        IF EXISTS (SELECT * FROM sys.foreign_keys WHERE name = 'FK_cuentas_por_cobrar_bcv_factura')
        BEGIN
            ALTER TABLE dbo.cuentas_por_cobrar_bcv DROP CONSTRAINT FK_cuentas_por_cobrar_bcv_factura;
            PRINT 'Constraint FK_cuentas_por_cobrar_bcv_factura eliminada.';
        END
        
        IF EXISTS (SELECT * FROM sys.foreign_keys WHERE name = 'FK_cuentas_por_cobrar_bcv_usuario')
        BEGIN
            ALTER TABLE dbo.cuentas_por_cobrar_bcv DROP CONSTRAINT FK_cuentas_por_cobrar_bcv_usuario;
            PRINT 'Constraint FK_cuentas_por_cobrar_bcv_usuario eliminada.';
        END
        
        -- Eliminar índices que dependen de las columnas
        IF EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_cuentas_por_cobrar_bcv_factura' AND object_id = OBJECT_ID('dbo.cuentas_por_cobrar_bcv'))
        BEGIN
            DROP INDEX IX_cuentas_por_cobrar_bcv_factura ON dbo.cuentas_por_cobrar_bcv;
            PRINT 'Índice IX_cuentas_por_cobrar_bcv_factura eliminado.';
        END
        
        IF EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_cuentas_por_cobrar_bcv_estado' AND object_id = OBJECT_ID('dbo.cuentas_por_cobrar_bcv'))
        BEGIN
            DROP INDEX IX_cuentas_por_cobrar_bcv_estado ON dbo.cuentas_por_cobrar_bcv;
            PRINT 'Índice IX_cuentas_por_cobrar_bcv_estado eliminado.';
        END
        
        IF EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_cuentas_por_cobrar_bcv_vencimiento' AND object_id = OBJECT_ID('dbo.cuentas_por_cobrar_bcv'))
        BEGIN
            DROP INDEX IX_cuentas_por_cobrar_bcv_vencimiento ON dbo.cuentas_por_cobrar_bcv;
            PRINT 'Índice IX_cuentas_por_cobrar_bcv_vencimiento eliminado.';
        END
        
        -- Cambiar tipo de id_cuenta_por_cobrar (requiere recrear la PK)
        IF @id_cuenta_tipo = 'int'
        BEGIN
            ALTER TABLE dbo.cuentas_por_cobrar_bcv DROP CONSTRAINT PK_cuentas_por_cobrar_bcv;
            PRINT 'Primary key eliminada para modificar id_cuenta_por_cobrar.';
            
            ALTER TABLE dbo.cuentas_por_cobrar_bcv ALTER COLUMN id_cuenta_por_cobrar BIGINT NOT NULL;
            PRINT 'Columna id_cuenta_por_cobrar cambiada a BIGINT.';
            
            ALTER TABLE dbo.cuentas_por_cobrar_bcv ADD CONSTRAINT PK_cuentas_por_cobrar_bcv PRIMARY KEY (id_cuenta_por_cobrar);
            PRINT 'Primary key recreada.';
        END
        
        -- Cambiar tipo de id_factura
        IF @id_factura_tipo = 'int'
        BEGIN
            ALTER TABLE dbo.cuentas_por_cobrar_bcv ALTER COLUMN id_factura BIGINT NOT NULL;
            PRINT 'Columna id_factura cambiada a BIGINT.';
        END
        
        -- Cambiar tipo de creado_por
        IF @creado_por_tipo = 'int'
        BEGIN
            ALTER TABLE dbo.cuentas_por_cobrar_bcv ALTER COLUMN creado_por BIGINT NOT NULL;
            PRINT 'Columna creado_por cambiada a BIGINT.';
        END
        
        -- Recrear foreign key constraints
        ALTER TABLE dbo.cuentas_por_cobrar_bcv
        ADD CONSTRAINT FK_cuentas_por_cobrar_bcv_factura 
            FOREIGN KEY (id_factura) REFERENCES dbo.factura_venta(id_factura);
        PRINT 'Constraint FK_cuentas_por_cobrar_bcv_factura recreada.';
        
        ALTER TABLE dbo.cuentas_por_cobrar_bcv
        ADD CONSTRAINT FK_cuentas_por_cobrar_bcv_usuario 
            FOREIGN KEY (creado_por) REFERENCES dbo.usuarios(id_usuario);
        PRINT 'Constraint FK_cuentas_por_cobrar_bcv_usuario recreada.';
        
        -- Recrear índices
        CREATE INDEX IX_cuentas_por_cobrar_bcv_factura 
            ON dbo.cuentas_por_cobrar_bcv(id_factura);
        PRINT 'Índice IX_cuentas_por_cobrar_bcv_factura recreado.';
        
        CREATE INDEX IX_cuentas_por_cobrar_bcv_estado 
            ON dbo.cuentas_por_cobrar_bcv(estado);
        PRINT 'Índice IX_cuentas_por_cobrar_bcv_estado recreado.';
        
        CREATE INDEX IX_cuentas_por_cobrar_bcv_vencimiento 
            ON dbo.cuentas_por_cobrar_bcv(fecha_vencimiento);
        PRINT 'Índice IX_cuentas_por_cobrar_bcv_vencimiento recreado.';
        
        PRINT 'Corrección de tipos de datos completada exitosamente.';
    END
    ELSE
    BEGIN
        PRINT 'Los tipos de datos en cuentas_por_cobrar_bcv ya son correctos (BIGINT). No se requiere corrección.';
    END
END
ELSE
BEGIN
    PRINT 'La tabla cuentas_por_cobrar_bcv no existe. Esta migración no hace nada.';
END
GO
