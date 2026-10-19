-- C14 (parte 3/3): catalogo de permisos para el modulo de gestion de comisiones
-- (ComisionService/PagoComisionService, app/services/comisiones.py). Distinto de
-- 'reportes_comisiones' (solo 'ver', ya asignado a VENDEDOR en el seed original de
-- schema_sqlserver.sql para que un vendedor consulte sus propias comisiones) -- este es
-- el CRUD de gestion (calcular/pagar), analogo a 'pagos'/'inventario'. Igual que
-- migrations/0004, [accion] mapea "aplicar pago de comision" -> 'crear' (mismo criterio
-- que 'pagos'/'crear' en app/services/pagos.py).
--
-- No se asigna a ningun rol -- igual que el resto del catalogo agregado en 0004, queda
-- para que un ADMIN lo otorgue explicitamente via PermisoService.establecer_permisos_rol().

INSERT INTO dbo.permisos ([recurso], [accion], [descripcion]) VALUES
('comisiones', 'ver', 'Consultar comisiones calculadas y pagos de comision'),
('comisiones', 'crear', 'Pagar comisiones acumuladas de un vendedor'),
('comisiones', 'editar', 'Ajustar comisiones calculadas'),
('comisiones', 'eliminar', 'Eliminar comisiones calculadas por error');
GO
