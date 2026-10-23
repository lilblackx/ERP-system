"""Otros movimientos: cada peso respaldado por un movimiento real (migrations/0090).

Prestamos que registran la salida de dinero, transferencias sin identificar ligadas a UN
movimiento bancario real, y conciliaciones que quedan en el historial del cliente."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.db.models import BancoMovimiento, CajaMovimiento, ConciliacionPartida, CuentaPorCobrarOtro
from app.services.historial_cliente import obtener_historial_cliente
from app.services.otros_movimientos import OtrosMovimientosService
from app.services.pagos import PagoService
from app.services.tesoreria import CajaService
from tests.factories import crear_caja, crear_cliente, crear_cuenta_bancaria, crear_usuario_admin
from tests.services.test_otros_movimientos import _caja_con_saldo, _crear_cxc_real, _crear_partida


def _prestamo(db_session, admin, cliente, monto="100.00", **origen):
    return OtrosMovimientosService.crear_cuenta_cobrar_otro(
        db_session,
        id_cliente=cliente.id_cliente,
        monto_total=Decimal(monto),
        descripcion="Anticipo",
        fecha_vencimiento=None,
        creado_por=admin.id_usuario,
        **origen,
    )


# ── Prestamos / anticipos: la salida de dinero queda registrada ─────────────────


def test_prestamo_por_caja_registra_la_salida_de_dinero(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session)
    caja = _caja_con_saldo(db_session, admin, Decimal("500.00"))

    _prestamo(db_session, admin, cliente, "120.00", id_caja=caja.id_caja)

    assert CajaService.calcular_saldo_actual(db_session, caja.id_caja) == Decimal("380.00")
    salida = db_session.query(CajaMovimiento).filter_by(id_caja=caja.id_caja, tipo_movimiento="salida").one()
    assert "Prestamo (otros)" in salida.descripcion_movimiento


def test_prestamo_por_banco_registra_el_cargo_y_baja_el_saldo(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session)
    banco = crear_cuenta_bancaria(db_session, saldo_total_banco=Decimal("300.00"))

    _prestamo(db_session, admin, cliente, "100.00", id_cuenta_bancaria=banco.id_cuenta, referencia="TRF-0001")

    db_session.refresh(banco)
    assert banco.saldo_total_banco == Decimal("200.00")
    cargo = db_session.query(BancoMovimiento).filter_by(id_cuenta=banco.id_cuenta, tipo_movimiento="cargo").one()
    assert cargo.referencia_movimiento == "TRF-0001"


def test_prestamo_exige_un_origen_del_dinero(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="exactamente un origen"):
        _prestamo(db_session, admin, cliente)


def test_prestamo_sin_saldo_en_la_caja_falla_y_no_crea_la_deuda(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session)
    caja = _caja_con_saldo(db_session, admin, Decimal("50.00"))

    with pytest.raises(ValueError, match="saldo suficiente"):
        _prestamo(db_session, admin, cliente, "100.00", id_caja=caja.id_caja)
    assert db_session.query(CuentaPorCobrarOtro).count() == 0


def test_prestamo_sin_saldo_en_el_banco_falla(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session)
    banco = crear_cuenta_bancaria(db_session, saldo_total_banco=Decimal("10.00"))

    with pytest.raises(ValueError, match="saldo suficiente"):
        _prestamo(db_session, admin, cliente, "100.00", id_cuenta_bancaria=banco.id_cuenta, referencia="TRF-0002")


def test_prestamo_desde_caja_sin_turno_abierto_falla(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="turno abierto"):
        _prestamo(db_session, admin, cliente, "10.00", id_caja=crear_caja(db_session).id_caja)


def test_prestamo_bancario_sin_referencia_falla(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session)
    banco = crear_cuenta_bancaria(db_session, saldo_total_banco=Decimal("300.00"))

    with pytest.raises(ValueError, match="referencia"):
        _prestamo(db_session, admin, cliente, "100.00", id_cuenta_bancaria=banco.id_cuenta)


# ── Transferencias sin identificar: ligadas a UN movimiento real ───────────────


def test_partida_sin_movimiento_bancario_se_rechaza(db_session):
    admin = crear_usuario_admin(db_session)
    banco = crear_cuenta_bancaria(db_session)

    with pytest.raises(ValueError, match="id_movimiento"):
        OtrosMovimientosService.crear_partida_no_conciliada(
            db_session, id_cuenta_bancaria=banco.id_cuenta, monto=Decimal("100.00"), creado_por=admin.id_usuario
        )


def test_un_movimiento_bancario_solo_origina_una_partida(db_session):
    admin = crear_usuario_admin(db_session)
    banco = crear_cuenta_bancaria(db_session)
    primera = _crear_partida(db_session, banco, admin, Decimal("100.00"))

    with pytest.raises(ValueError, match="ya tiene una transferencia sin identificar"):
        OtrosMovimientosService.crear_partida_no_conciliada(
            db_session,
            id_cuenta_bancaria=banco.id_cuenta,
            monto=Decimal("50.00"),
            id_movimiento=primera.id_movimiento,
            creado_por=admin.id_usuario,
        )


def _movimiento(db_session, banco, tipo="abono", monto="100.00"):
    movimiento = BancoMovimiento(
        id_cuenta=banco.id_cuenta,
        tipo_movimiento=tipo,
        monto_movimiento=Decimal(monto),
        fecha_movimiento=datetime.now(),
    )
    db_session.add(movimiento)
    db_session.commit()
    return movimiento


def test_la_partida_no_puede_superar_el_monto_del_movimiento(db_session):
    admin = crear_usuario_admin(db_session)
    banco = crear_cuenta_bancaria(db_session)
    movimiento = _movimiento(db_session, banco, monto="100.00")

    with pytest.raises(ValueError, match="excede el del movimiento"):
        OtrosMovimientosService.crear_partida_no_conciliada(
            db_session,
            id_cuenta_bancaria=banco.id_cuenta,
            monto=Decimal("500.00"),
            id_movimiento=movimiento.id_movimiento,
            creado_por=admin.id_usuario,
        )


def test_el_movimiento_debe_ser_un_abono_de_esa_cuenta(db_session):
    admin = crear_usuario_admin(db_session)
    banco = crear_cuenta_bancaria(db_session)
    otro_banco = crear_cuenta_bancaria(db_session)
    cargo = _movimiento(db_session, banco, tipo="cargo")
    ajeno = _movimiento(db_session, otro_banco)

    with pytest.raises(ValueError, match="abono"):
        OtrosMovimientosService.crear_partida_no_conciliada(
            db_session,
            id_cuenta_bancaria=banco.id_cuenta,
            monto=Decimal("10.00"),
            id_movimiento=cargo.id_movimiento,
            creado_por=admin.id_usuario,
        )
    with pytest.raises(ValueError, match="otra cuenta"):
        OtrosMovimientosService.crear_partida_no_conciliada(
            db_session,
            id_cuenta_bancaria=banco.id_cuenta,
            monto=Decimal("10.00"),
            id_movimiento=ajeno.id_movimiento,
            creado_por=admin.id_usuario,
        )


def test_un_movimiento_ya_atribuido_a_un_cobro_no_puede_quedar_sin_identificar(db_session):
    """Un abono que ya es el cobro de una factura no es una transferencia misteriosa: usarlo
    como partida contaria dos veces el mismo dinero."""
    cxc, _cliente, admin = _crear_cxc_real(db_session, Decimal("100.00"))
    banco = crear_cuenta_bancaria(db_session)
    PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("40.00"),
        metodo_pago="transferencia",
        id_cuenta_bancaria=banco.id_cuenta,
        referencia="REF-COBRO",
        id_usuario=admin.id_usuario,
    )
    movimiento = db_session.query(BancoMovimiento).filter_by(id_cuenta=banco.id_cuenta).one()

    with pytest.raises(ValueError, match="ya esta asociado a un pago"):
        OtrosMovimientosService.crear_partida_no_conciliada(
            db_session,
            id_cuenta_bancaria=banco.id_cuenta,
            monto=Decimal("40.00"),
            id_movimiento=movimiento.id_movimiento,
            creado_por=admin.id_usuario,
        )


# ── Conciliacion: solo contra facturas con saldo, y con constancia ──────────────


def test_conciliar_contra_una_factura_ya_pagada_falla(db_session):
    admin = crear_usuario_admin(db_session)
    banco = crear_cuenta_bancaria(db_session)
    partida = _crear_partida(db_session, banco, admin, Decimal("500.00"))
    cxc, cliente, _ = _crear_cxc_real(db_session, Decimal("100.00"))
    OtrosMovimientosService.conciliar_partida(
        db_session, partida.id_cuenta, cliente.id_cliente, cxc.id_cuenta_por_cobrar, Decimal("100.00"), admin.id_usuario
    )

    with pytest.raises(ValueError, match="no tiene saldo pendiente"):
        OtrosMovimientosService.conciliar_partida(
            db_session,
            partida.id_cuenta,
            cliente.id_cliente,
            cxc.id_cuenta_por_cobrar,
            Decimal("10.00"),
            admin.id_usuario,
        )


def test_conciliar_deja_constancia_y_aparece_como_abono_en_el_historial(db_session):
    admin = crear_usuario_admin(db_session)
    banco = crear_cuenta_bancaria(db_session)
    partida = _crear_partida(db_session, banco, admin, Decimal("100.00"))
    cxc, cliente, _ = _crear_cxc_real(db_session, Decimal("80.00"))

    OtrosMovimientosService.conciliar_partida(
        db_session, partida.id_cuenta, cliente.id_cliente, cxc.id_cuenta_por_cobrar, Decimal("30.00"), admin.id_usuario
    )

    registro = db_session.query(ConciliacionPartida).one()
    assert registro.monto == Decimal("30.00") and registro.conciliado_por == admin.id_usuario
    abonos = [h for h in obtener_historial_cliente(db_session, cliente.id_cliente) if h["tipo_transaccion"] == "pago"]
    assert [a["monto"] for a in abonos] == [Decimal("-30.00")]
    assert "conciliada" in abonos[0]["observaciones"]
