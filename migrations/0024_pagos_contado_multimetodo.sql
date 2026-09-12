-- Permite que una factura de CONTADO tambien abra y liquide una cuenta por cobrar en la
-- misma transaccion (antes solo credito abria cuenta por cobrar), y agrega soporte de
-- multiples formas de pago / monedas por factura de contado (VES, COP, USDT ademas de
-- USD) en pagos_cobros. Ver docs/ESTADO_DEL_PROYECTO.md seccion 3 y CLAUDE.md.

ALTER TABLE dbo.pagos_cobros
ADD [moneda] VARCHAR(10) NOT NULL CONSTRAINT DF_pagos_cobros_moneda DEFAULT 'USD';
GO

ALTER TABLE dbo.pagos_cobros
ADD CONSTRAINT CK_pagos_cobros_moneda CHECK ([moneda] IN ('USD','VES','COP','USDT'));
GO

ALTER TABLE dbo.pagos_cobros
ADD [monto_moneda_origen] DECIMAL(18,2) NULL;
GO

ALTER TABLE dbo.pagos_cobros
DROP CONSTRAINT CK_pagos_cobros_metodo;
GO

ALTER TABLE dbo.pagos_cobros
ADD CONSTRAINT CK_pagos_cobros_metodo CHECK ([metodo_pago] IN ('efectivo','transferencia','cheque','tarjeta','punto_de_venta','zelle','binance'));
GO

DROP TRIGGER trg_factura_venta_cxc;
GO

-- Identico al original salvo que ya no restringe la apertura/actualizacion de la cuenta
-- por cobrar a condicion_pago = 'credito': una factura de contado tambien pasa por aca
-- (se abre y se liquida con pagos_cobros en la misma transaccion, ver VentaService.
-- emitir_factura). El trigger solo reacciona a un cambio de total_venta, igual que antes.
CREATE TRIGGER trg_factura_venta_cxc ON dbo.factura_venta
AFTER UPDATE AS
BEGIN
	SET NOCOUNT ON;

	INSERT INTO dbo.cuentas_por_cobrar ([id_factura], [saldo_pendiente], [fecha_vencimiento], [estado], [creado_por], [fecha_creacion])
	SELECT i.[id_factura], i.[total_venta], i.[fecha_vencimiento], 'pendiente', i.[id_usuario_factura], GETDATE()
	FROM inserted i
	JOIN deleted d ON d.[id_factura] = i.[id_factura]
	WHERE i.[total_venta] <> d.[total_venta]
		AND NOT EXISTS (SELECT 1 FROM dbo.cuentas_por_cobrar c WHERE c.[id_factura] = i.[id_factura]);

	UPDATE c
	SET c.[saldo_pendiente] = i.[total_venta]
	FROM dbo.cuentas_por_cobrar c
	JOIN inserted i ON i.[id_factura] = c.[id_factura]
	JOIN deleted d ON d.[id_factura] = i.[id_factura]
	WHERE i.[total_venta] <> d.[total_venta]
		AND c.[estado] = 'pendiente';
END
GO

DROP TRIGGER trg_pagos_cobros_io;
GO

-- Identico al original salvo que ahora tambien propaga [moneda]/[monto_moneda_origen]
-- (el INSTEAD OF INSERT original solo copiaba las columnas que existian antes de este
-- migration -- sin esto, esas dos columnas nuevas se quedarian siempre en su DEFAULT sin
-- importar lo que el caller intente insertar, ver PagoService._aplicar_pago_cobro).
CREATE TRIGGER trg_pagos_cobros_io ON dbo.pagos_cobros
INSTEAD OF INSERT AS
BEGIN
	SET NOCOUNT ON;

	IF EXISTS (
		SELECT 1 FROM inserted
		WHERE ([id_cuenta_bancaria] IS NULL AND [id_caja] IS NULL)
			OR ([id_cuenta_bancaria] IS NOT NULL AND [id_caja] IS NOT NULL)
	)
	BEGIN
		RAISERROR('pagos_cobros: indique exactamente un origen (cuenta bancaria o caja)', 16, 1);
		RETURN;
	END

	IF EXISTS (
		SELECT 1 FROM inserted i
		JOIN dbo.cuentas_por_cobrar c ON c.[id_cuenta_por_cobrar] = i.[id_cuenta_por_cobrar]
		WHERE i.[monto] > c.[saldo_pendiente]
	)
	BEGIN
		RAISERROR('pagos_cobros: el monto excede el saldo pendiente', 16, 1);
		RETURN;
	END

	DECLARE @nuevos TABLE (
		[id_pago_cobro] BIGINT,
		[id_cuenta_por_cobrar] BIGINT,
		[id_cuenta_bancaria] BIGINT,
		[id_caja] BIGINT,
		[monto] DECIMAL(18,2),
		[referencia] VARCHAR(100),
		[fecha_pago] DATETIME,
		[creado_por] BIGINT
	);

	INSERT INTO dbo.pagos_cobros ([id_cuenta_por_cobrar], [id_cuenta_bancaria], [id_caja], [id_tasa], [metodo_pago], [moneda], [monto], [monto_moneda_origen], [referencia], [fecha_pago], [creado_por])
	OUTPUT inserted.[id_pago_cobro], inserted.[id_cuenta_por_cobrar], inserted.[id_cuenta_bancaria], inserted.[id_caja], inserted.[monto], inserted.[referencia], inserted.[fecha_pago], inserted.[creado_por]
	INTO @nuevos
	SELECT [id_cuenta_por_cobrar], [id_cuenta_bancaria], [id_caja], [id_tasa], [metodo_pago], [moneda], [monto], [monto_moneda_origen], [referencia], ISNULL([fecha_pago], GETDATE()), [creado_por]
	FROM inserted;

	UPDATE c
	SET c.[saldo_pendiente] = c.[saldo_pendiente] - n.[monto],
		c.[estado] = CASE WHEN c.[saldo_pendiente] - n.[monto] <= 0 THEN 'pagada' ELSE 'parcial' END
	FROM dbo.cuentas_por_cobrar c
	JOIN @nuevos n ON n.[id_cuenta_por_cobrar] = c.[id_cuenta_por_cobrar];

	INSERT INTO dbo.banco_movimientos ([id_cuenta], [tipo_movimiento], [monto_movimiento], [fecha_movimiento], [referencia_movimiento], [descripcion_movimiento], [creado_por], [fecha_creacion], [id_pago_cobro])
	SELECT [id_cuenta_bancaria], 'abono', [monto], [fecha_pago], [referencia], 'Cobro a cliente', [creado_por], GETDATE(), [id_pago_cobro]
	FROM @nuevos WHERE [id_cuenta_bancaria] IS NOT NULL;

	INSERT INTO dbo.caja_movimientos ([id_caja], [tipo_movimiento], [descripcion_movimiento], [monto_movimiento], [fecha_registro], [id_pago_cobro], [creado_por])
	SELECT [id_caja], 'entrada', 'Cobro a cliente', [monto], [fecha_pago], [id_pago_cobro], [creado_por]
	FROM @nuevos WHERE [id_caja] IS NOT NULL;

	-- Ver el comentario equivalente en trg_pagos_cobros_io original (schema_sqlserver.sql)
	-- sobre por que este SELECT final es necesario para que SQLAlchemy pueda leer el id
	-- autogenerado con session.add(...) + flush()/commit().
	SELECT [id_pago_cobro] FROM @nuevos;
END
GO
