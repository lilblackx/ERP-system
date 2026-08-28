-- Agrega la rama FECHA a trg_compra_oc_enmienda_autorizar (migrations/0032): hasta ahora
-- solo el tipo CANTIDAD tenia efecto automatico al autorizar una enmienda; PRECIO se deja
-- deliberadamente sin efecto automatico (compra_oc_enmienda no tiene id_oc_detalle -- sin
-- eso no hay forma de saber a cual linea de producto aplica un cambio de precio cuando la
-- OC tiene varias), pero FECHA si tiene un campo unico de cabecera
-- (compra_oc.fecha_estimada_entrega) al que aplicar el cambio sin ambiguedad.
--
-- DROP + CREATE (no ALTER TRIGGER) -- mismo patron que 0024_pagos_contado_multimetodo.sql
-- al redefinir trg_pagos_cobros_io.

DROP TRIGGER trg_compra_oc_enmienda_autorizar;
GO

CREATE TRIGGER trg_compra_oc_enmienda_autorizar ON dbo.compra_oc_enmienda
AFTER UPDATE AS
BEGIN
	SET NOCOUNT ON;

	IF UPDATE([estado_enmienda])
	BEGIN
		-- CANTIDAD: identico a 0032, sin cambios.
		UPDATE co
		SET co.[cantidad_solicitada] = i.[cantidad_nueva],
			co.[estado] = 'PARCIAL'
		FROM dbo.compra_oc co
		JOIN inserted i ON i.[id_oc] = co.[id_oc]
		JOIN deleted d ON d.[id_enmienda] = i.[id_enmienda]
		WHERE i.[estado_enmienda] = 'AUTORIZADA'
			AND d.[estado_enmienda] <> 'AUTORIZADA'
			AND i.[tipo_cambio] = 'CANTIDAD'
			AND i.[cantidad_nueva] IS NOT NULL;

		-- FECHA (nuevo): unico campo de cabecera, sin la ambiguedad de linea que tiene
		-- PRECIO -- no toca [estado], una extension de fecha no cambia cuanto se recibio.
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
