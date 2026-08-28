-- Bug real encontrado al probar el auto-aplicado de enmiendas FECHA (migrations/0034):
-- compra_oc.fecha_estimada_entrega y compra_oc_enmienda.fecha_entrega_anterior/
-- fecha_entrega_nueva quedaron como DATETIME en 0032 -- inconsistente con el resto del
-- schema, donde una fecha limite/de vencimiento SIN hora (compras.fecha_vencimiento,
-- cuentas_por_pagar.fecha_vencimiento, factura_venta.fecha_vencimiento) siempre es DATE.
--
-- El sintoma real: OrdenCompraFormDialog/EnmiendaOCDialog (app/ui/compras.py) usan
-- QDateEdit, cuyo .date().toPython() devuelve datetime.date -- pyodbc rechaza un `date`
-- puro contra una columna DATETIME (revisa .tzinfo, que `date` no tiene) y la insercion
-- explota. Con DATE en vez de DATETIME el driver lo acepta directo, sin conversion.
--
-- Sin dato existente que migrar (compra_oc/compra_oc_enmienda son tablas nuevas de 0032,
-- ninguna fila de produccion las uso todavia con fecha_estimada_entrega poblada).

ALTER TABLE dbo.compra_oc ALTER COLUMN [fecha_estimada_entrega] DATE NULL;
GO

ALTER TABLE dbo.compra_oc_enmienda ALTER COLUMN [fecha_entrega_anterior] DATE NULL;
GO

ALTER TABLE dbo.compra_oc_enmienda ALTER COLUMN [fecha_entrega_nueva] DATE NULL;
GO
