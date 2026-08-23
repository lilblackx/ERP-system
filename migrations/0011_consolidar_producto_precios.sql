-- C14 (docs/CHECKLIST_PRODUCCION.md): el modelo de precios se simplifica a un unico
-- precio de lista por producto (decision de producto) -- hoy producto_precios permite
-- hasta 3 filas por producto (DETAL/MAYOR/ESPECIAL, CK_producto_precios_tipo). El calculo
-- de comision de vendedor (app/services/comisiones.py) necesita "el" precio de lista de
-- un producto, no una lista ambigua de hasta 3.
--
-- Antes de restringir el CHECK, hay que resolver los productos que hoy tienen mas de una
-- fila: se conserva una sola por prioridad DETAL > MAYOR > ESPECIAL (el precio al detal es
-- el mas representativo del "precio de lista" que ve un cliente comun). Las filas que se
-- pierden quedan respaldadas en dbo.auditoria (accion='MIGRACION_CONSOLIDAR_PRECIOS')
-- antes del DELETE, por si hace falta recuperar a mano el valor de un MAYOR/ESPECIAL.

INSERT INTO dbo.auditoria ([id_usuario], [accion], [modulo], [detalle], [fecha_evento])
SELECT
	NULL,
	'MIGRACION_CONSOLIDAR_PRECIOS',
	'INVENTARIO',
	'{"id_producto_precio":' + CAST(pp.[id_producto_precio] AS VARCHAR(20)) +
		',"id_producto":' + CAST(pp.[id_producto] AS VARCHAR(20)) +
		',"tipo_precio":"' + pp.[tipo_precio] +
		'","precio_venta":' + CAST(pp.[precio_venta] AS VARCHAR(30)) + '}',
	GETDATE()
FROM dbo.producto_precios pp
WHERE pp.[id_producto_precio] IN (
	SELECT [id_producto_precio] FROM (
		SELECT
			[id_producto_precio],
			ROW_NUMBER() OVER (
				PARTITION BY [id_producto]
				ORDER BY CASE [tipo_precio] WHEN 'DETAL' THEN 1 WHEN 'MAYOR' THEN 2 WHEN 'ESPECIAL' THEN 3 END
			) AS rn
		FROM dbo.producto_precios
	) x
	WHERE x.rn > 1
);
GO

DELETE pp
FROM dbo.producto_precios pp
WHERE pp.[id_producto_precio] IN (
	SELECT [id_producto_precio] FROM (
		SELECT
			[id_producto_precio],
			ROW_NUMBER() OVER (
				PARTITION BY [id_producto]
				ORDER BY CASE [tipo_precio] WHEN 'DETAL' THEN 1 WHEN 'MAYOR' THEN 2 WHEN 'ESPECIAL' THEN 3 END
			) AS rn
		FROM dbo.producto_precios
	) x
	WHERE x.rn > 1
);
GO

ALTER TABLE dbo.producto_precios DROP CONSTRAINT CK_producto_precios_tipo;
GO

UPDATE dbo.producto_precios SET [tipo_precio] = 'UNICO';
GO

ALTER TABLE dbo.producto_precios ADD CONSTRAINT CK_producto_precios_tipo CHECK ([tipo_precio] = 'UNICO');
GO
