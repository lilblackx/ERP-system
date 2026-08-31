"""Paso 1 y parte del 3 del flujo OC -> NR -> Compra -> Pago: crear la orden de compra y
gestionar enmiendas (cambios autorizados a una OC ya emitida). Ver migrations/0032 para el
schema y los triggers (trg_compra_oc_enmienda_autorizar aplica el efecto de una enmienda de
tipo CANTIDAD recien cuando queda AUTORIZADA)."""

import logging
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import CompraOC, CompraOCDetalle, CompraOCEnmienda, Inventario, Proveedor
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso

logger = logging.getLogger(__name__)

TIPOS_CAMBIO_ENMIENDA = {"CANTIDAD", "PRECIO", "FECHA"}


def _generar_numero_oc(session: Session) -> str:
    # Prefijo "ODC-" (no "OC-") a pedido del usuario -- mas facil de identificar que el
    # numero_compra del flujo directo (compras.py), que ya usaba "OC-" desde antes.
    ultimo_id = session.query(func.max(CompraOC.id_oc)).scalar() or 0
    return f"ODC-{ultimo_id + 1:06d}"


def _generar_numero_enmienda(session: Session) -> str:
    ultimo_id = session.query(func.max(CompraOCEnmienda.id_enmienda)).scalar() or 0
    return f"ENM-{ultimo_id + 1:06d}"


def _validar_items_oc(items: list[dict]) -> None:
    if not items:
        raise ValueError("La orden de compra debe tener al menos un item")
    for item in items:
        if not item.get("id_producto"):
            raise ValueError("Cada item requiere id_producto")
        if not item.get("cantidad_solicitada") or Decimal(str(item["cantidad_solicitada"])) <= 0:
            raise ValueError("Cada item requiere una cantidad_solicitada mayor a cero")
        if not item.get("precio_unitario") or Decimal(str(item["precio_unitario"])) <= 0:
            raise ValueError("Cada item requiere un precio_unitario mayor a cero")


class CompraOCService:
    @staticmethod
    def crear_oc(
        session: Session,
        id_proveedor: int,
        items: list[dict],
        fecha_estimada_entrega: date | None = None,
        observaciones: str | None = None,
        id_usuario: int | None = None,
    ) -> CompraOC:
        require_permiso(session, id_usuario, "compras", "crear_oc")
        _validar_items_oc(items)

        proveedor = session.get(Proveedor, id_proveedor)
        if proveedor is None:
            raise ValueError("Proveedor no encontrado")
        if proveedor.estado_proveedor != "ACTIVO":
            raise ValueError(f"El proveedor '{proveedor.nombre_razon_social}' esta inactivo")

        for id_producto in {item["id_producto"] for item in items}:
            producto = session.get(Inventario, id_producto)
            if producto is None:
                raise ValueError(f"Producto {id_producto} no encontrado")
            if producto.estado_producto != "ACTIVO":
                raise ValueError(f"El producto '{producto.nombre_producto}' esta inactivo")

        cantidad_total = sum(Decimal(str(item["cantidad_solicitada"])) for item in items)
        total_oc = sum(
            (Decimal(str(item["cantidad_solicitada"])) * Decimal(str(item["precio_unitario"])) for item in items),
            Decimal("0.00"),
        )

        oc = CompraOC(
            numero_oc=_generar_numero_oc(session),
            id_proveedor=id_proveedor,
            fecha_oc=datetime.now(),
            fecha_estimada_entrega=fecha_estimada_entrega,
            cantidad_solicitada=cantidad_total,
            total_oc=total_oc,
            observaciones=observaciones,
            id_usuario_creador=id_usuario,
        )
        session.add(oc)
        session.flush()

        for item in items:
            cantidad = Decimal(str(item["cantidad_solicitada"]))
            precio = Decimal(str(item["precio_unitario"]))
            session.add(
                CompraOCDetalle(
                    id_oc=oc.id_oc,
                    id_producto=item["id_producto"],
                    cantidad_solicitada=cantidad,
                    # cantidad_pendiente arranca igual a lo solicitado -- nada recibido
                    # todavia. trg_nota_recepcion_detalle_ins la recalcula desde la primera
                    # NR en adelante (ver migrations/0032); esta fila nunca la toca de nuevo.
                    cantidad_pendiente=cantidad,
                    precio_unitario=precio,
                    total_linea=cantidad * precio,
                )
            )

        session.commit()
        session.refresh(oc)

        logger.info(
            "OC %s creada: proveedor=%s total=%s usuario=%s", oc.numero_oc, id_proveedor, oc.total_oc, id_usuario
        )
        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="CREAR_OC",
            modulo="COMPRAS",
            detalle={"numero_oc": oc.numero_oc, "id_proveedor": id_proveedor, "total_oc": str(oc.total_oc)},
        )
        return oc

    @staticmethod
    def crear_enmienda(
        session: Session,
        id_oc: int,
        tipo_cambio: str,
        motivo: str,
        cantidad_nueva=None,
        precio_nuevo=None,
        fecha_entrega_nueva: date | None = None,
        observaciones: str | None = None,
        id_usuario: int | None = None,
    ) -> CompraOCEnmienda:
        """Registra el CAMBIO PROPUESTO -- no tiene efecto hasta que autorizar_enmienda()
        la apruebe. CANTIDAD y FECHA tienen efecto automatico al autorizar (ver
        trg_compra_oc_enmienda_autorizar, migrations/0032 y 0034): CANTIDAD ajusta
        compra_oc.cantidad_solicitada, FECHA ajusta compra_oc.fecha_estimada_entrega --
        ambos son campos unicos de cabecera. PRECIO queda solo para trazabilidad, sin
        recalculo automatico -- la tabla no tiene id_oc_detalle (una OC puede tener varias
        lineas con precios distintos, no hay "un" precio de cabecera a enmendar sin
        definir antes a cual linea aplica); requiere editar la linea a mano."""
        require_permiso(session, id_usuario, "compras", "crear_enmienda_oc")
        if tipo_cambio not in TIPOS_CAMBIO_ENMIENDA:
            raise ValueError(f"tipo_cambio debe ser uno de {TIPOS_CAMBIO_ENMIENDA}")
        if not motivo:
            raise ValueError("motivo es requerido para una enmienda")

        oc = session.get(CompraOC, id_oc)
        if oc is None:
            raise ValueError("Orden de compra no encontrada")
        if oc.estado == "ANULADA":
            raise ValueError("No se puede enmendar una orden de compra anulada")

        if tipo_cambio == "CANTIDAD" and cantidad_nueva is None:
            raise ValueError("cantidad_nueva es requerida para una enmienda de tipo CANTIDAD")
        if tipo_cambio == "PRECIO" and precio_nuevo is None:
            raise ValueError("precio_nuevo es requerido para una enmienda de tipo PRECIO")
        if tipo_cambio == "FECHA" and fecha_entrega_nueva is None:
            raise ValueError("fecha_entrega_nueva es requerida para una enmienda de tipo FECHA")

        enmienda = CompraOCEnmienda(
            id_oc=id_oc,
            numero_enmienda=_generar_numero_enmienda(session),
            tipo_cambio=tipo_cambio,
            cantidad_anterior=oc.cantidad_solicitada if tipo_cambio == "CANTIDAD" else None,
            cantidad_nueva=Decimal(str(cantidad_nueva)) if cantidad_nueva is not None else None,
            precio_nuevo=Decimal(str(precio_nuevo)) if precio_nuevo is not None else None,
            fecha_entrega_anterior=oc.fecha_estimada_entrega if tipo_cambio == "FECHA" else None,
            fecha_entrega_nueva=fecha_entrega_nueva,
            motivo=motivo,
            observaciones=observaciones,
            id_usuario_solicitante=id_usuario,
        )
        session.add(enmienda)
        session.commit()
        session.refresh(enmienda)

        logger.info(
            "Enmienda %s creada para OC %s: tipo=%s usuario=%s",
            enmienda.numero_enmienda,
            oc.numero_oc,
            tipo_cambio,
            id_usuario,
        )
        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="CREAR_ENMIENDA_OC",
            modulo="COMPRAS",
            detalle={"numero_enmienda": enmienda.numero_enmienda, "id_oc": id_oc, "tipo_cambio": tipo_cambio},
        )
        return enmienda

    @staticmethod
    def autorizar_enmienda(
        session: Session, id_enmienda: int, aprobar: bool, id_usuario: int | None = None
    ) -> CompraOCEnmienda:
        """'compras'/'autorizar_enmienda_oc' (migrations/0033) no se le otorga a ningun rol
        a proposito -- solo ADMIN (que bypassa la matriz, ver require_permiso()) puede
        autorizar enmiendas hoy. Sigue sin distinguir solicitante/autorizador a nivel de
        permisos (como si hacen descuentos/creditos/vueltos_bancarios via
        AutorizacionDialog) -- se deja para cuando este flujo tenga su propia pantalla."""
        require_permiso(session, id_usuario, "compras", "autorizar_enmienda_oc")
        # WITH (UPDLOCK, ROWLOCK): sin esto, dos autorizaciones concurrentes de la MISMA
        # enmienda pueden ambas leer estado_enmienda='PENDIENTE' antes de que la primera
        # comitee -- si tipo_cambio='CANTIDAD', trg_compra_oc_enmienda_autorizar
        # (migrations/0032) se dispara en ambos UPDATE y ajusta compra_oc.cantidad_solicitada
        # dos veces. Mismo patron que CajaService.abrir_caja/cerrar_caja.
        enmienda = session.execute(
            select(CompraOCEnmienda)
            .where(CompraOCEnmienda.id_enmienda == id_enmienda)
            .with_hint(CompraOCEnmienda, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        ).scalar_one_or_none()
        if enmienda is None:
            raise ValueError("Enmienda no encontrada")
        if enmienda.estado_enmienda != "PENDIENTE":
            raise ValueError(f"La enmienda ya fue {enmienda.estado_enmienda.lower()}")

        enmienda.estado_enmienda = "AUTORIZADA" if aprobar else "RECHAZADA"
        enmienda.id_usuario_autorizador = id_usuario
        enmienda.fecha_autorizacion = datetime.now()
        # Si tipo_cambio='CANTIDAD' y queda AUTORIZADA, trg_compra_oc_enmienda_autorizar
        # (migrations/0032) ajusta compra_oc.cantidad_solicitada/estado en este mismo
        # UPDATE -- no hace falta nada mas en Python.
        session.commit()
        session.refresh(enmienda)

        logger.info("Enmienda %s %s por usuario=%s", enmienda.numero_enmienda, enmienda.estado_enmienda, id_usuario)
        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="AUTORIZAR_ENMIENDA_OC",
            modulo="COMPRAS",
            detalle={"numero_enmienda": enmienda.numero_enmienda, "estado_enmienda": enmienda.estado_enmienda},
        )
        return enmienda

    @staticmethod
    def listar_ocs(
        session: Session,
        texto_busqueda: str | None = None,
        estado: str | None = None,
        pagina: int = 1,
        por_pagina: int = 20,
        id_usuario: int | None = None,
    ) -> dict:
        """Necesario para la pestana 'Ordenes de Compra' de app/ui/compras.py -- ningun
        paso anterior agrego un metodo de lectura (paso 3 solo tenia escritura)."""
        require_permiso(session, id_usuario, "compras", "ver")
        query = session.query(CompraOC).join(Proveedor, Proveedor.id_proveedor == CompraOC.id_proveedor)
        if texto_busqueda:
            like = f"%{texto_busqueda}%"
            query = query.filter(CompraOC.numero_oc.ilike(like) | Proveedor.nombre_razon_social.ilike(like))
        if estado:
            query = query.filter(CompraOC.estado == estado)

        total = query.count()
        ocs = query.order_by(CompraOC.fecha_oc.desc()).offset((pagina - 1) * por_pagina).limit(por_pagina).all()
        return {"items": ocs, "total": total, "pagina": pagina, "por_pagina": por_pagina}

    @staticmethod
    def obtener_oc(session: Session, id_oc: int, id_usuario: int | None = None) -> dict:
        require_permiso(session, id_usuario, "compras", "ver")
        oc = session.get(CompraOC, id_oc)
        if oc is None:
            raise ValueError("Orden de compra no encontrada")
        detalles = session.query(CompraOCDetalle).filter(CompraOCDetalle.id_oc == id_oc).all()
        return {"oc": oc, "detalles": detalles}
