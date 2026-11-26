-- Vinculo entre una nota de credito de cliente y el abono general que la origino.
--
-- Cuando un abono general (o un abono sin facturas pendientes) deja excedente, el
-- dinero entra completo a caja/banco pero solo la parte aplicada genera
-- pagos_cobros; el excedente queda como NotaCreditoCliente (saldo a favor). Sin un
-- vinculo, el estado de cuenta no podia mostrar "el pago exacto que realizo el
-- cliente": la fila del abono solo sumaba los pagos aplicados y la NC salia como un
-- movimiento aparte.
--
-- fecha_pago_origen guarda la fecha_pago compartida por todos los pagos_cobros del
-- abono (ver PagoService.aplicar_abono_general_cliente /
-- PagoBCVService.aplicar_abono_general_cliente_bcv), que es la misma clave con que
-- ReporteService.estado_cuenta_cliente agrupa las lineas de pago en un solo abono.
-- El reporte suma el monto de la NC a ese grupo: el abono muestra el total exacto
-- recibido y el saldo corrido puede quedar negativo (= saldo a favor). Las notas de
-- anulacion y demas origenes quedan en NULL: su credito si se muestra como fila
-- propia (no viene de un pago).
--
-- NULL en todas las filas existentes: las NC historicas de sobreabono se tratan como
-- cualquier otra nota (fila propia de saldo a favor), que es lo correcto porque su
-- pago nunca incluyo el excedente en la fila del abono.

IF COL_LENGTH('dbo.notas_credito_clientes', 'fecha_pago_origen') IS NULL
BEGIN
	ALTER TABLE dbo.notas_credito_clientes
		ADD [fecha_pago_origen] DATETIME NULL;
END
GO
