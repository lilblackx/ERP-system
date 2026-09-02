-- Nueva tabla de rutas de venta + asociacion vendedor->ruta (decision de producto,
-- 2026-09-01): cada vendedor pertenece a una ruta de reparto/cobranza, y una ruta puede
-- tener varios vendedores asignados (1 ruta : N vendedores). Configuracion de rutas vive
-- en una pestaña nueva dentro del modulo Vendedores (app/ui/rutas_panel.py).
--
-- id_ruta se agrega NULLABLE a proposito, igual que codigo_vendedor/identificacion_vendedor
-- (ver migrations/0031): un entorno con vendedores ya cargados no puede satisfacer un NOT
-- NULL sin inventar una ruta generica sobre datos reales sin revisar caso por caso. En vez
-- de eso, VendedorService.crear() es quien garantiza que todo vendedor NUEVO siempre traiga
-- una ruta -- mismo criterio que el resto de los campos "obligatorios por decision de
-- negocio, no por schema" de este modulo (codigo_vendedor/identificacion_vendedor).

IF OBJECT_ID(N'dbo.rutas', N'U') IS NULL
BEGIN
CREATE TABLE dbo.rutas (
	[id_ruta] BIGINT IDENTITY(1,1) NOT NULL,
	[nombre_ruta] VARCHAR(100) NOT NULL,
	[descripcion_ruta] VARCHAR(255) NULL,
	[estado_ruta] VARCHAR(20) NOT NULL DEFAULT 'ACTIVO',
	[fecha_creacion] DATETIME NOT NULL DEFAULT GETDATE(),
	[creado_por] BIGINT NULL,
	CONSTRAINT PK_rutas PRIMARY KEY ([id_ruta])
);
END
GO

CREATE UNIQUE INDEX UQ_rutas_nombre_ruta ON dbo.rutas ([nombre_ruta]);
GO

ALTER TABLE dbo.rutas
ADD CONSTRAINT FK_rutas_creado_por FOREIGN KEY([creado_por]) REFERENCES dbo.usuarios([id_usuario]);
GO

ALTER TABLE dbo.vendedores
ADD [id_ruta] BIGINT NULL;
GO

ALTER TABLE dbo.vendedores
ADD CONSTRAINT FK_vendedores_id_ruta FOREIGN KEY([id_ruta]) REFERENCES dbo.rutas([id_ruta]);
GO

INSERT INTO dbo.permisos ([recurso], [accion], [descripcion]) VALUES
('rutas', 'ver', 'Consultar rutas de venta'),
('rutas', 'crear', 'Registrar rutas de venta'),
('rutas', 'editar', 'Editar rutas de venta'),
('rutas', 'eliminar', 'Eliminar rutas de venta');
GO
