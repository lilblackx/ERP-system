-- Correlativo transaccional para numero_factura / numero_control.
--
-- Antes ambos numeros se derivaban de id_factura (IDENTITY BIGINT): "FV-{id:06d}" y
-- "00-{id:08d}". El identity de SQL Server 2012+ pre-aloca bloques de 10.000 valores en
-- cache y, si el servidor se apaga sin checkpoint (contenedor docker kill, corte de luz,
-- OOM), el bloque sin usar se pierde -> el siguiente numero saltaba ~10.000 posiciones
-- (se observaron los bloques 10002, 20002, 30002, 40002 en produccion). Ademas cualquier
-- INSERT que fallaba o hacia rollback despues del flush quemaba el id.
--
-- Ahora el numero sale de dbo.correlativos, una tabla de una sola fila por correlativo
-- que se incrementa con UPDATE...OUTPUT DENTRO de la misma transaccion de la factura
-- (ver app/services/correlativos.py). Si la emision falla o el servidor muere a mitad,
-- el rollback deshace el incremento y el numero queda libre: la secuencia sigue sin
-- huecos y sin depender de como se apago SQL Server. El costo es que emisiones
-- concurrentes se serializan en esta fila por el UPDLOCK -- aceptable al ritmo de
-- facturacion de un punto de venta.
--
-- id_factura sigue siendo IDENTITY (clave interna, sus huecos no importan): el numero
-- de factura ya no tiene por que coincidir con el id.
--
-- La semilla es el mayor numero FV-/00- ya emitido, asi la secuencia continua donde
-- iba (no reinicia en 1 ni choca con facturas historicas). Filas TMP- nunca se
-- commitean (son placeholders intra-transaccion), asi que no entran al calculo.

IF OBJECT_ID('dbo.correlativos', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.correlativos (
		[nombre] VARCHAR(50) NOT NULL CONSTRAINT PK_correlativos PRIMARY KEY,
		[ultimo_numero] BIGINT NOT NULL
	);
END
GO

DECLARE @max_fv BIGINT = (
	SELECT MAX(TRY_CAST(SUBSTRING([numero_factura], 4, 20) AS BIGINT))
	FROM dbo.factura_venta
	WHERE [numero_factura] LIKE 'FV-[0-9]%'
);
DECLARE @max_nc BIGINT = (
	SELECT MAX(TRY_CAST(SUBSTRING([numero_control], 4, 20) AS BIGINT))
	FROM dbo.factura_venta
	WHERE [numero_control] LIKE '00-[0-9]%'
);
DECLARE @semilla BIGINT = ISNULL((
	SELECT MAX([v]) FROM (VALUES (@max_fv), (@max_nc)) AS [t]([v])
), 0);

IF NOT EXISTS (SELECT 1 FROM dbo.correlativos WHERE [nombre] = 'factura_venta')
BEGIN
	INSERT INTO dbo.correlativos ([nombre], [ultimo_numero])
	VALUES ('factura_venta', @semilla);
END
GO
