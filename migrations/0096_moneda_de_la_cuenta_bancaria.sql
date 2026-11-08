-- Moneda de cada cuenta bancaria. Hasta ahora una cuenta no decia en que moneda opera: todas guardaban saldo en
-- $ y en Bs y los dialogos de cobro/pago listaban TODAS las cuentas para cualquier metodo, asi que un cobro por
-- Zelle ofrecia una cuenta en bolivares (y una transferencia, una cuenta en dolares).
--
--   'VES': cuenta en bolivares (transferencia, punto de venta, pago movil).
--   'USD': cuenta en dolares (Zelle, Binance).
--   'COP': cuenta en pesos colombianos (pagos en pesos, con la tasa COP).
--
-- Las cuentas existentes quedan en 'VES' (son cuentas de bancos venezolanos); las que reciben dolares se cambian a
-- 'USD' desde el formulario de la cuenta mientras no tengan movimientos, o se crean nuevas.

ALTER TABLE dbo.cuentas_bancarias
	ADD [moneda] VARCHAR(3) NOT NULL CONSTRAINT DF_cuentas_bancarias_moneda DEFAULT 'VES';
GO

ALTER TABLE dbo.cuentas_bancarias
	ADD CONSTRAINT CK_cuentas_bancarias_moneda CHECK ([moneda] IN ('VES', 'USD', 'COP'));
GO
