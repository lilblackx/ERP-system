-- Corregir el cálculo de cajas en devolución de mercancía
-- El trigger trg_nota_devolucion_detalle_ins debe actualizar cantidad_caja_total
-- cuando se devuelve mercancía al proveedor, no solo cantidad_unidad

IF OBJECT_ID('dbo.trg_nota_devolucion_detalle_ins', 'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_nota_devolucion_detalle_ins;
GO

CREATE TRIGGER trg_nota_devolucion_detalle_ins ON dbo.nota_devolucion_detalle
AFTER INSERT AS
BEGIN
	SET NOCOUNT ON;

	-- Devuelve al proveedor mercancia que ya estaba contada en stock (sumada por
	-- trg_nota_recepcion_detalle_ins, punto 3) -- agregado por producto, no fila por fila,
	-- por la misma razon que ese trigger.
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] - agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT [id_producto], SUM([cantidad_devuelta]) AS [total_cant]
		FROM inserted
		GROUP BY [id_producto]
	) agg ON agg.[id_producto] = inv.[id_producto];

	-- Actualizar cantidad_caja_total y cantidad_caja_unidad después de actualizar cantidad_unidad
	UPDATE inv
	SET
		inv.[cantidad_caja_total] = CASE
			WHEN inv.[cantidad_caja] > 0 THEN FLOOR(inv.[cantidad_unidad] / inv.[cantidad_caja])
			ELSE 0
		END,
		inv.[cantidad_caja_unidad] = CASE
			WHEN inv.[cantidad_caja] > 0 THEN (inv.[cantidad_unidad] % inv.[cantidad_caja])
			ELSE inv.[cantidad_unidad]
		END
	FROM dbo.inventario inv
	JOIN (
		SELECT DISTINCT [id_producto]
		FROM inserted
	) agg ON agg.[id_producto] = inv.[id_producto];
END
GO
