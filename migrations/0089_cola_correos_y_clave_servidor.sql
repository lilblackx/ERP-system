-- Correo saliente SOLO desde el servidor, y contrasena SMTP que ninguna estacion puede leer.
--
-- Antes la contrasena de la cuenta de correo vivia en texto plano en configuracion_smtp y
-- cualquier estacion (o cualquiera que leyera la base) la veia. Ahora:
--
-- 1) clave_cifrado_servidor: llave PUBLICA del servidor. Cualquier estacion cifra con ella la
--    contrasena al guardarla (Configuracion > Correo); la llave PRIVADA nunca sale del
--    servidor (archivo protegido con DPAPI de esa maquina), asi que solo el servidor puede
--    descifrarla. configuracion_smtp.password_cifrada guarda el resultado; la columna vieja
--    `password` se vacia al migrarla (CorreoService/SmtpConfigService.migrar_password).
-- 2) cola_correos: las estaciones no envian correo, dejan aqui la solicitud (codigos de
--    desbloqueo/recuperacion, avisos de seguridad) y el servidor -- el servicio de Windows,
--    o la app abierta en el servidor -- la envia. Al enviarse (o vencer) se borra el
--    contenido del mensaje: los codigos no quedan en la base.

IF OBJECT_ID(N'dbo.clave_cifrado_servidor', N'U') IS NULL
BEGIN
CREATE TABLE dbo.clave_cifrado_servidor (
	[id] INT NOT NULL CONSTRAINT PK_clave_cifrado_servidor PRIMARY KEY CONSTRAINT CK_clave_cifrado_servidor_unica CHECK ([id] = 1),
	[clave_publica] NVARCHAR(MAX) NOT NULL,
	[fecha_creacion] DATETIME NOT NULL CONSTRAINT DF_clave_cifrado_servidor_fecha DEFAULT GETDATE()
);
END
GO

IF COL_LENGTH('dbo.configuracion_smtp', 'password_cifrada') IS NULL
BEGIN
	ALTER TABLE dbo.configuracion_smtp ADD [password_cifrada] NVARCHAR(MAX) NULL;
END
GO

IF OBJECT_ID(N'dbo.cola_correos', N'U') IS NULL
BEGIN
CREATE TABLE dbo.cola_correos (
	[id_correo] BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_cola_correos PRIMARY KEY,
	[tipo] VARCHAR(30) NOT NULL,
	[referencia] VARCHAR(50) NULL,
	[destinatario] NVARCHAR(255) NOT NULL,
	[asunto] NVARCHAR(255) NOT NULL,
	[cuerpo] NVARCHAR(MAX) NOT NULL,
	[cuerpo_html] NVARCHAR(MAX) NULL,
	[estado] VARCHAR(12) NOT NULL CONSTRAINT DF_cola_correos_estado DEFAULT 'PENDIENTE'
		CONSTRAINT CK_cola_correos_estado CHECK ([estado] IN ('PENDIENTE', 'ENVIANDO', 'ENVIADO', 'ERROR')),
	[intentos] INT NOT NULL CONSTRAINT DF_cola_correos_intentos DEFAULT 0,
	[error] NVARCHAR(500) NULL,
	[fecha_creacion] DATETIME NOT NULL CONSTRAINT DF_cola_correos_creacion DEFAULT GETDATE(),
	[fecha_actualizacion] DATETIME NOT NULL CONSTRAINT DF_cola_correos_actualizacion DEFAULT GETDATE(),
	[fecha_vencimiento] DATETIME NOT NULL,
	[fecha_envio] DATETIME NULL,
	[creado_por] BIGINT NULL
);
CREATE INDEX IX_cola_correos_estado ON dbo.cola_correos ([estado], [fecha_creacion]);
END
GO
