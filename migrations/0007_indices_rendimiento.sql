-- C2 (docs/CHECKLIST_PRODUCCION.md): cero indices secundarios en las 32 tablas del
-- schema (solo indices implicitos de PK/UNIQUE). A diferencia de MySQL/Postgres, SQL
-- Server NO crea automaticamente un indice sobre una columna FK -- sin uno, cada
-- filtro/join por esa columna (y cada verificacion de integridad referencial al borrar
-- la fila padre) es un table scan completo.
--
-- Cada indice de aca corresponde a una columna usada como filtro/join/order_by real en
-- app/services/*.py (verificado con grep antes de escribir esto, no son especulativos).
-- No se indexan columnas de auditoria (creado_por/modificado_por) ni FKs que ningun
-- servicio consulta hoy -- esas tablas padre (usuarios, roles, etc.) tampoco se borran
-- fisicamente (ver migrations/0005), asi que el chequeo de integridad referencial en
-- DELETE no aplica en la practica.

-- factura_venta: listar_facturas() filtra por cliente/fecha/estado; el join de limite de
-- credito en emitir_factura() filtra por id_cliente_factura.
CREATE INDEX IX_factura_venta_id_cliente_factura ON dbo.factura_venta ([id_cliente_factura]);
GO
CREATE INDEX IX_factura_venta_fecha_emision ON dbo.factura_venta ([fecha_emision]);
GO
CREATE INDEX IX_factura_venta_estado_factura ON dbo.factura_venta ([estado_factura]);
GO

-- factura_detalle: filtrada por id_factura en cada anulacion y en el chequeo de
-- comisiones antes de anular.
CREATE INDEX IX_factura_detalle_id_factura ON dbo.factura_detalle ([id_factura]);
GO

-- cuentas_por_cobrar: id_factura se consulta en anular_factura() y en el join de limite
-- de credito; estado se filtra ahi mismo (IN pendiente/parcial/vencida) y en el dashboard
-- (facturas vencidas).
CREATE INDEX IX_cuentas_por_cobrar_id_factura ON dbo.cuentas_por_cobrar ([id_factura]);
GO
CREATE INDEX IX_cuentas_por_cobrar_estado ON dbo.cuentas_por_cobrar ([estado]);
GO

-- compras: listar_compras() filtra por proveedor/fecha/estado; el join de limite de
-- credito en registrar_compra() filtra por id_proveedor.
CREATE INDEX IX_compras_id_proveedor ON dbo.compras ([id_proveedor]);
GO
CREATE INDEX IX_compras_fecha_emision ON dbo.compras ([fecha_emision]);
GO
CREATE INDEX IX_compras_estado_compra ON dbo.compras ([estado_compra]);
GO

-- compra_detalle: filtrada por id_compra en cada anulacion.
CREATE INDEX IX_compra_detalle_id_compra ON dbo.compra_detalle ([id_compra]);
GO

-- cuentas_por_pagar: id_compra se consulta en anular_compra() y en el join de limite de
-- credito; estado se filtra ahi mismo y en el dashboard (compras vencidas).
CREATE INDEX IX_cuentas_por_pagar_id_compra ON dbo.cuentas_por_pagar ([id_compra]);
GO
CREATE INDEX IX_cuentas_por_pagar_estado ON dbo.cuentas_por_pagar ([estado]);
GO

-- pagos_cobros / pagos_proveedores: PagoService.listar_pagos_cxc/cxp filtran y ordenan
-- por estas columnas.
CREATE INDEX IX_pagos_cobros_id_cuenta_por_cobrar ON dbo.pagos_cobros ([id_cuenta_por_cobrar]);
GO
CREATE INDEX IX_pagos_proveedores_id_cuenta_por_pagar ON dbo.pagos_proveedores ([id_cuenta_por_pagar]);
GO

-- banco_movimientos: TesoreriaService.listar_movimientos_bancarios() filtra por
-- cuenta/fecha y ordena por fecha.
CREATE INDEX IX_banco_movimientos_id_cuenta ON dbo.banco_movimientos ([id_cuenta]);
GO
CREATE INDEX IX_banco_movimientos_fecha_movimiento ON dbo.banco_movimientos ([fecha_movimiento]);
GO

-- caja_movimientos: TesoreriaService cuenta movimientos por caja al cerrar turno.
CREATE INDEX IX_caja_movimientos_id_caja ON dbo.caja_movimientos ([id_caja]);
GO

-- notas_credito_clientes / notas_credito_proveedores: NotaCreditoService filtra y
-- ordena por estas columnas al listar el saldo a favor de un cliente/proveedor.
CREATE INDEX IX_notas_credito_clientes_id_cliente ON dbo.notas_credito_clientes ([id_cliente]);
GO
CREATE INDEX IX_notas_credito_proveedores_id_proveedor ON dbo.notas_credito_proveedores ([id_proveedor]);
GO

-- cuentas_por_cobrar_otros / cuentas_por_pagar_otros: OtrosMovimientosService filtra por
-- estado y por cliente (cxc) al listar.
CREATE INDEX IX_cuentas_por_cobrar_otros_id_cliente ON dbo.cuentas_por_cobrar_otros ([id_cliente]);
GO
CREATE INDEX IX_cuentas_por_cobrar_otros_estado ON dbo.cuentas_por_cobrar_otros ([estado]);
GO
CREATE INDEX IX_cuentas_por_pagar_otros_estado ON dbo.cuentas_por_pagar_otros ([estado]);
GO

-- auditoria: tabla append-only que solo crece -- AuditoriaService.listar_eventos()
-- filtra por rango de fecha (siempre), usuario, y modulo; ordena siempre por fecha desc.
-- Sin indice, cada consulta de auditoria es un scan completo de la bitacora entera.
CREATE INDEX IX_auditoria_fecha_evento ON dbo.auditoria ([fecha_evento]);
GO
CREATE INDEX IX_auditoria_id_usuario ON dbo.auditoria ([id_usuario]);
GO
CREATE INDEX IX_auditoria_modulo ON dbo.auditoria ([modulo]);
GO

-- inventario: listar_productos()/alertas de stock/vencimiento filtran y ordenan por
-- estas columnas.
CREATE INDEX IX_inventario_id_categoria ON dbo.inventario ([id_categoria]);
GO
CREATE INDEX IX_inventario_cantidad_unidad ON dbo.inventario ([cantidad_unidad]);
GO
CREATE INDEX IX_inventario_fecha_vencimiento ON dbo.inventario ([fecha_vencimiento]);
GO

-- clientes: VendedorService.desempeno_mensual() filtra clientes por vendedor asignado.
CREATE INDEX IX_clientes_vendedor_cliente ON dbo.clientes ([vendedor_cliente]);
GO

-- usuarios: UsuarioService.listar_usuarios() filtra por rol.
CREATE INDEX IX_usuarios_id_rol ON dbo.usuarios ([id_rol]);
GO
