"""Servicio para obtener el historial de facturas y pagos de un cliente."""

from decimal import Decimal
from typing import Literal, TypedDict

from sqlalchemy.orm import Session, joinedload

from app.db.models import CuentaBancaria, CuentaPorCobrar, FacturaVenta, PagoCobro


class HistorialItem(TypedDict):
    """Representa un item del historial del cliente."""

    tipo_transaccion: Literal["factura", "pago"]
    id_cuenta: int | None
    id_factura: int | None
    id_pago: int | None
    numero_factura: str
    fecha: str
    fecha_vencimiento: str | None
    monto: Decimal
    estado_factura: str | None
    condicion_pago: str | None
    dias_credito: int | None
    observaciones: str | None
    metodo_pago: str | None
    monto_vuelto: Decimal
    metodo_vuelto: str | None
    saldo_corrido: Decimal


def obtener_historial_cliente(session: Session, id_cliente: int) -> list[HistorialItem]:
    """
    Obtiene el historial de facturas y pagos de un cliente.

    Las transacciones se agrupan por factura: cada factura se muestra con sus
    pagos asociados. El saldo corrido se calcula acumulativamente por factura.

    Args:
        session: Sesión de SQLAlchemy
        id_cliente: ID del cliente

    Returns:
        Lista de items del historial con transacciones agrupadas por factura
    """
    # Obtener facturas del cliente con sus cuentas por cobrar
    facturas = (
        session.query(FacturaVenta)
        .options(joinedload(FacturaVenta.cliente))
        .filter(FacturaVenta.id_cliente_factura == id_cliente)
        .order_by(FacturaVenta.fecha_emision.desc())
        .all()
    )

    # Obtener todos los pagos del cliente a través de sus cuentas por cobrar
    pagos = (
        session.query(PagoCobro)
        .join(CuentaPorCobrar, PagoCobro.id_cuenta_por_cobrar == CuentaPorCobrar.id_cuenta_por_cobrar)
        .join(FacturaVenta, CuentaPorCobrar.id_factura == FacturaVenta.id_factura)
        .filter(FacturaVenta.id_cliente_factura == id_cliente)
        .options(
            joinedload(PagoCobro.cuenta_bancaria).joinedload(CuentaBancaria.banco),
            joinedload(PagoCobro.caja),
            joinedload(PagoCobro.cuenta_por_cobrar).joinedload(CuentaPorCobrar.factura),
        )
        .order_by(PagoCobro.fecha_pago.desc())
        .all()
    )

    # Agrupar pagos por factura
    pagos_por_factura: dict[int, list] = {}
    for pago in pagos:
        cxc = pago.cuenta_por_cobrar
        if cxc and cxc.id_factura:
            if cxc.id_factura not in pagos_por_factura:
                pagos_por_factura[cxc.id_factura] = []
            pagos_por_factura[cxc.id_factura].append(pago)

    # Construir historial agrupado por factura
    historial: list[HistorialItem] = []

    for factura in facturas:
        cxc = session.query(CuentaPorCobrar).filter(CuentaPorCobrar.id_factura == factura.id_factura).first()
        fecha_emision_str = factura.fecha_emision.strftime("%Y-%m-%d %H:%M") if factura.fecha_emision else ""
        fecha_vencimiento_str = factura.fecha_vencimiento.strftime("%Y-%m-%d") if factura.fecha_vencimiento else None

        # Agregar la factura
        item_factura: HistorialItem = {
            "tipo_transaccion": "factura",
            "id_cuenta": cxc.id_cuenta_por_cobrar if cxc else None,
            "id_factura": factura.id_factura,
            "id_pago": None,
            "numero_factura": factura.numero_factura or "",
            "fecha": fecha_emision_str,
            "fecha_vencimiento": fecha_vencimiento_str,
            "monto": factura.total_venta,
            "estado_factura": factura.estado_factura or "EMITIDA",
            "condicion_pago": factura.condicion_pago or "",
            "dias_credito": factura.dias_credito_aplicados,
            "observaciones": factura.observaciones_factura,
            "metodo_pago": None,
            "monto_vuelto": factura.monto_vuelto,
            "metodo_vuelto": factura.metodo_vuelto,
            "saldo_corrido": cxc.saldo_pendiente if cxc else Decimal("0.00"),
        }
        historial.append(item_factura)

        # Agregar los pagos de esta factura
        if factura.id_factura in pagos_por_factura:
            for pago in pagos_por_factura[factura.id_factura]:
                fecha_pago_str = pago.fecha_pago.strftime("%Y-%m-%d %H:%M") if pago.fecha_pago else ""
                cxc_pago = pago.cuenta_por_cobrar

                # Construir observaciones con bolivares, tasa y banco
                observaciones = ""

                # Agregar bolivares y tasa si es transferencia
                if pago.metodo_pago == "transferencia" and pago.monto_moneda_origen and pago.tasa:
                    # Determinar qué tasa se usó comparando con los campos del registro
                    tasa_usada = None
                    tipo_tasa = ""

                    if (
                        pago.tasa.tasa_dolar_bcv
                        and pago.monto / pago.monto_moneda_origen
                        == float(pago.tasa.tasa_dolar_bcv)
                    ):
                        tasa_usada = pago.tasa.tasa_dolar_bcv
                        tipo_tasa = "BCV"
                    elif (
                        pago.tasa.tasa_dolar_paralelo
                        and pago.monto / pago.monto_moneda_origen
                        == float(pago.tasa.tasa_dolar_paralelo)
                    ):
                        tasa_usada = pago.tasa.tasa_dolar_paralelo
                        tipo_tasa = "Paralelo"
                    elif (
                        pago.tasa.tasa_cop
                        and pago.monto / pago.monto_moneda_origen
                        == float(pago.tasa.tasa_cop)
                    ):
                        tasa_usada = pago.tasa.tasa_cop
                        tipo_tasa = "COP"

                    if tasa_usada:
                        observaciones = (
                            f"Bs({pago.monto_moneda_origen:,.2f}) - {tipo_tasa}: {tasa_usada:,.2f}"
                        )
                    else:
                        # Fallback: mostrar BCV si no se puede determinar
                        if pago.tasa.tasa_dolar_bcv:
                            observaciones = (
                                f"Bs({pago.monto_moneda_origen:,.2f}) - BCV: "
                                f"{pago.tasa.tasa_dolar_bcv:,.2f}"
                            )
                        else:
                            observaciones = f"Bs({pago.monto_moneda_origen:,.2f})"

                # Agregar banco si existe
                if pago.cuenta_bancaria:
                    banco = pago.cuenta_bancaria.banco
                    nombre_banco = banco.nombre_banco if banco else ""
                    if nombre_banco:
                        if observaciones:
                            observaciones += f" - ({nombre_banco})"
                        else:
                            observaciones = f"({nombre_banco})"

                item_pago: HistorialItem = {
                    "tipo_transaccion": "pago",
                    "id_cuenta": cxc_pago.id_cuenta_por_cobrar if cxc_pago else None,
                    "id_factura": factura.id_factura,
                    "id_pago": pago.id_pago_cobro,
                    "numero_factura": factura.numero_factura or "",
                    "fecha": fecha_pago_str,
                    "fecha_vencimiento": None,
                    "monto": -pago.monto,  # Negativo para restar del saldo
                    "estado_factura": None,
                    "condicion_pago": None,
                    "dias_credito": None,
                    "observaciones": observaciones,
                    "metodo_pago": pago.metodo_pago,
                    "monto_vuelto": Decimal("0.00"),
                    "metodo_vuelto": None,
                    "saldo_corrido": Decimal("0.00"),  # No aplica para pagos individuales
                }
                historial.append(item_pago)

    return historial


def obtener_saldo_total_pendiente(session: Session, id_cliente: int) -> Decimal:
    """
    Calcula el saldo total pendiente de un cliente sumando todas sus cuentas por cobrar.

    Args:
        session: Sesión de SQLAlchemy
        id_cliente: ID del cliente

    Returns:
        Saldo total pendiente
    """
    # Sumar saldos pendientes de cuentas por cobrar del cliente
    total = (
        session.query(CuentaPorCobrar)
        .join(FacturaVenta, CuentaPorCobrar.id_factura == FacturaVenta.id_factura)
        .filter(FacturaVenta.id_cliente_factura == id_cliente)
        .filter(CuentaPorCobrar.estado.in_(["pendiente", "parcial", "vencida"]))
        .with_entities(CuentaPorCobrar.saldo_pendiente)
        .all()
    )

    return sum((saldo[0] for saldo in total), Decimal("0")) if total else Decimal("0.00")
