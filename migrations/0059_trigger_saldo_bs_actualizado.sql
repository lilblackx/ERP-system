-- Eliminar el trigger existente trg_banco_movimientos_saldo
IF EXISTS (SELECT 1 FROM sys.triggers WHERE name = 'trg_banco_movimientos_saldo' AND parent_class_desc = 'OBJECT_OR_COLUMN')
BEGIN
    DECLARE @sql NVARCHAR(MAX)
    SET @sql = 'DROP TRIGGER dbo.trg_banco_movimientos_saldo'
    EXEC sp_executesql @sql
END
GO

-- Crear el trigger actualizado trg_banco_movimientos_saldo que maneja saldo_total_banco y saldo_total_banco_bs
-- Este trigger actualiza tanto el saldo en USD como el saldo en BS cuando se insertan o actualizan movimientos bancarios
-- Para saldo_total_banco_bs, trabaja directamente con los montos en BS, sin conversiones desde USD

CREATE TRIGGER trg_banco_movimientos_saldo ON dbo.banco_movimientos
AFTER INSERT, UPDATE AS
BEGIN
	SET NOCOUNT ON;

	-- Actualizar saldo en USD para INSERTs
	IF EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted)
	BEGIN
		UPDATE cb
		SET cb.saldo_total_banco = cb.saldo_total_banco + agg.delta_usd
		FROM dbo.cuentas_bancarias cb
		JOIN (
			SELECT id_cuenta,
			       SUM(CASE WHEN tipo_movimiento IN ('abono','deposito')
			                THEN monto_movimiento
			                ELSE -monto_movimiento END) AS delta_usd
			FROM inserted
			GROUP BY id_cuenta
		) agg ON agg.id_cuenta = cb.id_cuenta;

		-- Actualizar saldo en BS directamente (solo si el movimiento tiene monto_bolivares)
		UPDATE cb
		SET cb.saldo_total_banco_bs = cb.saldo_total_banco_bs + agg.delta_bs
		FROM dbo.cuentas_bancarias cb
		JOIN (
			SELECT id_cuenta,
			       SUM(CASE WHEN tipo_movimiento IN ('abono','deposito')
			                THEN monto_bolivares
			                ELSE -monto_bolivares END) AS delta_bs
			FROM inserted
			WHERE monto_bolivares IS NOT NULL
			GROUP BY id_cuenta
		) agg ON agg.id_cuenta = cb.id_cuenta;
	END

	-- Manejar UPDATEs (revertir valor antiguo y aplicar nuevo valor)
	IF EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted)
	BEGIN
		-- Revertir el efecto del movimiento antiguo
		UPDATE cb
		SET cb.saldo_total_banco = cb.saldo_total_banco - agg.delta_usd_old
		FROM dbo.cuentas_bancarias cb
		JOIN (
			SELECT id_cuenta,
			       SUM(CASE WHEN tipo_movimiento IN ('abono','deposito')
			                THEN monto_movimiento
			                ELSE -monto_movimiento END) AS delta_usd_old
			FROM deleted
			GROUP BY id_cuenta
		) agg ON agg.id_cuenta = cb.id_cuenta;

		UPDATE cb
		SET cb.saldo_total_banco_bs = cb.saldo_total_banco_bs - agg.delta_bs_old
		FROM dbo.cuentas_bancarias cb
		JOIN (
			SELECT id_cuenta,
			       SUM(CASE WHEN tipo_movimiento IN ('abono','deposito')
			                THEN monto_bolivares
			                ELSE -monto_bolivares END) AS delta_bs_old
			FROM deleted
			WHERE monto_bolivares IS NOT NULL
			GROUP BY id_cuenta
		) agg ON agg.id_cuenta = cb.id_cuenta;

		-- Aplicar el efecto del movimiento nuevo
		UPDATE cb
		SET cb.saldo_total_banco = cb.saldo_total_banco + agg.delta_usd_new
		FROM dbo.cuentas_bancarias cb
		JOIN (
			SELECT id_cuenta,
			       SUM(CASE WHEN tipo_movimiento IN ('abono','deposito')
			                THEN monto_movimiento
			                ELSE -monto_movimiento END) AS delta_usd_new
			FROM inserted
			GROUP BY id_cuenta
		) agg ON agg.id_cuenta = cb.id_cuenta;

		UPDATE cb
		SET cb.saldo_total_banco_bs = cb.saldo_total_banco_bs + agg.delta_bs_new
		FROM dbo.cuentas_bancarias cb
		JOIN (
			SELECT id_cuenta,
			       SUM(CASE WHEN tipo_movimiento IN ('abono','deposito')
			                THEN monto_bolivares
			                ELSE -monto_bolivares END) AS delta_bs_new
			FROM inserted
			WHERE monto_bolivares IS NOT NULL
			GROUP BY id_cuenta
		) agg ON agg.id_cuenta = cb.id_cuenta;
	END
END