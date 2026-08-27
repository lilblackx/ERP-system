from decimal import Decimal

from app.services.historial_cliente import obtener_historial_cliente
from app.services.ventas import VentaService
from tests.factories import crear_cliente, crear_producto, crear_usuario_admin, crear_vendedor


def test_obtener_historial_cliente_dias_credito_no_cambia_retroactivamente(db_session):
    """Los dias de credito que muestra el historial para una factura ya emitida deben ser
    los que se aplicaron en ese momento (FacturaVenta.dias_credito_aplicados), no los
    configurados HOY en el cliente -- reportado como bug: cambiar los dias de credito del
    cliente hacia que el historial mostrara el valor nuevo para TODAS las facturas ya
    emitidas, como si el cambio fuera retroactivo (obtener_historial_cliente() leia
    factura.cliente.dias_credito en vez del snapshot de la factura)."""
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=10)
    cliente = crear_cliente(db_session, limite_credito=Decimal("1000.00"), dias_credito=10)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "50.00"}],
    )
    assert factura.dias_credito_aplicados == 10

    # El cliente cambia sus dias de credito configurados DESPUES de emitida la factura.
    cliente.dias_credito = 60
    db_session.commit()

    historial = obtener_historial_cliente(db_session, cliente.id_cliente)
    item = next(i for i in historial if i["id_factura"] == factura.id_factura)

    assert item["dias_credito"] == 10
