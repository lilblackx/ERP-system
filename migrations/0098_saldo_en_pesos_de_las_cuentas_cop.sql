-- Saldo en pesos colombianos (COP) para las cuentas en COP, igual que ya hay saldo en bolivares y en dolares.
--
-- Como los movimientos ya guardan el monto "en la moneda local del pago" en banco_movimientos.monto_bolivares (con la
-- tasa COP el dialogo de cobro lo llena con pesos), no hace falta una columna nueva en cada tabla de pagos: solo un
-- saldo propio y que el trigger de saldos lo lleve segun la moneda de la cuenta:
--
--   * cuenta 'VES' o 'USD': la parte "local" va a cuentas_bancarias.saldo_total_banco_bs (como hasta ahora);
--   * cuenta 'COP': va a cuentas_bancarias.saldo_total_banco_cop (antes mezclaba pesos con bolivares).
--
-- saldo_total_banco (USD) sigue sumando el equivalente en dolares de todos los movimientos de cualquier cuenta.

IF NOT EXISTS (
    SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.cuentas_bancarias') AND name = 'saldo_total_banco_cop'
)
BEGIN
    ALTER TABLE dbo.cuentas_bancarias ADD [saldo_total_banco_cop] DECIMAL(20,2) NOT NULL DEFAULT 0.00;
END
GO

-- Las cuentas que ya estan en COP (0097 las deduce del historial) acumulaban sus pesos en saldo_total_banco_bs: se pasan
-- a su saldo propio.
EXEC sp_executesql N'
UPDATE dbo.cuentas_bancarias
SET saldo_total_banco_cop = saldo_total_banco_bs,
    saldo_total_banco_bs = 0.00
WHERE moneda = ''COP'' AND saldo_total_banco_bs <> 0.00 AND saldo_total_banco_cop = 0.00;';
GO

IF EXISTS (SELECT 1 FROM sys.triggers WHERE name = 'trg_banco_movimientos_saldo' AND parent_class_desc = 'OBJECT_OR_COLUMN')
BEGIN
    DROP TRIGGER dbo.trg_banco_movimientos_saldo;
END
GO

CREATE TRIGGER trg_banco_movimientos_saldo ON dbo.banco_movimientos
AFTER INSERT, UPDATE AS
BEGIN
	SET NOCOUNT ON;

	-- INSERT: saldo en USD (equivalente) de la cuenta, sin importar su moneda
	IF EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted)
	BEGIN
		UPDATE cb
		SET cb.saldo_total_banco = cb.saldo_total_banco + agg.delta_usd
		FROM dbo.cuentas_bancarias cb
		JOIN (
			SELECT id_cuenta,
			       SUM(CASE WHEN tipo_movimiento IN ('abono','deposito') THEN monto_movimiento ELSE -monto_movimiento END) AS delta_usd
			FROM inserted
			GROUP BY id_cuenta
		) agg ON agg.id_cuenta = cb.id_cuenta;

		-- monto "local" en bolivares (cuentas VES/USD)
		UPDATE cb
		SET cb.saldo_total_banco_bs = cb.saldo_total_banco_bs + agg.delta_local
		FROM dbo.cuentas_bancarias cb
		JOIN (
			SELECT id_cuenta,
			       SUM(CASE WHEN tipo_movimiento IN ('abono','deposito') THEN monto_bolivares ELSE -monto_bolivares END) AS delta_local
			FROM inserted
			WHERE monto_bolivares IS NOT NULL
			GROUP BY id_cuenta
		) agg ON agg.id_cuenta = cb.id_cuenta
		WHERE cb.moneda <> 'COP';

		-- monto "local" en pesos (cuentas COP)
		UPDATE cb
		SET cb.saldo_total_banco_cop = cb.saldo_total_banco_cop + agg.delta_local
		FROM dbo.cuentas_bancarias cb
		JOIN (
			SELECT id_cuenta,
			       SUM(CASE WHEN tipo_movimiento IN ('abono','deposito') THEN monto_bolivares ELSE -monto_bolivares END) AS delta_local
			FROM inserted
			WHERE monto_bolivares IS NOT NULL
			GROUP BY id_cuenta
		) agg ON agg.id_cuenta = cb.id_cuenta
		WHERE cb.moneda = 'COP';
	END

	-- UPDATE: revertir el valor antiguo y aplicar el nuevo
	IF EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted)
	BEGIN
		UPDATE cb
		SET cb.saldo_total_banco = cb.saldo_total_banco - agg.delta_usd_old
		FROM dbo.cuentas_bancarias cb
		JOIN (
			SELECT id_cuenta,
			       SUM(CASE WHEN tipo_movimiento IN ('abono','deposito') THEN monto_movimiento ELSE -monto_movimiento END) AS delta_usd_old
			FROM deleted
			GROUP BY id_cuenta
		) agg ON agg.id_cuenta = cb.id_cuenta;

		UPDATE cb
		SET cb.saldo_total_banco_bs = cb.saldo_total_banco_bs - agg.delta_local_old
		FROM dbo.cuentas_bancarias cb
		JOIN (
			SELECT id_cuenta,
			       SUM(CASE WHEN tipo_movimiento IN ('abono','deposito') THEN monto_bolivares ELSE -monto_bolivares END) AS delta_local_old
			FROM deleted
			WHERE monto_bolivares IS NOT NULL
			GROUP BY id_cuenta
		) agg ON agg.id_cuenta = cb.id_cuenta
		WHERE cb.moneda <> 'COP';

		UPDATE cb
		SET cb.saldo_total_banco_cop = cb.saldo_total_banco_cop - agg.delta_local_old
		FROM dbo.cuentas_bancarias cb
		JOIN (
			SELECT id_cuenta,
			       SUM(CASE WHEN tipo_movimiento IN ('abono','deposito') THEN monto_bolivares ELSE -monto_bolivares END) AS delta_local_old
			FROM deleted
			WHERE monto_bolivares IS NOT NULL
			GROUP BY id_cuenta
		) agg ON agg.id_cuenta = cb.id_cuenta
		WHERE cb.moneda = 'COP';

		UPDATE cb
		SET cb.saldo_total_banco = cb.saldo_total_banco + agg.delta_usd_new
		FROM dbo.cuentas_bancarias cb
		JOIN (
			SELECT id_cuenta,
			       SUM(CASE WHEN tipo_movimiento IN ('abono','deposito') THEN monto_movimiento ELSE -monto_movimiento END) AS delta_usd_new
			FROM inserted
			GROUP BY id_cuenta
		) agg ON agg.id_cuenta = cb.id_cuenta;

		UPDATE cb
		SET cb.saldo_total_banco_bs = cb.saldo_total_banco_bs + agg.delta_local_new
		FROM dbo.cuentas_bancarias cb
		JOIN (
			SELECT id_cuenta,
			       SUM(CASE WHEN tipo_movimiento IN ('abono','deposito') THEN monto_bolivares ELSE -monto_bolivares END) AS delta_local_new
			FROM inserted
			WHERE monto_bolivares IS NOT NULL
			GROUP BY id_cuenta
		) agg ON agg.id_cuenta = cb.id_cuenta
		WHERE cb.moneda <> 'COP';

		UPDATE cb
		SET cb.saldo_total_banco_cop = cb.saldo_total_banco_cop + agg.delta_local_new
		FROM dbo.cuentas_bancarias cb
		JOIN (
			SELECT id_cuenta,
			       SUM(CASE WHEN tipo_movimiento IN ('abono','deposito') THEN monto_bolivares ELSE -monto_bolivares END) AS delta_local_new
			FROM inserted
			WHERE monto_bolivares IS NOT NULL
			GROUP BY id_cuenta
		) agg ON agg.id_cuenta = cb.id_cuenta
		WHERE cb.moneda = 'COP';
	END
END
GO
