-- La mercancia RECHAZADA al recibir no entra al stock. Antes, trg_nota_recepcion_detalle_ins
-- sumaba la cantidad BRUTA recibida y trg_nota_devolucion_detalle_ins la restaba recien al
-- registrar la devolucion al proveedor: mientras tanto el stock estaba inflado (se podia
-- vender mercancia defectuosa) y, si se vendia, la devolucion fallaba por stock negativo
-- (CK_inventario_cantidad_unidad_no_negativa).
--
-- Ahora el stock sube solo por lo ACEPTADO (cantidad_recibida - cantidad_rechazada) y la
-- nota de devolucion es solo el documento que respalda lo rechazado: ya no mueve stock,
-- asi que se elimina trg_nota_devolucion_detalle_ins.
--
-- Este archivo tambien actualiza trg_nota_recepcion_detalle_ins para recalcular el estado
-- de las NR de la OC (ver migrations/0085) cuando entra una recepcion nueva.
--
-- AJUSTE DE DATOS (una sola vez): el stock actual todavia incluye lo rechazado que NO se
-- ha devuelto aun (lo ya devuelto ya fue restado por el trigger viejo). Se resta esa
-- diferencia por producto: SUM(rechazado) - SUM(devuelto). Si parte ya se vendio, el
-- stock no puede quedar negativo -- se deja en 0 (piso). Hacer respaldo de la base antes
-- de aplicar en un entorno con datos reales.

IF OBJECT_ID('dbo.trg_nota_recepcion_detalle_ins', 'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_nota_recepcion_detalle_ins;
GO

CREATE TRIGGER trg_nota_recepcion_detalle_ins ON dbo.nota_recepcion_detalle
AFTER INSERT AS
BEGIN
	SET NOCOUNT ON;

	-- 1) cantidad_recibida/cantidad_pendiente por linea de OC, recalculada desde la tabla
	-- completa (no solo "inserted") para que sea correcta sin importar cuantas
	-- recepciones parciales hubo antes. cantidad_recibida es la cantidad BRUTA (incluye
	-- lo rechazado): la OC pide X y el proveedor entrego X, aunque parte volvio.
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

	-- 3) Stock: sube solo lo ACEPTADO (recibido - rechazado). Agregado por producto (no
	-- fila por fila) para no perder cantidad si una misma NR trae varias lineas del
	-- mismo producto.
	UPDATE inv
	SET inv.[cantidad_unidad] = inv.[cantidad_unidad] + agg.[total_cant]
	FROM dbo.inventario inv
	JOIN (
		SELECT [id_producto], SUM([cantidad_recibida] - [cantidad_rechazada]) AS [total_cant]
		FROM inserted
		GROUP BY [id_producto]
	) agg ON agg.[id_producto] = inv.[id_producto];

	-- 4) cantidad_caja_total / cantidad_caja_unidad derivadas de cantidad_unidad.
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

	-- 5) Estado de las NR de la OC (la NR nueva entra como RECIBIDA por default; si la
	-- linea ya estaba facturada de antes -- facturar es posible tras una recepcion previa
	-- -- las NR posteriores reparten lo facturado FIFO, ver fn_estado_nr_oc).
	UPDATE nr
	SET nr.[estado] = e.[estado]
	FROM (
		SELECT DISTINCT n.[id_oc]
		FROM inserted i
		JOIN dbo.nota_recepcion n ON n.[id_nr] = i.[id_nr]
	) o
	CROSS APPLY dbo.fn_estado_nr_oc(o.[id_oc]) e
	JOIN dbo.nota_recepcion nr ON nr.[id_nr] = e.[id_nr]
	WHERE nr.[estado] <> 'ANULADA' AND nr.[estado] <> e.[estado];
END
GO

IF OBJECT_ID('dbo.trg_nota_devolucion_detalle_ins', 'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_nota_devolucion_detalle_ins;
GO

-- Ajuste de datos (ver encabezado). Solo productos con rechazado pendiente de devolver.
UPDATE inv
SET inv.[cantidad_unidad] = CASE
		WHEN inv.[cantidad_unidad] - p.[pendiente] < 0 THEN 0
		ELSE inv.[cantidad_unidad] - p.[pendiente]
	END
FROM dbo.inventario inv
JOIN (
	SELECT
		r.[id_producto],
		r.[rechazado] - ISNULL(d.[devuelto], 0) AS [pendiente]
	FROM (
		SELECT [id_producto], SUM([cantidad_rechazada]) AS [rechazado]
		FROM dbo.nota_recepcion_detalle
		GROUP BY [id_producto]
	) r
	LEFT JOIN (
		SELECT [id_producto], SUM([cantidad_devuelta]) AS [devuelto]
		FROM dbo.nota_devolucion_detalle
		GROUP BY [id_producto]
	) d ON d.[id_producto] = r.[id_producto]
	WHERE r.[rechazado] - ISNULL(d.[devuelto], 0) > 0
) p ON p.[id_producto] = inv.[id_producto];
GO

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
WHERE inv.[id_producto] IN (SELECT DISTINCT [id_producto] FROM dbo.nota_recepcion_detalle WHERE [cantidad_rechazada] > 0);
GO
