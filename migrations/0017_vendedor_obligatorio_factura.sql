-- El vendedor deja de ser opcional al emitir una factura: toda venta debe quedar
-- atribuida a un vendedor para que ComisionService (C14, app/services/comisiones.py)
-- pueda calcular su comision cuando corresponda -- antes, una factura sin vendedor
-- simplemente no generaba comision (calcular_comisiones_factura retornaba temprano),
-- lo cual dejaba ventas sin dueño comercial asignado.
--
-- Solo aplicar si no hay facturas con id_vendedor NULL (entorno nuevo o ya migrado)

IF NOT EXISTS (SELECT 1 FROM dbo.factura_venta WHERE id_vendedor IS NULL)
BEGIN
    ALTER TABLE dbo.factura_venta ALTER COLUMN [id_vendedor] BIGINT NOT NULL;
END
GO
