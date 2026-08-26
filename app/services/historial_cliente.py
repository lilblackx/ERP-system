"""Servicio para obtener el historial de facturas y pagos de un cliente."""

from decimal import Decimal
from typing import TypedDict

from sqlalchemy.orm import Session, joinedload

from app.db.models import CuentaPorCobrar, FacturaVenta, PagoCobro


class HistorialItem(TypedDict):
    """Representa un item del historial del cliente."""

    id_cuenta: int | None
    id_factura: int
    numero_factura: str
    fecha_emision: str
    fecha_vencimiento: str | None
    total_venta: Decimal
    estado_factura: str
    condicion_pago: str
    dias_credito: int | None
    observaciones_factura: str | None
    total_pagado: Decimal
    saldo_pendiente: Decimal
    metodo_pago: str | None


def obtener_historial_cliente(session: Session, id_cliente: int) -> list[HistorialItem]:
    """
    Obtiene el historial de facturas y pagos de un cliente.

    Args:
        session: Sesión de SQLAlchemy
        id_cliente: ID del cliente

    Returns:
        Lista de items del historial con facturas, pagos y saldos pendientes
    """
    # Obtener facturas del cliente con sus cuentas por cobrar
    facturas = (
        session.query(FacturaVenta)
        .options(joinedload(FacturaVenta.cliente))
        .filter(FacturaVenta.id_cliente_factura == id_cliente)
        .order_by(FacturaVenta.fecha_emision.desc())
        .all()
    )

    historial: list[HistorialItem] = []

    for factura in facturas:
        # Obtener cuenta por cobrar de esta factura
        cxc = session.query(CuentaPorCobrar).filter(CuentaPorCobrar.id_factura == factura.id_factura).first()

        # Obtener pagos realizados para esta cuenta por cobrar
        pagos: list[PagoCobro] = []
        if cxc:
            pagos = session.query(PagoCobro).filter(PagoCobro.id_cuenta_por_cobrar == cxc.id_cuenta_por_cobrar).all()

        # Calcular total pagado
        total_pagado = Decimal(sum(pago.monto for pago in pagos))

        # Saldo pendiente (si no hay CxC, es el total de la factura)
        if cxc:
            saldo_pendiente = cxc.saldo_pendiente
        else:
            saldo_pendiente = factura.total_venta - total_pagado

        # Formatear fechas
        fecha_emision_str = factura.fecha_emision.strftime("%Y-%m-%d") if factura.fecha_emision else ""
        fecha_vencimiento_str = factura.fecha_vencimiento.strftime("%Y-%m-%d") if factura.fecha_vencimiento else None

        # Obtener días de crédito del cliente
        dias_credito = factura.cliente.dias_credito if factura.cliente else None

        # Obtener método de pago (para ventas de contado)
        metodo_pago = None
        if factura.condicion_pago == "contado" and pagos:
            metodo_pago = pagos[0].metodo_pago

        item: HistorialItem = {
            "id_cuenta": cxc.id_cuenta_por_cobrar if cxc else None,
            "id_factura": factura.id_factura,
            "numero_factura": factura.numero_factura or "",
            "fecha_emision": fecha_emision_str,
            "fecha_vencimiento": fecha_vencimiento_str,
            "total_venta": factura.total_venta,
            "estado_factura": factura.estado_factura or "EMITIDA",
            "condicion_pago": factura.condicion_pago or "",
            "dias_credito": dias_credito,
            "observaciones_factura": factura.observaciones_factura,
            "total_pagado": total_pagado,
            "saldo_pendiente": saldo_pendiente,
            "metodo_pago": metodo_pago,
        }

        historial.append(item)

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
