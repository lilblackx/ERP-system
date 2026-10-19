-- C14 (parte 2/3): pago real de comisiones a vendedores. monto_comision es la diferencia
-- (nunca negativa) entre lo que el vendedor cobro y el precio de lista del producto -- ver
-- ComisionService.calcular_comisiones_factura (app/services/comisiones.py). id_vendedor se
-- denormaliza desde factura_venta.id_vendedor al momento del calculo para no tener que
-- hacer join de 2 saltos (comisiones_factura -> factura_detalle -> factura_venta) en cada
-- consulta de "comisiones pendientes de vendedor X".

ALTER TABLE dbo.comisiones_factura ADD [id_vendedor] BIGINT NULL;
GO

UPDATE cf
SET cf.[id_vendedor] = fv.[id_vendedor]
FROM dbo.comisiones_factura cf
JOIN dbo.factura_detalle fd ON fd.[id_factura_detalle] = cf.[id_factura_detalle]
JOIN dbo.factura_venta fv ON fv.[id_factura] = fd.[id_factura]
WHERE cf.[id_vendedor] IS NULL;
GO

ALTER TABLE dbo.comisiones_factura ADD [monto_comision] DECIMAL(18,2) NULL;
GO

-- Backfill defensivo por si algun entorno ya tiene filas (hoy nada las puebla, pero la
-- migracion debe ser segura igual): monto_comision = max(0, venta - base), la misma regla
-- que aplicara ComisionService de aqui en adelante.
UPDATE dbo.comisiones_factura
SET [monto_comision] = CASE
	WHEN [monto_venta_comision] IS NULL OR [monto_base_comision] IS NULL THEN 0.00
	WHEN [monto_venta_comision] - [monto_base_comision] > 0 THEN [monto_venta_comision] - [monto_base_comision]
	ELSE 0.00
END
WHERE [monto_comision] IS NULL;
GO

ALTER TABLE dbo.comisiones_factura ALTER COLUMN [monto_comision] DECIMAL(18,2) NOT NULL;
GO

IF OBJECT_ID(N'dbo.pagos_comisiones', N'U') IS NULL
BEGIN
CREATE TABLE dbo.pagos_comisiones ( -- Pago real de comisiones acumuladas a un vendedor: mismo espiritu que pagos_proveedores, pero paga un batch de comisiones_factura pendientes en una sola operacion (no hay saldo_pendiente parcial que proteger con un trigger INSTEAD OF INSERT, ver nota en PagoComisionService).
	[id_pago_comision] BIGINT IDENTITY(1,1) NOT NULL,
	[id_vendedor] BIGINT NOT NULL,
	[id_cuenta_bancaria] BIGINT NULL,
	[id_caja] BIGINT NULL,
	[metodo_pago] VARCHAR(20) NOT NULL CONSTRAINT CK_pagos_comisiones_metodo CHECK ([metodo_pago] IN ('efectivo','transferencia','cheque','tarjeta','punto_de_venta')),
	[monto] DECIMAL(18,2) NOT NULL CONSTRAINT CK_pagos_comisiones_monto_positivo CHECK ([monto] > 0),
	[referencia] VARCHAR(100) NULL,
	[fecha_pago] DATETIME NOT NULL DEFAULT GETDATE(),
	[creado_por] BIGINT NULL,
	CONSTRAINT PK_pagos_comisiones PRIMARY KEY ([id_pago_comision]),
	CONSTRAINT CK_pagos_comisiones_origen CHECK (
		([id_cuenta_bancaria] IS NOT NULL AND [id_caja] IS NULL) OR
		([id_cuenta_bancaria] IS NULL AND [id_caja] IS NOT NULL)
	)
);
END
GO

ALTER TABLE dbo.comisiones_factura ADD [id_pago_comision] BIGINT NULL;
GO

ALTER TABLE dbo.banco_movimientos ADD [id_pago_comision] BIGINT NULL;
GO

ALTER TABLE dbo.caja_movimientos ADD [id_pago_comision] BIGINT NULL;
GO

ALTER TABLE dbo.comisiones_factura
ADD CONSTRAINT FK_comisiones_factura_id_vendedor FOREIGN KEY([id_vendedor]) REFERENCES dbo.vendedores([id_vendedor])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.comisiones_factura
ADD CONSTRAINT FK_comisiones_factura_id_pago_comision FOREIGN KEY([id_pago_comision]) REFERENCES dbo.pagos_comisiones([id_pago_comision])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.pagos_comisiones
ADD CONSTRAINT FK_pagos_comisiones_id_vendedor FOREIGN KEY([id_vendedor]) REFERENCES dbo.vendedores([id_vendedor])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.pagos_comisiones
ADD CONSTRAINT FK_pagos_comisiones_id_cuenta_bancaria FOREIGN KEY([id_cuenta_bancaria]) REFERENCES dbo.cuentas_bancarias([id_cuenta])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.pagos_comisiones
ADD CONSTRAINT FK_pagos_comisiones_id_caja FOREIGN KEY([id_caja]) REFERENCES dbo.cajas([id_caja])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.pagos_comisiones
ADD CONSTRAINT FK_pagos_comisiones_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.banco_movimientos
ADD CONSTRAINT FK_banco_movimientos_id_pago_comision FOREIGN KEY([id_pago_comision]) REFERENCES dbo.pagos_comisiones([id_pago_comision])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.caja_movimientos
ADD CONSTRAINT FK_caja_movimientos_id_pago_comision FOREIGN KEY([id_pago_comision]) REFERENCES dbo.pagos_comisiones([id_pago_comision])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

-- PagoComisionService.pagar_comisiones_vendedor() trae "las pendientes de este vendedor"
-- con lock; futuros reportes de comisiones listaran por vendedor+estado.
CREATE INDEX IX_comisiones_factura_id_vendedor_estado_pago ON dbo.comisiones_factura ([id_vendedor], [estado_pago]);
GO

CREATE INDEX IX_pagos_comisiones_id_vendedor ON dbo.pagos_comisiones ([id_vendedor]);
GO
