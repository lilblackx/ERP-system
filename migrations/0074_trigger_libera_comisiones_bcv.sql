-- Trigger para liberar comisiones cuando la cuenta por cobrar BCV se paga
-- Similar a trg_cxc_libera_comisiones pero para cuentas_por_cobrar_bcv
-- Cuando una cuenta BCV pasa a estado 'pagada', las comisiones asociadas
-- a esa factura deben pasar de 'pendiente' a 'liberada'

IF OBJECT_ID('dbo.trg_cxc_bcv_libera_comisiones', 'TR') IS NOT NULL
BEGIN
    DROP TRIGGER dbo.trg_cxc_bcv_libera_comisiones;
    PRINT 'Trigger trg_cxc_bcv_libera_comisiones eliminado.';
END
GO

CREATE TRIGGER trg_cxc_bcv_libera_comisiones ON dbo.cuentas_por_cobrar_bcv
AFTER UPDATE AS
BEGIN
	SET NOCOUNT ON;

	UPDATE cf
	SET cf.[estado_pago] = 'liberada'
	FROM dbo.comisiones_factura cf
	JOIN dbo.factura_detalle fd ON fd.[id_factura_detalle] = cf.[id_factura_detalle]
	JOIN inserted i ON i.[id_factura] = fd.[id_factura]
	JOIN deleted d ON d.[id_cuenta_por_cobrar] = i.[id_cuenta_por_cobrar]
	WHERE i.[estado] = 'pagada' AND d.[estado] <> 'pagada'
		AND cf.[estado_pago] = 'pendiente';
END
GO

PRINT 'Trigger trg_cxc_bcv_libera_comisiones creado exitosamente.';
