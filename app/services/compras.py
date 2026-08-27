import logging
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Compra, CompraDetalle, CuentaPorPagar, Inventario, PagoProveedor, Proveedor
from app.services.auditoria import AuditoriaService
from app.services.notas_credito import NotaCreditoService
from app.services.permisos import require_permiso

logger = logging.getLogger(__name__)


def _generar_numero_compra(session: Session) -> str:
    ultimo_id = session.query(func.max(Compra.id_compra)).scalar() or 0
    return f"OC-{ultimo_id + 1:06d}"


def _validar_items(items: list[dict]) -> None:
    if not items:
        raise ValueError("La compra debe tener al menos un item")
    for item in items:
        if not item.get("id_producto"):
            raise ValueError("Cada item requiere id_producto")
        if not item.get("cantidad") or Decimal(str(item["cantidad"])) <= 0:
            raise ValueError("Cada item requiere una cantidad mayor a cero")
        if item.get("costo_unitario") is None:
            raise ValueError("Cada item requiere costo_unitario")


class CompraService:
    @staticmethod
    def registrar_compra(
        session: Session,
        id_proveedor: int,
        id_usuario: int | None,
        condicion_pago: str,
        items: list[dict],
        fecha_vencimiento: date | None = None,
        id_tasa: int | None = None,
        observaciones: str | None = None,
    ) -> Compra:
        require_permiso(session, id_usuario, "compras", "crear")
        _validar_items(items)

        proveedor = session.get(Proveedor, id_proveedor)
        if proveedor is None:
            raise ValueError("Proveedor no encontrado")
        if proveedor.estado_proveedor != "ACTIVO":
            raise ValueError(f"El proveedor '{proveedor.nombre_razon_social}' esta inactivo")

        if condicion_pago not in ("contado", "credito"):
            raise ValueError("condicion_pago debe ser 'contado' o 'credito'")

        # --- Validar que los productos existan y esten activos (agrupando repetidos) ---
        for id_producto in {item["id_producto"] for item in items}:
            producto = session.get(Inventario, id_producto)
            if producto is None:
                raise ValueError(f"Producto {id_producto} no encontrado")
            if producto.estado_producto != "ACTIVO":
                raise ValueError(f"El producto '{producto.nombre_producto}' esta inactivo")

        total_compra = sum(
            (Decimal(str(item["cantidad"])) * Decimal(str(item["costo_unitario"])) for item in items),
            Decimal("0.00"),
        )

        if condicion_pago == "credito":
            deuda_actual = (
                session.query(func.coalesce(func.sum(CuentaPorPagar.saldo_pendiente), 0))
                .join(Compra, Compra.id_compra == CuentaPorPagar.id_compra)
                .filter(
                    Compra.id_proveedor == id_proveedor,
                    CuentaPorPagar.estado.in_(("pendiente", "parcial", "vencida")),
                )
                .scalar()
            )
            if deuda_actual + total_compra > proveedor.limite_credito:
                raise ValueError(
                    f"Se excede el limite de credito otorgado por el proveedor: deuda actual {deuda_actual} + "
                    f"nueva compra {total_compra} > limite {proveedor.limite_credito}"
                )

        # total_compra se inserta en 0.00 (la columna es NOT NULL sin DEFAULT) y se deja
        # que trg_compra_total_ins lo recalcule tras insertar las lineas. Si se insertara
        # ya con el total correcto, esa actualizacion del trigger no cambiaria el valor y
        # trg_compras_cxp (que solo abre la cuenta por pagar cuando total_compra SI cambia)
        # nunca se dispararia para compras a credito.
        compra = Compra(
            numero_compra=_generar_numero_compra(session),
            id_proveedor=id_proveedor,
            id_usuario_compra=id_usuario,
            fecha_emision=datetime.now(),
            total_compra=Decimal("0.00"),
            estado_compra="EMITIDA",
            condicion_pago=condicion_pago,
            fecha_vencimiento=fecha_vencimiento,
            id_tasa_compra=id_tasa,
            observaciones_compra=observaciones,
        )
        session.add(compra)
        session.flush()

        for item in items:
            session.add(
                CompraDetalle(
                    id_compra=compra.id_compra,
                    id_producto_compra=item["id_producto"],
                    descripcion=item.get("descripcion"),
                    cantidad_producto=item["cantidad"],
                    costo_unitario=item["costo_unitario"],
                    observaciones_item=item.get("observaciones"),
                )
            )

        session.commit()
        session.refresh(compra)

        logger.info(
            "Compra %s registrada: proveedor=%s condicion_pago=%s total=%s usuario=%s",
            compra.numero_compra,
            id_proveedor,
            condicion_pago,
            compra.total_compra,
            id_usuario,
        )

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="REGISTRO_COMPRA",
            modulo="COMPRAS",
            detalle={
                "numero_compra": compra.numero_compra,
                "id_proveedor": id_proveedor,
                "condicion_pago": condicion_pago,
                "total_compra": str(compra.total_compra),
            },
        )
        return compra

    @staticmethod
    def anular_compra(session: Session, id_compra: int, id_usuario: int | None, motivo: str) -> Compra:
        """Anula la compra: repone el stock recibido y cierra la cuenta por pagar (si la
        hubiera). Si ya se le aplicaron pagos, no se revierten -- quedan como
        NotaCreditoProveedor a favor de la empresa, sin tocar pagos_proveedores ni sus
        banco_movimientos/caja_movimientos (ver la misma nota en VentaService.anular_factura
        y migrations/0002_notas_credito_anulacion.sql).

        El stock se repone eliminando las lineas de compra_detalle: dispara
        trg_compra_detalle_stock_del y trg_compra_total_del, que a su vez dispara
        trg_compras_cxp -- por eso las lineas se borran ANTES de tocar la cuenta por
        pagar, para no reabrirla.
        """
        require_permiso(session, id_usuario, "compras", "eliminar")
        if not motivo:
            raise ValueError("motivo es requerido para anular una compra")

        # Ver el comentario equivalente en VentaService.anular_factura() -- mismo patron
        # de C1/C18/C22, aca resolviendo C24.
        compra = session.execute(
            select(Compra)
            .where(Compra.id_compra == id_compra)
            .with_hint(Compra, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        ).scalar_one_or_none()
        if compra is None:
            raise ValueError("Compra no encontrada")
        if compra.estado_compra == "ANULADA":
            raise ValueError("La compra ya esta anulada")

        cxp = session.query(CuentaPorPagar).filter(CuentaPorPagar.id_compra == id_compra).first()
        monto_pagado = Decimal("0.00")
        if cxp is not None:
            monto_pagado = (
                session.query(func.coalesce(func.sum(PagoProveedor.monto), 0))
                .filter(PagoProveedor.id_cuenta_por_pagar == cxp.id_cuenta)
                .scalar()
            )
            monto_pagado = Decimal(str(monto_pagado))

        session.query(CompraDetalle).filter(CompraDetalle.id_compra == id_compra).delete(synchronize_session=False)
        if cxp is not None:
            if monto_pagado > 0:
                cxp.estado = "anulada"
                cxp.saldo_pendiente = Decimal("0.00")
            else:
                session.delete(cxp)

        compra.estado_compra = "ANULADA"
        compra.modificado_por = id_usuario

        # Mismo fix que VentaService.anular_factura(): la nota de credito se crea AHORA,
        # con el nucleo interno sin commit propio, en la MISMA transaccion que la
        # anulacion -- antes comiteaban por separado y una falla en la segunda insercion
        # dejaba la anulacion comprometida sin su compensacion.
        if monto_pagado > 0:
            NotaCreditoService._crear_nota_credito_proveedor(
                session,
                id_proveedor=compra.id_proveedor,
                id_compra_origen=id_compra,
                monto=monto_pagado,
                motivo=motivo,
                id_usuario=id_usuario,
            )

        session.commit()
        session.refresh(compra)

        logger.info(
            "Compra %s anulada: motivo=%s monto_revertido_a_nota_credito=%s usuario=%s",
            compra.numero_compra,
            motivo,
            monto_pagado,
            id_usuario,
        )

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="ANULACION_COMPRA",
            modulo="COMPRAS",
            detalle={
                "numero_compra": compra.numero_compra,
                "motivo": motivo,
                "nota_credito_generada": str(monto_pagado) if monto_pagado > 0 else None,
            },
        )
        return compra

    @staticmethod
    def listar_compras(
        session: Session,
        id_proveedor: int | None = None,
        estado: str | None = None,
        fecha_desde: date | datetime | None = None,
        fecha_hasta: date | datetime | None = None,
        pagina: int = 1,
        por_pagina: int = 20,
        id_usuario: int | None = None,
    ) -> dict:
        require_permiso(session, id_usuario, "compras", "ver")
        query = session.query(Compra)
        if id_proveedor:
            query = query.filter(Compra.id_proveedor == id_proveedor)
        if estado:
            query = query.filter(Compra.estado_compra == estado)
        if fecha_desde:
            query = query.filter(Compra.fecha_emision >= fecha_desde)
        if fecha_hasta:
            query = query.filter(Compra.fecha_emision <= fecha_hasta)

        total = query.count()
        compras = query.order_by(Compra.fecha_emision.desc()).offset((pagina - 1) * por_pagina).limit(por_pagina).all()
        return {"items": compras, "total": total, "pagina": pagina, "por_pagina": por_pagina}
