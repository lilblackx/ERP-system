-- Indices para las consultas que mas se repiten y que hoy recorren la tabla completa.
--
-- Revision de indices (2026-11-08): se listaron las claves foraneas sin indice y se cruzaron con las consultas reales
-- de app/services. Solo se agregan los que alguna consulta usa; las columnas `creado_por`/`modificado_por` (solo
-- sirven si se BORRARA un usuario, que nunca pasa: se desactivan) y las claves de las tablas de pagos (ninguna
-- consulta filtra por ellas) se dejan sin indice para no encarecer cada escritura.
--
--   * Compuestos (columna de filtro, columna de orden): el listado paginado de movimientos de una cuenta, el de una
--     caja y el historial de un cliente filtran por una columna y ordenan por fecha. Con indices separados SQL Server
--     elegia uno y ordenaba el resto en memoria; con el compuesto lee ya ordenado y corta en el OFFSET/FETCH.
--     El indice de una sola columna queda cubierto por el compuesto (su primera columna), asi que se elimina.
--   * Claves foraneas que las consultas usan: kardex y reportes por producto, anulacion de facturas (nota de credito
--     de la factura), filtro de clientes por categoria, cuentas por banco, vendedores por ruta.

-- banco_movimientos: movimientos de una cuenta, mas recientes primero (listar_paginado, saldos, conciliacion)
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_banco_movimientos_cuenta_fecha' AND object_id = OBJECT_ID('dbo.banco_movimientos'))
    CREATE INDEX IX_banco_movimientos_cuenta_fecha ON dbo.banco_movimientos ([id_cuenta], [fecha_movimiento] DESC);
GO
IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_banco_movimientos_id_cuenta' AND object_id = OBJECT_ID('dbo.banco_movimientos'))
    DROP INDEX IX_banco_movimientos_id_cuenta ON dbo.banco_movimientos;
GO

-- caja_movimientos: historial y cierre de una caja
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_caja_movimientos_caja_fecha' AND object_id = OBJECT_ID('dbo.caja_movimientos'))
    CREATE INDEX IX_caja_movimientos_caja_fecha ON dbo.caja_movimientos ([id_caja], [fecha_registro] DESC);
GO
IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_caja_movimientos_id_caja' AND object_id = OBJECT_ID('dbo.caja_movimientos'))
    DROP INDEX IX_caja_movimientos_id_caja ON dbo.caja_movimientos;
GO

-- factura_venta: historial, cuentas por cobrar y limite de credito de un cliente
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_factura_venta_cliente_fecha' AND object_id = OBJECT_ID('dbo.factura_venta'))
    CREATE INDEX IX_factura_venta_cliente_fecha ON dbo.factura_venta ([id_cliente_factura], [fecha_emision] DESC);
GO
IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_factura_venta_id_cliente_factura' AND object_id = OBJECT_ID('dbo.factura_venta'))
    DROP INDEX IX_factura_venta_id_cliente_factura ON dbo.factura_venta;
GO

-- Kardex y reportes por producto: lineas de recepcion, devolucion y orden de compra de un producto
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_nota_recepcion_detalle_id_producto' AND object_id = OBJECT_ID('dbo.nota_recepcion_detalle'))
    CREATE INDEX IX_nota_recepcion_detalle_id_producto ON dbo.nota_recepcion_detalle ([id_producto]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_nota_devolucion_detalle_id_producto' AND object_id = OBJECT_ID('dbo.nota_devolucion_detalle'))
    CREATE INDEX IX_nota_devolucion_detalle_id_producto ON dbo.nota_devolucion_detalle ([id_producto]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_compra_oc_detalle_id_producto' AND object_id = OBJECT_ID('dbo.compra_oc_detalle'))
    CREATE INDEX IX_compra_oc_detalle_id_producto ON dbo.compra_oc_detalle ([id_producto]);
GO

-- Nota de credito generada por una factura (se busca al anularla / al devolver)
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_notas_credito_clientes_id_factura_origen' AND object_id = OBJECT_ID('dbo.notas_credito_clientes'))
    CREATE INDEX IX_notas_credito_clientes_id_factura_origen ON dbo.notas_credito_clientes ([id_factura_origen]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_notas_credito_proveedores_id_compra_origen' AND object_id = OBJECT_ID('dbo.notas_credito_proveedores'))
    CREATE INDEX IX_notas_credito_proveedores_id_compra_origen ON dbo.notas_credito_proveedores ([id_compra_origen]);
GO

-- Filtros de los listados de clientes (por categoria), cuentas bancarias (por banco) y vendedores (por ruta)
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_clientes_id_categoria_cliente' AND object_id = OBJECT_ID('dbo.clientes'))
    CREATE INDEX IX_clientes_id_categoria_cliente ON dbo.clientes ([id_categoria_cliente]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_cuentas_bancarias_id_banco' AND object_id = OBJECT_ID('dbo.cuentas_bancarias'))
    CREATE INDEX IX_cuentas_bancarias_id_banco ON dbo.cuentas_bancarias ([id_banco]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_vendedores_id_ruta' AND object_id = OBJECT_ID('dbo.vendedores'))
    CREATE INDEX IX_vendedores_id_ruta ON dbo.vendedores ([id_ruta]);
GO
