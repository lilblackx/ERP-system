-- =========================================================================
-- Prueba funcional de los 4 bloques de triggers (schema_sqlserver.sql)
-- Ejecutar contra la base ya migrada (USE distribuidora_dj; GO antes de correr).
--
-- Diseno: la parte "positiva" se hace COMMIT (no ROLLBACK), porque un error
-- levantado con RAISERROR *dentro de un trigger* deja la transaccion en
-- estado "doomed" (no permite mas escrituras hasta un ROLLBACK completo).
-- Si todo corriera en una sola transaccion, el primer test negativo tumbaria
-- todo lo que viene despues. Por eso cada test negativo corre en su propia
-- transaccion aislada, y al final se hace limpieza explicita con DELETE.
-- Es seguro re-ejecutar el script completo las veces que haga falta.
-- =========================================================================

SET NOCOUNT ON;

DECLARE @id_usuario BIGINT, @id_categoria BIGINT, @id_vendedor BIGINT,
        @id_cliente BIGINT, @id_producto BIGINT, @id_factura BIGINT,
        @id_caja BIGINT, @id_cuenta_por_cobrar BIGINT,
        @id_proveedor BIGINT, @id_compra BIGINT, @id_cuenta_por_pagar BIGINT;

BEGIN TRANSACTION;

PRINT '=== 1) Datos base: usuario, categoria, vendedor, cliente, producto ===';

INSERT INTO dbo.usuarios ([nombre_usuario], [nombre], [apellido], [email], [clave])
VALUES ('jperez', 'Juan', 'Perez', 'jperez@test.com', 'hash_no_real');
SET @id_usuario = SCOPE_IDENTITY();

INSERT INTO dbo.categorias ([nombre], [creado_por]) VALUES ('Bebidas', @id_usuario);
SET @id_categoria = SCOPE_IDENTITY();

INSERT INTO dbo.vendedores ([nombre_vendedor], [creado_por]) VALUES ('Carlos Ramirez', @id_usuario);
SET @id_vendedor = SCOPE_IDENTITY();

INSERT INTO dbo.clientes ([nombre_razon_social], [vendedor_cliente], [creado_por])
VALUES ('Abastos El Sol C.A.', @id_vendedor, @id_usuario);
SET @id_cliente = SCOPE_IDENTITY();

INSERT INTO dbo.inventario ([id_categoria], [cod_producto], [nombre_producto], [cantidad_unidad], [costo_producto], [creado_por])
VALUES (@id_categoria, 'REF-001', 'Refresco Cola 2L', 100, 5.00, @id_usuario);
SET @id_producto = SCOPE_IDENTITY();

PRINT 'Stock inicial:';
SELECT [id_producto], [nombre_producto], [cantidad_unidad] FROM dbo.inventario WHERE [id_producto] = @id_producto;


PRINT '=== 2) BLOQUE A + B: factura a credito con detalle -> stock y total ===';

INSERT INTO dbo.factura_venta ([numero_factura], [id_cliente_factura], [id_usuario_factura], [condicion_pago], [fecha_vencimiento], [id_vendedor])
VALUES ('FAC-TEST-0001', @id_cliente, @id_usuario, 'credito', DATEADD(DAY, 30, GETDATE()), @id_vendedor);
SET @id_factura = SCOPE_IDENTITY();

PRINT 'total_venta antes de insertar detalle (debe ser 0.00):';
SELECT [id_factura], [total_venta] FROM dbo.factura_venta WHERE [id_factura] = @id_factura;

INSERT INTO dbo.factura_detalle ([id_factura], [id_producto_factura], [cantidad_producto], [precio_unitario])
VALUES (@id_factura, @id_producto, 10, 8.50);

PRINT 'total_venta despues del detalle (esperado 85.00, Bloque B):';
SELECT [id_factura], [total_venta] FROM dbo.factura_venta WHERE [id_factura] = @id_factura;

PRINT 'stock despues de la venta (esperado 90, Bloque A):';
SELECT [id_producto], [cantidad_unidad] FROM dbo.inventario WHERE [id_producto] = @id_producto;


PRINT '=== 3) BLOQUE C: apertura automatica de cuenta por cobrar ===';

PRINT 'cuentas_por_cobrar generada por el UPDATE de total_venta (esperado saldo 85.00, estado pendiente):';
SELECT * FROM dbo.cuentas_por_cobrar WHERE [id_factura] = @id_factura;
SET @id_cuenta_por_cobrar = (SELECT [id_cuenta_por_cobrar] FROM dbo.cuentas_por_cobrar WHERE [id_factura] = @id_factura);


PRINT '=== 4) BLOQUE C + D: pago parcial por caja -> saldo, estado, movimiento, INSTEAD OF ===';

INSERT INTO dbo.cajas ([nombre_caja], [estado_caja], [saldo_apertura], [fecha_apertura], [id_usuario])
VALUES ('Caja Principal', 'ABIERTA', 100.00, GETDATE(), @id_usuario);
SET @id_caja = SCOPE_IDENTITY();

INSERT INTO dbo.pagos_cobros ([id_cuenta_por_cobrar], [id_caja], [metodo_pago], [monto], [referencia], [creado_por])
VALUES (@id_cuenta_por_cobrar, @id_caja, 'efectivo', 35.00, 'ABONO-1', @id_usuario);

PRINT 'cuentas_por_cobrar tras el pago (esperado saldo 50.00, estado parcial):';
SELECT * FROM dbo.cuentas_por_cobrar WHERE [id_cuenta_por_cobrar] = @id_cuenta_por_cobrar;

PRINT 'caja_movimientos generado por el trigger INSTEAD OF (esperado 1 fila, entrada 35.00):';
SELECT * FROM dbo.caja_movimientos WHERE [id_caja] = @id_caja;


PRINT '=== 5) BLOQUE D: cierre de caja (saldo_cierre calculado) ===';

UPDATE dbo.cajas SET [fecha_cierre] = GETDATE() WHERE [id_caja] = @id_caja;

PRINT 'cajas tras el cierre (esperado saldo_cierre = 100.00 + 35.00 = 135.00):';
SELECT [id_caja], [saldo_apertura], [saldo_cierre], [fecha_apertura], [fecha_cierre] FROM dbo.cajas WHERE [id_caja] = @id_caja;


PRINT '=== 6) BLOQUE A + B + C: compra a credito (mismo patron, lado proveedores) ===';

INSERT INTO dbo.proveedores ([nombre_razon_social], [creado_por]) VALUES ('Distribuidora Andina C.A.', @id_usuario);
SET @id_proveedor = SCOPE_IDENTITY();

INSERT INTO dbo.compras ([numero_compra], [id_proveedor], [id_usuario_compra], [fecha_emision], [total_compra], [condicion_pago], [fecha_vencimiento])
VALUES ('COMP-TEST-0001', @id_proveedor, @id_usuario, GETDATE(), 0.00, 'credito', DATEADD(DAY, 15, GETDATE()));
SET @id_compra = SCOPE_IDENTITY();

INSERT INTO dbo.compra_detalle ([id_compra], [id_producto_compra], [cantidad_producto], [costo_unitario])
VALUES (@id_compra, @id_producto, 50, 4.20);

PRINT 'total_compra recalculado (esperado 210.00):';
SELECT [id_compra], [total_compra] FROM dbo.compras WHERE [id_compra] = @id_compra;

PRINT 'stock tras la compra (esperado 90 + 50 = 140):';
SELECT [id_producto], [cantidad_unidad] FROM dbo.inventario WHERE [id_producto] = @id_producto;

PRINT 'cuentas_por_pagar generada (esperado saldo 210.00, pendiente):';
SELECT * FROM dbo.cuentas_por_pagar WHERE [id_compra] = @id_compra;
SET @id_cuenta_por_pagar = (SELECT [id_cuenta] FROM dbo.cuentas_por_pagar WHERE [id_compra] = @id_compra);

INSERT INTO dbo.pagos_proveedores ([id_cuenta_por_pagar], [id_caja], [metodo_pago], [monto], [creado_por])
VALUES (@id_cuenta_por_pagar, @id_caja, 'efectivo', 210.00, @id_usuario);

PRINT 'cuentas_por_pagar tras pago total (esperado saldo 0.00, estado pagada):';
SELECT * FROM dbo.cuentas_por_pagar WHERE [id_cuenta] = @id_cuenta_por_pagar;

PRINT 'caja_movimientos de salida generado por el pago a proveedor (esperado 1 fila, salida 210.00):';
SELECT * FROM dbo.caja_movimientos WHERE [id_caja] = @id_caja AND [id_pago_proveedor] IS NOT NULL;

COMMIT TRANSACTION;
PRINT '=== Flujo positivo confirmado (COMMIT). Datos de prueba persistidos temporalmente. ===';


PRINT '=== 7) BLOQUE C: validaciones del INSTEAD OF (cada una en su propia transaccion) ===';

BEGIN TRY
	BEGIN TRANSACTION neg1;
	INSERT INTO dbo.pagos_cobros ([id_cuenta_por_cobrar], [id_caja], [id_cuenta_bancaria], [metodo_pago], [monto], [creado_por])
	VALUES (@id_cuenta_por_cobrar, @id_caja, 1, 'efectivo', 10.00, @id_usuario); -- origen duplicado (caja + banco)
	COMMIT TRANSACTION neg1;
	PRINT 'FALLO: no debio dejar insertar con dos origenes';
END TRY
BEGIN CATCH
	PRINT 'OK (esperado): ' + ERROR_MESSAGE();
	IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
END CATCH;

BEGIN TRY
	BEGIN TRANSACTION neg2;
	INSERT INTO dbo.pagos_cobros ([id_cuenta_por_cobrar], [id_caja], [metodo_pago], [monto], [creado_por])
	VALUES (@id_cuenta_por_cobrar, @id_caja, 'efectivo', 999.00, @id_usuario); -- monto mayor al saldo (50.00)
	COMMIT TRANSACTION neg2;
	PRINT 'FALLO: no debio dejar insertar un monto mayor al saldo pendiente';
END TRY
BEGIN CATCH
	PRINT 'OK (esperado): ' + ERROR_MESSAGE();
	IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
END CATCH;


PRINT '=== 8) Limpieza: elimina todo lo insertado por esta prueba (orden respeta FKs) ===';

BEGIN TRANSACTION;

DELETE FROM dbo.caja_movimientos WHERE [id_caja] = @id_caja;
DELETE FROM dbo.pagos_cobros WHERE [id_cuenta_por_cobrar] = @id_cuenta_por_cobrar;
DELETE FROM dbo.pagos_proveedores WHERE [id_cuenta_por_pagar] = @id_cuenta_por_pagar;
DELETE FROM dbo.cuentas_por_pagar WHERE [id_compra] = @id_compra;
DELETE FROM dbo.compras WHERE [id_compra] = @id_compra;              -- cascada: compra_detalle
DELETE FROM dbo.factura_venta WHERE [id_factura] = @id_factura;      -- cascada: factura_detalle, cuentas_por_cobrar
DELETE FROM dbo.cajas WHERE [id_caja] = @id_caja;
DELETE FROM dbo.inventario WHERE [id_producto] = @id_producto;
DELETE FROM dbo.clientes WHERE [id_cliente] = @id_cliente;
DELETE FROM dbo.proveedores WHERE [id_proveedor] = @id_proveedor;
DELETE FROM dbo.vendedores WHERE [id_vendedor] = @id_vendedor;
DELETE FROM dbo.categorias WHERE [id_categoria] = @id_categoria;
DELETE FROM dbo.usuarios WHERE [id_usuario] = @id_usuario;

COMMIT TRANSACTION;
PRINT '=== FIN: limpieza confirmada, no queda nada persistido de esta prueba ===';
