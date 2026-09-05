-- Tercer estado de comisiones_factura.estado_pago: 'liberada' -- el cliente ya pago la
-- factura pero el vendedor todavia no cobro la comision (distinto de 'pendiente', cliente
-- no ha pagado, y de 'pagada', comision ya desembolsada). Ver app/services/comisiones.py
-- y docs/ESTADO_DEL_PROYECTO.md, "Comisiones de vendedor".
--
-- Contado: la comision nace 'liberada' directo (la factura se cobra completa al emitir,
-- nunca hay cuentas_por_cobrar de por medio) -- ver ComisionService.calcular_comisiones_factura.
-- Credito: nace 'pendiente' y este trigger la libera cuando la cuenta por cobrar asociada
-- llega a 'pagada' (disparado por trg_pagos_cobros_io, que hace el UPDATE sobre
-- cuentas_por_cobrar dentro de si mismo -- SQL Server permite triggers anidados por
-- defecto). No libera en 'parcial': solo con la factura completamente cobrada.

ALTER TABLE dbo.comisiones_factura DROP CONSTRAINT CK_comisiones_factura_estado;
GO

ALTER TABLE dbo.comisiones_factura
ADD CONSTRAINT CK_comisiones_factura_estado CHECK ([estado_pago] IN ('pendiente','liberada','pagada'));
GO

CREATE TRIGGER trg_cxc_libera_comisiones ON dbo.cuentas_por_cobrar
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
