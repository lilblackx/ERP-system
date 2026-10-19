-- Permiso dedicado para AUTORIZAR la devolucion en efectivo/banco de una nota de credito
-- de cliente (NotaCreditoService.devolver_nota_credito_cliente). Deliberadamente distinto
-- de 'notas_credito'/'crear' (migrations/0028, que ya tiene cualquiera que pueda iniciar
-- una devolucion o aplicar una nota a una factura): una devolucion mueve dinero real sin
-- ninguna venta en curso que la explique, asi que necesita que quien autoriza tenga un
-- permiso que el cajero comun no tenga -- mismo criterio que 'vueltos_bancarios'/'crear'
-- (migrations/0027) es distinto de 'ventas'/'crear'.
--
-- 'editar' en vez de una accion literal ("autorizar_devolucion"): CK_permisos_accion
-- limita accion a ('ver','crear','editar','eliminar'), mismo criterio ya usado en
-- 0021/0027 para acciones no-CRUD-literales.
--
-- Igual que el resto del catalogo, no se asigna a ningun rol por default -- un ADMIN lo
-- otorga explicitamente a quien corresponda. ADMIN ya bypassa la matriz por completo.

INSERT INTO dbo.permisos ([recurso], [accion], [descripcion]) VALUES
('notas_credito', 'editar', 'Autorizar la devolucion en efectivo/banco de una nota de credito');
GO
