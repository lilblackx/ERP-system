"""Paso 2 del flujo OC -> NR -> Compra -> Pago: recibir mercancia contra una OC (con
soporte de recepciones parciales -- multiples NR por OC) y devolver al proveedor lo que se
rechazo en la recepcion. El stock sube en trg_nota_recepcion_detalle_ins y baja en
trg_nota_devolucion_detalle_ins (ver migrations/0032) -- estos servicios solo validan e
insertan, no tocan inventario.cantidad_unidad directamente."""

import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    CompraOC,
    CompraOCDetalle,
    NotaDevolucion,
    NotaDevolucionDetalle,
    NotaRecepcion,
    NotaRecepcionDetalle,
)
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso

logger = logging.getLogger(__name__)


def _generar_numero_nr(session: Session) -> str:
    ultimo_id = session.query(func.max(NotaRecepcion.id_nr)).scalar() or 0
    return f"NR-{ultimo_id + 1:06d}"


def _generar_numero_devolucion(session: Session) -> str:
    ultimo_id = session.query(func.max(NotaDevolucion.id_devolucion)).scalar() or 0
    return f"ND-{ultimo_id + 1:06d}"


class NotaRecepcionService:
    @staticmethod
    def crear_nota_recepcion(
        session: Session,
        id_oc: int,
        items: list[dict],
        observaciones: str | None = None,
        id_usuario: int | None = None,
    ) -> NotaRecepcion:
        """items: [{"id_oc_detalle": int, "cantidad_recibida": Decimal, "cantidad_rechazada":
        Decimal opcional}]. id_producto/precio_unitario se toman de CompraOCDetalle, no del
        caller, para que no puedan divergir de lo que la OC realmente pidio. Soporta
        recepciones parciales: puede llamarse varias veces para la misma OC mientras quede
        cantidad_pendiente > 0 en la linea correspondiente."""
        require_permiso(session, id_usuario, "compras", "recibir_mercancia")
        if not items:
            raise ValueError("La nota de recepcion debe tener al menos un item")

        oc = session.get(CompraOC, id_oc)
        if oc is None:
            raise ValueError("Orden de compra no encontrada")
        if oc.estado == "ANULADA":
            raise ValueError("No se puede recibir mercancia de una orden de compra anulada")

        detalles_oc = {d.id_detalle: d for d in session.query(CompraOCDetalle).filter(CompraOCDetalle.id_oc == id_oc)}

        lineas_validadas = []
        for item in items:
            id_oc_detalle = item["id_oc_detalle"]
            detalle_oc = detalles_oc.get(id_oc_detalle)
            if detalle_oc is None:
                raise ValueError(f"La linea de OC {id_oc_detalle} no pertenece a la orden de compra {id_oc}")

            cantidad_recibida = Decimal(str(item["cantidad_recibida"]))
            cantidad_rechazada = Decimal(str(item.get("cantidad_rechazada") or 0))
            if cantidad_recibida <= 0:
                raise ValueError("cantidad_recibida debe ser mayor a cero")
            if cantidad_rechazada < 0 or cantidad_rechazada > cantidad_recibida:
                raise ValueError("cantidad_rechazada no puede ser negativa ni mayor a la cantidad recibida")
            if cantidad_recibida > detalle_oc.cantidad_pendiente:
                raise ValueError(
                    f"Se intenta recibir {cantidad_recibida} del producto {detalle_oc.id_producto}, pero solo "
                    f"quedan {detalle_oc.cantidad_pendiente} pendientes en la orden de compra {oc.numero_oc}"
                )
            lineas_validadas.append((detalle_oc, cantidad_recibida, cantidad_rechazada))

        nr = NotaRecepcion(
            id_oc=id_oc,
            numero_nr=_generar_numero_nr(session),
            fecha_recepcion=datetime.now(),
            observaciones=observaciones,
            id_usuario_recepcion=id_usuario,
        )
        session.add(nr)
        session.flush()

        for detalle_oc, cantidad_recibida, cantidad_rechazada in lineas_validadas:
            session.add(
                NotaRecepcionDetalle(
                    id_nr=nr.id_nr,
                    id_oc_detalle=detalle_oc.id_detalle,
                    id_producto=detalle_oc.id_producto,
                    cantidad_recibida=cantidad_recibida,
                    cantidad_rechazada=cantidad_rechazada,
                    precio_unitario=detalle_oc.precio_unitario,
                    total_linea=cantidad_recibida * detalle_oc.precio_unitario,
                )
            )

        session.commit()
        session.refresh(nr)

        logger.info("NR %s registrada: OC=%s usuario=%s", nr.numero_nr, oc.numero_oc, id_usuario)
        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="CREAR_NOTA_RECEPCION",
            modulo="COMPRAS",
            detalle={"numero_nr": nr.numero_nr, "id_oc": id_oc, "lineas": len(items)},
        )
        return nr

    @staticmethod
    def crear_nota_devolucion(
        session: Session,
        id_nr: int,
        items: list[dict],
        motivo: str,
        observaciones: str | None = None,
        id_usuario: int | None = None,
    ) -> NotaDevolucion:
        """items: [{"id_producto": int, "cantidad_devuelta": Decimal}]. precio_unitario se
        toma de la linea de NR correspondiente. Solo se puede devolver hasta lo que esa
        linea de NR marco como cantidad_rechazada, menos lo ya devuelto en notas previas de
        la misma NR (evita devolver mas de lo que en verdad se rechazo al recibir)."""
        require_permiso(session, id_usuario, "compras", "crear_nota_devolucion")
        if not items:
            raise ValueError("La nota de devolucion debe tener al menos un item")
        if not motivo:
            raise ValueError("motivo es requerido para una devolucion")

        nr = session.get(NotaRecepcion, id_nr)
        if nr is None:
            raise ValueError("Nota de recepcion no encontrada")

        lineas_validadas = []
        cantidad_total = Decimal("0")
        for item in items:
            id_producto = item["id_producto"]
            cantidad_devuelta = Decimal(str(item["cantidad_devuelta"]))
            if cantidad_devuelta <= 0:
                raise ValueError("cantidad_devuelta debe ser mayor a cero")

            detalle_nr = (
                session.query(NotaRecepcionDetalle)
                .filter(NotaRecepcionDetalle.id_nr == id_nr, NotaRecepcionDetalle.id_producto == id_producto)
                .first()
            )
            if detalle_nr is None:
                raise ValueError(f"El producto {id_producto} no fue recibido en la NR {nr.numero_nr}")

            ya_devuelto = (
                session.query(func.coalesce(func.sum(NotaDevolucionDetalle.cantidad_devuelta), 0))
                .join(NotaDevolucion, NotaDevolucion.id_devolucion == NotaDevolucionDetalle.id_devolucion)
                .filter(NotaDevolucion.id_nr == id_nr, NotaDevolucionDetalle.id_producto == id_producto)
                .scalar()
            )
            disponible_para_devolver = detalle_nr.cantidad_rechazada - Decimal(str(ya_devuelto))
            if cantidad_devuelta > disponible_para_devolver:
                raise ValueError(
                    f"Solo hay {disponible_para_devolver} unidades rechazadas del producto {id_producto} "
                    f"disponibles para devolver en la NR {nr.numero_nr}"
                )

            lineas_validadas.append((detalle_nr, cantidad_devuelta))
            cantidad_total += cantidad_devuelta

        devolucion = NotaDevolucion(
            id_nr=id_nr,
            numero_nota_devolucion=_generar_numero_devolucion(session),
            fecha_devolucion=datetime.now(),
            motivo=motivo,
            cantidad_total=cantidad_total,
            # Este servicio registra la devolucion ya efectuada (no un estado intermedio
            # "pendiente de despachar") -- coincide con que trg_nota_devolucion_detalle_ins
            # descuenta el stock en el mismo INSERT de sus lineas.
            estado="DEVUELTO",
            observaciones=observaciones,
            id_usuario_creador=id_usuario,
        )
        session.add(devolucion)
        session.flush()

        for detalle_nr, cantidad_devuelta in lineas_validadas:
            session.add(
                NotaDevolucionDetalle(
                    id_devolucion=devolucion.id_devolucion,
                    id_producto=detalle_nr.id_producto,
                    cantidad_devuelta=cantidad_devuelta,
                    precio_unitario=detalle_nr.precio_unitario,
                    total_linea=cantidad_devuelta * detalle_nr.precio_unitario,
                )
            )

        session.commit()
        session.refresh(devolucion)

        logger.info(
            "Devolucion %s registrada: NR=%s motivo=%s usuario=%s",
            devolucion.numero_nota_devolucion,
            nr.numero_nr,
            motivo,
            id_usuario,
        )
        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="CREAR_NOTA_DEVOLUCION",
            modulo="COMPRAS",
            detalle={"numero_nota_devolucion": devolucion.numero_nota_devolucion, "id_nr": id_nr, "motivo": motivo},
        )
        return devolucion

    @staticmethod
    def listar_notas_recepcion(
        session: Session,
        id_oc: int | None = None,
        pagina: int = 1,
        por_pagina: int = 20,
        id_usuario: int | None = None,
    ) -> dict:
        """Necesario para la pestana 'Recepciones' de app/ui/compras.py -- ningun paso
        anterior agrego un metodo de lectura (paso 3 solo tenia escritura)."""
        require_permiso(session, id_usuario, "compras", "ver")
        query = session.query(NotaRecepcion)
        if id_oc:
            query = query.filter(NotaRecepcion.id_oc == id_oc)

        total = query.count()
        nrs = (
            query.order_by(NotaRecepcion.fecha_recepcion.desc())
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
            .all()
        )
        return {"items": nrs, "total": total, "pagina": pagina, "por_pagina": por_pagina}

    @staticmethod
    def obtener_nota_recepcion(session: Session, id_nr: int, id_usuario: int | None = None) -> dict:
        require_permiso(session, id_usuario, "compras", "ver")
        nr = session.get(NotaRecepcion, id_nr)
        if nr is None:
            raise ValueError("Nota de recepcion no encontrada")
        detalles = session.query(NotaRecepcionDetalle).filter(NotaRecepcionDetalle.id_nr == id_nr).all()
        return {"nota": nr, "detalles": detalles}
