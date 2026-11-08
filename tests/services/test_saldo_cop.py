"""Saldo en pesos (COP) de las cuentas COP, igual que el saldo en bolivares y en dolares (migracion 0098).

El monto "local" de cada movimiento (banco_movimientos.monto_bolivares) va al saldo en pesos si la cuenta es COP y al
saldo en bolivares si no; el equivalente en dolares (saldo_total_banco) lo suma cualquier cuenta."""

from decimal import Decimal

import pytest

from app.services.banco_movimientos import BancoMovimientoService
from app.services.cuentas_bancarias import CuentaBancariaService
from app.services.pagos import PagoService
from tests.factories import crear_banco, crear_cuenta_bancaria, crear_usuario_admin
from tests.services.test_pagos import _crear_cxc


def _refrescar(db_session, cuenta):
    db_session.expire_all()
    return db_session.get(type(cuenta), cuenta.id_cuenta)


def test_un_abono_en_una_cuenta_cop_suma_al_saldo_en_pesos_y_no_al_de_bolivares(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session, moneda="COP")

    BancoMovimientoService.crear(
        db_session,
        cuenta.id_cuenta,
        "abono",
        10.00,
        id_usuario=admin.id_usuario,
        monto_bolivares=40000.00,
        tasa_cambio=4000.00,
    )

    cuenta = _refrescar(db_session, cuenta)
    assert cuenta.saldo_total_banco_cop == Decimal("40000.00")
    assert cuenta.saldo_total_banco_bs == Decimal("0.00")
    assert cuenta.saldo_total_banco == Decimal("10.00")  # el equivalente en dolares lo lleva toda cuenta


def test_un_abono_en_una_cuenta_en_bolivares_sigue_sumando_al_saldo_en_bs(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session, moneda="VES")

    BancoMovimientoService.crear(
        db_session,
        cuenta.id_cuenta,
        "abono",
        10.00,
        id_usuario=admin.id_usuario,
        monto_bolivares=400.00,
        tasa_cambio=40.00,
    )

    cuenta = _refrescar(db_session, cuenta)
    assert cuenta.saldo_total_banco_bs == Decimal("400.00")
    assert cuenta.saldo_total_banco_cop == Decimal("0.00")


def test_un_cargo_resta_del_saldo_en_pesos(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session, moneda="COP")
    BancoMovimientoService.crear(
        db_session,
        cuenta.id_cuenta,
        "abono",
        10.00,
        id_usuario=admin.id_usuario,
        monto_bolivares=40000.00,
        tasa_cambio=4000.00,
    )

    BancoMovimientoService.crear(
        db_session,
        cuenta.id_cuenta,
        "cargo",
        3.00,
        id_usuario=admin.id_usuario,
        monto_bolivares=12000.00,
        tasa_cambio=4000.00,
    )

    cuenta = _refrescar(db_session, cuenta)
    assert cuenta.saldo_total_banco_cop == Decimal("28000.00")
    assert cuenta.saldo_total_banco == Decimal("7.00")


def test_un_movimiento_sin_monto_local_no_toca_los_saldos_locales(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session, moneda="COP")

    BancoMovimientoService.crear(db_session, cuenta.id_cuenta, "abono", 10.00, id_usuario=admin.id_usuario)

    cuenta = _refrescar(db_session, cuenta)
    assert cuenta.saldo_total_banco_cop == Decimal("0.00") and cuenta.saldo_total_banco_bs == Decimal("0.00")
    assert cuenta.saldo_total_banco == Decimal("10.00")


def test_un_cobro_en_pesos_deja_los_pesos_en_el_saldo_de_la_cuenta_cop(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    cuenta = crear_cuenta_bancaria(db_session, moneda="COP")

    PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("10.00"),
        metodo_pago="transferencia",
        moneda="COP",
        monto_moneda_origen=Decimal("40000.00"),  # sin monto_bolivares: el servicio usa los pesos como monto local
        id_cuenta_bancaria=cuenta.id_cuenta,
        tasa_cambio=Decimal("4000.00"),
        id_usuario=admin.id_usuario,
    )

    cuenta = _refrescar(db_session, cuenta)
    assert cuenta.saldo_total_banco_cop == Decimal("40000.00")
    assert cuenta.saldo_total_banco_bs == Decimal("0.00")


def test_se_puede_crear_una_cuenta_cop_con_saldo_inicial_en_pesos(db_session):
    admin = crear_usuario_admin(db_session)
    banco = crear_banco(db_session)

    cuenta = CuentaBancariaService.crear(
        db_session,
        id_banco=banco.id_banco,
        numero_cuenta="999000111",
        tipo_cuenta_banco="AHORRO",
        nombre_titular="DJ",
        identificacion_titular="J-1",
        moneda="COP",
        saldo_total_banco_cop=Decimal("2500000.00"),
        creado_por=admin.id_usuario,
    )

    assert cuenta.moneda == "COP" and cuenta.saldo_total_banco_cop == Decimal("2500000.00")


def test_el_saldo_en_pesos_no_se_edita_a_mano(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session, moneda="COP")

    with pytest.raises(ValueError, match="saldo"):
        CuentaBancariaService.actualizar(
            db_session, cuenta.id_cuenta, id_usuario=admin.id_usuario, saldo_total_banco_cop=Decimal("5")
        )


def test_pasar_una_cuenta_de_bolivares_a_pesos_mueve_su_saldo_local(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session, moneda="VES")
    BancoMovimientoService.crear(
        db_session,
        cuenta.id_cuenta,
        "abono",
        10.00,
        id_usuario=admin.id_usuario,
        monto_bolivares=400.00,
        tasa_cambio=40.00,
    )

    CuentaBancariaService.actualizar(
        db_session, cuenta.id_cuenta, id_usuario=admin.id_usuario, moneda="COP", confirmar_cambio_moneda=True
    )

    cuenta = _refrescar(db_session, cuenta)
    assert cuenta.moneda == "COP"
    assert cuenta.saldo_total_banco_cop == Decimal("400.00") and cuenta.saldo_total_banco_bs == Decimal("0.00")


def test_pasar_una_cuenta_de_pesos_a_bolivares_devuelve_su_saldo_local(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session, moneda="COP")
    BancoMovimientoService.crear(
        db_session,
        cuenta.id_cuenta,
        "abono",
        10.00,
        id_usuario=admin.id_usuario,
        monto_bolivares=40000.00,
        tasa_cambio=4000.00,
    )

    CuentaBancariaService.actualizar(
        db_session, cuenta.id_cuenta, id_usuario=admin.id_usuario, moneda="VES", confirmar_cambio_moneda=True
    )

    cuenta = _refrescar(db_session, cuenta)
    assert cuenta.saldo_total_banco_bs == Decimal("40000.00") and cuenta.saldo_total_banco_cop == Decimal("0.00")


def test_pasar_de_dolares_a_pesos_no_mueve_el_saldo_en_bolivares_de_otra_cuenta(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session, moneda="USD")

    CuentaBancariaService.actualizar(db_session, cuenta.id_cuenta, id_usuario=admin.id_usuario, moneda="COP")

    cuenta = _refrescar(db_session, cuenta)
    assert cuenta.moneda == "COP" and cuenta.saldo_total_banco_cop == Decimal("0.00")


def test_el_servicio_de_movimientos_suma_los_pesos_como_monto_local(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session, moneda="COP")
    BancoMovimientoService.crear(
        db_session,
        cuenta.id_cuenta,
        "abono",
        10.00,
        id_usuario=admin.id_usuario,
        monto_bolivares=40000.00,
        tasa_cambio=4000.00,
    )
    BancoMovimientoService.crear(
        db_session, cuenta.id_cuenta, "cargo", 2.00, id_usuario=admin.id_usuario, tasa_cambio=4000.00
    )

    totales = BancoMovimientoService.listar_paginado(db_session, cuenta.id_cuenta, id_usuario=admin.id_usuario)[
        "totales"
    ]

    assert totales["entradas_bs"] == 40000.0 and totales["salidas_bs"] == 8000.0  # el cargo sin monto local: 2 x 4000
