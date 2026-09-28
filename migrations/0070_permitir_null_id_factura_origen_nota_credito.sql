-- Permitir NULL en id_factura_origen para notas de crédito generadas por sobreabonos
-- Las notas de crédito por sobreabono no tienen una factura origen específica

ALTER TABLE dbo.notas_credito_clientes
ALTER COLUMN id_factura_origen BIGINT NULL;
GO
