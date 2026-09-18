-- Recalcular saldo_total_banco_bs basándose en TODOS los movimientos bancarios existentes
-- Esto corrige el saldo BS para incluir movimientos que existían antes de la implementación del trigger

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
