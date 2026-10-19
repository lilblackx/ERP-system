-- Vuelto (cambio) en facturas de contado: el excedente de las formas de pago sobre
-- total_a_cobrar SIEMPRE se entrega al cliente (no existe "saldo a favor" como metodo de
-- vuelto, decision de alcance) -- ver VentaService.emitir_factura(). Vuelto en efectivo es
-- libre y se registra como egreso real de caja (caja_movimientos tipo 'salida', afecta
-- saldo_cierre via trg_cajas_cierre); vuelto por pago movil o transferencia exige una
-- referencia bancaria (banco_movimientos.referencia_movimiento, tipo_movimiento 'cargo') y
-- autorizacion de un usuario con el permiso nuevo 'vueltos_bancarios'/'crear' -- mismo
-- mecanismo ya usado por 'descuentos'/'crear' (migrations/0020+0021) y 'creditos'/'crear'
-- (migrations/0025): no se crea un rol SUPERVISOR nuevo, ADMIN bypassa siempre y cualquier
-- otro rol necesita que un ADMIN se lo otorgue explicitamente.
--
-- Un solo archivo para columnas + FK + CHECK + permiso, siguiendo el criterio mas
-- reciente (0025_autorizacion_dias_credito.sql) en vez de separar en dos como 0020/0021.

ALTER TABLE dbo.factura_venta ADD [monto_vuelto] DECIMAL(18,2) NOT NULL CONSTRAINT DF_factura_venta_monto_vuelto DEFAULT (0.00);
GO

ALTER TABLE dbo.factura_venta ADD [metodo_vuelto] VARCHAR(20) NULL;
GO

ALTER TABLE dbo.factura_venta
ADD CONSTRAINT CK_factura_venta_metodo_vuelto CHECK ([metodo_vuelto] IS NULL OR [metodo_vuelto] IN ('efectivo','pago_movil','transferencia'));
GO

ALTER TABLE dbo.factura_venta ADD [referencia_vuelto] VARCHAR(50) NULL;
GO

ALTER TABLE dbo.factura_venta ADD [autorizado_por_vuelto] BIGINT NULL;
GO

ALTER TABLE dbo.factura_venta
ADD CONSTRAINT FK_factura_venta_autorizado_por_vuelto FOREIGN KEY([autorizado_por_vuelto]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.factura_venta ADD [fecha_autorizacion_vuelto] DATETIME NULL;
GO

INSERT INTO dbo.permisos ([recurso], [accion], [descripcion]) VALUES
('vueltos_bancarios', 'crear', 'Autorizar vuelto de factura por pago movil o transferencia (requiere referencia bancaria)');
GO
