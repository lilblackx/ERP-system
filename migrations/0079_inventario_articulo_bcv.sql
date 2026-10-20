-- Articulo BCV: un producto marcado asi se factura siempre a su precio guardado, sin el porcentaje
-- BCV que se aplica al resto de los precios de la factura (el precio ya esta fijado en terminos BCV).
-- 0 (default) = comportamiento de siempre: el porcentaje BCV de la factura le aplica.
-- La marca se lee al facturar y al calcular la comision (la base de comision de un articulo BCV
-- tampoco lleva el porcentaje), y no cambia las facturas ya emitidas.

ALTER TABLE dbo.inventario
	ADD articulo_bcv BIT NOT NULL CONSTRAINT DF_inventario_articulo_bcv DEFAULT (0);
GO
