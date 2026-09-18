-- Eliminar el trigger existente trg_banco_movimientos_saldo
-- Esta migración elimina el trigger antiguo para ser reemplazado por el nuevo con manejo de UPDATEs
IF EXISTS (SELECT 1 FROM sys.triggers WHERE name = 'trg_banco_movimientos_saldo' AND parent_class_desc = 'OBJECT_OR_COLUMN')
BEGIN
    DECLARE @sql NVARCHAR(MAX)
    SET @sql = 'DROP TRIGGER dbo.trg_banco_movimientos_saldo'
    EXEC sp_executesql @sql
END
