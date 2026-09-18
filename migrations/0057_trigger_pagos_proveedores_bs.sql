-- Actualizar trigger trg_pagos_proveedores_io para manejar monto_bolivares y tasa_cambio
-- Este trigger ahora incluirá los campos de bolívares al crear movimientos bancarios para pagos a proveedores

IF EXISTS (SELECT 1 FROM sys.triggers WHERE name = 'trg_pagos_proveedores_io' AND parent_id = OBJECT_ID('dbo.pagos_proveedores'))
BEGIN
    DECLARE @sql NVARCHAR(MAX)
    SET @sql = 'DROP TRIGGER dbo.trg_pagos_proveedores_io'
    EXEC sp_executesql @sql
END
GO

CREATE TRIGGER trg_pagos_proveedores_io ON dbo.pagos_proveedores
INSTEAD OF INSERT AS
BEGIN
	SET NOCOUNT ON;

	IF EXISTS (
		SELECT 1 FROM inserted
		WHERE ([id_cuenta_bancaria] IS NULL AND [id_caja] IS NULL)
			OR ([id_cuenta_bancaria] IS NOT NULL AND [id_caja] IS NOT NULL)
	)
	BEGIN
		RAISERROR('pagos_proveedores: indique exactamente un origen (cuenta bancaria o caja)', 16, 1);
		RETURN;
	END

	IF EXISTS (
		SELECT 1 FROM inserted i
		JOIN dbo.cuentas_por_pagar c ON c.[id_cuenta] = i.[id_cuenta_por_pagar]
		WHERE i.[monto] > c.[saldo_pendiente]
	)
	BEGIN
		RAISERROR('pagos_proveedores: el monto excede el saldo pendiente', 16, 1);
		RETURN;
	END

	DECLARE @nuevos TABLE (
		[id_pago_proveedor] BIGINT,
		[id_cuenta_por_pagar] BIGINT,
		[id_cuenta_bancaria] BIGINT,
		[id_caja] BIGINT,
		[id_tasa] BIGINT,
		[monto] DECIMAL(18,2),
		[monto_bolivares] DECIMAL(18,2),
		[tasa_cambio] DECIMAL(10,2),
		[referencia] VARCHAR(100),
		[fecha_pago] DATETIME,
		[creado_por] BIGINT
	);

	INSERT INTO dbo.pagos_proveedores ([id_cuenta_por_pagar], [id_cuenta_bancaria], [id_caja], [id_tasa], [metodo_pago], [monto], [monto_bolivares], [tasa_cambio], [referencia], [fecha_pago], [creado_por])
	OUTPUT inserted.[id_pago_proveedor], inserted.[id_cuenta_por_pagar], inserted.[id_cuenta_bancaria], inserted.[id_caja], inserted.[id_tasa], inserted.[monto], inserted.[monto_bolivares], inserted.[tasa_cambio], inserted.[referencia], inserted.[fecha_pago], inserted.[creado_por]
	INTO @nuevos
	SELECT [id_cuenta_por_pagar], [id_cuenta_bancaria], [id_caja], [id_tasa], [metodo_pago], [monto], [monto_bolivares], [tasa_cambio], [referencia], ISNULL([fecha_pago], GETDATE()), [creado_por]
	FROM inserted;

	UPDATE c
	SET c.[saldo_pendiente] = c.[saldo_pendiente] - n.[monto],
		c.[estado] = CASE WHEN c.[saldo_pendiente] - n.[monto] <= 0 THEN 'pagada' ELSE 'parcial' END
	FROM dbo.cuentas_por_pagar c
	JOIN @nuevos n ON n.[id_cuenta_por_pagar] = c.[id_cuenta];

	INSERT INTO dbo.banco_movimientos ([id_cuenta], [tipo_movimiento], [monto_movimiento], [monto_bolivares], [tasa_cambio], [id_tasa], [fecha_movimiento], [referencia_movimiento], [descripcion_movimiento], [creado_por], [fecha_creacion], [id_pago_proveedor])
	SELECT [id_cuenta_bancaria], 'cargo', [monto], [monto_bolivares], [tasa_cambio], [id_tasa], [fecha_pago], [referencia], 'Pago a proveedor', [creado_por], GETDATE(), [id_pago_proveedor]
	FROM @nuevos WHERE [id_cuenta_bancaria] IS NOT NULL;

	INSERT INTO dbo.caja_movimientos ([id_caja], [tipo_movimiento], [descripcion_movimiento], [monto_movimiento], [fecha_registro], [id_pago_proveedor], [creado_por])
	SELECT [id_caja], 'salida', 'Pago a proveedor', [monto], [fecha_pago], [id_pago_proveedor], [creado_por]
	FROM @nuevos WHERE [id_caja] IS NOT NULL;

	SELECT [id_pago_proveedor] FROM @nuevos;
END
GO