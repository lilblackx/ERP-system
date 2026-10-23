"""Historial del cliente con facturas de porcentaje BCV: el monto de la factura, su saldo y el
"SALDO PENDIENTE" total tienen que reflejar la deuda real (que vive en cuentas_por_cobrar_bcv)."""

from decimal import Decimal

from app.services.empresa import EmpresaService
from app.services.historial_cliente import (
    obtener_historial_cliente,
    obtener_saldo_total_pendiente,
)
from app.services.pagos_bcv import PagoBCVService
from app.services.ventas import VentaService
from tests.factories import (
    crear_caja,
    crear_cliente,
    crear_precio_producto,
    crear_producto,
    crear_usuario_admin,
    crear_vendedor,
)
from tests.services.test_pagos_bcv import _caja_abierta, _emitir_credito_bcv


def _factura(db_session, admin, cliente, precio, **extra):
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=100)
    crear_precio_producto(db_session, producto, precio)
    return VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": precio}],
        **extra,
    )


def test_el_saldo_pendiente_total_suma_las_facturas_bcv(db_session):
    admin = crear_usuario_admin(db_session)
    factura_bcv, cuenta_bcv, cliente = _emitir_credito_bcv(db_session, admin, precio="110.00", porcentaje="10")

    # Una factura normal del mismo cliente: el total debe sumar las dos deudas.
    _factura(db_session, admin, cliente, "50.00")

    assert cuenta_bcv.saldo_pendiente == Decimal("110.00")
    assert obtener_saldo_total_pendiente(db_session, cliente.id_cliente) == Decimal("160.00")
    del factura_bcv


def test_el_saldo_pendiente_total_baja_con_los_abonos_bcv(db_session):
    admin = crear_usuario_admin(db_session)
    _factura_bcv, cuenta, cliente = _emitir_credito_bcv(db_session, admin, precio="100.00", porcentaje="10")
    caja = _caja_abierta(db_session, admin)

    PagoBCVService.registrar_pago_cobro_bcv(
        db_session,
        id_cuenta_por_cobrar=cuenta.id_cuenta_por_cobrar,
        monto=Decimal("40.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    assert obtener_saldo_total_pendiente(db_session, cliente.id_cliente) == Decimal("60.00")


def test_la_factura_bcv_muestra_su_monto_y_su_saldo_en_el_historial(db_session):
    admin = crear_usuario_admin(db_session)
    factura, cuenta, cliente = _emitir_credito_bcv(db_session, admin, precio="110.00", porcentaje="10")

    (fila,) = [
        h for h in obtener_historial_cliente(db_session, cliente.id_cliente) if h["tipo_transaccion"] == "factura"
    ]

    assert fila["numero_factura"] == factura.numero_factura
    assert fila["monto"] == Decimal("110.00")
    assert fila["saldo_corrido"] == cuenta.saldo_pendiente == Decimal("110.00")


def test_el_monto_de_la_factura_en_el_historial_incluye_iva_y_descuento(db_session):
    """Antes mostraba solo el subtotal de las lineas: con IVA el monto no cuadraba con el saldo."""
    admin = crear_usuario_admin(db_session)
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
    cliente = crear_cliente(db_session, limite_credito=Decimal("1000.00"))
    _factura(db_session, admin, cliente, "100.00")

    (fila,) = [
        h for h in obtener_historial_cliente(db_session, cliente.id_cliente) if h["tipo_transaccion"] == "factura"
    ]

    assert fila["monto"] == Decimal("116.00")
    assert fila["saldo_corrido"] == Decimal("116.00")


def test_factura_bcv_de_contado_aparece_pagada_en_el_historial(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=100)
    crear_precio_producto(db_session, producto, "110.00")
    cliente = crear_cliente(db_session)
    caja = crear_caja(db_session)
    from app.services.tesoreria import CajaService

    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)
    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=[
            {
                "metodo_pago": "efectivo",
                "moneda": "USD",
                "monto_moneda_origen": Decimal("110.00"),
                "id_caja": caja.id_caja,
                "id_cuenta_bancaria": None,
                "referencia": None,
            }
        ],
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "110.00"}],
        porcentaje_bcv=Decimal("10"),
    )

    historial = obtener_historial_cliente(db_session, cliente.id_cliente)
    (factura,) = [h for h in historial if h["tipo_transaccion"] == "factura"]
    pagos = [h for h in historial if h["tipo_transaccion"] == "pago"]

    assert factura["monto"] == Decimal("110.00")
    assert factura["saldo_corrido"] == Decimal("0.00")
    assert [p["monto"] for p in pagos] == [Decimal("-110.00")]
    assert obtener_saldo_total_pendiente(db_session, cliente.id_cliente) == Decimal("0.00")
