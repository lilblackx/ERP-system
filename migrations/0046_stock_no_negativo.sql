-- Hallazgo de auditoria (Fase 3, item 3.7): inventario.cantidad_unidad no tiene ningun
-- CHECK que impida un valor negativo a nivel de esquema. El UPDLOCK/ROWLOCK agregado en
-- Fase 1 (VentaService.emitir_factura, ver ese comentario) ya previene la race condition
-- que dejaria stock negativo bajo concurrencia normal, pero eso es una garantia de la
-- capa Python -- un INSERT/UPDATE directo contra la tabla (una migracion futura con un
-- bug, un script de carga masiva, un acceso fuera de los servicios) podria dejar stock
-- negativo sin que nada lo impida. Este CHECK es el respaldo a nivel de esquema, ultima
-- linea de defensa independientemente de por donde entre el dato.
--
-- WITH CHECK (default, no NOCHECK): valida tambien las filas YA existentes -- si el
-- ALTER falla aca, hay stock negativo real en la base que hay que investigar antes de
-- seguir, no taparlo dejando el CHECK sin aplicar retroactivamente.

ALTER TABLE dbo.inventario
ADD CONSTRAINT CK_inventario_cantidad_unidad_no_negativa CHECK ([cantidad_unidad] >= 0);
GO
