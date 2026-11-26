"""El historial del cliente tiene que mostrar lo mismo que el estado de cuenta del reporte.

Fuente de la verdad: `ReporteService.estado_cuenta_cliente`. Para el mismo cliente, lo que muestra el historial
(facturas, abonos, saldos) debe cuadrar con el reporte: el saldo de la factura mas reciente es el saldo final del
reporte y el de la cabecera, lo cargado y lo abonado suman lo mismo, y cada factura trae lo que se le abono y lo que
le queda.

Antes, aplicar una nota de credito, conciliar una transferencia o anular una factura con pago dejaban al historial
sumando mal (p. ej. una tabla que terminaba en $160 con su cabecera en $130).
"""

from decimal import Decimal

from app.services.historial_cliente import (
    obtener_historial_cliente,
    obtener_saldo_total_pendiente,
    obtener_saldo_total_positivo,
)
from app.services.notas_credito import NotaCreditoService
from app.services.otros_movimientos import OtrosMovimientosService
from app.services.pagos import PagoService
from app.services.pagos_bcv import PagoBCVService
from app.services.reportes import ReporteService
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
    pago_contado,
)
from tests.services.test_otros_movimientos import _crear_cxc_real, _crear_partida
from tests.services.test_pagos_bcv import _emitir_credito_bcv


def _escenario(db):
    admin = crear_usuario_admin(db)
    vendedor = crear_vendedor(db)
    producto = crear_producto(db, cantidad_unidad=500)
    crear_precio_producto(db, producto, "20.00")
    cliente = crear_cliente(db, limite_credito=Decimal("100000.00"), dias_credito=30)
    return admin, vendedor, producto, cliente


def _credito(db, admin, vendedor, producto, cliente, unidades):
    """Factura a credito de `unidades` x $20."""
    return VentaService.emitir_factura(
        db,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": unidades, "precio_unitario": "20.00"}],
    )


def _contado(db, admin, vendedor, producto, cliente, unidades):
    return VentaService.emitir_factura(
        db,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db),
        items=[{"id_producto": producto.id_producto, "cantidad": unidades, "precio_unitario": "20.00"}],
    )


def _historial_y_reporte(db, admin, id_cliente):
    historial = obtener_historial_cliente(db, id_cliente, admin.id_usuario)
    reporte = ReporteService.estado_cuenta_cliente(db, admin.id_usuario, id_cliente)
    return historial, reporte


def _facturas(historial):
    """Las filas de factura, de la mas reciente a la mas antigua (el orden del historial)."""
    return [i for i in historial if i["tipo_transaccion"] == "factura"]


def _afirmar_que_cuadra(db, admin, id_cliente):
    """Lo que tiene que cumplirse SIEMPRE entre el historial y el estado de cuenta del mismo cliente."""
    historial, reporte = _historial_y_reporte(db, admin, id_cliente)
    facturas = _facturas(historial)

    pendiente = obtener_saldo_total_pendiente(db, id_cliente, admin.id_usuario)
    favor = obtener_saldo_total_positivo(db, id_cliente, admin.id_usuario)

    # 1. El historial muestra la DEUDA; el estado de cuenta muestra la posicion neta:
    #    deuda menos saldo a favor (puede quedar negativa cuando el cliente tiene
    #    credito a su favor).
    assert facturas[0]["saldo_corrido"] == pendiente
    assert reporte["saldo_final"] == pendiente - favor

    # 2. Lo cargado y lo abonado suman lo mismo. Los abonos del reporte son negativos
    #    y ademas incluyen el saldo a favor vigente (NC sin aplicar) y el excedente
    #    dentro del pago exacto: son credito que el historial no cuenta como abono.
    assert sum(f["monto"] for f in facturas) == sum(f["cargo"] for f in reporte["filas"])
    abonos = sum(-i["monto"] for i in historial if i["tipo_transaccion"] in ("pago", "aplicacion_nota_credito"))
    assert abonos + favor == -sum(f["abono"] for f in reporte["filas"])

    # 3. Cada factura trae lo que se le abono y lo que le queda, y el saldo corrido es la suma de lo que queda.
    acumulado = Decimal("0.00")
    for factura in reversed(facturas):
        assert factura["saldo_factura"] == factura["monto"] - factura["monto_pagado"]
        assert factura["saldo_factura"] >= 0
        acumulado += factura["saldo_factura"]
        assert factura["saldo_corrido"] == acumulado
    return historial, reporte


# -- Lo que fallaba ----------------------------------------------------------------------------------------------


def test_una_nota_de_credito_aplicada_baja_el_saldo_y_sale_como_abono(db_session):
    """Dos facturas ($100 y $60) y una nota de $30 aplicada a la segunda: el reporte termina en $130 y el historial
    terminaba en $160 con su cabecera en $130."""
    db = db_session
    admin, vendedor, producto, cliente = _escenario(db)
    f1 = _credito(db, admin, vendedor, producto, cliente, 5)
    f2 = _credito(db, admin, vendedor, producto, cliente, 3)
    nota = NotaCreditoService.crear_nota_credito_cliente(
        db,
        id_cliente=cliente.id_cliente,
        id_factura_origen=f1.id_factura,
        monto=Decimal("30.00"),
        motivo="Ajuste",
        id_usuario=admin.id_usuario,
    )
    NotaCreditoService.aplicar_nota_credito_cliente(
        db, nota.id_nota_credito, f2.id_factura, Decimal("30.00"), admin.id_usuario
    )

    historial, reporte = _afirmar_que_cuadra(db, admin, cliente.id_cliente)

    assert reporte["saldo_final"] == Decimal("130.00")
    fila_f2 = next(f for f in _facturas(historial) if f["id_factura"] == f2.id_factura)
    assert (fila_f2["monto"], fila_f2["monto_pagado"], fila_f2["saldo_factura"]) == (
        Decimal("60.00"),
        Decimal("30.00"),
        Decimal("30.00"),
    )
    (aplicacion,) = [i for i in historial if i["tipo_transaccion"] == "aplicacion_nota_credito"]
    assert aplicacion["numero_factura"] == nota.numero_nota_credito
    assert aplicacion["id_factura"] == f2.id_factura
    assert aplicacion["monto"] == Decimal("-30.00")  # abono: resta, como un pago


def test_una_nota_disponible_sigue_siendo_saldo_a_favor_y_no_cambia_lo_que_se_debe(db_session):
    db = db_session
    admin, vendedor, producto, cliente = _escenario(db)
    f1 = _credito(db, admin, vendedor, producto, cliente, 5)
    NotaCreditoService.crear_nota_credito_cliente(
        db,
        id_cliente=cliente.id_cliente,
        id_factura_origen=f1.id_factura,
        monto=Decimal("20.00"),
        motivo="A favor",
        id_usuario=admin.id_usuario,
    )

    historial, reporte = _afirmar_que_cuadra(db, admin, cliente.id_cliente)

    # 100 de deuda - 20 de saldo a favor = 80 de posicion neta.
    assert reporte["saldo_final"] == Decimal("80.00")
    assert obtener_saldo_total_positivo(db, cliente.id_cliente, admin.id_usuario) == Decimal("20.00")
    assert [i["monto"] for i in historial if i["tipo_transaccion"] == "nota_credito"] == [Decimal("20.00")]


def test_una_factura_anulada_con_pago_sale_como_en_el_reporte_neto_cero(db_session):
    """Contado de $100 anulada y una factura a credito de $40: el reporte termina en $40 y el historial terminaba en
    -$60 (la factura anulada quedaba en $0 con su pago de -$100 al lado)."""
    db = db_session
    admin, vendedor, producto, cliente = _escenario(db)
    credito = _credito(db, admin, vendedor, producto, cliente, 2)
    contado = _contado(db, admin, vendedor, producto, cliente, 5)
    VentaService.anular_factura(db, contado.id_factura, admin.id_usuario, "Prueba")

    historial, reporte = _afirmar_que_cuadra(db, admin, cliente.id_cliente)

    # 40 de deuda - 100 de saldo a favor (la NC de la anulacion) = -60.
    assert reporte["saldo_final"] == Decimal("-60.00")
    anulada = next(f for f in _facturas(historial) if f["id_factura"] == contado.id_factura)
    assert anulada["estado_factura"] == "ANULADA"
    assert (anulada["monto"], anulada["monto_pagado"], anulada["saldo_factura"]) == (
        Decimal("100.00"),  # lo que se habia cobrado: el cargo que el reporte tambien muestra
        Decimal("100.00"),
        Decimal("0.00"),
    )
    abierta = next(f for f in _facturas(historial) if f["id_factura"] == credito.id_factura)
    assert abierta["saldo_factura"] == Decimal("40.00")


def test_una_transferencia_conciliada_baja_el_saldo_de_la_factura(db_session):
    """La conciliacion ya salia como fila de abono pero no restaba del saldo de la factura."""
    db = db_session
    admin = crear_usuario_admin(db)
    banco = crear_cuenta_bancaria(db)
    partida = _crear_partida(db, banco, admin, Decimal("100.00"))
    cxc, cliente, _ = _crear_cxc_real(db, Decimal("80.00"))
    OtrosMovimientosService.conciliar_partida(
        db, partida.id_cuenta, cliente.id_cliente, cxc.id_cuenta_por_cobrar, Decimal("30.00"), admin.id_usuario
    )

    historial, reporte = _afirmar_que_cuadra(db, admin, cliente.id_cliente)

    assert reporte["saldo_final"] == Decimal("50.00")
    (factura,) = _facturas(historial)
    assert (factura["monto"], factura["monto_pagado"], factura["saldo_factura"]) == (
        Decimal("80.00"),
        Decimal("30.00"),
        Decimal("50.00"),
    )


# -- Lo que ya cuadraba y no debe romperse ------------------------------------------------------------------------


def test_los_pagos_normales_cuadran_con_el_reporte(db_session):
    db = db_session
    admin, vendedor, producto, cliente = _escenario(db)
    factura = _credito(db, admin, vendedor, producto, cliente, 5)
    otra = _credito(db, admin, vendedor, producto, cliente, 2)
    caja = crear_caja(db)
    CajaService.abrir_caja(db, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)
    cuenta = next(c for c in _cuentas(db, cliente) if c.id_factura == factura.id_factura)
    for monto in ("30.00", "10.00"):
        PagoService.registrar_pago_cobro(
            db,
            id_cuenta_por_cobrar=cuenta.id_cuenta_por_cobrar,
            monto=Decimal(monto),
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
            id_usuario=admin.id_usuario,
        )

    historial, reporte = _afirmar_que_cuadra(db, admin, cliente.id_cliente)

    assert reporte["saldo_final"] == Decimal("100.00")  # (100 - 40) + 40
    fila = next(f for f in _facturas(historial) if f["id_factura"] == factura.id_factura)
    assert (fila["monto_pagado"], fila["saldo_factura"]) == (Decimal("40.00"), Decimal("60.00"))
    assert otra.id_factura in {f["id_factura"] for f in _facturas(historial)}


def test_una_factura_bcv_con_abono_cuadra_con_el_reporte(db_session):
    db = db_session
    admin = crear_usuario_admin(db)
    _factura, cuenta, cliente = _emitir_credito_bcv(db, admin, precio="100.00", porcentaje="10")
    caja = crear_caja(db)
    CajaService.abrir_caja(db, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)
    PagoBCVService.registrar_pago_cobro_bcv(
        db,
        id_cuenta_por_cobrar=cuenta.id_cuenta_por_cobrar,
        monto=Decimal("40.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    _historial, reporte = _afirmar_que_cuadra(db, admin, cliente.id_cliente)

    assert reporte["saldo_final"] == Decimal("60.00")


def test_un_cliente_sin_facturas_no_rompe_la_comparacion(db_session):
    db = db_session
    admin = crear_usuario_admin(db)
    cliente = crear_cliente(db)

    historial, reporte = _historial_y_reporte(db, admin, cliente.id_cliente)

    assert historial == [] and reporte["filas"] == [] and reporte["saldo_final"] == Decimal("0.00")


def _cuentas(db, cliente):
    from app.db.models import CuentaPorCobrar, FacturaVenta

    return (
        db.query(CuentaPorCobrar)
        .join(FacturaVenta, FacturaVenta.id_factura == CuentaPorCobrar.id_factura)
        .filter(FacturaVenta.id_cliente_factura == cliente.id_cliente)
        .all()
    )
