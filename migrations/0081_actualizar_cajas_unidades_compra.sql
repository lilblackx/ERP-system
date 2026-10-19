-- Actualizar trigger de compra_detalle para calcular automáticamente cajas y unidades sueltas
-- Cuando se compra directamente sin OC/NR, se calculan las cajas completas y unidades sueltas
-- basado en la cantidad total y unidades por caja del producto.

DROP TRIGGER trg_compra_detalle_stock_ins;
GO

CREATE TRIGGER trg_compra_detalle_stock_ins ON dbo.compra_detalle
AFTER INSERT AS
BEGIN
	SET NOCOUNT ON;
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] + agg.[total_cant],
		-- Calcular cajas completas y unidades sueltas basado en cantidad_caja
		inv.[cantidad_caja_total] = CASE
			WHEN inv.[cantidad_caja] > 0 AND inv.[cantidad_caja] IS NOT NULL
			THEN FLOOR((inv.[cantidad_unidad] + agg.[total_cant]) / inv.[cantidad_caja])
			ELSE 0
		END,
		inv.[cantidad_caja_unidad] = CASE
			WHEN inv.[cantidad_caja] > 0 AND inv.[cantidad_caja] IS NOT NULL
			THEN (inv.[cantidad_unidad] + agg.[total_cant]) % inv.[cantidad_caja]
			ELSE (inv.[cantidad_unidad] + agg.[total_cant])
		END
	FROM dbo.inventario inv
	JOIN (
		SELECT [id_producto_compra], SUM([cantidad_producto]) AS [total_cant]
		FROM inserted
		WHERE [stock_ya_contabilizado] = 0
		GROUP BY [id_producto_compra]
	) agg ON agg.[id_producto_compra] = inv.[id_producto];
END
GO
