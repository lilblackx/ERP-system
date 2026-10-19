-- Configuracion del servidor SMTP desde la app (Configuracion > Correo), para que el usuario no
-- tenga que editar el .env / config.env a mano. Se guarda en la base (y no en un archivo local)
-- porque el envio de codigos de desbloqueo/recuperacion de clave puede dispararse desde cualquier
-- estacion: asi toda la red comparte la misma cuenta de correo.
--
-- Una sola fila (se crea al guardar por primera vez). Sin fila, email_service sigue usando
-- las variables SMTP_* del .env como respaldo. La clave se guarda tal cual, igual que antes en
-- el .env: quien accede a la base ya tiene acceso a todo lo demas.

IF OBJECT_ID(N'dbo.configuracion_smtp', N'U') IS NULL
BEGIN
	CREATE TABLE dbo.configuracion_smtp (
		[id_config] INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_configuracion_smtp PRIMARY KEY,
		[host] VARCHAR(255) NOT NULL,
		[puerto] INT NOT NULL CONSTRAINT DF_configuracion_smtp_puerto DEFAULT 587
			CONSTRAINT CK_configuracion_smtp_puerto CHECK ([puerto] BETWEEN 1 AND 65535),
		[usuario] VARCHAR(255) NULL,
		[password] VARCHAR(255) NULL,
		[remitente] VARCHAR(255) NULL,
		[usar_tls] BIT NOT NULL CONSTRAINT DF_configuracion_smtp_tls DEFAULT 1,
		[modificado_por] BIGINT NULL
			CONSTRAINT FK_configuracion_smtp_modificado_por REFERENCES dbo.usuarios([id_usuario]),
		[fecha_modificacion] DATETIME NOT NULL CONSTRAINT DF_configuracion_smtp_fecha DEFAULT GETDATE()
	);
END
GO
