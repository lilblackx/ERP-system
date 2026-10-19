-- Extiende C7 (lockout de login, migrations/0008_lockout_login.sql, esta misma sesion):
-- decision del usuario fue eliminar el auto-desbloqueo por tiempo -- la unica forma de
-- recuperar acceso a una cuenta bloqueada es un codigo de un solo uso enviado al correo
-- registrado. Tambien resuelve C6 (politica de complejidad de clave, ver
-- app/services/auth.py:validar_password_policy) para el flujo de "recuperar clave
-- olvidada" que usa la misma tabla de codigos.

-- 1) bloqueado_hasta -> bloqueado_desde: el significado cambia de "bloqueado hasta esta
-- hora" (auto-expiraba) a "bloqueado desde esta hora" (solo un codigo verificado, o un
-- ADMIN via UsuarioService.desbloquear_usuario(), lo limpia). Renombrar en vez de dejar
-- el nombre viejo evita que el codigo futuro asuma que expira solo.
EXEC sp_rename 'dbo.usuarios.bloqueado_hasta', 'bloqueado_desde', 'COLUMN';
GO

-- 2) codigos_verificacion: un codigo de 6 digitos, de un solo uso, para dos flujos
-- distintos (tipo). Nunca se guarda en texto plano (codigo_hash = sha256), y se
-- invalida tanto por expiracion (fecha_expiracion) como por demasiados intentos de
-- adivinarlo (intentos_verificacion) -- ver RecuperacionAccesoService.
CREATE TABLE dbo.codigos_verificacion (
	[id_codigo] BIGINT IDENTITY(1,1) NOT NULL,
	[id_usuario] BIGINT NOT NULL,
	[tipo] VARCHAR(20) NOT NULL CONSTRAINT CK_codigos_verificacion_tipo CHECK ([tipo] IN ('DESBLOQUEO','RECUPERAR_CLAVE')),
	[codigo_hash] VARCHAR(255) NOT NULL,
	[fecha_creacion] DATETIME NOT NULL DEFAULT GETDATE(),
	[fecha_expiracion] DATETIME NOT NULL,
	[usado] BIT NOT NULL DEFAULT 0,
	[intentos_verificacion] INT NOT NULL DEFAULT 0,
	CONSTRAINT PK_codigos_verificacion PRIMARY KEY ([id_codigo])
);
GO

ALTER TABLE dbo.codigos_verificacion
ADD CONSTRAINT FK_codigos_verificacion_id_usuario FOREIGN KEY([id_usuario]) REFERENCES dbo.usuarios([id_usuario])
ON UPDATE NO ACTION ON DELETE NO ACTION;
GO

-- Unico filtro real que hace RecuperacionAccesoService: "el ultimo codigo vigente de
-- este usuario+tipo" (mismo criterio de C2, solo lo que de verdad se consulta).
CREATE INDEX IX_codigos_verificacion_id_usuario ON dbo.codigos_verificacion ([id_usuario]);
GO
