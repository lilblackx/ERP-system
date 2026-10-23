-- "Otros movimientos": que cada peso quede respaldado por un movimiento real.
--
-- 1) Una transferencia sin identificar (cuentas_por_pagar_otros) ahora SIEMPRE apunta al
--    movimiento bancario que la trajo, y cada movimiento puede originar UNA sola partida. Antes
--    id_movimiento era opcional y repetible: se podian crear varias partidas (cada una con su
--    saldo) sobre la misma transferencia, o partidas sin ningun movimiento detras, y con eso
--    saldar mas facturas de las que el dinero real alcanzaba.
-- 2) conciliaciones_partida: cada vez que una partida se aplica a una factura queda un registro
--    (partida, factura, monto, quien, cuando). Antes solo bajaba el saldo de la factura y el
--    historial del cliente no mostraba ningun abono.
--
-- Las partidas viejas sin movimiento (id_movimiento NULL) se conservan: el indice unico es
-- filtrado. Si ya hubiera DOS partidas sobre el mismo movimiento, la migracion se detiene con un
-- mensaje claro en vez de elegir cual borrar -- hay que revisarlas a mano.

IF EXISTS (
	SELECT 1 FROM dbo.cuentas_por_pagar_otros
	WHERE [id_movimiento] IS NOT NULL
	GROUP BY [id_movimiento] HAVING COUNT(*) > 1
)
	THROW 50000, 'Hay partidas de cuentas_por_pagar_otros repetidas sobre el mismo id_movimiento: revisarlas a mano antes de aplicar la migracion 0090.', 1;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_cxp_otros_id_movimiento' AND object_id = OBJECT_ID('dbo.cuentas_por_pagar_otros'))
BEGIN
	CREATE UNIQUE INDEX UX_cxp_otros_id_movimiento ON dbo.cuentas_por_pagar_otros ([id_movimiento]) WHERE [id_movimiento] IS NOT NULL;
END
GO

IF OBJECT_ID(N'dbo.conciliaciones_partida', N'U') IS NULL
BEGIN
CREATE TABLE dbo.conciliaciones_partida (
	[id_conciliacion] BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_conciliaciones_partida PRIMARY KEY,
	[id_partida] BIGINT NOT NULL CONSTRAINT FK_conciliaciones_partida_partida REFERENCES dbo.cuentas_por_pagar_otros([id_cuenta]),
	[id_cuenta_por_cobrar] BIGINT NOT NULL CONSTRAINT FK_conciliaciones_partida_cxc REFERENCES dbo.cuentas_por_cobrar([id_cuenta_por_cobrar]),
	[monto] DECIMAL(18,2) NOT NULL CONSTRAINT CK_conciliaciones_partida_monto CHECK ([monto] > 0),
	[fecha_conciliacion] DATETIME NOT NULL CONSTRAINT DF_conciliaciones_partida_fecha DEFAULT GETDATE(),
	[conciliado_por] BIGINT NULL CONSTRAINT FK_conciliaciones_partida_usuario REFERENCES dbo.usuarios([id_usuario])
);
CREATE INDEX IX_conciliaciones_partida_cxc ON dbo.conciliaciones_partida ([id_cuenta_por_cobrar]);
END
GO
