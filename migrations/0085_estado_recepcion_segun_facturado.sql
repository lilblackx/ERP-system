-- nota_recepcion.estado nunca cambiaba: toda NR quedaba 'RECIBIDA' (el default) y los
-- filtros Parcial/Facturada de la pestana Recepciones no mostraban nada.
--
-- Estado de una NR segun cuanto de lo ACEPTADO en ella (cantidad_recibida -
-- cantidad_rechazada) ya fue facturado al proveedor:
--   RECIBIDA  : nada facturado (o no hay nada aceptado que facturar)
--   PARCIAL   : una parte facturada
--   FACTURADA : todo lo aceptado ya facturado
-- La factura de compra se hace por LINEA de OC (compra_oc_detalle.cantidad_facturada), no
-- por NR, asi que lo facturado de cada linea se reparte entre las NR de esa linea en orden
-- de llegada: la mas vieja se factura primero (FIFO).
--
-- fn_estado_nr_oc calcula el estado de TODAS las NR de una OC; lo usan este trigger
-- (cuando cambia cantidad_facturada), trg_nota_recepcion_detalle_ins (migrations/0086,
-- cuando entra una NR nueva) y el backfill de abajo. No toca 'ANULADA'.

IF OBJECT_ID('dbo.fn_estado_nr_oc', 'IF') IS NOT NULL
	DROP FUNCTION dbo.fn_estado_nr_oc;
GO

CREATE FUNCTION dbo.fn_estado_nr_oc (@id_oc BIGINT)
RETURNS TABLE
AS
RETURN
(
	WITH lineas AS (
		SELECT
			nrd.[id_nr],
			cod.[cantidad_facturada] AS [facturada],
			nrd.[cantidad_recibida] - nrd.[cantidad_rechazada] AS [aceptada],
			ISNULL(SUM(nrd.[cantidad_recibida] - nrd.[cantidad_rechazada]) OVER (
				PARTITION BY nrd.[id_oc_detalle]
				ORDER BY nrd.[id_nr], nrd.[id_detalle]
				ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
			), 0) AS [aceptada_previa]
		FROM dbo.nota_recepcion_detalle nrd
		JOIN dbo.nota_recepcion nr ON nr.[id_nr] = nrd.[id_nr]
		JOIN dbo.compra_oc_detalle cod ON cod.[id_detalle] = nrd.[id_oc_detalle]
		WHERE nr.[id_oc] = @id_oc AND nr.[estado] <> 'ANULADA'
	),
	asignadas AS (
		SELECT
			[id_nr],
			[aceptada],
			CASE
				WHEN [facturada] - [aceptada_previa] <= 0 THEN 0
				WHEN [facturada] - [aceptada_previa] >= [aceptada] THEN [aceptada]
				ELSE [facturada] - [aceptada_previa]
			END AS [asignada]
		FROM lineas
	)
	SELECT
		[id_nr],
		CASE
			WHEN SUM([aceptada]) <= 0 OR SUM([asignada]) <= 0 THEN 'RECIBIDA'
			WHEN SUM([asignada]) >= SUM([aceptada]) THEN 'FACTURADA'
			ELSE 'PARCIAL'
		END AS [estado]
	FROM asignadas
	GROUP BY [id_nr]
);
GO

IF OBJECT_ID('dbo.trg_compra_oc_detalle_estado_nr', 'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_compra_oc_detalle_estado_nr;
GO

CREATE TRIGGER trg_compra_oc_detalle_estado_nr ON dbo.compra_oc_detalle
AFTER UPDATE AS
BEGIN
	SET NOCOUNT ON;

	IF UPDATE([cantidad_facturada])
	BEGIN
		UPDATE nr
		SET nr.[estado] = e.[estado]
		FROM (SELECT DISTINCT [id_oc] FROM inserted) o
		CROSS APPLY dbo.fn_estado_nr_oc(o.[id_oc]) e
		JOIN dbo.nota_recepcion nr ON nr.[id_nr] = e.[id_nr]
		WHERE nr.[estado] <> 'ANULADA' AND nr.[estado] <> e.[estado];
	END
END
GO

-- Backfill: las NR ya registradas quedaron todas en 'RECIBIDA'.
UPDATE nr
SET nr.[estado] = e.[estado]
FROM (SELECT DISTINCT [id_oc] FROM dbo.nota_recepcion) o
CROSS APPLY dbo.fn_estado_nr_oc(o.[id_oc]) e
JOIN dbo.nota_recepcion nr ON nr.[id_nr] = e.[id_nr]
WHERE nr.[estado] <> 'ANULADA' AND nr.[estado] <> e.[estado];
GO
