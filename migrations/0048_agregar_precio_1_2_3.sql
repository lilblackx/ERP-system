-- Migración para agregar/modificar columnas precio_1, precio_2, precio_3 en producto_precios
-- Esta migración reemplaza la columna precio_venta por precio_1 y asegura precio_2 y precio_3
-- Versión idempotente y defensiva para evitar errores en entornos CI

-- Paso 1: Renombrar precio_venta a precio_1 si existe
IF EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('dbo.producto_precios') AND name = 'precio_venta')
BEGIN
    -- Renombrar precio_venta a precio_1
    EXEC sp_rename 'dbo.producto_precios.precio_venta', 'precio_1', 'COLUMN';
END
GO

-- Paso 2: Asegurar columnas precio_1/2/3 y convertirlas a NOT NULL de forma segura
-- 1) Añadir columnas si no existen
IF NOT EXISTS (
  SELECT 1 FROM sys.columns
  WHERE Name = 'precio_1' AND Object_ID('dbo.producto_precios') = object_id('dbo.producto_precios')
)
BEGIN
  ALTER TABLE dbo.producto_precios ADD precio_1 FLOAT NULL;
END
GO

IF NOT EXISTS (
  SELECT 1 FROM sys.columns
  WHERE Name = 'precio_2' AND Object_ID('dbo.producto_precios') = object_id('dbo.producto_precios')
)
BEGIN
  ALTER TABLE dbo.producto_precios ADD precio_2 FLOAT NULL;
END
GO

IF NOT EXISTS (
  SELECT 1 FROM sys.columns
  WHERE Name = 'precio_3' AND Object_ID('dbo.producto_precios') = object_id('dbo.producto_precios')
)
BEGIN
  ALTER TABLE dbo.producto_precios ADD precio_3 FLOAT NULL;
END
GO

-- 2) Asegurar que no haya NULLs antes de convertir a NOT NULL
IF EXISTS (SELECT 1 FROM dbo.producto_precios WHERE precio_1 IS NULL)
BEGIN
  UPDATE dbo.producto_precios SET precio_1 = 0 WHERE precio_1 IS NULL;
END
GO

ALTER TABLE dbo.producto_precios ALTER COLUMN precio_1 FLOAT NOT NULL;
GO

-- Repetir validación para precio_2
IF EXISTS (SELECT 1 FROM dbo.producto_precios WHERE precio_2 IS NULL)
BEGIN
  UPDATE dbo.producto_precios SET precio_2 = 0 WHERE precio_2 IS NULL;
END
GO

ALTER TABLE dbo.producto_precios ALTER COLUMN precio_2 FLOAT NOT NULL;
GO

-- Repetir validación para precio_3
IF EXISTS (SELECT 1 FROM dbo.producto_precios WHERE precio_3 IS NULL)
BEGIN
  UPDATE dbo.producto_precios SET precio_3 = 0 WHERE precio_3 IS NULL;
END
GO

ALTER TABLE dbo.producto_precios ALTER COLUMN precio_3 FLOAT NOT NULL;
GO
