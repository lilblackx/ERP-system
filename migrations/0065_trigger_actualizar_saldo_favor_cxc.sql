-- Trigger para mantener saldo_favor actualizado en cuentas_por_cobrar
-- Se activa cuando se crean, modifican o eliminan notas de crédito
-- Actualiza todas las cuentas por cobrar del cliente afectado

IF OBJECT_ID('dbo.trg_actualizar_saldo_favor_cxc', 'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_actualizar_saldo_favor_cxc;
GO

CREATE TRIGGER trg_actualizar_saldo_favor_cxc ON dbo.notas_credito_clientes
AFTER INSERT, UPDATE, DELETE AS
BEGIN
	SET NOCOUNT ON;
	
	DECLARE @clientes_affected TABLE (id_cliente INT);
	
	-- Capturar clientes afectados por INSERT
	IF EXISTS (SELECT 1 FROM inserted)
	BEGIN
		INSERT INTO @clientes_affected (id_cliente)
		SELECT DISTINCT id_cliente FROM inserted;
	END
	
	-- Capturar clientes afectados por DELETE
	IF EXISTS (SELECT 1 FROM deleted)
	BEGIN
		INSERT INTO @clientes_affected (id_cliente)
		SELECT DISTINCT id_cliente FROM deleted;
	END
	
	-- Actualizar saldo_favor en todas las cuentas por cobrar de los clientes afectados
	UPDATE cxc
	SET cxc.saldo_favor = ISNULL((
		SELECT SUM(nc.saldo_disponible)
		FROM dbo.notas_credito_clientes nc
		WHERE nc.id_cliente = fv.id_cliente_factura
		AND nc.estado = 'disponible'
	), 0.00)
	FROM dbo.cuentas_por_cobrar cxc
	JOIN dbo.factura_venta fv ON cxc.id_factura = fv.id_factura
	JOIN @clientes_affected ca ON fv.id_cliente_factura = ca.id_cliente;
END
GO
