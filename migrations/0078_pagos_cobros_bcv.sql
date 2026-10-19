-- Pagos de cuentas por cobrar BCV (cuentas_por_cobrar_bcv).
--
-- Hasta ahora un pago contra una cuenta BCV solo le restaba saldo a la cuenta: no dejaba
-- ninguna fila de pago, no sumaba nada a la caja/cuenta bancaria de destino y por eso
-- tampoco aparecia en el historial del cliente. trg_pagos_cobros_io (que hace todo eso para
-- las cuentas normales) no sirve aca: valida contra y descuenta de cuentas_por_cobrar, no de
-- cuentas_por_cobrar_bcv. En vez de reescribir ese trigger, los pagos BCV tienen su propia
-- tabla y PagoBCVService (app/services/pagos_bcv.py) inserta el ingreso en caja/banco.
--
--   pagos_cobros_bcv                     un pago aplicado a una cuenta BCV (mismas columnas utiles
--                                        que pagos_cobros: monto en USD, Bs, tasa, origen)
--   banco_movimientos/caja_movimientos   id_pago_cobro_bcv: de que pago BCV viene el movimiento,
--                                        para mostrarlo como "Cliente" y no como "Manual"

-- Reparacion previa: cuentas_por_cobrar_bcv con columnas INT en vez de BIGINT.
--
-- La 0071 se creo primero con INT y despues se edito a BIGINT; las bases que aplicaron la
-- version vieja quedaron en INT y la 0073 debia corregirlas. Pero la 0073 asumia que la PK se
-- llamaba PK_cuentas_por_cobrar_bcv cuando es anonima (nombre generado por SQL Server), el
-- DROP CONSTRAINT fallaba sin que el runner se enterara, la 0073 quedaba registrada como
-- aplicada y la tabla seguia en INT. Aca la FK de pagos_cobros_bcv no se puede crear contra
-- una columna INT, asi que se repara antes. Es idempotente y no hace nada si ya esta en
-- BIGINT: tolera tambien un estado intermedio (FKs o indices ya borrados o ya recreados).
IF OBJECT_ID(N'dbo.cuentas_por_cobrar_bcv', N'U') IS NOT NULL
AND EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'cuentas_por_cobrar_bcv'
      AND COLUMN_NAME IN ('id_cuenta_por_cobrar', 'id_factura', 'creado_por')
      AND DATA_TYPE = 'int'
)
BEGIN
    IF EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_cuentas_por_cobrar_bcv_factura')
        ALTER TABLE dbo.cuentas_por_cobrar_bcv DROP CONSTRAINT FK_cuentas_por_cobrar_bcv_factura;

    IF EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_cuentas_por_cobrar_bcv_usuario')
        ALTER TABLE dbo.cuentas_por_cobrar_bcv DROP CONSTRAINT FK_cuentas_por_cobrar_bcv_usuario;

    IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_cuentas_por_cobrar_bcv_factura' AND object_id = OBJECT_ID('dbo.cuentas_por_cobrar_bcv'))
        DROP INDEX IX_cuentas_por_cobrar_bcv_factura ON dbo.cuentas_por_cobrar_bcv;

    IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_cuentas_por_cobrar_bcv_estado' AND object_id = OBJECT_ID('dbo.cuentas_por_cobrar_bcv'))
        DROP INDEX IX_cuentas_por_cobrar_bcv_estado ON dbo.cuentas_por_cobrar_bcv;

    IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_cuentas_por_cobrar_bcv_vencimiento' AND object_id = OBJECT_ID('dbo.cuentas_por_cobrar_bcv'))
        DROP INDEX IX_cuentas_por_cobrar_bcv_vencimiento ON dbo.cuentas_por_cobrar_bcv;

    IF EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'cuentas_por_cobrar_bcv'
          AND COLUMN_NAME = 'id_cuenta_por_cobrar' AND DATA_TYPE = 'int'
    )
    BEGIN
        DECLARE @pk_nombre SYSNAME = (
            SELECT name FROM sys.key_constraints
            WHERE parent_object_id = OBJECT_ID('dbo.cuentas_por_cobrar_bcv') AND type = 'PK'
        );
        DECLARE @pk_sql NVARCHAR(400) = N'ALTER TABLE dbo.cuentas_por_cobrar_bcv DROP CONSTRAINT ' + QUOTENAME(@pk_nombre);
        EXEC (@pk_sql);
        ALTER TABLE dbo.cuentas_por_cobrar_bcv ALTER COLUMN id_cuenta_por_cobrar BIGINT NOT NULL;
        ALTER TABLE dbo.cuentas_por_cobrar_bcv ADD CONSTRAINT PK_cuentas_por_cobrar_bcv PRIMARY KEY (id_cuenta_por_cobrar);
    END

    IF EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'cuentas_por_cobrar_bcv'
          AND COLUMN_NAME = 'id_factura' AND DATA_TYPE = 'int'
    )
        ALTER TABLE dbo.cuentas_por_cobrar_bcv ALTER COLUMN id_factura BIGINT NOT NULL;

    IF EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'cuentas_por_cobrar_bcv'
          AND COLUMN_NAME = 'creado_por' AND DATA_TYPE = 'int'
    )
        ALTER TABLE dbo.cuentas_por_cobrar_bcv ALTER COLUMN creado_por BIGINT NOT NULL;

    ALTER TABLE dbo.cuentas_por_cobrar_bcv
    ADD CONSTRAINT FK_cuentas_por_cobrar_bcv_factura
        FOREIGN KEY (id_factura) REFERENCES dbo.factura_venta(id_factura);

    ALTER TABLE dbo.cuentas_por_cobrar_bcv
    ADD CONSTRAINT FK_cuentas_por_cobrar_bcv_usuario
        FOREIGN KEY (creado_por) REFERENCES dbo.usuarios(id_usuario);

    CREATE INDEX IX_cuentas_por_cobrar_bcv_factura ON dbo.cuentas_por_cobrar_bcv(id_factura);
    CREATE INDEX IX_cuentas_por_cobrar_bcv_estado ON dbo.cuentas_por_cobrar_bcv(estado);
    CREATE INDEX IX_cuentas_por_cobrar_bcv_vencimiento ON dbo.cuentas_por_cobrar_bcv(fecha_vencimiento);
END
GO

IF OBJECT_ID(N'dbo.pagos_cobros_bcv', N'U') IS NULL
BEGIN
	CREATE TABLE dbo.pagos_cobros_bcv (
		[id_pago_cobro_bcv] BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_pagos_cobros_bcv PRIMARY KEY,
		[id_cuenta_por_cobrar] BIGINT NOT NULL
			CONSTRAINT FK_pagos_cobros_bcv_cuenta REFERENCES dbo.cuentas_por_cobrar_bcv([id_cuenta_por_cobrar]),
		[id_cuenta_bancaria] BIGINT NULL
			CONSTRAINT FK_pagos_cobros_bcv_cuenta_bancaria REFERENCES dbo.cuentas_bancarias([id_cuenta]),
		[id_caja] BIGINT NULL
			CONSTRAINT FK_pagos_cobros_bcv_caja REFERENCES dbo.cajas([id_caja]),
		[id_tasa] BIGINT NULL
			CONSTRAINT FK_pagos_cobros_bcv_tasa REFERENCES dbo.control_de_tasas([id_tasa]),
		[metodo_pago] VARCHAR(20) NOT NULL
			CONSTRAINT CK_pagos_cobros_bcv_metodo CHECK ([metodo_pago] IN ('efectivo','transferencia','cheque','tarjeta','punto_de_venta','zelle','binance')),
		[moneda] VARCHAR(10) NOT NULL CONSTRAINT DF_pagos_cobros_bcv_moneda DEFAULT 'USD',
		[monto] DECIMAL(18,2) NOT NULL CONSTRAINT CK_pagos_cobros_bcv_monto CHECK ([monto] > 0),
		[monto_moneda_origen] DECIMAL(18,2) NULL,
		[monto_bolivares] DECIMAL(20,2) NULL,
		[tasa_cambio] DECIMAL(18,2) NULL,
		[referencia] VARCHAR(100) NULL,
		[fecha_pago] DATETIME NOT NULL CONSTRAINT DF_pagos_cobros_bcv_fecha DEFAULT GETDATE(),
		[creado_por] BIGINT NULL
			CONSTRAINT FK_pagos_cobros_bcv_creado_por REFERENCES dbo.usuarios([id_usuario]),
		CONSTRAINT CK_pagos_cobros_bcv_origen CHECK (
			([id_cuenta_bancaria] IS NULL AND [id_caja] IS NOT NULL)
			OR ([id_cuenta_bancaria] IS NOT NULL AND [id_caja] IS NULL)
		)
	);
END
GO

IF COL_LENGTH('dbo.banco_movimientos', 'id_pago_cobro_bcv') IS NULL
	ALTER TABLE dbo.banco_movimientos ADD [id_pago_cobro_bcv] BIGINT NULL
		CONSTRAINT FK_banco_movimientos_pago_cobro_bcv REFERENCES dbo.pagos_cobros_bcv([id_pago_cobro_bcv]);
GO

IF COL_LENGTH('dbo.caja_movimientos', 'id_pago_cobro_bcv') IS NULL
	ALTER TABLE dbo.caja_movimientos ADD [id_pago_cobro_bcv] BIGINT NULL
		CONSTRAINT FK_caja_movimientos_pago_cobro_bcv REFERENCES dbo.pagos_cobros_bcv([id_pago_cobro_bcv]);
GO
