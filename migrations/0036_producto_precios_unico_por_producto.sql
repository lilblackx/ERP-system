-- Auditoria de Productos (2026-08-28), hallazgo #1: el comentario de
-- test_inventario.py::test_establecer_precio_segunda_vez_actualiza_no_duplica afirmaba que
-- "un solo precio por producto" estaba garantizado por una UNIQUE a nivel de BD -- no
-- existia ninguna. migrations/0011 solo restringio el VALOR de tipo_precio (siempre
-- 'UNICO'), nunca agrego unicidad sobre id_producto. Sin esa constraint,
-- PrecioService.establecer_precio() (check-then-insert-or-update, sin lock) puede dejar
-- dos filas para el mismo producto si dos ediciones de precio caen concurrentes -- y
-- ComisionService.calcular_comisiones_factura()/VentaService.emitir_factura() arman su
-- lookup de precio de lista con un dict comprehension sobre esas filas, asi que con dos
-- filas cual "gana" queda arbitrario segun el orden de la consulta.
--
-- Mismo patron defensivo que migrations/0011: antes de agregar la UNIQUE, se respaldan en
-- auditoria las filas duplicadas que se van a borrar (por si alguna vez paso la carrera en
-- produccion), conservando la de id_producto_precio mas alto (la mas reciente) por
-- producto.

INSERT INTO dbo.auditoria ([id_usuario], [accion], [modulo], [detalle], [fecha_evento])
SELECT
	NULL,
	'MIGRACION_DEDUPLICAR_PRECIOS',
	'INVENTARIO',
	'{"id_producto_precio":' + CAST(pp.[id_producto_precio] AS VARCHAR(20)) +
		',"id_producto":' + CAST(pp.[id_producto] AS VARCHAR(20)) +
		',"precio_venta":' + CAST(pp.[precio_venta] AS VARCHAR(30)) + '}',
	GETDATE()
FROM dbo.producto_precios pp
WHERE pp.[id_producto_precio] IN (
	SELECT [id_producto_precio] FROM (
		SELECT [id_producto_precio], ROW_NUMBER() OVER (PARTITION BY [id_producto] ORDER BY [id_producto_precio] DESC) AS rn
		FROM dbo.producto_precios
	) x
	WHERE x.rn > 1
);
GO

DELETE pp
FROM dbo.producto_precios pp
WHERE pp.[id_producto_precio] IN (
	SELECT [id_producto_precio] FROM (
		SELECT [id_producto_precio], ROW_NUMBER() OVER (PARTITION BY [id_producto] ORDER BY [id_producto_precio] DESC) AS rn
		FROM dbo.producto_precios
	) x
	WHERE x.rn > 1
);
GO

ALTER TABLE dbo.producto_precios ADD CONSTRAINT UQ_producto_precios_id_producto UNIQUE ([id_producto]);
GO
