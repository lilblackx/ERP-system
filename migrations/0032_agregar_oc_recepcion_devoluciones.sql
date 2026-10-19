-- Flujo completo de Compras estilo ERP: Orden de Compra (OC) -> Nota de Recepcion (NR)
-- -> Compra (factura del proveedor) -> Pago (CxP, ya existente). Agrega tablas nuevas sin
-- tocar ninguna tabla/trigger existente salvo dos puntos quirurgicos, explicados abajo.
--
-- Decisiones de diseno de esta migracion:
--
-- 1) El STOCK se mueve en nota_recepcion_detalle (al recibir mercancia), NO en
--    compra_detalle (al facturar) -- ver trg_nota_recepcion_detalle_ins. Se usa la
--    cantidad BRUTA recibida (cantidad_recibida), no neta de rechazos:
--    cantidad_rechazada en la linea de NR es solo informativo hasta que una
--    nota_devolucion real decide devolver esas unidades al proveedor, momento en el que
--    trg_nota_devolucion_detalle_ins recien ahi descuenta el stock.
--
-- 2) compra_detalle.stock_ya_contabilizado (nueva columna, DEFAULT 0) le dice a
--    trg_compra_detalle_stock_ins si esta linea de Compra ya sumo su stock antes via una
--    NR (flujo nuevo, columna en 1) o si tiene que sumarlo el mismo, como siempre (flujo
--    viejo, sin OC/NR -- columna se queda en su DEFAULT 0). Este es el UNICO trigger
--    existente que se modifica (DROP + CREATE, mismo patron que 0024_pagos_contado_
--    multimetodo.sql con trg_pagos_cobros_io) y el cambio es un AND extra en el WHERE:
--    con la columna en 0 en todas las filas actuales, el comportamiento de hoy no cambia.
--
-- 3) compra_oc_enmienda: el efecto automatico (trg_compra_oc_enmienda_autorizar) solo
--    ajusta CompraOC.cantidad_solicitada a nivel de CABECERA, no por linea -- la tabla no
--    tiene id_oc_detalle porque una enmienda de cantidad hoy se autoriza a nivel de OC
--    completa. Repartir el ajuste entre lineas especificas queda pendiente para cuando se
--    necesite de verdad (no hay caso de uso todavia que lo pida).
--
-- 4) id_usuario_autorizador en compra_oc_enmienda es NULL-able (se llena recien al
--    autorizar) y se agrega id_usuario_solicitante (quien la pidio) -- separado del
--    autorizador, igual que el resto de los flujos de autorizacion del sistema
--    (AutorizacionDialog: quien pide != quien autoriza).
--
-- Este paso es SOLO schema (tablas + triggers). app/db/models.py y los servicios/UI que
-- usan estas tablas se agregan en un paso posterior.


-- =========================================================================
-- BLOQUE A: Tablas nuevas
-- =========================================================================

IF OBJECT_ID(N'dbo.compra_oc', N'U') IS NULL
BEGIN
CREATE TABLE dbo.compra_oc ( -- Orden de compra: paso 1 del flujo OC -> NR -> Compra -> Pago
	[id_oc] BIGINT IDENTITY(1,1) NOT NULL,
	[id_proveedor] BIGINT NOT NULL,
	[numero_oc] VARCHAR(20) NOT NULL UNIQUE,
	[fecha_oc] DATETIME NOT NULL DEFAULT GETDATE(),
	[fecha_estimada_entrega] DATETIME NULL,
	[cantidad_solicitada] DECIMAL(18,4) NOT NULL DEFAULT 0,
	[cantidad_recibida] DECIMAL(18,4) NOT NULL DEFAULT 0,
	[cantidad_facturada] DECIMAL(18,4) NOT NULL DEFAULT 0,
	[estado] VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE' CONSTRAINT CK_compra_oc_estado CHECK ([estado] IN ('PENDIENTE','PARCIAL','COMPLETA','ANULADA')),
	[motivo_cierre] VARCHAR(500) NULL,
	[total_oc] DECIMAL(18,2) NOT NULL DEFAULT 0,
	[observaciones] VARCHAR(500) NULL,
	[id_usuario_creador] BIGINT NULL,
	[fecha_creacion] DATETIME NOT NULL DEFAULT GETDATE(),
	[id_usuario_modificador] BIGINT NULL,
	[fecha_modificacion] DATETIME NULL,
	CONSTRAINT PK_compra_oc PRIMARY KEY ([id_oc])
);
END
GO


IF OBJECT_ID(N'dbo.compra_oc_detalle', N'U') IS NULL
BEGIN
CREATE TABLE dbo.compra_oc_detalle ( -- Lineas de producto de una OC
	[id_detalle] BIGINT IDENTITY(1,1) NOT NULL,
	[id_oc] BIGINT NOT NULL,
	[id_producto] BIGINT NOT NULL,
	[cantidad_solicitada] DECIMAL(18,4) NOT NULL,
	[cantidad_recibida] DECIMAL(18,4) NOT NULL DEFAULT 0,
	[cantidad_facturada] DECIMAL(18,4) NOT NULL DEFAULT 0,
	[cantidad_pendiente] DECIMAL(18,4) NOT NULL DEFAULT 0,
	[precio_unitario] DECIMAL(18,4) NOT NULL,
	[total_linea] DECIMAL(18,2) NOT NULL,
	CONSTRAINT PK_compra_oc_detalle PRIMARY KEY ([id_detalle])
);
END
GO


IF OBJECT_ID(N'dbo.compra_oc_enmienda', N'U') IS NULL
BEGIN
CREATE TABLE dbo.compra_oc_enmienda ( -- Cambios autorizados a una OC ya emitida
	[id_enmienda] BIGINT IDENTITY(1,1) NOT NULL,
	[id_oc] BIGINT NOT NULL,
	[numero_enmienda] VARCHAR(20) NOT NULL UNIQUE,
	[fecha_enmienda] DATETIME NOT NULL DEFAULT GETDATE(),
	[tipo_cambio] VARCHAR(20) NOT NULL CONSTRAINT CK_compra_oc_enmienda_tipo CHECK ([tipo_cambio] IN ('CANTIDAD','PRECIO','FECHA')),
	[cantidad_anterior] DECIMAL(18,4) NULL,
	[cantidad_nueva] DECIMAL(18,4) NULL,
	[precio_anterior] DECIMAL(18,4) NULL,
	[precio_nuevo] DECIMAL(18,4) NULL,
	[fecha_entrega_anterior] DATETIME NULL,
	[fecha_entrega_nueva] DATETIME NULL,
	[motivo] VARCHAR(500) NOT NULL,
	[observaciones] VARCHAR(500) NULL,
	[id_usuario_solicitante] BIGINT NOT NULL,
	[id_usuario_autorizador] BIGINT NULL,
	[fecha_autorizacion] DATETIME NULL,
	[estado_enmienda] VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE' CONSTRAINT CK_compra_oc_enmienda_estado CHECK ([estado_enmienda] IN ('PENDIENTE','AUTORIZADA','RECHAZADA')),
	CONSTRAINT PK_compra_oc_enmienda PRIMARY KEY ([id_enmienda])
);
END
GO


IF OBJECT_ID(N'dbo.nota_recepcion', N'U') IS NULL
BEGIN
CREATE TABLE dbo.nota_recepcion ( -- Entrada de almacen: paso 2, separada de la factura del proveedor
	[id_nr] BIGINT IDENTITY(1,1) NOT NULL,
	[id_oc] BIGINT NOT NULL,
	[numero_nr] VARCHAR(20) NOT NULL UNIQUE,
	[fecha_recepcion] DATETIME NOT NULL DEFAULT GETDATE(),
	[estado] VARCHAR(20) NOT NULL DEFAULT 'RECIBIDA' CONSTRAINT CK_nota_recepcion_estado CHECK ([estado] IN ('RECIBIDA','FACTURADA','PARCIAL','ANULADA')),
	[observaciones] VARCHAR(500) NULL,
	[id_usuario_recepcion] BIGINT NOT NULL,
	[fecha_creacion] DATETIME NOT NULL DEFAULT GETDATE(),
	CONSTRAINT PK_nota_recepcion PRIMARY KEY ([id_nr])
);
END
GO


IF OBJECT_ID(N'dbo.nota_recepcion_detalle', N'U') IS NULL
BEGIN
CREATE TABLE dbo.nota_recepcion_detalle ( -- Lineas de producto recibidas en una NR, vinculadas a su linea de OC
	[id_detalle] BIGINT IDENTITY(1,1) NOT NULL,
	[id_nr] BIGINT NOT NULL,
	[id_oc_detalle] BIGINT NOT NULL,
	[id_producto] BIGINT NOT NULL,
	[cantidad_recibida] DECIMAL(18,4) NOT NULL,
	[cantidad_rechazada] DECIMAL(18,4) NOT NULL DEFAULT 0,
	[precio_unitario] DECIMAL(18,4) NOT NULL,
	[total_linea] DECIMAL(18,2) NOT NULL,
	CONSTRAINT PK_nota_recepcion_detalle PRIMARY KEY ([id_detalle])
);
END
GO


IF OBJECT_ID(N'dbo.nota_devolucion', N'U') IS NULL
BEGIN
CREATE TABLE dbo.nota_devolucion ( -- Mercancia rechazada que se devuelve al proveedor
	[id_devolucion] BIGINT IDENTITY(1,1) NOT NULL,
	[id_nr] BIGINT NOT NULL,
	[numero_nota_devolucion] VARCHAR(20) NOT NULL UNIQUE,
	[fecha_devolucion] DATETIME NOT NULL DEFAULT GETDATE(),
	[motivo] VARCHAR(50) NOT NULL,
	[cantidad_total] DECIMAL(18,4) NOT NULL DEFAULT 0,
	[estado] VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE' CONSTRAINT CK_nota_devolucion_estado CHECK ([estado] IN ('PENDIENTE','DEVUELTO')),
	[observaciones] VARCHAR(500) NULL,
	[id_usuario_creador] BIGINT NULL,
	[fecha_creacion] DATETIME NOT NULL DEFAULT GETDATE(),
	CONSTRAINT PK_nota_devolucion PRIMARY KEY ([id_devolucion])
);
END
GO


IF OBJECT_ID(N'dbo.nota_devolucion_detalle', N'U') IS NULL
BEGIN
CREATE TABLE dbo.nota_devolucion_detalle ( -- Lineas de producto devueltas al proveedor
	[id_detalle] BIGINT IDENTITY(1,1) NOT NULL,
	[id_devolucion] BIGINT NOT NULL,
	[id_producto] BIGINT NOT NULL,
	[cantidad_devuelta] DECIMAL(18,4) NOT NULL,
	[precio_unitario] DECIMAL(18,4) NOT NULL,
	[total_linea] DECIMAL(18,2) NOT NULL,
	CONSTRAINT PK_nota_devolucion_detalle PRIMARY KEY ([id_detalle])
);
END
GO


-- =========================================================================
-- BLOQUE B: Columnas nuevas en tablas existentes (sin tocar las columnas actuales)
-- =========================================================================

ALTER TABLE dbo.compra_detalle ADD [stock_ya_contabilizado] BIT NOT NULL DEFAULT 0;
GO

ALTER TABLE dbo.compras ADD [id_oc] BIGINT NULL;
GO


-- =========================================================================
-- BLOQUE C: Foreign keys de las tablas nuevas
-- =========================================================================

ALTER TABLE dbo.compra_oc
ADD CONSTRAINT FK_compra_oc_id_proveedor FOREIGN KEY([id_proveedor]) REFERENCES dbo.proveedores([id_proveedor])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.compra_oc
ADD CONSTRAINT FK_compra_oc_id_usuario_creador FOREIGN KEY([id_usuario_creador]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.compra_oc
ADD CONSTRAINT FK_compra_oc_id_usuario_modificador FOREIGN KEY([id_usuario_modificador]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.compra_oc_detalle
ADD CONSTRAINT FK_compra_oc_detalle_id_oc FOREIGN KEY([id_oc]) REFERENCES dbo.compra_oc([id_oc])
ON UPDATE NO ACTION ON DELETE CASCADE;
GO

ALTER TABLE dbo.compra_oc_detalle
ADD CONSTRAINT FK_compra_oc_detalle_id_producto FOREIGN KEY([id_producto]) REFERENCES dbo.inventario([id_producto])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.compra_oc_enmienda
ADD CONSTRAINT FK_compra_oc_enmienda_id_oc FOREIGN KEY([id_oc]) REFERENCES dbo.compra_oc([id_oc])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.compra_oc_enmienda
ADD CONSTRAINT FK_compra_oc_enmienda_solicitante FOREIGN KEY([id_usuario_solicitante]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.compra_oc_enmienda
ADD CONSTRAINT FK_compra_oc_enmienda_autorizador FOREIGN KEY([id_usuario_autorizador]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.nota_recepcion
ADD CONSTRAINT FK_nota_recepcion_id_oc FOREIGN KEY([id_oc]) REFERENCES dbo.compra_oc([id_oc])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.nota_recepcion
ADD CONSTRAINT FK_nota_recepcion_id_usuario FOREIGN KEY([id_usuario_recepcion]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.nota_recepcion_detalle
ADD CONSTRAINT FK_nota_recepcion_detalle_id_nr FOREIGN KEY([id_nr]) REFERENCES dbo.nota_recepcion([id_nr])
ON UPDATE NO ACTION ON DELETE CASCADE;
GO

ALTER TABLE dbo.nota_recepcion_detalle
ADD CONSTRAINT FK_nota_recepcion_detalle_id_oc_detalle FOREIGN KEY([id_oc_detalle]) REFERENCES dbo.compra_oc_detalle([id_detalle])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.nota_recepcion_detalle
ADD CONSTRAINT FK_nota_recepcion_detalle_id_producto FOREIGN KEY([id_producto]) REFERENCES dbo.inventario([id_producto])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.nota_devolucion
ADD CONSTRAINT FK_nota_devolucion_id_nr FOREIGN KEY([id_nr]) REFERENCES dbo.nota_recepcion([id_nr])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.nota_devolucion
ADD CONSTRAINT FK_nota_devolucion_id_usuario FOREIGN KEY([id_usuario_creador]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.nota_devolucion_detalle
ADD CONSTRAINT FK_nota_devolucion_detalle_id_devolucion FOREIGN KEY([id_devolucion]) REFERENCES dbo.nota_devolucion([id_devolucion])
ON UPDATE NO ACTION ON DELETE CASCADE;
GO

ALTER TABLE dbo.nota_devolucion_detalle
ADD CONSTRAINT FK_nota_devolucion_detalle_id_producto FOREIGN KEY([id_producto]) REFERENCES dbo.inventario([id_producto])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

ALTER TABLE dbo.compras
ADD CONSTRAINT FK_compras_id_oc FOREIGN KEY([id_oc]) REFERENCES dbo.compra_oc([id_oc])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO


-- =========================================================================
-- BLOQUE D: Indices (mismo criterio que 0007_indices_rendimiento.sql: toda FK usada
-- para filtrar/joinear, mas el estado de cabecera)
-- =========================================================================

CREATE INDEX IX_compra_oc_id_proveedor ON dbo.compra_oc ([id_proveedor]);
GO

CREATE INDEX IX_compra_oc_estado ON dbo.compra_oc ([estado]);
GO

CREATE INDEX IX_compra_oc_detalle_id_oc ON dbo.compra_oc_detalle ([id_oc]);
GO

CREATE INDEX IX_compra_oc_enmienda_id_oc ON dbo.compra_oc_enmienda ([id_oc]);
GO

CREATE INDEX IX_nota_recepcion_id_oc ON dbo.nota_recepcion ([id_oc]);
GO

CREATE INDEX IX_nota_recepcion_detalle_id_nr ON dbo.nota_recepcion_detalle ([id_nr]);
GO

CREATE INDEX IX_nota_recepcion_detalle_id_oc_detalle ON dbo.nota_recepcion_detalle ([id_oc_detalle]);
GO

CREATE INDEX IX_nota_devolucion_id_nr ON dbo.nota_devolucion ([id_nr]);
GO

CREATE INDEX IX_nota_devolucion_detalle_id_devolucion ON dbo.nota_devolucion_detalle ([id_devolucion]);
GO

CREATE INDEX IX_compras_id_oc ON dbo.compras ([id_oc]);
GO


-- =========================================================================
-- BLOQUE E: Trigger existente modificado (unico punto que toca algo ya existente)
-- =========================================================================

DROP TRIGGER trg_compra_detalle_stock_ins;
GO

-- Identico al original salvo el WHERE [stock_ya_contabilizado] = 0 agregado al agregado:
-- con la columna en su DEFAULT 0 para toda fila existente/del flujo viejo, el
-- comportamiento no cambia. Las filas del flujo nuevo (Compra vinculada a una OC ya
-- recibida) llegan con stock_ya_contabilizado = 1 -- ver docstring de esta migracion,
-- punto 2 -- y quedan afuera de esta suma porque su stock ya lo sumo
-- trg_nota_recepcion_detalle_ins al recibir la mercancia.
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
		WHERE [stock_ya_contabilizado] = 0
		GROUP BY [id_producto_compra]
	) agg ON agg.[id_producto_compra] = inv.[id_producto];
END
GO


-- =========================================================================
-- BLOQUE F: Triggers nuevos
-- =========================================================================

CREATE TRIGGER trg_nota_recepcion_detalle_ins ON dbo.nota_recepcion_detalle
AFTER INSERT AS
BEGIN
	SET NOCOUNT ON;

	-- 1) cantidad_recibida/cantidad_pendiente por linea de OC, recalculada desde la tabla
	-- completa (no solo "inserted") -- mismo criterio que trg_compra_total_ins -- para que
	-- sea correcta sin importar cuantas recepciones parciales hubo antes.
	UPDATE cod
	SET cod.[cantidad_recibida] = ISNULL((
			SELECT SUM(nrd.[cantidad_recibida]) FROM dbo.nota_recepcion_detalle nrd WHERE nrd.[id_oc_detalle] = cod.[id_detalle]
		), 0),
		cod.[cantidad_pendiente] = cod.[cantidad_solicitada] - ISNULL((
			SELECT SUM(nrd.[cantidad_recibida]) FROM dbo.nota_recepcion_detalle nrd WHERE nrd.[id_oc_detalle] = cod.[id_detalle]
		), 0)
	FROM dbo.compra_oc_detalle cod
	WHERE cod.[id_detalle] IN (SELECT DISTINCT [id_oc_detalle] FROM inserted);

	-- 2) cantidad_recibida + estado de la OC, derivados de sus lineas. Nunca pisa una OC ya
	-- ANULADA -- una recepcion tardia sobre una OC anulada no deberia resucitarla.
	UPDATE co
	SET co.[cantidad_recibida] = ISNULL((
			SELECT SUM(cod.[cantidad_recibida]) FROM dbo.compra_oc_detalle cod WHERE cod.[id_oc] = co.[id_oc]
		), 0),
		co.[estado] = CASE
			WHEN ISNULL((SELECT SUM(cod.[cantidad_recibida]) FROM dbo.compra_oc_detalle cod WHERE cod.[id_oc] = co.[id_oc]), 0)
				>= ISNULL((SELECT SUM(cod.[cantidad_solicitada]) FROM dbo.compra_oc_detalle cod WHERE cod.[id_oc] = co.[id_oc]), 0)
			THEN 'COMPLETA'
			ELSE 'PARCIAL'
		END
	FROM dbo.compra_oc co
	WHERE co.[estado] <> 'ANULADA'
		AND co.[id_oc] IN (
			SELECT DISTINCT cod.[id_oc]
			FROM dbo.compra_oc_detalle cod
			JOIN inserted i ON i.[id_oc_detalle] = cod.[id_detalle]
		);

	-- 3) Stock sube al recibir (no al facturar, ver BLOQUE E) -- cantidad BRUTA recibida;
	-- cantidad_rechazada es solo informativo en esta linea, se descuenta recien si/cuando
	-- exista una nota_devolucion real (ver trg_nota_devolucion_detalle_ins). Agregado por
	-- producto (no fila por fila) para no perder cantidad si una misma NR trae varias
	-- lineas del mismo producto.
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] + agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT [id_producto], SUM([cantidad_recibida]) AS [total_cant]
		FROM inserted
		GROUP BY [id_producto]
	) agg ON agg.[id_producto] = inv.[id_producto];
END
GO


CREATE TRIGGER trg_nota_devolucion_detalle_ins ON dbo.nota_devolucion_detalle
AFTER INSERT AS
BEGIN
	SET NOCOUNT ON;

	-- Devuelve al proveedor mercancia que ya estaba contada en stock (sumada por
	-- trg_nota_recepcion_detalle_ins, punto 3) -- agregado por producto, no fila por fila,
	-- por la misma razon que ese trigger.
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] - agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT [id_producto], SUM([cantidad_devuelta]) AS [total_cant]
		FROM inserted
		GROUP BY [id_producto]
	) agg ON agg.[id_producto] = inv.[id_producto];
END
GO


CREATE TRIGGER trg_compra_oc_enmienda_autorizar ON dbo.compra_oc_enmienda
AFTER UPDATE AS
BEGIN
	SET NOCOUNT ON;

	IF UPDATE([estado_enmienda])
	BEGIN
		-- Set-based (no variables escalares, ver docstring de esta migracion): cubre un
		-- UPDATE por lote con varias filas, no solo una. "Acaba de pasar a AUTORIZADA en
		-- este UPDATE" = join contra deleted comparando el estado anterior, mismo patron
		-- que trg_compras_cxp/trg_factura_venta_cxc para detectar una transicion real.
		UPDATE co
		SET co.[cantidad_solicitada] = i.[cantidad_nueva],
			co.[estado] = 'PARCIAL'
		FROM dbo.compra_oc co
		JOIN inserted i ON i.[id_oc] = co.[id_oc]
		JOIN deleted d ON d.[id_enmienda] = i.[id_enmienda]
		WHERE i.[estado_enmienda] = 'AUTORIZADA'
			AND d.[estado_enmienda] <> 'AUTORIZADA'
			AND i.[tipo_cambio] = 'CANTIDAD'
			AND i.[cantidad_nueva] IS NOT NULL;
	END
END
GO
