-- Catalogo completo de permisos (recurso + accion) para los modulos que hoy no tienen
-- ninguna fila en dbo.permisos. El seed original (schema_sqlserver.sql) solo cubria
-- 'inventario:ver', 'reportes_ventas:ver' y 'reportes_comisiones:ver' para el rol
-- VENDEDOR -- esta migracion agrega el resto del catalogo para que
-- PermisoService.require_permiso() (app/services/permisos.py) tenga algo contra que
-- validar en cada modulo.
--
-- [accion] esta restringido por CK_permisos_accion a exactamente 'ver'/'crear'/'editar'/
-- 'eliminar' -- por eso operaciones que no son CRUD literal se mapean al mas cercano:
-- emitir factura/registrar compra -> 'crear', anular factura/compra -> 'eliminar',
-- abrir/cerrar turno de caja -> 'editar', aplicar pago -> 'crear', asignar permisos a
-- un rol -> 'editar' (es editar la matriz de ESE rol), etc.
--
-- IMPORTANTE (operacional, no de codigo): esta migracion NO asigna ninguno de estos
-- permisos nuevos a VENDEDOR/CAJERO -- solo crea el catalogo. El rol ADMIN no necesita
-- fila en rol_permisos (bypassa la matriz, ver require_permiso()), pero cualquier
-- usuario real con rol VENDEDOR/CAJERO en una base existente perdera acceso a escribir
-- en los modulos recien protegidos hasta que un ADMIN se los otorgue explicitamente via
-- PermisoService.establecer_permisos_rol() -- no hay pantalla para eso todavia.

INSERT INTO dbo.permisos ([recurso], [accion], [descripcion]) VALUES
('clientes', 'ver', 'Consultar clientes'),
('clientes', 'crear', 'Registrar clientes'),
('clientes', 'editar', 'Editar clientes'),
('clientes', 'eliminar', 'Eliminar clientes'),

('proveedores', 'ver', 'Consultar proveedores'),
('proveedores', 'crear', 'Registrar proveedores'),
('proveedores', 'editar', 'Editar proveedores'),
('proveedores', 'eliminar', 'Eliminar proveedores'),

('vendedores', 'ver', 'Consultar vendedores'),
('vendedores', 'crear', 'Registrar vendedores'),
('vendedores', 'editar', 'Editar vendedores'),
('vendedores', 'eliminar', 'Eliminar vendedores'),

('categorias', 'ver', 'Consultar categorias'),
('categorias', 'crear', 'Crear categorias'),
('categorias', 'editar', 'Editar categorias'),
('categorias', 'eliminar', 'Eliminar categorias'),

('inventario', 'crear', 'Crear productos y precios'),
('inventario', 'editar', 'Editar productos y precios'),
('inventario', 'eliminar', 'Eliminar productos y precios'),

('ventas', 'ver', 'Consultar facturas de venta'),
('ventas', 'crear', 'Emitir facturas de venta'),
('ventas', 'eliminar', 'Anular facturas de venta'),

('compras', 'ver', 'Consultar compras'),
('compras', 'crear', 'Registrar compras'),
('compras', 'eliminar', 'Anular compras'),

('bancos', 'ver', 'Consultar bancos y cuentas bancarias'),
('bancos', 'crear', 'Crear bancos y cuentas bancarias'),
('bancos', 'editar', 'Editar bancos y cuentas bancarias'),
('bancos', 'eliminar', 'Eliminar bancos y cuentas bancarias'),

('cajas', 'ver', 'Consultar cajas y sus movimientos'),
('cajas', 'crear', 'Registrar movimientos manuales de caja'),
('cajas', 'editar', 'Abrir y cerrar turnos de caja'),

('pagos', 'ver', 'Consultar pagos aplicados'),
('pagos', 'crear', 'Aplicar pagos de clientes y proveedores'),

('tasas', 'ver', 'Consultar tasas de cambio'),
('tasas', 'crear', 'Registrar tasas de cambio'),

('usuarios', 'ver', 'Consultar usuarios'),
('usuarios', 'crear', 'Crear usuarios'),
('usuarios', 'editar', 'Editar usuarios y cambiar su estado'),

('permisos', 'ver', 'Consultar roles y permisos'),
('permisos', 'crear', 'Crear roles'),
('permisos', 'editar', 'Editar roles y su matriz de permisos'),
('permisos', 'eliminar', 'Eliminar roles'),

('otros_movimientos', 'ver', 'Consultar cuentas y partidas de otros movimientos'),
('otros_movimientos', 'crear', 'Crear cuentas y partidas de otros movimientos'),
('otros_movimientos', 'editar', 'Abonar y conciliar otros movimientos'),

('empresa', 'ver', 'Consultar configuracion de la empresa'),
('empresa', 'editar', 'Editar configuracion de la empresa'),

('auditoria', 'ver', 'Consultar la bitacora de auditoria'),

('notas_credito', 'ver', 'Consultar notas de credito'),

('dashboard', 'ver', 'Consultar el panel general');
GO
