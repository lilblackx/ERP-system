-- Correlativo fiscal para notas_credito_clientes: es un documento que la empresa emite
-- (reduce lo que le debe el cliente), reportable al SENIAT cuando se solicite -- igual
-- que factura_venta.numero_factura, necesita numeracion propia y correlativa.
--
-- notas_credito_proveedores NO se toca: cuando anulamos una compra ya pagada, el
-- documento fiscal (si aplica) lo emite el proveedor hacia nosotros, no al reves -- esa
-- tabla sigue siendo solo un registro interno de que se nos debe.

ALTER TABLE dbo.notas_credito_clientes ADD [numero_nota_credito] VARCHAR(20) NULL;
GO

-- Backfill defensivo por si ya hay filas (p. ej. entornos donde 0002 ya se aplico y se
-- generaron notas antes de esta migracion). En una base nueva la tabla esta vacia y este
-- UPDATE no afecta nada.
UPDATE dbo.notas_credito_clientes
SET [numero_nota_credito] = 'NC-' + RIGHT('000000' + CAST([id_nota_credito] AS VARCHAR(10)), 6)
WHERE [numero_nota_credito] IS NULL;
GO

ALTER TABLE dbo.notas_credito_clientes ALTER COLUMN [numero_nota_credito] VARCHAR(20) NOT NULL;
GO

ALTER TABLE dbo.notas_credito_clientes
ADD CONSTRAINT UQ_notas_credito_clientes_numero UNIQUE ([numero_nota_credito]);
GO
