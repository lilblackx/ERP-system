-- categorias_cliente.descuento_porcentaje queda eliminado: nunca se uso desde ningun
-- servicio (grep confirma 0 referencias fuera de la definicion de columna/modelo) y el
-- descuento en facturacion ahora se maneja explicitamente al momento de facturar --
-- bajando precio_unitario por debajo del precio de lista, o via
-- factura_venta.monto_descuento -- ambos con autorizacion obligatoria (ver
-- migrations/0020_descuentos_autorizacion.sql). Mantener esta columna sin usar
-- confundia sobre cual era el mecanismo de descuento vigente.
--
-- La columna se creo con DEFAULT inline sin nombre propio (schema_sqlserver.sql:528,
-- "DEFAULT 0.00" sin CONSTRAINT), asi que SQL Server le asigno un nombre de sistema
-- autogenerado (tipo DF__categoria__descu__<sufijo aleatorio>) que varia por
-- instalacion -- no se puede hardcodear. Se busca dinamicamente en sys.default_constraints
-- antes de soltarla, unica forma portable de borrar la columna sin adivinar el nombre.

DECLARE @constraint_name NVARCHAR(200);
SELECT @constraint_name = dc.name
FROM sys.default_constraints dc
JOIN sys.columns c ON c.object_id = dc.parent_object_id AND c.column_id = dc.parent_column_id
WHERE dc.parent_object_id = OBJECT_ID(N'dbo.categorias_cliente')
	AND c.name = 'descuento_porcentaje';

IF @constraint_name IS NOT NULL
BEGIN
	EXEC('ALTER TABLE dbo.categorias_cliente DROP CONSTRAINT [' + @constraint_name + ']');
END
GO

ALTER TABLE dbo.categorias_cliente DROP COLUMN [descuento_porcentaje];
GO
