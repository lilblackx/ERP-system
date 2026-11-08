from decimal import Decimal

from app.services.historial_cliente import obtener_historial_cliente
from app.services.ventas import VentaService
from tests.factories import (
    crear_cliente,
    crear_precio_producto,
    crear_producto,
    crear_usuario_admin,
    crear_vendedor,
)


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
    crear_precio_producto(db_session, producto, "50.00")
    cliente = crear_cliente(db_session, limite_credito=Decimal("1000.00"), dias_credito=10)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[
            {
                "id_producto": producto.id_producto,
                "cantidad": 1,
                "precio_unitario": "50.00",
            }
        ],
    )
    assert factura.dias_credito_aplicados == 10

    # El cliente cambia sus dias de credito configurados DESPUES de emitida la factura.
    cliente.dias_credito = 60
    db_session.commit()

    historial = obtener_historial_cliente(db_session, cliente.id_cliente)
    item = next(i for i in historial if i["id_factura"] == factura.id_factura)

    assert item["dias_credito"] == 10


# -- Vistas del historial (filtrar_historial / monto_para_vista / total_pagado) y campos de pago ---------------

import pytest  # noqa: E402

from app.services.historial_cliente import (  # noqa: E402
    VISTA_FACTURAS,
    VISTA_PAGOS,
    VISTA_TODOS,
    filtrar_historial,
    monto_para_vista,
    total_pagado,
)

_TIPOS = ["pago", "factura", "nota_credito", "pago", "devolucion_nota_credito", "factura"]
_HIST = [{"tipo_transaccion": t, "monto": Decimal("-10.00") if t == "pago" else Decimal("10.00")} for t in _TIPOS]


def test_filtrar_historial_por_vista():
    assert [i["tipo_transaccion"] for i in filtrar_historial(_HIST, VISTA_FACTURAS)] == [
        "factura",
        "nota_credito",
        "devolucion_nota_credito",
        "factura",
    ]
    assert [i["tipo_transaccion"] for i in filtrar_historial(_HIST, VISTA_PAGOS)] == ["pago", "pago"]
    assert filtrar_historial(_HIST, VISTA_TODOS) == _HIST


def test_filtrar_historial_no_modifica_la_lista_original_y_rechaza_vistas_desconocidas():
    copia = list(_HIST)

    filtrar_historial(_HIST, VISTA_FACTURAS)
    assert _HIST == copia
    with pytest.raises(ValueError):
        filtrar_historial(_HIST, "otra")


def test_monto_para_vista_solo_invierte_el_signo_de_los_abonos_en_la_vista_de_pagos():
    abono, factura = _HIST[0], _HIST[1]

    assert monto_para_vista(abono, VISTA_PAGOS) == Decimal("10.00")
    assert monto_para_vista(abono, VISTA_TODOS) == Decimal("-10.00")
    assert monto_para_vista(factura, VISTA_PAGOS) == Decimal("10.00")  # no es un abono: sin cambio


def test_total_pagado_suma_los_abonos_en_positivo():
    assert total_pagado(_HIST) == Decimal("20.00")
    assert total_pagado([]) == Decimal("0.00")


def test_la_factura_del_historial_trae_lo_pagado_y_su_saldo(db_session):
    from app.services.pagos import PagoService
    from app.services.tesoreria import CajaService
    from tests.factories import crear_caja

    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=10)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session, limite_credito=Decimal("1000.00"))
    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
    )
    from app.db.models import CuentaPorCobrar

    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)
    for monto in ("30.00", "10.00"):
        PagoService.registrar_pago_cobro(
            db_session,
            id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
            monto=Decimal(monto),
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
            id_usuario=admin.id_usuario,
        )

    historial = obtener_historial_cliente(db_session, cliente.id_cliente)
    item = next(i for i in historial if i["tipo_transaccion"] == "factura")
    abonos = [i for i in historial if i["tipo_transaccion"] == "pago"]

    assert (item["monto_pagado"], item["saldo_factura"]) == (Decimal("40.00"), Decimal("60.00"))
    assert item["saldo_corrido"] == Decimal("60.00")  # los abonos ocultos no cambian el saldo
    assert sorted(a["monto"] for a in abonos) == [Decimal("-30.00"), Decimal("-10.00")]
    assert total_pagado(historial) == Decimal("40.00")
    assert filtrar_historial(historial, VISTA_FACTURAS) == [item]


def test_el_historial_no_hace_una_consulta_por_factura(db_session):
    """La cuenta por cobrar de cada factura se trae en una sola consulta: con 3 000 facturas el historial hacia 3 000
    consultas y tardaba segundos. El numero de consultas no debe crecer con el numero de facturas."""
    from sqlalchemy import event

    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "10.00")
    cliente = crear_cliente(db_session, limite_credito=Decimal("1000.00"))

    def emitir_facturas(cantidad: int) -> None:
        for _ in range(cantidad):
            VentaService.emitir_factura(
                db_session,
                id_cliente=cliente.id_cliente,
                id_usuario=admin.id_usuario,
                id_vendedor=vendedor.id_vendedor,
                condicion_pago="credito",
                items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "10.00"}],
            )

    def contar_consultas() -> int:
        consultas = []
        motor = db_session.get_bind()
        db_session.expire_all()

        def registrar(*args):
            consultas.append(args[2])

        event.listen(motor, "before_cursor_execute", registrar)
        try:
            obtener_historial_cliente(db_session, cliente.id_cliente)
        finally:
            event.remove(motor, "before_cursor_execute", registrar)
        return len(consultas)

    emitir_facturas(2)
    con_dos = contar_consultas()
    emitir_facturas(4)
    con_seis = contar_consultas()

    assert con_seis == con_dos
