-- La migracion 0096 dejo todas las cuentas bancarias en 'VES'. Las que ya reciben dolares (Zelle, Binance) o pesos
-- tienen historial y, sin esto, quedarian sin poder usarse para esos pagos. Aqui se deduce la moneda de cada cuenta
-- a partir de los pagos que ya recibio/emitio:
--
--   * cada pago aporta una moneda: 'COP' si se registro en pesos, 'USD' si fue por Zelle o Binance, 'VES' si no;
--   * si TODOS los pagos de la cuenta aportan la misma moneda, la cuenta queda en esa moneda;
--   * si hay pagos mezclados (p. ej. Zelle y transferencia en la misma cuenta) NO se adivina: la cuenta se queda en
--     'VES' y se deja un aviso 'MONEDA_CUENTA_REVISAR' en la auditoria para que un administrador decida (el
--     formulario de la cuenta permite cambiarla con confirmacion aunque tenga movimientos);
--   * una cuenta sin pagos queda como esta.
--
-- Cada cuenta que cambia deja un 'MONEDA_CUENTA_DEDUCIDA' en la auditoria.

DECLARE @uso TABLE (id_cuenta BIGINT NOT NULL, moneda_pago VARCHAR(3) NOT NULL);

INSERT INTO @uso (id_cuenta, moneda_pago)
SELECT id_cuenta_bancaria,
       CASE WHEN moneda = 'COP' THEN 'COP' WHEN metodo_pago IN ('zelle', 'binance') THEN 'USD' ELSE 'VES' END
FROM dbo.pagos_cobros WHERE id_cuenta_bancaria IS NOT NULL;

INSERT INTO @uso (id_cuenta, moneda_pago)
SELECT id_cuenta_bancaria,
       CASE WHEN moneda = 'COP' THEN 'COP' WHEN metodo_pago IN ('zelle', 'binance') THEN 'USD' ELSE 'VES' END
FROM dbo.pagos_cobros_bcv WHERE id_cuenta_bancaria IS NOT NULL;

INSERT INTO @uso (id_cuenta, moneda_pago)
SELECT id_cuenta_bancaria, CASE WHEN metodo_pago IN ('zelle', 'binance') THEN 'USD' ELSE 'VES' END
FROM dbo.pagos_proveedores WHERE id_cuenta_bancaria IS NOT NULL;

INSERT INTO @uso (id_cuenta, moneda_pago)
SELECT id_cuenta_bancaria, CASE WHEN metodo_pago IN ('zelle', 'binance') THEN 'USD' ELSE 'VES' END
FROM dbo.pagos_comisiones WHERE id_cuenta_bancaria IS NOT NULL;

DECLARE @resumen TABLE (id_cuenta BIGINT NOT NULL, monedas INT NOT NULL, moneda VARCHAR(3) NOT NULL, pagos INT NOT NULL);

INSERT INTO @resumen (id_cuenta, monedas, moneda, pagos)
SELECT id_cuenta, COUNT(DISTINCT moneda_pago), MIN(moneda_pago), COUNT(*)
FROM @uso
GROUP BY id_cuenta;

-- Avisos primero (comparan contra la moneda actual, antes del UPDATE).
INSERT INTO dbo.auditoria (id_usuario, accion, modulo, detalle)
SELECT NULL, 'MONEDA_CUENTA_DEDUCIDA', 'CUENTAS_BANCARIAS',
       CONCAT('Cuenta ', r.id_cuenta, ' (...', RIGHT(ISNULL(c.numero_cuenta, ''), 4), '): moneda ', c.moneda,
              ' -> ', r.moneda, ' segun ', r.pagos, ' pago(s) del historial (migracion 0097)')
FROM @resumen r
JOIN dbo.cuentas_bancarias c ON c.id_cuenta = r.id_cuenta
WHERE r.monedas = 1 AND c.moneda <> r.moneda;

INSERT INTO dbo.auditoria (id_usuario, accion, modulo, detalle)
SELECT NULL, 'MONEDA_CUENTA_REVISAR', 'CUENTAS_BANCARIAS',
       CONCAT('Cuenta ', r.id_cuenta, ' (...', RIGHT(ISNULL(c.numero_cuenta, ''), 4),
              '): tiene pagos en ', r.monedas, ' monedas distintas (', r.pagos,
              ' pagos en total); se dejo en ', c.moneda, '. Un administrador debe confirmar su moneda (migracion 0097)')
FROM @resumen r
JOIN dbo.cuentas_bancarias c ON c.id_cuenta = r.id_cuenta
WHERE r.monedas > 1;

UPDATE c
SET c.moneda = r.moneda
FROM dbo.cuentas_bancarias c
JOIN @resumen r ON r.id_cuenta = c.id_cuenta
WHERE r.monedas = 1 AND c.moneda <> r.moneda;
GO
