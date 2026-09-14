-- Migración para agregar/modificar columnas precio_1, precio_2, precio_3 en producto_precios
-- Esta migración reemplaza la columna precio_venta por precio_1 y asegura precio_2 y precio_3

-- Paso 1: Renombrar precio_venta a precio_1 si existe, o agregar precio_1 si no existe
IF EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('dbo.producto_precios') AND name = 'precio_venta')
BEGIN
    -- Renombrar precio_venta a precio_1
    EXEC sp_rename 'dbo.producto_precios.precio_venta', 'precio_1', 'COLUMN';
END
ELSE IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('dbo.producto_precios') AND name = 'precio_1')
BEGIN
    -- Agregar precio_1 si no existe
    ALTER TABLE dbo.producto_precios ADD precio_1 FLOAT NULL;
END

-- Paso 2: Asegurar que precio_2 existe
IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('dbo.producto_precios') AND name = 'precio_2')
BEGIN
    ALTER TABLE dbo.producto_precios ADD precio_2 FLOAT NULL;
END

-- Paso 3: Asegurar que precio_3 existe
IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('dbo.producto_precios') AND name = 'precio_3')
BEGIN
    ALTER TABLE dbo.producto_precios ADD precio_3 FLOAT NULL;
END

-- Paso 4: Establecer valores por defecto para NULLs
UPDATE dbo.producto_precios SET precio_1 = 0.00 WHERE precio_1 IS NULL;
UPDATE dbo.producto_precios SET precio_2 = 0.00 WHERE precio_2 IS NULL;
UPDATE dbo.producto_precios SET precio_3 = 0.00 WHERE precio_3 IS NULL;

-- Paso 5: Hacer las columnas NOT NULL
ALTER TABLE dbo.producto_precios ALTER COLUMN precio_1 FLOAT NOT NULL;
ALTER TABLE dbo.producto_precios ALTER COLUMN precio_2 FLOAT NOT NULL;
ALTER TABLE dbo.producto_precios ALTER COLUMN precio_3 FLOAT NOT NULL;
