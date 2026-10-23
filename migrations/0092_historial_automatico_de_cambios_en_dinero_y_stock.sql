-- Blindaje de la base (2/2): historial automatico de cambios a dinero y stock.
--
-- Cada INSERT/UPDATE/DELETE sobre las tablas de dinero e inventario deja una fila en
-- auditoria_cambios_db con el valor ANTERIOR y el NUEVO (JSON), quien lo hizo (usuario SQL), desde que
-- PC y con que programa (APP_NAME). La app se identifica con "APP=NexoERP" en su cadena
-- de conexion (app/config.py): un cambio hecho desde Excel, SSMS o cualquier otro programa queda
-- marcado `fuera_de_la_app = 1`, y la campana de notificaciones avisa a quien ve la auditoria
-- (NotificacionesService._cambios_directos_en_la_base). No impide el cambio -- lo hace visible y
-- reversible (el JSON anterior sirve para restaurar el valor).
--
-- Triggers AFTER en vez de tablas temporales (SYSTEM_VERSIONING): pagos_cobros y pagos_proveedores
-- tienen triggers INSTEAD OF, que SQL Server no admite en una tabla temporal.
--
-- Una actualizacion que no cambia ningun valor (p. ej. el recalculo de cajas del inventario que
-- sigue a cada venta) no genera fila.

IF OBJECT_ID(N'dbo.auditoria_cambios_db', N'U') IS NULL
BEGIN
CREATE TABLE dbo.auditoria_cambios_db (
	[id_cambio] BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_auditoria_cambios_db PRIMARY KEY,
	[fecha] DATETIME2 NOT NULL CONSTRAINT DF_auditoria_cambios_db_fecha DEFAULT SYSDATETIME(),
	[tabla] SYSNAME NOT NULL,
	[operacion] CHAR(1) NOT NULL CONSTRAINT CK_auditoria_cambios_db_operacion CHECK ([operacion] IN ('I', 'U', 'D')),
	[clave] NVARCHAR(100) NOT NULL,
	[anterior] NVARCHAR(MAX) NULL,
	[nuevo] NVARCHAR(MAX) NULL,
	[usuario_sql] NVARCHAR(128) NOT NULL CONSTRAINT DF_auditoria_cambios_db_usuario DEFAULT SUSER_SNAME(),
	[equipo] NVARCHAR(128) NULL CONSTRAINT DF_auditoria_cambios_db_equipo DEFAULT HOST_NAME(),
	[aplicacion] NVARCHAR(128) NULL CONSTRAINT DF_auditoria_cambios_db_aplicacion DEFAULT APP_NAME(),
	[fuera_de_la_app] AS (CASE WHEN [aplicacion] LIKE N'NexoERP%' THEN CAST(0 AS BIT) ELSE CAST(1 AS BIT) END) PERSISTED
);
CREATE INDEX IX_auditoria_cambios_db_fecha ON dbo.auditoria_cambios_db ([fecha]);
CREATE INDEX IX_auditoria_cambios_db_tabla ON dbo.auditoria_cambios_db ([tabla], [clave]);
END
GO

-- La bitacora de cambios no se borra ni se edita con el usuario de la aplicacion (ver 0091).
DENY DELETE ON dbo.auditoria_cambios_db TO [nexo_app_sin_borrado];
DENY UPDATE ON dbo.auditoria_cambios_db TO [nexo_app_sin_borrado];
GO

IF OBJECT_ID(N'dbo.trg_cambios_inventario', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_cambios_inventario;
GO

CREATE TRIGGER dbo.trg_cambios_inventario ON dbo.inventario
AFTER INSERT, UPDATE, DELETE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted) RETURN;

	INSERT INTO dbo.auditoria_cambios_db ([tabla], [operacion], [clave], [anterior], [nuevo])
	SELECT
		N'inventario',
		CASE WHEN d.[id_producto] IS NULL THEN 'I' WHEN i.[id_producto] IS NULL THEN 'D' ELSE 'U' END,
		CAST(COALESCE(i.[id_producto], d.[id_producto]) AS NVARCHAR(100)),
		j.[anterior],
		j.[nuevo]
	FROM inserted i
	FULL OUTER JOIN deleted d ON d.[id_producto] = i.[id_producto]
	CROSS APPLY (
		SELECT
			CASE WHEN d.[id_producto] IS NULL THEN NULL
				ELSE (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [anterior],
			CASE WHEN i.[id_producto] IS NULL THEN NULL
				ELSE (SELECT i.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [nuevo]
	) j
	WHERE d.[id_producto] IS NULL OR i.[id_producto] IS NULL OR ISNULL(j.[anterior], N'') <> ISNULL(j.[nuevo], N'');
END
GO

IF OBJECT_ID(N'dbo.trg_cambios_cuentas_bancarias', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_cambios_cuentas_bancarias;
GO

CREATE TRIGGER dbo.trg_cambios_cuentas_bancarias ON dbo.cuentas_bancarias
AFTER INSERT, UPDATE, DELETE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted) RETURN;

	INSERT INTO dbo.auditoria_cambios_db ([tabla], [operacion], [clave], [anterior], [nuevo])
	SELECT
		N'cuentas_bancarias',
		CASE WHEN d.[id_cuenta] IS NULL THEN 'I' WHEN i.[id_cuenta] IS NULL THEN 'D' ELSE 'U' END,
		CAST(COALESCE(i.[id_cuenta], d.[id_cuenta]) AS NVARCHAR(100)),
		j.[anterior],
		j.[nuevo]
	FROM inserted i
	FULL OUTER JOIN deleted d ON d.[id_cuenta] = i.[id_cuenta]
	CROSS APPLY (
		SELECT
			CASE WHEN d.[id_cuenta] IS NULL THEN NULL
				ELSE (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [anterior],
			CASE WHEN i.[id_cuenta] IS NULL THEN NULL
				ELSE (SELECT i.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [nuevo]
	) j
	WHERE d.[id_cuenta] IS NULL OR i.[id_cuenta] IS NULL OR ISNULL(j.[anterior], N'') <> ISNULL(j.[nuevo], N'');
END
GO

IF OBJECT_ID(N'dbo.trg_cambios_banco_movimientos', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_cambios_banco_movimientos;
GO

CREATE TRIGGER dbo.trg_cambios_banco_movimientos ON dbo.banco_movimientos
AFTER INSERT, UPDATE, DELETE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted) RETURN;

	INSERT INTO dbo.auditoria_cambios_db ([tabla], [operacion], [clave], [anterior], [nuevo])
	SELECT
		N'banco_movimientos',
		CASE WHEN d.[id_movimiento] IS NULL THEN 'I' WHEN i.[id_movimiento] IS NULL THEN 'D' ELSE 'U' END,
		CAST(COALESCE(i.[id_movimiento], d.[id_movimiento]) AS NVARCHAR(100)),
		j.[anterior],
		j.[nuevo]
	FROM inserted i
	FULL OUTER JOIN deleted d ON d.[id_movimiento] = i.[id_movimiento]
	CROSS APPLY (
		SELECT
			CASE WHEN d.[id_movimiento] IS NULL THEN NULL
				ELSE (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [anterior],
			CASE WHEN i.[id_movimiento] IS NULL THEN NULL
				ELSE (SELECT i.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [nuevo]
	) j
	WHERE d.[id_movimiento] IS NULL OR i.[id_movimiento] IS NULL OR ISNULL(j.[anterior], N'') <> ISNULL(j.[nuevo], N'');
END
GO

IF OBJECT_ID(N'dbo.trg_cambios_caja_movimientos', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_cambios_caja_movimientos;
GO

CREATE TRIGGER dbo.trg_cambios_caja_movimientos ON dbo.caja_movimientos
AFTER INSERT, UPDATE, DELETE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted) RETURN;

	INSERT INTO dbo.auditoria_cambios_db ([tabla], [operacion], [clave], [anterior], [nuevo])
	SELECT
		N'caja_movimientos',
		CASE WHEN d.[id_movimiento] IS NULL THEN 'I' WHEN i.[id_movimiento] IS NULL THEN 'D' ELSE 'U' END,
		CAST(COALESCE(i.[id_movimiento], d.[id_movimiento]) AS NVARCHAR(100)),
		j.[anterior],
		j.[nuevo]
	FROM inserted i
	FULL OUTER JOIN deleted d ON d.[id_movimiento] = i.[id_movimiento]
	CROSS APPLY (
		SELECT
			CASE WHEN d.[id_movimiento] IS NULL THEN NULL
				ELSE (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [anterior],
			CASE WHEN i.[id_movimiento] IS NULL THEN NULL
				ELSE (SELECT i.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [nuevo]
	) j
	WHERE d.[id_movimiento] IS NULL OR i.[id_movimiento] IS NULL OR ISNULL(j.[anterior], N'') <> ISNULL(j.[nuevo], N'');
END
GO

IF OBJECT_ID(N'dbo.trg_cambios_cajas', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_cambios_cajas;
GO

CREATE TRIGGER dbo.trg_cambios_cajas ON dbo.cajas
AFTER INSERT, UPDATE, DELETE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted) RETURN;

	INSERT INTO dbo.auditoria_cambios_db ([tabla], [operacion], [clave], [anterior], [nuevo])
	SELECT
		N'cajas',
		CASE WHEN d.[id_caja] IS NULL THEN 'I' WHEN i.[id_caja] IS NULL THEN 'D' ELSE 'U' END,
		CAST(COALESCE(i.[id_caja], d.[id_caja]) AS NVARCHAR(100)),
		j.[anterior],
		j.[nuevo]
	FROM inserted i
	FULL OUTER JOIN deleted d ON d.[id_caja] = i.[id_caja]
	CROSS APPLY (
		SELECT
			CASE WHEN d.[id_caja] IS NULL THEN NULL
				ELSE (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [anterior],
			CASE WHEN i.[id_caja] IS NULL THEN NULL
				ELSE (SELECT i.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [nuevo]
	) j
	WHERE d.[id_caja] IS NULL OR i.[id_caja] IS NULL OR ISNULL(j.[anterior], N'') <> ISNULL(j.[nuevo], N'');
END
GO

IF OBJECT_ID(N'dbo.trg_cambios_pagos_cobros', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_cambios_pagos_cobros;
GO

CREATE TRIGGER dbo.trg_cambios_pagos_cobros ON dbo.pagos_cobros
AFTER INSERT, UPDATE, DELETE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted) RETURN;

	INSERT INTO dbo.auditoria_cambios_db ([tabla], [operacion], [clave], [anterior], [nuevo])
	SELECT
		N'pagos_cobros',
		CASE WHEN d.[id_pago_cobro] IS NULL THEN 'I' WHEN i.[id_pago_cobro] IS NULL THEN 'D' ELSE 'U' END,
		CAST(COALESCE(i.[id_pago_cobro], d.[id_pago_cobro]) AS NVARCHAR(100)),
		j.[anterior],
		j.[nuevo]
	FROM inserted i
	FULL OUTER JOIN deleted d ON d.[id_pago_cobro] = i.[id_pago_cobro]
	CROSS APPLY (
		SELECT
			CASE WHEN d.[id_pago_cobro] IS NULL THEN NULL
				ELSE (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [anterior],
			CASE WHEN i.[id_pago_cobro] IS NULL THEN NULL
				ELSE (SELECT i.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [nuevo]
	) j
	WHERE d.[id_pago_cobro] IS NULL OR i.[id_pago_cobro] IS NULL OR ISNULL(j.[anterior], N'') <> ISNULL(j.[nuevo], N'');
END
GO

IF OBJECT_ID(N'dbo.trg_cambios_pagos_proveedores', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_cambios_pagos_proveedores;
GO

CREATE TRIGGER dbo.trg_cambios_pagos_proveedores ON dbo.pagos_proveedores
AFTER INSERT, UPDATE, DELETE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted) RETURN;

	INSERT INTO dbo.auditoria_cambios_db ([tabla], [operacion], [clave], [anterior], [nuevo])
	SELECT
		N'pagos_proveedores',
		CASE WHEN d.[id_pago_proveedor] IS NULL THEN 'I' WHEN i.[id_pago_proveedor] IS NULL THEN 'D' ELSE 'U' END,
		CAST(COALESCE(i.[id_pago_proveedor], d.[id_pago_proveedor]) AS NVARCHAR(100)),
		j.[anterior],
		j.[nuevo]
	FROM inserted i
	FULL OUTER JOIN deleted d ON d.[id_pago_proveedor] = i.[id_pago_proveedor]
	CROSS APPLY (
		SELECT
			CASE WHEN d.[id_pago_proveedor] IS NULL THEN NULL
				ELSE (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [anterior],
			CASE WHEN i.[id_pago_proveedor] IS NULL THEN NULL
				ELSE (SELECT i.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [nuevo]
	) j
	WHERE d.[id_pago_proveedor] IS NULL OR i.[id_pago_proveedor] IS NULL OR ISNULL(j.[anterior], N'') <> ISNULL(j.[nuevo], N'');
END
GO

IF OBJECT_ID(N'dbo.trg_cambios_pagos_cobros_bcv', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_cambios_pagos_cobros_bcv;
GO

CREATE TRIGGER dbo.trg_cambios_pagos_cobros_bcv ON dbo.pagos_cobros_bcv
AFTER INSERT, UPDATE, DELETE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted) RETURN;

	INSERT INTO dbo.auditoria_cambios_db ([tabla], [operacion], [clave], [anterior], [nuevo])
	SELECT
		N'pagos_cobros_bcv',
		CASE WHEN d.[id_pago_cobro_bcv] IS NULL THEN 'I' WHEN i.[id_pago_cobro_bcv] IS NULL THEN 'D' ELSE 'U' END,
		CAST(COALESCE(i.[id_pago_cobro_bcv], d.[id_pago_cobro_bcv]) AS NVARCHAR(100)),
		j.[anterior],
		j.[nuevo]
	FROM inserted i
	FULL OUTER JOIN deleted d ON d.[id_pago_cobro_bcv] = i.[id_pago_cobro_bcv]
	CROSS APPLY (
		SELECT
			CASE WHEN d.[id_pago_cobro_bcv] IS NULL THEN NULL
				ELSE (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [anterior],
			CASE WHEN i.[id_pago_cobro_bcv] IS NULL THEN NULL
				ELSE (SELECT i.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [nuevo]
	) j
	WHERE d.[id_pago_cobro_bcv] IS NULL OR i.[id_pago_cobro_bcv] IS NULL OR ISNULL(j.[anterior], N'') <> ISNULL(j.[nuevo], N'');
END
GO

IF OBJECT_ID(N'dbo.trg_cambios_pagos_comisiones', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_cambios_pagos_comisiones;
GO

CREATE TRIGGER dbo.trg_cambios_pagos_comisiones ON dbo.pagos_comisiones
AFTER INSERT, UPDATE, DELETE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted) RETURN;

	INSERT INTO dbo.auditoria_cambios_db ([tabla], [operacion], [clave], [anterior], [nuevo])
	SELECT
		N'pagos_comisiones',
		CASE WHEN d.[id_pago_comision] IS NULL THEN 'I' WHEN i.[id_pago_comision] IS NULL THEN 'D' ELSE 'U' END,
		CAST(COALESCE(i.[id_pago_comision], d.[id_pago_comision]) AS NVARCHAR(100)),
		j.[anterior],
		j.[nuevo]
	FROM inserted i
	FULL OUTER JOIN deleted d ON d.[id_pago_comision] = i.[id_pago_comision]
	CROSS APPLY (
		SELECT
			CASE WHEN d.[id_pago_comision] IS NULL THEN NULL
				ELSE (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [anterior],
			CASE WHEN i.[id_pago_comision] IS NULL THEN NULL
				ELSE (SELECT i.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [nuevo]
	) j
	WHERE d.[id_pago_comision] IS NULL OR i.[id_pago_comision] IS NULL OR ISNULL(j.[anterior], N'') <> ISNULL(j.[nuevo], N'');
END
GO

IF OBJECT_ID(N'dbo.trg_cambios_cuentas_por_cobrar', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_cambios_cuentas_por_cobrar;
GO

CREATE TRIGGER dbo.trg_cambios_cuentas_por_cobrar ON dbo.cuentas_por_cobrar
AFTER INSERT, UPDATE, DELETE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted) RETURN;

	INSERT INTO dbo.auditoria_cambios_db ([tabla], [operacion], [clave], [anterior], [nuevo])
	SELECT
		N'cuentas_por_cobrar',
		CASE WHEN d.[id_cuenta_por_cobrar] IS NULL THEN 'I' WHEN i.[id_cuenta_por_cobrar] IS NULL THEN 'D' ELSE 'U' END,
		CAST(COALESCE(i.[id_cuenta_por_cobrar], d.[id_cuenta_por_cobrar]) AS NVARCHAR(100)),
		j.[anterior],
		j.[nuevo]
	FROM inserted i
	FULL OUTER JOIN deleted d ON d.[id_cuenta_por_cobrar] = i.[id_cuenta_por_cobrar]
	CROSS APPLY (
		SELECT
			CASE WHEN d.[id_cuenta_por_cobrar] IS NULL THEN NULL
				ELSE (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [anterior],
			CASE WHEN i.[id_cuenta_por_cobrar] IS NULL THEN NULL
				ELSE (SELECT i.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [nuevo]
	) j
	WHERE d.[id_cuenta_por_cobrar] IS NULL OR i.[id_cuenta_por_cobrar] IS NULL OR ISNULL(j.[anterior], N'') <> ISNULL(j.[nuevo], N'');
END
GO

IF OBJECT_ID(N'dbo.trg_cambios_cuentas_por_pagar', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_cambios_cuentas_por_pagar;
GO

CREATE TRIGGER dbo.trg_cambios_cuentas_por_pagar ON dbo.cuentas_por_pagar
AFTER INSERT, UPDATE, DELETE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted) RETURN;

	INSERT INTO dbo.auditoria_cambios_db ([tabla], [operacion], [clave], [anterior], [nuevo])
	SELECT
		N'cuentas_por_pagar',
		CASE WHEN d.[id_cuenta] IS NULL THEN 'I' WHEN i.[id_cuenta] IS NULL THEN 'D' ELSE 'U' END,
		CAST(COALESCE(i.[id_cuenta], d.[id_cuenta]) AS NVARCHAR(100)),
		j.[anterior],
		j.[nuevo]
	FROM inserted i
	FULL OUTER JOIN deleted d ON d.[id_cuenta] = i.[id_cuenta]
	CROSS APPLY (
		SELECT
			CASE WHEN d.[id_cuenta] IS NULL THEN NULL
				ELSE (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [anterior],
			CASE WHEN i.[id_cuenta] IS NULL THEN NULL
				ELSE (SELECT i.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [nuevo]
	) j
	WHERE d.[id_cuenta] IS NULL OR i.[id_cuenta] IS NULL OR ISNULL(j.[anterior], N'') <> ISNULL(j.[nuevo], N'');
END
GO

IF OBJECT_ID(N'dbo.trg_cambios_cuentas_por_cobrar_bcv', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_cambios_cuentas_por_cobrar_bcv;
GO

CREATE TRIGGER dbo.trg_cambios_cuentas_por_cobrar_bcv ON dbo.cuentas_por_cobrar_bcv
AFTER INSERT, UPDATE, DELETE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted) RETURN;

	INSERT INTO dbo.auditoria_cambios_db ([tabla], [operacion], [clave], [anterior], [nuevo])
	SELECT
		N'cuentas_por_cobrar_bcv',
		CASE WHEN d.[id_cuenta_por_cobrar] IS NULL THEN 'I' WHEN i.[id_cuenta_por_cobrar] IS NULL THEN 'D' ELSE 'U' END,
		CAST(COALESCE(i.[id_cuenta_por_cobrar], d.[id_cuenta_por_cobrar]) AS NVARCHAR(100)),
		j.[anterior],
		j.[nuevo]
	FROM inserted i
	FULL OUTER JOIN deleted d ON d.[id_cuenta_por_cobrar] = i.[id_cuenta_por_cobrar]
	CROSS APPLY (
		SELECT
			CASE WHEN d.[id_cuenta_por_cobrar] IS NULL THEN NULL
				ELSE (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [anterior],
			CASE WHEN i.[id_cuenta_por_cobrar] IS NULL THEN NULL
				ELSE (SELECT i.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [nuevo]
	) j
	WHERE d.[id_cuenta_por_cobrar] IS NULL OR i.[id_cuenta_por_cobrar] IS NULL OR ISNULL(j.[anterior], N'') <> ISNULL(j.[nuevo], N'');
END
GO

IF OBJECT_ID(N'dbo.trg_cambios_notas_credito_clientes', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_cambios_notas_credito_clientes;
GO

CREATE TRIGGER dbo.trg_cambios_notas_credito_clientes ON dbo.notas_credito_clientes
AFTER INSERT, UPDATE, DELETE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted) RETURN;

	INSERT INTO dbo.auditoria_cambios_db ([tabla], [operacion], [clave], [anterior], [nuevo])
	SELECT
		N'notas_credito_clientes',
		CASE WHEN d.[id_nota_credito] IS NULL THEN 'I' WHEN i.[id_nota_credito] IS NULL THEN 'D' ELSE 'U' END,
		CAST(COALESCE(i.[id_nota_credito], d.[id_nota_credito]) AS NVARCHAR(100)),
		j.[anterior],
		j.[nuevo]
	FROM inserted i
	FULL OUTER JOIN deleted d ON d.[id_nota_credito] = i.[id_nota_credito]
	CROSS APPLY (
		SELECT
			CASE WHEN d.[id_nota_credito] IS NULL THEN NULL
				ELSE (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [anterior],
			CASE WHEN i.[id_nota_credito] IS NULL THEN NULL
				ELSE (SELECT i.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [nuevo]
	) j
	WHERE d.[id_nota_credito] IS NULL OR i.[id_nota_credito] IS NULL OR ISNULL(j.[anterior], N'') <> ISNULL(j.[nuevo], N'');
END
GO

IF OBJECT_ID(N'dbo.trg_cambios_notas_credito_proveedores', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_cambios_notas_credito_proveedores;
GO

CREATE TRIGGER dbo.trg_cambios_notas_credito_proveedores ON dbo.notas_credito_proveedores
AFTER INSERT, UPDATE, DELETE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted) RETURN;

	INSERT INTO dbo.auditoria_cambios_db ([tabla], [operacion], [clave], [anterior], [nuevo])
	SELECT
		N'notas_credito_proveedores',
		CASE WHEN d.[id_nota_credito] IS NULL THEN 'I' WHEN i.[id_nota_credito] IS NULL THEN 'D' ELSE 'U' END,
		CAST(COALESCE(i.[id_nota_credito], d.[id_nota_credito]) AS NVARCHAR(100)),
		j.[anterior],
		j.[nuevo]
	FROM inserted i
	FULL OUTER JOIN deleted d ON d.[id_nota_credito] = i.[id_nota_credito]
	CROSS APPLY (
		SELECT
			CASE WHEN d.[id_nota_credito] IS NULL THEN NULL
				ELSE (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [anterior],
			CASE WHEN i.[id_nota_credito] IS NULL THEN NULL
				ELSE (SELECT i.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [nuevo]
	) j
	WHERE d.[id_nota_credito] IS NULL OR i.[id_nota_credito] IS NULL OR ISNULL(j.[anterior], N'') <> ISNULL(j.[nuevo], N'');
END
GO

IF OBJECT_ID(N'dbo.trg_cambios_comisiones_factura', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_cambios_comisiones_factura;
GO

CREATE TRIGGER dbo.trg_cambios_comisiones_factura ON dbo.comisiones_factura
AFTER INSERT, UPDATE, DELETE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted) RETURN;

	INSERT INTO dbo.auditoria_cambios_db ([tabla], [operacion], [clave], [anterior], [nuevo])
	SELECT
		N'comisiones_factura',
		CASE WHEN d.[id_comision] IS NULL THEN 'I' WHEN i.[id_comision] IS NULL THEN 'D' ELSE 'U' END,
		CAST(COALESCE(i.[id_comision], d.[id_comision]) AS NVARCHAR(100)),
		j.[anterior],
		j.[nuevo]
	FROM inserted i
	FULL OUTER JOIN deleted d ON d.[id_comision] = i.[id_comision]
	CROSS APPLY (
		SELECT
			CASE WHEN d.[id_comision] IS NULL THEN NULL
				ELSE (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [anterior],
			CASE WHEN i.[id_comision] IS NULL THEN NULL
				ELSE (SELECT i.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [nuevo]
	) j
	WHERE d.[id_comision] IS NULL OR i.[id_comision] IS NULL OR ISNULL(j.[anterior], N'') <> ISNULL(j.[nuevo], N'');
END
GO

