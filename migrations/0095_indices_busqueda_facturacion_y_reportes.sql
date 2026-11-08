-- Indices que faltaban para consultas que hoy recorren la tabla completa (auditoria de rendimiento, 2026-11):
--
--   * factura_venta.id_vendedor: la busqueda de texto del listado de facturas tambien compara el nombre del
--     vendedor (VentaService.listar_facturas), y los reportes por vendedor/ruta agrupan por esa columna.
--   * factura_detalle.id_producto_factura / compra_detalle.id_producto_compra: kardex, ventas/compras por
--     producto, productos sin movimiento y margen de utilidad filtran las lineas por producto.
--   * pagos_cobros.fecha_pago, pagos_cobros_bcv, pagos_proveedores.fecha_pago, caja_movimientos.fecha_registro:
--     los reportes de cobros/pagos/movimientos del periodo filtran por rango de fechas, y los pagos BCV no
--     tenian ningun indice (se busca por id_cuenta_por_cobrar al armar estados de cuenta y aging).
--
-- Cada uno se crea solo si no existe: algun entorno pudo haberlo creado a mano.

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_factura_venta_id_vendedor' AND object_id = OBJECT_ID(N'dbo.factura_venta'))
	CREATE INDEX IX_factura_venta_id_vendedor ON dbo.factura_venta ([id_vendedor]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_factura_detalle_id_producto_factura' AND object_id = OBJECT_ID(N'dbo.factura_detalle'))
	CREATE INDEX IX_factura_detalle_id_producto_factura ON dbo.factura_detalle ([id_producto_factura])
	INCLUDE ([id_factura], [cantidad_producto], [precio_unitario]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_compra_detalle_id_producto_compra' AND object_id = OBJECT_ID(N'dbo.compra_detalle'))
	CREATE INDEX IX_compra_detalle_id_producto_compra ON dbo.compra_detalle ([id_producto_compra]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_pagos_cobros_fecha_pago' AND object_id = OBJECT_ID(N'dbo.pagos_cobros'))
	CREATE INDEX IX_pagos_cobros_fecha_pago ON dbo.pagos_cobros ([fecha_pago]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_pagos_cobros_bcv_id_cuenta_por_cobrar' AND object_id = OBJECT_ID(N'dbo.pagos_cobros_bcv'))
	CREATE INDEX IX_pagos_cobros_bcv_id_cuenta_por_cobrar ON dbo.pagos_cobros_bcv ([id_cuenta_por_cobrar]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_pagos_cobros_bcv_fecha_pago' AND object_id = OBJECT_ID(N'dbo.pagos_cobros_bcv'))
	CREATE INDEX IX_pagos_cobros_bcv_fecha_pago ON dbo.pagos_cobros_bcv ([fecha_pago]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_pagos_proveedores_fecha_pago' AND object_id = OBJECT_ID(N'dbo.pagos_proveedores'))
	CREATE INDEX IX_pagos_proveedores_fecha_pago ON dbo.pagos_proveedores ([fecha_pago]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_caja_movimientos_fecha_registro' AND object_id = OBJECT_ID(N'dbo.caja_movimientos'))
	CREATE INDEX IX_caja_movimientos_fecha_registro ON dbo.caja_movimientos ([fecha_registro]);
GO
