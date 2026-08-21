from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Cliente, CuentaPorCobrar, FacturaDetalle, FacturaVenta, Inventario
from app.services.auditoria import AuditoriaService


def _generar_numero_factura(session: Session) -> str:
    ultimo_id = session.query(func.max(FacturaVenta.id_factura)).scalar() or 0
    return f"FV-{ultimo_id + 1:06d}"


def _validar_items(items: list[dict]) -> None:
    if not items:
        raise ValueError("La factura debe tener al menos un item")
    for item in items:
        if not item.get("id_producto"):
            raise ValueError("Cada item requiere id_producto")
        if not item.get("cantidad") or Decimal(str(item["cantidad"])) <= 0:
            raise ValueError("Cada item requiere una cantidad mayor a cero")
        if item.get("precio_unitario") is None:
            raise ValueError("Cada item requiere precio_unitario")


class VentaService:
    @staticmethod
    def emitir_factura(
        session: Session,
        id_cliente: int,
        id_usuario: int | None,
        id_vendedor: int | None,
        condicion_pago: str,
        items: list[dict],
        fecha_vencimiento: date | None = None,
        id_tasa: int | None = None,
        observaciones: str | None = None,
    ) -> FacturaVenta:
        _validar_items(items)

        cliente = session.get(Cliente, id_cliente)
        if cliente is None:
            raise ValueError("Cliente no encontrado")

        if condicion_pago not in ("contado", "credito"):
            raise ValueError("condicion_pago debe ser 'contado' o 'credito'")

        # --- Validar stock disponible por producto (agrupando items repetidos) ---
        cantidades_por_producto: dict[int, Decimal] = {}
        for item in items:
            id_producto = item["id_producto"]
            cantidad = Decimal(str(item["cantidad"]))
            cantidades_por_producto[id_producto] = cantidades_por_producto.get(id_producto, Decimal("0")) + cantidad

        for id_producto, cantidad_requerida in cantidades_por_producto.items():
            producto = session.get(Inventario, id_producto)
            if producto is None:
                raise ValueError(f"Producto {id_producto} no encontrado")
            if producto.cantidad_unidad < cantidad_requerida:
                raise ValueError(
                    f"Stock insuficiente para '{producto.nombre_producto}': "
                    f"disponible {producto.cantidad_unidad}, solicitado {cantidad_requerida}"
                )

        # --- Validar limite de credito del cliente ---
        total_factura = sum(
            (Decimal(str(item["cantidad"])) * Decimal(str(item["precio_unitario"])) for item in items),
            Decimal("0.00"),
        )
        if condicion_pago == "credito":
            deuda_actual = (
                session.query(func.coalesce(func.sum(CuentaPorCobrar.saldo_pendiente), 0))
                .join(FacturaVenta, FacturaVenta.id_factura == CuentaPorCobrar.id_factura)
                .filter(
                    FacturaVenta.id_cliente_factura == id_cliente,
                    CuentaPorCobrar.estado.in_(("pendiente", "parcial", "vencida")),
                )
                .scalar()
            )
            if deuda_actual + total_factura > cliente.limite_credito:
                raise ValueError(
                    f"El cliente excede su limite de credito: deuda actual {deuda_actual} + "
                    f"nueva factura {total_factura} > limite {cliente.limite_credito}"
                )

        # --- Insercion atomica de cabecera y lineas ---
        factura = FacturaVenta(
            numero_factura=_generar_numero_factura(session),
            id_cliente_factura=id_cliente,
            id_usuario_factura=id_usuario,
            id_vendedor=id_vendedor,
            condicion_pago=condicion_pago,
            fecha_vencimiento=fecha_vencimiento,
            id_tasa_factura=id_tasa,
            observaciones_factura=observaciones,
        )
        session.add(factura)
        session.flush()

        for item in items:
            session.add(
                FacturaDetalle(
                    id_factura=factura.id_factura,
                    id_producto_factura=item["id_producto"],
                    descripcion=item.get("descripcion"),
                    cantidad_producto=item["cantidad"],
                    observaciones_item=item.get("observaciones"),
                    precio_unitario=item["precio_unitario"],
                )
            )

        session.commit()
        session.refresh(factura)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="EMISION_FACTURA",
            modulo="VENTAS",
            detalle={
                "numero_factura": factura.numero_factura,
                "id_cliente": id_cliente,
                "condicion_pago": condicion_pago,
                "total_venta": str(factura.total_venta),
            },
        )
        return factura

    @staticmethod
    def anular_factura(session: Session, id_factura: int, id_usuario: int | None, motivo: str) -> FacturaVenta:
        """Marca la factura como ANULADA y registra el evento en auditoria.

        No revierte stock ni cuentas por cobrar automaticamente: los triggers de stock
        (trg_factura_detalle_stock_*) y de totales solo reaccionan a INSERT/UPDATE/DELETE
        sobre factura_detalle, no a un cambio de estado_factura. Si se requiere reponer
        stock o cancelar la cuenta por cobrar, debe hacerse explicitamente (por ejemplo
        eliminando las lineas de factura_detalle, lo cual si dispara esos triggers).
        """
        if not motivo:
            raise ValueError("motivo es requerido para anular una factura")

        factura = session.get(FacturaVenta, id_factura)
        if factura is None:
            raise ValueError("Factura no encontrada")
        if factura.estado_factura == "ANULADA":
            raise ValueError("La factura ya esta anulada")

        factura.estado_factura = "ANULADA"
        factura.modificado_por = id_usuario
        session.commit()
        session.refresh(factura)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="ANULACION_FACTURA",
            modulo="VENTAS",
            detalle={"numero_factura": factura.numero_factura, "motivo": motivo},
        )
        return factura

    @staticmethod
    def listar_facturas(
        session: Session,
        fecha_desde: date | datetime | None = None,
        fecha_hasta: date | datetime | None = None,
        id_cliente: int | None = None,
        condicion_pago: str | None = None,
        estado: str | None = None,
        pagina: int = 1,
        por_pagina: int = 20,
    ) -> dict:
        query = session.query(FacturaVenta)
        if fecha_desde:
            query = query.filter(FacturaVenta.fecha_emision >= fecha_desde)
        if fecha_hasta:
            query = query.filter(FacturaVenta.fecha_emision <= fecha_hasta)
        if id_cliente:
            query = query.filter(FacturaVenta.id_cliente_factura == id_cliente)
        if condicion_pago:
            query = query.filter(FacturaVenta.condicion_pago == condicion_pago)
        if estado:
            query = query.filter(FacturaVenta.estado_factura == estado)

        total = query.count()
        facturas = (
            query.order_by(FacturaVenta.fecha_emision.desc())
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
            .all()
        )
        return {"items": facturas, "total": total, "pagina": pagina, "por_pagina": por_pagina}
