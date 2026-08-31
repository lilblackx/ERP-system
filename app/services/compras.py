import logging
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Caja,
    Compra,
    CompraDetalle,
    CompraOC,
    CompraOCDetalle,
    ControlDeTasa,
    CuentaPorPagar,
    Inventario,
    PagoProveedor,
    Proveedor,
)
from app.services.auditoria import AuditoriaService
from app.services.notas_credito import NotaCreditoService
from app.services.permisos import require_permiso
from app.services.tesoreria import BancoService, CajaService
from app.services.ventas import _convertir_a_usd

logger = logging.getLogger(__name__)

METODOS_QUE_REQUIEREN_CAJA = {"efectivo"}
TOLERANCIA_CENTAVO = Decimal("0.01")


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
        if item.get("costo_unitario") is None or Decimal(str(item["costo_unitario"])) <= 0:
            raise ValueError("Cada item requiere un costo_unitario mayor a cero")


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
        pago: dict | None = None,
    ) -> Compra:
        """`pago` (solo para condicion_pago='contado'): mismo shape que
        PagoLineaDialog.get_data() -- metodo_pago, moneda, monto_moneda_origen, id_caja,
        id_cuenta_bancaria, referencia. A diferencia de VentaService.emitir_factura, una
        compra de contado no admite vuelto ni pago parcial: el monto convertido a USD debe
        coincidir con el total de la compra (tolerancia de un centavo), porque quien paga
        aca es la propia empresa, no hay "excedente que devolver". El egreso de caja/banco
        se inserta DENTRO de esta misma transaccion atomica, reusando tal cual los helpers
        que ya existen para el vuelto bancario de facturacion (CajaService/BancoService.
        _registrar_egreso_vuelto) -- son genericos, no especificos de vuelto."""
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
            if pago is not None:
                raise ValueError("Una compra a credito no admite pago -- se paga despues contra la cuenta por pagar")
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

        # id_tasa: mismo criterio que VentaService.emitir_factura -- si no se paso
        # explicitamente, se toma un snapshot de la tasa vigente (necesaria para convertir
        # el pago si viene en VES/COP). Se resuelve ANTES de validar el pago de contado.
        tasa_vigente = None
        if id_tasa is None:
            tasa_vigente = (
                session.query(ControlDeTasa)
                .order_by(ControlDeTasa.fecha_tasa.desc(), ControlDeTasa.id_tasa.desc())
                .first()
            )
            if tasa_vigente is not None:
                id_tasa = tasa_vigente.id_tasa
        elif condicion_pago == "contado":
            tasa_vigente = session.get(ControlDeTasa, id_tasa)

        caja_para_egreso = None
        id_cuenta_bancaria = None
        monto_usd = Decimal("0.00")
        if condicion_pago == "contado":
            if pago is None:
                raise ValueError("pago es requerido para una compra de contado")

            monto_origen = Decimal(str(pago["monto_moneda_origen"]))
            if monto_origen <= 0:
                raise ValueError("El monto del pago debe ser mayor a cero")
            monto_usd = _convertir_a_usd(monto_origen, pago["moneda"], tasa_vigente)
            if abs(monto_usd - total_compra) > TOLERANCIA_CENTAVO:
                raise ValueError(
                    f"El pago (${monto_usd}) no coincide con el total de la compra (${total_compra}); "
                    "una compra de contado se paga por el total exacto, sin vuelto"
                )

            id_caja = pago.get("id_caja")
            id_cuenta_bancaria = pago.get("id_cuenta_bancaria")
            if (id_caja is None) == (id_cuenta_bancaria is None):
                raise ValueError("El pago debe indicar exactamente un origen: id_caja o id_cuenta_bancaria")

            if pago["metodo_pago"] in METODOS_QUE_REQUIEREN_CAJA:
                if id_caja is None:
                    raise ValueError("Este metodo de pago requiere una caja")
                # Mismo lock que CajaService.abrir_caja/el vuelto bancario -- serializa dos
                # compras de contado concurrentes contra la misma caja.
                caja_para_egreso = session.execute(
                    select(Caja)
                    .where(Caja.id_caja == id_caja)
                    .with_hint(Caja, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
                ).scalar_one_or_none()
                if caja_para_egreso is None:
                    raise ValueError("Caja no encontrada")
                saldo_actual = CajaService.calcular_saldo_actual(session, id_caja)
                if saldo_actual < monto_usd:
                    raise ValueError(
                        f"La caja '{caja_para_egreso.nombre_caja}' no tiene saldo suficiente: "
                        f"disponible ${saldo_actual}, requerido ${monto_usd}"
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

        # Egreso de contado: se inserta DESPUES de las lineas (ya paso por
        # trg_compra_total_ins) pero ANTES del commit, en la misma transaccion atomica --
        # si algo de esto falla, nada se persiste (mismo criterio que el vuelto bancario en
        # VentaService.emitir_factura). No se revierte en anular_compra: dinero ya movido no
        # se toca, mismo criterio que pagos ya aplicados a una compra a credito.
        if condicion_pago == "contado":
            descripcion = f"Pago de contado a proveedor por compra {compra.numero_compra}"
            if caja_para_egreso is not None:
                CajaService._registrar_egreso_vuelto(
                    session,
                    id_caja=caja_para_egreso.id_caja,
                    monto=monto_usd,
                    descripcion=descripcion,
                    id_usuario=id_usuario,
                    fecha=compra.fecha_emision,
                )
            else:
                BancoService._registrar_egreso_vuelto(
                    session,
                    id_cuenta=id_cuenta_bancaria,
                    monto=monto_usd,
                    descripcion=descripcion,
                    referencia=pago.get("referencia") or "",
                    id_usuario=id_usuario,
                    fecha=compra.fecha_emision,
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
                "pago": {"metodo_pago": pago["metodo_pago"], "moneda": pago["moneda"]} if pago else None,
            },
        )
        return compra

    @staticmethod
    def obtener_compra(session: Session, id_compra: int, id_usuario: int | None = None) -> dict:
        require_permiso(session, id_usuario, "compras", "ver")
        compra = session.get(Compra, id_compra)
        if compra is None:
            raise ValueError("Compra no encontrada")
        detalles = session.query(CompraDetalle).filter(CompraDetalle.id_compra == id_compra).all()
        return {"compra": compra, "detalles": detalles}

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
        solo_desde_oc: bool = False,
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
        # solo_desde_oc: la pestana "Facturas" del flujo OC (app/ui/compras.py) solo
        # muestra compras creadas via crear_compra_desde_oc -- registrar_compra() (compra
        # directa, sin OC) sigue existiendo aca mismo, aunque hoy ninguna UI la llame.
        if solo_desde_oc:
            query = query.filter(Compra.id_oc.isnot(None))

        total = query.count()
        compras = query.order_by(Compra.fecha_emision.desc()).offset((pagina - 1) * por_pagina).limit(por_pagina).all()
        return {"items": compras, "total": total, "pagina": pagina, "por_pagina": por_pagina}

    @staticmethod
    def crear_compra_desde_oc(
        session: Session,
        id_oc: int,
        id_usuario: int | None,
        items: list[dict],
        condicion_pago: str,
        fecha_vencimiento: date | None = None,
        id_tasa: int | None = None,
        observaciones: str | None = None,
        pago: dict | None = None,
    ) -> Compra:
        """Paso 3 del flujo OC -> NR -> Compra -> Pago: factura contra una OC ya
        (parcialmente) recibida. A diferencia de registrar_compra() (compra directa, sin
        OC), el stock de estas lineas YA se sumo al recibir la mercancia (ver
        trg_nota_recepcion_detalle_ins, migrations/0032) -- cada CompraDetalle se inserta
        con stock_ya_contabilizado=True para que trg_compra_detalle_stock_ins no lo vuelva
        a sumar.

        items: [{"id_oc_detalle": int, "cantidad": Decimal}]. id_producto/costo_unitario se
        toman de CompraOCDetalle, no del caller, para no divergir de lo realmente recibido.
        La regla cantidad_facturada acumulada <= cantidad_recibida se valida ACA en Python
        -- no hay trigger ni CHECK que la proteja, es una invariante entre dos tablas
        (compra_detalle y compra_oc_detalle) que ningun trigger de esta migracion cubre."""
        require_permiso(session, id_usuario, "compras", "crear")
        if not items:
            raise ValueError("La compra debe tener al menos un item")
        if condicion_pago not in ("contado", "credito"):
            raise ValueError("condicion_pago debe ser 'contado' o 'credito'")

        oc = session.get(CompraOC, id_oc)
        if oc is None:
            raise ValueError("Orden de compra no encontrada")
        if oc.estado == "ANULADA":
            raise ValueError("No se puede facturar una orden de compra anulada")

        proveedor = session.get(Proveedor, oc.id_proveedor)
        if proveedor is None:
            raise ValueError("Proveedor no encontrado")
        if proveedor.estado_proveedor != "ACTIVO":
            raise ValueError(f"El proveedor '{proveedor.nombre_razon_social}' esta inactivo")

        detalles_oc = {d.id_detalle: d for d in session.query(CompraOCDetalle).filter(CompraOCDetalle.id_oc == id_oc)}

        lineas_validadas = []
        total_compra = Decimal("0.00")
        for item in items:
            id_oc_detalle = item["id_oc_detalle"]
            detalle_oc = detalles_oc.get(id_oc_detalle)
            if detalle_oc is None:
                raise ValueError(f"La linea de OC {id_oc_detalle} no pertenece a la orden de compra {id_oc}")

            cantidad = Decimal(str(item["cantidad"]))
            if cantidad <= 0:
                raise ValueError("Cada item requiere una cantidad mayor a cero")

            disponible_para_facturar = detalle_oc.cantidad_recibida - detalle_oc.cantidad_facturada
            if cantidad > disponible_para_facturar:
                raise ValueError(
                    f"Se intenta facturar {cantidad} del producto {detalle_oc.id_producto}, pero solo hay "
                    f"{disponible_para_facturar} recibidas y sin facturar en la orden de compra {oc.numero_oc}"
                )

            lineas_validadas.append((detalle_oc, cantidad))
            total_compra += cantidad * detalle_oc.precio_unitario

        if condicion_pago == "credito":
            if pago is not None:
                raise ValueError("Una compra a credito no admite pago -- se paga despues contra la cuenta por pagar")
            deuda_actual = (
                session.query(func.coalesce(func.sum(CuentaPorPagar.saldo_pendiente), 0))
                .join(Compra, Compra.id_compra == CuentaPorPagar.id_compra)
                .filter(
                    Compra.id_proveedor == oc.id_proveedor,
                    CuentaPorPagar.estado.in_(("pendiente", "parcial", "vencida")),
                )
                .scalar()
            )
            if deuda_actual + total_compra > proveedor.limite_credito:
                raise ValueError(
                    f"Se excede el limite de credito otorgado por el proveedor: deuda actual {deuda_actual} + "
                    f"nueva compra {total_compra} > limite {proveedor.limite_credito}"
                )

        # id_tasa: mismo criterio que registrar_compra().
        tasa_vigente = None
        if id_tasa is None:
            tasa_vigente = (
                session.query(ControlDeTasa)
                .order_by(ControlDeTasa.fecha_tasa.desc(), ControlDeTasa.id_tasa.desc())
                .first()
            )
            if tasa_vigente is not None:
                id_tasa = tasa_vigente.id_tasa
        elif condicion_pago == "contado":
            tasa_vigente = session.get(ControlDeTasa, id_tasa)

        caja_para_egreso = None
        id_cuenta_bancaria = None
        monto_usd = Decimal("0.00")
        if condicion_pago == "contado":
            if pago is None:
                raise ValueError("pago es requerido para una compra de contado")

            monto_origen = Decimal(str(pago["monto_moneda_origen"]))
            if monto_origen <= 0:
                raise ValueError("El monto del pago debe ser mayor a cero")
            monto_usd = _convertir_a_usd(monto_origen, pago["moneda"], tasa_vigente)
            if abs(monto_usd - total_compra) > TOLERANCIA_CENTAVO:
                raise ValueError(
                    f"El pago (${monto_usd}) no coincide con el total de la compra (${total_compra}); "
                    "una compra de contado se paga por el total exacto, sin vuelto"
                )

            id_caja = pago.get("id_caja")
            id_cuenta_bancaria = pago.get("id_cuenta_bancaria")
            if (id_caja is None) == (id_cuenta_bancaria is None):
                raise ValueError("El pago debe indicar exactamente un origen: id_caja o id_cuenta_bancaria")

            if pago["metodo_pago"] in METODOS_QUE_REQUIEREN_CAJA:
                if id_caja is None:
                    raise ValueError("Este metodo de pago requiere una caja")
                caja_para_egreso = session.execute(
                    select(Caja)
                    .where(Caja.id_caja == id_caja)
                    .with_hint(Caja, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
                ).scalar_one_or_none()
                if caja_para_egreso is None:
                    raise ValueError("Caja no encontrada")
                saldo_actual = CajaService.calcular_saldo_actual(session, id_caja)
                if saldo_actual < monto_usd:
                    raise ValueError(
                        f"La caja '{caja_para_egreso.nombre_caja}' no tiene saldo suficiente: "
                        f"disponible ${saldo_actual}, requerido ${monto_usd}"
                    )

        compra = Compra(
            numero_compra=_generar_numero_compra(session),
            id_proveedor=oc.id_proveedor,
            id_usuario_compra=id_usuario,
            id_oc=id_oc,
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

        for detalle_oc, cantidad in lineas_validadas:
            session.add(
                CompraDetalle(
                    id_compra=compra.id_compra,
                    id_producto_compra=detalle_oc.id_producto,
                    cantidad_producto=cantidad,
                    costo_unitario=detalle_oc.precio_unitario,
                    stock_ya_contabilizado=True,
                )
            )
            detalle_oc.cantidad_facturada += cantidad

        # cantidad_facturada de cabecera, derivada de sus lineas -- a diferencia de
        # cantidad_recibida (que trg_nota_recepcion_detalle_ins mantiene sola), ningun
        # trigger de esta migracion actualiza cantidad_facturada.
        oc.cantidad_facturada = sum((d.cantidad_facturada for d in detalles_oc.values()), Decimal("0"))

        if condicion_pago == "contado":
            descripcion = f"Pago de contado a proveedor por compra {compra.numero_compra}"
            if caja_para_egreso is not None:
                CajaService._registrar_egreso_vuelto(
                    session,
                    id_caja=caja_para_egreso.id_caja,
                    monto=monto_usd,
                    descripcion=descripcion,
                    id_usuario=id_usuario,
                    fecha=compra.fecha_emision,
                )
            else:
                BancoService._registrar_egreso_vuelto(
                    session,
                    id_cuenta=id_cuenta_bancaria,
                    monto=monto_usd,
                    descripcion=descripcion,
                    referencia=pago.get("referencia") or "",
                    id_usuario=id_usuario,
                    fecha=compra.fecha_emision,
                )

        session.commit()
        session.refresh(compra)

        logger.info(
            "Compra %s creada desde OC %s: proveedor=%s condicion_pago=%s total=%s usuario=%s",
            compra.numero_compra,
            oc.numero_oc,
            oc.id_proveedor,
            condicion_pago,
            compra.total_compra,
            id_usuario,
        )
        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="REGISTRO_COMPRA_DESDE_OC",
            modulo="COMPRAS",
            detalle={
                "numero_compra": compra.numero_compra,
                "id_oc": id_oc,
                "condicion_pago": condicion_pago,
                "total_compra": str(compra.total_compra),
            },
        )
        return compra
