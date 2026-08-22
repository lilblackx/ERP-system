-- Agrega un campo de estado (ACTIVO/INACTIVO) a clientes, proveedores, inventario
-- (productos), bancos y cuentas_bancarias -- mismo patron que dbo.usuarios.estado y
-- dbo.vendedores.estado_vendedor (ya existentes, sin CHECK a nivel de BD, validado en
-- Python via ESTADOS_VALIDOS en cada servicio).
--
-- Motivo: la auditoria del 2026-08-22 encontro que eliminar_*/delete_* en estos modulos
-- (mas vendedores, que ya tenia estado_vendedor pero no lo usaba) hacian DELETE fisico
-- sin guarda -- si la fila tenia dependientes (facturas, compras, precios, cuentas,
-- movimientos, etc., todas con FK ON DELETE NO ACTION) el DELETE reventaba con un
-- IntegrityError crudo de pyodbc. Decision: en vez de agregar una guarda de conteo que
-- permita borrar cuando no hay dependientes (como CategoriaService.eliminar()/
-- RolService.eliminar_rol()), estas 5 entidades dejan de ser borrables del todo -- la
-- fila se desactiva (estado = 'INACTIVO') en vez de eliminarse, sin importar si tiene
-- dependientes o no. Ver la logica nueva en cada servicio (clientes.py, proveedores.py,
-- vendedores.py, inventario.py, tesoreria.py).

ALTER TABLE dbo.clientes ADD [estado_cliente] VARCHAR(20) NOT NULL CONSTRAINT DF_clientes_estado_cliente DEFAULT 'ACTIVO';
GO

ALTER TABLE dbo.proveedores ADD [estado_proveedor] VARCHAR(20) NOT NULL CONSTRAINT DF_proveedores_estado_proveedor DEFAULT 'ACTIVO';
GO

ALTER TABLE dbo.inventario ADD [estado_producto] VARCHAR(20) NOT NULL CONSTRAINT DF_inventario_estado_producto DEFAULT 'ACTIVO';
GO

ALTER TABLE dbo.bancos ADD [estado_banco] VARCHAR(20) NOT NULL CONSTRAINT DF_bancos_estado_banco DEFAULT 'ACTIVO';
GO

ALTER TABLE dbo.cuentas_bancarias ADD [estado_cuenta] VARCHAR(20) NOT NULL CONSTRAINT DF_cuentas_bancarias_estado_cuenta DEFAULT 'ACTIVO';
GO
