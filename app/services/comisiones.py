import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    BancoMovimiento,
    Caja,
    CajaMovimiento,
    ComisionFactura,
    CuentaBancaria,
    FacturaDetalle,
    FacturaVenta,
    PagoComision,
    ProductoPrecio,
    Usuario,
    Vendedor,
)
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso

logger = logging.getLogger(__name__)

# El principio contable de este modulo (C14): el monto de la venta (factura_detalle.
# precio_unitario, total_venta, cuentas_por_cobrar) nunca se toca -- es el ingreso real.
# La comision es un pasivo/gasto derivado, calculado aparte, nunca neteado contra la
# venta.


class ComisionService:
    @staticmethod
    def calcular_comisiones_factura(
        session: Session,
        factura: FacturaVenta,
        detalles: list[FacturaDetalle],
        id_usuario: int | None,
    ) -> list[ComisionFactura]:
        """Llamada INTERNA desde VentaService.emitir_factura(), sin require_permiso propio
        -- mismo criterio que NotaCreditoService llamado desde anular_factura(): efecto
        secundario interno de una accion ya autorizada, no una accion directa de usuario.

        NO hace session.commit() -- solo session.add(), para quedar en la MISMA
        transaccion atomica que la venta (el caller ya hizo flush() antes de llamar aca,
        asi que `detalles` trae id_factura_detalle poblado).

        El vendedor es obligatorio en toda factura (factura_venta.id_vendedor NOT NULL,
        migrations/0017_vendedor_obligatorio_factura.sql), asi que siempre hay a quien
        acreditarle la comision. Si un producto no tiene precio de lista configurado
        (ProductoPrecio), esa linea se saltea -- no bloquea la venta, simplemente no genera
        comision para ese item.
        """
        if not detalles:
            return []

        ids_producto = {detalle.id_producto_factura for detalle in detalles}
        precios_lista = {
            precio.id_producto: precio.precio_venta
            for precio in session.query(ProductoPrecio).filter(ProductoPrecio.id_producto.in_(ids_producto)).all()
        }

        comisiones = []
        for detalle in detalles:
            precio_lista = precios_lista.get(detalle.id_producto_factura)
            if precio_lista is None:
                continue

            # detalle recien se flusheo (no se refresco): precio_unitario/cantidad_producto
            # pueden seguir siendo el tipo crudo que llego del caller (ej. str), no Decimal
            # todavia -- misma coercion defensiva que usa el resto del codebase.
            cantidad = Decimal(str(detalle.cantidad_producto))
            monto_base = precio_lista * cantidad
            monto_venta = Decimal(str(detalle.precio_unitario)) * cantidad
            monto_comision = max(Decimal("0.00"), monto_venta - monto_base)

            if monto_comision <= 0:
                continue

            # Contado: la factura se cobra completa al emitir (nunca hay cuentas_por_cobrar
            # de por medio) -- la comision nace 'liberada' directo. Credito: nace 'pendiente'
            # y trg_cxc_libera_comisiones (migrations/0045) la libera cuando la cuenta por
            # cobrar de esta factura llega a 'pagada'.
            estado_inicial = "liberada" if factura.condicion_pago == "contado" else "pendiente"
            comision = ComisionFactura(
                id_factura_detalle=detalle.id_factura_detalle,
                id_vendedor=factura.id_vendedor,
                monto_base_comision=monto_base,
                monto_venta_comision=monto_venta,
                monto_comision=monto_comision,
                estado_pago=estado_inicial,
                fecha_calculo=datetime.now(),
                creado_por=id_usuario,
            )
            session.add(comision)
            comisiones.append(comision)

        return comisiones

    @staticmethod
    def listar_comisiones_vendedor(
        session: Session, id_vendedor: int, estado_pago: str | None = None, id_usuario: int | None = None
    ) -> list[ComisionFactura]:
        require_permiso(session, id_usuario, "comisiones", "ver")
        query = session.query(ComisionFactura).filter(
            ComisionFactura.id_vendedor == id_vendedor, ComisionFactura.monto_comision > 0
        )
        if estado_pago:
            query = query.filter(ComisionFactura.estado_pago == estado_pago)
        return query.order_by(ComisionFactura.fecha_calculo.desc()).all()

    @staticmethod
    def listar_mis_comisiones(session: Session, id_usuario: int | None) -> list[ComisionFactura]:
        """Retorna las comisiones del vendedor logueado. Requiere permiso reportes_comisiones:ver
        (distinto de comisiones:ver, que es para gestion/pago). El usuario debe tener un vendedor
        vinculado (Usuario.id_vendedor_usuario) -- esto es verdad para usuarios con rol VENDEDOR."""
        require_permiso(session, id_usuario, "reportes_comisiones", "ver")
        usuario = session.get(Usuario, id_usuario) if id_usuario is not None else None
        if usuario is None or usuario.id_vendedor_usuario is None:
            raise ValueError("Este usuario no tiene un vendedor vinculado")
        return (
            session.query(ComisionFactura)
            .filter(ComisionFactura.id_vendedor == usuario.id_vendedor_usuario, ComisionFactura.monto_comision > 0)
            .order_by(ComisionFactura.fecha_calculo.desc())
            .all()
        )


class PagoComisionService:
    @staticmethod
    def pagar_comisiones_vendedor(
        session: Session,
        id_vendedor: int,
        metodo_pago: str,
        id_cuenta_bancaria: int | None = None,
        id_caja: int | None = None,
        referencia: str | None = None,
        id_usuario: int | None = None,
    ) -> PagoComision:
        """Paga en un solo batch TODAS las comisiones 'liberada' con monto_comision > 0
        de ese vendedor -- 'liberada' es el cliente ya pago la factura, el vendedor
        todavia no cobro esa comision (ver migrations/0045_comisiones_estado_liberada.sql).
        Las 'pendiente' (cliente no ha pagado) nunca son pagables aca. Un pago de comision
        liquida lo acumulado de una vez, no hay pago parcial de una linea individual. Sin
        trigger INSTEAD OF INSERT (a diferencia de PagoCobro/PagoProveedor): no hay
        saldo_pendiente parcial que proteger, asi que el BancoMovimiento/CajaMovimiento se
        crea directo aca, en la misma transaccion."""
        require_permiso(session, id_usuario, "comisiones", "crear")
        if (id_cuenta_bancaria is None) == (id_caja is None):
            raise ValueError("Indique exactamente un origen del pago: cuenta bancaria o caja")

        vendedor = session.get(Vendedor, id_vendedor)
        if vendedor is None:
            raise ValueError("Vendedor no encontrado")

        if id_cuenta_bancaria is not None:
            cuenta_bancaria = session.get(CuentaBancaria, id_cuenta_bancaria)
            if cuenta_bancaria is None:
                raise ValueError("Cuenta bancaria no encontrada")
            if cuenta_bancaria.estado_cuenta != "ACTIVO":
                raise ValueError(f"La cuenta bancaria '{cuenta_bancaria.numero_cuenta}' esta inactiva")
        else:
            caja = session.get(Caja, id_caja)
            if caja is None:
                raise ValueError("Caja no encontrada")

        # WITH (UPDLOCK, ROWLOCK): mismo patron que C1/C18/C22/C24 -- bloquea las filas
        # hasta el commit para que un segundo pago concurrente sobre el mismo vendedor no
        # alcance a pagar dos veces las mismas comisiones.
        comisiones_liberadas = (
            session.execute(
                select(ComisionFactura)
                .where(
                    ComisionFactura.id_vendedor == id_vendedor,
                    ComisionFactura.estado_pago == "liberada",
                    ComisionFactura.monto_comision > 0,
                )
                .with_hint(ComisionFactura, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
            )
            .scalars()
            .all()
        )
        if not comisiones_liberadas:
            raise ValueError("No hay comisiones liberadas para pagar a este vendedor")

        monto_total = sum((c.monto_comision for c in comisiones_liberadas), Decimal("0.00"))

        pago = PagoComision(
            id_vendedor=id_vendedor,
            id_cuenta_bancaria=id_cuenta_bancaria,
            id_caja=id_caja,
            metodo_pago=metodo_pago,
            monto=monto_total,
            referencia=referencia,
            fecha_pago=datetime.now(),
            creado_por=id_usuario,
        )
        session.add(pago)
        session.flush()

        for comision in comisiones_liberadas:
            comision.estado_pago = "pagada"
            comision.id_pago_comision = pago.id_pago_comision

        ahora = datetime.now()
        if id_cuenta_bancaria is not None:
            session.add(
                BancoMovimiento(
                    id_cuenta=id_cuenta_bancaria,
                    tipo_movimiento="cargo",
                    monto_movimiento=monto_total,
                    fecha_movimiento=ahora,
                    referencia_movimiento=referencia,
                    descripcion_movimiento=f"Pago de comisiones a vendedor #{id_vendedor}",
                    creado_por=id_usuario,
                    fecha_creacion=ahora,
                    id_pago_comision=pago.id_pago_comision,
                )
            )
        else:
            session.add(
                CajaMovimiento(
                    id_caja=id_caja,
                    tipo_movimiento="salida",
                    descripcion_movimiento=(
                        f"Pago de comisiones a vendedor #{id_vendedor}" + (f" - {referencia}" if referencia else "")
                    ),
                    monto_movimiento=monto_total,
                    fecha_registro=ahora,
                    creado_por=id_usuario,
                    id_pago_comision=pago.id_pago_comision,
                )
            )

        session.commit()
        session.refresh(pago)

        logger.info(
            "Comisiones pagadas: vendedor=%s monto=%s cantidad_comisiones=%s usuario=%s",
            id_vendedor,
            monto_total,
            len(comisiones_liberadas),
            id_usuario,
        )

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="PAGO_COMISION",
            modulo="COMISIONES",
            detalle={
                "id_vendedor": id_vendedor,
                "monto": str(monto_total),
                "cantidad_comisiones": len(comisiones_liberadas),
            },
        )
        return pago

    @staticmethod
    def listar_pagos_comision_vendedor(
        session: Session, id_vendedor: int, id_usuario: int | None = None
    ) -> list[PagoComision]:
        require_permiso(session, id_usuario, "comisiones", "ver")
        return (
            session.query(PagoComision)
            .filter(PagoComision.id_vendedor == id_vendedor)
            .order_by(PagoComision.fecha_pago.desc())
            .all()
        )
