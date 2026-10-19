-- C7 (docs/CHECKLIST_PRODUCCION.md): lockout tras intentos fallidos de login. TODO
-- explicito en app/services/auth.py desde la auditoria 2026-08-22 -- sin esto, un
-- acceso fuera de la red local no tenia ninguna barrera contra fuerza bruta sobre la
-- clave de un usuario. La logica de conteo/bloqueo vive en Python (auth.authenticate()),
-- estas columnas solo persisten el estado entre intentos.

ALTER TABLE dbo.usuarios ADD [intentos_fallidos] INT NOT NULL CONSTRAINT DF_usuarios_intentos_fallidos DEFAULT 0;
GO

ALTER TABLE dbo.usuarios ADD [bloqueado_hasta] DATETIME NULL;
GO
