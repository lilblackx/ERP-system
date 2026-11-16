-- El saldo en bolivares es solo de las cuentas en bolivares (VES).
--
-- Una cuenta en dolares lleva saldo en dolares. Los cobros y pagos por Zelle y Binance son en dolares, pero el dialogo
-- calcula igual su equivalente en bolivares (dolares x tasa) y lo guarda en el movimiento
-- (banco_movimientos.monto_bolivares) como referencia. El trigger de saldos (0098) sumaba ese monto al saldo en
-- bolivares de TODA cuenta que no fuera en pesos, asi que una cuenta en dolares acumulaba un saldo en Bs inventado (un
-- cobro de $10 a tasa 40 le sumaba Bs 400).
--
--   * Trigger: el monto "local" va a saldo_total_banco_bs solo si la cuenta es 'VES' (y a saldo_total_banco_cop si es
--     'COP', como hasta ahora). Una cuenta 'USD' no lleva saldo local; el movimiento conserva su equivalente en bolivares
--     como referencia y saldo_total_banco (dolares) lo suma toda cuenta, sin cambios.
--   * Datos: el saldo en Bs de las cuentas en dolares se deja en cero. El formulario de la cuenta nunca permitio cargarles
--     uno (solo muestra el saldo de la moneda de la cuenta), asi que todo lo que tengan viene de esos equivalentes. Cada
--     cambio queda en auditoria_cambios_db (ver 0092) con el valor anterior, por si hace falta restaurarlo.

UPDATE dbo.cuentas_bancarias
SET saldo_total_banco_bs = 0.00
WHERE moneda = 'USD' AND saldo_total_banco_bs <> 0.00;
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

		-- monto "local" en bolivares (solo cuentas VES: una cuenta USD no lleva saldo en Bs)
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
		WHERE cb.moneda = 'VES';

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
		WHERE cb.moneda = 'VES';

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
		WHERE cb.moneda = 'VES';

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
