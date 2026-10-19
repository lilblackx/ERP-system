-- Descuento manual de factura (monto absoluto sobre el subtotal) + autorizacion
-- obligatoria: tanto este descuento explicito como vender un item por debajo de su
-- precio de lista (comparacion contra producto_precios, ver ComisionService) requieren
-- que un usuario con el permiso 'ventas'/'autorizar_descuento' lo autorice -- ver
-- VentaService.emitir_factura() y migrations/0021_permiso_autorizar_descuento.sql.
--
-- El descuento por item NO tiene columna propia: se maneja bajando precio_unitario
-- directamente (la diferencia contra el precio de lista ya es visible comparando esas
-- dos columnas), simetrico a como ComisionService ya trata precio_unitario > precio de
-- lista como comision del vendedor.

ALTER TABLE dbo.factura_venta ADD [monto_descuento] DECIMAL(18,2) NOT NULL CONSTRAINT DF_factura_venta_monto_descuento DEFAULT (0.00);
GO

ALTER TABLE dbo.factura_venta ADD [motivo_descuento] VARCHAR(255) NULL;
GO

ALTER TABLE dbo.factura_venta ADD [autorizado_por_descuento] BIGINT NULL;
GO

ALTER TABLE dbo.factura_venta
ADD CONSTRAINT FK_factura_venta_autorizado_por_descuento FOREIGN KEY([autorizado_por_descuento]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
