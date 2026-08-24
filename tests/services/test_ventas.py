from decimal import Decimal

import pytest

from app.db.models import (
    CajaMovimiento,
    ComisionFactura,
    CuentaPorCobrar,
    FacturaDetalle,
    NotaCreditoCliente,
    PagoCobro,
)
from app.services.empresa import EmpresaService
from app.services.pagos import PagoService
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import CajaService
from app.services.ventas import VentaService
from tests.factories import (
    crear_caja,
    crear_cliente,
    crear_precio_producto,
    crear_producto,
    crear_usuario_admin,
    crear_vendedor,
)


def test_emitir_factura_contado_descuenta_stock_y_calcula_total(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 5, "precio_unitario": "20.00"}],
    )

    db_session.refresh(producto)
    assert producto.cantidad_unidad == Decimal("45.00")
    assert factura.total_venta == Decimal("100.00")


def test_emitir_factura_sin_usuario_autorizado_falla(db_session):
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    with pytest.raises(PermisoDenegadoError):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=None,
            id_vendedor=None,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 5, "precio_unitario": "20.00"}],
        )


def test_emitir_factura_contado_no_abre_cuenta_por_cobrar(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )

    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).first()
    assert cxc is None


def test_emitir_factura_credito_abre_cuenta_por_cobrar(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, limite_credito=1000)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "30.00"}],
    )

    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).first()
    assert cxc is not None
    assert cxc.saldo_pendiente == Decimal("60.00")
    assert cxc.estado == "pendiente"


def test_emitir_factura_credito_excede_limite(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, limite_credito=50)

    with pytest.raises(ValueError, match="limite de credito"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "30.00"}],
        )


def test_emitir_factura_credito_acumula_deuda_de_facturas_previas(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, limite_credito=100)

    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "30.00"}],
    )

    with pytest.raises(ValueError, match="limite de credito"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "30.00"}],
        )


def test_emitir_factura_stock_insuficiente(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=3)
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="Stock insuficiente"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 10, "precio_unitario": "20.00"}],
        )

    db_session.refresh(producto)
    assert producto.cantidad_unidad == Decimal("3.00")


def test_emitir_factura_cliente_inactivo_falla(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, estado_cliente="INACTIVO")

    with pytest.raises(ValueError, match="inactivo"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=None,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 5, "precio_unitario": "20.00"}],
        )


def test_emitir_factura_vendedor_inactivo_falla(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)
    vendedor = crear_vendedor(db_session, estado_vendedor="INACTIVO")

    with pytest.raises(ValueError, match="inactivo"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 5, "precio_unitario": "20.00"}],
        )


def test_emitir_factura_vendedor_inexistente_falla(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="Vendedor no encontrado"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=999999,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 5, "precio_unitario": "20.00"}],
        )


def test_emitir_factura_producto_inactivo_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50, estado_producto="INACTIVO")
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="inactivo"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 5, "precio_unitario": "20.00"}],
        )


def test_emitir_factura_agrupa_items_repetidos_para_validar_stock(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=5)
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="Stock insuficiente"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            items=[
                {"id_producto": producto.id_producto, "cantidad": 3, "precio_unitario": "20.00"},
                {"id_producto": producto.id_producto, "cantidad": 3, "precio_unitario": "20.00"},
            ],
        )


def test_emitir_factura_sin_items(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session)
    with pytest.raises(ValueError, match="al menos un item"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=None,
            condicion_pago="contado",
            items=[],
        )


def test_emitir_factura_condicion_pago_invalida(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session)
    cliente = crear_cliente(db_session)
    with pytest.raises(ValueError, match="condicion_pago"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="otra",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
        )


def test_emitir_factura_cliente_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    with pytest.raises(ValueError, match="Cliente no encontrado"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=999999,
            id_usuario=admin.id_usuario,
            id_vendedor=None,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
        )


def test_anular_factura_contado_repone_stock(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 5, "precio_unitario": "20.00"}],
    )

    VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="Error de carga")

    db_session.refresh(factura)
    db_session.refresh(producto)
    assert factura.estado_factura == "ANULADA"
    assert producto.cantidad_unidad == Decimal("50.00")  # se repone
    assert factura.total_venta == Decimal("0.00")
    assert db_session.query(FacturaDetalle).filter_by(id_factura=factura.id_factura).count() == 0


def test_anular_factura_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)
    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 5, "precio_unitario": "20.00"}],
    )

    with pytest.raises(PermisoDenegadoError):
        VentaService.anular_factura(db_session, factura.id_factura, id_usuario=None, motivo="Error de carga")


def test_anular_factura_credito_repone_stock_y_cierra_cxc(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, limite_credito=1000)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 3, "precio_unitario": "20.00"}],
    )
    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()

    VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="Error de carga")

    db_session.refresh(producto)
    assert producto.cantidad_unidad == Decimal("50.00")
    assert db_session.get(CuentaPorCobrar, cxc.id_cuenta_por_cobrar) is None

    # anular una factura credito ya cerrada no debe volver a abrir cupo con el cliente
    otra = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "999.00"}],
    )
    assert otra.total_venta == Decimal("999.00")


def test_anular_factura_con_pago_aplicado_genera_nota_de_credito(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, limite_credito=1000)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "20.00"}],
    )
    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()
    pago = PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("10.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )
    id_pago_cobro = pago.id_pago_cobro

    VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="Error de carga")

    db_session.refresh(factura)
    db_session.refresh(producto)
    assert factura.estado_factura == "ANULADA"
    assert producto.cantidad_unidad == Decimal("50.00")  # stock repuesto

    # la cuenta por cobrar NO se borra (se conserva el vinculo con el pago ya aplicado):
    # queda anulada, sin saldo pendiente
    db_session.refresh(cxc)
    assert cxc.estado == "anulada"
    assert cxc.saldo_pendiente == Decimal("0.00")

    # el pago original y su movimiento de caja quedan intactos, sin revertir
    assert db_session.query(PagoCobro).filter_by(id_pago_cobro=id_pago_cobro).one().monto == Decimal("10.00")
    assert db_session.query(CajaMovimiento).filter_by(id_pago_cobro=id_pago_cobro).first() is not None

    # y la plata ya cobrada queda como nota de credito a favor del cliente
    nota = db_session.query(NotaCreditoCliente).filter_by(id_factura_origen=factura.id_factura).one()
    assert nota.id_cliente == cliente.id_cliente
    assert nota.numero_nota_credito.startswith("NC-")
    assert nota.monto == Decimal("10.00")
    assert nota.saldo_disponible == Decimal("10.00")
    assert nota.estado == "disponible"

    # no revive la deuda: emitir_factura no cuenta la cxc anulada como deuda vigente
    otra = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "999.00"}],
    )
    assert otra.total_venta == Decimal("999.00")


def test_anular_factura_con_comision_pendiente_borra_comision_y_anula(db_session):
    """C14: una comision 'pendiente' (el vendedor todavia no cobro nada) no bloquea la
    anulacion -- se borra junto con el resto de la reversion."""
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "20.00"}],
    )
    detalle = db_session.query(FacturaDetalle).filter_by(id_factura=factura.id_factura).first()
    id_factura_detalle = detalle.id_factura_detalle  # capturado antes de que anular_factura borre la fila
    db_session.add(
        ComisionFactura(
            id_factura_detalle=id_factura_detalle,
            id_vendedor=vendedor.id_vendedor,
            monto_venta_comision=Decimal("40.00"),
            monto_comision=Decimal("4.00"),
            estado_pago="pendiente",
        )
    )
    db_session.commit()

    VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="Error de carga")

    db_session.refresh(factura)
    db_session.refresh(producto)
    assert factura.estado_factura == "ANULADA"
    assert producto.cantidad_unidad == Decimal("50.00")  # stock repuesto
    assert db_session.query(ComisionFactura).filter_by(id_factura_detalle=id_factura_detalle).first() is None


def test_anular_factura_con_comision_pagada_bloqueada(db_session):
    """Si la comision ya se pago (el vendedor ya cobro ese dinero real), la anulacion
    sigue bloqueada -- no hay forma de revertir un pago ya hecho."""
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "20.00"}],
    )
    detalle = db_session.query(FacturaDetalle).filter_by(id_factura=factura.id_factura).first()
    db_session.add(
        ComisionFactura(
            id_factura_detalle=detalle.id_factura_detalle,
            id_vendedor=vendedor.id_vendedor,
            monto_venta_comision=Decimal("40.00"),
            monto_comision=Decimal("4.00"),
            estado_pago="pagada",
        )
    )
    db_session.commit()

    with pytest.raises(ValueError, match="comisiones ya pagadas"):
        VentaService.anular_factura(
            db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="Error de carga"
        )

    db_session.refresh(factura)
    db_session.refresh(producto)
    assert factura.estado_factura != "ANULADA"
    assert producto.cantidad_unidad == Decimal("48.00")  # stock intacto, no se repuso


# --- ComisionService.calcular_comisiones_factura (llamada desde emitir_factura, C14) ---


def test_emitir_factura_con_vendedor_calcula_comision_sobre_diferencia(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "1.00")
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 3, "precio_unitario": "2.00"}],
    )

    detalle = db_session.query(FacturaDetalle).filter_by(id_factura=factura.id_factura).first()
    comision = db_session.query(ComisionFactura).filter_by(id_factura_detalle=detalle.id_factura_detalle).one()
    assert comision.id_vendedor == vendedor.id_vendedor
    assert comision.monto_base_comision == Decimal("3.00")  # 1.00 (lista) * 3
    assert comision.monto_venta_comision == Decimal("6.00")  # 2.00 (real) * 3
    assert comision.monto_comision == Decimal("3.00")  # diferencia
    assert comision.estado_pago == "pendiente"


def test_emitir_factura_precio_igual_al_de_lista_comision_cero(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "5.00")
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "5.00"}],
    )

    detalle = db_session.query(FacturaDetalle).filter_by(id_factura=factura.id_factura).first()
    comision = db_session.query(ComisionFactura).filter_by(id_factura_detalle=detalle.id_factura_detalle).one()
    assert comision.monto_comision == Decimal("0.00")  # nunca negativa


def test_emitir_factura_precio_menor_al_de_lista_requiere_autorizacion_y_comision_cero(db_session):
    """Vender por debajo del precio de lista es un descuento implicito (hallazgo #4/#5
    del audit de facturacion): requiere motivo + autorizador con permiso
    'descuentos'/'crear', igual que un monto_descuento explicito."""
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "5.00")
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "3.00"}],
        motivo_descuento="Cliente frecuente",
        id_autorizador_descuento=admin.id_usuario,
    )

    assert factura.autorizado_por_descuento == admin.id_usuario
    assert factura.motivo_descuento == "Cliente frecuente"
    detalle = db_session.query(FacturaDetalle).filter_by(id_factura=factura.id_factura).first()
    comision = db_session.query(ComisionFactura).filter_by(id_factura_detalle=detalle.id_factura_detalle).one()
    assert comision.monto_comision == Decimal("0.00")  # nunca negativa


def test_emitir_factura_precio_menor_al_de_lista_sin_autorizacion_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "5.00")
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="requiere un motivo"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "3.00"}],
        )

    with pytest.raises(ValueError, match="requiere autorizacion de un supervisor"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "3.00"}],
            motivo_descuento="Cliente frecuente",
        )


def test_emitir_factura_precio_menor_al_de_lista_autorizador_sin_permiso_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "5.00")
    cliente = crear_cliente(db_session)

    with pytest.raises(PermisoDenegadoError):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "3.00"}],
            motivo_descuento="Cliente frecuente",
            id_autorizador_descuento=999999,
        )


def test_emitir_factura_sin_precio_de_lista_no_genera_comision(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)  # sin crear_precio_producto
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )

    detalle = db_session.query(FacturaDetalle).filter_by(id_factura=factura.id_factura).first()
    assert db_session.query(ComisionFactura).filter_by(id_factura_detalle=detalle.id_factura_detalle).first() is None


def test_emitir_factura_sin_vendedor_falla(db_session):
    """El vendedor es obligatorio en toda factura desde
    migrations/0017_vendedor_obligatorio_factura.sql -- sin el, ComisionService no
    tendria a quien acreditarle la venta."""
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="vendedor es obligatorio"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=None,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
        )


def test_anular_factura_sin_motivo(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session)
    cliente = crear_cliente(db_session)
    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )

    with pytest.raises(ValueError, match="motivo"):
        VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="")


def test_anular_factura_ya_anulada(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session)
    cliente = crear_cliente(db_session)
    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )
    VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="Motivo 1")

    with pytest.raises(ValueError, match="ya esta anulada"):
        VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="Motivo 2")


def test_listar_facturas_filtra_por_cliente(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente_a = crear_cliente(db_session)
    cliente_b = crear_cliente(db_session)

    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente_a.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )
    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente_b.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )

    resultado = VentaService.listar_facturas(db_session, id_cliente=cliente_a.id_cliente, id_usuario=admin.id_usuario)

    assert resultado["total"] == 1
    assert resultado["items"][0].id_cliente_factura == cliente_a.id_cliente


def test_listar_facturas_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        VentaService.listar_facturas(db_session)


def test_listar_facturas_filtra_por_numero_parcial(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )

    resultado = VentaService.listar_facturas(
        db_session, numero_factura=factura.numero_factura[-4:], id_usuario=admin.id_usuario
    )

    assert resultado["total"] == 1
    assert resultado["items"][0].numero_factura == factura.numero_factura


def test_obtener_factura_incluye_detalles(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "20.00"}],
    )

    resultado = VentaService.obtener_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario)

    assert resultado["factura"].id_factura == factura.id_factura
    assert resultado["factura"].cliente.id_cliente == cliente.id_cliente
    assert len(resultado["detalles"]) == 1
    assert resultado["detalles"][0].producto.id_producto == producto.id_producto
    assert resultado["detalles"][0].cantidad_producto == Decimal("2.00")


def test_obtener_factura_inexistente_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Factura no encontrada"):
        VentaService.obtener_factura(db_session, 999999, id_usuario=admin.id_usuario)


def test_obtener_factura_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        VentaService.obtener_factura(db_session, 1)


# --- numero_control + IVA (facturacion fiscal, migrations/0018-0019) ------------------


def test_emitir_factura_numero_control_correlativo_unico(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    primera = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )
    segunda = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )

    assert primera.numero_control.startswith("00-")
    assert primera.numero_control != segunda.numero_control
    assert primera.numero_control == f"00-{primera.id_factura:08d}"


def test_emitir_factura_sin_config_empresa_no_calcula_iva(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )

    assert factura.iva_aplicado is False
    assert factura.monto_iva == Decimal("0.00")


def test_emitir_factura_con_iva_activo_calcula_monto_y_snapshot(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)
    EmpresaService.guardar_configuracion(
        db_session,
        rif=None,
        razon_social=None,
        direccion=None,
        telefono=None,
        iva_activo=True,
        iva_porcentaje="16.00",
        modificado_por=admin.id_usuario,
    )

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
    )

    assert factura.iva_aplicado is True
    assert factura.porcentaje_iva_aplicado == Decimal("16.00")
    assert factura.monto_iva == Decimal("16.00")
    assert factura.total_venta == Decimal("100.00")  # total_venta sigue siendo el subtotal


def test_emitir_factura_con_iva_desactivado_no_calcula_iva_aunque_haya_config(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)
    EmpresaService.guardar_configuracion(
        db_session,
        rif=None,
        razon_social=None,
        direccion=None,
        telefono=None,
        iva_activo=False,
        iva_porcentaje="16.00",
        modificado_por=admin.id_usuario,
    )

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
    )

    assert factura.iva_aplicado is False
    assert factura.monto_iva == Decimal("0.00")


def test_emitir_factura_credito_con_iva_suma_iva_a_cuenta_por_cobrar(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, limite_credito=1000)
    EmpresaService.guardar_configuracion(
        db_session,
        rif=None,
        razon_social=None,
        direccion=None,
        telefono=None,
        iva_activo=True,
        iva_porcentaje="16.00",
        modificado_por=admin.id_usuario,
    )

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
    )

    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()
    assert cxc.saldo_pendiente == Decimal("116.00")  # 100 + 16% IVA


def test_emitir_factura_credito_con_iva_valida_limite_credito_incluyendo_iva(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    # limite alcanza para el subtotal (100) pero no para subtotal+IVA (116)
    cliente = crear_cliente(db_session, limite_credito=Decimal("110.00"))
    EmpresaService.guardar_configuracion(
        db_session,
        rif=None,
        razon_social=None,
        direccion=None,
        telefono=None,
        iva_activo=True,
        iva_porcentaje="16.00",
        modificado_por=admin.id_usuario,
    )

    with pytest.raises(ValueError, match="limite de credito"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
        )


# --- monto_descuento de factura (descuento manual, requiere autorizacion) -------------


def test_emitir_factura_monto_descuento_sin_autorizacion_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="requiere un motivo"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
            monto_descuento="10.00",
        )


def test_emitir_factura_monto_descuento_autorizado_resta_del_total(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
        monto_descuento="10.00",
        motivo_descuento="Cliente frecuente",
        id_autorizador_descuento=admin.id_usuario,
    )

    assert factura.monto_descuento == Decimal("10.00")
    assert factura.autorizado_por_descuento == admin.id_usuario
    assert factura.total_venta == Decimal("100.00")  # subtotal crudo, sin tocar (triggers)


def test_emitir_factura_monto_descuento_mayor_al_subtotal_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="no puede ser mayor al subtotal"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
            monto_descuento="150.00",
            motivo_descuento="x",
            id_autorizador_descuento=admin.id_usuario,
        )


def test_emitir_factura_monto_descuento_negativo_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="no puede ser negativo"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
            monto_descuento="-1.00",
        )


def test_emitir_factura_credito_con_descuento_y_iva_ajusta_cuenta_por_cobrar(db_session):
    """subtotal 100 - descuento 20 = 80; +16% IVA sobre 80 = 12.80; total a cobrar 92.80."""
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, limite_credito=1000)
    EmpresaService.guardar_configuracion(
        db_session,
        rif=None,
        razon_social=None,
        direccion=None,
        telefono=None,
        iva_activo=True,
        iva_porcentaje="16.00",
        modificado_por=admin.id_usuario,
    )

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
        monto_descuento="20.00",
        motivo_descuento="Cliente frecuente",
        id_autorizador_descuento=admin.id_usuario,
    )

    assert factura.monto_iva == Decimal("12.80")
    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()
    assert cxc.saldo_pendiente == Decimal("92.80")


# --- consultar_limite_disponible (bloqueo visual proactivo en factura_form_dialog) ----


def test_consultar_limite_disponible_sin_deuda(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session, limite_credito=Decimal("500.00"))

    resultado = VentaService.consultar_limite_disponible(db_session, cliente.id_cliente, id_usuario=admin.id_usuario)

    assert resultado["limite_credito"] == Decimal("500.00")
    assert resultado["deuda_actual"] == Decimal("0.00")
    assert resultado["disponible"] == Decimal("500.00")


def test_consultar_limite_disponible_descuenta_deuda_vigente(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, limite_credito=Decimal("500.00"))

    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "120.00"}],
    )

    resultado = VentaService.consultar_limite_disponible(db_session, cliente.id_cliente, id_usuario=admin.id_usuario)

    assert resultado["deuda_actual"] == Decimal("120.00")
    assert resultado["disponible"] == Decimal("380.00")


def test_consultar_limite_disponible_cliente_inexistente_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Cliente no encontrado"):
        VentaService.consultar_limite_disponible(db_session, 999999, id_usuario=admin.id_usuario)


def test_consultar_limite_disponible_sin_usuario_autorizado_falla(db_session):
    cliente = crear_cliente(db_session)
    with pytest.raises(PermisoDenegadoError):
        VentaService.consultar_limite_disponible(db_session, cliente.id_cliente)
