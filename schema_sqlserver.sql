-- =========================================================================
-- Migracion MySQL -> SQL Server (T-SQL)
-- Notas de mapeo (aplican a todo el archivo):
--   BIGINT UNSIGNED / INTEGER UNSIGNED -> BIGINT / INT (SQL Server no tiene UNSIGNED)
--   AUTO_INCREMENT                     -> IDENTITY(1,1)
--   ENUM(...)                          -> VARCHAR(n) + CHECK constraint
--   DATETIME DEFAULT CURRENT_TIMESTAMP -> DATETIME DEFAULT GETDATE()
--   LONGBLOB                           -> VARBINARY(MAX)
--   `backticks`                        -> [corchetes]
--   COMMENT '...'                      -> comentario -- (metadata, no se migra a extended properties)
--   CREATE TABLE IF NOT EXISTS         -> IF OBJECT_ID(...) IS NULL BEGIN ... END
--
-- Desviaciones de comportamiento respecto al original MySQL:
--   1) ON UPDATE CASCADE -> ON UPDATE NO ACTION en TODAS las FK. Las PK son IDENTITY
--      autoincremental y nunca se actualizan en la practica, asi que esto no cambia
--      comportamiento real. Es obligatorio: SQL Server cuenta el ON UPDATE CASCADE como
--      arista de cascada igual que el ON DELETE, y con tantas FK hacia `usuarios` el grafo
--      combinado generaba rutas multiples (error 1785) en varios puntos del schema.
--   2) control_de_tasas.modificado_por -> usuarios  y  bancos.modificado_por -> usuarios
--      pasan de ON DELETE SET NULL a ON DELETE NO ACTION. Sin este cambio, `usuarios`
--      alcanza `factura_venta` por dos rutas de cascada (directa, y via control_de_tasas)
--      y `bancos` por dos FK cascada (creado_por + modificado_por).
--   Resto de FKs identicas en semantica de ON DELETE al script MySQL original.
-- =========================================================================

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO


-- =========================================================================
-- TABLAS
-- =========================================================================

IF OBJECT_ID(N'dbo.usuarios', N'U') IS NULL
BEGIN
CREATE TABLE dbo.usuarios (
	[id_usuario] BIGINT IDENTITY(1,1) NOT NULL,
	[nombre_usuario] VARCHAR(50) NOT NULL UNIQUE,
	[nombre] VARCHAR(100) NULL,
	[apellido] VARCHAR(100) NULL,
	[email] VARCHAR(150) NULL,
	[clave] VARCHAR(255) NULL,
	[id_rol] BIGINT NULL,
	[fecha_registro] DATETIME NOT NULL DEFAULT GETDATE(),
	[estado] VARCHAR(20) NOT NULL DEFAULT 'ACTIVO',
	[id_vendedor_usuario] BIGINT NULL,
	CONSTRAINT PK_usuarios PRIMARY KEY ([id_usuario])
);
END
GO


IF OBJECT_ID(N'dbo.roles', N'U') IS NULL
BEGIN
CREATE TABLE dbo.roles (
	[id_rol] BIGINT IDENTITY(1,1) NOT NULL,
	[nombre] VARCHAR(30) NOT NULL UNIQUE,
	[descripcion] VARCHAR(255) NULL,
	CONSTRAINT PK_roles PRIMARY KEY ([id_rol])
);
END
GO


IF OBJECT_ID(N'dbo.permisos', N'U') IS NULL
BEGIN
CREATE TABLE dbo.permisos (
	[id_permiso] BIGINT IDENTITY(1,1) NOT NULL,
	[recurso] VARCHAR(50) NOT NULL, -- Ej: inventario, reportes_ventas, reportes_comisiones
	[accion] VARCHAR(10) NOT NULL CONSTRAINT CK_permisos_accion CHECK ([accion] IN ('ver','crear','editar','eliminar')),
	[descripcion] VARCHAR(255) NULL,
	CONSTRAINT PK_permisos PRIMARY KEY ([id_permiso]),
	CONSTRAINT UQ_permisos_recurso_accion UNIQUE ([recurso], [accion])
);
END
GO


IF OBJECT_ID(N'dbo.rol_permisos', N'U') IS NULL
BEGIN
CREATE TABLE dbo.rol_permisos ( -- Matriz de permisos por rol: que recursos y acciones puede ejecutar cada rol
	[id_rol] BIGINT NOT NULL,
	[id_permiso] BIGINT NOT NULL,
	CONSTRAINT PK_rol_permisos PRIMARY KEY ([id_rol], [id_permiso])
);
END
GO


IF OBJECT_ID(N'dbo.vendedores', N'U') IS NULL
BEGIN
CREATE TABLE dbo.vendedores (
	[id_vendedor] BIGINT IDENTITY(1,1) NOT NULL,
	[codigo_vendedor] VARCHAR(20) NULL,
	[identificacion_vendedor] VARCHAR(20) NULL,
	[nombre_vendedor] VARCHAR(150) NOT NULL,
	[direccion_vendedor] VARCHAR(255) NULL,
	[telefono_vendedor] VARCHAR(20) NULL,
	[email_vendedor] VARCHAR(150) NULL,
	[fecha_creacion] DATETIME NOT NULL DEFAULT GETDATE(),
	[estado_vendedor] VARCHAR(20) NOT NULL DEFAULT 'ACTIVO',
	[creado_por] BIGINT NULL,
	CONSTRAINT PK_vendedores PRIMARY KEY ([id_vendedor])
);
END
GO


IF OBJECT_ID(N'dbo.categorias', N'U') IS NULL
BEGIN
CREATE TABLE dbo.categorias (
	[id_categoria] BIGINT IDENTITY(1,1) NOT NULL,
	[nombre] VARCHAR(100) NOT NULL,
	[creado_por] BIGINT NULL,
	[fecha_creacion] DATETIME NOT NULL DEFAULT GETDATE(),
	CONSTRAINT PK_categorias PRIMARY KEY ([id_categoria])
);
END
GO


IF OBJECT_ID(N'dbo.control_de_tasas', N'U') IS NULL
BEGIN
CREATE TABLE dbo.control_de_tasas (
	[id_tasa] BIGINT IDENTITY(1,1) NOT NULL,
	[fecha_tasa] DATETIME NOT NULL DEFAULT GETDATE(),
	[tasa_dolar_bcv] DECIMAL(10,2) NOT NULL,
	[tasa_dolar_paralelo] DECIMAL(10,2) NULL,
	[tasa_cop] DECIMAL(10,2) NULL,
	[modificado_por] BIGINT NULL,
	[creado_por] BIGINT NULL,
	CONSTRAINT PK_control_de_tasas PRIMARY KEY ([id_tasa])
);
END
GO


IF OBJECT_ID(N'dbo.clientes', N'U') IS NULL
BEGIN
CREATE TABLE dbo.clientes (
	[id_cliente] BIGINT IDENTITY(1,1) NOT NULL,
	[id_legal] VARCHAR(20) NULL,
	[codigo_cliente] VARCHAR(20) NULL UNIQUE,
	[identificacion_cliente] VARCHAR(20) NULL UNIQUE,
	[nombre_razon_social] VARCHAR(200) NOT NULL,
	[telefono] VARCHAR(20) NULL,
	[email] VARCHAR(150) NULL,
	[direccion] VARCHAR(255) NULL,
	[limite_credito] DECIMAL(18,2) NOT NULL DEFAULT 0.00,
	[dias_credito] INT NOT NULL DEFAULT 0,
	[vendedor_cliente] BIGINT NULL,
	[creado_por] BIGINT NULL,
	[fecha_creacion] DATETIME NOT NULL DEFAULT GETDATE(),
	[id_categoria_cliente] BIGINT NULL,
	CONSTRAINT PK_clientes PRIMARY KEY ([id_cliente])
);
END
GO


IF OBJECT_ID(N'dbo.proveedores', N'U') IS NULL
BEGIN
CREATE TABLE dbo.proveedores (
	[id_proveedor] BIGINT IDENTITY(1,1) NOT NULL,
	[id_legal] VARCHAR(20) NULL,
	[codigo_proveedor] VARCHAR(20) NULL UNIQUE,
	[identificacion_proveedor] VARCHAR(20) NULL UNIQUE,
	[nombre_razon_social] VARCHAR(200) NOT NULL,
	[telefono] VARCHAR(20) NULL,
	[email] VARCHAR(150) NULL,
	[direccion] VARCHAR(255) NULL,
	[limite_credito] DECIMAL(18,2) NOT NULL DEFAULT 0.00,
	[dias_credito] INT NOT NULL DEFAULT 0,
	[creado_por] BIGINT NULL,
	[fecha_creacion] DATETIME NOT NULL DEFAULT GETDATE(),
	CONSTRAINT PK_proveedores PRIMARY KEY ([id_proveedor])
);
END
GO


IF OBJECT_ID(N'dbo.inventario', N'U') IS NULL
BEGIN
CREATE TABLE dbo.inventario (
	[id_producto] BIGINT IDENTITY(1,1) NOT NULL,
	[id_categoria] BIGINT NOT NULL,
	[cod_producto] VARCHAR(20) NOT NULL UNIQUE,
	[nombre_producto] VARCHAR(200) NOT NULL,
	[descripcion_producto] VARCHAR(MAX) NULL,
	[cantidad_caja] DECIMAL(12,2) NOT NULL DEFAULT 0.000,
	[cantidad_unidad] DECIMAL(12,2) NOT NULL DEFAULT 0.000,
	[costo_producto] DECIMAL(18,2) NOT NULL DEFAULT 0.00,
	[fecha_registro] DATETIME NOT NULL DEFAULT GETDATE(),
	[fecha_vencimiento] DATE NULL,
	[creado_por] BIGINT NULL,
	CONSTRAINT PK_inventario PRIMARY KEY ([id_producto])
);
END
GO


IF OBJECT_ID(N'dbo.factura_venta', N'U') IS NULL
BEGIN
CREATE TABLE dbo.factura_venta (
	[id_factura] BIGINT IDENTITY(1,1) NOT NULL,
	[numero_factura] VARCHAR(20) NOT NULL UNIQUE,
	[id_cliente_factura] BIGINT NOT NULL,
	[id_usuario_factura] BIGINT NULL,
	[fecha_emision] DATETIME NOT NULL DEFAULT GETDATE(),
	[total_venta] DECIMAL(18,2) NOT NULL DEFAULT 0.00,
	[estado_factura] VARCHAR(20) NOT NULL DEFAULT 'EMITIDA',
	[id_tasa_factura] BIGINT NULL,
	[condicion_pago] VARCHAR(10) NOT NULL CONSTRAINT CK_factura_venta_condicion_pago CHECK ([condicion_pago] IN ('contado','credito')),
	[fecha_vencimiento] DATE NULL,
	[observaciones_factura] VARCHAR(255) NULL,
	[id_vendedor] BIGINT NULL,
	[modificado_por] BIGINT NULL,
	CONSTRAINT PK_factura_venta PRIMARY KEY ([id_factura])
);
END
GO


IF OBJECT_ID(N'dbo.factura_detalle', N'U') IS NULL
BEGIN
CREATE TABLE dbo.factura_detalle (
	[id_factura_detalle] BIGINT IDENTITY(1,1) NOT NULL,
	[id_factura] BIGINT NOT NULL,
	[id_producto_factura] BIGINT NOT NULL,
	[descripcion] VARCHAR(255) NULL,
	[cantidad_producto] DECIMAL(12,2) NOT NULL,
	[observaciones_item] VARCHAR(255) NULL,
	[precio_unitario] DECIMAL(18,2) NOT NULL,
	CONSTRAINT PK_factura_detalle PRIMARY KEY ([id_factura_detalle])
);
END
GO


IF OBJECT_ID(N'dbo.cuentas_por_cobrar', N'U') IS NULL
BEGIN
CREATE TABLE dbo.cuentas_por_cobrar (
	[id_cuenta_por_cobrar] BIGINT IDENTITY(1,1) NOT NULL,
	[id_factura] BIGINT NOT NULL,
	[saldo_pendiente] DECIMAL(18,2) NOT NULL,
	[fecha_vencimiento] DATE NULL,
	[estado] VARCHAR(10) NOT NULL DEFAULT 'pendiente' CONSTRAINT CK_cxc_estado CHECK ([estado] IN ('pendiente','parcial','pagada','vencida')),
	[creado_por] BIGINT NULL,
	[fecha_creacion] DATETIME NULL,
	CONSTRAINT PK_cuentas_por_cobrar PRIMARY KEY ([id_cuenta_por_cobrar])
);
END
GO


IF OBJECT_ID(N'dbo.cuentas_por_pagar', N'U') IS NULL
BEGIN
CREATE TABLE dbo.cuentas_por_pagar (
	[id_cuenta] BIGINT IDENTITY(1,1) NOT NULL,
	[saldo_pendiente] DECIMAL(18,2) NOT NULL,
	[fecha_emision] DATE NULL,
	[fecha_vencimiento] DATE NULL,
	[estado] VARCHAR(10) NOT NULL DEFAULT 'pendiente' CONSTRAINT CK_cxp_estado CHECK ([estado] IN ('pendiente','parcial','pagada','vencida')),
	[id_compra] BIGINT NOT NULL,
	[creado_por] BIGINT NULL,
	[fecha_creacion] DATETIME NULL,
	CONSTRAINT PK_cuentas_por_pagar PRIMARY KEY ([id_cuenta])
);
END
GO


IF OBJECT_ID(N'dbo.bancos', N'U') IS NULL
BEGIN
CREATE TABLE dbo.bancos (
	[id_banco] BIGINT IDENTITY(1,1) NOT NULL,
	[codigo_banco] CHAR(4) NULL,
	[nombre_banco] VARCHAR(100) NULL,
	[tipo_banco] VARCHAR(30) NULL,
	[identificacion_banco] VARCHAR(20) NULL UNIQUE,
	[correo_banco] VARCHAR(150) NULL,
	[numero_telefono_banco] VARCHAR(20) NULL,
	[modificado_por] BIGINT NULL,
	[creado_por] BIGINT NULL,
	[fecha_creacion] DATETIME NULL,
	CONSTRAINT PK_bancos PRIMARY KEY ([id_banco])
);
END
GO


IF OBJECT_ID(N'dbo.cuentas_bancarias', N'U') IS NULL
BEGIN
CREATE TABLE dbo.cuentas_bancarias (
	[id_cuenta] BIGINT IDENTITY(1,1) NOT NULL,
	[id_banco] BIGINT NULL,
	[numero_cuenta] VARCHAR(30) NULL,
	[tipo_cuenta_banco] VARCHAR(10) NULL CONSTRAINT CK_cuentas_bancarias_tipo CHECK ([tipo_cuenta_banco] IN ('ahorro','corriente')),
	[nombre_titular] VARCHAR(150) NULL,
	[identificacion_titular] VARCHAR(20) NULL,
	[saldo_total_banco] DECIMAL(18,2) NOT NULL DEFAULT 0.00,
	[creado_por] BIGINT NULL,
	[fecha_creacion] DATETIME NULL,
	CONSTRAINT PK_cuentas_bancarias PRIMARY KEY ([id_cuenta])
);
END
GO


IF OBJECT_ID(N'dbo.banco_movimientos', N'U') IS NULL
BEGIN
CREATE TABLE dbo.banco_movimientos (
	[id_movimiento] BIGINT IDENTITY(1,1) NOT NULL,
	[id_cuenta] BIGINT NULL,
	[tipo_movimiento] VARCHAR(15) NULL CONSTRAINT CK_banco_movimientos_tipo CHECK ([tipo_movimiento] IN ('abono','cargo','transferencia','deposito')),
	[monto_movimiento] DECIMAL(18,2) NULL,
	[fecha_movimiento] DATETIME NULL,
	[referencia_movimiento] VARCHAR(100) NULL,
	[descripcion_movimiento] VARCHAR(255) NULL,
	[creado_por] BIGINT NULL,
	[fecha_creacion] DATETIME NULL,
	[id_pago_cobro] BIGINT NULL,
	[id_pago_proveedor] BIGINT NULL,
	CONSTRAINT PK_banco_movimientos PRIMARY KEY ([id_movimiento])
);
END
GO


IF OBJECT_ID(N'dbo.cajas', N'U') IS NULL
BEGIN
CREATE TABLE dbo.cajas (
	[id_caja] BIGINT IDENTITY(1,1) NOT NULL,
	[nombre_caja] VARCHAR(50) NULL,
	[estado_caja] VARCHAR(20) NULL,
	[saldo_apertura] DECIMAL(18,2) NOT NULL DEFAULT 0.00,
	[saldo_cierre] DECIMAL(18,2) NULL,
	[fecha_apertura] DATETIME NULL,
	[fecha_cierre] DATETIME NULL,
	[id_usuario] BIGINT NULL, -- Responsable de la apertura/cierre del turno de caja
	[modificado_por] BIGINT NULL,
	CONSTRAINT PK_cajas PRIMARY KEY ([id_caja])
);
END
GO


IF OBJECT_ID(N'dbo.caja_movimientos', N'U') IS NULL
BEGIN
CREATE TABLE dbo.caja_movimientos (
	[id_movimiento] BIGINT IDENTITY(1,1) NOT NULL,
	[id_caja] BIGINT NULL,
	[tipo_movimiento] VARCHAR(10) NULL CONSTRAINT CK_caja_movimientos_tipo CHECK ([tipo_movimiento] IN ('entrada','salida')),
	[descripcion_movimiento] VARCHAR(255) NULL,
	[monto_movimiento] DECIMAL(18,2) NULL,
	[fecha_registro] DATETIME NULL,
	[id_pago_cobro] BIGINT NULL, -- Pago de cobro a cliente que origina el movimiento
	[id_pago_proveedor] BIGINT NULL, -- Pago a proveedor que origina el movimiento
	[creado_por] BIGINT NULL,
	CONSTRAINT PK_caja_movimientos PRIMARY KEY ([id_movimiento])
);
END
GO


IF OBJECT_ID(N'dbo.compras', N'U') IS NULL
BEGIN
CREATE TABLE dbo.compras ( -- Cabecera de compras a proveedores
	[id_compra] BIGINT IDENTITY(1,1) NOT NULL,
	[numero_compra] VARCHAR(20) NOT NULL UNIQUE,
	[id_proveedor] BIGINT NOT NULL,
	[id_usuario_compra] BIGINT NULL,
	[fecha_emision] DATETIME NULL,
	[total_compra] DECIMAL(18,2) NOT NULL,
	[estado_compra] VARCHAR(20) NULL,
	[id_tasa_compra] BIGINT NULL,
	[condicion_pago] VARCHAR(10) NOT NULL CONSTRAINT CK_compras_condicion_pago CHECK ([condicion_pago] IN ('contado','credito')),
	[fecha_vencimiento] DATE NULL,
	[observaciones_compra] VARCHAR(255) NULL,
	[modificado_por] BIGINT NULL,
	CONSTRAINT PK_compras PRIMARY KEY ([id_compra])
);
END
GO


IF OBJECT_ID(N'dbo.compra_detalle', N'U') IS NULL
BEGIN
CREATE TABLE dbo.compra_detalle ( -- Lineas de detalle de cada compra
	[id_compra_detalle] BIGINT IDENTITY(1,1) NOT NULL,
	[id_compra] BIGINT NOT NULL,
	[id_producto_compra] BIGINT NOT NULL,
	[descripcion] VARCHAR(255) NULL,
	[cantidad_producto] DECIMAL(12,2) NOT NULL,
	[costo_unitario] DECIMAL(18,2) NOT NULL,
	[observaciones_item] VARCHAR(255) NULL,
	CONSTRAINT PK_compra_detalle PRIMARY KEY ([id_compra_detalle])
);
END
GO


IF OBJECT_ID(N'dbo.producto_precios', N'U') IS NULL
BEGIN
CREATE TABLE dbo.producto_precios ( -- Lista de niveles de precio por producto (1FN: desacopla grupos repetitivos de inventario)
	[id_producto_precio] BIGINT IDENTITY(1,1) NOT NULL,
	[id_producto] BIGINT NOT NULL,
	[tipo_precio] VARCHAR(10) NOT NULL CONSTRAINT CK_producto_precios_tipo CHECK ([tipo_precio] IN ('DETAL','MAYOR','ESPECIAL')),
	[porcentaje_ganancia] DECIMAL(10,2) NOT NULL DEFAULT 0.00,
	[precio_venta] DECIMAL(18,2) NOT NULL,
	CONSTRAINT PK_producto_precios PRIMARY KEY ([id_producto_precio]),
	CONSTRAINT UQ_producto_tipo_precio UNIQUE ([id_producto], [tipo_precio])
);
END
GO


IF OBJECT_ID(N'dbo.pagos_cobros', N'U') IS NULL
BEGIN
CREATE TABLE dbo.pagos_cobros ( -- Pagos de cobros a clientes vinculados directamente a la cuenta por cobrar (elimina el polimorfismo de pagos)
	[id_pago_cobro] BIGINT IDENTITY(1,1) NOT NULL,
	[id_cuenta_por_cobrar] BIGINT NOT NULL,
	[id_cuenta_bancaria] BIGINT NULL,
	[id_caja] BIGINT NULL,
	[id_tasa] BIGINT NULL,
	[metodo_pago] VARCHAR(20) NOT NULL CONSTRAINT CK_pagos_cobros_metodo CHECK ([metodo_pago] IN ('efectivo','transferencia','cheque','tarjeta','punto_de_venta')),
	[monto] DECIMAL(18,2) NOT NULL,
	[referencia] VARCHAR(100) NULL,
	[fecha_pago] DATETIME NOT NULL DEFAULT GETDATE(),
	[creado_por] BIGINT NULL,
	CONSTRAINT PK_pagos_cobros PRIMARY KEY ([id_pago_cobro])
);
END
GO


IF OBJECT_ID(N'dbo.pagos_proveedores', N'U') IS NULL
BEGIN
CREATE TABLE dbo.pagos_proveedores ( -- Abonos y pagos a proveedores vinculados directamente a la cuenta por pagar
	[id_pago_proveedor] BIGINT IDENTITY(1,1) NOT NULL,
	[id_cuenta_por_pagar] BIGINT NOT NULL,
	[id_cuenta_bancaria] BIGINT NULL,
	[id_caja] BIGINT NULL,
	[id_tasa] BIGINT NULL,
	[metodo_pago] VARCHAR(20) NOT NULL CONSTRAINT CK_pagos_proveedores_metodo CHECK ([metodo_pago] IN ('efectivo','transferencia','cheque','tarjeta','punto_de_venta')),
	[monto] DECIMAL(18,2) NOT NULL,
	[referencia] VARCHAR(100) NULL,
	[fecha_pago] DATETIME NOT NULL DEFAULT GETDATE(),
	[creado_por] BIGINT NULL,
	CONSTRAINT PK_pagos_proveedores PRIMARY KEY ([id_pago_proveedor])
);
END
GO


IF OBJECT_ID(N'dbo.comisiones_factura', N'U') IS NULL
BEGIN
CREATE TABLE dbo.comisiones_factura (
	[id_comision] BIGINT IDENTITY(1,1) NOT NULL,
	[monto_base_comision] DECIMAL(18,2) NULL,
	[monto_venta_comision] DECIMAL(18,2) NULL,
	[estado_pago] VARCHAR(10) NOT NULL DEFAULT 'pendiente' CONSTRAINT CK_comisiones_factura_estado CHECK ([estado_pago] IN ('pendiente','pagada')),
	[fecha_calculo] DATETIME NULL,
	[modificador_por] BIGINT NULL,
	[id_factura_detalle] BIGINT NOT NULL UNIQUE,
	[creado_por] BIGINT NULL,
	CONSTRAINT PK_comisiones_factura PRIMARY KEY ([id_comision])
);
END
GO


IF OBJECT_ID(N'dbo.cuentas_por_cobrar_otros', N'U') IS NULL
BEGIN
CREATE TABLE dbo.cuentas_por_cobrar_otros (
	[id_cuenta] BIGINT IDENTITY(1,1) NOT NULL,
	[monto_total] DECIMAL(18,2) NOT NULL,
	[fecha_emision] DATETIME NULL,
	[descripcion] VARCHAR(255) NULL,
	[id_cliente] BIGINT NOT NULL,
	[saldo_pendiente] DECIMAL(18,2) NOT NULL,
	[fecha_vencimiento] DATE NULL,
	[estado] VARCHAR(10) NOT NULL CONSTRAINT CK_cxc_otros_estado CHECK ([estado] IN ('pendiente','parcial','pagada','vencida')),
	[creado_por] BIGINT NULL,
	CONSTRAINT PK_cuentas_por_cobrar_otros PRIMARY KEY ([id_cuenta])
);
END
GO


-- cuentas_por_pagar_otros: pese al nombre (simetria con cuentas_por_cobrar_otros y con el
-- modulo de UI "Cuentas por Pagar Otros"), NO son pasivos comerciales (alquileres, servicios).
-- Registran dinero YA recibido en una cuenta bancaria de la empresa (transferencia de un
-- cliente sin comprobante) que no se ha podido identificar/conciliar. Mientras no se sepa
-- de quien es, es dinero que la empresa "debe explicar/devolver" -> de alli el encaje en el
-- modulo de pagar. [id_movimiento] enlaza opcionalmente al banco_movimientos que trajo el
-- dinero; la conciliacion NO crea un nuevo banco_movimientos (el ingreso ya esta contabilizado
-- alli), solo aplica el monto contra la cuenta_por_cobrar del cliente una vez identificado.
IF OBJECT_ID(N'dbo.cuentas_por_pagar_otros', N'U') IS NULL
BEGIN
CREATE TABLE dbo.cuentas_por_pagar_otros (
	[id_cuenta] BIGINT IDENTITY(1,1) NOT NULL,
	[id_cuenta_bancaria] BIGINT NOT NULL,
	[id_movimiento] BIGINT NULL,
	[monto_total] DECIMAL(18,2) NOT NULL,
	[saldo_pendiente] DECIMAL(18,2) NOT NULL,
	[fecha_recepcion] DATETIME NOT NULL DEFAULT GETDATE(),
	[referencia_bancaria] VARCHAR(100) NULL,
	[descripcion] VARCHAR(255) NULL,
	[estado] VARCHAR(10) NOT NULL DEFAULT 'pendiente' CONSTRAINT CK_cxp_otros_estado CHECK ([estado] IN ('pendiente','parcial','conciliado')),
	[id_cliente_identificado] BIGINT NULL,
	[conciliado_por] BIGINT NULL,
	[fecha_conciliacion] DATETIME NULL,
	[creado_por] BIGINT NULL,
	[fecha_creacion] DATETIME NOT NULL DEFAULT GETDATE(),
	CONSTRAINT PK_cuentas_por_pagar_otros PRIMARY KEY ([id_cuenta])
);
END
GO


IF OBJECT_ID(N'dbo.categorias_cliente', N'U') IS NULL
BEGIN
CREATE TABLE dbo.categorias_cliente (
	[id_categoria_cliente] BIGINT IDENTITY(1,1) NOT NULL,
	[nombre] VARCHAR(50) NOT NULL UNIQUE,
	[descuento_porcentaje] DECIMAL(5,2) NOT NULL DEFAULT 0.00,
	[dias_credito_default] INT NOT NULL DEFAULT 0,
	CONSTRAINT PK_categorias_cliente PRIMARY KEY ([id_categoria_cliente])
);
END
GO


IF OBJECT_ID(N'dbo.configuracion_empresa', N'U') IS NULL
BEGIN
CREATE TABLE dbo.configuracion_empresa (
	[id_config] INT IDENTITY(1,1) NOT NULL,
	[logotipo_empresa] VARBINARY(MAX) NULL,
	[modificado_por] BIGINT NULL,
	[rif_empresa] VARCHAR(20) NULL,
	[razon_social_empresa] VARCHAR(255) NULL,
	[direccion_empresa] VARCHAR(255) NULL,
	[telefono_empresa] VARCHAR(255) NULL,
	CONSTRAINT PK_configuracion_empresa PRIMARY KEY ([id_config])
);
END
GO


-- auditoria: bitacora de eventos criticos (login, apertura/cierre de caja, anulacion de
-- facturas, cambios de tasa, etc.). Tabla append-only para trazabilidad, sin FKs de cascada.
IF OBJECT_ID(N'dbo.auditoria', N'U') IS NULL
BEGIN
CREATE TABLE dbo.auditoria (
	[id_auditoria] BIGINT IDENTITY(1,1) NOT NULL,
	[id_usuario] BIGINT NULL,
	[accion] VARCHAR(50) NOT NULL,
	[modulo] VARCHAR(50) NOT NULL,
	[detalle] VARCHAR(MAX) NULL,
	[fecha_evento] DATETIME NOT NULL DEFAULT GETDATE(),
	CONSTRAINT PK_auditoria PRIMARY KEY ([id_auditoria])
);
END
GO


-- schema_migrations: registro de que cambios de schema (archivos en migrations/) ya se
-- aplicaron en este entorno. Este script (schema_sqlserver.sql) arma el schema completo
-- para un entorno nuevo y se auto-registra como la migracion '0000_baseline' al final del
-- archivo -- a partir de ahi, todo cambio de schema se agrega como un .sql nuevo en
-- migrations/ (aplicado con `python -m app.db.migrar`), nunca editando este archivo. Ver
-- migrations/README.md.
IF OBJECT_ID(N'dbo.schema_migrations', N'U') IS NULL
BEGIN
CREATE TABLE dbo.schema_migrations (
	[version] VARCHAR(255) NOT NULL,
	[aplicada_en] DATETIME NOT NULL DEFAULT GETDATE(),
	CONSTRAINT PK_schema_migrations PRIMARY KEY ([version])
);
END
GO


-- =========================================================================
-- FOREIGN KEYS
-- =========================================================================

ALTER TABLE dbo.control_de_tasas
ADD CONSTRAINT FK_control_de_tasas_modificado_por FOREIGN KEY([modificado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION; -- original: CASCADE/SET NULL — neutralizado, ver nota de cabecera
GO
ALTER TABLE dbo.clientes
ADD CONSTRAINT FK_clientes_vendedor_cliente FOREIGN KEY([vendedor_cliente]) REFERENCES dbo.vendedores([id_vendedor])
ON UPDATE NO ACTION ON DELETE SET NULL;
GO
ALTER TABLE dbo.clientes
ADD CONSTRAINT FK_clientes_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE SET NULL;
GO
ALTER TABLE dbo.proveedores
ADD CONSTRAINT FK_proveedores_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE SET NULL;
GO
ALTER TABLE dbo.inventario
ADD CONSTRAINT FK_inventario_id_categoria FOREIGN KEY([id_categoria]) REFERENCES dbo.categorias([id_categoria])
ON UPDATE NO ACTION ON DELETE NO ACTION; -- original: RESTRICT (equivalente en SQL Server)
GO
ALTER TABLE dbo.inventario
ADD CONSTRAINT FK_inventario_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE SET NULL;
GO
ALTER TABLE dbo.factura_venta
ADD CONSTRAINT FK_factura_venta_id_cliente_factura FOREIGN KEY([id_cliente_factura]) REFERENCES dbo.clientes([id_cliente])
ON UPDATE NO ACTION ON DELETE NO ACTION; -- original: RESTRICT
GO
ALTER TABLE dbo.factura_venta
ADD CONSTRAINT FK_factura_venta_id_tasa_factura FOREIGN KEY([id_tasa_factura]) REFERENCES dbo.control_de_tasas([id_tasa])
ON UPDATE NO ACTION ON DELETE SET NULL;
GO
ALTER TABLE dbo.factura_detalle
ADD CONSTRAINT FK_factura_detalle_id_factura FOREIGN KEY([id_factura]) REFERENCES dbo.factura_venta([id_factura])
ON UPDATE NO ACTION ON DELETE CASCADE;
GO
ALTER TABLE dbo.factura_detalle
ADD CONSTRAINT FK_factura_detalle_id_producto_factura FOREIGN KEY([id_producto_factura]) REFERENCES dbo.inventario([id_producto])
ON UPDATE NO ACTION ON DELETE NO ACTION; -- original: RESTRICT
GO
ALTER TABLE dbo.cuentas_por_cobrar
ADD CONSTRAINT FK_cuentas_por_cobrar_id_factura FOREIGN KEY([id_factura]) REFERENCES dbo.factura_venta([id_factura])
ON UPDATE NO ACTION ON DELETE CASCADE;
GO
ALTER TABLE dbo.banco_movimientos
ADD CONSTRAINT FK_banco_movimientos_id_cuenta FOREIGN KEY([id_cuenta]) REFERENCES dbo.cuentas_bancarias([id_cuenta])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.compras
ADD CONSTRAINT FK_compras_id_proveedor FOREIGN KEY([id_proveedor]) REFERENCES dbo.proveedores([id_proveedor])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.compras
ADD CONSTRAINT FK_compras_id_usuario_compra FOREIGN KEY([id_usuario_compra]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE SET NULL;
GO
ALTER TABLE dbo.compras
ADD CONSTRAINT FK_compras_id_tasa_compra FOREIGN KEY([id_tasa_compra]) REFERENCES dbo.control_de_tasas([id_tasa])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.compra_detalle
ADD CONSTRAINT FK_compra_detalle_id_compra FOREIGN KEY([id_compra]) REFERENCES dbo.compras([id_compra])
ON UPDATE NO ACTION ON DELETE CASCADE;
GO
ALTER TABLE dbo.compra_detalle
ADD CONSTRAINT FK_compra_detalle_id_producto_compra FOREIGN KEY([id_producto_compra]) REFERENCES dbo.inventario([id_producto])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.cuentas_por_pagar
ADD CONSTRAINT FK_cuentas_por_pagar_id_compra FOREIGN KEY([id_compra]) REFERENCES dbo.compras([id_compra])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.bancos
ADD CONSTRAINT FK_bancos_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE SET NULL;
GO
ALTER TABLE dbo.caja_movimientos
ADD CONSTRAINT FK_caja_movimientos_id_caja FOREIGN KEY([id_caja]) REFERENCES dbo.cajas([id_caja])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.bancos
ADD CONSTRAINT FK_bancos_modificado_por FOREIGN KEY([modificado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION; -- original: CASCADE/SET NULL — neutralizado, ver nota de cabecera
GO
ALTER TABLE dbo.cuentas_bancarias
ADD CONSTRAINT FK_cuentas_bancarias_id_banco FOREIGN KEY([id_banco]) REFERENCES dbo.bancos([id_banco])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.factura_venta
ADD CONSTRAINT FK_factura_venta_id_usuario_factura FOREIGN KEY([id_usuario_factura]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE SET NULL;
GO
ALTER TABLE dbo.factura_venta
ADD CONSTRAINT FK_factura_venta_id_vendedor FOREIGN KEY([id_vendedor]) REFERENCES dbo.vendedores([id_vendedor])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.producto_precios
ADD CONSTRAINT FK_producto_precios_id_producto FOREIGN KEY([id_producto]) REFERENCES dbo.inventario([id_producto])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.pagos_cobros
ADD CONSTRAINT FK_pagos_cobros_id_cuenta_por_cobrar FOREIGN KEY([id_cuenta_por_cobrar]) REFERENCES dbo.cuentas_por_cobrar([id_cuenta_por_cobrar])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.pagos_cobros
ADD CONSTRAINT FK_pagos_cobros_id_cuenta_bancaria FOREIGN KEY([id_cuenta_bancaria]) REFERENCES dbo.cuentas_bancarias([id_cuenta])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.pagos_cobros
ADD CONSTRAINT FK_pagos_cobros_id_caja FOREIGN KEY([id_caja]) REFERENCES dbo.cajas([id_caja])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.pagos_cobros
ADD CONSTRAINT FK_pagos_cobros_id_tasa FOREIGN KEY([id_tasa]) REFERENCES dbo.control_de_tasas([id_tasa])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.pagos_cobros
ADD CONSTRAINT FK_pagos_cobros_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.cajas
ADD CONSTRAINT FK_cajas_id_usuario FOREIGN KEY([id_usuario]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.pagos_proveedores
ADD CONSTRAINT FK_pagos_proveedores_id_cuenta_por_pagar FOREIGN KEY([id_cuenta_por_pagar]) REFERENCES dbo.cuentas_por_pagar([id_cuenta])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.pagos_proveedores
ADD CONSTRAINT FK_pagos_proveedores_id_cuenta_bancaria FOREIGN KEY([id_cuenta_bancaria]) REFERENCES dbo.cuentas_bancarias([id_cuenta])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.pagos_proveedores
ADD CONSTRAINT FK_pagos_proveedores_id_caja FOREIGN KEY([id_caja]) REFERENCES dbo.cajas([id_caja])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.pagos_proveedores
ADD CONSTRAINT FK_pagos_proveedores_id_tasa FOREIGN KEY([id_tasa]) REFERENCES dbo.control_de_tasas([id_tasa])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.pagos_proveedores
ADD CONSTRAINT FK_pagos_proveedores_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.caja_movimientos
ADD CONSTRAINT FK_caja_movimientos_id_pago_cobro FOREIGN KEY([id_pago_cobro]) REFERENCES dbo.pagos_cobros([id_pago_cobro])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.caja_movimientos
ADD CONSTRAINT FK_caja_movimientos_id_pago_proveedor FOREIGN KEY([id_pago_proveedor]) REFERENCES dbo.pagos_proveedores([id_pago_proveedor])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.comisiones_factura
ADD CONSTRAINT FK_comisiones_factura_modificador_por FOREIGN KEY([modificador_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.cuentas_por_cobrar_otros
ADD CONSTRAINT FK_cxc_otros_id_cliente FOREIGN KEY([id_cliente]) REFERENCES dbo.clientes([id_cliente])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.comisiones_factura
ADD CONSTRAINT FK_comisiones_factura_id_factura_detalle FOREIGN KEY([id_factura_detalle]) REFERENCES dbo.factura_detalle([id_factura_detalle])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.cuentas_por_cobrar_otros
ADD CONSTRAINT FK_cxc_otros_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.cuentas_por_pagar_otros
ADD CONSTRAINT FK_cxp_otros_id_cuenta_bancaria FOREIGN KEY([id_cuenta_bancaria]) REFERENCES dbo.cuentas_bancarias([id_cuenta])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.cuentas_por_pagar_otros
ADD CONSTRAINT FK_cxp_otros_id_movimiento FOREIGN KEY([id_movimiento]) REFERENCES dbo.banco_movimientos([id_movimiento])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.cuentas_por_pagar_otros
ADD CONSTRAINT FK_cxp_otros_id_cliente_identificado FOREIGN KEY([id_cliente_identificado]) REFERENCES dbo.clientes([id_cliente])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.cuentas_por_pagar_otros
ADD CONSTRAINT FK_cxp_otros_conciliado_por FOREIGN KEY([conciliado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.cuentas_por_pagar_otros
ADD CONSTRAINT FK_cxp_otros_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.categorias
ADD CONSTRAINT FK_categorias_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.cuentas_bancarias
ADD CONSTRAINT FK_cuentas_bancarias_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.cuentas_por_cobrar
ADD CONSTRAINT FK_cuentas_por_cobrar_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.cuentas_por_pagar
ADD CONSTRAINT FK_cuentas_por_pagar_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.banco_movimientos
ADD CONSTRAINT FK_banco_movimientos_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.vendedores
ADD CONSTRAINT FK_vendedores_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.control_de_tasas
ADD CONSTRAINT FK_control_de_tasas_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.caja_movimientos
ADD CONSTRAINT FK_caja_movimientos_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.comisiones_factura
ADD CONSTRAINT FK_comisiones_factura_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.cajas
ADD CONSTRAINT FK_cajas_modificado_por FOREIGN KEY([modificado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.factura_venta
ADD CONSTRAINT FK_factura_venta_modificado_por FOREIGN KEY([modificado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.compras
ADD CONSTRAINT FK_compras_modificado_por FOREIGN KEY([modificado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.banco_movimientos
ADD CONSTRAINT FK_banco_movimientos_id_pago_cobro FOREIGN KEY([id_pago_cobro]) REFERENCES dbo.pagos_cobros([id_pago_cobro])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.banco_movimientos
ADD CONSTRAINT FK_banco_movimientos_id_pago_proveedor FOREIGN KEY([id_pago_proveedor]) REFERENCES dbo.pagos_proveedores([id_pago_proveedor])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.clientes
ADD CONSTRAINT FK_clientes_id_categoria_cliente FOREIGN KEY([id_categoria_cliente]) REFERENCES dbo.categorias_cliente([id_categoria_cliente])
ON UPDATE NO ACTION ON DELETE SET NULL;
GO
ALTER TABLE dbo.usuarios
ADD CONSTRAINT FK_usuarios_id_vendedor_usuario FOREIGN KEY([id_vendedor_usuario]) REFERENCES dbo.vendedores([id_vendedor])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.configuracion_empresa
ADD CONSTRAINT FK_configuracion_empresa_modificado_por FOREIGN KEY([modificado_por]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO
ALTER TABLE dbo.auditoria
ADD CONSTRAINT FK_auditoria_id_usuario FOREIGN KEY([id_usuario]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE SET NULL;
GO
ALTER TABLE dbo.usuarios
ADD CONSTRAINT FK_usuarios_id_rol FOREIGN KEY([id_rol]) REFERENCES dbo.roles([id_rol])
ON UPDATE NO ACTION ON DELETE SET NULL;
GO
ALTER TABLE dbo.rol_permisos
ADD CONSTRAINT FK_rol_permisos_id_rol FOREIGN KEY([id_rol]) REFERENCES dbo.roles([id_rol])
ON UPDATE NO ACTION ON DELETE CASCADE;
GO
ALTER TABLE dbo.rol_permisos
ADD CONSTRAINT FK_rol_permisos_id_permiso FOREIGN KEY([id_permiso]) REFERENCES dbo.permisos([id_permiso])
ON UPDATE NO ACTION ON DELETE CASCADE;
GO


-- =========================================================================
-- SEED: roles base y permisos de catalogo/reportes para el rol VENDEDOR
-- =========================================================================

INSERT INTO dbo.roles ([nombre], [descripcion]) VALUES
('ADMIN', 'Acceso total al sistema'),
('VENDEDOR', 'Fuerza de venta: consulta catalogo y reportes propios'),
('CAJERO', 'Operacion de caja y cobros');
GO

INSERT INTO dbo.permisos ([recurso], [accion], [descripcion]) VALUES
('inventario', 'ver', 'Consultar existencias y precios del catalogo'),
('reportes_ventas', 'ver', 'Visualizar reportes de ventas'),
('reportes_comisiones', 'ver', 'Visualizar reportes de comisiones propias');
GO

INSERT INTO dbo.rol_permisos ([id_rol], [id_permiso])
SELECT r.[id_rol], p.[id_permiso]
FROM dbo.roles r
JOIN dbo.permisos p ON p.[recurso] IN ('inventario', 'reportes_ventas', 'reportes_comisiones') AND p.[accion] = 'ver'
WHERE r.[nombre] = 'VENDEDOR';
GO


-- =========================================================================
-- BLOQUE A: Stock (inventario) — descuenta/repone por venta y por compra
-- Reescrito set-based (inserted/deleted pueden traer varias filas a la vez,
-- a diferencia de MySQL FOR EACH ROW que procesa fila por fila).
-- =========================================================================

CREATE TRIGGER trg_factura_detalle_stock_ins ON dbo.factura_detalle
AFTER INSERT AS
BEGIN
	SET NOCOUNT ON;
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] - agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT [id_producto_factura], SUM([cantidad_producto]) AS [total_cant]
		FROM inserted
		GROUP BY [id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto];
END
GO

CREATE TRIGGER trg_factura_detalle_stock_upd ON dbo.factura_detalle
AFTER UPDATE AS
BEGIN
	SET NOCOUNT ON;
	-- revierte lo que tenian las filas antes de modificarse
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] + agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT [id_producto_factura], SUM([cantidad_producto]) AS [total_cant]
		FROM deleted
		GROUP BY [id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto];

	-- aplica lo que quedo tras la modificacion
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] - agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT [id_producto_factura], SUM([cantidad_producto]) AS [total_cant]
		FROM inserted
		GROUP BY [id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto];
END
GO

CREATE TRIGGER trg_factura_detalle_stock_del ON dbo.factura_detalle
AFTER DELETE AS
BEGIN
	SET NOCOUNT ON;
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] + agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT [id_producto_factura], SUM([cantidad_producto]) AS [total_cant]
		FROM deleted
		GROUP BY [id_producto_factura]
	) agg ON agg.[id_producto_factura] = inv.[id_producto];
END
GO

CREATE TRIGGER trg_compra_detalle_stock_ins ON dbo.compra_detalle
AFTER INSERT AS
BEGIN
	SET NOCOUNT ON;
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] + agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT [id_producto_compra], SUM([cantidad_producto]) AS [total_cant]
		FROM inserted
		GROUP BY [id_producto_compra]
	) agg ON agg.[id_producto_compra] = inv.[id_producto];
END
GO

CREATE TRIGGER trg_compra_detalle_stock_upd ON dbo.compra_detalle
AFTER UPDATE AS
BEGIN
	SET NOCOUNT ON;
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] - agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT [id_producto_compra], SUM([cantidad_producto]) AS [total_cant]
		FROM deleted
		GROUP BY [id_producto_compra]
	) agg ON agg.[id_producto_compra] = inv.[id_producto];

	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] + agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT [id_producto_compra], SUM([cantidad_producto]) AS [total_cant]
		FROM inserted
		GROUP BY [id_producto_compra]
	) agg ON agg.[id_producto_compra] = inv.[id_producto];
END
GO

CREATE TRIGGER trg_compra_detalle_stock_del ON dbo.compra_detalle
AFTER DELETE AS
BEGIN
	SET NOCOUNT ON;
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] - agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT [id_producto_compra], SUM([cantidad_producto]) AS [total_cant]
		FROM deleted
		GROUP BY [id_producto_compra]
	) agg ON agg.[id_producto_compra] = inv.[id_producto];
END
GO


-- =========================================================================
-- BLOQUE B: Totales de cabecera — factura_venta.total_venta / compras.total_compra
-- =========================================================================

CREATE TRIGGER trg_factura_total_ins ON dbo.factura_detalle
AFTER INSERT AS
BEGIN
	SET NOCOUNT ON;
	UPDATE fv
	SET fv.[total_venta] = ISNULL((SELECT SUM(fd.[cantidad_producto] * fd.[precio_unitario]) FROM dbo.factura_detalle fd WHERE fd.[id_factura] = fv.[id_factura]), 0)
	FROM dbo.factura_venta fv
	WHERE fv.[id_factura] IN (SELECT DISTINCT [id_factura] FROM inserted);
END
GO

CREATE TRIGGER trg_factura_total_upd ON dbo.factura_detalle
AFTER UPDATE AS
BEGIN
	SET NOCOUNT ON;
	UPDATE fv
	SET fv.[total_venta] = ISNULL((SELECT SUM(fd.[cantidad_producto] * fd.[precio_unitario]) FROM dbo.factura_detalle fd WHERE fd.[id_factura] = fv.[id_factura]), 0)
	FROM dbo.factura_venta fv
	WHERE fv.[id_factura] IN (SELECT [id_factura] FROM inserted UNION SELECT [id_factura] FROM deleted);
END
GO

CREATE TRIGGER trg_factura_total_del ON dbo.factura_detalle
AFTER DELETE AS
BEGIN
	SET NOCOUNT ON;
	UPDATE fv
	SET fv.[total_venta] = ISNULL((SELECT SUM(fd.[cantidad_producto] * fd.[precio_unitario]) FROM dbo.factura_detalle fd WHERE fd.[id_factura] = fv.[id_factura]), 0)
	FROM dbo.factura_venta fv
	WHERE fv.[id_factura] IN (SELECT DISTINCT [id_factura] FROM deleted);
END
GO

CREATE TRIGGER trg_compra_total_ins ON dbo.compra_detalle
AFTER INSERT AS
BEGIN
	SET NOCOUNT ON;
	UPDATE c
	SET c.[total_compra] = ISNULL((SELECT SUM(cd.[cantidad_producto] * cd.[costo_unitario]) FROM dbo.compra_detalle cd WHERE cd.[id_compra] = c.[id_compra]), 0)
	FROM dbo.compras c
	WHERE c.[id_compra] IN (SELECT DISTINCT [id_compra] FROM inserted);
END
GO

CREATE TRIGGER trg_compra_total_upd ON dbo.compra_detalle
AFTER UPDATE AS
BEGIN
	SET NOCOUNT ON;
	UPDATE c
	SET c.[total_compra] = ISNULL((SELECT SUM(cd.[cantidad_producto] * cd.[costo_unitario]) FROM dbo.compra_detalle cd WHERE cd.[id_compra] = c.[id_compra]), 0)
	FROM dbo.compras c
	WHERE c.[id_compra] IN (SELECT [id_compra] FROM inserted UNION SELECT [id_compra] FROM deleted);
END
GO

CREATE TRIGGER trg_compra_total_del ON dbo.compra_detalle
AFTER DELETE AS
BEGIN
	SET NOCOUNT ON;
	UPDATE c
	SET c.[total_compra] = ISNULL((SELECT SUM(cd.[cantidad_producto] * cd.[costo_unitario]) FROM dbo.compra_detalle cd WHERE cd.[id_compra] = c.[id_compra]), 0)
	FROM dbo.compras c
	WHERE c.[id_compra] IN (SELECT DISTINCT [id_compra] FROM deleted);
END
GO


-- =========================================================================
-- BLOQUE C: Cuentas por cobrar / pagar — apertura, saldo, validaciones de pago
-- pagos_cobros/pagos_proveedores usan INSTEAD OF INSERT: SQL Server no tiene
-- BEFORE INSERT, asi que la validacion + el insert real + la aplicacion del
-- pago se resuelven en un unico trigger (equivalente a los 2 triggers MySQL).
-- =========================================================================

CREATE TRIGGER trg_factura_venta_cxc ON dbo.factura_venta
AFTER UPDATE AS
BEGIN
	SET NOCOUNT ON;

	INSERT INTO dbo.cuentas_por_cobrar ([id_factura], [saldo_pendiente], [fecha_vencimiento], [estado], [creado_por], [fecha_creacion])
	SELECT i.[id_factura], i.[total_venta], i.[fecha_vencimiento], 'pendiente', i.[id_usuario_factura], GETDATE()
	FROM inserted i
	JOIN deleted d ON d.[id_factura] = i.[id_factura]
	WHERE i.[condicion_pago] = 'credito'
		AND i.[total_venta] <> d.[total_venta]
		AND NOT EXISTS (SELECT 1 FROM dbo.cuentas_por_cobrar c WHERE c.[id_factura] = i.[id_factura]);

	UPDATE c
	SET c.[saldo_pendiente] = i.[total_venta]
	FROM dbo.cuentas_por_cobrar c
	JOIN inserted i ON i.[id_factura] = c.[id_factura]
	JOIN deleted d ON d.[id_factura] = i.[id_factura]
	WHERE i.[condicion_pago] = 'credito'
		AND i.[total_venta] <> d.[total_venta]
		AND c.[estado] = 'pendiente';
END
GO

CREATE TRIGGER trg_compras_cxp ON dbo.compras
AFTER UPDATE AS
BEGIN
	SET NOCOUNT ON;

	INSERT INTO dbo.cuentas_por_pagar ([saldo_pendiente], [fecha_emision], [fecha_vencimiento], [estado], [id_compra], [creado_por], [fecha_creacion])
	SELECT i.[total_compra], i.[fecha_emision], i.[fecha_vencimiento], 'pendiente', i.[id_compra], i.[id_usuario_compra], GETDATE()
	FROM inserted i
	JOIN deleted d ON d.[id_compra] = i.[id_compra]
	WHERE i.[condicion_pago] = 'credito'
		AND i.[total_compra] <> d.[total_compra]
		AND NOT EXISTS (SELECT 1 FROM dbo.cuentas_por_pagar c WHERE c.[id_compra] = i.[id_compra]);

	UPDATE c
	SET c.[saldo_pendiente] = i.[total_compra]
	FROM dbo.cuentas_por_pagar c
	JOIN inserted i ON i.[id_compra] = c.[id_compra]
	JOIN deleted d ON d.[id_compra] = i.[id_compra]
	WHERE i.[condicion_pago] = 'credito'
		AND i.[total_compra] <> d.[total_compra]
		AND c.[estado] = 'pendiente';
END
GO

CREATE TRIGGER trg_pagos_cobros_io ON dbo.pagos_cobros
INSTEAD OF INSERT AS
BEGIN
	SET NOCOUNT ON;

	IF EXISTS (
		SELECT 1 FROM inserted
		WHERE ([id_cuenta_bancaria] IS NULL AND [id_caja] IS NULL)
			OR ([id_cuenta_bancaria] IS NOT NULL AND [id_caja] IS NOT NULL)
	)
	BEGIN
		RAISERROR('pagos_cobros: indique exactamente un origen (cuenta bancaria o caja)', 16, 1);
		RETURN;
	END

	IF EXISTS (
		SELECT 1 FROM inserted i
		JOIN dbo.cuentas_por_cobrar c ON c.[id_cuenta_por_cobrar] = i.[id_cuenta_por_cobrar]
		WHERE i.[monto] > c.[saldo_pendiente]
	)
	BEGIN
		RAISERROR('pagos_cobros: el monto excede el saldo pendiente', 16, 1);
		RETURN;
	END

	DECLARE @nuevos TABLE (
		[id_pago_cobro] BIGINT,
		[id_cuenta_por_cobrar] BIGINT,
		[id_cuenta_bancaria] BIGINT,
		[id_caja] BIGINT,
		[monto] DECIMAL(18,2),
		[referencia] VARCHAR(100),
		[fecha_pago] DATETIME,
		[creado_por] BIGINT
	);

	INSERT INTO dbo.pagos_cobros ([id_cuenta_por_cobrar], [id_cuenta_bancaria], [id_caja], [id_tasa], [metodo_pago], [monto], [referencia], [fecha_pago], [creado_por])
	OUTPUT inserted.[id_pago_cobro], inserted.[id_cuenta_por_cobrar], inserted.[id_cuenta_bancaria], inserted.[id_caja], inserted.[monto], inserted.[referencia], inserted.[fecha_pago], inserted.[creado_por]
	INTO @nuevos
	SELECT [id_cuenta_por_cobrar], [id_cuenta_bancaria], [id_caja], [id_tasa], [metodo_pago], [monto], [referencia], ISNULL([fecha_pago], GETDATE()), [creado_por]
	FROM inserted;

	UPDATE c
	SET c.[saldo_pendiente] = c.[saldo_pendiente] - n.[monto],
		c.[estado] = CASE WHEN c.[saldo_pendiente] - n.[monto] <= 0 THEN 'pagada' ELSE 'parcial' END
	FROM dbo.cuentas_por_cobrar c
	JOIN @nuevos n ON n.[id_cuenta_por_cobrar] = c.[id_cuenta_por_cobrar];

	INSERT INTO dbo.banco_movimientos ([id_cuenta], [tipo_movimiento], [monto_movimiento], [fecha_movimiento], [referencia_movimiento], [descripcion_movimiento], [creado_por], [fecha_creacion], [id_pago_cobro])
	SELECT [id_cuenta_bancaria], 'abono', [monto], [fecha_pago], [referencia], 'Cobro a cliente', [creado_por], GETDATE(), [id_pago_cobro]
	FROM @nuevos WHERE [id_cuenta_bancaria] IS NOT NULL;

	INSERT INTO dbo.caja_movimientos ([id_caja], [tipo_movimiento], [descripcion_movimiento], [monto_movimiento], [fecha_registro], [id_pago_cobro], [creado_por])
	SELECT [id_caja], 'entrada', 'Cobro a cliente', [monto], [fecha_pago], [id_pago_cobro], [creado_por]
	FROM @nuevos WHERE [id_caja] IS NOT NULL;

	-- Un INSTEAD OF INSERT reemplaza el INSERT del caller: SCOPE_IDENTITY() no ve el
	-- id generado aqui adentro (es un scope distinto) y @@IDENTITY devolveria el de
	-- banco_movimientos/caja_movimientos (insertados despues). Este SELECT final es
	-- el unico resultset no vacio que llega al cliente antes del "select
	-- scope_identity()" que SQLAlchemy agrega automaticamente, asi que su primera fila
	-- es la que SQLAlchemy toma como id autogenerado — permite usar
	-- session.add(PagoCobro(...)); session.commit() de forma normal, igual que en el
	-- resto de los servicios.
	SELECT [id_pago_cobro] FROM @nuevos;
END
GO

CREATE TRIGGER trg_pagos_proveedores_io ON dbo.pagos_proveedores
INSTEAD OF INSERT AS
BEGIN
	SET NOCOUNT ON;

	IF EXISTS (
		SELECT 1 FROM inserted
		WHERE ([id_cuenta_bancaria] IS NULL AND [id_caja] IS NULL)
			OR ([id_cuenta_bancaria] IS NOT NULL AND [id_caja] IS NOT NULL)
	)
	BEGIN
		RAISERROR('pagos_proveedores: indique exactamente un origen (cuenta bancaria o caja)', 16, 1);
		RETURN;
	END

	IF EXISTS (
		SELECT 1 FROM inserted i
		JOIN dbo.cuentas_por_pagar c ON c.[id_cuenta] = i.[id_cuenta_por_pagar]
		WHERE i.[monto] > c.[saldo_pendiente]
	)
	BEGIN
		RAISERROR('pagos_proveedores: el monto excede el saldo pendiente', 16, 1);
		RETURN;
	END

	DECLARE @nuevos TABLE (
		[id_pago_proveedor] BIGINT,
		[id_cuenta_por_pagar] BIGINT,
		[id_cuenta_bancaria] BIGINT,
		[id_caja] BIGINT,
		[monto] DECIMAL(18,2),
		[referencia] VARCHAR(100),
		[fecha_pago] DATETIME,
		[creado_por] BIGINT
	);

	INSERT INTO dbo.pagos_proveedores ([id_cuenta_por_pagar], [id_cuenta_bancaria], [id_caja], [id_tasa], [metodo_pago], [monto], [referencia], [fecha_pago], [creado_por])
	OUTPUT inserted.[id_pago_proveedor], inserted.[id_cuenta_por_pagar], inserted.[id_cuenta_bancaria], inserted.[id_caja], inserted.[monto], inserted.[referencia], inserted.[fecha_pago], inserted.[creado_por]
	INTO @nuevos
	SELECT [id_cuenta_por_pagar], [id_cuenta_bancaria], [id_caja], [id_tasa], [metodo_pago], [monto], [referencia], ISNULL([fecha_pago], GETDATE()), [creado_por]
	FROM inserted;

	UPDATE c
	SET c.[saldo_pendiente] = c.[saldo_pendiente] - n.[monto],
		c.[estado] = CASE WHEN c.[saldo_pendiente] - n.[monto] <= 0 THEN 'pagada' ELSE 'parcial' END
	FROM dbo.cuentas_por_pagar c
	JOIN @nuevos n ON n.[id_cuenta_por_pagar] = c.[id_cuenta];

	INSERT INTO dbo.banco_movimientos ([id_cuenta], [tipo_movimiento], [monto_movimiento], [fecha_movimiento], [referencia_movimiento], [descripcion_movimiento], [creado_por], [fecha_creacion], [id_pago_proveedor])
	SELECT [id_cuenta_bancaria], 'cargo', [monto], [fecha_pago], [referencia], 'Pago a proveedor', [creado_por], GETDATE(), [id_pago_proveedor]
	FROM @nuevos WHERE [id_cuenta_bancaria] IS NOT NULL;

	INSERT INTO dbo.caja_movimientos ([id_caja], [tipo_movimiento], [descripcion_movimiento], [monto_movimiento], [fecha_registro], [id_pago_proveedor], [creado_por])
	SELECT [id_caja], 'salida', 'Pago a proveedor', [monto], [fecha_pago], [id_pago_proveedor], [creado_por]
	FROM @nuevos WHERE [id_caja] IS NOT NULL;

	-- Ver el comentario equivalente en trg_pagos_cobros_io.
	SELECT [id_pago_proveedor] FROM @nuevos;
END
GO


-- =========================================================================
-- BLOQUE D: Bancos y caja — saldo de cuenta bancaria y cierre de turno de caja
-- =========================================================================

CREATE TRIGGER trg_banco_movimientos_saldo ON dbo.banco_movimientos
AFTER INSERT AS
BEGIN
	SET NOCOUNT ON;
	UPDATE cb
	SET cb.[saldo_total_banco] = cb.[saldo_total_banco] + agg.[delta]
	FROM dbo.cuentas_bancarias cb
	JOIN (
		SELECT [id_cuenta], SUM(CASE WHEN [tipo_movimiento] IN ('abono','deposito') THEN [monto_movimiento] ELSE -[monto_movimiento] END) AS [delta]
		FROM inserted
		GROUP BY [id_cuenta]
	) agg ON agg.[id_cuenta] = cb.[id_cuenta];
END
GO

-- Requiere RECURSIVE_TRIGGERS OFF a nivel de base de datos (valor por defecto en SQL Server)
-- para que el UPDATE interno sobre `cajas` no vuelva a disparar este mismo trigger.
CREATE TRIGGER trg_cajas_cierre ON dbo.cajas
AFTER UPDATE AS
BEGIN
	SET NOCOUNT ON;
	UPDATE c
	SET c.[saldo_cierre] = i.[saldo_apertura] + ISNULL((
		SELECT SUM(CASE WHEN cm.[tipo_movimiento] = 'entrada' THEN cm.[monto_movimiento] ELSE -cm.[monto_movimiento] END)
		FROM dbo.caja_movimientos cm
		WHERE cm.[id_caja] = i.[id_caja]
			AND cm.[fecha_registro] >= d.[fecha_apertura]
			AND cm.[fecha_registro] <= i.[fecha_cierre]
	), 0)
	FROM dbo.cajas c
	JOIN inserted i ON i.[id_caja] = c.[id_caja]
	JOIN deleted d ON d.[id_caja] = i.[id_caja]
	WHERE i.[fecha_cierre] IS NOT NULL AND d.[fecha_cierre] IS NULL;
END
GO


-- =========================================================================
-- BASELINE: marca este script como la migracion '0000_baseline' ya aplicada
-- =========================================================================

IF NOT EXISTS (SELECT 1 FROM dbo.schema_migrations WHERE [version] = '0000_baseline')
BEGIN
	INSERT INTO dbo.schema_migrations ([version]) VALUES ('0000_baseline');
END
GO
