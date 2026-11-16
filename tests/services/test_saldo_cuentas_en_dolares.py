"""Una cuenta en dolares lleva solo saldo en dolares (migracion 0102).

Los cobros por Zelle o Binance son en dolares y entran a una cuenta en dolares. El dialogo calcula igual el
equivalente en bolivares (dolares x tasa) y lo guarda en el movimiento como REFERENCIA; pero el trigger de saldos lo
sumaba tambien al saldo en bolivares de la cuenta, asi que una cuenta en dolares terminaba con un saldo en Bs inventado
(cada cobro de $10 a tasa 40 le sumaba Bs 400). El saldo en Bs es solo de las cuentas en bolivares, y el de pesos,
de las cuentas en pesos.
"""

from decimal import Decimal

import pytest

from app.db.models import BancoMovimiento
from app.services.banco_movimientos import BancoMovimientoService
from app.services.cuentas_bancarias import CuentaBancariaService
from app.services.pagos import PagoService
from tests.factories import crear_cuenta_bancaria, crear_usuario_admin
from tests.services.test_pagos import _crear_cxc


def _refrescar(db_session, cuenta):
    db_session.expire_all()
    return db_session.get(type(cuenta), cuenta.id_cuenta)


def _saldos(cuenta):
    return cuenta.saldo_total_banco, cuenta.saldo_total_banco_bs, cuenta.saldo_total_banco_cop


def _abono(db_session, admin, cuenta, usd="100.00", local="4000.00", tasa="40.00", tipo="abono"):
    return BancoMovimientoService.crear(
        db_session,
        cuenta.id_cuenta,
        tipo,
        float(usd),
        id_usuario=admin.id_usuario,
        monto_bolivares=float(local),
        tasa_cambio=float(tasa),
    )


# -- El trigger de saldos -----------------------------------------------------------------------------------------


def test_un_abono_en_una_cuenta_en_dolares_suma_solo_dolares(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session, moneda="USD")

    _abono(db_session, admin, cuenta)  # $100 con su equivalente de referencia: Bs 4.000 a tasa 40

    assert _saldos(_refrescar(db_session, cuenta)) == (Decimal("100.00"), Decimal("0.00"), Decimal("0.00"))


def test_un_cargo_en_una_cuenta_en_dolares_resta_solo_dolares(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session, moneda="USD")
    _abono(db_session, admin, cuenta)

    _abono(db_session, admin, cuenta, usd="30.00", local="1200.00", tipo="cargo")

    assert _saldos(_refrescar(db_session, cuenta)) == (Decimal("70.00"), Decimal("0.00"), Decimal("0.00"))


def test_corregir_un_movimiento_de_una_cuenta_en_dolares_tampoco_toca_el_saldo_en_bs(db_session):
    """La rama de UPDATE del trigger revierte el valor viejo y aplica el nuevo: en dolares solo cuenta el monto en $."""
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session, moneda="USD")
    movimiento = _abono(db_session, admin, cuenta)

    db_session.query(BancoMovimiento).filter_by(id_movimiento=movimiento.id_movimiento).update(
        {"monto_movimiento": Decimal("60.00"), "monto_bolivares": Decimal("2400.00")}
    )
    db_session.commit()

    assert _saldos(_refrescar(db_session, cuenta)) == (Decimal("60.00"), Decimal("0.00"), Decimal("0.00"))


def test_el_movimiento_conserva_su_equivalente_en_bolivares_como_referencia(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session, moneda="USD")

    movimiento = _abono(db_session, admin, cuenta)

    db_session.refresh(movimiento)
    assert movimiento.monto_bolivares == Decimal("4000.00") and movimiento.tasa_cambio == Decimal("40.00")


def test_las_cuentas_en_bolivares_y_en_pesos_siguen_igual(db_session):
    admin = crear_usuario_admin(db_session)
    ves = crear_cuenta_bancaria(db_session, moneda="VES")
    cop = crear_cuenta_bancaria(db_session, moneda="COP")

    _abono(db_session, admin, ves, usd="10.00", local="400.00", tasa="40.00")
    _abono(db_session, admin, cop, usd="10.00", local="40000.00", tasa="4000.00")

    assert _saldos(_refrescar(db_session, ves)) == (Decimal("10.00"), Decimal("400.00"), Decimal("0.00"))
    assert _saldos(_refrescar(db_session, cop)) == (Decimal("10.00"), Decimal("0.00"), Decimal("40000.00"))


# -- Los cobros reales por Zelle y Binance ----------------------------------------------------------------------


@pytest.mark.parametrize("metodo", ["zelle", "binance"])
def test_un_cobro_en_dolares_con_tasa_deja_solo_dolares_en_la_cuenta(db_session, metodo):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    cuenta = crear_cuenta_bancaria(db_session, moneda="USD")

    PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("10.00"),
        metodo_pago=metodo,
        moneda="USD",
        monto_bolivares=Decimal("400.00"),
        tasa_cambio=Decimal("40.00"),
        id_cuenta_bancaria=cuenta.id_cuenta,
        id_usuario=admin.id_usuario,
    )

    assert _saldos(_refrescar(db_session, cuenta)) == (Decimal("10.00"), Decimal("0.00"), Decimal("0.00"))


# -- Cambiar la moneda de una cuenta ------------------------------------------------------------------------------


def test_pasar_una_cuenta_de_bolivares_a_dolares_deja_su_saldo_en_bs_en_cero(db_session):
    """Una cuenta en dolares no tiene saldo en Bs: lo que habia como "saldo local" no se vuelve un saldo en dolares."""
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session, moneda="VES")
    _abono(db_session, admin, cuenta, usd="10.00", local="400.00", tasa="40.00")

    CuentaBancariaService.actualizar(
        db_session, cuenta.id_cuenta, id_usuario=admin.id_usuario, moneda="USD", confirmar_cambio_moneda=True
    )

    assert _saldos(_refrescar(db_session, cuenta)) == (Decimal("10.00"), Decimal("0.00"), Decimal("0.00"))


def test_pasar_una_cuenta_de_pesos_a_dolares_deja_los_saldos_locales_en_cero(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session, moneda="COP")
    _abono(db_session, admin, cuenta, usd="10.00", local="40000.00", tasa="4000.00")

    CuentaBancariaService.actualizar(
        db_session, cuenta.id_cuenta, id_usuario=admin.id_usuario, moneda="USD", confirmar_cambio_moneda=True
    )

    cuenta = _refrescar(db_session, cuenta)
    assert cuenta.saldo_total_banco_bs == Decimal("0.00") and cuenta.saldo_total_banco_cop == Decimal("0.00")
    assert cuenta.saldo_total_banco == Decimal("10.00")  # el equivalente en dolares no se pierde


def test_pasar_una_cuenta_de_dolares_a_bolivares_no_inventa_un_saldo_en_bs(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session, moneda="USD")
    _abono(db_session, admin, cuenta)

    CuentaBancariaService.actualizar(
        db_session, cuenta.id_cuenta, id_usuario=admin.id_usuario, moneda="VES", confirmar_cambio_moneda=True
    )

    assert _saldos(_refrescar(db_session, cuenta)) == (Decimal("100.00"), Decimal("0.00"), Decimal("0.00"))
