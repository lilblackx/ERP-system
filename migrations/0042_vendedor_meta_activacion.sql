-- Cuota de activacion por vendedor (decision de negocio, 2026-09-03): frecuencia de
-- venta esperada por cliente (ej. 4 ventas/mes) que ReporteService.activacion_clientes()
-- usa para calcular % de efectividad = facturas del cliente en el periodo / meta del
-- vendedor asignado. Se define por VENDEDOR (no por cliente/ruta/categoria) y es
-- configurable desde VendedorFormDialog.
--
-- NULLABLE a proposito, mismo criterio que codigo_vendedor/identificacion_vendedor
-- (migrations/0031) e id_ruta (migrations/0038): un vendedor sin meta configurada no
-- rompe nada, ReporteService.activacion_clientes() simplemente no calcula efectividad
-- para sus clientes (sin meta no hay contra que comparar).

ALTER TABLE dbo.vendedores
ADD [meta_activacion] INT NULL;
GO
