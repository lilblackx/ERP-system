-- Vendedores no tenia proteccion de unicidad para codigo_vendedor/identificacion_vendedor
-- (a diferencia de clientes.codigo_cliente/identificacion_cliente, que ya la tienen desde
-- el schema base) -- se podian crear vendedores duplicados con el mismo codigo interno o
-- cedula sin que nada lo impidiera, ni en servicio ni en BD (hallazgo de auditoria
-- Vendedores/Clientes, 2026-08-27).
--
-- INDICE UNICO FILTRADO, no `ADD CONSTRAINT ... UNIQUE`: a diferencia del estandar ANSI
-- SQL (y de Postgres), SQL Server trata todos los NULL como el MISMO valor dentro de una
-- UNIQUE CONSTRAINT/INDEX normal -- permite como maximo UNA fila con NULL, no muchas.
-- clientes.codigo_cliente/identificacion_cliente usan un UNIQUE plano sin problema solo
-- porque ClienteService los exige siempre no vacios (_validar_requeridos), asi que el caso
-- "dos NULL" nunca ocurre ahi. codigo_vendedor/identificacion_vendedor SI son opcionales
-- por diseno (formulario sin asterisco) -- un UNIQUE plano habria roto crear el segundo
-- vendedor sin codigo/identificacion (reventaba en pruebas, 2026-08-27). La clausula WHERE
-- excluye los NULL del indice, dejando que existan cuantas filas NULL se quiera mientras
-- los valores no-NULL si sean unicos entre si.

CREATE UNIQUE INDEX UQ_vendedores_codigo_vendedor ON dbo.vendedores ([codigo_vendedor]) WHERE [codigo_vendedor] IS NOT NULL;
GO

CREATE UNIQUE INDEX UQ_vendedores_identificacion_vendedor ON dbo.vendedores ([identificacion_vendedor]) WHERE [identificacion_vendedor] IS NOT NULL;
GO
