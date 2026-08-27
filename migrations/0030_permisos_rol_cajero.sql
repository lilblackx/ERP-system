-- Define el modelo final de roles acordado con el usuario (2026-08-27): ADMIN
-- (superadmin, bypassa la matriz por completo, ver require_permiso()), CAJERO (opera el
-- dia a dia: factura, cobra, aplica/devuelve notas de credito) y VENDEDOR (rep de campo
-- de solo lectura: existencia de inventario + sus propios reportes -- ya cubierto por el
-- seed original de schema_sqlserver.sql, sin cambios aca).
--
-- migrations/0004 creo el catalogo de permisos pero deliberadamente NO se lo asigno a
-- CAJERO ("queda para que un ADMIN lo otorgue explicitamente via
-- PermisoService.establecer_permisos_rol() -- no hay pantalla para eso todavia"). Esta
-- migracion es ese otorgamiento ahora que la pantalla (app/ui/roles_permisos_panel.py)
-- ya existe -- se deja como seed inicial razonable, ajustable despues desde esa UI sin
-- tocar codigo.
--
-- No se le da a CAJERO: 'usuarios'/'permisos' (evita que pueda gestionar cuentas o
-- escalar su propio rol), 'descuentos'/'creditos'/'vueltos_bancarios'/'notas_credito'
-- 'editar' (autorizaciones de supervisor -- sin un rol intermedio todavia, quedan solo
-- para ADMIN), 'empresa'/'auditoria' (configuracion fiscal y bitacora), y
-- 'proveedores'/'compras'/'bancos'/'tasas'/'categorias'/'otros_movimientos'/'comisiones'/
-- 'reportes' (back-office, fuera del dia a dia de caja -- a definir mas adelante si hace
-- falta).
--
-- 'cajas'/'crear' le permite registrar movimientos manuales y que sus cobros de contado
-- muevan la caja (via VentaService.emitir_factura); abrir/cerrar turno sigue restringido
-- a ADMIN literal sin importar la matriz (ver _require_admin en tesoreria.py, decision de
-- diseno aparte, no se toca aca).

INSERT INTO dbo.rol_permisos ([id_rol], [id_permiso])
SELECT r.[id_rol], p.[id_permiso]
FROM dbo.roles r
JOIN dbo.permisos p ON (
    (p.[recurso] = 'dashboard' AND p.[accion] = 'ver')
    OR (p.[recurso] = 'clientes' AND p.[accion] IN ('ver', 'crear'))
    OR (p.[recurso] = 'inventario' AND p.[accion] = 'ver')
    OR (p.[recurso] = 'ventas' AND p.[accion] IN ('ver', 'crear'))
    OR (p.[recurso] = 'pagos' AND p.[accion] IN ('ver', 'crear'))
    OR (p.[recurso] = 'notas_credito' AND p.[accion] IN ('ver', 'crear'))
    OR (p.[recurso] = 'cajas' AND p.[accion] IN ('ver', 'crear'))
    OR (p.[recurso] = 'vendedores' AND p.[accion] = 'ver')
)
WHERE r.[nombre] = 'CAJERO';
GO
