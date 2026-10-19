-- Actualizar trigger de recepción para calcular automáticamente cajas y unidades sueltas
-- Cuando se recibe mercancia, se calculan las cajas completas y unidades sueltas
-- basado en la cantidad total y unidades por caja del producto.

DROP TRIGGER trg_nota_recepcion_detalle_ins;
GO

CREATE TRIGGER trg_nota_recepcion_detalle_ins ON dbo.nota_recepcion_detalle
AFTER INSERT AS
BEGIN
	SET NOCOUNT ON;

	-- 1) cantidad_recibida/cantidad_pendiente por linea de OC, recalculada desde la tabla
	-- completa (no solo "inserted") -- mismo criterio que trg_compra_total_ins -- para que
	-- sea correcta sin importar cuantas recepciones parciales hubo antes.
	UPDATE cod
	SET cod.[cantidad_recibida] = ISNULL((
			SELECT SUM(nrd.[cantidad_recibida]) FROM dbo.nota_recepcion_detalle nrd WHERE nrd.[id_oc_detalle] = cod.[id_detalle]
		), 0),
		cod.[cantidad_pendiente] = cod.[cantidad_solicitada] - ISNULL((
			SELECT SUM(nrd.[cantidad_recibida]) FROM dbo.nota_recepcion_detalle nrd WHERE nrd.[id_oc_detalle] = cod.[id_detalle]
		), 0)
	FROM dbo.compra_oc_detalle cod
	WHERE cod.[id_detalle] IN (SELECT DISTINCT [id_oc_detalle] FROM inserted);

	-- 2) cantidad_recibida + estado de la OC, derivados de sus lineas. Nunca pisa una OC ya
	-- ANULADA -- una recepcion tardia sobre una OC anulada no deberia resucitarla.
	UPDATE co
	SET co.[cantidad_recibida] = ISNULL((
			SELECT SUM(cod.[cantidad_recibida]) FROM dbo.compra_oc_detalle cod WHERE cod.[id_oc] = co.[id_oc]
		), 0),
		co.[estado] = CASE
			WHEN ISNULL((SELECT SUM(cod.[cantidad_recibida]) FROM dbo.compra_oc_detalle cod WHERE cod.[id_oc] = co.[id_oc]), 0)
				>= ISNULL((SELECT SUM(cod.[cantidad_solicitada]) FROM dbo.compra_oc_detalle cod WHERE cod.[id_oc] = co.[id_oc]), 0)
			THEN 'COMPLETA'
			ELSE 'PARCIAL'
		END
	FROM dbo.compra_oc co
	WHERE co.[estado] <> 'ANULADA'
		AND co.[id_oc] IN (
			SELECT DISTINCT cod.[id_oc]
			FROM dbo.compra_oc_detalle cod
			JOIN inserted i ON i.[id_oc_detalle] = cod.[id_detalle]
		);

	-- 3) Stock sube al recibir (no al facturar, ver BLOQUE E) -- cantidad BRUTA recibida;
	-- cantidad_rechazada es solo informativo en esta linea, se descuenta recien si/cuando
	-- exista una nota_devolucion real (ver trg_nota_devolucion_detalle_ins). Agregado por
	-- producto (no fila por fila) para no perder cantidad si una misma NR trae varias
	-- lineas del mismo producto.
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
		SELECT [id_producto], SUM([cantidad_recibida]) AS [total_cant]
		FROM inserted
		GROUP BY [id_producto]
	) agg ON agg.[id_producto] = inv.[id_producto];
END
GO
