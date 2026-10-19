-- Permiso dedicado para invocar directamente NotaCreditoService.crear_nota_credito_cliente()
-- y crear_nota_credito_proveedor() (los metodos publicos, no el nucleo privado
-- _crear_nota_credito_* que VentaService.anular_factura()/CompraService.anular_compra()
-- usan internamente ya bajo su propio require_permiso("ventas"/"compras", "eliminar")).
--
-- Hasta ahora estos dos metodos publicos no tenian su propio require_permiso -- decision
-- documentada en notas_credito.py y en 0028_permiso_aplicar_nota_credito.sql como
-- intencional, porque no existia ningun callsite de UI que los llamara directo (solo el
-- flujo interno de anulacion, y tests). Se cierra ahora para que dejen de ser invocables
-- sin permiso si en el futuro se agrega un callsite de UI que los use directo, sin
-- depender de que quien los llame recuerde repetir el chequeo.
--
-- 'eliminar' en vez de 'crear': 'notas_credito'/'crear' ya esta en uso
-- (0028_permiso_aplicar_nota_credito.sql) para una accion distinta (aplicar una nota
-- existente como abono), y 'notas_credito'/'editar' tambien esta en uso
-- (0029_permiso_devolver_nota_credito.sql, autorizar devolucion). 'eliminar' es la unica
-- accion del enum CK_permisos_accion ('ver','crear','editar','eliminar') que queda libre
-- para este recurso -- mismo criterio ya usado en 0021/0027/0029 de mapear una accion
-- no-CRUD-literal a la mas cercana disponible.
--
-- Igual que el resto del catalogo, no se asigna a ningun rol por default -- un ADMIN lo
-- otorga explicitamente a quien corresponda. ADMIN ya bypassa la matriz por completo.

INSERT INTO dbo.permisos ([recurso], [accion], [descripcion]) VALUES
('notas_credito', 'eliminar', 'Generar una nota de credito directamente (fuera del flujo automatico de anulacion)');
GO
