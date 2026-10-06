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
