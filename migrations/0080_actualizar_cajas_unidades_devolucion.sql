-- Actualizar trigger de devolución para calcular automáticamente cajas y unidades sueltas
-- Cuando se devuelve mercancia, se recalculan las cajas completas y unidades sueltas
-- basado en la cantidad total y unidades por caja del producto.

DROP TRIGGER trg_nota_devolucion_detalle_ins;
GO

CREATE TRIGGER trg_nota_devolucion_detalle_ins ON dbo.nota_devolucion_detalle
AFTER INSERT AS
BEGIN
	SET NOCOUNT ON;

	-- Devuelve al proveedor mercancia que ya estaba contada en stock (sumada por
	-- trg_nota_recepcion_detalle_ins, punto 3) -- agregado por producto, no fila por fila,
	-- por la misma razon que ese trigger.
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] - agg.[total_cant],
		-- Recalcular cajas completas y unidades sueltas
		inv.[cantidad_caja_total] = CASE
			WHEN inv.[cantidad_caja] > 0 AND inv.[cantidad_caja] IS NOT NULL
			THEN FLOOR((inv.[cantidad_unidad] - agg.[total_cant]) / inv.[cantidad_caja])
			ELSE 0
		END,
		inv.[cantidad_caja_unidad] = CASE
			WHEN inv.[cantidad_caja] > 0 AND inv.[cantidad_caja] IS NOT NULL
			THEN (inv.[cantidad_unidad] - agg.[total_cant]) % inv.[cantidad_caja]
			ELSE (inv.[cantidad_unidad] - agg.[total_cant])
		END
	FROM dbo.inventario inv
	JOIN (
		SELECT [id_producto], SUM([cantidad_devuelta]) AS [total_cant]
		FROM inserted
		GROUP BY [id_producto]
	) agg ON agg.[id_producto] = inv.[id_producto];
END
GO
