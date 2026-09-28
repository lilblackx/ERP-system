-- Actualizar trigger trg_pagos_cobros_io para incluir el nombre del cliente en la descripción de movimientos de caja
-- Esto permite ver en el historial de movimientos de caja qué cliente realizó el pago o recibió vuelto

-- Eliminar el trigger existente
IF OBJECT_ID('dbo.trg_pagos_cobros_io', 'TR') IS NOT NULL
BEGIN
    DROP TRIGGER dbo.trg_pagos_cobros_io;
END
GO

-- Crear el trigger actualizado con el nombre del cliente en la descripción
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
		[id_tasa] BIGINT,
		[monto] DECIMAL(18,2),
		[monto_bolivares] DECIMAL(18,2),
		[tasa_cambio] DECIMAL(10,2),
		[referencia] VARCHAR(100),
		[fecha_pago] DATETIME,
		[creado_por] BIGINT
	);

	INSERT INTO dbo.pagos_cobros ([id_cuenta_por_cobrar], [id_cuenta_bancaria], [id_caja], [id_tasa], [metodo_pago], [moneda], [monto], [monto_moneda_origen], [monto_bolivares], [tasa_cambio], [referencia], [fecha_pago], [creado_por])
	OUTPUT inserted.[id_pago_cobro], inserted.[id_cuenta_por_cobrar], inserted.[id_cuenta_bancaria], inserted.[id_caja], inserted.[id_tasa], inserted.[monto], inserted.[monto_bolivares], inserted.[tasa_cambio], inserted.[referencia], inserted.[fecha_pago], inserted.[creado_por]
	INTO @nuevos
	SELECT [id_cuenta_por_cobrar], [id_cuenta_bancaria], [id_caja], [id_tasa], [metodo_pago], [moneda], [monto], [monto_moneda_origen], [monto_bolivares], [tasa_cambio], [referencia], ISNULL([fecha_pago], GETDATE()), [creado_por]
	FROM inserted;

	UPDATE c
	SET c.[saldo_pendiente] = c.[saldo_pendiente] - n.[monto],
		c.[estado] = CASE WHEN c.[saldo_pendiente] - n.[monto] <= 0 THEN 'pagada' ELSE 'parcial' END
	FROM dbo.cuentas_por_cobrar c
	JOIN @nuevos n ON n.[id_cuenta_por_cobrar] = c.[id_cuenta_por_cobrar];

	-- Insertar movimientos de banco con nombre del cliente
	INSERT INTO dbo.banco_movimientos ([id_cuenta], [tipo_movimiento], [monto_movimiento], [monto_bolivares], [tasa_cambio], [id_tasa], [fecha_movimiento], [referencia_movimiento], [descripcion_movimiento], [creado_por], [fecha_creacion], [id_pago_cobro])
	SELECT
		[id_cuenta_bancaria],
		'abono',
		[monto],
		[monto_bolivares],
		[tasa_cambio],
		[id_tasa],
		[fecha_pago],
		[referencia],
		'Cobro a cliente: ' + COALESCE(cl.nombre_razon_social, 'Desconocido'),
		[creado_por],
		GETDATE(),
		[id_pago_cobro]
	FROM @nuevos n
	JOIN dbo.cuentas_por_cobrar cxc ON cxc.[id_cuenta_por_cobrar] = n.[id_cuenta_por_cobrar]
	JOIN dbo.factura_venta fv ON fv.[id_factura] = cxc.[id_factura]
	JOIN dbo.clientes cl ON cl.[id_cliente] = fv.[id_cliente_factura]
	WHERE [id_cuenta_bancaria] IS NOT NULL;

	-- Insertar movimientos de caja con nombre del cliente
	INSERT INTO dbo.caja_movimientos ([id_caja], [tipo_movimiento], [descripcion_movimiento], [monto_movimiento], [fecha_registro], [id_pago_cobro], [creado_por])
	SELECT
		[id_caja],
		'entrada',
		'Cobro a cliente: ' + COALESCE(cl.nombre_razon_social, 'Desconocido'),
		[monto],
		[fecha_pago],
		[id_pago_cobro],
		[creado_por]
	FROM @nuevos n
	JOIN dbo.cuentas_por_cobrar cxc ON cxc.[id_cuenta_por_cobrar] = n.[id_cuenta_por_cobrar]
	JOIN dbo.factura_venta fv ON fv.[id_factura] = cxc.[id_factura]
	JOIN dbo.clientes cl ON cl.[id_cliente] = fv.[id_cliente_factura]
	WHERE [id_caja] IS NOT NULL;

	-- Un INSTEAD OF INSERT reemplaza el INSERT del caller: SCOPE_IDENTITY() no ve el
	-- id generado aqui adentro (es un scope distinto) y @@IDENTITY devolveria el de
	-- banco_movimientos/caja_movimientos (insertados despues). Este SELECT final es
	-- el unico resultset no vacio que llega al cliente antes del "select
	-- scope_identity()" que SQLAlchemy agrega automaticamente, asi que su primera fila
	-- es la que SQLAlchemy toma como id autogenerado — permite usar
	-- session.add(PagoCobro(...)); session.commit() de forma normal, igual que en el
	-- resto de los servicios.
	SELECT [id_pago_cobro] FROM @nuevos;
END
GO
