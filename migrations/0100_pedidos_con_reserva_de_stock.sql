-- Pedidos de venta tomados por los vendedores (futura app movil) con reserva de stock.
--
-- Un pedido NO es una factura: no mueve inventario, no abre cuentas por cobrar ni genera
-- comisiones. Solo aparta unidades hasta que caja/admin lo aprueba y lo convierte en factura
-- (VentaService.emitir_factura(id_pedido=...)), o hasta que se rechaza, anula o vence.
--
-- La reserva NO es una columna ni la mantiene un trigger: se calcula sumando las lineas de los
-- pedidos que hoy apartan stock (app/services/reservas_stock.py, una sola consulta con la hora
-- del servidor). Asi no puede desincronizarse del inventario (no hay un contador que corregir
-- tras una anulacion o un fallo a medias) y no se toca ningun trigger de facturacion.
-- inventario.cantidad_unidad sigue siendo el stock REAL; el disponible es
-- cantidad_unidad - unidades reservadas.
--
-- Que aparta stock:
--   * APROBADO: hasta que se factura o se anula.
--   * ENVIADO : solo hasta fecha_vencimiento_reserva. Pasada esa fecha deja de contarse solo
--               (sin depender de ningun job); PedidoService.vencer_pendientes() solo actualiza
--               el estado visible a VENCIDO.
-- RECHAZADO, ANULADO, VENCIDO y FACTURADO no apartan nada (al facturar, el trigger de
-- factura_detalle descuenta el stock real).

-- Numero de pedido legible y atomico entre estaciones (mismo mecanismo que codigo_cliente, 0093).
CREATE SEQUENCE dbo.seq_numero_pedido AS BIGINT START WITH 1 INCREMENT BY 1 NO CYCLE NO CACHE;
GO

CREATE TABLE dbo.pedidos (
	[id_pedido] BIGINT IDENTITY(1,1) NOT NULL,
	[numero_pedido] VARCHAR(20) NOT NULL
		CONSTRAINT DF_pedidos_numero_pedido
		DEFAULT ('PED-' + RIGHT('000000' + CAST(NEXT VALUE FOR dbo.seq_numero_pedido AS VARCHAR(12)), 6)),
	[id_cliente] BIGINT NOT NULL,
	[id_vendedor] BIGINT NOT NULL,
	[condicion_pago] VARCHAR(10) NOT NULL,
	[estado] VARCHAR(20) NOT NULL CONSTRAINT DF_pedidos_estado DEFAULT 'ENVIADO',
	[observaciones] VARCHAR(255) NULL,
	-- Por que se rechazo o se anulo (lo ve el vendedor).
	[motivo] VARCHAR(255) NULL,
	-- Identificador generado por la app movil al armar el pedido: si reenvia el mismo pedido
	-- (se corto la senal tras enviar), el servidor devuelve el que ya existe en vez de duplicarlo.
	[id_cliente_local] VARCHAR(64) NULL,
	[fecha_creacion] DATETIME NOT NULL CONSTRAINT DF_pedidos_fecha_creacion DEFAULT GETDATE(),
	[fecha_vencimiento_reserva] DATETIME NULL,
	[id_usuario_creador] BIGINT NULL,
	[id_usuario_revisor] BIGINT NULL,
	[fecha_revision] DATETIME NULL,
	[id_factura] BIGINT NULL,
	[fecha_modificacion] DATETIME NULL,
	CONSTRAINT PK_pedidos PRIMARY KEY ([id_pedido]),
	CONSTRAINT UQ_pedidos_numero_pedido UNIQUE ([numero_pedido]),
	CONSTRAINT CK_pedidos_estado CHECK ([estado] IN
		('ENVIADO', 'APROBADO', 'RECHAZADO', 'FACTURADO', 'ANULADO', 'VENCIDO')),
	CONSTRAINT CK_pedidos_condicion_pago CHECK ([condicion_pago] IN ('contado', 'credito')),
	CONSTRAINT FK_pedidos_cliente FOREIGN KEY ([id_cliente]) REFERENCES dbo.clientes([id_cliente]),
	CONSTRAINT FK_pedidos_vendedor FOREIGN KEY ([id_vendedor]) REFERENCES dbo.vendedores([id_vendedor]),
	CONSTRAINT FK_pedidos_usuario_creador FOREIGN KEY ([id_usuario_creador]) REFERENCES dbo.usuarios([id_usuario]),
	CONSTRAINT FK_pedidos_usuario_revisor FOREIGN KEY ([id_usuario_revisor]) REFERENCES dbo.usuarios([id_usuario]),
	CONSTRAINT FK_pedidos_factura FOREIGN KEY ([id_factura]) REFERENCES dbo.factura_venta([id_factura])
);
GO

CREATE TABLE dbo.pedido_detalle (
	[id_pedido_detalle] BIGINT IDENTITY(1,1) NOT NULL,
	[id_pedido] BIGINT NOT NULL,
	[id_producto] BIGINT NOT NULL,
	[descripcion] VARCHAR(255) NULL,
	-- Lo que pidio el vendedor: cajas (bulto) o unidades sueltas, igual que factura_detalle.
	[cantidad] NUMERIC(12,2) NOT NULL,
	[tipo_venta] VARCHAR(10) NOT NULL,
	-- Cuantas unidades de inventario aparta la linea (bulto = cantidad * unidades por caja). Se
	-- guarda al crear el pedido: si luego cambia cantidad_caja del producto, lo apartado no cambia.
	[unidades_reservadas] NUMERIC(12,2) NOT NULL,
	[precio_unitario] NUMERIC(18,2) NOT NULL,
	CONSTRAINT PK_pedido_detalle PRIMARY KEY ([id_pedido_detalle]),
	CONSTRAINT CK_pedido_detalle_cantidad CHECK ([cantidad] > 0),
	CONSTRAINT CK_pedido_detalle_unidades CHECK ([unidades_reservadas] > 0),
	CONSTRAINT CK_pedido_detalle_precio CHECK ([precio_unitario] > 0),
	CONSTRAINT CK_pedido_detalle_tipo_venta CHECK ([tipo_venta] IN ('bulto', 'unidad')),
	CONSTRAINT FK_pedido_detalle_pedido FOREIGN KEY ([id_pedido]) REFERENCES dbo.pedidos([id_pedido]),
	CONSTRAINT FK_pedido_detalle_producto FOREIGN KEY ([id_producto]) REFERENCES dbo.inventario([id_producto])
);
GO

-- Un mismo id_cliente_local no se repite dentro de un vendedor (NULL no cuenta).
CREATE UNIQUE INDEX UQ_pedidos_vendedor_id_cliente_local
	ON dbo.pedidos ([id_vendedor], [id_cliente_local]) WHERE [id_cliente_local] IS NOT NULL;
GO

CREATE INDEX IX_pedidos_estado ON dbo.pedidos ([estado]) INCLUDE ([fecha_vencimiento_reserva]);
GO

CREATE INDEX IX_pedidos_vendedor_fecha ON dbo.pedidos ([id_vendedor], [fecha_creacion] DESC);
GO

CREATE INDEX IX_pedidos_cliente ON dbo.pedidos ([id_cliente]);
GO

CREATE INDEX IX_pedido_detalle_pedido ON dbo.pedido_detalle ([id_pedido]);
GO

CREATE INDEX IX_pedido_detalle_producto ON dbo.pedido_detalle ([id_producto]) INCLUDE ([unidades_reservadas]);
GO

-- Permisos. ADMIN bypassa la matriz. VENDEDOR toma y consulta sus pedidos (el alcance a "solo los
-- suyos" lo aplica el servicio); CAJERO los revisa, aprueba y factura.
-- CK_permisos_accion solo admite 'ver'/'crear'/'editar'/'eliminar': "revisar" se mapea a 'editar',
-- el mismo criterio de 0021/0029/0048 para acciones que no son un CRUD literal.
INSERT INTO dbo.permisos ([recurso], [accion], [descripcion]) VALUES
('pedidos', 'ver', 'Consultar pedidos de venta'),
('pedidos', 'crear', 'Tomar pedidos de venta y anular los propios'),
('pedidos', 'editar', 'Revisar pedidos de venta: aprobar, rechazar o anular, y convertirlos en factura');
GO

INSERT INTO dbo.rol_permisos ([id_rol], [id_permiso])
SELECT r.[id_rol], p.[id_permiso]
FROM dbo.roles r
JOIN dbo.permisos p ON p.[recurso] = 'pedidos' AND p.[accion] IN ('ver', 'crear')
WHERE r.[nombre] = 'VENDEDOR';
GO

INSERT INTO dbo.rol_permisos ([id_rol], [id_permiso])
SELECT r.[id_rol], p.[id_permiso]
FROM dbo.roles r
JOIN dbo.permisos p ON p.[recurso] = 'pedidos' AND p.[accion] IN ('ver', 'editar')
WHERE r.[nombre] = 'CAJERO';
GO
