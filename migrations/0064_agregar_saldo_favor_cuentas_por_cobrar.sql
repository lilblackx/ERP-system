-- Agregar campo saldo_favor para almacenar el saldo a favor del cliente (notas de crédito disponibles)
-- Este campo se mantiene actualizado mediante triggers para llevar control del crédito a favor

IF NOT EXISTS (
	SELECT 1 FROM sys.columns
	WHERE object_id = OBJECT_ID('dbo.cuentas_por_cobrar')
	AND name = 'saldo_favor'
)
BEGIN
	ALTER TABLE dbo.cuentas_por_cobrar
	ADD [saldo_favor] DECIMAL(18,2) NOT NULL DEFAULT 0.00;
END
GO

-- Inicializar saldo_favor para registros existentes
-- Calcular el saldo a favor basado en notas de crédito disponibles del cliente
UPDATE cxc
SET [saldo_favor] = ISNULL((
	SELECT SUM(nc.saldo_disponible)
	FROM dbo.notas_credito_clientes nc
	WHERE nc.id_cliente = fv.id_cliente_factura
	AND nc.estado = 'disponible'
), 0.00)
FROM dbo.cuentas_por_cobrar cxc
JOIN dbo.factura_venta fv ON cxc.id_factura = fv.id_factura
WHERE cxc.saldo_favor = 0;
GO
