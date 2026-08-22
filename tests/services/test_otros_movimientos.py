from decimal import Decimal

import pytest

from app.db.models import BancoMovimiento, CajaMovimiento, CuentaPorCobrar
from app.services.otros_movimientos import OtrosMovimientosService
from app.services.tesoreria import CajaService
from app.services.ventas import VentaService
from tests.factories import crear_caja, crear_cliente, crear_cuenta_bancaria, crear_producto


def _crear_cxc_otro(session, monto=Decimal("100.00"), **overrides):
    cliente = overrides.pop("cliente", None) or crear_cliente(session)
    return OtrosMovimientosService.crear_cuenta_cobrar_otro(
        session, id_cliente=cliente.id_cliente, monto_total=monto, descripcion=None, fecha_vencimiento=None, creado_por=None
    ), cliente


def _crear_cxc_real(session, saldo: Decimal):
    producto = crear_producto(session, cantidad_unidad=100)
    cliente = crear_cliente(session, limite_credito=saldo * 2)
    factura = VentaService.emitir_factura(
        session,
        id_cliente=cliente.id_cliente,
        id_usuario=None,
        id_vendedor=None,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": str(saldo)}],
    )
    cxc = session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()
    return cxc, cliente


# --- crear_cuenta_cobrar_otro ---------------------------------------------------


def test_crear_cuenta_cobrar_otro(db_session):
    cliente = crear_cliente(db_session)

    cuenta = OtrosMovimientosService.crear_cuenta_cobrar_otro(
        db_session, id_cliente=cliente.id_cliente, monto_total=Decimal("100.00"), descripcion="Prestamo", fecha_vencimiento=None, creado_por=None
    )

    assert cuenta.id_cuenta is not None
    assert cuenta.saldo_pendiente == Decimal("100.00")
    assert cuenta.estado == "pendiente"


def test_crear_cuenta_cobrar_otro_monto_invalido(db_session):
    cliente = crear_cliente(db_session)
    with pytest.raises(ValueError, match="monto_total debe ser mayor a cero"):
        OtrosMovimientosService.crear_cuenta_cobrar_otro(
            db_session, id_cliente=cliente.id_cliente, monto_total=Decimal("0.00"), descripcion=None, fecha_vencimiento=None, creado_por=None
        )


def test_crear_cuenta_cobrar_otro_cliente_inexistente(db_session):
    with pytest.raises(ValueError, match="Cliente no encontrado"):
        OtrosMovimientosService.crear_cuenta_cobrar_otro(
            db_session, id_cliente=999999, monto_total=Decimal("100.00"), descripcion=None, fecha_vencimiento=None, creado_por=None
        )


# --- registrar_abono_otro -------------------------------------------------------


def test_registrar_abono_sin_origen(db_session):
    cuenta, _ = _crear_cxc_otro(db_session)
    with pytest.raises(ValueError, match="exactamente un origen"):
        OtrosMovimientosService.registrar_abono_otro(db_session, cuenta.id_cuenta, monto=Decimal("10.00"))


def test_registrar_abono_dos_origenes(db_session):
    cuenta, _ = _crear_cxc_otro(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=None, saldo_apertura=0)
    banco = crear_cuenta_bancaria(db_session)

    with pytest.raises(ValueError, match="exactamente un origen"):
        OtrosMovimientosService.registrar_abono_otro(
            db_session, cuenta.id_cuenta, monto=Decimal("10.00"), id_caja=caja.id_caja, id_cuenta_bancaria=banco.id_cuenta
        )


def test_registrar_abono_monto_invalido(db_session):
    cuenta, _ = _crear_cxc_otro(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=None, saldo_apertura=0)

    with pytest.raises(ValueError, match="mayor a cero"):
        OtrosMovimientosService.registrar_abono_otro(db_session, cuenta.id_cuenta, monto=Decimal("0.00"), id_caja=caja.id_caja)


def test_registrar_abono_cuenta_inexistente(db_session):
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=None, saldo_apertura=0)

    with pytest.raises(ValueError, match="no encontrada"):
        OtrosMovimientosService.registrar_abono_otro(db_session, 999999, monto=Decimal("10.00"), id_caja=caja.id_caja)


def test_registrar_abono_cuenta_ya_pagada(db_session):
    cuenta, _ = _crear_cxc_otro(db_session, monto=Decimal("50.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=None, saldo_apertura=0)
    OtrosMovimientosService.registrar_abono_otro(db_session, cuenta.id_cuenta, monto=Decimal("50.00"), id_caja=caja.id_caja)

    with pytest.raises(ValueError, match="ya esta pagada"):
        OtrosMovimientosService.registrar_abono_otro(db_session, cuenta.id_cuenta, monto=Decimal("1.00"), id_caja=caja.id_caja)


def test_registrar_abono_excede_saldo(db_session):
    cuenta, _ = _crear_cxc_otro(db_session, monto=Decimal("50.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=None, saldo_apertura=0)

    with pytest.raises(ValueError, match="excede el saldo pendiente"):
        OtrosMovimientosService.registrar_abono_otro(db_session, cuenta.id_cuenta, monto=Decimal("100.00"), id_caja=caja.id_caja)


def test_registrar_abono_cuenta_bancaria_inexistente(db_session):
    cuenta, _ = _crear_cxc_otro(db_session)
    with pytest.raises(ValueError, match="Cuenta bancaria no encontrada"):
        OtrosMovimientosService.registrar_abono_otro(db_session, cuenta.id_cuenta, monto=Decimal("10.00"), id_cuenta_bancaria=999999)


def test_registrar_abono_caja_inexistente(db_session):
    cuenta, _ = _crear_cxc_otro(db_session)
    with pytest.raises(ValueError, match="Caja no encontrada"):
        OtrosMovimientosService.registrar_abono_otro(db_session, cuenta.id_cuenta, monto=Decimal("10.00"), id_caja=999999)


def test_registrar_abono_caja_sin_turno_abierto(db_session):
    cuenta, _ = _crear_cxc_otro(db_session)
    caja = crear_caja(db_session)
    with pytest.raises(ValueError, match="no tiene un turno abierto"):
        OtrosMovimientosService.registrar_abono_otro(db_session, cuenta.id_cuenta, monto=Decimal("10.00"), id_caja=caja.id_caja)


def test_registrar_abono_parcial_por_caja(db_session):
    cuenta, _ = _crear_cxc_otro(db_session, monto=Decimal("100.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=None, saldo_apertura=0)

    actualizada = OtrosMovimientosService.registrar_abono_otro(
        db_session, cuenta.id_cuenta, monto=Decimal("40.00"), id_caja=caja.id_caja
    )

    assert actualizada.saldo_pendiente == Decimal("60.00")
    assert actualizada.estado == "parcial"

    movimiento = db_session.query(CajaMovimiento).filter_by(id_caja=caja.id_caja).one()
    assert movimiento.tipo_movimiento == "entrada"


def test_registrar_abono_completo_por_banco(db_session):
    cuenta, _ = _crear_cxc_otro(db_session, monto=Decimal("100.00"))
    banco = crear_cuenta_bancaria(db_session)

    actualizada = OtrosMovimientosService.registrar_abono_otro(
        db_session, cuenta.id_cuenta, monto=Decimal("100.00"), id_cuenta_bancaria=banco.id_cuenta
    )

    assert actualizada.saldo_pendiente == Decimal("0.00")
    assert actualizada.estado == "pagada"

    movimiento = db_session.query(BancoMovimiento).filter_by(id_cuenta=banco.id_cuenta).one()
    assert movimiento.tipo_movimiento == "abono"


# --- listar_cuentas_cobrar_otro --------------------------------------------------


def test_listar_cuentas_cobrar_otro_estado_invalido(db_session):
    with pytest.raises(ValueError, match="estado invalido"):
        OtrosMovimientosService.listar_cuentas_cobrar_otro(db_session, estado="no_existe")


def test_listar_cuentas_cobrar_otro_filtra_por_estado(db_session):
    cliente = crear_cliente(db_session)
    _crear_cxc_otro(db_session, monto=Decimal("50.00"), cliente=cliente)
    otra, _ = _crear_cxc_otro(db_session, monto=Decimal("30.00"), cliente=cliente)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=None, saldo_apertura=0)
    OtrosMovimientosService.registrar_abono_otro(db_session, otra.id_cuenta, monto=Decimal("30.00"), id_caja=caja.id_caja)

    pendientes = OtrosMovimientosService.listar_cuentas_cobrar_otro(db_session, estado="pendiente")
    pagadas = OtrosMovimientosService.listar_cuentas_cobrar_otro(db_session, estado="pagada")

    assert len(pendientes) == 1
    assert len(pagadas) == 1


def test_listar_cuentas_cobrar_otro_filtra_por_cliente(db_session):
    cliente_a = crear_cliente(db_session)
    cliente_b = crear_cliente(db_session)
    _crear_cxc_otro(db_session, cliente=cliente_a)
    _crear_cxc_otro(db_session, cliente=cliente_b)

    resultado = OtrosMovimientosService.listar_cuentas_cobrar_otro(db_session, id_cliente=cliente_a.id_cliente)

    assert len(resultado) == 1


# --- crear_partida_no_conciliada -------------------------------------------------


def test_crear_partida_no_conciliada(db_session):
    banco = crear_cuenta_bancaria(db_session)

    partida = OtrosMovimientosService.crear_partida_no_conciliada(
        db_session, id_cuenta_bancaria=banco.id_cuenta, monto=Decimal("200.00")
    )

    assert partida.id_cuenta is not None
    assert partida.saldo_pendiente == Decimal("200.00")
    assert partida.estado == "pendiente"


def test_crear_partida_no_conciliada_monto_invalido(db_session):
    banco = crear_cuenta_bancaria(db_session)
    with pytest.raises(ValueError, match="monto debe ser mayor a cero"):
        OtrosMovimientosService.crear_partida_no_conciliada(db_session, id_cuenta_bancaria=banco.id_cuenta, monto=Decimal("0.00"))


def test_crear_partida_no_conciliada_cuenta_bancaria_inexistente(db_session):
    with pytest.raises(ValueError, match="Cuenta bancaria no encontrada"):
        OtrosMovimientosService.crear_partida_no_conciliada(db_session, id_cuenta_bancaria=999999, monto=Decimal("200.00"))


def test_crear_partida_no_conciliada_movimiento_inexistente(db_session):
    banco = crear_cuenta_bancaria(db_session)
    with pytest.raises(ValueError, match="Movimiento bancario no encontrado"):
        OtrosMovimientosService.crear_partida_no_conciliada(
            db_session, id_cuenta_bancaria=banco.id_cuenta, monto=Decimal("200.00"), id_movimiento=999999
        )


# --- conciliar_partida -----------------------------------------------------------


def test_conciliar_partida_monto_invalido(db_session):
    banco = crear_cuenta_bancaria(db_session)
    partida = OtrosMovimientosService.crear_partida_no_conciliada(db_session, id_cuenta_bancaria=banco.id_cuenta, monto=Decimal("100.00"))
    cxc, cliente = _crear_cxc_real(db_session, Decimal("100.00"))

    with pytest.raises(ValueError, match="mayor a cero"):
        OtrosMovimientosService.conciliar_partida(
            db_session, partida.id_cuenta, cliente.id_cliente, cxc.id_cuenta_por_cobrar, monto=Decimal("0.00"), id_usuario=None
        )


def test_conciliar_partida_inexistente(db_session):
    cxc, cliente = _crear_cxc_real(db_session, Decimal("100.00"))
    with pytest.raises(ValueError, match="Partida no conciliada no encontrada"):
        OtrosMovimientosService.conciliar_partida(
            db_session, 999999, cliente.id_cliente, cxc.id_cuenta_por_cobrar, monto=Decimal("10.00"), id_usuario=None
        )


def test_conciliar_partida_excede_saldo_partida(db_session):
    banco = crear_cuenta_bancaria(db_session)
    partida = OtrosMovimientosService.crear_partida_no_conciliada(db_session, id_cuenta_bancaria=banco.id_cuenta, monto=Decimal("50.00"))
    cxc, cliente = _crear_cxc_real(db_session, Decimal("100.00"))

    with pytest.raises(ValueError, match="excede el saldo sin conciliar"):
        OtrosMovimientosService.conciliar_partida(
            db_session, partida.id_cuenta, cliente.id_cliente, cxc.id_cuenta_por_cobrar, monto=Decimal("60.00"), id_usuario=None
        )


def test_conciliar_partida_cliente_inexistente(db_session):
    banco = crear_cuenta_bancaria(db_session)
    partida = OtrosMovimientosService.crear_partida_no_conciliada(db_session, id_cuenta_bancaria=banco.id_cuenta, monto=Decimal("100.00"))
    cxc, _ = _crear_cxc_real(db_session, Decimal("100.00"))

    with pytest.raises(ValueError, match="Cliente no encontrado"):
        OtrosMovimientosService.conciliar_partida(
            db_session, partida.id_cuenta, 999999, cxc.id_cuenta_por_cobrar, monto=Decimal("10.00"), id_usuario=None
        )


def test_conciliar_partida_cxc_inexistente(db_session):
    banco = crear_cuenta_bancaria(db_session)
    partida = OtrosMovimientosService.crear_partida_no_conciliada(db_session, id_cuenta_bancaria=banco.id_cuenta, monto=Decimal("100.00"))
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="Cuenta por cobrar no encontrada"):
        OtrosMovimientosService.conciliar_partida(
            db_session, partida.id_cuenta, cliente.id_cliente, 999999, monto=Decimal("10.00"), id_usuario=None
        )


def test_conciliar_partida_cxc_no_pertenece_al_cliente(db_session):
    banco = crear_cuenta_bancaria(db_session)
    partida = OtrosMovimientosService.crear_partida_no_conciliada(db_session, id_cuenta_bancaria=banco.id_cuenta, monto=Decimal("100.00"))
    cxc, _dueno_real = _crear_cxc_real(db_session, Decimal("100.00"))
    otro_cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="no pertenece al cliente"):
        OtrosMovimientosService.conciliar_partida(
            db_session, partida.id_cuenta, otro_cliente.id_cliente, cxc.id_cuenta_por_cobrar, monto=Decimal("10.00"), id_usuario=None
        )


def test_conciliar_partida_excede_saldo_factura(db_session):
    banco = crear_cuenta_bancaria(db_session)
    partida = OtrosMovimientosService.crear_partida_no_conciliada(db_session, id_cuenta_bancaria=banco.id_cuenta, monto=Decimal("500.00"))
    cxc, cliente = _crear_cxc_real(db_session, Decimal("50.00"))

    with pytest.raises(ValueError, match="excede el saldo pendiente de la factura"):
        OtrosMovimientosService.conciliar_partida(
            db_session, partida.id_cuenta, cliente.id_cliente, cxc.id_cuenta_por_cobrar, monto=Decimal("100.00"), id_usuario=None
        )


def test_conciliar_partida_ya_atribuida_a_otro_cliente(db_session):
    banco = crear_cuenta_bancaria(db_session)
    partida = OtrosMovimientosService.crear_partida_no_conciliada(db_session, id_cuenta_bancaria=banco.id_cuenta, monto=Decimal("100.00"))
    cxc1, cliente1 = _crear_cxc_real(db_session, Decimal("50.00"))
    OtrosMovimientosService.conciliar_partida(
        db_session, partida.id_cuenta, cliente1.id_cliente, cxc1.id_cuenta_por_cobrar, monto=Decimal("30.00"), id_usuario=None
    )

    cxc2, cliente2 = _crear_cxc_real(db_session, Decimal("50.00"))
    with pytest.raises(ValueError, match="ya fue atribuida a otro cliente"):
        OtrosMovimientosService.conciliar_partida(
            db_session, partida.id_cuenta, cliente2.id_cliente, cxc2.id_cuenta_por_cobrar, monto=Decimal("10.00"), id_usuario=None
        )


def test_conciliar_partida_exitosa_no_duplica_movimiento_bancario(db_session):
    banco = crear_cuenta_bancaria(db_session)
    partida = OtrosMovimientosService.crear_partida_no_conciliada(db_session, id_cuenta_bancaria=banco.id_cuenta, monto=Decimal("100.00"))
    cxc, cliente = _crear_cxc_real(db_session, Decimal("80.00"))

    conteo_movimientos_antes = db_session.query(BancoMovimiento).count()

    resultado = OtrosMovimientosService.conciliar_partida(
        db_session, partida.id_cuenta, cliente.id_cliente, cxc.id_cuenta_por_cobrar, monto=Decimal("80.00"), id_usuario=None
    )

    assert resultado["cuenta_por_cobrar"].saldo_pendiente == Decimal("0.00")
    assert resultado["cuenta_por_cobrar"].estado == "pagada"
    assert resultado["partida"].saldo_pendiente == Decimal("20.00")
    assert resultado["partida"].estado == "parcial"
    assert resultado["partida"].id_cliente_identificado == cliente.id_cliente

    conteo_movimientos_despues = db_session.query(BancoMovimiento).count()
    assert conteo_movimientos_despues == conteo_movimientos_antes


# --- listar_partidas_no_conciliadas ----------------------------------------------


def test_listar_partidas_no_conciliadas_estado_invalido(db_session):
    with pytest.raises(ValueError, match="estado invalido"):
        OtrosMovimientosService.listar_partidas_no_conciliadas(db_session, estado="no_existe")


def test_listar_partidas_no_conciliadas_filtra_por_estado(db_session):
    banco = crear_cuenta_bancaria(db_session)
    OtrosMovimientosService.crear_partida_no_conciliada(db_session, id_cuenta_bancaria=banco.id_cuenta, monto=Decimal("100.00"))

    pendientes = OtrosMovimientosService.listar_partidas_no_conciliadas(db_session, estado="pendiente")
    conciliadas = OtrosMovimientosService.listar_partidas_no_conciliadas(db_session, estado="conciliado")

    assert len(pendientes) == 1
    assert len(conciliadas) == 0
