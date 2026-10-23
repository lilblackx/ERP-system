-- Las enmiendas de OC de tipo CANTIDAD ajustaban solo la cabecera (compra_oc.
-- cantidad_solicitada), no las lineas: la recepcion y la factura validan contra las
-- LINEAS, asi que autorizar una enmienda no cambiaba nada de lo que realmente se podia
-- recibir o facturar, y dejaba la OC en 'PARCIAL' sin haber recibido nada. PRECIO nunca
-- tuvo efecto (no habia a que linea aplicarlo).
--
-- Ahora CANTIDAD y PRECIO se enmiendan POR LINEA (compra_oc_enmienda.id_oc_detalle). Al
-- autorizarse, el trigger ajusta esa linea (cantidad/pendiente/precio/total_linea) y
-- recalcula la cabecera de la OC desde sus lineas: cantidad_solicitada, total_oc y estado
-- (PENDIENTE/PARCIAL/COMPLETA segun lo recibido, igual que trg_nota_recepcion_detalle_ins).
-- FECHA sigue siendo un campo unico de cabecera, sin cambios.
--
-- Enmiendas CANTIDAD/PRECIO viejas, sin id_oc_detalle (nunca tuvieron efecto real), no se
-- aplican: el servicio ahora exige la linea al crearlas.

IF COL_LENGTH('dbo.compra_oc_enmienda', 'id_oc_detalle') IS NULL
BEGIN
	ALTER TABLE dbo.compra_oc_enmienda ADD [id_oc_detalle] BIGINT NULL;
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_compra_oc_enmienda_oc_detalle')
BEGIN
	ALTER TABLE dbo.compra_oc_enmienda
	ADD CONSTRAINT FK_compra_oc_enmienda_oc_detalle
		FOREIGN KEY ([id_oc_detalle]) REFERENCES dbo.compra_oc_detalle([id_detalle]);
END
GO

IF OBJECT_ID('dbo.trg_compra_oc_enmienda_autorizar', 'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_compra_oc_enmienda_autorizar;
GO

CREATE TRIGGER trg_compra_oc_enmienda_autorizar ON dbo.compra_oc_enmienda
AFTER UPDATE AS
BEGIN
	SET NOCOUNT ON;

	IF UPDATE([estado_enmienda])
	BEGIN
		-- CANTIDAD (por linea): nunca por debajo de lo ya recibido -- el servicio lo valida
		-- con un mensaje claro; este WHERE es la defensa de ultima linea para que
		-- cantidad_pendiente no quede negativa.
		UPDATE cod
		SET cod.[cantidad_solicitada] = i.[cantidad_nueva],
			cod.[cantidad_pendiente] = i.[cantidad_nueva] - cod.[cantidad_recibida],
			cod.[total_linea] = i.[cantidad_nueva] * cod.[precio_unitario]
		FROM dbo.compra_oc_detalle cod
		JOIN inserted i ON i.[id_oc_detalle] = cod.[id_detalle]
		JOIN deleted d ON d.[id_enmienda] = i.[id_enmienda]
		WHERE i.[estado_enmienda] = 'AUTORIZADA'
			AND d.[estado_enmienda] <> 'AUTORIZADA'
			AND i.[tipo_cambio] = 'CANTIDAD'
			AND i.[cantidad_nueva] IS NOT NULL
			AND i.[cantidad_nueva] >= cod.[cantidad_recibida];

		-- PRECIO (por linea): afecta lo que todavia se facture; las facturas ya hechas
		-- guardan su propio costo_unitario y no cambian.
		UPDATE cod
		SET cod.[precio_unitario] = i.[precio_nuevo],
			cod.[total_linea] = cod.[cantidad_solicitada] * i.[precio_nuevo]
		FROM dbo.compra_oc_detalle cod
		JOIN inserted i ON i.[id_oc_detalle] = cod.[id_detalle]
		JOIN deleted d ON d.[id_enmienda] = i.[id_enmienda]
		WHERE i.[estado_enmienda] = 'AUTORIZADA'
			AND d.[estado_enmienda] <> 'AUTORIZADA'
			AND i.[tipo_cambio] = 'PRECIO'
			AND i.[precio_nuevo] IS NOT NULL;

		-- Cabecera derivada de las lineas, solo para las OC con un cambio de linea.
		UPDATE co
		SET co.[cantidad_solicitada] = ISNULL((SELECT SUM(cod.[cantidad_solicitada]) FROM dbo.compra_oc_detalle cod WHERE cod.[id_oc] = co.[id_oc]), 0),
			co.[total_oc] = ISNULL((SELECT SUM(cod.[total_linea]) FROM dbo.compra_oc_detalle cod WHERE cod.[id_oc] = co.[id_oc]), 0),
			co.[estado] = CASE
				WHEN ISNULL((SELECT SUM(cod.[cantidad_recibida]) FROM dbo.compra_oc_detalle cod WHERE cod.[id_oc] = co.[id_oc]), 0)
					>= ISNULL((SELECT SUM(cod.[cantidad_solicitada]) FROM dbo.compra_oc_detalle cod WHERE cod.[id_oc] = co.[id_oc]), 0)
				THEN 'COMPLETA'
				WHEN ISNULL((SELECT SUM(cod.[cantidad_recibida]) FROM dbo.compra_oc_detalle cod WHERE cod.[id_oc] = co.[id_oc]), 0) > 0
				THEN 'PARCIAL'
				ELSE 'PENDIENTE'
			END
		FROM dbo.compra_oc co
		WHERE co.[estado] <> 'ANULADA'
			AND co.[id_oc] IN (
				SELECT i.[id_oc]
				FROM inserted i
				JOIN deleted d ON d.[id_enmienda] = i.[id_enmienda]
				WHERE i.[estado_enmienda] = 'AUTORIZADA'
					AND d.[estado_enmienda] <> 'AUTORIZADA'
					AND i.[tipo_cambio] IN ('CANTIDAD', 'PRECIO')
					AND i.[id_oc_detalle] IS NOT NULL
			);

		-- FECHA: unico campo de cabecera, sin la ambiguedad de linea -- no toca [estado].
		UPDATE co
		SET co.[fecha_estimada_entrega] = i.[fecha_entrega_nueva]
		FROM dbo.compra_oc co
		JOIN inserted i ON i.[id_oc] = co.[id_oc]
		JOIN deleted d ON d.[id_enmienda] = i.[id_enmienda]
		WHERE i.[estado_enmienda] = 'AUTORIZADA'
			AND d.[estado_enmienda] <> 'AUTORIZADA'
			AND i.[tipo_cambio] = 'FECHA'
			AND i.[fecha_entrega_nueva] IS NOT NULL;
	END
END
GO
