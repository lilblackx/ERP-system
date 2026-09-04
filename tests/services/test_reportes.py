from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest

from app.db.models import (
    BancoMovimiento,
    Caja,
    ComisionFactura,
    Compra,
    CuentaPorCobrar,
    CuentaPorPagar,
    FacturaDetalle,
)
from app.services.banco_movimientos import BancoMovimientoService
from app.services.comisiones import PagoComisionService
from app.services.compra_oc import CompraOCService
from app.services.compras import CompraService
from app.services.inventario import PrecioService
from app.services.nota_recepcion import NotaRecepcionService
from app.services.otros_movimientos import OtrosMovimientosService
from app.services.pagos import PagoService
from app.services.permisos import PermisoDenegadoError
from app.services.reportes import ReporteService
from app.services.tesoreria import CajaService
from app.services.ventas import VentaService
from tests.factories import (
    crear_banco,
    crear_caja,
    crear_categoria,
    crear_cliente,
    crear_cuenta_bancaria,
    crear_precio_producto,
    crear_producto,
    crear_proveedor,
    crear_ruta,
    crear_usuario_admin,
    crear_vendedor,
    pago_contado,
)

# --- aging_cuentas_por_cobrar ------------------------------------------------------


def _factura_a_credito(session, admin, cliente, total, fecha_vencimiento):
    vendedor = crear_vendedor(session)
    producto = crear_producto(session, cantidad_unidad=1000)
    return VentaService.emitir_factura(
        session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": str(total)}],
        fecha_vencimiento=fecha_vencimiento,
    )


def _factura_contado(session, admin, cliente, vendedor, producto, cantidad, precio_unitario):
    return VentaService.emitir_factura(
        session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(session),
        items=[{"id_producto": producto.id_producto, "cantidad": cantidad, "precio_unitario": precio_unitario}],
    )


def _pago_efectivo(id_caja, monto) -> dict:
    return {
        "metodo_pago": "efectivo",
        "moneda": "USD",
        "monto_moneda_origen": monto,
        "id_caja": id_caja,
        "id_cuenta_bancaria": None,
        "referencia": None,
    }


def _crear_comision(session, admin, vendedor, precio_lista, precio_venta, cantidad):
    """Una linea de venta con precio_venta > precio_lista genera comision (max(0,
    monto_venta - monto_base) en ComisionFactura, calculada automaticamente por
    VentaService.emitir_factura -- ver tests/services/test_comisiones.py."""
    producto = crear_producto(session, cantidad_unidad=100)
    crear_precio_producto(session, producto, precio_lista)
    cliente = crear_cliente(session)
    factura = VentaService.emitir_factura(
        session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": cantidad, "precio_unitario": str(precio_venta)}],
        pagos=pago_contado(session),
    )
    id_factura_detalle = (
        session.query(FacturaDetalle.id_factura_detalle).filter_by(id_factura=factura.id_factura).scalar()
    )
    return session.query(ComisionFactura).filter_by(id_factura_detalle=id_factura_detalle).one()


def _compra_a_credito(session, admin, proveedor, total, fecha_vencimiento):
    producto = crear_producto(session)
    return CompraService.registrar_compra(
        session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": str(total)}],
        fecha_vencimiento=fecha_vencimiento,
    )


def _compra_contado(session, admin, proveedor, producto, cantidad, costo_unitario, caja):
    monto = Decimal(str(cantidad)) * Decimal(costo_unitario)
    return CompraService.registrar_compra(
        session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": cantidad, "costo_unitario": costo_unitario}],
        pago=_pago_efectivo(caja.id_caja, monto),
    )


def _oc_recibida(session, admin, proveedor, producto, cantidad, precio_unitario, fecha_estimada_entrega=None):
    oc = CompraOCService.crear_oc(
        session,
        id_proveedor=proveedor.id_proveedor,
        items=[
            {
                "id_producto": producto.id_producto,
                "cantidad_solicitada": cantidad,
                "precio_unitario": precio_unitario,
            }
        ],
        id_usuario=admin.id_usuario,
        fecha_estimada_entrega=fecha_estimada_entrega,
    )
    NotaRecepcionService.crear_nota_recepcion(
        session,
        id_oc=oc.id_oc,
        items=[{"id_oc_detalle": oc.detalles[0].id_detalle, "cantidad_recibida": cantidad}],
        id_usuario=admin.id_usuario,
    )
    return oc


def test_aging_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.aging_cuentas_por_cobrar(db_session, id_usuario=None)


def test_aging_orden_invalido_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="orden invalido"):
        ReporteService.aging_cuentas_por_cobrar(db_session, id_usuario=admin.id_usuario, orden="columna_inventada")


def test_aging_sin_cuentas_abiertas(db_session):
    admin = crear_usuario_admin(db_session)
    resultado = ReporteService.aging_cuentas_por_cobrar(db_session, id_usuario=admin.id_usuario)
    assert resultado["filas"] == []
    assert resultado["total_general"] == Decimal("0.00")


def test_aging_clasifica_por_bucket_segun_dias_vencidos(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    hoy = date.today()

    _factura_a_credito(db_session, admin, cliente, "80.00", hoy + timedelta(days=5))  # vigente
    _factura_a_credito(db_session, admin, cliente, "50.00", hoy - timedelta(days=10))  # 1-30
    _factura_a_credito(db_session, admin, cliente, "30.00", hoy - timedelta(days=45))  # 31-60

    resultado = ReporteService.aging_cuentas_por_cobrar(db_session, id_usuario=admin.id_usuario, fecha_corte=hoy)

    buckets = {f["bucket"] for f in resultado["filas"]}
    assert buckets == {"vigente", "1-30", "31-60"}
    assert resultado["totales_por_bucket"]["1-30"] == Decimal("50.00")
    assert resultado["totales_por_bucket"]["31-60"] == Decimal("30.00")
    assert resultado["total_general"] == Decimal("160.00")


def test_aging_excluye_cuentas_pagadas_por_completo(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    factura = _factura_a_credito(db_session, admin, cliente, "40.00", date.today() - timedelta(days=5))
    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()

    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)
    PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto="40.00",
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    resultado = ReporteService.aging_cuentas_por_cobrar(db_session, id_usuario=admin.id_usuario)
    assert resultado["filas"] == []


def test_aging_filtra_por_cliente(db_session):
    admin = crear_usuario_admin(db_session)
    cliente_a = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    cliente_b = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    _factura_a_credito(db_session, admin, cliente_a, "70.00", date.today() - timedelta(days=5))
    _factura_a_credito(db_session, admin, cliente_b, "20.00", date.today() - timedelta(days=5))

    resultado = ReporteService.aging_cuentas_por_cobrar(
        db_session, id_usuario=admin.id_usuario, id_cliente=cliente_a.id_cliente
    )

    assert len(resultado["filas"]) == 1
    assert resultado["filas"][0]["cliente"] == cliente_a.nombre_razon_social


def test_aging_orden_por_saldo_pendiente(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    vencimiento = date.today() - timedelta(days=5)
    _factura_a_credito(db_session, admin, cliente, "90.00", vencimiento)
    _factura_a_credito(db_session, admin, cliente, "10.00", vencimiento)

    resultado = ReporteService.aging_cuentas_por_cobrar(
        db_session, id_usuario=admin.id_usuario, orden="saldo_pendiente"
    )

    saldos = [f["saldo_pendiente"] for f in resultado["filas"]]
    assert saldos == sorted(saldos)


# --- ventas_por_periodo --------------------------------------------------------------


def test_ventas_por_periodo_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.ventas_por_periodo(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_ventas_por_periodo_agrupacion_invalida_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="agrupacion invalida"):
        ReporteService.ventas_por_periodo(
            db_session,
            id_usuario=admin.id_usuario,
            fecha_desde=date.today(),
            fecha_hasta=date.today(),
            agrupacion="semana",
        )


def test_ventas_por_periodo_rango_invertido_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="fecha_desde"):
        ReporteService.ventas_por_periodo(
            db_session,
            id_usuario=admin.id_usuario,
            fecha_desde=date.today(),
            fecha_hasta=date.today() - timedelta(days=1),
        )


def test_ventas_por_periodo_agrupa_por_dia_y_excluye_anuladas(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=100)
    cliente = crear_cliente(db_session)

    _factura_contado(db_session, admin, cliente, vendedor, producto, 2, "10.00")  # 20.00
    _factura_contado(db_session, admin, cliente, vendedor, producto, 1, "5.00")  # 5.00
    anulada = _factura_contado(db_session, admin, cliente, vendedor, producto, 1, "999.00")
    VentaService.anular_factura(db_session, anulada.id_factura, id_usuario=admin.id_usuario, motivo="prueba")

    resultado = ReporteService.ventas_por_periodo(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today(), agrupacion="dia"
    )

    assert len(resultado["filas"]) == 1
    assert resultado["filas"][0]["cantidad_facturas"] == 2
    assert resultado["filas"][0]["total"] == Decimal("25.00")
    assert resultado["total_facturas"] == 2
    assert resultado["total_general"] == Decimal("25.00")


# --- ventas_por_cliente ---------------------------------------------------------------


def test_ventas_por_cliente_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.ventas_por_cliente(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_ventas_por_cliente_arma_ranking_descendente(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=100)
    cliente_a = crear_cliente(db_session, nombre_razon_social="Cliente A")
    cliente_b = crear_cliente(db_session, nombre_razon_social="Cliente B")

    _factura_contado(db_session, admin, cliente_a, vendedor, producto, 1, "10.00")
    _factura_contado(db_session, admin, cliente_b, vendedor, producto, 1, "50.00")

    resultado = ReporteService.ventas_por_cliente(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )

    assert [f["cliente"] for f in resultado["filas"]] == ["Cliente B", "Cliente A"]
    assert resultado["total_general"] == Decimal("60.00")


# --- ventas_por_vendedor --------------------------------------------------------------


def test_ventas_por_vendedor_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.ventas_por_vendedor(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_ventas_por_vendedor_agrupa_correctamente(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor_a = crear_vendedor(db_session, nombre_vendedor="Vendedor A")
    vendedor_b = crear_vendedor(db_session, nombre_vendedor="Vendedor B")
    producto = crear_producto(db_session, cantidad_unidad=100)
    cliente = crear_cliente(db_session)

    _factura_contado(db_session, admin, cliente, vendedor_a, producto, 1, "10.00")
    _factura_contado(db_session, admin, cliente, vendedor_a, producto, 1, "15.00")
    _factura_contado(db_session, admin, cliente, vendedor_b, producto, 1, "5.00")

    resultado = ReporteService.ventas_por_vendedor(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )

    por_vendedor = {f["vendedor"]: f for f in resultado["filas"]}
    assert por_vendedor["Vendedor A"]["cantidad_facturas"] == 2
    assert por_vendedor["Vendedor A"]["total"] == Decimal("25.00")
    assert por_vendedor["Vendedor B"]["total"] == Decimal("5.00")


def test_ventas_por_vendedor_calcula_ticket_promedio(db_session):
    """'drop site' pedido por el cliente (2026-09-02): total facturado en $ entre
    cantidad de facturas."""
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=100)
    cliente = crear_cliente(db_session)

    _factura_contado(db_session, admin, cliente, vendedor, producto, 1, "10.00")
    _factura_contado(db_session, admin, cliente, vendedor, producto, 1, "20.00")

    resultado = ReporteService.ventas_por_vendedor(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )

    fila = resultado["filas"][0]
    assert fila["total"] == Decimal("30.00")
    assert fila["cantidad_facturas"] == 2
    assert fila["ticket_promedio"] == Decimal("15.00")


# --- ventas_por_ruta --------------------------------------------------------------------


def test_ventas_por_ruta_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.ventas_por_ruta(db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today())


def test_ventas_por_ruta_fecha_desde_posterior_a_hasta_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="fecha_desde"):
        ReporteService.ventas_por_ruta(
            db_session,
            id_usuario=admin.id_usuario,
            fecha_desde=date.today(),
            fecha_hasta=date.today() - timedelta(days=1),
        )


def test_ventas_por_ruta_agrupa_por_ruta_del_vendedor_y_calcula_ticket_promedio(db_session):
    admin = crear_usuario_admin(db_session)
    ruta_norte = crear_ruta(db_session, nombre_ruta="Ruta Norte")
    ruta_sur = crear_ruta(db_session, nombre_ruta="Ruta Sur")
    vendedor_norte = crear_vendedor(db_session, nombre_vendedor="Vendedor Norte", ruta=ruta_norte)
    otro_vendedor_norte = crear_vendedor(db_session, nombre_vendedor="Otro Vendedor Norte", ruta=ruta_norte)
    vendedor_sur = crear_vendedor(db_session, nombre_vendedor="Vendedor Sur", ruta=ruta_sur)
    producto = crear_producto(db_session, cantidad_unidad=100)
    cliente = crear_cliente(db_session)

    _factura_contado(db_session, admin, cliente, vendedor_norte, producto, 1, "10.00")
    _factura_contado(db_session, admin, cliente, otro_vendedor_norte, producto, 1, "20.00")
    _factura_contado(db_session, admin, cliente, vendedor_sur, producto, 1, "5.00")

    resultado = ReporteService.ventas_por_ruta(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )

    por_ruta = {f["ruta"]: f for f in resultado["filas"]}
    assert por_ruta["Ruta Norte"]["cantidad_facturas"] == 2
    assert por_ruta["Ruta Norte"]["total"] == Decimal("30.00")
    assert por_ruta["Ruta Norte"]["ticket_promedio"] == Decimal("15.00")
    assert por_ruta["Ruta Sur"]["total"] == Decimal("5.00")
    assert por_ruta["Ruta Sur"]["ticket_promedio"] == Decimal("5.00")
    assert resultado["total_general"] == Decimal("35.00")


def test_ventas_por_ruta_excluye_anuladas(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = crear_ruta(db_session)
    vendedor = crear_vendedor(db_session, ruta=ruta)
    producto = crear_producto(db_session, cantidad_unidad=100)
    cliente = crear_cliente(db_session)

    _factura_contado(db_session, admin, cliente, vendedor, producto, 1, "10.00")
    anulada = _factura_contado(db_session, admin, cliente, vendedor, producto, 1, "100.00")
    VentaService.anular_factura(db_session, anulada.id_factura, id_usuario=admin.id_usuario, motivo="Error de carga")

    resultado = ReporteService.ventas_por_ruta(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )

    assert resultado["filas"][0]["cantidad_facturas"] == 1
    assert resultado["filas"][0]["total"] == Decimal("10.00")


# --- activacion_clientes ----------------------------------------------------------------


def test_activacion_clientes_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.activacion_clientes(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_activacion_clientes_fecha_desde_posterior_a_hasta_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="fecha_desde"):
        ReporteService.activacion_clientes(
            db_session,
            id_usuario=admin.id_usuario,
            fecha_desde=date.today(),
            fecha_hasta=date.today() - timedelta(days=1),
        )


def test_activacion_clientes_calcula_efectividad_contra_meta_del_vendedor(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session, meta_activacion=4)
    producto = crear_producto(db_session, cantidad_unidad=100)
    cliente = crear_cliente(db_session, vendedor_cliente=vendedor.id_vendedor)

    _factura_contado(db_session, admin, cliente, vendedor, producto, 1, "10.00")
    _factura_contado(db_session, admin, cliente, vendedor, producto, 1, "10.00")

    resultado = ReporteService.activacion_clientes(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )

    fila = next(f for f in resultado["filas"] if f["cliente"] == cliente.nombre_razon_social)
    assert fila["cantidad_facturas"] == 2
    assert fila["meta_activacion"] == 4
    assert fila["efectividad_pct"] == 50.0
    assert fila["activo"] is True
    assert resultado["total_activos"] == 1
    assert resultado["efectividad_promedio"] == 50.0


def test_activacion_clientes_sin_compras_queda_inactivo(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session, meta_activacion=4)
    crear_cliente(db_session, vendedor_cliente=vendedor.id_vendedor, nombre_razon_social="Cliente sin compras")

    resultado = ReporteService.activacion_clientes(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )

    fila = next(f for f in resultado["filas"] if f["cliente"] == "Cliente sin compras")
    assert fila["cantidad_facturas"] == 0
    assert fila["activo"] is False
    assert fila["efectividad_pct"] == 0.0


def test_activacion_clientes_sin_meta_configurada_no_calcula_efectividad(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=100)
    cliente = crear_cliente(db_session, vendedor_cliente=vendedor.id_vendedor)

    _factura_contado(db_session, admin, cliente, vendedor, producto, 1, "10.00")

    resultado = ReporteService.activacion_clientes(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )

    fila = next(f for f in resultado["filas"] if f["cliente"] == cliente.nombre_razon_social)
    assert fila["meta_activacion"] is None
    assert fila["efectividad_pct"] is None
    assert resultado["efectividad_promedio"] is None


def test_activacion_clientes_excluye_anuladas(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session, meta_activacion=1)
    producto = crear_producto(db_session, cantidad_unidad=100)
    cliente = crear_cliente(db_session, vendedor_cliente=vendedor.id_vendedor)

    anulada = _factura_contado(db_session, admin, cliente, vendedor, producto, 1, "10.00")
    VentaService.anular_factura(db_session, anulada.id_factura, id_usuario=admin.id_usuario, motivo="Error de carga")

    resultado = ReporteService.activacion_clientes(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )

    fila = next(f for f in resultado["filas"] if f["cliente"] == cliente.nombre_razon_social)
    assert fila["cantidad_facturas"] == 0
    assert fila["activo"] is False


def test_activacion_clientes_filtra_por_vendedor(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor_a = crear_vendedor(db_session, meta_activacion=4)
    vendedor_b = crear_vendedor(db_session, meta_activacion=4)
    cliente_a = crear_cliente(db_session, vendedor_cliente=vendedor_a.id_vendedor, nombre_razon_social="Cliente A")
    crear_cliente(db_session, vendedor_cliente=vendedor_b.id_vendedor, nombre_razon_social="Cliente B")

    resultado = ReporteService.activacion_clientes(
        db_session,
        id_usuario=admin.id_usuario,
        fecha_desde=date.today(),
        fecha_hasta=date.today(),
        id_vendedor=vendedor_a.id_vendedor,
    )

    assert [f["cliente"] for f in resultado["filas"]] == [cliente_a.nombre_razon_social]


def test_activacion_clientes_ignora_clientes_sin_vendedor_asignado(db_session):
    admin = crear_usuario_admin(db_session)
    crear_cliente(db_session, vendedor_cliente=None, nombre_razon_social="Cliente huerfano")

    resultado = ReporteService.activacion_clientes(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )

    assert "Cliente huerfano" not in [f["cliente"] for f in resultado["filas"]]


# --- productos_mas_vendidos ------------------------------------------------------------


def test_productos_mas_vendidos_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.productos_mas_vendidos(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_productos_mas_vendidos_orden_invalido_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="orden invalido"):
        ReporteService.productos_mas_vendidos(
            db_session,
            id_usuario=admin.id_usuario,
            fecha_desde=date.today(),
            fecha_hasta=date.today(),
            orden="lateral",
        )


def test_productos_mas_vendidos_respeta_orden_asc_y_desc(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    cliente = crear_cliente(db_session)
    producto_popular = crear_producto(db_session, cantidad_unidad=100, nombre_producto="Popular")
    producto_lento = crear_producto(db_session, cantidad_unidad=100, nombre_producto="Lento")

    _factura_contado(db_session, admin, cliente, vendedor, producto_popular, 5, "10.00")  # 50.00
    _factura_contado(db_session, admin, cliente, vendedor, producto_lento, 1, "2.00")  # 2.00

    mas_vendidos = ReporteService.productos_mas_vendidos(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today(), orden="desc"
    )
    menos_vendidos = ReporteService.productos_mas_vendidos(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today(), orden="asc"
    )

    assert mas_vendidos["filas"][0]["producto"] == "Popular"
    assert menos_vendidos["filas"][0]["producto"] == "Lento"


# --- facturas_anuladas -----------------------------------------------------------------


def test_facturas_anuladas_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.facturas_anuladas(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_facturas_anuladas_incluye_motivo_desde_auditoria(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=100)
    cliente = crear_cliente(db_session)

    factura = _factura_contado(db_session, admin, cliente, vendedor, producto, 1, "10.00")
    VentaService.anular_factura(
        db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="cliente arrepentido"
    )

    resultado = ReporteService.facturas_anuladas(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )

    assert resultado["total_facturas"] == 1
    assert resultado["filas"][0]["numero_factura"] == factura.numero_factura
    assert resultado["filas"][0]["motivo"] == "cliente arrepentido"


def test_facturas_anuladas_no_incluye_facturas_vigentes(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=100)
    cliente = crear_cliente(db_session)
    _factura_contado(db_session, admin, cliente, vendedor, producto, 1, "10.00")

    resultado = ReporteService.facturas_anuladas(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )

    assert resultado["filas"] == []


# --- notas_credito_emitidas -------------------------------------------------------------


def test_notas_credito_emitidas_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.notas_credito_emitidas(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_notas_credito_emitidas_lista_las_generadas_al_anular_con_pago(db_session):
    """anular_factura() solo genera NotaCreditoCliente si la cuenta por cobrar ya tenia
    pagos aplicados -- una factura de contado pagada de contado en la emision siempre
    cae en ese caso."""
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=100)
    cliente = crear_cliente(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
        pagos=[
            {
                "metodo_pago": "efectivo",
                "moneda": "USD",
                "monto_moneda_origen": Decimal("20.00"),
                "id_caja": caja.id_caja,
            }
        ],
    )
    VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="devolucion")

    resultado = ReporteService.notas_credito_emitidas(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )

    assert len(resultado["filas"]) == 1
    fila = resultado["filas"][0]
    assert fila["monto"] == Decimal("20.00")
    assert fila["motivo"] == "devolucion"
    assert fila["estado"] == "disponible"
    assert fila["numero_factura_origen"] == factura.numero_factura
    assert resultado["total_general"] == Decimal("20.00")


def test_notas_credito_emitidas_filtra_por_cliente(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=100)
    cliente_a = crear_cliente(db_session)
    cliente_b = crear_cliente(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    for cliente in (cliente_a, cliente_b):
        factura = VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "10.00"}],
            pagos=[
                {
                    "metodo_pago": "efectivo",
                    "moneda": "USD",
                    "monto_moneda_origen": Decimal("10.00"),
                    "id_caja": caja.id_caja,
                }
            ],
        )
        VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="prueba")

    resultado = ReporteService.notas_credito_emitidas(
        db_session,
        id_usuario=admin.id_usuario,
        fecha_desde=date.today(),
        fecha_hasta=date.today(),
        id_cliente=cliente_a.id_cliente,
    )

    assert len(resultado["filas"]) == 1
    assert resultado["filas"][0]["cliente"] == cliente_a.nombre_razon_social


# --- ventas_contado_vs_credito -----------------------------------------------------------


def test_ventas_contado_vs_credito_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.ventas_contado_vs_credito(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_ventas_contado_vs_credito_separa_correctamente(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=100)
    cliente_contado = crear_cliente(db_session)
    cliente_credito = crear_cliente(db_session, limite_credito=Decimal("10000.00"))

    _factura_contado(db_session, admin, cliente_contado, vendedor, producto, 1, "30.00")
    _factura_a_credito(db_session, admin, cliente_credito, "70.00", date.today() + timedelta(days=30))

    resultado = ReporteService.ventas_contado_vs_credito(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )

    por_condicion = {f["condicion_pago"]: f for f in resultado["filas"]}
    assert por_condicion["contado"]["total"] == Decimal("30.00")
    assert por_condicion["credito"]["total"] == Decimal("70.00")
    assert resultado["total_general"] == Decimal("100.00")
    assert por_condicion["contado"]["porcentaje"] == Decimal("30.00")
    assert por_condicion["credito"]["porcentaje"] == Decimal("70.00")


# --- margen_utilidad_productos ------------------------------------------------------------


def test_margen_utilidad_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.margen_utilidad_productos(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_margen_utilidad_calcula_ingreso_costo_y_margen(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    cliente = crear_cliente(db_session)
    producto = crear_producto(db_session, cantidad_unidad=100, costo_producto=Decimal("6.00"))

    _factura_contado(db_session, admin, cliente, vendedor, producto, 10, "10.00")  # ingreso 100, costo 60

    resultado = ReporteService.margen_utilidad_productos(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )

    assert len(resultado["filas"]) == 1
    fila = resultado["filas"][0]
    assert fila["ingreso"] == Decimal("100.00")
    assert fila["costo"] == Decimal("60.00")
    assert fila["margen"] == Decimal("40.00")
    assert fila["margen_pct"] == Decimal("40.00")
    assert resultado["total_margen"] == Decimal("40.00")


# --- compras_por_periodo -------------------------------------------------------------


def test_compras_por_periodo_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.compras_por_periodo(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_compras_por_periodo_agrupacion_invalida_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="agrupacion invalida"):
        ReporteService.compras_por_periodo(
            db_session,
            id_usuario=admin.id_usuario,
            fecha_desde=date.today(),
            fecha_hasta=date.today(),
            agrupacion="semana",
        )


def test_compras_por_periodo_agrupa_por_dia_y_excluye_anuladas(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=0)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("1000.00"))

    _compra_contado(db_session, admin, proveedor, producto, 5, "10.00", caja)  # 50.00
    compra_anulada = _compra_contado(db_session, admin, proveedor, producto, 1, "10.00", caja)
    CompraService.anular_compra(db_session, compra_anulada.id_compra, id_usuario=admin.id_usuario, motivo="Error")

    resultado = ReporteService.compras_por_periodo(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today(), agrupacion="dia"
    )

    assert len(resultado["filas"]) == 1
    assert resultado["filas"][0]["cantidad_compras"] == 1
    assert resultado["total_general"] == Decimal("50.00")


# --- compras_por_proveedor ------------------------------------------------------------


def test_compras_por_proveedor_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.compras_por_proveedor(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_compras_por_proveedor_arma_ranking_descendente(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=0)
    proveedor_grande = crear_proveedor(db_session)
    proveedor_chico = crear_proveedor(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("1000.00"))

    _compra_contado(db_session, admin, proveedor_grande, producto, 10, "10.00", caja)  # 100.00
    _compra_contado(db_session, admin, proveedor_chico, producto, 1, "5.00", caja)  # 5.00

    resultado = ReporteService.compras_por_proveedor(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )

    assert resultado["filas"][0]["proveedor"] == proveedor_grande.nombre_razon_social
    assert resultado["filas"][0]["total"] == Decimal("100.00")
    assert resultado["total_general"] == Decimal("105.00")


# --- compras_por_producto -------------------------------------------------------------


def test_compras_por_producto_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.compras_por_producto(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_compras_por_producto_orden_invalido_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="orden invalido"):
        ReporteService.compras_por_producto(
            db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today(), orden="ZZZ"
        )


def test_compras_por_producto_respeta_orden_asc_y_desc(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session)
    producto_caro = crear_producto(db_session, cantidad_unidad=0)
    producto_barato = crear_producto(db_session, cantidad_unidad=0)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("1000.00"))

    _compra_contado(db_session, admin, proveedor, producto_caro, 10, "10.00", caja)  # 100.00
    _compra_contado(db_session, admin, proveedor, producto_barato, 1, "5.00", caja)  # 5.00

    desc = ReporteService.compras_por_producto(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today(), orden="desc"
    )
    asc = ReporteService.compras_por_producto(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today(), orden="asc"
    )

    assert desc["filas"][0]["producto"] == producto_caro.nombre_producto
    assert asc["filas"][0]["producto"] == producto_barato.nombre_producto


# --- ordenes_compra_abiertas -----------------------------------------------------------


def test_ordenes_compra_abiertas_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.ordenes_compra_abiertas(db_session, id_usuario=None)


def test_ordenes_compra_abiertas_excluye_completas(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=0)

    oc_completa = _oc_recibida(db_session, admin, proveedor, producto, 5, "10.00")

    oc_parcial = CompraOCService.crear_oc(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        items=[{"id_producto": producto.id_producto, "cantidad_solicitada": 10, "precio_unitario": "10.00"}],
        id_usuario=admin.id_usuario,
    )
    NotaRecepcionService.crear_nota_recepcion(
        db_session,
        id_oc=oc_parcial.id_oc,
        items=[{"id_oc_detalle": oc_parcial.detalles[0].id_detalle, "cantidad_recibida": 4}],
        id_usuario=admin.id_usuario,
    )

    db_session.refresh(oc_completa)
    db_session.refresh(oc_parcial)
    assert oc_completa.estado == "COMPLETA"
    assert oc_parcial.estado == "PARCIAL"

    resultado = ReporteService.ordenes_compra_abiertas(db_session, id_usuario=admin.id_usuario)

    numeros = [f["numero_oc"] for f in resultado["filas"]]
    assert oc_parcial.numero_oc in numeros
    assert oc_completa.numero_oc not in numeros
    fila = next(f for f in resultado["filas"] if f["numero_oc"] == oc_parcial.numero_oc)
    assert fila["cantidad_pendiente"] == Decimal("6.0000")


def test_ordenes_compra_abiertas_marca_vencida_si_paso_fecha_estimada(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=0)

    oc = CompraOCService.crear_oc(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        items=[{"id_producto": producto.id_producto, "cantidad_solicitada": 10, "precio_unitario": "10.00"}],
        id_usuario=admin.id_usuario,
        fecha_estimada_entrega=date.today() - timedelta(days=5),
    )

    resultado = ReporteService.ordenes_compra_abiertas(db_session, id_usuario=admin.id_usuario)

    fila = next(f for f in resultado["filas"] if f["numero_oc"] == oc.numero_oc)
    assert fila["vencida"] is True


# --- cumplimiento_proveedores -----------------------------------------------------------


def test_cumplimiento_proveedores_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.cumplimiento_proveedores(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_cumplimiento_proveedores_rango_invertido_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="fecha_desde"):
        ReporteService.cumplimiento_proveedores(
            db_session,
            id_usuario=admin.id_usuario,
            fecha_desde=date.today(),
            fecha_hasta=date.today() - timedelta(days=1),
        )


def test_cumplimiento_proveedores_clasifica_a_tiempo_y_tardia(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session)
    producto_a = crear_producto(db_session, cantidad_unidad=0)
    producto_b = crear_producto(db_session, cantidad_unidad=0)

    # recepcion se registra "ahora" (datetime.now()) -- fecha_estimada_entrega manana = a tiempo
    _oc_recibida(db_session, admin, proveedor, producto_a, 5, "10.00", date.today() + timedelta(days=1))
    # fecha_estimada_entrega ayer = tardia
    _oc_recibida(db_session, admin, proveedor, producto_b, 5, "10.00", date.today() - timedelta(days=1))

    resultado = ReporteService.cumplimiento_proveedores(
        db_session,
        id_usuario=admin.id_usuario,
        fecha_desde=date.today() - timedelta(days=1),
        fecha_hasta=date.today() + timedelta(days=1),
    )

    assert len(resultado["filas"]) == 1
    fila = resultado["filas"][0]
    assert fila["proveedor"] == proveedor.nombre_razon_social
    assert fila["cantidad_oc"] == 2
    assert fila["a_tiempo"] == 1
    assert fila["tardias"] == 1
    assert fila["pct_a_tiempo"] == Decimal("50")


# --- devoluciones_proveedor -----------------------------------------------------------


def test_devoluciones_proveedor_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.devoluciones_proveedor(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_devoluciones_proveedor_lista_con_motivo(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=0)

    oc = CompraOCService.crear_oc(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        items=[{"id_producto": producto.id_producto, "cantidad_solicitada": 10, "precio_unitario": "10.00"}],
        id_usuario=admin.id_usuario,
    )
    nr = NotaRecepcionService.crear_nota_recepcion(
        db_session,
        id_oc=oc.id_oc,
        items=[
            {"id_oc_detalle": oc.detalles[0].id_detalle, "cantidad_recibida": 10, "cantidad_rechazada": 3},
        ],
        id_usuario=admin.id_usuario,
    )
    devolucion = NotaRecepcionService.crear_nota_devolucion(
        db_session,
        id_nr=nr.id_nr,
        items=[{"id_producto": producto.id_producto, "cantidad_devuelta": 3}],
        motivo="Producto defectuoso",
        id_usuario=admin.id_usuario,
    )

    resultado = ReporteService.devoluciones_proveedor(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )

    assert resultado["total_devoluciones"] == 1
    fila = resultado["filas"][0]
    assert fila["numero_nota_devolucion"] == devolucion.numero_nota_devolucion
    assert fila["proveedor"] == proveedor.nombre_razon_social
    assert fila["motivo"] == "Producto defectuoso"
    assert fila["cantidad_total"] == Decimal("3")


# --- notas_credito_proveedor -----------------------------------------------------------


def test_notas_credito_proveedor_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.notas_credito_proveedor(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_notas_credito_proveedor_lista_generada_al_anular_con_pago(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=10)
    proveedor = crear_proveedor(db_session, limite_credito=Decimal("1000.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("0.00"))

    compra = CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 4, "costo_unitario": "10.00"}],
    )
    cxp = db_session.query(CuentaPorPagar).filter_by(id_compra=compra.id_compra).one()
    PagoService.registrar_pago_proveedor(
        db_session,
        id_cuenta_por_pagar=cxp.id_cuenta,
        monto=Decimal("10.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )
    CompraService.anular_compra(db_session, compra.id_compra, id_usuario=admin.id_usuario, motivo="Error de carga")

    resultado = ReporteService.notas_credito_proveedor(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )

    assert len(resultado["filas"]) == 1
    fila = resultado["filas"][0]
    assert fila["proveedor"] == proveedor.nombre_razon_social
    assert fila["numero_compra_origen"] == compra.numero_compra
    assert fila["monto"] == Decimal("10.00")
    assert resultado["total_general"] == Decimal("10.00")


# --- arqueo_caja --------------------------------------------------------------------


def test_arqueo_caja_sin_usuario_autorizado_falla(db_session):
    caja = crear_caja(db_session)
    with pytest.raises(PermisoDenegadoError):
        ReporteService.arqueo_caja(db_session, id_usuario=None, id_caja=caja.id_caja)


def test_arqueo_caja_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Caja no encontrada"):
        ReporteService.arqueo_caja(db_session, id_usuario=admin.id_usuario, id_caja=999999)


def test_arqueo_caja_nunca_abierta_falla(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)
    with pytest.raises(ValueError, match="nunca se ha abierto"):
        ReporteService.arqueo_caja(db_session, id_usuario=admin.id_usuario, id_caja=caja.id_caja)


def test_arqueo_caja_calcula_saldo_esperado_y_diferencia(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("100.00"))
    CajaService.registrar_movimiento_manual(
        db_session, caja.id_caja, "entrada", Decimal("50.00"), "Venta contado", admin.id_usuario
    )
    CajaService.registrar_movimiento_manual(
        db_session, caja.id_caja, "salida", Decimal("20.00"), "Compra insumos", admin.id_usuario
    )
    CajaService.cerrar_caja(db_session, caja.id_caja, id_usuario_cierre=admin.id_usuario)
    # saldo_cierre lo deja el usuario/proceso de cierre real; se fuerza aca para probar
    # el calculo de diferencia contra un valor que no coincide con lo esperado (130.00).
    caja_db = db_session.get(Caja, caja.id_caja)
    caja_db.saldo_cierre = Decimal("125.00")
    db_session.commit()

    resultado = ReporteService.arqueo_caja(db_session, id_usuario=admin.id_usuario, id_caja=caja.id_caja)

    assert resultado["total_entradas"] == Decimal("50.00")
    assert resultado["total_salidas"] == Decimal("20.00")
    assert resultado["saldo_esperado"] == Decimal("130.00")
    assert resultado["diferencia"] == Decimal("-5.00")
    assert len(resultado["movimientos"]) == 2


def test_arqueo_caja_incluye_movimientos_generados_por_pagos(db_session):
    """Un cobro con id_caja no crea CajaMovimiento explicito en pagos.py -- lo hace el
    trigger trg_pagos_cobros_io (INSTEAD OF INSERT). El arqueo debe verlo igual."""
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("0.00"))

    factura = _factura_a_credito(db_session, admin, cliente, "60.00", date.today())
    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()

    PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto="60.00",
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    resultado = ReporteService.arqueo_caja(db_session, id_usuario=admin.id_usuario, id_caja=caja.id_caja)

    assert resultado["total_entradas"] == Decimal("60.00")
    assert resultado["saldo_esperado"] == Decimal("60.00")


# --- kardex_producto ---------------------------------------------------------------


def test_kardex_sin_usuario_autorizado_falla(db_session):
    producto = crear_producto(db_session)
    with pytest.raises(PermisoDenegadoError):
        ReporteService.kardex_producto(
            db_session,
            id_usuario=None,
            id_producto=producto.id_producto,
            fecha_desde=date.today(),
            fecha_hasta=date.today(),
        )


def test_kardex_producto_no_encontrado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Producto no encontrado"):
        ReporteService.kardex_producto(
            db_session,
            id_usuario=admin.id_usuario,
            id_producto=999999,
            fecha_desde=date.today(),
            fecha_hasta=date.today(),
        )


def test_kardex_fecha_desde_posterior_a_hasta_falla(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    with pytest.raises(ValueError, match="fecha_desde"):
        ReporteService.kardex_producto(
            db_session,
            id_usuario=admin.id_usuario,
            id_producto=producto.id_producto,
            fecha_desde=date.today(),
            fecha_hasta=date.today() - timedelta(days=1),
        )


def test_kardex_sin_movimientos(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=0)
    resultado = ReporteService.kardex_producto(
        db_session,
        id_usuario=admin.id_usuario,
        id_producto=producto.id_producto,
        fecha_desde=date.today(),
        fecha_hasta=date.today(),
    )
    assert resultado["filas"] == []
    assert resultado["saldo_inicial"] == Decimal("0.00")
    assert resultado["saldo_final"] == Decimal("0.00")


def test_kardex_combina_las_4_fuentes_con_saldo_corrido(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session)
    cliente = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    vendedor = crear_vendedor(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("1000.00"))
    producto = crear_producto(db_session, cantidad_unidad=0)
    hoy = date.today()

    # Entrada 1: compra directa (10 unidades)
    _compra_contado(db_session, admin, proveedor, producto, 10, "5.00", caja)

    # Entrada 2: recepcion de OC (5 unidades, de las cuales 2 se rechazan y luego se
    # devuelven -- salida via nota_devolucion)
    oc = CompraOCService.crear_oc(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        items=[{"id_producto": producto.id_producto, "cantidad_solicitada": 5, "precio_unitario": "5.00"}],
        id_usuario=admin.id_usuario,
    )
    nr = NotaRecepcionService.crear_nota_recepcion(
        db_session,
        id_oc=oc.id_oc,
        items=[{"id_oc_detalle": oc.detalles[0].id_detalle, "cantidad_recibida": 5, "cantidad_rechazada": 2}],
        id_usuario=admin.id_usuario,
    )
    NotaRecepcionService.crear_nota_devolucion(
        db_session,
        id_nr=nr.id_nr,
        items=[{"id_producto": producto.id_producto, "cantidad_devuelta": 2}],
        motivo="Producto defectuoso",
        id_usuario=admin.id_usuario,
    )

    # Salida: venta de contado (3 unidades)
    _factura_contado(db_session, admin, cliente, vendedor, producto, 3, "8.00")

    resultado = ReporteService.kardex_producto(
        db_session, id_usuario=admin.id_usuario, id_producto=producto.id_producto, fecha_desde=hoy, fecha_hasta=hoy
    )

    assert resultado["saldo_inicial"] == Decimal("0.00")
    assert len(resultado["filas"]) == 4
    tipos = [f["tipo"] for f in resultado["filas"]]
    assert set(tipos) == {"Compra", "Recepción OC", "Venta", "Devolución a Proveedor"}
    # 10 (compra) + 5 (recepcion) - 2 (devolucion) - 3 (venta) = 10, y el saldo corrido
    # de la ultima fila (ya ordenadas por fecha) debe coincidir con el saldo final.
    assert resultado["saldo_final"] == Decimal("10")
    assert resultado["filas"][-1]["saldo"] == Decimal("10")


def test_kardex_saldo_inicial_incluye_movimientos_previos_al_rango(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("1000.00"))
    producto = crear_producto(db_session, cantidad_unidad=0)
    hoy = date.today()

    compra = _compra_contado(db_session, admin, proveedor, producto, 10, "5.00", caja)
    # Simula que la compra ocurrio hace 5 dias (fecha_emision es GETDATE() en el trigger,
    # no hay forma de pasarla al crear -- mismo patron que el test de arqueo que fuerza
    # saldo_cierre despues de crear la caja).
    compra_db = db_session.query(Compra).filter_by(id_compra=compra.id_compra).one()
    compra_db.fecha_emision = datetime.combine(hoy - timedelta(days=5), time.min)
    db_session.commit()

    resultado = ReporteService.kardex_producto(
        db_session, id_usuario=admin.id_usuario, id_producto=producto.id_producto, fecha_desde=hoy, fecha_hasta=hoy
    )

    assert resultado["filas"] == []
    assert resultado["saldo_inicial"] == Decimal("10")
    assert resultado["saldo_final"] == Decimal("10")


# --- valorizacion_inventario ---------------------------------------------------------


def test_valorizacion_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.valorizacion_inventario(db_session, id_usuario=None)


def test_valorizacion_sin_productos(db_session):
    admin = crear_usuario_admin(db_session)
    resultado = ReporteService.valorizacion_inventario(db_session, id_usuario=admin.id_usuario)
    assert resultado["filas"] == []
    assert resultado["total_general"] == Decimal("0.00")


def test_valorizacion_calcula_valor_total_y_agrupa_por_categoria(db_session):
    admin = crear_usuario_admin(db_session)
    cat_a = crear_categoria(db_session, nombre="Categoría A")
    cat_b = crear_categoria(db_session, nombre="Categoría B")
    crear_producto(db_session, categoria=cat_a, cantidad_unidad=10, costo_producto=Decimal("5.00"))
    crear_producto(db_session, categoria=cat_a, cantidad_unidad=4, costo_producto=Decimal("2.50"))
    crear_producto(db_session, categoria=cat_b, cantidad_unidad=2, costo_producto=Decimal("100.00"))

    resultado = ReporteService.valorizacion_inventario(db_session, id_usuario=admin.id_usuario)

    assert len(resultado["filas"]) == 3
    assert resultado["totales_por_categoria"]["Categoría A"] == Decimal("60.00")
    assert resultado["totales_por_categoria"]["Categoría B"] == Decimal("200.00")
    assert resultado["total_general"] == Decimal("260.00")


def test_valorizacion_filtra_por_categoria(db_session):
    admin = crear_usuario_admin(db_session)
    cat_a = crear_categoria(db_session)
    cat_b = crear_categoria(db_session)
    crear_producto(db_session, categoria=cat_a, cantidad_unidad=10, costo_producto=Decimal("5.00"))
    crear_producto(db_session, categoria=cat_b, cantidad_unidad=2, costo_producto=Decimal("100.00"))

    resultado = ReporteService.valorizacion_inventario(
        db_session, id_usuario=admin.id_usuario, id_categoria=cat_a.id_categoria
    )

    assert len(resultado["filas"]) == 1
    assert resultado["total_general"] == Decimal("50.00")


def test_valorizacion_excluye_productos_inactivos(db_session):
    admin = crear_usuario_admin(db_session)
    crear_producto(db_session, cantidad_unidad=10, costo_producto=Decimal("5.00"), estado_producto="INACTIVO")

    resultado = ReporteService.valorizacion_inventario(db_session, id_usuario=admin.id_usuario)

    assert resultado["filas"] == []


# --- productos_bajo_minimo ------------------------------------------------------------


def test_bajo_minimo_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.productos_bajo_minimo(db_session, id_usuario=None)


def test_bajo_minimo_sin_alertas(db_session):
    admin = crear_usuario_admin(db_session)
    crear_producto(db_session, cantidad_unidad=50, cantidad_minima=Decimal("10.00"))
    resultado = ReporteService.productos_bajo_minimo(db_session, id_usuario=admin.id_usuario)
    assert resultado["filas"] == []


def test_bajo_minimo_ignora_producto_sin_minimo_configurado(db_session):
    admin = crear_usuario_admin(db_session)
    crear_producto(db_session, cantidad_unidad=0, cantidad_minima=Decimal("0.00"))
    resultado = ReporteService.productos_bajo_minimo(db_session, id_usuario=admin.id_usuario)
    assert resultado["filas"] == []


def test_bajo_minimo_detecta_deficit_y_ordena_desc(db_session):
    admin = crear_usuario_admin(db_session)
    crear_producto(db_session, cod_producto="LEVE", cantidad_unidad=8, cantidad_minima=Decimal("10.00"))  # deficit 2
    crear_producto(
        db_session, cod_producto="CRITICO", cantidad_unidad=1, cantidad_minima=Decimal("20.00")
    )  # deficit 19

    resultado = ReporteService.productos_bajo_minimo(db_session, id_usuario=admin.id_usuario)

    assert resultado["total_productos"] == 2
    assert [f["cod_producto"] for f in resultado["filas"]] == ["CRITICO", "LEVE"]
    assert resultado["filas"][0]["deficit"] == Decimal("19.00")


# --- productos_sin_movimiento ----------------------------------------------------------


def test_sin_movimiento_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.productos_sin_movimiento(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_sin_movimiento_fecha_invalida_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="fecha_desde"):
        ReporteService.productos_sin_movimiento(
            db_session,
            id_usuario=admin.id_usuario,
            fecha_desde=date.today(),
            fecha_hasta=date.today() - timedelta(days=1),
        )


def test_sin_movimiento_excluye_productos_con_venta_o_compra_en_rango(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session)
    cliente = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    vendedor = crear_vendedor(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("1000.00"))
    hoy = date.today()

    con_venta = crear_producto(db_session, cod_producto="CON-VENTA", cantidad_unidad=100)
    con_compra = crear_producto(db_session, cod_producto="CON-COMPRA", cantidad_unidad=100)
    sin_movimiento = crear_producto(db_session, cod_producto="SIN-MOV", cantidad_unidad=100)

    _factura_contado(db_session, admin, cliente, vendedor, con_venta, 1, "8.00")
    _compra_contado(db_session, admin, proveedor, con_compra, 1, "5.00", caja)

    resultado = ReporteService.productos_sin_movimiento(
        db_session, id_usuario=admin.id_usuario, fecha_desde=hoy, fecha_hasta=hoy
    )

    codigos = {f["cod_producto"] for f in resultado["filas"]}
    assert sin_movimiento.cod_producto in codigos
    assert con_venta.cod_producto not in codigos
    assert con_compra.cod_producto not in codigos


def test_sin_movimiento_incluye_fecha_ultimo_movimiento_fuera_de_rango(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=100)
    hoy = date.today()

    factura = _factura_contado(db_session, admin, cliente, vendedor, producto, 1, "8.00")
    factura_db = db_session.get(type(factura), factura.id_factura)
    factura_db.fecha_emision = datetime.combine(hoy - timedelta(days=30), time.min)
    db_session.commit()

    resultado = ReporteService.productos_sin_movimiento(
        db_session, id_usuario=admin.id_usuario, fecha_desde=hoy - timedelta(days=5), fecha_hasta=hoy
    )

    fila = next(f for f in resultado["filas"] if f["cod_producto"] == producto.cod_producto)
    assert fila["fecha_ultimo_movimiento"] is not None
    assert fila["fecha_ultimo_movimiento"].date() == hoy - timedelta(days=30)


# --- historico_precios -----------------------------------------------------------------


def test_historico_precios_sin_usuario_autorizado_falla(db_session):
    producto = crear_producto(db_session)
    with pytest.raises(PermisoDenegadoError):
        ReporteService.historico_precios(db_session, id_usuario=None, id_producto=producto.id_producto)


def test_historico_precios_producto_no_encontrado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Producto no encontrado"):
        ReporteService.historico_precios(db_session, id_usuario=admin.id_usuario, id_producto=999999)


def test_historico_precios_sin_cambios(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    resultado = ReporteService.historico_precios(
        db_session, id_usuario=admin.id_usuario, id_producto=producto.id_producto
    )
    assert resultado["filas"] == []


def test_historico_precios_registra_cada_cambio_en_orden(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, costo_producto=Decimal("10.00"))

    PrecioService.establecer_precio(db_session, producto.id_producto, "15.00", id_usuario=admin.id_usuario)
    PrecioService.establecer_precio(db_session, producto.id_producto, "18.00", id_usuario=admin.id_usuario)

    resultado = ReporteService.historico_precios(
        db_session, id_usuario=admin.id_usuario, id_producto=producto.id_producto
    )

    assert len(resultado["filas"]) == 2
    assert resultado["filas"][0]["precio_venta"] == Decimal("15.00")
    assert resultado["filas"][1]["precio_venta"] == Decimal("18.00")
    assert resultado["filas"][1]["usuario"] == admin.nombre_usuario


def test_historico_precios_no_mezcla_productos(db_session):
    admin = crear_usuario_admin(db_session)
    producto_a = crear_producto(db_session, costo_producto=Decimal("10.00"))
    producto_b = crear_producto(db_session, costo_producto=Decimal("10.00"))

    PrecioService.establecer_precio(db_session, producto_a.id_producto, "15.00", id_usuario=admin.id_usuario)
    PrecioService.establecer_precio(db_session, producto_b.id_producto, "99.00", id_usuario=admin.id_usuario)

    resultado = ReporteService.historico_precios(
        db_session, id_usuario=admin.id_usuario, id_producto=producto_a.id_producto
    )

    assert len(resultado["filas"]) == 1
    assert resultado["filas"][0]["precio_venta"] == Decimal("15.00")


# --- estado_cuenta_cliente -----------------------------------------------------------


def test_estado_cuenta_cliente_sin_usuario_autorizado_falla(db_session):
    cliente = crear_cliente(db_session)
    with pytest.raises(PermisoDenegadoError):
        ReporteService.estado_cuenta_cliente(db_session, id_usuario=None, id_cliente=cliente.id_cliente)


def test_estado_cuenta_cliente_cliente_no_encontrado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Cliente no encontrado"):
        ReporteService.estado_cuenta_cliente(db_session, id_usuario=admin.id_usuario, id_cliente=999999)


def test_estado_cuenta_cliente_fecha_invalida_falla(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session)
    with pytest.raises(ValueError, match="fecha_desde"):
        ReporteService.estado_cuenta_cliente(
            db_session,
            id_usuario=admin.id_usuario,
            id_cliente=cliente.id_cliente,
            fecha_desde=date.today(),
            fecha_hasta=date.today() - timedelta(days=1),
        )


def test_estado_cuenta_cliente_sin_movimientos(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session)
    resultado = ReporteService.estado_cuenta_cliente(
        db_session, id_usuario=admin.id_usuario, id_cliente=cliente.id_cliente
    )
    assert resultado["filas"] == []
    assert resultado["saldo_inicial"] == Decimal("0.00")
    assert resultado["saldo_final"] == Decimal("0.00")


def test_estado_cuenta_cliente_combina_cargo_y_abono_con_saldo_corrido(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    factura = _factura_a_credito(db_session, admin, cliente, "80.00", date.today() + timedelta(days=10))
    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()
    PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto="30.00",
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    resultado = ReporteService.estado_cuenta_cliente(
        db_session, id_usuario=admin.id_usuario, id_cliente=cliente.id_cliente
    )

    assert len(resultado["filas"]) == 2
    assert resultado["filas"][0]["tipo"] == "Factura"
    assert resultado["filas"][0]["cargo"] == Decimal("80.00")
    assert resultado["filas"][1]["tipo"] == "Pago"
    assert resultado["filas"][1]["abono"] == Decimal("30.00")
    assert resultado["saldo_final"] == Decimal("50.00")


def test_estado_cuenta_cliente_no_mezcla_clientes(db_session):
    admin = crear_usuario_admin(db_session)
    cliente_a = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    cliente_b = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    _factura_a_credito(db_session, admin, cliente_a, "40.00", date.today() + timedelta(days=10))
    _factura_a_credito(db_session, admin, cliente_b, "99.00", date.today() + timedelta(days=10))

    resultado = ReporteService.estado_cuenta_cliente(
        db_session, id_usuario=admin.id_usuario, id_cliente=cliente_a.id_cliente
    )

    assert len(resultado["filas"]) == 1
    assert resultado["filas"][0]["cargo"] == Decimal("40.00")


# --- cobros_del_periodo ---------------------------------------------------------------


def test_cobros_del_periodo_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.cobros_del_periodo(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_cobros_del_periodo_fecha_invalida_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="fecha_desde"):
        ReporteService.cobros_del_periodo(
            db_session,
            id_usuario=admin.id_usuario,
            fecha_desde=date.today(),
            fecha_hasta=date.today() - timedelta(days=1),
        )


def test_cobros_del_periodo_sin_cobros(db_session):
    admin = crear_usuario_admin(db_session)
    resultado = ReporteService.cobros_del_periodo(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )
    assert resultado["filas"] == []
    assert resultado["total_general"] == Decimal("0.00")


def test_cobros_del_periodo_agrupa_por_metodo_y_filtra_por_cliente(db_session):
    admin = crear_usuario_admin(db_session)
    cliente_a = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    cliente_b = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)
    hoy = date.today()

    factura_a = _factura_a_credito(db_session, admin, cliente_a, "50.00", hoy + timedelta(days=10))
    cxc_a = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura_a.id_factura).one()
    PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc_a.id_cuenta_por_cobrar,
        monto="50.00",
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    factura_b = _factura_a_credito(db_session, admin, cliente_b, "20.00", hoy + timedelta(days=10))
    cxc_b = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura_b.id_factura).one()
    PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc_b.id_cuenta_por_cobrar,
        monto="20.00",
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    resultado = ReporteService.cobros_del_periodo(
        db_session, id_usuario=admin.id_usuario, fecha_desde=hoy, fecha_hasta=hoy, id_cliente=cliente_a.id_cliente
    )

    assert len(resultado["filas"]) == 1
    assert resultado["filas"][0]["monto"] == Decimal("50.00")
    assert resultado["totales_por_metodo"]["efectivo"] == Decimal("50.00")
    assert resultado["total_general"] == Decimal("50.00")


# --- clientes_morosos ------------------------------------------------------------------


def test_clientes_morosos_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.clientes_morosos(db_session, id_usuario=None)


def test_clientes_morosos_sin_morosos(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    _factura_a_credito(db_session, admin, cliente, "40.00", date.today() + timedelta(days=10))

    resultado = ReporteService.clientes_morosos(db_session, id_usuario=admin.id_usuario)

    assert resultado["filas"] == []


def test_clientes_morosos_agrupa_por_cliente_y_excluye_vigentes(db_session):
    admin = crear_usuario_admin(db_session)
    moroso = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    al_dia = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    hoy = date.today()

    _factura_a_credito(db_session, admin, moroso, "60.00", hoy - timedelta(days=10))
    _factura_a_credito(db_session, admin, moroso, "40.00", hoy - timedelta(days=40))
    _factura_a_credito(db_session, admin, al_dia, "99.00", hoy + timedelta(days=10))

    resultado = ReporteService.clientes_morosos(db_session, id_usuario=admin.id_usuario, fecha_corte=hoy)

    assert len(resultado["filas"]) == 1
    fila = resultado["filas"][0]
    assert fila["cliente"] == moroso.nombre_razon_social
    assert fila["saldo_vencido"] == Decimal("100.00")
    assert fila["dias_vencido_max"] == 40
    assert fila["facturas_vencidas"] == 2
    assert resultado["total_general"] == Decimal("100.00")


# --- cxc_otras -------------------------------------------------------------------------


def test_cxc_otras_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.cxc_otras(db_session, id_usuario=None)


def test_cxc_otras_estado_invalido_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="estado invalido"):
        ReporteService.cxc_otras(db_session, id_usuario=admin.id_usuario, estado="no_existe")


def test_cxc_otras_sin_cuentas(db_session):
    admin = crear_usuario_admin(db_session)
    resultado = ReporteService.cxc_otras(db_session, id_usuario=admin.id_usuario)
    assert resultado["filas"] == []


def test_cxc_otras_filtra_por_cliente_y_estado(db_session):
    admin = crear_usuario_admin(db_session)
    cliente_a = crear_cliente(db_session)
    cliente_b = crear_cliente(db_session)

    OtrosMovimientosService.crear_cuenta_cobrar_otro(
        db_session,
        id_cliente=cliente_a.id_cliente,
        monto_total=Decimal("100.00"),
        descripcion="Anticipo A",
        fecha_vencimiento=None,
        creado_por=admin.id_usuario,
    )
    OtrosMovimientosService.crear_cuenta_cobrar_otro(
        db_session,
        id_cliente=cliente_b.id_cliente,
        monto_total=Decimal("50.00"),
        descripcion="Anticipo B",
        fecha_vencimiento=None,
        creado_por=admin.id_usuario,
    )

    resultado = ReporteService.cxc_otras(db_session, id_usuario=admin.id_usuario, id_cliente=cliente_a.id_cliente)
    assert len(resultado["filas"]) == 1
    assert resultado["filas"][0]["cliente"] == cliente_a.nombre_razon_social

    resultado_pendientes = ReporteService.cxc_otras(db_session, id_usuario=admin.id_usuario, estado="pendiente")
    assert len(resultado_pendientes["filas"]) == 2
    assert resultado_pendientes["total_general"] == Decimal("150.00")


# --- estado_cuenta_proveedor ----------------------------------------------------------


def test_estado_cuenta_proveedor_sin_usuario_autorizado_falla(db_session):
    proveedor = crear_proveedor(db_session)
    with pytest.raises(PermisoDenegadoError):
        ReporteService.estado_cuenta_proveedor(db_session, id_usuario=None, id_proveedor=proveedor.id_proveedor)


def test_estado_cuenta_proveedor_proveedor_no_encontrado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Proveedor no encontrado"):
        ReporteService.estado_cuenta_proveedor(db_session, id_usuario=admin.id_usuario, id_proveedor=999999)


def test_estado_cuenta_proveedor_sin_movimientos(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session)
    resultado = ReporteService.estado_cuenta_proveedor(
        db_session, id_usuario=admin.id_usuario, id_proveedor=proveedor.id_proveedor
    )
    assert resultado["filas"] == []
    assert resultado["saldo_inicial"] == Decimal("0.00")


def test_estado_cuenta_proveedor_combina_cargo_y_abono_con_saldo_corrido(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session, limite_credito=Decimal("10000.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    compra = _compra_a_credito(db_session, admin, proveedor, "80.00", date.today() + timedelta(days=10))
    cxp = db_session.query(CuentaPorPagar).filter_by(id_compra=compra.id_compra).one()
    PagoService.registrar_pago_proveedor(
        db_session,
        id_cuenta_por_pagar=cxp.id_cuenta,
        monto="30.00",
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    resultado = ReporteService.estado_cuenta_proveedor(
        db_session, id_usuario=admin.id_usuario, id_proveedor=proveedor.id_proveedor
    )

    assert len(resultado["filas"]) == 2
    assert resultado["filas"][0]["tipo"] == "Compra"
    assert resultado["filas"][0]["cargo"] == Decimal("80.00")
    assert resultado["filas"][1]["tipo"] == "Pago"
    assert resultado["saldo_final"] == Decimal("50.00")


# --- pagos_del_periodo -----------------------------------------------------------------


def test_pagos_del_periodo_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.pagos_del_periodo(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_pagos_del_periodo_fecha_invalida_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="fecha_desde"):
        ReporteService.pagos_del_periodo(
            db_session,
            id_usuario=admin.id_usuario,
            fecha_desde=date.today(),
            fecha_hasta=date.today() - timedelta(days=1),
        )


def test_pagos_del_periodo_sin_pagos(db_session):
    admin = crear_usuario_admin(db_session)
    resultado = ReporteService.pagos_del_periodo(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )
    assert resultado["filas"] == []


def test_pagos_del_periodo_agrupa_por_metodo_y_filtra_por_proveedor(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor_a = crear_proveedor(db_session, limite_credito=Decimal("10000.00"))
    proveedor_b = crear_proveedor(db_session, limite_credito=Decimal("10000.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)
    hoy = date.today()

    compra_a = _compra_a_credito(db_session, admin, proveedor_a, "50.00", hoy + timedelta(days=10))
    cxp_a = db_session.query(CuentaPorPagar).filter_by(id_compra=compra_a.id_compra).one()
    PagoService.registrar_pago_proveedor(
        db_session,
        id_cuenta_por_pagar=cxp_a.id_cuenta,
        monto="50.00",
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    compra_b = _compra_a_credito(db_session, admin, proveedor_b, "20.00", hoy + timedelta(days=10))
    cxp_b = db_session.query(CuentaPorPagar).filter_by(id_compra=compra_b.id_compra).one()
    PagoService.registrar_pago_proveedor(
        db_session,
        id_cuenta_por_pagar=cxp_b.id_cuenta,
        monto="20.00",
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    resultado = ReporteService.pagos_del_periodo(
        db_session, id_usuario=admin.id_usuario, fecha_desde=hoy, fecha_hasta=hoy, id_proveedor=proveedor_a.id_proveedor
    )

    assert len(resultado["filas"]) == 1
    assert resultado["filas"][0]["monto"] == Decimal("50.00")
    assert resultado["totales_por_metodo"]["efectivo"] == Decimal("50.00")


# --- proximos_vencimientos --------------------------------------------------------------


def test_proximos_vencimientos_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.proximos_vencimientos(db_session, id_usuario=None)


def test_proximos_vencimientos_dias_horizonte_negativo_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="dias_horizonte"):
        ReporteService.proximos_vencimientos(db_session, id_usuario=admin.id_usuario, dias_horizonte=-1)


def test_proximos_vencimientos_sin_cuentas(db_session):
    admin = crear_usuario_admin(db_session)
    resultado = ReporteService.proximos_vencimientos(db_session, id_usuario=admin.id_usuario)
    assert resultado["filas"] == []


def test_proximos_vencimientos_respeta_el_horizonte(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session, limite_credito=Decimal("10000.00"))
    hoy = date.today()

    _compra_a_credito(db_session, admin, proveedor, "40.00", hoy + timedelta(days=10))  # dentro del horizonte
    _compra_a_credito(db_session, admin, proveedor, "60.00", hoy + timedelta(days=90))  # fuera del horizonte

    resultado = ReporteService.proximos_vencimientos(db_session, id_usuario=admin.id_usuario, dias_horizonte=30)

    assert len(resultado["filas"]) == 1
    assert resultado["filas"][0]["saldo_pendiente"] == Decimal("40.00")


# --- cxp_otras -------------------------------------------------------------------------


def test_cxp_otras_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.cxp_otras(db_session, id_usuario=None)


def test_cxp_otras_estado_invalido_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="estado invalido"):
        ReporteService.cxp_otras(db_session, id_usuario=admin.id_usuario, estado="no_existe")


def test_cxp_otras_sin_cuentas(db_session):
    admin = crear_usuario_admin(db_session)
    resultado = ReporteService.cxp_otras(db_session, id_usuario=admin.id_usuario)
    assert resultado["filas"] == []


def test_cxp_otras_filtra_por_cuenta_bancaria_y_estado(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta_a = crear_cuenta_bancaria(db_session)
    cuenta_b = crear_cuenta_bancaria(db_session)

    OtrosMovimientosService.crear_partida_no_conciliada(
        db_session, id_cuenta_bancaria=cuenta_a.id_cuenta, monto=Decimal("100.00"), creado_por=admin.id_usuario
    )
    OtrosMovimientosService.crear_partida_no_conciliada(
        db_session, id_cuenta_bancaria=cuenta_b.id_cuenta, monto=Decimal("50.00"), creado_por=admin.id_usuario
    )

    resultado = ReporteService.cxp_otras(db_session, id_usuario=admin.id_usuario, id_cuenta_bancaria=cuenta_a.id_cuenta)
    assert len(resultado["filas"]) == 1
    assert resultado["filas"][0]["saldo_pendiente"] == Decimal("100.00")

    resultado_pendientes = ReporteService.cxp_otras(db_session, id_usuario=admin.id_usuario, estado="pendiente")
    assert len(resultado_pendientes["filas"]) == 2
    assert resultado_pendientes["total_general"] == Decimal("150.00")


# --- movimientos_caja_periodo -----------------------------------------------------------


def test_movimientos_caja_periodo_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.movimientos_caja_periodo(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_movimientos_caja_periodo_fecha_invalida_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="fecha_desde"):
        ReporteService.movimientos_caja_periodo(
            db_session,
            id_usuario=admin.id_usuario,
            fecha_desde=date.today(),
            fecha_hasta=date.today() - timedelta(days=1),
        )


def test_movimientos_caja_periodo_tipo_invalido_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="tipo_movimiento invalido"):
        ReporteService.movimientos_caja_periodo(
            db_session,
            id_usuario=admin.id_usuario,
            fecha_desde=date.today(),
            fecha_hasta=date.today(),
            tipo_movimiento="invalido",
        )


def test_movimientos_caja_periodo_sin_movimientos(db_session):
    admin = crear_usuario_admin(db_session)
    resultado = ReporteService.movimientos_caja_periodo(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )
    assert resultado["filas"] == []
    assert resultado["neto"] == Decimal("0.00")


def test_movimientos_caja_periodo_filtra_por_caja_y_tipo_con_totales(db_session):
    admin = crear_usuario_admin(db_session)
    caja_a = crear_caja(db_session)
    caja_b = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja_a.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)
    CajaService.abrir_caja(db_session, caja_b.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)
    hoy = date.today()

    CajaService.registrar_movimiento_manual(
        db_session, caja_a.id_caja, "entrada", "100.00", "Ingreso manual", admin.id_usuario
    )
    CajaService.registrar_movimiento_manual(
        db_session, caja_a.id_caja, "salida", "30.00", "Egreso manual", admin.id_usuario
    )
    CajaService.registrar_movimiento_manual(
        db_session, caja_b.id_caja, "entrada", "999.00", "Otra caja", admin.id_usuario
    )

    resultado = ReporteService.movimientos_caja_periodo(
        db_session,
        id_usuario=admin.id_usuario,
        fecha_desde=hoy,
        fecha_hasta=hoy,
        id_caja=caja_a.id_caja,
        tipo_movimiento="entrada",
    )

    assert len(resultado["filas"]) == 1
    assert resultado["filas"][0]["monto_movimiento"] == Decimal("100.00")
    assert resultado["filas"][0]["origen"] == "Manual"

    resultado_todos = ReporteService.movimientos_caja_periodo(
        db_session, id_usuario=admin.id_usuario, fecha_desde=hoy, fecha_hasta=hoy, id_caja=caja_a.id_caja
    )
    assert resultado_todos["total_entradas"] == Decimal("100.00")
    assert resultado_todos["total_salidas"] == Decimal("30.00")
    assert resultado_todos["neto"] == Decimal("70.00")


# --- cierre_diario_por_cajero ------------------------------------------------------------


def test_cierre_diario_por_cajero_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.cierre_diario_por_cajero(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_cierre_diario_por_cajero_fecha_invalida_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="fecha_desde"):
        ReporteService.cierre_diario_por_cajero(
            db_session,
            id_usuario=admin.id_usuario,
            fecha_desde=date.today(),
            fecha_hasta=date.today() - timedelta(days=1),
        )


def test_cierre_diario_por_cajero_sin_turnos(db_session):
    admin = crear_usuario_admin(db_session)
    resultado = ReporteService.cierre_diario_por_cajero(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )
    assert resultado["filas"] == []


def test_cierre_diario_por_cajero_calcula_saldo_esperado_y_diferencia(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)
    hoy = date.today()

    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("100.00"))
    CajaService.registrar_movimiento_manual(db_session, caja.id_caja, "entrada", "50.00", "Venta", admin.id_usuario)
    CajaService.registrar_movimiento_manual(
        db_session, caja.id_caja, "salida", "20.00", "Compra insumos", admin.id_usuario
    )
    CajaService.cerrar_caja(db_session, caja.id_caja, id_usuario_cierre=admin.id_usuario)
    # saldo_cierre real forzado distinto del esperado (130.00), igual que el test de
    # arqueo_caja existente -- para probar el calculo de diferencia.
    caja_db = db_session.get(Caja, caja.id_caja)
    caja_db.saldo_cierre = Decimal("125.00")
    db_session.commit()

    resultado = ReporteService.cierre_diario_por_cajero(
        db_session, id_usuario=admin.id_usuario, fecha_desde=hoy, fecha_hasta=hoy
    )

    assert len(resultado["filas"]) == 1
    fila = resultado["filas"][0]
    assert fila["cajero"] == admin.nombre_usuario
    assert fila["saldo_esperado"] == Decimal("130.00")
    assert fila["diferencia"] == Decimal("-5.00")


def test_cierre_diario_por_cajero_filtra_por_cajero(db_session):
    admin = crear_usuario_admin(db_session)
    otro_admin = crear_usuario_admin(db_session)
    caja_a = crear_caja(db_session)
    caja_b = crear_caja(db_session)
    hoy = date.today()

    CajaService.abrir_caja(db_session, caja_a.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)
    CajaService.abrir_caja(db_session, caja_b.id_caja, id_usuario=otro_admin.id_usuario, saldo_apertura=0)

    resultado = ReporteService.cierre_diario_por_cajero(
        db_session, id_usuario=admin.id_usuario, fecha_desde=hoy, fecha_hasta=hoy, id_usuario_cajero=admin.id_usuario
    )

    assert len(resultado["filas"]) == 1
    assert resultado["filas"][0]["caja"] == caja_a.nombre_caja


# --- flujo_caja_consolidado --------------------------------------------------------------


def test_flujo_caja_consolidado_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.flujo_caja_consolidado(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_flujo_caja_consolidado_agrupacion_invalida_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="agrupacion"):
        ReporteService.flujo_caja_consolidado(
            db_session,
            id_usuario=admin.id_usuario,
            fecha_desde=date.today(),
            fecha_hasta=date.today(),
            agrupacion="semana",
        )


def test_flujo_caja_consolidado_fecha_invalida_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="fecha_desde"):
        ReporteService.flujo_caja_consolidado(
            db_session,
            id_usuario=admin.id_usuario,
            fecha_desde=date.today(),
            fecha_hasta=date.today() - timedelta(days=1),
        )


def test_flujo_caja_consolidado_sin_movimientos(db_session):
    admin = crear_usuario_admin(db_session)
    resultado = ReporteService.flujo_caja_consolidado(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )
    assert resultado["filas"] == []


def test_flujo_caja_consolidado_direcciones_correctas_caja_y_banco(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)
    cuenta = crear_cuenta_bancaria(db_session)
    hoy = date.today()

    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)
    CajaService.registrar_movimiento_manual(db_session, caja.id_caja, "entrada", "100.00", "Venta", admin.id_usuario)
    CajaService.registrar_movimiento_manual(db_session, caja.id_caja, "salida", "40.00", "Gasto", admin.id_usuario)
    # abono/deposito = entrada, cargo/transferencia = salida (trg_banco_movimientos_saldo,
    # schema_sqlserver.sql:1273) -- confirmado, no una suposicion.
    BancoMovimientoService.crear(db_session, cuenta.id_cuenta, "abono", 200.00, id_usuario=admin.id_usuario)
    BancoMovimientoService.crear(db_session, cuenta.id_cuenta, "cargo", 75.00, id_usuario=admin.id_usuario)

    resultado = ReporteService.flujo_caja_consolidado(
        db_session, id_usuario=admin.id_usuario, fecha_desde=hoy, fecha_hasta=hoy
    )

    assert len(resultado["filas"]) == 1
    fila = resultado["filas"][0]
    assert fila["entradas_caja"] == Decimal("100.00")
    assert fila["salidas_caja"] == Decimal("40.00")
    assert fila["entradas_banco"] == Decimal("200.00")
    assert fila["salidas_banco"] == Decimal("75.00")
    assert fila["neto"] == Decimal("185.00")
    assert resultado["total_entradas"] == Decimal("300.00")
    assert resultado["total_salidas"] == Decimal("115.00")


# --- movimientos_cuenta_bancaria ---------------------------------------------------------


def test_movimientos_cuenta_bancaria_sin_usuario_autorizado_falla(db_session):
    cuenta = crear_cuenta_bancaria(db_session)
    with pytest.raises(PermisoDenegadoError):
        ReporteService.movimientos_cuenta_bancaria(
            db_session,
            id_usuario=None,
            id_cuenta_bancaria=cuenta.id_cuenta,
            fecha_desde=date.today(),
            fecha_hasta=date.today(),
        )


def test_movimientos_cuenta_bancaria_cuenta_no_encontrada_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Cuenta bancaria no encontrada"):
        ReporteService.movimientos_cuenta_bancaria(
            db_session,
            id_usuario=admin.id_usuario,
            id_cuenta_bancaria=999999,
            fecha_desde=date.today(),
            fecha_hasta=date.today(),
        )


def test_movimientos_cuenta_bancaria_fecha_invalida_falla(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session)
    with pytest.raises(ValueError, match="fecha_desde"):
        ReporteService.movimientos_cuenta_bancaria(
            db_session,
            id_usuario=admin.id_usuario,
            id_cuenta_bancaria=cuenta.id_cuenta,
            fecha_desde=date.today(),
            fecha_hasta=date.today() - timedelta(days=1),
        )


def test_movimientos_cuenta_bancaria_sin_movimientos(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session)
    resultado = ReporteService.movimientos_cuenta_bancaria(
        db_session,
        id_usuario=admin.id_usuario,
        id_cuenta_bancaria=cuenta.id_cuenta,
        fecha_desde=date.today(),
        fecha_hasta=date.today(),
    )
    assert resultado["filas"] == []
    assert resultado["saldo_inicial"] == Decimal("0.00")


def test_movimientos_cuenta_bancaria_calcula_saldo_corrido_con_direccion_correcta(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session)
    hoy = date.today()

    BancoMovimientoService.crear(db_session, cuenta.id_cuenta, "abono", 200.00, id_usuario=admin.id_usuario)
    BancoMovimientoService.crear(db_session, cuenta.id_cuenta, "cargo", 75.00, id_usuario=admin.id_usuario)

    resultado = ReporteService.movimientos_cuenta_bancaria(
        db_session, id_usuario=admin.id_usuario, id_cuenta_bancaria=cuenta.id_cuenta, fecha_desde=hoy, fecha_hasta=hoy
    )

    assert len(resultado["filas"]) == 2
    assert resultado["saldo_final"] == Decimal("125.00")
    assert resultado["filas"][-1]["saldo"] == Decimal("125.00")


def test_movimientos_cuenta_bancaria_saldo_inicial_incluye_movimientos_previos(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session)
    hoy = date.today()

    movimiento = BancoMovimientoService.crear(
        db_session, cuenta.id_cuenta, "abono", 200.00, id_usuario=admin.id_usuario
    )
    movimiento_db = db_session.get(BancoMovimiento, movimiento.id_movimiento)
    movimiento_db.fecha_movimiento = datetime.combine(hoy - timedelta(days=5), time.min)
    db_session.commit()

    resultado = ReporteService.movimientos_cuenta_bancaria(
        db_session, id_usuario=admin.id_usuario, id_cuenta_bancaria=cuenta.id_cuenta, fecha_desde=hoy, fecha_hasta=hoy
    )

    assert resultado["filas"] == []
    assert resultado["saldo_inicial"] == Decimal("200.00")


# --- conciliacion_bancaria ----------------------------------------------------------------


def test_conciliacion_bancaria_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.conciliacion_bancaria(db_session, id_usuario=None)


def test_conciliacion_bancaria_fecha_invalida_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="fecha_desde"):
        ReporteService.conciliacion_bancaria(
            db_session,
            id_usuario=admin.id_usuario,
            fecha_desde=date.today(),
            fecha_hasta=date.today() - timedelta(days=1),
        )


def test_conciliacion_bancaria_sin_partidas(db_session):
    admin = crear_usuario_admin(db_session)
    resultado = ReporteService.conciliacion_bancaria(db_session, id_usuario=admin.id_usuario)
    assert resultado["filas"] == []


def test_conciliacion_bancaria_agrupa_pendiente_vs_conciliado_por_cuenta(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session)

    OtrosMovimientosService.crear_partida_no_conciliada(
        db_session, id_cuenta_bancaria=cuenta.id_cuenta, monto=Decimal("100.00"), creado_por=admin.id_usuario
    )
    conciliada = OtrosMovimientosService.crear_partida_no_conciliada(
        db_session, id_cuenta_bancaria=cuenta.id_cuenta, monto=Decimal("60.00"), creado_por=admin.id_usuario
    )
    # Forzar el estado a "conciliado" directamente: conciliar_partida() real exige una
    # factura/CxC completa del cliente, fuera del alcance de este test (que solo prueba
    # la agregacion del reporte, no las reglas de negocio de la conciliacion).
    conciliada_db = db_session.get(type(conciliada), conciliada.id_cuenta)
    conciliada_db.estado = "conciliado"
    db_session.commit()

    resultado = ReporteService.conciliacion_bancaria(db_session, id_usuario=admin.id_usuario)

    assert len(resultado["filas"]) == 1
    fila = resultado["filas"][0]
    assert fila["total_pendiente"] == Decimal("100.00")
    assert fila["cantidad_pendiente"] == 1
    assert fila["total_conciliado"] == Decimal("60.00")
    assert fila["cantidad_conciliada"] == 1
    assert resultado["total_pendiente"] == Decimal("100.00")
    assert resultado["total_conciliado"] == Decimal("60.00")


# --- saldo_consolidado --------------------------------------------------------------------


def test_saldo_consolidado_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.saldo_consolidado(db_session, id_usuario=None)


def test_saldo_consolidado_agrupa_por_banco_y_excluye_inactivas(db_session):
    admin = crear_usuario_admin(db_session)
    banco = crear_banco(db_session)
    crear_cuenta_bancaria(db_session, banco=banco, saldo_total_banco=Decimal("500.00"))
    crear_cuenta_bancaria(db_session, banco=banco, saldo_total_banco=Decimal("300.00"))
    crear_cuenta_bancaria(db_session, saldo_total_banco=Decimal("999.00"), estado_cuenta="INACTIVO")

    resultado = ReporteService.saldo_consolidado(db_session, id_usuario=admin.id_usuario)

    assert len(resultado["filas"]) == 2
    assert resultado["totales_por_banco"][banco.nombre_banco] == Decimal("800.00")
    assert resultado["total_general"] == Decimal("800.00")


# --- comisiones_por_vendedor_periodo ------------------------------------------------------


def test_comisiones_por_vendedor_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.comisiones_por_vendedor_periodo(
            db_session, id_usuario=None, fecha_desde=date.today(), fecha_hasta=date.today()
        )


def test_comisiones_por_vendedor_fecha_invalida_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="fecha_desde"):
        ReporteService.comisiones_por_vendedor_periodo(
            db_session,
            id_usuario=admin.id_usuario,
            fecha_desde=date.today(),
            fecha_hasta=date.today() - timedelta(days=1),
        )


def test_comisiones_por_vendedor_sin_comisiones(db_session):
    admin = crear_usuario_admin(db_session)
    resultado = ReporteService.comisiones_por_vendedor_periodo(
        db_session, id_usuario=admin.id_usuario, fecha_desde=date.today(), fecha_hasta=date.today()
    )
    assert resultado["filas"] == []
    assert resultado["total_general"] == Decimal("0.00")


def test_comisiones_por_vendedor_agrupa_y_filtra_por_vendedor(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor_a = crear_vendedor(db_session)
    vendedor_b = crear_vendedor(db_session)
    hoy = date.today()

    _crear_comision(db_session, admin, vendedor_a, Decimal("1.00"), Decimal("2.00"), Decimal("3"))
    _crear_comision(db_session, admin, vendedor_b, Decimal("1.00"), Decimal("5.00"), Decimal("1"))

    resultado_todos = ReporteService.comisiones_por_vendedor_periodo(
        db_session, id_usuario=admin.id_usuario, fecha_desde=hoy, fecha_hasta=hoy
    )
    assert len(resultado_todos["filas"]) == 2
    assert resultado_todos["total_general"] == Decimal("7.00")

    resultado_a = ReporteService.comisiones_por_vendedor_periodo(
        db_session, id_usuario=admin.id_usuario, fecha_desde=hoy, fecha_hasta=hoy, id_vendedor=vendedor_a.id_vendedor
    )
    assert len(resultado_a["filas"]) == 1
    assert resultado_a["filas"][0]["monto_comision"] == Decimal("3.00")
    assert resultado_a["filas"][0]["cantidad_facturas"] == 1


# --- comisiones_pagadas_vs_pendientes -----------------------------------------------------


def test_comisiones_pagadas_vs_pendientes_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.comisiones_pagadas_vs_pendientes(db_session, id_usuario=None)


def test_comisiones_pagadas_vs_pendientes_fecha_invalida_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="fecha_desde"):
        ReporteService.comisiones_pagadas_vs_pendientes(
            db_session,
            id_usuario=admin.id_usuario,
            fecha_desde=date.today(),
            fecha_hasta=date.today() - timedelta(days=1),
        )


def test_comisiones_pagadas_vs_pendientes_sin_comisiones(db_session):
    admin = crear_usuario_admin(db_session)
    resultado = ReporteService.comisiones_pagadas_vs_pendientes(db_session, id_usuario=admin.id_usuario)
    assert resultado["filas"] == []


def test_comisiones_pagadas_vs_pendientes_separa_pagado_de_pendiente(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)

    _crear_comision(db_session, admin, vendedor, Decimal("1.00"), Decimal("2.00"), Decimal("3"))  # pagada
    _crear_comision(db_session, admin, vendedor, Decimal("1.00"), Decimal("4.00"), Decimal("2"))  # pendiente

    caja = crear_caja(db_session)
    PagoComisionService.pagar_comisiones_vendedor(
        db_session,
        id_vendedor=vendedor.id_vendedor,
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )
    # pagar_comisiones_vendedor liquida TODO lo pendiente del vendedor de una vez (C14) --
    # asi que la segunda comision, creada ANTES del pago, tambien quedo pagada. Se agrega
    # una tercera comision DESPUES del pago para tener una fila realmente pendiente.
    _crear_comision(db_session, admin, vendedor, Decimal("1.00"), Decimal("6.00"), Decimal("1"))

    resultado = ReporteService.comisiones_pagadas_vs_pendientes(db_session, id_usuario=admin.id_usuario)

    assert len(resultado["filas"]) == 1
    fila = resultado["filas"][0]
    assert fila["pagado"] == Decimal("9.00")
    assert fila["pendiente"] == Decimal("5.00")
    assert resultado["total_pagado"] == Decimal("9.00")
    assert resultado["total_pendiente"] == Decimal("5.00")
