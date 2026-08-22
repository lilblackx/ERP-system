from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import NotaCreditoCliente, NotaCreditoProveedor
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso


def _generar_numero_nota_credito_cliente(session: Session) -> str:
    ultimo_id = session.query(func.max(NotaCreditoCliente.id_nota_credito)).scalar() or 0
    return f"NC-{ultimo_id + 1:06d}"


class NotaCreditoService:
    """Saldo a favor de un cliente/proveedor generado cuando se anula una factura/compra
    que ya tenia pagos aplicados. Ver la nota en VentaService.anular_factura() y
    CompraService.anular_compra() para por que existe: no revierte el pago original (ese
    dinero, y el movimiento de caja/banco que lo trajo, quedan intactos), solo deja
    constancia de que se le debe. Aplicarlo a una compra futura, o devolverlo, es un
    desarrollo aparte -- todavia no hay un flujo que consuma estas notas.

    NotaCreditoCliente es un documento fiscal que la empresa emite (reduce lo que el
    cliente le debe): tiene numero_nota_credito correlativo, igual que numero_factura,
    para poder reportarlo al SENIAT cuando se solicite -- ver listar_notas_credito_clientes().

    NotaCreditoProveedor NO es un documento fiscal nuestro: si anulamos una compra ya
    pagada, quien debe emitir la nota de credito es el proveedor hacia nosotros, no al
    reves. Por eso no tiene correlativo -- es solo un registro interno de que se nos debe.
    """

    @staticmethod
    def crear_nota_credito_cliente(
        session: Session,
        id_cliente: int,
        id_factura_origen: int,
        monto,
        motivo: str,
        id_usuario: int | None,
    ) -> NotaCreditoCliente:
        monto = Decimal(str(monto))
        if monto <= 0:
            raise ValueError("monto debe ser mayor a cero")

        nota = NotaCreditoCliente(
            numero_nota_credito=_generar_numero_nota_credito_cliente(session),
            id_cliente=id_cliente,
            id_factura_origen=id_factura_origen,
            monto=monto,
            saldo_disponible=monto,
            motivo=motivo,
            estado="disponible",
            creado_por=id_usuario,
        )
        session.add(nota)
        session.commit()
        session.refresh(nota)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="NOTA_CREDITO_CLIENTE",
            modulo="NOTAS_CREDITO",
            detalle={
                "numero_nota_credito": nota.numero_nota_credito,
                "id_cliente": id_cliente,
                "id_factura_origen": id_factura_origen,
                "monto": str(monto),
            },
        )
        return nota

    @staticmethod
    def crear_nota_credito_proveedor(
        session: Session,
        id_proveedor: int,
        id_compra_origen: int,
        monto,
        motivo: str,
        id_usuario: int | None,
    ) -> NotaCreditoProveedor:
        monto = Decimal(str(monto))
        if monto <= 0:
            raise ValueError("monto debe ser mayor a cero")

        nota = NotaCreditoProveedor(
            id_proveedor=id_proveedor,
            id_compra_origen=id_compra_origen,
            monto=monto,
            saldo_disponible=monto,
            motivo=motivo,
            estado="disponible",
            creado_por=id_usuario,
        )
        session.add(nota)
        session.commit()
        session.refresh(nota)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="NOTA_CREDITO_PROVEEDOR",
            modulo="NOTAS_CREDITO",
            detalle={"id_proveedor": id_proveedor, "id_compra_origen": id_compra_origen, "monto": str(monto)},
        )
        return nota

    @staticmethod
    def listar_notas_credito_cliente(
        session: Session, id_cliente: int, id_usuario: int | None = None
    ) -> list[NotaCreditoCliente]:
        require_permiso(session, id_usuario, "notas_credito", "ver")
        return (
            session.query(NotaCreditoCliente)
            .filter(NotaCreditoCliente.id_cliente == id_cliente)
            .order_by(NotaCreditoCliente.fecha_creacion.desc())
            .all()
        )

    @staticmethod
    def listar_notas_credito_clientes(
        session: Session,
        fecha_desde: date | datetime | None = None,
        fecha_hasta: date | datetime | None = None,
        id_cliente: int | None = None,
        estado: str | None = None,
        pagina: int = 1,
        por_pagina: int = 20,
        id_usuario: int | None = None,
    ) -> dict:
        """Reporte paginado con filtros -- pensado para armar lo que pida el SENIAT
        (rango de fechas, o todas las de un cliente) sin tener que consultar la tabla
        directamente. Ver listar_notas_credito_cliente() para el caso simple de listar
        las notas disponibles de un cliente puntual."""
        require_permiso(session, id_usuario, "notas_credito", "ver")
        query = session.query(NotaCreditoCliente)
        if fecha_desde:
            query = query.filter(NotaCreditoCliente.fecha_creacion >= fecha_desde)
        if fecha_hasta:
            query = query.filter(NotaCreditoCliente.fecha_creacion <= fecha_hasta)
        if id_cliente:
            query = query.filter(NotaCreditoCliente.id_cliente == id_cliente)
        if estado:
            query = query.filter(NotaCreditoCliente.estado == estado)

        total = query.count()
        notas = (
            query.order_by(NotaCreditoCliente.numero_nota_credito.desc())
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
            .all()
        )
        return {"items": notas, "total": total, "pagina": pagina, "por_pagina": por_pagina}

    @staticmethod
    def listar_notas_credito_proveedor(
        session: Session, id_proveedor: int, id_usuario: int | None = None
    ) -> list[NotaCreditoProveedor]:
        require_permiso(session, id_usuario, "notas_credito", "ver")
        return (
            session.query(NotaCreditoProveedor)
            .filter(NotaCreditoProveedor.id_proveedor == id_proveedor)
            .order_by(NotaCreditoProveedor.fecha_creacion.desc())
            .all()
        )
