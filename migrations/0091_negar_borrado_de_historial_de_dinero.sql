-- Blindaje de la base (1/2): el usuario SQL de la aplicacion no puede BORRAR el historial de dinero.
--
-- Todas las estaciones se conectan con el mismo usuario SQL (ver app/instalacion.py::_crear_usuario_app).
-- Con la contrasena de ese usuario (que vive en el .env de cada PC) alguien puede abrir Excel/SSMS y
-- borrar un pago o un movimiento de caja saltandose permisos y auditoria. La aplicacion NO necesita
-- borrar nada de esto -- no ejecuta ningun DELETE sobre estas tablas: las anulaciones generan notas de
-- credito, no borran pagos -- asi que se le niega DELETE sobre ellas. A la bitacora (auditoria y
-- auditoria_cambios_db) tambien se le niega UPDATE: no se puede reescribir.
--
-- SQL Server no admite DENY sobre roles fijos (db_datawriter), asi que los DENY van a un rol PROPIO,
-- [nexo_app_sin_borrado]. El instalador agrega al usuario de la app a ese rol al crearlo, y esta migracion agrega a
-- los usuarios que YA escriben en la base (miembros de db_datawriter que no son db_owner), para
-- instalaciones existentes.
--
-- ALCANCE: DENY no aplica a sysadmin ni a db_owner. Si la app corre con 'sa' o con el dueno de la
-- base (como un entorno de desarrollo), esto no protege nada: en produccion la app debe usar el
-- usuario limitado que crea el instalador. Idempotente.

IF DATABASE_PRINCIPAL_ID(N'nexo_app_sin_borrado') IS NULL
	CREATE ROLE [nexo_app_sin_borrado];
GO

DECLARE @sql NVARCHAR(MAX) = N'';
SELECT @sql += N'ALTER ROLE [nexo_app_sin_borrado] ADD MEMBER ' + QUOTENAME(m.[name]) + N';'
FROM sys.database_role_members rm
JOIN sys.database_principals r ON r.[principal_id] = rm.[role_principal_id] AND r.[name] = N'db_datawriter'
JOIN sys.database_principals m ON m.[principal_id] = rm.[member_principal_id]
WHERE m.[type] IN ('S', 'U', 'G')
	AND m.[name] <> N'dbo'
	AND NOT EXISTS (
		SELECT 1 FROM sys.database_role_members x
		JOIN sys.database_principals xr ON xr.[principal_id] = x.[role_principal_id]
		WHERE x.[member_principal_id] = m.[principal_id] AND xr.[name] IN (N'db_owner', N'nexo_app_sin_borrado')
	);
EXEC sp_executesql @sql;
GO

IF OBJECT_ID(N'dbo.caja_movimientos', N'U') IS NOT NULL
	DENY DELETE ON dbo.caja_movimientos TO [nexo_app_sin_borrado];
GO

IF OBJECT_ID(N'dbo.banco_movimientos', N'U') IS NOT NULL
	DENY DELETE ON dbo.banco_movimientos TO [nexo_app_sin_borrado];
GO

IF OBJECT_ID(N'dbo.pagos_cobros', N'U') IS NOT NULL
	DENY DELETE ON dbo.pagos_cobros TO [nexo_app_sin_borrado];
GO

IF OBJECT_ID(N'dbo.pagos_proveedores', N'U') IS NOT NULL
	DENY DELETE ON dbo.pagos_proveedores TO [nexo_app_sin_borrado];
GO

IF OBJECT_ID(N'dbo.pagos_cobros_bcv', N'U') IS NOT NULL
	DENY DELETE ON dbo.pagos_cobros_bcv TO [nexo_app_sin_borrado];
GO

IF OBJECT_ID(N'dbo.pagos_comisiones', N'U') IS NOT NULL
	DENY DELETE ON dbo.pagos_comisiones TO [nexo_app_sin_borrado];
GO

IF OBJECT_ID(N'dbo.notas_credito_clientes', N'U') IS NOT NULL
	DENY DELETE ON dbo.notas_credito_clientes TO [nexo_app_sin_borrado];
GO

IF OBJECT_ID(N'dbo.notas_credito_proveedores', N'U') IS NOT NULL
	DENY DELETE ON dbo.notas_credito_proveedores TO [nexo_app_sin_borrado];
GO

IF OBJECT_ID(N'dbo.conciliaciones_partida', N'U') IS NOT NULL
	DENY DELETE ON dbo.conciliaciones_partida TO [nexo_app_sin_borrado];
GO

IF OBJECT_ID(N'dbo.auditoria', N'U') IS NOT NULL
	DENY DELETE ON dbo.auditoria TO [nexo_app_sin_borrado];
GO

IF OBJECT_ID(N'dbo.auditoria', N'U') IS NOT NULL
	DENY UPDATE ON dbo.auditoria TO [nexo_app_sin_borrado];
GO

