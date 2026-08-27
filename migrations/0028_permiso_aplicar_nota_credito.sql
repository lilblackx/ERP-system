-- Permiso dedicado para aplicar una nota de credito de cliente disponible como abono a
-- una factura futura del mismo cliente (NotaCreditoService.aplicar_nota_credito_cliente).
-- Antes solo existia 'notas_credito'/'ver' (migrations/0004) -- crear/listar las notas ya
-- estaba cubierto (crear_nota_credito_cliente es un efecto secundario interno de
-- VentaService.anular_factura, sin su propio require_permiso), pero APLICARLA es una
-- accion nueva, directamente disparada por un usuario, que necesita su propio gate.
--
-- Igual que el resto del catalogo agregado en 0004/0013/0016/0021, no se asigna a ningun
-- rol por default -- un ADMIN lo otorga explicitamente a quien corresponda. ADMIN ya
-- bypassa la matriz por completo.

INSERT INTO dbo.permisos ([recurso], [accion], [descripcion]) VALUES
('notas_credito', 'crear', 'Aplicar una nota de credito disponible como abono a una factura');
GO
