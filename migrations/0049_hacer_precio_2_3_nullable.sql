-- Migración para hacer precio_2 y precio_3 nullable en producto_precios
-- Esto restaura el comportamiento original donde solo precio_1 es obligatorio

-- Hacer precio_2 nullable
ALTER TABLE dbo.producto_precios ALTER COLUMN precio_2 FLOAT NULL;
GO

-- Hacer precio_3 nullable
ALTER TABLE dbo.producto_precios ALTER COLUMN precio_3 FLOAT NULL;
GO