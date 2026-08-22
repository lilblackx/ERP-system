-- Reversion automatica de pagos al anular una factura/compra.
--
-- Hasta ahora anular_factura()/anular_compra() se negaban con ValueError si la cuenta
-- por cobrar/pagar ya tenia pagos aplicados, porque no habia forma de deshacer el
-- movimiento de banco/caja ni el saldo ya descontado sin intervencion manual. Esta
-- migracion agrega el lado "DELETE" que faltaba, simetrico al "INSERT" que ya existia:
--
--   1. Las FK de banco_movimientos/caja_movimientos hacia pagos_cobros/pagos_proveedores
--      pasan de NO ACTION a CASCADE: borrar un pago borra automaticamente el movimiento
--      de banco/caja que género.
--   2. trg_banco_movimientos_saldo_del revierte cuentas_bancarias.saldo_total_banco
--      cuando se borra (o se cascadea) un banco_movimiento -- espejo de
--      trg_banco_movimientos_saldo (AFTER INSERT).
--   3. trg_caja_movimientos_cierre_recalc_del recalcula cajas.saldo_cierre cuando se
--      borra (o se cascadea) un caja_movimiento de un turno YA cerrado -- sin esto, un
--      pago revertido despues del cierre de caja dejaria saldo_cierre desactualizado.
--      Turnos abiertos no se ven afectados (saldo_cierre es NULL hasta el cierre).
--   4. trg_pagos_cobros_del / trg_pagos_proveedores_del revierten
--      cuentas_por_cobrar/cuentas_por_pagar.saldo_pendiente y estado cuando se borra un
--      pago -- espejo de trg_pagos_cobros_io/trg_pagos_proveedores_io (INSTEAD OF INSERT).
--      El estado resultante ('pendiente' o 'parcial') se calcula comparando contra
--      factura_venta.total_venta / compras.total_compra, igual que hace el trigger de
--      insercion con 'pagada'/'parcial'.
--
-- Con esto, el codigo de aplicacion solo necesita borrar la fila de pagos_cobros/
-- pagos_proveedores (ver ventas.py/compras.py) -- todo lo demas se propaga solo.

-- =========================================================================
-- 1) FK de banco_movimientos/caja_movimientos hacia pagos_*: NO ACTION -> CASCADE
-- =========================================================================

ALTER TABLE dbo.banco_movimientos DROP CONSTRAINT FK_banco_movimientos_id_pago_cobro;
GO
ALTER TABLE dbo.banco_movimientos
ADD CONSTRAINT FK_banco_movimientos_id_pago_cobro FOREIGN KEY([id_pago_cobro]) REFERENCES dbo.pagos_cobros([id_pago_cobro])
ON UPDATE NO ACTION ON DELETE CASCADE;
GO

ALTER TABLE dbo.banco_movimientos DROP CONSTRAINT FK_banco_movimientos_id_pago_proveedor;
GO
ALTER TABLE dbo.banco_movimientos
ADD CONSTRAINT FK_banco_movimientos_id_pago_proveedor FOREIGN KEY([id_pago_proveedor]) REFERENCES dbo.pagos_proveedores([id_pago_proveedor])
ON UPDATE NO ACTION ON DELETE CASCADE;
GO

ALTER TABLE dbo.caja_movimientos DROP CONSTRAINT FK_caja_movimientos_id_pago_cobro;
GO
ALTER TABLE dbo.caja_movimientos
ADD CONSTRAINT FK_caja_movimientos_id_pago_cobro FOREIGN KEY([id_pago_cobro]) REFERENCES dbo.pagos_cobros([id_pago_cobro])
ON UPDATE NO ACTION ON DELETE CASCADE;
GO

ALTER TABLE dbo.caja_movimientos DROP CONSTRAINT FK_caja_movimientos_id_pago_proveedor;
GO
ALTER TABLE dbo.caja_movimientos
ADD CONSTRAINT FK_caja_movimientos_id_pago_proveedor FOREIGN KEY([id_pago_proveedor]) REFERENCES dbo.pagos_proveedores([id_pago_proveedor])
ON UPDATE NO ACTION ON DELETE CASCADE;
GO

-- =========================================================================
-- 2) Reversa de saldo bancario
-- =========================================================================

CREATE TRIGGER trg_banco_movimientos_saldo_del ON dbo.banco_movimientos
AFTER DELETE AS
BEGIN
	SET NOCOUNT ON;
	UPDATE cb
	SET cb.[saldo_total_banco] = cb.[saldo_total_banco] - agg.[delta]
	FROM dbo.cuentas_bancarias cb
	JOIN (
		SELECT [id_cuenta], SUM(CASE WHEN [tipo_movimiento] IN ('abono','deposito') THEN [monto_movimiento] ELSE -[monto_movimiento] END) AS [delta]
		FROM deleted
		GROUP BY [id_cuenta]
	) agg ON agg.[id_cuenta] = cb.[id_cuenta];
END
GO

-- =========================================================================
-- 3) Recalculo de saldo_cierre si el turno ya estaba cerrado
-- =========================================================================

CREATE TRIGGER trg_caja_movimientos_cierre_recalc_del ON dbo.caja_movimientos
AFTER DELETE AS
BEGIN
	SET NOCOUNT ON;
	UPDATE c
	SET c.[saldo_cierre] = c.[saldo_apertura] + ISNULL((
		SELECT SUM(CASE WHEN cm.[tipo_movimiento] = 'entrada' THEN cm.[monto_movimiento] ELSE -cm.[monto_movimiento] END)
		FROM dbo.caja_movimientos cm
		WHERE cm.[id_caja] = c.[id_caja]
			AND cm.[fecha_registro] >= c.[fecha_apertura]
			AND cm.[fecha_registro] <= c.[fecha_cierre]
	), 0)
	FROM dbo.cajas c
	JOIN (SELECT DISTINCT [id_caja] FROM deleted) d ON d.[id_caja] = c.[id_caja]
	WHERE c.[fecha_cierre] IS NOT NULL;
END
GO

-- =========================================================================
-- 4) Reversa de saldo_pendiente/estado en cuentas por cobrar/pagar
-- =========================================================================

CREATE TRIGGER trg_pagos_cobros_del ON dbo.pagos_cobros
AFTER DELETE AS
BEGIN
	SET NOCOUNT ON;
	UPDATE c
	SET c.[saldo_pendiente] = c.[saldo_pendiente] + agg.[monto],
		c.[estado] = CASE WHEN c.[saldo_pendiente] + agg.[monto] >= fv.[total_venta] THEN 'pendiente' ELSE 'parcial' END
	FROM dbo.cuentas_por_cobrar c
	JOIN (
		SELECT [id_cuenta_por_cobrar], SUM([monto]) AS [monto]
		FROM deleted
		GROUP BY [id_cuenta_por_cobrar]
	) agg ON agg.[id_cuenta_por_cobrar] = c.[id_cuenta_por_cobrar]
	JOIN dbo.factura_venta fv ON fv.[id_factura] = c.[id_factura];
END
GO

CREATE TRIGGER trg_pagos_proveedores_del ON dbo.pagos_proveedores
AFTER DELETE AS
BEGIN
	SET NOCOUNT ON;
	UPDATE c
	SET c.[saldo_pendiente] = c.[saldo_pendiente] + agg.[monto],
		c.[estado] = CASE WHEN c.[saldo_pendiente] + agg.[monto] >= co.[total_compra] THEN 'pendiente' ELSE 'parcial' END
	FROM dbo.cuentas_por_pagar c
	JOIN (
		SELECT [id_cuenta_por_pagar], SUM([monto]) AS [monto]
		FROM deleted
		GROUP BY [id_cuenta_por_pagar]
	) agg ON agg.[id_cuenta_por_pagar] = c.[id_cuenta]
	JOIN dbo.compras co ON co.[id_compra] = c.[id_compra];
END
GO
