-- C1 (docs/CHECKLIST_PRODUCCION.md): segunda barrera contra sobreventa de stock.
-- El fix real es el WITH (UPDLOCK, ROWLOCK) agregado en VentaService.emitir_factura()
-- (app/services/ventas.py), que serializa la validacion+insercion contra facturas
-- concurrentes sobre el mismo producto. Este CHECK es defensa en profundidad: si algun
-- camino futuro (script, migracion de datos, bug) deja cantidad_unidad en negativo, la
-- base de datos lo rechaza en vez de permitir stock invalido silencioso.

ALTER TABLE dbo.inventario ADD CONSTRAINT CK_inventario_cantidad_unidad_no_negativa CHECK ([cantidad_unidad] >= 0);
GO
