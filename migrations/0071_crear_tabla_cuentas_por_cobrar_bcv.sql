-- Crear tabla cuentas_por_cobrar_bcv para manejar cuentas con porcentaje BCV
-- Esta tabla almacena cuentas por cobrar separadas cuando se aplica un porcentaje BCV
-- a los precios de los productos durante la facturación.

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'cuentas_por_cobrar_bcv')
BEGIN
    CREATE TABLE dbo.cuentas_por_cobrar_bcv (
        id_cuenta_por_cobrar INT IDENTITY(1,1) PRIMARY KEY,
        id_factura INT NOT NULL,
        saldo_pendiente DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        fecha_vencimiento DATE NULL,
        estado VARCHAR(50) NOT NULL,
        creado_por INT NOT NULL,
        fecha_creacion DATETIME NOT NULL DEFAULT GETDATE(),
        saldo_favor DECIMAL(18, 2) NULL,
        porcentaje DECIMAL(5, 2) NULL,
        
        CONSTRAINT FK_cuentas_por_cobrar_bcv_factura 
            FOREIGN KEY (id_factura) REFERENCES dbo.factura_venta(id_factura),
        CONSTRAINT FK_cuentas_por_cobrar_bcv_usuario 
            FOREIGN KEY (creado_por) REFERENCES dbo.usuarios(id_usuario),
        CONSTRAINT CK_estado_cuentas_por_cobrar_bcv 
            CHECK (estado IN ('pendiente', 'parcial', 'pagada', 'vencida'))
    );
    
    -- Índice para búsquedas por factura
    CREATE INDEX IX_cuentas_por_cobrar_bcv_factura 
        ON dbo.cuentas_por_cobrar_bcv(id_factura);
    
    -- Índice para búsquedas por estado
    CREATE INDEX IX_cuentas_por_cobrar_bcv_estado 
        ON dbo.cuentas_por_cobrar_bcv(estado);
    
    -- Índice para búsquedas por fecha de vencimiento
    CREATE INDEX IX_cuentas_por_cobrar_bcv_vencimiento 
        ON dbo.cuentas_por_cobrar_bcv(fecha_vencimiento);
        
    PRINT 'Tabla cuentas_por_cobrar_bcv creada exitosamente.';
END
ELSE
BEGIN
    PRINT 'La tabla cuentas_por_cobrar_bcv ya existe.';
END;
