-- Aplicaciones de notas de credito de cliente: una tabla propia en vez de un evento de Auditoria.
--
-- Aplicar una nota de credito a una factura (NotaCreditoService.aplicar_nota_credito_cliente) baja el saldo de la
-- cuenta por cobrar sin crear un pago, y solo dejaba constancia como un evento de Auditoria con el detalle en JSON.
-- El estado de cuenta del reporte y el historial del cliente tenian que leer y parsear ese JSON para saber que
-- parte de una factura se habia cubierto con una nota: dependia de que nadie tocara la bitacora, de que el JSON
-- estuviera bien formado y no habia ninguna garantia de que el registro existiera.
--
-- Ahora cada aplicacion es una fila con sus claves foraneas (la nota, la cuenta por cobrar), un monto positivo,
-- fecha y quien la aplico. El servicio la escribe en la MISMA transaccion que baja el saldo: o quedan las dos cosas
-- o ninguna. Los reportes la leen de aqui; Auditoria sigue registrando el evento, pero ya no es la fuente.
--
-- Se vuelcan las aplicaciones que ya existen (leidas de los eventos de Auditoria). El evento solo guarda el NUMERO de
-- la nota, asi que se enlaza por numero_nota_credito (unico); la cuenta destino sale de la factura. Un evento que no
-- se puede enlazar (JSON roto, nota o factura que ya no existe, monto no positivo) no se vuelca: no habia forma de
-- reconstruirlo y el reporte tampoco lo contaba.
--
-- Mismo blindaje que las demas tablas de dinero: el usuario de la aplicacion no puede borrar filas (ver 0091) y cada
-- cambio queda en auditoria_cambios_db con el valor anterior y el nuevo (ver 0092).

IF OBJECT_ID(N'dbo.aplicaciones_nota_credito_cliente', N'U') IS NULL
BEGIN
CREATE TABLE dbo.aplicaciones_nota_credito_cliente (
	[id_aplicacion] BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_aplicaciones_nota_credito_cliente PRIMARY KEY,
	[id_nota_credito] BIGINT NOT NULL
		CONSTRAINT FK_aplicaciones_nc_cliente_nota REFERENCES dbo.notas_credito_clientes([id_nota_credito]),
	[id_cuenta_por_cobrar] BIGINT NOT NULL
		CONSTRAINT FK_aplicaciones_nc_cliente_cxc REFERENCES dbo.cuentas_por_cobrar([id_cuenta_por_cobrar]),
	[monto] DECIMAL(18,2) NOT NULL CONSTRAINT CK_aplicaciones_nc_cliente_monto CHECK ([monto] > 0),
	[fecha_aplicacion] DATETIME NOT NULL CONSTRAINT DF_aplicaciones_nc_cliente_fecha DEFAULT GETDATE(),
	[aplicado_por] BIGINT NULL
		CONSTRAINT FK_aplicaciones_nc_cliente_usuario REFERENCES dbo.usuarios([id_usuario])
);
CREATE INDEX IX_aplicaciones_nc_cliente_cxc ON dbo.aplicaciones_nota_credito_cliente ([id_cuenta_por_cobrar])
	INCLUDE ([id_nota_credito], [monto], [fecha_aplicacion]);
CREATE INDEX IX_aplicaciones_nc_cliente_nota ON dbo.aplicaciones_nota_credito_cliente ([id_nota_credito]);
CREATE INDEX IX_aplicaciones_nc_cliente_fecha ON dbo.aplicaciones_nota_credito_cliente ([fecha_aplicacion]);
END
GO

-- Volcado de las aplicaciones ya hechas. CASE WHEN ISJSON es una defensa: segun la version de SQL Server, JSON_VALUE
-- sobre un texto que no es JSON puede fallar (en la 2022 devuelve NULL y el evento se salta igual), y el motor no
-- garantiza el orden de evaluacion entre el WHERE y el SELECT, asi que cada lectura se protege sola.
;WITH eventos AS (
	SELECT
		a.[id_usuario],
		a.[fecha_evento],
		CASE WHEN ISJSON(a.[detalle]) = 1 THEN JSON_VALUE(a.[detalle], '$.numero_nota_credito') END AS [numero_nota],
		CASE WHEN ISJSON(a.[detalle]) = 1
			THEN TRY_CAST(JSON_VALUE(a.[detalle], '$.id_factura_destino') AS BIGINT) END AS [id_factura],
		CASE WHEN ISJSON(a.[detalle]) = 1
			THEN TRY_CAST(JSON_VALUE(a.[detalle], '$.monto') AS DECIMAL(18,2)) END AS [monto]
	FROM dbo.auditoria a
	WHERE a.[accion] = 'APLICACION_NOTA_CREDITO_CLIENTE' AND a.[modulo] = 'NOTAS_CREDITO'
)
INSERT INTO dbo.aplicaciones_nota_credito_cliente
	([id_nota_credito], [id_cuenta_por_cobrar], [monto], [fecha_aplicacion], [aplicado_por])
SELECT n.[id_nota_credito], c.[id_cuenta_por_cobrar], e.[monto], e.[fecha_evento], u.[id_usuario]
FROM eventos e
JOIN dbo.notas_credito_clientes n ON n.[numero_nota_credito] = e.[numero_nota]
CROSS APPLY (
	SELECT TOP 1 x.[id_cuenta_por_cobrar]
	FROM dbo.cuentas_por_cobrar x
	WHERE x.[id_factura] = e.[id_factura]
	ORDER BY x.[id_cuenta_por_cobrar]
) c
LEFT JOIN dbo.usuarios u ON u.[id_usuario] = e.[id_usuario]
WHERE e.[monto] > 0
ORDER BY e.[fecha_evento];
GO

-- El usuario de la aplicacion no borra aplicaciones (ver 0091). El rol puede no existir en una base muy vieja.
IF DATABASE_PRINCIPAL_ID(N'nexo_app_sin_borrado') IS NOT NULL
	DENY DELETE ON dbo.aplicaciones_nota_credito_cliente TO [nexo_app_sin_borrado];
GO

-- Historial automatico de cambios (ver 0092): valor anterior y nuevo de cada alta, cambio o borrado.
IF OBJECT_ID(N'dbo.trg_cambios_aplicaciones_nota_credito_cliente', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_cambios_aplicaciones_nota_credito_cliente;
GO

CREATE TRIGGER dbo.trg_cambios_aplicaciones_nota_credito_cliente ON dbo.aplicaciones_nota_credito_cliente
AFTER INSERT, UPDATE, DELETE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted) RETURN;

	INSERT INTO dbo.auditoria_cambios_db ([tabla], [operacion], [clave], [anterior], [nuevo])
	SELECT
		N'aplicaciones_nota_credito_cliente',
		CASE WHEN d.[id_aplicacion] IS NULL THEN 'I' WHEN i.[id_aplicacion] IS NULL THEN 'D' ELSE 'U' END,
		CAST(COALESCE(i.[id_aplicacion], d.[id_aplicacion]) AS NVARCHAR(100)),
		j.[anterior],
		j.[nuevo]
	FROM inserted i
	FULL OUTER JOIN deleted d ON d.[id_aplicacion] = i.[id_aplicacion]
	CROSS APPLY (
		SELECT
			CASE WHEN d.[id_aplicacion] IS NULL THEN NULL
				ELSE (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [anterior],
			CASE WHEN i.[id_aplicacion] IS NULL THEN NULL
				ELSE (SELECT i.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [nuevo]
	) j
	WHERE d.[id_aplicacion] IS NULL OR i.[id_aplicacion] IS NULL OR ISNULL(j.[anterior], N'') <> ISNULL(j.[nuevo], N'');
END
GO
