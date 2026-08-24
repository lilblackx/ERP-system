-- El vendedor deja de ser opcional al emitir una factura: toda venta debe quedar
-- atribuida a un vendedor para que ComisionService (C14, app/services/comisiones.py)
-- pueda calcular su comision cuando corresponda -- antes, una factura sin vendedor
-- simplemente no generaba comision (calcular_comisiones_factura retornaba temprano),
-- lo cual dejaba ventas sin dueño comercial asignado.
--
-- Entorno nuevo (sin datos): no hace falta backfill, ALTER COLUMN corre directo.
-- Entorno con datos previos: si existe alguna factura_venta.id_vendedor NULL, este
-- ALTER falla (Msg 515) hasta que se le asigne un vendedor manualmente -- a proposito,
-- para no inventar un vendedor "generico" ficticio sobre datos reales sin revisar caso
-- por caso.

ALTER TABLE dbo.factura_venta ALTER COLUMN [id_vendedor] BIGINT NOT NULL;
GO
