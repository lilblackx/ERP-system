"""Pruebas de ComisionService (calculo, llamado desde VentaService.emitir_factura -- ver
tests/services/test_ventas.py para esos casos) y PagoComisionService (pago real de
caja/banco de las comisiones acumuladas de un vendedor, C14)."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.db.models import BancoMovimiento, CajaMovimiento, ComisionFactura, CuentaPorCobrar, FacturaDetalle
from app.services.comisiones import ComisionService, PagoComisionService
from app.services.pagos import PagoService
from app.services.permisos import PermisoDenegadoError
from app.services.ventas import VentaService
from tests.factories import (
    crear_caja,
    crear_cliente,
    crear_cuenta_bancaria,
    crear_precio_producto,
    crear_producto,
    crear_usuario_admin,
    crear_vendedor,
    pago_contado,
)


def _crear_comisiones_liberadas(session, vendedor, admin, cantidades_precios: list[tuple[Decimal, Decimal, Decimal]]):
    """cantidades_precios: lista de (precio_lista, precio_venta, cantidad) -- una linea por
    tupla, cada una en un producto distinto (ComisionFactura.id_factura_detalle es unico,
    asi que hace falta una linea real por comision). Factura de contado: la comision nace
    'liberada' directo (ver ComisionService.calcular_comisiones_factura). Devuelve la lista
    de ComisionFactura creadas."""
    items = []
    for precio_lista, precio_venta, cantidad in cantidades_precios:
        producto = crear_producto(session, cantidad_unidad=100)
        crear_precio_producto(session, producto, precio_lista)
        items.append({"id_producto": producto.id_producto, "cantidad": cantidad, "precio_unitario": str(precio_venta)})

    cliente = crear_cliente(session)
    factura = VentaService.emitir_factura(
        session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=items,
        pagos=pago_contado(session),
    )
    ids_detalle = [
        id_factura_detalle
        for (id_factura_detalle,) in session.query(FacturaDetalle.id_factura_detalle).filter_by(
            id_factura=factura.id_factura
        )
    ]
    return session.query(ComisionFactura).filter(ComisionFactura.id_factura_detalle.in_(ids_detalle)).all()


# --- ComisionService.calcular_comisiones_factura (batch, N+1) ----------------------


def test_calcular_comisiones_factura_batch_saltea_producto_sin_precio(db_session):
    """Un solo producto del batch sin precio de lista configurado bloquea la factura
    entera (VentaService.emitir_factura lo valida antes de tocar stock/CxC/comisiones) --
    no hay forma de emitir parcialmente ni de saltear solo esa linea."""
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    con_precio = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, con_precio, "1.00")
    sin_precio = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="no tienen precio de venta configurado"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            items=[
                {"id_producto": con_precio.id_producto, "cantidad": 2, "precio_unitario": "2.00"},
                {"id_producto": sin_precio.id_producto, "cantidad": 1, "precio_unitario": "20.00"},
            ],
            pagos=pago_contado(db_session),
        )


# --- PagoComisionService.pagar_comisiones_vendedor ----------------------------------


def test_pagar_comisiones_vendedor_por_caja(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    comisiones = _crear_comisiones_liberadas(
        db_session, vendedor, admin, [(Decimal("1.00"), Decimal("2.00"), Decimal("3"))]
    )
    assert comisiones[0].monto_comision == Decimal("3.00")
    caja = crear_caja(db_session)

    pago = PagoComisionService.pagar_comisiones_vendedor(
        db_session,
        id_vendedor=vendedor.id_vendedor,
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    assert pago.id_pago_comision is not None
    assert pago.monto == Decimal("3.00")

    db_session.refresh(comisiones[0])
    assert comisiones[0].estado_pago == "pagada"
    assert comisiones[0].id_pago_comision == pago.id_pago_comision

    movimiento = db_session.query(CajaMovimiento).filter_by(id_pago_comision=pago.id_pago_comision).one()
    assert movimiento.tipo_movimiento == "salida"
    assert movimiento.monto_movimiento == Decimal("3.00")


def test_pagar_comisiones_vendedor_por_cuenta_bancaria(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    _crear_comisiones_liberadas(db_session, vendedor, admin, [(Decimal("1.00"), Decimal("2.00"), Decimal("3"))])
    cuenta = crear_cuenta_bancaria(db_session, saldo_total_banco=Decimal("500.00"))

    pago = PagoComisionService.pagar_comisiones_vendedor(
        db_session,
        id_vendedor=vendedor.id_vendedor,
        metodo_pago="transferencia",
        id_cuenta_bancaria=cuenta.id_cuenta,
        id_usuario=admin.id_usuario,
    )

    assert pago.monto == Decimal("3.00")
    movimiento = db_session.query(BancoMovimiento).filter_by(id_pago_comision=pago.id_pago_comision).one()
    assert movimiento.tipo_movimiento == "cargo"

    db_session.refresh(cuenta)
    assert cuenta.saldo_total_banco == Decimal("497.00")  # trg_banco_movimientos_saldo


def test_pagar_comisiones_vendedor_agrupa_varias_lineas_pendientes(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    _crear_comisiones_liberadas(
        db_session,
        vendedor,
        admin,
        [(Decimal("1.00"), Decimal("2.00"), Decimal("1")), (Decimal("5.00"), Decimal("7.00"), Decimal("1"))],
    )
    caja = crear_caja(db_session)

    pago = PagoComisionService.pagar_comisiones_vendedor(
        db_session,
        id_vendedor=vendedor.id_vendedor,
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    assert pago.monto == Decimal("3.00")  # (2.00-1.00) + (7.00-5.00)


def test_pagar_comisiones_vendedor_requiere_exactamente_un_origen(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    _crear_comisiones_liberadas(db_session, vendedor, admin, [(Decimal("1.00"), Decimal("2.00"), Decimal("1"))])
    caja = crear_caja(db_session)
    cuenta = crear_cuenta_bancaria(db_session)

    with pytest.raises(ValueError, match="exactamente un origen"):
        PagoComisionService.pagar_comisiones_vendedor(
            db_session,
            id_vendedor=vendedor.id_vendedor,
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
            id_cuenta_bancaria=cuenta.id_cuenta,
            id_usuario=admin.id_usuario,
        )

    with pytest.raises(ValueError, match="exactamente un origen"):
        PagoComisionService.pagar_comisiones_vendedor(
            db_session, id_vendedor=vendedor.id_vendedor, metodo_pago="efectivo", id_usuario=admin.id_usuario
        )


def test_pagar_comisiones_vendedor_sin_comisiones_pendientes_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    caja = crear_caja(db_session)

    with pytest.raises(ValueError, match="No hay comisiones liberadas"):
        PagoComisionService.pagar_comisiones_vendedor(
            db_session,
            id_vendedor=vendedor.id_vendedor,
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
            id_usuario=admin.id_usuario,
        )


def test_pagar_comisiones_vendedor_no_repaga_las_ya_pagadas(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    _crear_comisiones_liberadas(db_session, vendedor, admin, [(Decimal("1.00"), Decimal("2.00"), Decimal("1"))])
    caja = crear_caja(db_session)
    PagoComisionService.pagar_comisiones_vendedor(
        db_session,
        id_vendedor=vendedor.id_vendedor,
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    with pytest.raises(ValueError, match="No hay comisiones liberadas"):
        PagoComisionService.pagar_comisiones_vendedor(
            db_session,
            id_vendedor=vendedor.id_vendedor,
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
            id_usuario=admin.id_usuario,
        )


def test_pagar_comisiones_vendedor_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    _crear_comisiones_liberadas(db_session, vendedor, admin, [(Decimal("1.00"), Decimal("2.00"), Decimal("1"))])
    caja = crear_caja(db_session)

    with pytest.raises(PermisoDenegadoError):
        PagoComisionService.pagar_comisiones_vendedor(
            db_session, id_vendedor=vendedor.id_vendedor, metodo_pago="efectivo", id_caja=caja.id_caja
        )


def test_pagar_comisiones_vendedor_no_encontrado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)

    with pytest.raises(ValueError, match="Vendedor no encontrado"):
        PagoComisionService.pagar_comisiones_vendedor(
            db_session, id_vendedor=999999, metodo_pago="efectivo", id_caja=caja.id_caja, id_usuario=admin.id_usuario
        )


# --- listar_comisiones_vendedor / listar_pagos_comision_vendedor -------------------


def test_listar_comisiones_vendedor_filtra_por_estado(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    _crear_comisiones_liberadas(db_session, vendedor, admin, [(Decimal("1.00"), Decimal("2.00"), Decimal("1"))])

    liberadas = ComisionService.listar_comisiones_vendedor(
        db_session, vendedor.id_vendedor, estado_pago="liberada", id_usuario=admin.id_usuario
    )
    pendientes = ComisionService.listar_comisiones_vendedor(
        db_session, vendedor.id_vendedor, estado_pago="pendiente", id_usuario=admin.id_usuario
    )
    pagadas = ComisionService.listar_comisiones_vendedor(
        db_session, vendedor.id_vendedor, estado_pago="pagada", id_usuario=admin.id_usuario
    )

    assert len(liberadas) == 1
    assert len(pendientes) == 0
    assert len(pagadas) == 0


def test_listar_pagos_comision_vendedor(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    _crear_comisiones_liberadas(db_session, vendedor, admin, [(Decimal("1.00"), Decimal("2.00"), Decimal("1"))])
    caja = crear_caja(db_session)
    PagoComisionService.pagar_comisiones_vendedor(
        db_session,
        id_vendedor=vendedor.id_vendedor,
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    pagos = PagoComisionService.listar_pagos_comision_vendedor(
        db_session, vendedor.id_vendedor, id_usuario=admin.id_usuario
    )

    assert len(pagos) == 1
    assert pagos[0].monto == Decimal("1.00")


def test_listar_mis_comisiones_retorna_solo_propias(db_session):
    """listar_mis_comisiones retorna solo comisiones del vendedor vinculado.
    Usa un usuario ADMIN con id_vendedor_usuario para testear el filtrado."""
    admin = crear_usuario_admin(db_session)
    vendedor1 = crear_vendedor(db_session)
    vendedor2 = crear_vendedor(db_session)

    admin.id_vendedor_usuario = vendedor1.id_vendedor
    db_session.commit()

    _crear_comisiones_liberadas(db_session, vendedor1, admin, [(Decimal("1.00"), Decimal("2.00"), Decimal("1"))])
    _crear_comisiones_liberadas(db_session, vendedor2, admin, [(Decimal("1.00"), Decimal("3.00"), Decimal("1"))])

    comisiones = ComisionService.listar_mis_comisiones(db_session, admin.id_usuario)

    assert len(comisiones) == 1
    assert comisiones[0].id_vendedor == vendedor1.id_vendedor
    assert comisiones[0].monto_comision == Decimal("1.00")


def test_listar_mis_comisiones_sin_vendedor_vinculado(db_session):
    """Usuario sin vendedor vinculado lanza ValueError."""
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="no tiene un vendedor vinculado"):
        ComisionService.listar_mis_comisiones(db_session, admin.id_usuario)


# --- Flujo de credito: 'pendiente' hasta que el cliente paga, luego 'liberada' -----


def test_comision_credito_nace_pendiente_y_no_es_pagable(db_session):
    """A diferencia de contado, una venta a credito no esta cobrada al emitir -- la
    comision nace 'pendiente' y pagar_comisiones_vendedor (que solo paga 'liberada') no
    tiene nada que pagar todavia."""
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "1.00")
    cliente = crear_cliente(db_session, limite_credito=Decimal("100.00"))
    caja = crear_caja(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "2.00"}],
    )
    detalle = db_session.query(FacturaDetalle).filter_by(id_factura=factura.id_factura).first()
    comision = db_session.query(ComisionFactura).filter_by(id_factura_detalle=detalle.id_factura_detalle).one()
    assert comision.estado_pago == "pendiente"

    with pytest.raises(ValueError, match="No hay comisiones liberadas"):
        PagoComisionService.pagar_comisiones_vendedor(
            db_session,
            id_vendedor=vendedor.id_vendedor,
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
            id_usuario=admin.id_usuario,
        )


def test_comision_credito_se_libera_al_cobrar_cxc_completa(db_session):
    """trg_cxc_libera_comisiones (migrations/0045) libera la comision 'pendiente' cuando
    la cuenta por cobrar de esa factura llega a 'pagada' -- no antes (pago parcial deja la
    comision 'pendiente')."""
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "1.00")
    cliente = crear_cliente(db_session, limite_credito=Decimal("100.00"))
    caja = crear_caja(db_session, fecha_apertura=datetime.now())

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "2.00"}],
    )
    detalle = db_session.query(FacturaDetalle).filter_by(id_factura=factura.id_factura).first()
    comision = db_session.query(ComisionFactura).filter_by(id_factura_detalle=detalle.id_factura_detalle).one()
    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()
    assert cxc.saldo_pendiente == Decimal("4.00")  # 2.00 (real) * 2

    # Pago parcial: la CxC queda 'parcial', la comision sigue 'pendiente'.
    PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("2.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )
    db_session.refresh(comision)
    assert comision.estado_pago == "pendiente"

    # Pago del saldo restante: la CxC llega a 'pagada' y el trigger libera la comision.
    PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("2.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )
    db_session.refresh(comision)
    assert comision.estado_pago == "liberada"

    pago = PagoComisionService.pagar_comisiones_vendedor(
        db_session,
        id_vendedor=vendedor.id_vendedor,
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )
    assert pago.monto == Decimal("2.00")  # (2.00-1.00)*2
    db_session.refresh(comision)
    assert comision.estado_pago == "pagada"
