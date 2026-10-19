-- C18 (docs/CHECKLIST_PRODUCCION.md): segunda barrera contra saldo negativo en las 4
-- tablas de cuentas con saldo_pendiente que no la tenian. El fix real es el
-- WITH (UPDLOCK, ROWLOCK) agregado en OtrosMovimientosService.registrar_abono_otro()/
-- conciliar_partida() (app/services/otros_movimientos.py, mismo patron que C1 en
-- ventas.py), que serializa la validacion+actualizacion contra abonos/conciliaciones
-- concurrentes sobre la misma cuenta. Este CHECK es defensa en profundidad, igual que
-- migrations/0006_check_stock_no_negativo.sql para inventario.cantidad_unidad.

ALTER TABLE dbo.cuentas_por_cobrar ADD CONSTRAINT CK_cuentas_por_cobrar_saldo_no_negativo CHECK ([saldo_pendiente] >= 0);
GO

ALTER TABLE dbo.cuentas_por_pagar ADD CONSTRAINT CK_cuentas_por_pagar_saldo_no_negativo CHECK ([saldo_pendiente] >= 0);
GO

ALTER TABLE dbo.cuentas_por_cobrar_otros ADD CONSTRAINT CK_cuentas_por_cobrar_otros_saldo_no_negativo CHECK ([saldo_pendiente] >= 0);
GO

ALTER TABLE dbo.cuentas_por_pagar_otros ADD CONSTRAINT CK_cuentas_por_pagar_otros_saldo_no_negativo CHECK ([saldo_pendiente] >= 0);
GO
