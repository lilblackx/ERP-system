"""Servicio para obtener el historial de facturas y pagos de un cliente."""

from decimal import Decimal
from typing import Literal, TypedDict

from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    CuentaBancaria,
    CuentaPorCobrar,
    CuentaPorCobrarBCV,
    FacturaVenta,
    NotaCreditoCliente,
    PagoCobro,
    PagoCobroBCV,
)


class HistorialItem(TypedDict):
    """Representa un item del historial del cliente."""

    tipo_transaccion: Literal["factura", "pago", "nota_credito", "devolucion_nota_credito"]
    id_cuenta: int | None
    id_factura: int | None
    id_pago: int | None
    id_nota_credito: int | None
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
    Obtiene el historial de facturas, pagos y notas de crédito de un cliente.

    Las transacciones se agrupan por factura: cada factura se muestra con sus
    pagos asociados. El saldo corrido se calcula acumulativamente por factura.
    Las notas de crédito disponibles se muestran como saldo a favor.

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
        .join(
            CuentaPorCobrar,
            PagoCobro.id_cuenta_por_cobrar == CuentaPorCobrar.id_cuenta_por_cobrar,
        )
        .join(FacturaVenta, CuentaPorCobrar.id_factura == FacturaVenta.id_factura)
        .filter(FacturaVenta.id_cliente_factura == id_cliente)
        .options(
            joinedload(PagoCobro.cuenta_bancaria).joinedload(CuentaBancaria.banco),
            joinedload(PagoCobro.caja),
            joinedload(PagoCobro.cuenta_por_cobrar).joinedload(CuentaPorCobrar.factura),
            joinedload(PagoCobro.tasa),
        )
        .order_by(PagoCobro.fecha_pago.desc())
        .all()
    )

    # Pagos de las cuentas por cobrar BCV (tabla aparte, ver migrations/0078): sin esto, un
    # abono a una factura con porcentaje BCV no aparecia en el historial.
    pagos_bcv = (
        session.query(PagoCobroBCV)
        .join(
            CuentaPorCobrarBCV,
            PagoCobroBCV.id_cuenta_por_cobrar == CuentaPorCobrarBCV.id_cuenta_por_cobrar,
        )
        .join(FacturaVenta, CuentaPorCobrarBCV.id_factura == FacturaVenta.id_factura)
        .filter(FacturaVenta.id_cliente_factura == id_cliente)
        .options(
            joinedload(PagoCobroBCV.cuenta_bancaria).joinedload(CuentaBancaria.banco),
            joinedload(PagoCobroBCV.cuenta_por_cobrar),
        )
        .all()
    )

    # Obtener notas de crédito disponibles del cliente
    notas_credito = (
        session.query(NotaCreditoCliente)
        .filter(NotaCreditoCliente.id_cliente == id_cliente)
        .filter(NotaCreditoCliente.estado == "disponible")
        .order_by(NotaCreditoCliente.fecha_creacion.desc())
        .all()
    )

    # Obtener notas de crédito devueltas del cliente
    notas_devueltas = (
        session.query(NotaCreditoCliente)
        .filter(NotaCreditoCliente.id_cliente == id_cliente)
        .filter(NotaCreditoCliente.estado == "devuelta")
        .order_by(NotaCreditoCliente.fecha_creacion.desc())
        .all()
    )

    # Agrupar pagos por factura (normales y BCV juntos, el más reciente primero)
    pagos_por_factura: dict[int, list] = {}
    for pago in [*pagos, *pagos_bcv]:
        cxc = pago.cuenta_por_cobrar
        if cxc and cxc.id_factura:
            pagos_por_factura.setdefault(cxc.id_factura, []).append(pago)
    for lista in pagos_por_factura.values():
        lista.sort(key=lambda p: p.fecha_pago, reverse=True)

    # Construir historial agrupado por factura
    historial: list[HistorialItem] = []

    for factura in facturas:
        cxc = session.query(CuentaPorCobrar).filter(CuentaPorCobrar.id_factura == factura.id_factura).first()
        # Una factura con porcentaje BCV deja su cuenta normal en saldo 0 y lleva la deuda real
        # en cuentas_por_cobrar_bcv: sin mirarla, el historial mostraba saldo 0 estando pendiente.
        cxc_bcv = (
            session.query(CuentaPorCobrarBCV)
            .filter(CuentaPorCobrarBCV.id_factura == factura.id_factura, CuentaPorCobrarBCV.porcentaje > 0)
            .first()
        )
        fecha_emision_str = factura.fecha_emision.strftime("%Y-%m-%d %H:%M") if factura.fecha_emision else ""
        fecha_vencimiento_str = factura.fecha_vencimiento.strftime("%Y-%m-%d") if factura.fecha_vencimiento else None

        # Agregar la factura
        item_factura: HistorialItem = {
            "tipo_transaccion": "factura",
            "id_cuenta": cxc.id_cuenta_por_cobrar if cxc else None,
            "id_factura": factura.id_factura,
            "id_pago": None,
            "id_nota_credito": None,
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
            "saldo_corrido": (
                cxc_bcv.saldo_pendiente if cxc_bcv else (cxc.saldo_pendiente if cxc else Decimal("0.00"))
            ),
        }
        historial.append(item_factura)

        # Agregar los pagos de esta factura
        if factura.id_factura in pagos_por_factura:
            for pago in pagos_por_factura[factura.id_factura]:
                fecha_pago_str = pago.fecha_pago.strftime("%Y-%m-%d %H:%M") if pago.fecha_pago else ""
                cxc_pago = pago.cuenta_por_cobrar

                # Construir observaciones con bolivares, tasa y banco
                observaciones = ""

                # Usar campos directos monto_bolivares y tasa_cambio
                monto_bs = pago.monto_bolivares or pago.monto_moneda_origen
                tasa = pago.tasa_cambio

                if monto_bs and tasa:
                    observaciones = f"Bs. {monto_bs:,.2f} - {tasa:,.2f}"
                elif monto_bs:
                    observaciones = f"Bs. {monto_bs:,.2f}"

                # Agregar banco si existe
                if pago.cuenta_bancaria:
                    banco = pago.cuenta_bancaria.banco
                    nombre_banco = banco.nombre_banco if banco else ""
                    if nombre_banco:
                        if observaciones:
                            observaciones += f" - {nombre_banco}"
                        else:
                            observaciones = nombre_banco

                id_pago = pago.id_pago_cobro_bcv if isinstance(pago, PagoCobroBCV) else pago.id_pago_cobro
                item_pago: HistorialItem = {
                    "tipo_transaccion": "pago",
                    "id_cuenta": cxc_pago.id_cuenta_por_cobrar if cxc_pago else None,
                    "id_factura": factura.id_factura,
                    "id_pago": id_pago,
                    "id_nota_credito": None,
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

    # Agregar notas de crédito disponibles como saldo a favor
    for nota in notas_credito:
        fecha_creacion_str = nota.fecha_creacion.strftime("%Y-%m-%d %H:%M") if nota.fecha_creacion else ""

        item_nota: HistorialItem = {
            "tipo_transaccion": "nota_credito",
            "id_cuenta": None,
            "id_factura": nota.id_factura_origen,
            "id_pago": None,
            "id_nota_credito": nota.id_nota_credito,
            "numero_factura": nota.numero_nota_credito or "",
            "fecha": fecha_creacion_str,
            "fecha_vencimiento": None,
            "monto": nota.saldo_disponible,  # Positivo (saldo a favor)
            "estado_factura": nota.estado,
            "condicion_pago": None,
            "dias_credito": None,
            "observaciones": nota.motivo or "Saldo a favor",
            "metodo_pago": None,
            "monto_vuelto": Decimal("0.00"),
            "metodo_vuelto": None,
            "saldo_corrido": nota.saldo_disponible,
        }
        historial.append(item_nota)

    # Agregar notas de crédito devueltas
    for nota in notas_devueltas:
        fecha_creacion_str = nota.fecha_creacion.strftime("%Y-%m-%d %H:%M") if nota.fecha_creacion else ""

        item_devolucion: HistorialItem = {
            "tipo_transaccion": "devolucion_nota_credito",
            "id_cuenta": None,
            "id_factura": nota.id_factura_origen,
            "id_pago": None,
            "id_nota_credito": nota.id_nota_credito,
            "numero_factura": nota.numero_nota_credito or "",
            "fecha": fecha_creacion_str,
            "fecha_vencimiento": None,
            "monto": nota.monto - nota.saldo_disponible,  # Monto devuelto (monto original - saldo restante)
            "estado_factura": nota.estado,
            "condicion_pago": None,
            "dias_credito": None,
            "observaciones": nota.motivo or "Devolución de nota de crédito",
            "metodo_pago": None,
            "monto_vuelto": Decimal("0.00"),
            "metodo_vuelto": None,
            "saldo_corrido": Decimal("0.00"),
        }
        historial.append(item_devolucion)

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


def obtener_saldo_total_positivo(session: Session, id_cliente: int) -> Decimal:
    """
    Calcula el saldo total positivo (a favor) de un cliente sumando sus notas de crédito disponibles.

    Args:
        session: Sesión de SQLAlchemy
        id_cliente: ID del cliente

    Returns:
        Saldo total positivo (notas de crédito disponibles)
    """
    # Sumar saldos disponibles de notas de crédito del cliente
    total = (
        session.query(NotaCreditoCliente)
        .filter(NotaCreditoCliente.id_cliente == id_cliente)
        .filter(NotaCreditoCliente.estado == "disponible")
        .with_entities(NotaCreditoCliente.saldo_disponible)
        .all()
    )

    return sum((saldo[0] for saldo in total), Decimal("0")) if total else Decimal("0.00")
