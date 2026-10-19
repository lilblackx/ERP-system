-- Paso 4 del flujo OC -> NR -> Compra -> Pago: acciones de permiso dedicadas para las
-- operaciones de negocio de app/services/compra_oc.py y app/services/nota_recepcion.py
-- (paso 3), que hoy corren todas contra el generico ('compras', 'crear') -- resuelve la
-- deuda tecnica anotada en esa sesion (autorizar_enmienda sin permiso propio).
--
-- CK_permisos_accion (schema_sqlserver.sql) restringe [accion] a exactamente
-- 'ver'/'crear'/'editar'/'eliminar' -- un enum COMPARTIDO por todos los recursos, no por
-- fila. Para las 5 acciones nuevas (mas especificas que ese CRUD generico) hay que
-- ensanchar la columna (VARCHAR(10) no alcanza para 'autorizar_enmienda_oc', 21
-- caracteres) y el CHECK, agregando los 5 valores nuevos a la lista sin sacar los 4
-- existentes (los sigue usando el resto del catalogo).
--
-- 'autorizar_enmienda_oc' queda reservada a ADMIN a proposito: esta migracion NO se la
-- otorga a ningun rol en rol_permisos (mismo patron que 0004 con VENDEDOR/CAJERO -- el
-- catalogo se crea aparte de la asignacion). Como ADMIN bypassa la matriz por completo
-- (ver require_permiso()), ningun otro rol podra autorizar enmiendas hasta que un ADMIN
-- se lo otorgue explicitamente via PermisoService.establecer_permisos_rol().

ALTER TABLE dbo.permisos DROP CONSTRAINT CK_permisos_accion;
GO

ALTER TABLE dbo.permisos ALTER COLUMN [accion] VARCHAR(30) NOT NULL;
GO

ALTER TABLE dbo.permisos ADD CONSTRAINT CK_permisos_accion CHECK ([accion] IN (
	'ver', 'crear', 'editar', 'eliminar',
	'crear_oc', 'recibir_mercancia', 'crear_nota_devolucion', 'crear_enmienda_oc', 'autorizar_enmienda_oc'
));
GO

INSERT INTO dbo.permisos ([recurso], [accion], [descripcion]) VALUES
('compras', 'crear_oc', 'Crear ordenes de compra'),
('compras', 'recibir_mercancia', 'Registrar notas de recepcion de mercancia contra una orden de compra'),
('compras', 'crear_nota_devolucion', 'Registrar notas de devolucion de mercancia rechazada a un proveedor'),
('compras', 'crear_enmienda_oc', 'Proponer una enmienda (cambio) a una orden de compra ya emitida'),
('compras', 'autorizar_enmienda_oc', 'Autorizar o rechazar una enmienda propuesta a una orden de compra');
GO
