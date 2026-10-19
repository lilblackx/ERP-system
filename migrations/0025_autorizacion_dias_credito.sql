-- Facturas de credito quedan limitadas a clientes con dias_credito configurado (>0):
-- VentaService.emitir_factura() rechaza condicion_pago='credito' si el cliente tiene
-- dias_credito<=0 (columna NOT NULL DEFAULT 0 -- ese es el estado real de "sin
-- configurar"). Para los clientes que si califican, se puede facturar con dias distintos
-- a los configurados en una factura puntual, pero requiere autorizacion de un supervisor
-- (permiso 'creditos'/'crear', mismo patron que 'descuentos'/'crear' en
-- migrations/0020_descuentos_autorizacion.sql y 0021_permiso_autorizar_descuento.sql).
--
-- dias_credito_aplicados guarda el snapshot de los dias efectivamente usados (configurados
-- o personalizados) para esta factura -- NULL en facturas de contado. motivo_dias_credito/
-- autorizado_por_dias_credito solo se pueblan cuando hubo un override autorizado.

ALTER TABLE dbo.factura_venta ADD [dias_credito_aplicados] INT NULL;
GO

ALTER TABLE dbo.factura_venta ADD [motivo_dias_credito] VARCHAR(255) NULL;
GO

ALTER TABLE dbo.factura_venta ADD [autorizado_por_dias_credito] BIGINT NULL;
GO

ALTER TABLE dbo.factura_venta
ADD CONSTRAINT FK_factura_venta_autorizado_por_dias_credito FOREIGN KEY([autorizado_por_dias_credito]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

INSERT INTO dbo.permisos ([recurso], [accion], [descripcion]) VALUES
('creditos', 'crear', 'Autorizar dias de credito distintos a los configurados en el cliente');
GO
