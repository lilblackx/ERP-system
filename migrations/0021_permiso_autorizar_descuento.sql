-- Permiso dedicado para autorizar descuentos en facturacion (venta bajo precio de lista
-- o descuento manual de factura, migrations/0020_descuentos_autorizacion.sql).
--
-- Recurso propio 'descuentos' en vez de sumarlo a 'ventas': [accion] esta limitado por
-- CK_permisos_accion a ('ver','crear','editar','eliminar') y VARCHAR(10), asi que
-- 'autorizar_descuento' no entra ni como accion. 'crear' se usa aca con el mismo
-- criterio que 0013 le dio a 'comisiones'/'crear' ("pagar comisiones acumuladas"): la
-- accion significativa de este recurso, no un CRUD literal.
--
-- Igual que el resto del catalogo agregado en 0004/0013/0016, no se asigna a ningun rol
-- por default -- queda para que un ADMIN lo otorgue explicitamente via
-- PermisoService.establecer_permisos_rol() al rol que corresponda (ej. un futuro
-- SUPERVISOR). ADMIN ya bypassa la matriz por completo, asi que siempre puede autorizar.

INSERT INTO dbo.permisos ([recurso], [accion], [descripcion]) VALUES
('descuentos', 'crear', 'Autorizar ventas por debajo del precio de lista o descuentos manuales de factura');
GO
