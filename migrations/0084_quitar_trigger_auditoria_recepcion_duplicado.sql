-- trg_auditoria_recepcion_mercancia (migrations/0080) duplicaba la auditoria de
-- recepcion: NotaRecepcionService.crear_nota_recepcion ya registra un evento
-- RECEPCION_MERCANCIA por linea, asi que cada recepcion quedaba anotada dos veces. Ademas
-- el texto del trigger terminaba en "id_detalle: <id de nota_recepcion_detalle>", y el
-- filtro por producto de ProductoAuditoriaDialog lo comparaba contra el id_producto --
-- mostraba recepciones de otros productos. Se conserva solo el evento del servicio, que
-- identifica el producto con "(ID: <id_producto>)".

IF OBJECT_ID('dbo.trg_auditoria_recepcion_mercancia', 'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_auditoria_recepcion_mercancia;
GO
