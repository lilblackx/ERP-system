-- Poblar saldo_total_banco_bs basándose en movimientos bancarios existentes
-- Esta migración calcula el saldo en BS sumando los movimientos bancarios que tienen monto_bolivares

UPDATE cb
SET cb.saldo_total_banco_bs = ISNULL((
    SELECT SUM(CASE WHEN bm.tipo_movimiento IN ('abono','deposito')
                   THEN ISNULL(bm.monto_bolivares, 0)
                   ELSE -ISNULL(bm.monto_bolivares, 0) END)
    FROM dbo.banco_movimientos bm
    WHERE bm.id_cuenta = cb.id_cuenta
    AND bm.monto_bolivares IS NOT NULL
), 0.00)
FROM dbo.cuentas_bancarias cb
