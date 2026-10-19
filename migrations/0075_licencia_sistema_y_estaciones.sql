-- Licenciamiento servidor/estaciones (app/services/licencia.py).
--
-- licencia_sistema: UNA fila (id = 1) con la clave y el token firmado de la licencia de esta
-- instalacion. Solo el servidor la escribe (al activar y al renovar); las estaciones la leen
-- por su conexion normal a SQL Server, asi toda la red ve el mismo estado de licencia.
--
-- licencia_estaciones: PCs cliente que usan esta instalacion. Cada estacion se registra sola
-- al abrir la app; el servicio de licencia del servidor manda la lista a Cloudflare, que decide
-- cuantas entran segun max_estaciones de la licencia.
--
-- Ambas tablas estan exentas del modo solo lectura (TABLAS_EXENTAS en licencia.py): si no, una
-- licencia vencida no podria ni renovarse.

IF OBJECT_ID(N'dbo.licencia_sistema', N'U') IS NULL
BEGIN
	CREATE TABLE dbo.licencia_sistema (
		[id] TINYINT NOT NULL CONSTRAINT PK_licencia_sistema PRIMARY KEY
			CONSTRAINT CK_licencia_sistema_fila_unica CHECK ([id] = 1),
		[clave] VARCHAR(40) NULL,
		[token] VARCHAR(MAX) NULL,
		[rechazo] VARCHAR(30) NULL,
		[mensaje] VARCHAR(300) NULL,
		[actualizado_en] DATETIME NOT NULL DEFAULT GETDATE()
	);
END
GO

IF OBJECT_ID(N'dbo.licencia_estaciones', N'U') IS NULL
BEGIN
	CREATE TABLE dbo.licencia_estaciones (
		[hw_id] CHAR(64) NOT NULL CONSTRAINT PK_licencia_estaciones PRIMARY KEY,
		[nombre] VARCHAR(60) NOT NULL,
		[primera_vez] DATETIME NOT NULL DEFAULT GETDATE(),
		[ultima_vez] DATETIME NOT NULL DEFAULT GETDATE()
	);
END
GO
