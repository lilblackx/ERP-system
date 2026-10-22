-- Agregar trigger de auditoría para recepción de mercancía
-- Registra en la tabla auditoria cada vez que se recibe mercancía (nota_recepcion_detalle)
-- con el formato: "Recepción de X unidades de [PRODUCTO] de la OC [OC] en la NR [NR], id_detalle: [ID]"

IF OBJECT_ID('dbo.trg_auditoria_recepcion_mercancia', 'TR') IS NOT NULL
	DROP TRIGGER dbo.trg_auditoria_recepcion_mercancia;
GO

CREATE TRIGGER trg_auditoria_recepcion_mercancia ON dbo.nota_recepcion_detalle
AFTER INSERT AS
BEGIN
	SET NOCOUNT ON;

	DECLARE @usuario_recepcion BIGINT;
	DECLARE @nr_numero VARCHAR(20);
	DECLARE @oc_numero VARCHAR(20);

	-- Obtener el usuario que realizó la recepción y los números de NR y OC
	SELECT TOP 1
		@usuario_recepcion = nr.id_usuario_recepcion,
		@nr_numero = nr.numero_nr,
		@oc_numero = co.numero_oc
	FROM dbo.nota_recepcion nr
	JOIN dbo.compra_oc co ON co.id_oc = nr.id_oc
	JOIN inserted i ON i.id_nr = nr.id_nr;

	-- Insertar registro de auditoría por cada línea de detalle recibida
	INSERT INTO dbo.auditoria (id_usuario, accion, modulo, detalle, fecha_evento)
	SELECT
		@usuario_recepcion,
		'RECEPCION_MERCANCIA',
		'INVENTARIO',
		'Recepción de ' + CAST(i.cantidad_recibida AS VARCHAR(20)) + ' unidades de ' + inv.nombre_producto + ' de la OC ' + @oc_numero + ' en la NR ' + @nr_numero + ', id_detalle: ' + CAST(i.id_detalle AS VARCHAR(20)),
		GETDATE()
	FROM inserted i
	JOIN dbo.inventario inv ON inv.id_producto = i.id_producto;
END
GO
