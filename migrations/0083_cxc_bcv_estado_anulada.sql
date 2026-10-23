-- VentaService.anular_factura no tocaba cuentas_por_cobrar_bcv: anular una factura con
-- porcentaje BCV dejaba la deuda BCV abierta (el cliente seguia debiendo una factura
-- anulada) y los pagos BCV ya cobrados no generaban nota de credito. Ahora la anulacion
-- deja esa cuenta en estado 'anulada' con saldo 0 -- mismo criterio que
-- cuentas_por_cobrar.estado='anulada' (migrations/0002). No se puede borrar la fila si
-- ya tiene pagos_cobros_bcv (FK), y el CHECK original de 0071 no admitia 'anulada'.

ALTER TABLE dbo.cuentas_por_cobrar_bcv DROP CONSTRAINT CK_estado_cuentas_por_cobrar_bcv;
GO

ALTER TABLE dbo.cuentas_por_cobrar_bcv
ADD CONSTRAINT CK_estado_cuentas_por_cobrar_bcv
	CHECK ([estado] IN ('pendiente', 'parcial', 'pagada', 'vencida', 'anulada'));
GO
