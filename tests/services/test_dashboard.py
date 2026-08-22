from datetime import date, datetime, timedelta
from decimal import Decimal

from app.db.models import Caja, FacturaVenta
from app.services.compras import CompraService
from app.services.dashboard import DashboardService
from app.services.tesoreria import CajaService
from app.services.ventas import VentaService
from tests.factories import crear_caja, crear_cliente, crear_producto, crear_proveedor


def _factura_directa(session, cliente, fecha_emision, total, estado="EMITIDA", numero=None):
    factura = FacturaVenta(
        numero_factura=numero or f"FV-DIRECT-{fecha_emision.timestamp()}",
        id_cliente_factura=cliente.id_cliente,
        fecha_emision=fecha_emision,
        total_venta=Decimal(str(total)),
        estado_factura=estado,
        condicion_pago="contado",
    )
    session.add(factura)
    session.commit()
    session.refresh(factura)
    return factura


def test_panel_general_devuelve_todas_las_secciones(db_session):
    resultado = DashboardService.get_panel_general_data(db_session)

    assert set(resultado.keys()) == {
        "ventas_hoy",
        "por_cobrar",
        "por_pagar",
        "productos_alerta",
        "grafico_semanal",
        "cajas_activas",
        "facturas_recientes",
        "inventario_alerta",
    }


def test_ventas_hoy_excluye_anuladas_y_calcula_porcentaje(db_session):
    cliente = crear_cliente(db_session)
    ahora = datetime.now()
    ayer = ahora - timedelta(days=1)

    _factura_directa(db_session, cliente, ayer, total=Decimal("50.00"), numero="FV-AYER-1")
    _factura_directa(db_session, cliente, ahora, total=Decimal("100.00"), numero="FV-HOY-1")
    _factura_directa(db_session, cliente, ahora, total=Decimal("999.00"), estado="ANULADA", numero="FV-HOY-ANULADA")

    resultado = DashboardService.get_panel_general_data(db_session)

    assert resultado["ventas_hoy"]["total"] == Decimal("100.00")
    assert resultado["ventas_hoy"]["porcentaje_vs_ayer"] == 100.0


def test_ventas_hoy_sin_ventas_previas(db_session):
    resultado = DashboardService.get_panel_general_data(db_session)
    assert resultado["ventas_hoy"]["total"] == 0
    assert resultado["ventas_hoy"]["porcentaje_vs_ayer"] == 0.0


def test_por_cobrar_suma_saldos_abiertos_y_cuenta_vencidas(db_session):
    producto = crear_producto(db_session, cantidad_unidad=100)
    cliente = crear_cliente(db_session, limite_credito=Decimal("1000.00"))

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=None,
        id_vendedor=None,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "80.00"}],
        fecha_vencimiento=date.today() - timedelta(days=5),
    )

    resultado = DashboardService.get_panel_general_data(db_session)

    assert resultado["por_cobrar"]["saldo_total"] == Decimal("80.00")
    assert resultado["por_cobrar"]["facturas_vencidas"] == 1
    assert factura.condicion_pago == "credito"


def test_por_pagar_suma_saldos_abiertos_y_cuenta_vencidas(db_session):
    producto = crear_producto(db_session, cantidad_unidad=100)
    proveedor = crear_proveedor(db_session, limite_credito=Decimal("1000.00"))

    CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=None,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "60.00"}],
        fecha_vencimiento=date.today() - timedelta(days=3),
    )

    resultado = DashboardService.get_panel_general_data(db_session)

    assert resultado["por_pagar"]["saldo_total"] == Decimal("60.00")
    assert resultado["por_pagar"]["compras_vencidas"] == 1


def test_productos_alerta_cuenta_bajo_stock(db_session):
    crear_producto(db_session, cantidad_unidad=3)
    crear_producto(db_session, cantidad_unidad=500)

    resultado = DashboardService.get_panel_general_data(db_session, umbral_stock_minimo=10)

    assert resultado["productos_alerta"] == 1


def test_grafico_semanal_tiene_siete_dias_incluyendo_hoy(db_session):
    cliente = crear_cliente(db_session)
    hoy = datetime.now()
    _factura_directa(db_session, cliente, hoy, total=Decimal("25.00"), numero="FV-GRAFICO-HOY")

    resultado = DashboardService.get_panel_general_data(db_session)
    grafico = resultado["grafico_semanal"]

    assert len(grafico) == 7
    assert grafico[-1]["fecha"] == date.today()
    assert grafico[-1]["monto"] == Decimal("25.00")


def test_cajas_activas_solo_incluye_abiertas_hoy(db_session):
    caja_abierta_hoy = crear_caja(db_session, nombre_caja="Abierta hoy")
    CajaService.abrir_caja(db_session, caja_abierta_hoy.id_caja, id_usuario=None, saldo_apertura=Decimal("50.00"))

    caja_cerrada = crear_caja(db_session, nombre_caja="Cerrada")
    CajaService.abrir_caja(db_session, caja_cerrada.id_caja, id_usuario=None, saldo_apertura=0)
    CajaService.cerrar_caja(db_session, caja_cerrada.id_caja, id_usuario_cierre=None)

    caja_abierta_ayer = Caja(
        nombre_caja="Abierta ayer",
        estado_caja="ABIERTA",
        saldo_apertura=Decimal("0.00"),
        fecha_apertura=datetime.now() - timedelta(days=1),
        fecha_cierre=None,
    )
    db_session.add(caja_abierta_ayer)
    db_session.commit()

    resultado = DashboardService.get_panel_general_data(db_session)

    nombres_activos = [c["nombre_caja"] for c in resultado["cajas_activas"]]
    assert nombres_activos == ["Abierta hoy"]


def test_facturas_recientes_limita_a_cinco_y_ordena_desc(db_session):
    cliente = crear_cliente(db_session)
    ahora = datetime.now()
    for i in range(7):
        _factura_directa(db_session, cliente, ahora - timedelta(minutes=i), total=Decimal("10.00"), numero=f"FV-REC-{i}")

    resultado = DashboardService.get_panel_general_data(db_session)
    recientes = resultado["facturas_recientes"]

    assert len(recientes) == 5
    assert recientes[0]["numero_factura"] == "FV-REC-0"


def test_inventario_alerta_incluye_categoria(db_session):
    from tests.factories import crear_categoria

    categoria = crear_categoria(db_session, nombre="Lacteos")
    crear_producto(db_session, categoria=categoria, cantidad_unidad=2, nombre_producto="Leche")
    crear_producto(db_session, cantidad_unidad=999)

    resultado = DashboardService.get_panel_general_data(db_session, umbral_stock_minimo=10)
    alertas = resultado["inventario_alerta"]

    assert len(alertas) == 1
    assert alertas[0]["nombre_producto"] == "Leche"
    assert alertas[0]["categoria"] == "Lacteos"
