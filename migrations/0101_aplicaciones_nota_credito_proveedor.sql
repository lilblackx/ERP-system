-- Aplicaciones de notas de credito de proveedor: una tabla propia en vez de un evento de Auditoria (espejo de la
-- 0100, que hizo lo mismo del lado del cliente).
--
-- Aplicar una nota de credito de proveedor a una cuenta por pagar (NotaCreditoService.aplicar_nota_credito_proveedor)
-- baja el saldo de la cuenta sin crear un pago, y solo dejaba constancia como un evento de Auditoria con JSON. Nada
-- leia ese evento: el estado de cuenta de proveedor mostraba la compra con un cargo menor al real (saldo + pagos, sin la
-- nota) y sin ninguna fila para la nota, y la antiguedad de cuentas por pagar con fecha de corte pasada no podia saber
-- que una nota aplicada despues del corte no existia todavia.
--
-- Ahora cada aplicacion es una fila (la nota, la cuenta por pagar, un monto positivo, fecha y quien la aplico), escrita
-- por el servicio en la MISMA transaccion que baja el saldo. Auditoria sigue registrando el evento, pero ya no es la
-- fuente.
--
-- Se vuelcan las aplicaciones ya hechas. A diferencia del lado del cliente, aqui el evento SI guarda el id de la nota y
-- el de la cuenta, asi que se enlaza directo; un evento que no se puede enlazar (JSON roto, nota o cuenta que ya no
-- existe, monto no positivo) no se vuelca.
--
-- Mismo blindaje que las demas tablas de dinero: el usuario de la aplicacion no borra filas (ver 0091) y cada cambio
-- queda en auditoria_cambios_db (ver 0092).

IF OBJECT_ID(N'dbo.aplicaciones_nota_credito_proveedor', N'U') IS NULL
BEGIN
CREATE TABLE dbo.aplicaciones_nota_credito_proveedor (
	[id_aplicacion] BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_aplicaciones_nota_credito_proveedor PRIMARY KEY,
	[id_nota_credito] BIGINT NOT NULL
		CONSTRAINT FK_aplicaciones_nc_proveedor_nota REFERENCES dbo.notas_credito_proveedores([id_nota_credito]),
	[id_cuenta_por_pagar] BIGINT NOT NULL
		CONSTRAINT FK_aplicaciones_nc_proveedor_cxp REFERENCES dbo.cuentas_por_pagar([id_cuenta]),
	[monto] DECIMAL(18,2) NOT NULL CONSTRAINT CK_aplicaciones_nc_proveedor_monto CHECK ([monto] > 0),
	[fecha_aplicacion] DATETIME NOT NULL CONSTRAINT DF_aplicaciones_nc_proveedor_fecha DEFAULT GETDATE(),
	[aplicado_por] BIGINT NULL
		CONSTRAINT FK_aplicaciones_nc_proveedor_usuario REFERENCES dbo.usuarios([id_usuario])
);
CREATE INDEX IX_aplicaciones_nc_proveedor_cxp ON dbo.aplicaciones_nota_credito_proveedor ([id_cuenta_por_pagar])
	INCLUDE ([id_nota_credito], [monto], [fecha_aplicacion]);
CREATE INDEX IX_aplicaciones_nc_proveedor_nota ON dbo.aplicaciones_nota_credito_proveedor ([id_nota_credito]);
CREATE INDEX IX_aplicaciones_nc_proveedor_fecha ON dbo.aplicaciones_nota_credito_proveedor ([fecha_aplicacion]);
END
GO

-- Volcado de las aplicaciones ya hechas. CASE WHEN ISJSON es una defensa: segun la version de SQL Server, JSON_VALUE
-- sobre un texto que no es JSON puede fallar (en la 2022 devuelve NULL y el evento se salta igual).
;WITH eventos AS (
	SELECT
		a.[id_usuario],
		a.[fecha_evento],
		CASE WHEN ISJSON(a.[detalle]) = 1
			THEN TRY_CAST(JSON_VALUE(a.[detalle], '$.id_nota_credito') AS BIGINT) END AS [id_nota_credito],
		CASE WHEN ISJSON(a.[detalle]) = 1
			THEN TRY_CAST(JSON_VALUE(a.[detalle], '$.id_cuenta_por_pagar') AS BIGINT) END AS [id_cuenta],
		CASE WHEN ISJSON(a.[detalle]) = 1
			THEN TRY_CAST(JSON_VALUE(a.[detalle], '$.monto') AS DECIMAL(18,2)) END AS [monto]
	FROM dbo.auditoria a
	WHERE a.[accion] = 'APLICACION_NOTA_CREDITO_PROVEEDOR' AND a.[modulo] = 'NOTAS_CREDITO'
)
INSERT INTO dbo.aplicaciones_nota_credito_proveedor
	([id_nota_credito], [id_cuenta_por_pagar], [monto], [fecha_aplicacion], [aplicado_por])
SELECT n.[id_nota_credito], c.[id_cuenta], e.[monto], e.[fecha_evento], u.[id_usuario]
FROM eventos e
JOIN dbo.notas_credito_proveedores n ON n.[id_nota_credito] = e.[id_nota_credito]
JOIN dbo.cuentas_por_pagar c ON c.[id_cuenta] = e.[id_cuenta]
LEFT JOIN dbo.usuarios u ON u.[id_usuario] = e.[id_usuario]
WHERE e.[monto] > 0
ORDER BY e.[fecha_evento];
GO

-- El usuario de la aplicacion no borra aplicaciones (ver 0091). El rol puede no existir en una base muy vieja.
IF DATABASE_PRINCIPAL_ID(N'nexo_app_sin_borrado') IS NOT NULL
	DENY DELETE ON dbo.aplicaciones_nota_credito_proveedor TO [nexo_app_sin_borrado];
GO

-- Historial automatico de cambios (ver 0092): valor anterior y nuevo de cada alta, cambio o borrado.
IF OBJECT_ID(N'dbo.trg_cambios_aplicaciones_nota_credito_proveedor', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_cambios_aplicaciones_nota_credito_proveedor;
GO

CREATE TRIGGER dbo.trg_cambios_aplicaciones_nota_credito_proveedor ON dbo.aplicaciones_nota_credito_proveedor
AFTER INSERT, UPDATE, DELETE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted) RETURN;

	INSERT INTO dbo.auditoria_cambios_db ([tabla], [operacion], [clave], [anterior], [nuevo])
	SELECT
		N'aplicaciones_nota_credito_proveedor',
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
