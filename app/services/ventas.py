from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Cliente,
    ComisionFactura,
    CuentaPorCobrar,
    FacturaDetalle,
    FacturaVenta,
    Inventario,
    PagoCobro,
    Vendedor,
)
from app.services.auditoria import AuditoriaService
from app.services.comisiones import ComisionService
from app.services.notas_credito import NotaCreditoService
from app.services.permisos import require_permiso


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
        require_permiso(session, id_usuario, "ventas", "crear")
        _validar_items(items)

        cliente = session.get(Cliente, id_cliente)
        if cliente is None:
            raise ValueError("Cliente no encontrado")
        if cliente.estado_cliente != "ACTIVO":
            raise ValueError(f"El cliente '{cliente.nombre_razon_social}' esta inactivo")

        if id_vendedor is not None:
            vendedor = session.get(Vendedor, id_vendedor)
            if vendedor is None:
                raise ValueError("Vendedor no encontrado")
            if vendedor.estado_vendedor != "ACTIVO":
                raise ValueError(f"El vendedor '{vendedor.nombre_vendedor}' esta inactivo")

        if condicion_pago not in ("contado", "credito"):
            raise ValueError("condicion_pago debe ser 'contado' o 'credito'")

        # --- Validar stock disponible por producto (agrupando items repetidos) ---
        cantidades_por_producto: dict[int, Decimal] = {}
        for item in items:
            id_producto = item["id_producto"]
            cantidad = Decimal(str(item["cantidad"]))
            cantidades_por_producto[id_producto] = cantidades_por_producto.get(id_producto, Decimal("0")) + cantidad

        for id_producto, cantidad_requerida in cantidades_por_producto.items():
            # WITH (UPDLOCK, ROWLOCK): bloquea la fila hasta el commit de esta
            # transaccion para que una segunda factura concurrente sobre el mismo
            # producto espere en vez de leer el mismo stock stale (TOCTOU). session.get()
            # no sirve aca -- with_for_update() de SQLAlchemy es un no-op en el dialecto
            # mssql (no existe "FOR UPDATE" en T-SQL), hace falta el table hint explicito.
            producto = session.execute(
                select(Inventario)
                .where(Inventario.id_producto == id_producto)
                .with_hint(Inventario, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
            ).scalar_one_or_none()
            if producto is None:
                raise ValueError(f"Producto {id_producto} no encontrado")
            if producto.estado_producto != "ACTIVO":
                raise ValueError(f"El producto '{producto.nombre_producto}' esta inactivo")
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

        detalles_creados = []
        for item in items:
            detalle = FacturaDetalle(
                id_factura=factura.id_factura,
                id_producto_factura=item["id_producto"],
                descripcion=item.get("descripcion"),
                cantidad_producto=item["cantidad"],
                observaciones_item=item.get("observaciones"),
                precio_unitario=item["precio_unitario"],
            )
            session.add(detalle)
            detalles_creados.append(detalle)

        # flush (no commit) para tener id_factura_detalle poblado -- ComisionService lo
        # necesita para crear ComisionFactura en la MISMA transaccion atomica que la venta
        # (C14: el vendedor puede vender mas caro que el precio de lista, la diferencia es
        # su comision).
        session.flush()
        ComisionService.calcular_comisiones_factura(session, factura, detalles_creados, id_usuario)

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
        """Anula la factura: repone el stock vendido y cierra la cuenta por cobrar (si la
        hubiera).

        Si la cuenta por cobrar ya tenia pagos aplicados, esos pagos NO se revierten --
        pagos_cobros y sus banco_movimientos/caja_movimientos quedan intactos, con su
        fecha e historial reales (no se edita retroactivamente un turno de caja ya
        cerrado ni un movimiento bancario ya conciliado; ver migrations/
        0002_notas_credito_anulacion.sql). En su lugar, esa plata queda como
        NotaCreditoCliente a favor del cliente -- la cuenta por cobrar pasa a
        estado='anulada' (no se borra, para no perder el vinculo con los pagos ya
        aplicados) y su saldo_pendiente se pone en 0. Sin pagos aplicados, la cuenta por
        cobrar se sigue borrando igual que antes (no hay nada que preservar).

        Si se calcularon comisiones sobre alguna de sus lineas (ComisionService, C14): las
        que siguen 'pendiente' se borran (nada que preservar, el vendedor todavia no cobro
        nada) ANTES de borrar factura_detalle -- ComisionFactura.id_factura_detalle tiene
        FK ON DELETE NO ACTION, asi que borrar el detalle primero reventaria con un
        IntegrityError crudo. Si alguna ya esta 'pagada' (el vendedor ya cobro ese dinero
        real via PagoComisionService), la anulacion sigue bloqueada -- no hay forma de
        revertir un pago ya hecho, mismo criterio que los pagos de cliente ya aplicados
        (ver NotaCreditoCliente mas abajo).

        El stock se repone eliminando las lineas de factura_detalle: dispara
        trg_factura_detalle_stock_del (repone cantidad_unidad) y trg_factura_total_del
        (recalcula total_venta). Ese recalculo, a su vez, dispara trg_factura_venta_cxc,
        pero solo toca cuentas_por_cobrar en estado 'pendiente' -- si ya hay pagos
        aplicados (estado 'parcial'/'pagada'), el trigger no la reabre ni la altera, asi
        que fijar estado='anulada' despues es seguro sin importar el orden.
        """
        require_permiso(session, id_usuario, "ventas", "eliminar")
        if not motivo:
            raise ValueError("motivo es requerido para anular una factura")

        # WITH (UPDLOCK, ROWLOCK): mismo patron que C1/C18/C22 -- evita que dos clics de
        # "anular" casi simultaneos sobre la misma factura pasen ambos el guard de
        # estado_factura y generen una NotaCreditoCliente duplicada (C24).
        factura = session.execute(
            select(FacturaVenta)
            .where(FacturaVenta.id_factura == id_factura)
            .with_hint(FacturaVenta, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        ).scalar_one_or_none()
        if factura is None:
            raise ValueError("Factura no encontrada")
        if factura.estado_factura == "ANULADA":
            raise ValueError("La factura ya esta anulada")

        ids_detalle = [
            id_factura_detalle
            for (id_factura_detalle,) in session.query(FacturaDetalle.id_factura_detalle)
            .filter(FacturaDetalle.id_factura == id_factura)
            .all()
        ]
        if ids_detalle:
            comisiones = (
                session.query(ComisionFactura).filter(ComisionFactura.id_factura_detalle.in_(ids_detalle)).all()
            )
            if any(comision.estado_pago == "pagada" for comision in comisiones):
                raise ValueError("No se puede anular: hay comisiones ya pagadas sobre esta factura.")
            if comisiones:
                session.query(ComisionFactura).filter(ComisionFactura.id_factura_detalle.in_(ids_detalle)).delete(
                    synchronize_session=False
                )

        cxc = session.query(CuentaPorCobrar).filter(CuentaPorCobrar.id_factura == id_factura).first()
        monto_pagado = Decimal("0.00")
        if cxc is not None:
            monto_pagado = (
                session.query(func.coalesce(func.sum(PagoCobro.monto), 0))
                .filter(PagoCobro.id_cuenta_por_cobrar == cxc.id_cuenta_por_cobrar)
                .scalar()
            )
            monto_pagado = Decimal(str(monto_pagado))

        session.query(FacturaDetalle).filter(FacturaDetalle.id_factura == id_factura).delete(synchronize_session=False)
        if cxc is not None:
            if monto_pagado > 0:
                cxc.estado = "anulada"
                cxc.saldo_pendiente = Decimal("0.00")
            else:
                session.delete(cxc)

        factura.estado_factura = "ANULADA"
        factura.modificado_por = id_usuario
        session.commit()
        session.refresh(factura)

        if monto_pagado > 0:
            NotaCreditoService.crear_nota_credito_cliente(
                session,
                id_cliente=factura.id_cliente_factura,
                id_factura_origen=id_factura,
                monto=monto_pagado,
                motivo=motivo,
                id_usuario=id_usuario,
            )

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="ANULACION_FACTURA",
            modulo="VENTAS",
            detalle={
                "numero_factura": factura.numero_factura,
                "motivo": motivo,
                "nota_credito_generada": str(monto_pagado) if monto_pagado > 0 else None,
            },
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
        id_usuario: int | None = None,
    ) -> dict:
        require_permiso(session, id_usuario, "ventas", "ver")
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
            query.order_by(FacturaVenta.fecha_emision.desc()).offset((pagina - 1) * por_pagina).limit(por_pagina).all()
        )
        return {"items": facturas, "total": total, "pagina": pagina, "por_pagina": por_pagina}
