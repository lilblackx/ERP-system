"""Pagos de cuentas por cobrar BCV: deben dejar fila de pago, ingreso en la caja/cuenta de
destino y aparecer en el historial del cliente (antes solo bajaban el saldo de la cuenta)."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.db.models import BancoMovimiento, Caja, CajaMovimiento, CuentaPorCobrarBCV, PagoCobroBCV
from app.services.historial_cliente import obtener_historial_cliente
from app.services.pagos_bcv import PagoBCVService
from app.services.tesoreria import CajaService
from app.services.ventas import VentaService
from tests.factories import (
    crear_caja,
    crear_cliente,
    crear_cuenta_bancaria,
    crear_precio_producto,
    crear_producto,
    crear_usuario_admin,
    crear_vendedor,
)


def _emitir_credito_bcv(session, admin, cliente=None, precio="100.00", porcentaje="10"):
    vendedor = crear_vendedor(session)
    producto = crear_producto(session, cantidad_unidad=100)
    crear_precio_producto(session, producto, precio)
    cliente = cliente or crear_cliente(session, limite_credito=Decimal("100000.00"))
    factura = VentaService.emitir_factura(
        session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": precio}],
        porcentaje_bcv=Decimal(porcentaje),
    )
    cuenta = session.query(CuentaPorCobrarBCV).filter_by(id_factura=factura.id_factura).one()
    return factura, cuenta, cliente


def _caja_abierta(session, admin):
    caja = crear_caja(session)
    CajaService.abrir_caja(session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)
    return caja


# ── Cobro individual ────────────────────────────────────────────────────────


def test_cobro_bcv_por_banco_registra_pago_y_abono_en_la_cuenta(db_session):
    admin = crear_usuario_admin(db_session)
    _, cuenta, _ = _emitir_credito_bcv(db_session, admin)
    banco = crear_cuenta_bancaria(db_session, saldo_total_banco=Decimal("500.00"))
    saldo_inicial = cuenta.saldo_pendiente

    PagoBCVService.registrar_pago_cobro_bcv(
        db_session,
        id_cuenta_por_cobrar=cuenta.id_cuenta_por_cobrar,
        monto=Decimal("30.00"),
        metodo_pago="transferencia",
        monto_moneda_origen=Decimal("1200.00"),
        monto_bolivares=Decimal("1200.00"),
        tasa_cambio=Decimal("40.00"),
        id_cuenta_bancaria=banco.id_cuenta,
        referencia="REF-1",
        id_usuario=admin.id_usuario,
    )

    db_session.refresh(cuenta)
    assert cuenta.saldo_pendiente == saldo_inicial - Decimal("30.00")
    assert cuenta.estado == "parcial"

    pago = db_session.query(PagoCobroBCV).one()
    assert pago.id_cuenta_por_cobrar == cuenta.id_cuenta_por_cobrar
    assert pago.monto == Decimal("30.00")
    assert pago.monto_bolivares == Decimal("1200.00")
    assert pago.tasa_cambio == Decimal("40.00")
    assert pago.id_cuenta_bancaria == banco.id_cuenta

    movimiento = db_session.query(BancoMovimiento).filter_by(id_cuenta=banco.id_cuenta).one()
    assert movimiento.tipo_movimiento == "abono"
    assert movimiento.monto_movimiento == Decimal("30.00")
    assert movimiento.monto_bolivares == Decimal("1200.00")
    assert movimiento.referencia_movimiento == "REF-1"
    assert movimiento.id_pago_cobro_bcv == pago.id_pago_cobro_bcv
    assert "Cobro a cliente BCV" in movimiento.descripcion_movimiento

    db_session.refresh(banco)
    assert banco.saldo_total_banco == Decimal("530.00")  # lo suma trg_banco_movimientos_saldo


def test_cobro_bcv_por_caja_registra_entrada(db_session):
    admin = crear_usuario_admin(db_session)
    _, cuenta, _ = _emitir_credito_bcv(db_session, admin)
    caja = _caja_abierta(db_session, admin)

    PagoBCVService.registrar_pago_cobro_bcv(
        db_session,
        id_cuenta_por_cobrar=cuenta.id_cuenta_por_cobrar,
        monto=Decimal("25.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    pago = db_session.query(PagoCobroBCV).one()
    movimiento = (
        db_session.query(CajaMovimiento).filter_by(id_caja=caja.id_caja, id_pago_cobro_bcv=pago.id_pago_cobro_bcv).one()
    )
    assert movimiento.tipo_movimiento == "entrada"
    assert movimiento.monto_movimiento == Decimal("25.00")


def test_cobro_bcv_total_deja_la_cuenta_pagada(db_session):
    admin = crear_usuario_admin(db_session)
    _, cuenta, _ = _emitir_credito_bcv(db_session, admin)
    caja = _caja_abierta(db_session, admin)

    PagoBCVService.registrar_pago_cobro_bcv(
        db_session,
        id_cuenta_por_cobrar=cuenta.id_cuenta_por_cobrar,
        monto=cuenta.saldo_pendiente,
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    db_session.refresh(cuenta)
    assert cuenta.saldo_pendiente == Decimal("0.00")
    assert cuenta.estado == "pagada"


def test_cobro_bcv_a_caja_sin_turno_abierto_falla_y_no_toca_nada(db_session):
    admin = crear_usuario_admin(db_session)
    _, cuenta, _ = _emitir_credito_bcv(db_session, admin)
    caja_cerrada = crear_caja(db_session)  # nunca se abrio
    saldo_inicial = cuenta.saldo_pendiente

    with pytest.raises(ValueError, match="turno abierto"):
        PagoBCVService.registrar_pago_cobro_bcv(
            db_session,
            id_cuenta_por_cobrar=cuenta.id_cuenta_por_cobrar,
            monto=Decimal("10.00"),
            metodo_pago="efectivo",
            id_caja=caja_cerrada.id_caja,
            id_usuario=admin.id_usuario,
        )

    db_session.refresh(cuenta)
    assert cuenta.saldo_pendiente == saldo_inicial
    assert db_session.query(PagoCobroBCV).count() == 0
    assert db_session.query(CajaMovimiento).filter_by(id_caja=caja_cerrada.id_caja).count() == 0


def test_cobro_bcv_excedido_falla(db_session):
    admin = crear_usuario_admin(db_session)
    _, cuenta, _ = _emitir_credito_bcv(db_session, admin)
    caja = _caja_abierta(db_session, admin)

    with pytest.raises(ValueError, match="excede el saldo"):
        PagoBCVService.registrar_pago_cobro_bcv(
            db_session,
            id_cuenta_por_cobrar=cuenta.id_cuenta_por_cobrar,
            monto=cuenta.saldo_pendiente + Decimal("1.00"),
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
            id_usuario=admin.id_usuario,
        )
    assert db_session.query(PagoCobroBCV).count() == 0


# ── Abono general ───────────────────────────────────────────────────────────


def test_abono_general_bcv_registra_un_pago_por_factura_y_el_ingreso_total(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session, limite_credito=Decimal("100000.00"))
    _, cuenta1, _ = _emitir_credito_bcv(db_session, admin, cliente=cliente, precio="100.00")
    _, cuenta2, _ = _emitir_credito_bcv(db_session, admin, cliente=cliente, precio="100.00")
    banco = crear_cuenta_bancaria(db_session, saldo_total_banco=Decimal("0.00"))
    # Mas que la primera factura, para que reparta (FIFO) entre las dos.
    abono = cuenta1.saldo_pendiente + Decimal("20.00")

    resultado = PagoBCVService.aplicar_abono_general_cliente_bcv(
        db_session,
        id_cliente=cliente.id_cliente,
        monto_abono=abono,
        tasa_cambio=Decimal("40.00"),
        metodo_pago="transferencia",
        id_cuenta_bancaria=banco.id_cuenta,
        id_usuario=admin.id_usuario,
    )

    assert resultado["monto_total_aplicado"] == abono
    pagos = db_session.query(PagoCobroBCV).order_by(PagoCobroBCV.id_pago_cobro_bcv).all()
    assert len(pagos) == 2
    assert sum((p.monto for p in pagos), Decimal("0")) == abono
    assert all(p.tasa_cambio == Decimal("40.00") for p in pagos)
    assert pagos[0].monto_bolivares == (pagos[0].monto * Decimal("40")).quantize(Decimal("0.01"))

    movimientos = db_session.query(BancoMovimiento).filter_by(id_cuenta=banco.id_cuenta).all()
    assert sum((m.monto_movimiento for m in movimientos), Decimal("0")) == abono
    db_session.refresh(banco)
    assert banco.saldo_total_banco == abono


def test_abono_general_bcv_sobreabono_tambien_ingresa_el_excedente(db_session):
    admin = crear_usuario_admin(db_session)
    _, cuenta, cliente = _emitir_credito_bcv(db_session, admin)
    banco = crear_cuenta_bancaria(db_session, saldo_total_banco=Decimal("0.00"))
    deuda = cuenta.saldo_pendiente
    abono = deuda + Decimal("15.00")

    resultado = PagoBCVService.aplicar_abono_general_cliente_bcv(
        db_session,
        id_cliente=cliente.id_cliente,
        monto_abono=abono,
        tasa_cambio=Decimal("40.00"),
        metodo_pago="transferencia",
        id_cuenta_bancaria=banco.id_cuenta,
        id_usuario=admin.id_usuario,
    )

    assert resultado["es_sobreabono"] is True
    assert resultado["saldo_restante"] == Decimal("15.00")
    db_session.refresh(banco)
    # Entro todo el dinero: la deuda cobrada + el excedente que quedo como saldo a favor.
    assert banco.saldo_total_banco == abono
    descripciones = [m.descripcion_movimiento for m in db_session.query(BancoMovimiento).all()]
    assert any("Sobreabono BCV" in d for d in descripciones)


# ── Factura de contado con porcentaje BCV ───────────────────────────────────


def test_factura_de_contado_con_bcv_ingresa_el_dinero_a_la_caja(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=100)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session)
    caja = Caja(
        nombre_caja="Caja contado BCV",
        estado_caja="ABIERTA",
        saldo_apertura=Decimal("0.00"),
        fecha_apertura=datetime.now(),
    )
    db_session.add(caja)
    db_session.commit()
    db_session.refresh(caja)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
        pagos=[
            {
                "metodo_pago": "efectivo",
                "moneda": "USD",
                "monto_moneda_origen": Decimal("500.00"),
                "id_caja": caja.id_caja,
            }
        ],
        porcentaje_bcv=Decimal("10"),
    )

    cuenta = db_session.query(CuentaPorCobrarBCV).filter_by(id_factura=factura.id_factura).one()
    assert cuenta.estado == "pagada"
    pago = db_session.query(PagoCobroBCV).one()
    assert pago.id_cuenta_por_cobrar == cuenta.id_cuenta_por_cobrar
    # El pago aplicado es lo que cubria la cuenta BCV; el resto fue vuelto.
    assert 0 < pago.monto <= Decimal("500.00")

    entradas = (
        db_session.query(CajaMovimiento)
        .filter_by(id_caja=caja.id_caja, id_pago_cobro_bcv=pago.id_pago_cobro_bcv, tipo_movimiento="entrada")
        .all()
    )
    assert len(entradas) == 1
    assert entradas[0].monto_movimiento == pago.monto


# ── Historial del cliente ───────────────────────────────────────────────────


def test_historial_muestra_el_pago_bcv_y_el_saldo_real_de_la_factura(db_session):
    admin = crear_usuario_admin(db_session)
    factura, cuenta, cliente = _emitir_credito_bcv(db_session, admin)
    caja = _caja_abierta(db_session, admin)
    PagoBCVService.registrar_pago_cobro_bcv(
        db_session,
        id_cuenta_por_cobrar=cuenta.id_cuenta_por_cobrar,
        monto=Decimal("40.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )
    db_session.refresh(cuenta)

    historial = obtener_historial_cliente(db_session, cliente.id_cliente)

    facturas = [h for h in historial if h["tipo_transaccion"] == "factura"]
    pagos = [h for h in historial if h["tipo_transaccion"] == "pago"]
    assert len(pagos) == 1
    assert pagos[0]["monto"] == Decimal("-40.00")
    assert pagos[0]["numero_factura"] == factura.numero_factura
    assert pagos[0]["metodo_pago"] == "efectivo"
    # La cuenta normal queda en 0 a proposito: el saldo de la factura es el de la cuenta BCV.
    assert facturas[0]["saldo_corrido"] == cuenta.saldo_pendiente
    assert cuenta.saldo_pendiente > 0
