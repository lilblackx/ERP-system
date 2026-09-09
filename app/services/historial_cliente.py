"""Servicio para obtener el historial de facturas y pagos de un cliente."""

from decimal import Decimal
from typing import Literal, TypedDict

from sqlalchemy.orm import Session, joinedload

from app.db.models import CuentaPorCobrar, FacturaVenta, PagoCobro


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

    Las transacciones (facturas y pagos) se ordenan cronológicamente y el saldo
    corrido se calcula acumulativamente. Las facturas aumentan el saldo (cargos)
    y los pagos lo disminuyen (abonos).

    Args:
        session: Sesión de SQLAlchemy
        id_cliente: ID del cliente

    Returns:
        Lista de items del historial con transacciones y saldo corrido acumulativo
    """
    # Obtener facturas del cliente con sus cuentas por cobrar
    facturas = (
        session.query(FacturaVenta)
        .options(joinedload(FacturaVenta.cliente))
        .filter(FacturaVenta.id_cliente_factura == id_cliente)
        .all()
    )

    # Obtener todos los pagos del cliente a través de sus cuentas por cobrar
    pagos = (
        session.query(PagoCobro)
        .join(CuentaPorCobrar, PagoCobro.id_cuenta_por_cobrar == CuentaPorCobrar.id_cuenta_por_cobrar)
        .join(FacturaVenta, CuentaPorCobrar.id_factura == FacturaVenta.id_factura)
        .filter(FacturaVenta.id_cliente_factura == id_cliente)
        .options(
            joinedload(PagoCobro.cuenta_bancaria),
            joinedload(PagoCobro.caja),
            joinedload(PagoCobro.cuenta_por_cobrar).joinedload(CuentaPorCobrar.factura),
        )
        .all()
    )

    # Construir lista de transacciones (facturas y pagos)
    transacciones: list[dict] = []

    # Agregar facturas como transacciones de cargo
    for factura in facturas:
        cxc = session.query(CuentaPorCobrar).filter(CuentaPorCobrar.id_factura == factura.id_factura).first()
        fecha_emision_str = factura.fecha_emision.strftime("%Y-%m-%d %H:%M") if factura.fecha_emision else ""
        fecha_vencimiento_str = factura.fecha_vencimiento.strftime("%Y-%m-%d") if factura.fecha_vencimiento else None

        transacciones.append(
            {
                "tipo": "factura",
                "fecha": fecha_emision_str,
                "fecha_obj": factura.fecha_emision,
                "id_cuenta": cxc.id_cuenta_por_cobrar if cxc else None,
                "id_factura": factura.id_factura,
                "id_pago": None,
                "numero_factura": factura.numero_factura or "",
                "monto": factura.total_venta,
                "estado_factura": factura.estado_factura or "EMITIDA",
                "condicion_pago": factura.condicion_pago or "",
                "dias_credito": factura.dias_credito_aplicados,
                "observaciones": factura.observaciones_factura,
                "metodo_pago": None,
                "monto_vuelto": factura.monto_vuelto,
                "metodo_vuelto": factura.metodo_vuelto,
                "fecha_vencimiento": fecha_vencimiento_str,
            }
        )

    # Agregar pagos como transacciones de abono
    for pago in pagos:
        fecha_pago_str = pago.fecha_pago.strftime("%Y-%m-%d %H:%M") if pago.fecha_pago else ""
        cxc = pago.cuenta_por_cobrar
        factura = cxc.factura if cxc else None
        numero_factura = factura.numero_factura if factura else "N/A"

        # Construir observaciones con bolivares y tasa si es transferencia
        observaciones = f"Abono - {pago.metodo_pago}"
        if pago.metodo_pago == "transferencia" and pago.monto_moneda_origen:
            tasa_bcv = pago.tasa.tasa_dolar_bcv if pago.tasa else None
            if tasa_bcv:
                observaciones += f" - Bs {pago.monto_moneda_origen:,.2f} @ {tasa_bcv:,.2f}"
            else:
                observaciones += f" - Bs {pago.monto_moneda_origen:,.2f}"

        transacciones.append(
            {
                "tipo": "pago",
                "fecha": fecha_pago_str,
                "fecha_obj": pago.fecha_pago,
                "id_cuenta": cxc.id_cuenta_por_cobrar if cxc else None,
                "id_factura": factura.id_factura if factura else None,
                "id_pago": pago.id_pago_cobro,
                "numero_factura": numero_factura,
                "monto": -pago.monto,  # Negativo para restar del saldo
                "estado_factura": None,
                "condicion_pago": None,
                "dias_credito": None,
                "observaciones": observaciones,
                "metodo_pago": pago.metodo_pago,
                "monto_vuelto": Decimal("0.00"),
                "metodo_vuelto": None,
                "fecha_vencimiento": None,
            }
        )

    # Ordenar transacciones cronológicamente
    transacciones.sort(key=lambda x: (x["fecha_obj"], x["tipo"] == "pago"))

    # Calcular saldo corrido acumulativo
    saldo_corrido_acumulado = Decimal("0.00")
    historial: list[HistorialItem] = []

    for trans in transacciones:
        saldo_corrido_acumulado += trans["monto"]

        item: HistorialItem = {
            "tipo_transaccion": trans["tipo"],
            "id_cuenta": trans["id_cuenta"],
            "id_factura": trans["id_factura"],
            "id_pago": trans["id_pago"],
            "numero_factura": trans["numero_factura"],
            "fecha": trans["fecha"],
            "fecha_vencimiento": trans["fecha_vencimiento"],
            "monto": trans["monto"],
            "estado_factura": trans["estado_factura"],
            "condicion_pago": trans["condicion_pago"],
            "dias_credito": trans["dias_credito"],
            "observaciones": trans["observaciones"],
            "metodo_pago": trans["metodo_pago"],
            "monto_vuelto": trans["monto_vuelto"],
            "metodo_vuelto": trans["metodo_vuelto"],
            "saldo_corrido": saldo_corrido_acumulado,
        }

        historial.append(item)

    # Invertir el orden para mostrar las transacciones más recientes primero
    historial.reverse()

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
