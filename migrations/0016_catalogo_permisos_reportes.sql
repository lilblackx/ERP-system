-- R-06 (docs/CHECKLIST_PRODUCCION.md): catalogo de permisos para el motor de reportes que
-- viene en R-01 (app/services/reportes.py, todavia no existe). Distinto de
-- 'reportes_ventas'/'reportes_comisiones' (seed original de schema_sqlserver.sql, 'ver'
-- unicamente, ya asignados a VENDEDOR para que consulte sus propios reportes acotados) --
-- este es el recurso general del motor de reportes/exportacion (aging CxC, arqueo de caja,
-- etc.), mismo patron que migrations/0013 para comisiones.
--
-- El filtro de "un VENDEDOR solo ve sus propias facturas" va en el servicio (comparando
-- id_vendedor), no aca -- este recurso solo controla quien puede *entrar* al modulo de
-- reportes en general.
--
-- No se asigna a ningun rol -- igual que el resto del catalogo agregado en 0004/0013,
-- queda para que un ADMIN lo otorgue explicitamente via PermisoService.establecer_permisos_rol().

INSERT INTO dbo.permisos ([recurso], [accion], [descripcion]) VALUES
('reportes', 'ver', 'Consultar y generar reportes (aging CxC/CxP, arqueo de caja, etc.)'),
('reportes', 'crear', 'Exportar reportes a Excel/PDF'),
('reportes', 'editar', 'Guardar filtros/plantillas de reporte reutilizables'),
('reportes', 'eliminar', 'Eliminar filtros/plantillas de reporte guardadas');
GO
