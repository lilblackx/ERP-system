-- Notas de credito automaticas al anular una factura/compra con pagos aplicados.
--
-- La migracion 0001 resolvia esto borrando el pago (y su movimiento de caja/banco) en
-- cascada -- automatico, pero contablemente incorrecto: si el turno de caja donde se
-- registro el pago ya habia cerrado, o el movimiento bancario ya se habia conciliado,
-- el borrado mutaba retroactivamente un registro que ya se considera historico/sellado.
-- No hay columna "conciliado" en banco_movimientos/caja_movimientos que lo impidiera.
--
-- Este cambio reemplaza esa estrategia por una nota de credito: la plata que el cliente
-- (o la empresa, en el caso de proveedores) ya pago NO se revierte -- pagos_cobros/
-- pagos_proveedores y sus banco_movimientos/caja_movimientos quedan intactos para
-- siempre, con su fecha e historial reales. En vez de eso, VentaService.anular_factura()/
-- CompraService.anular_compra() (app/services/ventas.py, compras.py) dejan un registro
-- de que esa plata ahora es un saldo a favor del cliente/proveedor, para aplicar a una
-- operacion futura o devolver despues, a mano, como un movimiento nuevo y fechado (nunca
-- una edicion retroactiva).
--
-- Los triggers _del de la migracion 0001 NO se tocan: siguen siendo utiles para el caso
-- distinto de borrar un pago mal registrado directamente (sin pasar por anulacion), pero
-- ya no los usa el flujo de anulacion.

-- =========================================================================
-- 1) Nuevo estado 'anulada' para cuentas_por_cobrar/cuentas_por_pagar
-- =========================================================================
-- Antes, anular_factura()/anular_compra() borraban la fila de cuentas_por_cobrar/
-- cuentas_por_pagar (no habia estado para representar "anulada"). Para conservar el
-- historial cuando hubo pagos aplicados, la fila ahora se conserva con este estado en
-- vez de borrarse. Sin pagos aplicados, se sigue borrando igual que antes (no hay nada
-- que preservar).

ALTER TABLE dbo.cuentas_por_cobrar DROP CONSTRAINT CK_cxc_estado;
GO
ALTER TABLE dbo.cuentas_por_cobrar
ADD CONSTRAINT CK_cxc_estado CHECK ([estado] IN ('pendiente','parcial','pagada','vencida','anulada'));
GO

ALTER TABLE dbo.cuentas_por_pagar DROP CONSTRAINT CK_cxp_estado;
GO
ALTER TABLE dbo.cuentas_por_pagar
ADD CONSTRAINT CK_cxp_estado CHECK ([estado] IN ('pendiente','parcial','pagada','vencida','anulada'));
GO

-- =========================================================================
-- 2) notas_credito_clientes / notas_credito_proveedores
-- =========================================================================

CREATE TABLE dbo.notas_credito_clientes (
	[id_nota_credito] BIGINT IDENTITY(1,1) NOT NULL,
	[id_cliente] BIGINT NOT NULL,
	[id_factura_origen] BIGINT NOT NULL,
	[monto] DECIMAL(18,2) NOT NULL,
	[saldo_disponible] DECIMAL(18,2) NOT NULL,
	[motivo] VARCHAR(255) NULL,
	[estado] VARCHAR(15) NOT NULL DEFAULT 'disponible' CONSTRAINT CK_notas_credito_clientes_estado CHECK ([estado] IN ('disponible','aplicada','devuelta')),
	[creado_por] BIGINT NULL,
	[fecha_creacion] DATETIME NOT NULL DEFAULT GETDATE(),
	CONSTRAINT PK_notas_credito_clientes PRIMARY KEY ([id_nota_credito])
);
GO

ALTER TABLE dbo.notas_credito_clientes
ADD CONSTRAINT FK_notas_credito_clientes_id_cliente FOREIGN KEY([id_cliente]) REFERENCES dbo.clientes([id_cliente])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.notas_credito_clientes
ADD CONSTRAINT FK_notas_credito_clientes_id_factura_origen FOREIGN KEY([id_factura_origen]) REFERENCES dbo.factura_venta([id_factura])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.notas_credito_clientes
ADD CONSTRAINT FK_notas_credito_clientes_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE SET NULL;
GO

CREATE TABLE dbo.notas_credito_proveedores (
	[id_nota_credito] BIGINT IDENTITY(1,1) NOT NULL,
	[id_proveedor] BIGINT NOT NULL,
	[id_compra_origen] BIGINT NOT NULL,
	[monto] DECIMAL(18,2) NOT NULL,
	[saldo_disponible] DECIMAL(18,2) NOT NULL,
	[motivo] VARCHAR(255) NULL,
	[estado] VARCHAR(15) NOT NULL DEFAULT 'disponible' CONSTRAINT CK_notas_credito_proveedores_estado CHECK ([estado] IN ('disponible','aplicada','devuelta')),
	[creado_por] BIGINT NULL,
	[fecha_creacion] DATETIME NOT NULL DEFAULT GETDATE(),
	CONSTRAINT PK_notas_credito_proveedores PRIMARY KEY ([id_nota_credito])
);
GO

ALTER TABLE dbo.notas_credito_proveedores
ADD CONSTRAINT FK_notas_credito_proveedores_id_proveedor FOREIGN KEY([id_proveedor]) REFERENCES dbo.proveedores([id_proveedor])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.notas_credito_proveedores
ADD CONSTRAINT FK_notas_credito_proveedores_id_compra_origen FOREIGN KEY([id_compra_origen]) REFERENCES dbo.compras([id_compra])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.notas_credito_proveedores
ADD CONSTRAINT FK_notas_credito_proveedores_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE SET NULL;
GO
