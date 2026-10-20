"""Pruebas de ComisionService (calculo, llamado desde VentaService.emitir_factura -- ver
tests/services/test_ventas.py para esos casos) y PagoComisionService (pago real de
caja/banco de las comisiones acumuladas de un vendedor, C14)."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.db.models import (
    BancoMovimiento,
    CajaMovimiento,
    ComisionFactura,
    CuentaPorCobrar,
    FacturaDetalle,
)
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
        items.append(
            {
                "id_producto": producto.id_producto,
                "cantidad": cantidad,
                "precio_unitario": str(precio_venta),
            }
        )

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
                {
                    "id_producto": con_precio.id_producto,
                    "cantidad": 2,
                    "precio_unitario": "2.00",
                },
                {
                    "id_producto": sin_precio.id_producto,
                    "cantidad": 1,
                    "precio_unitario": "20.00",
                },
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
        [
            (Decimal("1.00"), Decimal("2.00"), Decimal("1")),
            (Decimal("5.00"), Decimal("7.00"), Decimal("1")),
        ],
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
            db_session,
            id_vendedor=vendedor.id_vendedor,
            metodo_pago="efectivo",
            id_usuario=admin.id_usuario,
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
            db_session,
            id_vendedor=vendedor.id_vendedor,
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
        )


def test_pagar_comisiones_vendedor_no_encontrado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)

    with pytest.raises(ValueError, match="Vendedor no encontrado"):
        PagoComisionService.pagar_comisiones_vendedor(
            db_session,
            id_vendedor=999999,
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
            id_usuario=admin.id_usuario,
        )


# --- listar_comisiones_vendedor / listar_pagos_comision_vendedor -------------------


def test_listar_comisiones_vendedor_filtra_por_estado(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    _crear_comisiones_liberadas(db_session, vendedor, admin, [(Decimal("1.00"), Decimal("2.00"), Decimal("1"))])

    liberadas = ComisionService.listar_comisiones_vendedor(
        db_session,
        vendedor.id_vendedor,
        estado_pago="liberada",
        id_usuario=admin.id_usuario,
    )
    pendientes = ComisionService.listar_comisiones_vendedor(
        db_session,
        vendedor.id_vendedor,
        estado_pago="pendiente",
        id_usuario=admin.id_usuario,
    )
    pagadas = ComisionService.listar_comisiones_vendedor(
        db_session,
        vendedor.id_vendedor,
        estado_pago="pagada",
        id_usuario=admin.id_usuario,
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
        items=[
            {
                "id_producto": producto.id_producto,
                "cantidad": 2,
                "precio_unitario": "2.00",
            }
        ],
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
        items=[
            {
                "id_producto": producto.id_producto,
                "cantidad": 2,
                "precio_unitario": "2.00",
            }
        ],
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


# --- Pago restringido a un subconjunto (ej. filtro "Solo con porcentaje BCV") -------


def _dos_comisiones_liberadas(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    comisiones = _crear_comisiones_liberadas(
        db_session,
        vendedor,
        admin,
        [
            (Decimal("1.00"), Decimal("2.00"), Decimal("3")),  # comision 3.00
            (Decimal("1.00"), Decimal("3.00"), Decimal("2")),  # comision 4.00
        ],
    )
    assert [c.monto_comision for c in comisiones] == [Decimal("3.00"), Decimal("4.00")]
    return admin, vendedor, comisiones, crear_caja(db_session)


def test_pagar_con_ids_paga_solo_esas_comisiones(db_session):
    """Con la lista filtrada la pantalla muestra (y el usuario confirma) $3, no los $7 que
    suman todas las liberadas: el pago tiene que liquidar solo lo mostrado."""
    admin, vendedor, comisiones, caja = _dos_comisiones_liberadas(db_session)

    pago = PagoComisionService.pagar_comisiones_vendedor(
        db_session,
        id_vendedor=vendedor.id_vendedor,
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
        ids_comision=[comisiones[0].id_comision],
        monto_esperado=Decimal("3.00"),
    )

    assert pago.monto == Decimal("3.00")
    db_session.refresh(comisiones[0])
    db_session.refresh(comisiones[1])
    assert comisiones[0].estado_pago == "pagada"
    assert comisiones[1].estado_pago == "liberada"  # no se toco
    movimiento = db_session.query(CajaMovimiento).filter_by(id_pago_comision=pago.id_pago_comision).one()
    assert movimiento.monto_movimiento == Decimal("3.00")


def test_pagar_sin_ids_sigue_pagando_todo_lo_liberado(db_session):
    admin, vendedor, comisiones, caja = _dos_comisiones_liberadas(db_session)

    pago = PagoComisionService.pagar_comisiones_vendedor(
        db_session,
        id_vendedor=vendedor.id_vendedor,
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    assert pago.monto == Decimal("7.00")


def test_pagar_con_monto_esperado_distinto_se_rechaza_sin_pagar_nada(db_session):
    """El usuario confirmo $3 pero las comisiones indicadas suman $7: no se mueve plata."""
    admin, vendedor, comisiones, caja = _dos_comisiones_liberadas(db_session)

    with pytest.raises(ValueError, match="no coincide con el confirmado"):
        PagoComisionService.pagar_comisiones_vendedor(
            db_session,
            id_vendedor=vendedor.id_vendedor,
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
            id_usuario=admin.id_usuario,
            ids_comision=[c.id_comision for c in comisiones],
            monto_esperado=Decimal("3.00"),
        )

    for comision in comisiones:
        db_session.refresh(comision)
        assert comision.estado_pago == "liberada"
    assert db_session.query(CajaMovimiento).filter_by(id_caja=caja.id_caja).count() == 0


def test_pagar_con_ids_ya_pagados_falla(db_session):
    admin, vendedor, comisiones, caja = _dos_comisiones_liberadas(db_session)
    PagoComisionService.pagar_comisiones_vendedor(
        db_session,
        id_vendedor=vendedor.id_vendedor,
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
        ids_comision=[comisiones[0].id_comision],
    )

    with pytest.raises(ValueError, match="No hay comisiones liberadas"):
        PagoComisionService.pagar_comisiones_vendedor(
            db_session,
            id_vendedor=vendedor.id_vendedor,
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
            id_usuario=admin.id_usuario,
            ids_comision=[comisiones[0].id_comision],
        )


# --- Filtro por porcentaje BCV (comisiones en Bs/BCV vs en $) -----------------------


def _factura_credito_con_comision(session, vendedor, admin, porcentaje_bcv: Decimal | None):
    """Factura a credito (opcionalmente con porcentaje BCV) cuya unica linea genera una
    comision de 1.00. Devuelve la ComisionFactura."""
    producto = crear_producto(session, cantidad_unidad=50)
    crear_precio_producto(session, producto, "1.00")
    cliente = crear_cliente(session, limite_credito=Decimal("1000.00"))
    factura = VentaService.emitir_factura(
        session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "2.00"}],
        porcentaje_bcv=porcentaje_bcv,
    )
    detalle = session.query(FacturaDetalle).filter_by(id_factura=factura.id_factura).one()
    return session.query(ComisionFactura).filter_by(id_factura_detalle=detalle.id_factura_detalle).one()


def _dos_facturas_una_bcv_y_una_en_dolares(session):
    admin = crear_usuario_admin(session)
    vendedor = crear_vendedor(session)
    comision_bcv = _factura_credito_con_comision(session, vendedor, admin, Decimal("10"))
    comision_usd = _factura_credito_con_comision(session, vendedor, admin, None)
    return admin, vendedor, comision_bcv, comision_usd


def test_listar_comisiones_vendedor_sin_filtro_bcv_trae_todas(db_session):
    admin, vendedor, bcv, usd = _dos_facturas_una_bcv_y_una_en_dolares(db_session)

    comisiones = ComisionService.listar_comisiones_vendedor(
        db_session, vendedor.id_vendedor, id_usuario=admin.id_usuario
    )

    assert {c.id_comision for c in comisiones} == {bcv.id_comision, usd.id_comision}


def test_listar_comisiones_vendedor_solo_con_porcentaje_bcv(db_session):
    admin, vendedor, bcv, _usd = _dos_facturas_una_bcv_y_una_en_dolares(db_session)

    comisiones = ComisionService.listar_comisiones_vendedor(
        db_session, vendedor.id_vendedor, id_usuario=admin.id_usuario, solo_con_porcentaje_bcv=True
    )

    assert [c.id_comision for c in comisiones] == [bcv.id_comision]


def test_listar_comisiones_vendedor_solo_sin_porcentaje_bcv(db_session):
    admin, vendedor, _bcv, usd = _dos_facturas_una_bcv_y_una_en_dolares(db_session)

    comisiones = ComisionService.listar_comisiones_vendedor(
        db_session, vendedor.id_vendedor, id_usuario=admin.id_usuario, solo_sin_porcentaje_bcv=True
    )

    assert [c.id_comision for c in comisiones] == [usd.id_comision]


def test_listar_comisiones_vendedor_filtro_bcv_se_combina_con_estado_pago(db_session):
    """Las comisiones de credito nacen 'pendiente': con estado 'liberada' no queda ninguna,
    con o sin el filtro BCV."""
    admin, vendedor, bcv, _usd = _dos_facturas_una_bcv_y_una_en_dolares(db_session)

    pendientes_bcv = ComisionService.listar_comisiones_vendedor(
        db_session,
        vendedor.id_vendedor,
        estado_pago="pendiente",
        id_usuario=admin.id_usuario,
        solo_con_porcentaje_bcv=True,
    )
    liberadas_bcv = ComisionService.listar_comisiones_vendedor(
        db_session,
        vendedor.id_vendedor,
        estado_pago="liberada",
        id_usuario=admin.id_usuario,
        solo_con_porcentaje_bcv=True,
    )

    assert [c.id_comision for c in pendientes_bcv] == [bcv.id_comision]
    assert liberadas_bcv == []


def test_listar_comisiones_vendedor_filtro_bcv_no_incluye_comisiones_de_otro_vendedor(db_session):
    admin, vendedor, bcv, _usd = _dos_facturas_una_bcv_y_una_en_dolares(db_session)
    otro_vendedor = crear_vendedor(db_session)
    _factura_credito_con_comision(db_session, otro_vendedor, admin, Decimal("10"))

    comisiones = ComisionService.listar_comisiones_vendedor(
        db_session, vendedor.id_vendedor, id_usuario=admin.id_usuario, solo_con_porcentaje_bcv=True
    )

    assert [c.id_comision for c in comisiones] == [bcv.id_comision]


def test_listar_mis_comisiones_filtra_por_porcentaje_bcv(db_session):
    admin, vendedor, bcv, usd = _dos_facturas_una_bcv_y_una_en_dolares(db_session)
    admin.id_vendedor_usuario = vendedor.id_vendedor
    db_session.commit()

    todas = ComisionService.listar_mis_comisiones(db_session, admin.id_usuario)
    con_bcv = ComisionService.listar_mis_comisiones(db_session, admin.id_usuario, solo_con_porcentaje_bcv=True)
    sin_bcv = ComisionService.listar_mis_comisiones(db_session, admin.id_usuario, solo_sin_porcentaje_bcv=True)

    assert {c.id_comision for c in todas} == {bcv.id_comision, usd.id_comision}
    assert [c.id_comision for c in con_bcv] == [bcv.id_comision]
    assert [c.id_comision for c in sin_bcv] == [usd.id_comision]


# --- Articulo BCV: el porcentaje BCV no entra en su base de comision ----------------


def _comision_de_una_linea(session, porcentaje_bcv, **datos_producto):
    """Factura a credito de una linea (precio de lista 1.00 vendido a 2.00) y su comision."""
    admin = crear_usuario_admin(session)
    vendedor = crear_vendedor(session)
    producto = crear_producto(session, cantidad_unidad=50, **datos_producto)
    crear_precio_producto(session, producto, "1.00")
    cliente = crear_cliente(session, limite_credito=Decimal("1000.00"))
    factura = VentaService.emitir_factura(
        session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "2.00"}],
        porcentaje_bcv=porcentaje_bcv,
    )
    detalle = session.query(FacturaDetalle).filter_by(id_factura=factura.id_factura).one()
    return session.query(ComisionFactura).filter_by(id_factura_detalle=detalle.id_factura_detalle).one()


def test_comision_con_porcentaje_bcv_sube_la_base_del_articulo_normal(db_session):
    comision = _comision_de_una_linea(db_session, Decimal("10"))
    assert comision.monto_comision == Decimal("0.90")  # 2.00 - 1.00 * 1.10


def test_comision_de_articulo_bcv_no_lleva_el_porcentaje_en_la_base(db_session):
    comision = _comision_de_una_linea(db_session, Decimal("10"), articulo_bcv=True)
    assert comision.monto_comision == Decimal("1.00")  # 2.00 - 1.00, como sin porcentaje


def test_comision_de_articulo_bcv_sin_porcentaje_es_la_de_siempre(db_session):
    comision = _comision_de_una_linea(db_session, None, articulo_bcv=True)
    assert comision.monto_comision == Decimal("1.00")
