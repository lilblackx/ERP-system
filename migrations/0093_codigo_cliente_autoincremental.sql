-- codigo_cliente autoincremental en SQL Server.
--
-- Antes el siguiente codigo lo calculaba Python (SELECT MAX + 1) y se insertaba despues,
-- sin reserva: dos estaciones dando de alta un cliente a la vez calculaban el mismo numero
-- y una de las dos fallaba contra el UNIQUE. Con una SEQUENCE como DEFAULT de la columna
-- el motor asigna el numero en el propio INSERT, de forma atomica entre estaciones.
--
-- La secuencia arranca despues del mayor codigo puramente numerico que ya exista (TRY_CAST
-- da NULL para los no numericos, como "CLI-001", que MAX ignora), asi que no choca con los
-- clientes cargados antes. Un codigo explicito en el INSERT sigue ganando sobre el DEFAULT
-- (importaciones, datos de prueba).
--
-- NO CACHE: con el cache por defecto un reinicio de SQL Server salta hasta 50 numeros.
-- Aun asi una SEQUENCE no es "sin huecos": un INSERT que falla o se revierte consume su
-- numero. Es el comportamiento esperado de cualquier autoincremental de SQL Server.
--
-- CREATE SEQUENCE no acepta variables en START WITH, de ahi el SQL dinamico.

DECLARE @inicio BIGINT = ISNULL(
	(SELECT MAX(TRY_CAST([codigo_cliente] AS BIGINT)) FROM dbo.clientes WHERE TRY_CAST([codigo_cliente] AS BIGINT) > 0),
	0
) + 1;
DECLARE @sql NVARCHAR(300) = N'CREATE SEQUENCE dbo.seq_codigo_cliente AS BIGINT START WITH '
	+ CAST(@inicio AS NVARCHAR(20)) + N' INCREMENT BY 1 NO CYCLE NO CACHE;';
EXEC sp_executesql @sql;
GO

ALTER TABLE dbo.clientes
	ADD CONSTRAINT DF_clientes_codigo_cliente
	DEFAULT (CAST(NEXT VALUE FOR dbo.seq_codigo_cliente AS VARCHAR(20))) FOR [codigo_cliente];
GO
