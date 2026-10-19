-- Poblar la tabla categorias_cliente con las categorías estándar de clientes
-- para que estén disponibles en el formulario de nuevo cliente.

IF NOT EXISTS (SELECT 1 FROM dbo.categorias_cliente WHERE nombre = 'Mayorista')
BEGIN
	INSERT INTO dbo.categorias_cliente (nombre, dias_credito_default)
	VALUES ('Mayorista', 30);
END
GO

IF NOT EXISTS (SELECT 1 FROM dbo.categorias_cliente WHERE nombre = 'Minorista')
BEGIN
	INSERT INTO dbo.categorias_cliente (nombre, dias_credito_default)
	VALUES ('Minorista', 0);
END
GO

IF NOT EXISTS (SELECT 1 FROM dbo.categorias_cliente WHERE nombre = 'Distribuidor')
BEGIN
	INSERT INTO dbo.categorias_cliente (nombre, dias_credito_default)
	VALUES ('Distribuidor', 45);
END
GO

IF NOT EXISTS (SELECT 1 FROM dbo.categorias_cliente WHERE nombre = 'Fabricante')
BEGIN
	INSERT INTO dbo.categorias_cliente (nombre, dias_credito_default)
	VALUES ('Fabricante', 60);
END
GO
