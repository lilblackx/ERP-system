-- Devoluciones de notas de credito de cliente: una tabla propia en vez de solo
-- el saldo_disponible decreciente + un evento de Auditoria.
--
-- devolver_nota_credito_cliente() paga en efectivo/banco parte del saldo a favor
-- de una nota: mueve dinero real (egreso en caja/banco) y baja saldo_disponible.
-- Hasta aqui la unica constancia era el evento de Auditoria DEVOLUCION_NOTA_CREDITO_
-- CLIENTE con el detalle en JSON -- el estado de cuenta del cliente no tenia forma
-- de mostrar esa salida como movimiento propio (solo veia la nota con menos saldo).
--
-- Misma razon por la que existe aplicaciones_nota_credito_cliente (0100): cada
-- devolucion es una fila con su clave foranea a la nota, monto, fecha, metodo y
-- quien (y quien autorizo). El servicio la escribe en la MISMA transaccion que
-- baja el saldo y registra el egreso: o quedan las tres cosas o ninguna.
--
-- Se vuelcan las devoluciones que ya existen (leidas de los eventos de Auditoria).
-- El evento guarda el NUMERO de la nota, asi que se enlaza por numero_nota_credito
-- (unico); un evento que no se puede enlazar (JSON roto, nota inexistente, monto
-- no positivo) no se vuelca.
--
-- Mismo blindaje que las demas tablas de dinero: el usuario de la aplicacion no
-- puede borrar filas (ver 0091) y cada cambio queda en auditoria_cambios_db (0092).

IF OBJECT_ID(N'dbo.devoluciones_nota_credito', N'U') IS NULL
BEGIN
CREATE TABLE dbo.devoluciones_nota_credito (
	[id_devolucion] BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_devoluciones_nota_credito PRIMARY KEY,
	[id_nota_credito] BIGINT NOT NULL
		CONSTRAINT FK_devoluciones_nc_nota REFERENCES dbo.notas_credito_clientes([id_nota_credito]),
	[monto] DECIMAL(18,2) NOT NULL CONSTRAINT CK_devoluciones_nc_monto CHECK ([monto] > 0),
	[metodo_devolucion] VARCHAR(20) NULL,
	[fecha_devolucion] DATETIME NOT NULL CONSTRAINT DF_devoluciones_nc_fecha DEFAULT GETDATE(),
	[devuelto_por] BIGINT NULL
		CONSTRAINT FK_devoluciones_nc_usuario REFERENCES dbo.usuarios([id_usuario]),
	[autorizado_por] BIGINT NULL
		CONSTRAINT FK_devoluciones_nc_autorizador REFERENCES dbo.usuarios([id_usuario])
);
CREATE INDEX IX_devoluciones_nc_nota ON dbo.devoluciones_nota_credito ([id_nota_credito]);
CREATE INDEX IX_devoluciones_nc_fecha ON dbo.devoluciones_nota_credito ([fecha_devolucion]);
END
GO

-- Volcado de las devoluciones ya hechas. CASE WHEN ISJSON es una defensa (ver 0100):
-- cada lectura del JSON se protege sola y el motor no garantiza el orden de evaluacion.
;WITH eventos AS (
	SELECT
		a.[id_usuario],
		a.[fecha_evento],
		CASE WHEN ISJSON(a.[detalle]) = 1 THEN JSON_VALUE(a.[detalle], '$.numero_nota_credito') END AS [numero_nota],
		CASE WHEN ISJSON(a.[detalle]) = 1
			THEN JSON_VALUE(a.[detalle], '$.metodo_devolucion') END AS [metodo],
		CASE WHEN ISJSON(a.[detalle]) = 1
			THEN TRY_CAST(JSON_VALUE(a.[detalle], '$.monto') AS DECIMAL(18,2)) END AS [monto],
		CASE WHEN ISJSON(a.[detalle]) = 1
			THEN TRY_CAST(JSON_VALUE(a.[detalle], '$.autorizado_por') AS BIGINT) END AS [autorizador]
	FROM dbo.auditoria a
	WHERE a.[accion] = 'DEVOLUCION_NOTA_CREDITO_CLIENTE' AND a.[modulo] = 'NOTAS_CREDITO'
)
INSERT INTO dbo.devoluciones_nota_credito
	([id_nota_credito], [monto], [metodo_devolucion], [fecha_devolucion], [devuelto_por], [autorizado_por])
SELECT
	n.[id_nota_credito], e.[monto], e.[metodo], e.[fecha_evento], u.[id_usuario], ua.[id_usuario]
FROM eventos e
JOIN dbo.notas_credito_clientes n ON n.[numero_nota_credito] = e.[numero_nota]
LEFT JOIN dbo.usuarios u ON u.[id_usuario] = e.[id_usuario]
LEFT JOIN dbo.usuarios ua ON ua.[id_usuario] = e.[autorizador]
WHERE e.[monto] > 0
ORDER BY e.[fecha_evento];
GO

-- El usuario de la aplicacion no borra devoluciones (ver 0091). El rol puede no existir en una base muy vieja.
IF DATABASE_PRINCIPAL_ID(N'nexo_app_sin_borrado') IS NOT NULL
	DENY DELETE ON dbo.devoluciones_nota_credito TO [nexo_app_sin_borrado];
GO

-- Historial automatico de cambios (ver 0092): valor anterior y nuevo de cada alta, cambio o borrado.
IF OBJECT_ID(N'dbo.trg_cambios_devoluciones_nota_credito', N'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_cambios_devoluciones_nota_credito;
GO

CREATE TRIGGER dbo.trg_cambios_devoluciones_nota_credito ON dbo.devoluciones_nota_credito
AFTER INSERT, UPDATE, DELETE AS
BEGIN
	SET NOCOUNT ON;
	IF NOT EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted) RETURN;

	INSERT INTO dbo.auditoria_cambios_db ([tabla], [operacion], [clave], [anterior], [nuevo])
	SELECT
		N'devoluciones_nota_credito',
		CASE WHEN d.[id_devolucion] IS NULL THEN 'I' WHEN i.[id_devolucion] IS NULL THEN 'D' ELSE 'U' END,
		CAST(COALESCE(i.[id_devolucion], d.[id_devolucion]) AS NVARCHAR(100)),
		j.[anterior],
		j.[nuevo]
	FROM inserted i
	FULL OUTER JOIN deleted d ON d.[id_devolucion] = i.[id_devolucion]
	CROSS APPLY (
		SELECT
			CASE WHEN d.[id_devolucion] IS NULL THEN NULL
				ELSE (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [anterior],
			CASE WHEN i.[id_devolucion] IS NULL THEN NULL
				ELSE (SELECT i.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) END AS [nuevo]
	) j
	WHERE d.[id_devolucion] IS NULL OR i.[id_devolucion] IS NULL OR ISNULL(j.[anterior], N'') <> ISNULL(j.[nuevo], N'');
END
GO
