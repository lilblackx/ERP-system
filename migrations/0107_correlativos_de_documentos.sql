-- Correlativo transaccional (ver 0104 y app/services/correlativos.py) para los demas documentos, y candado en la base
-- contra numeros que no salgan de el.
--
-- 1) NC- se derivaba del IDENTITY, y OC-/ODC-/ENM-/NR-/ND- de MAX(id)+1: los dos saltan de bloque (~10.000) cuando
--    SQL Server se apaga de golpe, y MAX(id)+1 ademas podia dar el mismo numero a dos usuarios a la vez.
--
-- 2) Una estacion que se quede con la version anterior seguiria numerando por su cuenta. Usaria numeros que el
--    correlativo todavia no entrego y, al llegar a ellos, la emision fallaria por duplicado una y otra vez (el rollback
--    devuelve el mismo numero). Un trigger por tabla rechaza todo numero NUEVO mayor que lo entregado: la estacion
--    vieja no puede emitir y hay que actualizarla. No toca los documentos ya emitidos.
--
-- Cada correlativo continua desde el numero mas alto ya emitido; no renumera nada. Idempotente y nunca baja un
-- correlativo (factura_venta se vuelve a alinear por si una estacion vieja emitio despues de la 0104).

;WITH emitidos AS (
	SELECT 'factura_venta' AS [nombre], MAX(TRY_CAST(SUBSTRING([numero_factura], 4, 20) AS BIGINT)) AS [maximo]
		FROM dbo.factura_venta WHERE [numero_factura] LIKE 'FV-[0-9]%'
	UNION ALL
	SELECT 'factura_venta', MAX(TRY_CAST(SUBSTRING([numero_control], 4, 20) AS BIGINT))
		FROM dbo.factura_venta WHERE [numero_control] LIKE '00-[0-9]%'
	UNION ALL
	SELECT 'nota_credito_cliente', MAX(TRY_CAST(SUBSTRING([numero_nota_credito], 4, 20) AS BIGINT))
		FROM dbo.notas_credito_clientes WHERE [numero_nota_credito] LIKE 'NC-[0-9]%'
	UNION ALL
	SELECT 'compra', MAX(TRY_CAST(SUBSTRING([numero_compra], 4, 20) AS BIGINT))
		FROM dbo.compras WHERE [numero_compra] LIKE 'OC-[0-9]%'
	UNION ALL
	SELECT 'orden_compra', MAX(TRY_CAST(SUBSTRING([numero_oc], 5, 20) AS BIGINT))
		FROM dbo.compra_oc WHERE [numero_oc] LIKE 'ODC-[0-9]%'
	UNION ALL
	SELECT 'enmienda_oc', MAX(TRY_CAST(SUBSTRING([numero_enmienda], 5, 20) AS BIGINT))
		FROM dbo.compra_oc_enmienda WHERE [numero_enmienda] LIKE 'ENM-[0-9]%'
	UNION ALL
	SELECT 'nota_recepcion', MAX(TRY_CAST(SUBSTRING([numero_nr], 4, 20) AS BIGINT))
		FROM dbo.nota_recepcion WHERE [numero_nr] LIKE 'NR-[0-9]%'
	UNION ALL
	SELECT 'nota_devolucion', MAX(TRY_CAST(SUBSTRING([numero_nota_devolucion], 4, 20) AS BIGINT))
		FROM dbo.nota_devolucion WHERE [numero_nota_devolucion] LIKE 'ND-[0-9]%'
), semillas AS (
	SELECT [nombre], ISNULL(MAX([maximo]), 0) AS [semilla] FROM emitidos GROUP BY [nombre]
)
MERGE dbo.correlativos AS c
USING semillas AS s ON c.[nombre] = s.[nombre]
WHEN MATCHED AND s.[semilla] > c.[ultimo_numero] THEN UPDATE SET [ultimo_numero] = s.[semilla]
WHEN NOT MATCHED THEN INSERT ([nombre], [ultimo_numero]) VALUES (s.[nombre], s.[semilla]);
GO

-- El usuario de la aplicacion no borra correlativos (ver 0091). El rol puede no existir en una base muy vieja.
IF DATABASE_PRINCIPAL_ID(N'nexo_app_sin_borrado') IS NOT NULL
	DENY DELETE ON dbo.correlativos TO [nexo_app_sin_borrado];
GO

IF OBJECT_ID(N'dbo.trg_correlativo_factura_venta', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_correlativo_factura_venta;
GO

CREATE TRIGGER dbo.trg_correlativo_factura_venta ON dbo.factura_venta
AFTER INSERT, UPDATE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT UPDATE([numero_factura]) AND NOT UPDATE([numero_control]) RETURN;

	DECLARE @ultimo BIGINT = (SELECT [ultimo_numero] FROM dbo.correlativos WHERE [nombre] = 'factura_venta');
	IF EXISTS (
		SELECT 1 FROM inserted i LEFT JOIN deleted d ON d.[id_factura] = i.[id_factura]
		WHERE (
			(d.[id_factura] IS NULL OR d.[numero_factura] <> i.[numero_factura])
			AND i.[numero_factura] LIKE 'FV-[0-9]%'
			AND TRY_CAST(SUBSTRING(i.[numero_factura], 4, 20) AS BIGINT) > @ultimo
		) OR (
			(d.[id_factura] IS NULL OR d.[numero_control] <> i.[numero_control])
			AND i.[numero_control] LIKE '00-[0-9]%'
			AND TRY_CAST(SUBSTRING(i.[numero_control], 4, 20) AS BIGINT) > @ultimo
		)
	)
		THROW 51070, 'Numero de factura fuera del correlativo: actualice Nexo ERP en esta estacion.', 1;
END
GO

IF OBJECT_ID(N'dbo.trg_correlativo_notas_credito_clientes', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_correlativo_notas_credito_clientes;
GO

CREATE TRIGGER dbo.trg_correlativo_notas_credito_clientes ON dbo.notas_credito_clientes
AFTER INSERT, UPDATE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT UPDATE([numero_nota_credito]) RETURN;

	DECLARE @ultimo BIGINT = (SELECT [ultimo_numero] FROM dbo.correlativos WHERE [nombre] = 'nota_credito_cliente');
	IF EXISTS (
		SELECT 1 FROM inserted i LEFT JOIN deleted d ON d.[id_nota_credito] = i.[id_nota_credito]
		WHERE (d.[id_nota_credito] IS NULL OR d.[numero_nota_credito] <> i.[numero_nota_credito])
			AND i.[numero_nota_credito] LIKE 'NC-[0-9]%'
			AND TRY_CAST(SUBSTRING(i.[numero_nota_credito], 4, 20) AS BIGINT) > @ultimo
	)
		THROW 51070, 'Numero de nota de credito fuera del correlativo: actualice Nexo ERP en esta estacion.', 1;
END
GO

IF OBJECT_ID(N'dbo.trg_correlativo_compras', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_correlativo_compras;
GO

CREATE TRIGGER dbo.trg_correlativo_compras ON dbo.compras
AFTER INSERT, UPDATE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT UPDATE([numero_compra]) RETURN;

	DECLARE @ultimo BIGINT = (SELECT [ultimo_numero] FROM dbo.correlativos WHERE [nombre] = 'compra');
	IF EXISTS (
		SELECT 1 FROM inserted i LEFT JOIN deleted d ON d.[id_compra] = i.[id_compra]
		WHERE (d.[id_compra] IS NULL OR d.[numero_compra] <> i.[numero_compra])
			AND i.[numero_compra] LIKE 'OC-[0-9]%'
			AND TRY_CAST(SUBSTRING(i.[numero_compra], 4, 20) AS BIGINT) > @ultimo
	)
		THROW 51070, 'Numero de compra fuera del correlativo: actualice Nexo ERP en esta estacion.', 1;
END
GO

IF OBJECT_ID(N'dbo.trg_correlativo_compra_oc', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_correlativo_compra_oc;
GO

CREATE TRIGGER dbo.trg_correlativo_compra_oc ON dbo.compra_oc
AFTER INSERT, UPDATE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT UPDATE([numero_oc]) RETURN;

	DECLARE @ultimo BIGINT = (SELECT [ultimo_numero] FROM dbo.correlativos WHERE [nombre] = 'orden_compra');
	IF EXISTS (
		SELECT 1 FROM inserted i LEFT JOIN deleted d ON d.[id_oc] = i.[id_oc]
		WHERE (d.[id_oc] IS NULL OR d.[numero_oc] <> i.[numero_oc])
			AND i.[numero_oc] LIKE 'ODC-[0-9]%'
			AND TRY_CAST(SUBSTRING(i.[numero_oc], 5, 20) AS BIGINT) > @ultimo
	)
		THROW 51070, 'Numero de orden de compra fuera del correlativo: actualice Nexo ERP en esta estacion.', 1;
END
GO

IF OBJECT_ID(N'dbo.trg_correlativo_compra_oc_enmienda', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_correlativo_compra_oc_enmienda;
GO

CREATE TRIGGER dbo.trg_correlativo_compra_oc_enmienda ON dbo.compra_oc_enmienda
AFTER INSERT, UPDATE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT UPDATE([numero_enmienda]) RETURN;

	DECLARE @ultimo BIGINT = (SELECT [ultimo_numero] FROM dbo.correlativos WHERE [nombre] = 'enmienda_oc');
	IF EXISTS (
		SELECT 1 FROM inserted i LEFT JOIN deleted d ON d.[id_enmienda] = i.[id_enmienda]
		WHERE (d.[id_enmienda] IS NULL OR d.[numero_enmienda] <> i.[numero_enmienda])
			AND i.[numero_enmienda] LIKE 'ENM-[0-9]%'
			AND TRY_CAST(SUBSTRING(i.[numero_enmienda], 5, 20) AS BIGINT) > @ultimo
	)
		THROW 51070, 'Numero de enmienda fuera del correlativo: actualice Nexo ERP en esta estacion.', 1;
END
GO

IF OBJECT_ID(N'dbo.trg_correlativo_nota_recepcion', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_correlativo_nota_recepcion;
GO

CREATE TRIGGER dbo.trg_correlativo_nota_recepcion ON dbo.nota_recepcion
AFTER INSERT, UPDATE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT UPDATE([numero_nr]) RETURN;

	DECLARE @ultimo BIGINT = (SELECT [ultimo_numero] FROM dbo.correlativos WHERE [nombre] = 'nota_recepcion');
	IF EXISTS (
		SELECT 1 FROM inserted i LEFT JOIN deleted d ON d.[id_nr] = i.[id_nr]
		WHERE (d.[id_nr] IS NULL OR d.[numero_nr] <> i.[numero_nr])
			AND i.[numero_nr] LIKE 'NR-[0-9]%'
			AND TRY_CAST(SUBSTRING(i.[numero_nr], 4, 20) AS BIGINT) > @ultimo
	)
		THROW 51070, 'Numero de nota de recepcion fuera del correlativo: actualice Nexo ERP en esta estacion.', 1;
END
GO

IF OBJECT_ID(N'dbo.trg_correlativo_nota_devolucion', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_correlativo_nota_devolucion;
GO

CREATE TRIGGER dbo.trg_correlativo_nota_devolucion ON dbo.nota_devolucion
AFTER INSERT, UPDATE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT UPDATE([numero_nota_devolucion]) RETURN;

	DECLARE @ultimo BIGINT = (SELECT [ultimo_numero] FROM dbo.correlativos WHERE [nombre] = 'nota_devolucion');
	IF EXISTS (
		SELECT 1 FROM inserted i LEFT JOIN deleted d ON d.[id_devolucion] = i.[id_devolucion]
		WHERE (d.[id_devolucion] IS NULL OR d.[numero_nota_devolucion] <> i.[numero_nota_devolucion])
			AND i.[numero_nota_devolucion] LIKE 'ND-[0-9]%'
			AND TRY_CAST(SUBSTRING(i.[numero_nota_devolucion], 4, 20) AS BIGINT) > @ultimo
	)
		THROW 51070, 'Numero de nota de devolucion fuera del correlativo: actualice Nexo ERP en esta estacion.', 1;
END
GO
