-- R-05 (docs/CHECKLIST_PRODUCCION.md): los indices de migrations/0007 son, salvo el
-- compuesto de C14, de columna unica. Una consulta tipica de reporte (rango de fechas +
-- filtro de estado, ej. "facturas emitidas entre X y Y que no esten ANULADA") no puede
-- usar dos indices de columna unica a la vez -- SQL Server elige uno, hace un range scan
-- y despues un key lookup por cada fila para traer el resto de columnas filtradas/
-- proyectadas. No reemplazan los indices de 0007 (esos siguen sirviendo consultas que
-- filtran solo por estado, ej. anular_factura), son un indice adicional para el patron
-- de reporte por rango + estado.

-- factura_venta: aging/reportes por rango de fecha_emision + estado_factura,
-- proyectando total_venta sin volver a la tabla base (INCLUDE).
CREATE INDEX IX_factura_venta_fecha_estado ON dbo.factura_venta ([fecha_emision], [estado_factura])
INCLUDE ([total_venta]);
GO

-- compras: equivalente de factura_venta para reportes de compras.
CREATE INDEX IX_compras_fecha_estado ON dbo.compras ([fecha_emision], [estado_compra])
INCLUDE ([total_compra]);
GO

-- cuentas_por_cobrar: el reporte de aging de CxC filtra por estado (pendiente/parcial/
-- vencida) y ordena/agrupa por fecha_vencimiento para armar los rangos (0-30, 31-60, ...).
CREATE INDEX IX_cuentas_por_cobrar_estado_vencimiento ON dbo.cuentas_por_cobrar ([estado], [fecha_vencimiento])
INCLUDE ([saldo_pendiente]);
GO

-- cuentas_por_pagar: equivalente de cuentas_por_cobrar para el aging de CxP.
CREATE INDEX IX_cuentas_por_pagar_estado_vencimiento ON dbo.cuentas_por_pagar ([estado], [fecha_vencimiento])
INCLUDE ([saldo_pendiente]);
GO
