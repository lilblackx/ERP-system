from decimal import Decimal

import pytest

from app.db.models import (
    CajaMovimiento,
    ComisionFactura,
    CuentaPorCobrar,
    FacturaDetalle,
    FacturaVenta,
    NotaCreditoCliente,
    PagoCobro,
)
from app.services.pagos import PagoService
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import CajaService
from app.services.ventas import VentaService
from tests.factories import crear_caja, crear_cliente, crear_producto, crear_usuario_admin, crear_vendedor


def test_emitir_factura_contado_descuenta_stock_y_calcula_total(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=None,
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
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=None,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )

    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).first()
    assert cxc is None


def test_emitir_factura_credito_abre_cuenta_por_cobrar(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, limite_credito=1000)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=None,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "30.00"}],
    )

    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).first()
    assert cxc is not None
    assert cxc.saldo_pendiente == Decimal("60.00")
    assert cxc.estado == "pendiente"


def test_emitir_factura_credito_excede_limite(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, limite_credito=50)

    with pytest.raises(ValueError, match="limite de credito"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=None,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "30.00"}],
        )


def test_emitir_factura_credito_acumula_deuda_de_facturas_previas(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, limite_credito=100)

    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=None,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "30.00"}],
    )

    with pytest.raises(ValueError, match="limite de credito"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=None,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "30.00"}],
        )


def test_emitir_factura_stock_insuficiente(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=3)
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="Stock insuficiente"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=None,
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
    producto = crear_producto(db_session, cantidad_unidad=50, estado_producto="INACTIVO")
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="inactivo"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=None,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 5, "precio_unitario": "20.00"}],
        )


def test_emitir_factura_agrupa_items_repetidos_para_validar_stock(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=5)
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="Stock insuficiente"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=None,
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
    producto = crear_producto(db_session)
    cliente = crear_cliente(db_session)
    with pytest.raises(ValueError, match="condicion_pago"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=None,
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
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=None,
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
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)
    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=None,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 5, "precio_unitario": "20.00"}],
    )

    with pytest.raises(PermisoDenegadoError):
        VentaService.anular_factura(db_session, factura.id_factura, id_usuario=None, motivo="Error de carga")


def test_anular_factura_credito_repone_stock_y_cierra_cxc(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, limite_credito=1000)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=None,
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
        id_vendedor=None,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "999.00"}],
    )
    assert otra.total_venta == Decimal("999.00")


def test_anular_factura_con_pago_aplicado_genera_nota_de_credito(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, limite_credito=1000)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=None,
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
        id_vendedor=None,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "999.00"}],
    )
    assert otra.total_venta == Decimal("999.00")


def test_anular_factura_con_comision_calculada_bloqueada(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=None,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "20.00"}],
    )
    detalle = db_session.query(FacturaDetalle).filter_by(id_factura=factura.id_factura).first()
    db_session.add(ComisionFactura(id_factura_detalle=detalle.id_factura_detalle, monto_venta_comision=Decimal("4.00")))
    db_session.commit()

    with pytest.raises(ValueError, match="comisiones calculadas"):
        VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="Error de carga")

    db_session.refresh(factura)
    db_session.refresh(producto)
    assert factura.estado_factura != "ANULADA"
    assert producto.cantidad_unidad == Decimal("48.00")  # stock intacto, no se repuso


def test_anular_factura_sin_motivo(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    cliente = crear_cliente(db_session)
    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=None,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )

    with pytest.raises(ValueError, match="motivo"):
        VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="")


def test_anular_factura_ya_anulada(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    cliente = crear_cliente(db_session)
    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=None,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )
    VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="Motivo 1")

    with pytest.raises(ValueError, match="ya esta anulada"):
        VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="Motivo 2")


def test_listar_facturas_filtra_por_cliente(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente_a = crear_cliente(db_session)
    cliente_b = crear_cliente(db_session)

    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente_a.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=None,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )
    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente_b.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=None,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )

    resultado = VentaService.listar_facturas(db_session, id_cliente=cliente_a.id_cliente, id_usuario=admin.id_usuario)

    assert resultado["total"] == 1
    assert resultado["items"][0].id_cliente_factura == cliente_a.id_cliente


def test_listar_facturas_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        VentaService.listar_facturas(db_session)
