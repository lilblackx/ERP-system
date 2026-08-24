import logging
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    Cliente,
    ComisionFactura,
    ConfiguracionEmpresa,
    ControlDeTasa,
    CuentaPorCobrar,
    FacturaDetalle,
    FacturaVenta,
    Inventario,
    PagoCobro,
    ProductoPrecio,
    Vendedor,
)
from app.services.auditoria import AuditoriaService
from app.services.comisiones import ComisionService
from app.services.notas_credito import NotaCreditoService
from app.services.permisos import require_permiso

logger = logging.getLogger(__name__)


def _numero_factura_temporal() -> str:
    """Placeholder unico para el INSERT inicial: numero_factura es NOT NULL UNIQUE y el
    numero definitivo (FV-{id_factura:06d}) solo se conoce despues del flush que asigna
    el id_factura real. Generarlo antes con MAX(id_factura)+1 tiene una carrera entre dos
    emisiones concurrentes que leen el mismo MAX y violan el UNIQUE -- este placeholder
    aleatorio evita esa colision sin necesitar un lock de tabla completa."""
    return f"TMP-{uuid.uuid4().hex[:16]}"


def _numero_control_temporal() -> str:
    """Mismo patron y motivo que _numero_factura_temporal(), para la segunda columna
    unica de la cabecera (numero_control: correlativo fiscal simple '00-00000001', ver
    migrations/0019_factura_numero_control_iva.sql)."""
    return f"TMP-{uuid.uuid4().hex[:16]}"


def _deuda_pendiente_cliente(session: Session, id_cliente: int) -> Decimal:
    deuda = (
        session.query(func.coalesce(func.sum(CuentaPorCobrar.saldo_pendiente), 0))
        .join(FacturaVenta, FacturaVenta.id_factura == CuentaPorCobrar.id_factura)
        .filter(
            FacturaVenta.id_cliente_factura == id_cliente,
            CuentaPorCobrar.estado.in_(("pendiente", "parcial", "vencida")),
        )
        .scalar()
    )
    return Decimal(str(deuda))


def _validar_items(items: list[dict]) -> None:
    if not items:
        raise ValueError("La factura debe tener al menos un item")
    for item in items:
        if not item.get("id_producto"):
            raise ValueError("Cada item requiere id_producto")
        if not item.get("cantidad") or Decimal(str(item["cantidad"])) <= 0:
            raise ValueError("Cada item requiere una cantidad mayor a cero")
        if item.get("precio_unitario") is None or Decimal(str(item["precio_unitario"])) <= 0:
            raise ValueError("Cada item requiere un precio_unitario mayor a cero")


class VentaService:
    @staticmethod
    def emitir_factura(
        session: Session,
        id_cliente: int,
        id_usuario: int | None,
        id_vendedor: int,
        condicion_pago: str,
        items: list[dict],
        fecha_vencimiento: date | None = None,
        id_tasa: int | None = None,
        observaciones: str | None = None,
        monto_descuento: Decimal | int | str = Decimal("0.00"),
        motivo_descuento: str | None = None,
        id_autorizador_descuento: int | None = None,
    ) -> FacturaVenta:
        require_permiso(session, id_usuario, "ventas", "crear")
        _validar_items(items)

        monto_descuento = Decimal(str(monto_descuento))
        if monto_descuento < 0:
            raise ValueError("monto_descuento no puede ser negativo")

        cliente = session.get(Cliente, id_cliente)
        if cliente is None:
            raise ValueError("Cliente no encontrado")
        if cliente.estado_cliente != "ACTIVO":
            raise ValueError(f"El cliente '{cliente.nombre_razon_social}' esta inactivo")

        if id_vendedor is None:
            raise ValueError("El vendedor es obligatorio para emitir una factura")
        vendedor = session.get(Vendedor, id_vendedor)
        if vendedor is None:
            raise ValueError("Vendedor no encontrado")
        if vendedor.estado_vendedor != "ACTIVO":
            raise ValueError(f"El vendedor '{vendedor.nombre_vendedor}' esta inactivo")

        if condicion_pago not in ("contado", "credito"):
            raise ValueError("condicion_pago debe ser 'contado' o 'credito'")

        if observaciones is not None and len(observaciones) > 255:
            raise ValueError("observaciones no puede superar 255 caracteres")

        # fecha_vencimiento: si no se paso explicitamente en una venta a credito, se
        # calcula con los dias_credito del cliente (mismo default que ya aplicaba la UI
        # en factura_form_dialog.py) -- antes quedaba en NULL si el caller no la mandaba,
        # dejando la cuenta por cobrar sin fecha de vencimiento coherente. No se rechazan
        # fechas pasadas explicitas: una venta a credito puede cargarse ya vencida (dato
        # historico/backdateado), ver test_por_cobrar_suma_saldos_abiertos_y_cuenta_vencidas.
        if condicion_pago == "credito" and fecha_vencimiento is None:
            dias_credito = cliente.dias_credito if cliente.dias_credito is not None else 30
            fecha_vencimiento = date.today() + timedelta(days=dias_credito)

        if id_tasa is not None and session.get(ControlDeTasa, id_tasa) is None:
            raise ValueError("Tasa de cambio no encontrada")

        # --- Descuentos: vender un item por debajo de su precio de lista, o un
        # monto_descuento manual de factura, requieren autorizacion de un usuario con
        # permiso 'descuentos'/'crear' -- simetrico a como ComisionService ya trata
        # precio_unitario > precio de lista como comision del vendedor. id_autorizador_
        # descuento llega ya verificado por la UI (reautenticacion de un supervisor sin
        # cerrar la sesion del vendedor, ver app/ui/autorizacion_dialog.py) -- este
        # require_permiso es una segunda validacion server-side, no confia en que la UI
        # lo hizo bien.
        ids_producto_items = {item["id_producto"] for item in items}
        precios_lista = {
            precio.id_producto: precio.precio_venta
            for precio in session.query(ProductoPrecio).filter(ProductoPrecio.id_producto.in_(ids_producto_items)).all()
        }
        hay_precio_bajo_lista = any(
            item["id_producto"] in precios_lista
            and Decimal(str(item["precio_unitario"])) < precios_lista[item["id_producto"]]
            for item in items
        )
        requiere_autorizacion_descuento = hay_precio_bajo_lista or monto_descuento > 0
        if requiere_autorizacion_descuento:
            if not motivo_descuento:
                raise ValueError("El descuento requiere un motivo")
            if id_autorizador_descuento is None:
                raise ValueError("Esta factura tiene descuentos y requiere autorizacion de un supervisor")
            require_permiso(session, id_autorizador_descuento, "descuentos", "crear")

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

        # --- IVA: snapshot de la configuracion vigente, no recalculado retroactivamente
        # si config_empresa cambia despues (ver ConfiguracionEmpresa.iva_activo/
        # iva_porcentaje). total_factura es exactamente lo que trg_factura_total_ins va a
        # dejar en factura_venta.total_venta (misma formula), asi que el IVA se calcula
        # sobre este valor en Python sin necesitar releer la fila despues del insert. El
        # IVA se calcula sobre el subtotal YA descontado -- se cobra impuesto sobre lo que
        # realmente se cobra, no sobre el precio de lista.
        total_factura = sum(
            (Decimal(str(item["cantidad"])) * Decimal(str(item["precio_unitario"])) for item in items),
            Decimal("0.00"),
        )
        if monto_descuento > total_factura:
            raise ValueError("monto_descuento no puede ser mayor al subtotal de la factura")
        subtotal_con_descuento = total_factura - monto_descuento

        config_empresa = session.query(ConfiguracionEmpresa).order_by(ConfiguracionEmpresa.id_config).first()
        iva_activo = bool(config_empresa.iva_activo) if config_empresa else False
        porcentaje_iva = config_empresa.iva_porcentaje if iva_activo else Decimal("0.00")
        monto_iva = (
            (subtotal_con_descuento * porcentaje_iva / Decimal("100")).quantize(Decimal("0.01"))
            if iva_activo
            else Decimal("0.00")
        )

        # --- Validar limite de credito del cliente (deuda + lo que realmente se le suma a
        # la cuenta por cobrar: subtotal - descuento + IVA) ---
        if condicion_pago == "credito":
            deuda_actual = _deuda_pendiente_cliente(session, id_cliente)
            limite_credito = cliente.limite_credito if cliente.limite_credito is not None else Decimal("0.00")
            total_a_cobrar = subtotal_con_descuento + monto_iva
            if deuda_actual + total_a_cobrar > limite_credito:
                raise ValueError(
                    f"El cliente excede su limite de credito: deuda actual {deuda_actual} + "
                    f"nueva factura {total_a_cobrar} > limite {limite_credito}"
                )

        # id_tasa: si no se paso explicitamente, se toma un snapshot de la tasa de cambio
        # vigente al momento de la venta (mismo criterio que ComisionService/
        # NotaCreditoService -- efecto secundario interno de una accion ya autorizada, no
        # requiere su propio require_permiso de "tasas").
        if id_tasa is None:
            tasa_vigente = (
                session.query(ControlDeTasa)
                .order_by(ControlDeTasa.fecha_tasa.desc(), ControlDeTasa.id_tasa.desc())
                .first()
            )
            if tasa_vigente is not None:
                id_tasa = tasa_vigente.id_tasa

        # --- Insercion atomica de cabecera y lineas ---
        # numero_factura/numero_control definitivos se asignan DESPUES del flush -- ver
        # _numero_factura_temporal()/_numero_control_temporal() para el porque del
        # placeholder.
        factura = FacturaVenta(
            numero_factura=_numero_factura_temporal(),
            numero_control=_numero_control_temporal(),
            # fecha_emision explicita en vez de dejar el server_default=GETDATE() de la
            # columna: el reloj del contenedor de SQL Server puede estar desfasado del
            # reloj real del negocio (mismo riesgo de clock skew ya corregido en
            # pagos.py -- ver ESTADO_DEL_PROYECTO), y la factura digital le muestra la
            # hora de emision al cliente.
            fecha_emision=datetime.now(),
            id_cliente_factura=id_cliente,
            id_usuario_factura=id_usuario,
            id_vendedor=id_vendedor,
            condicion_pago=condicion_pago,
            fecha_vencimiento=fecha_vencimiento,
            id_tasa_factura=id_tasa,
            observaciones_factura=observaciones,
            iva_aplicado=iva_activo,
            porcentaje_iva_aplicado=porcentaje_iva,
            monto_iva=monto_iva,
            monto_descuento=monto_descuento,
            motivo_descuento=motivo_descuento if requiere_autorizacion_descuento else None,
            autorizado_por_descuento=id_autorizador_descuento if requiere_autorizacion_descuento else None,
        )
        session.add(factura)
        session.flush()
        factura.numero_factura = f"FV-{factura.id_factura:06d}"
        factura.numero_control = f"00-{factura.id_factura:08d}"

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
        # su comision). Este mismo flush es el que dispara (via trg_factura_total_ins ->
        # trg_factura_venta_cxc, triggers anidados) la apertura de la cuenta por cobrar
        # para creditos -- con saldo_pendiente = total_venta, o sea SIN el IVA todavia.
        session.flush()
        ComisionService.calcular_comisiones_factura(session, factura, detalles_creados, id_usuario)

        # El IVA/descuento se le suman/restan a la cuenta por cobrar recien abierta -- el
        # trigger la deja en total_venta (subtotal crudo, sin descuento ni IVA) porque no
        # conoce config_empresa ni monto_descuento, asi que se corrige aca, en la misma
        # transaccion, antes de comprometer.
        ajuste_cxc = monto_iva - monto_descuento
        if condicion_pago == "credito" and ajuste_cxc != 0:
            cxc = session.query(CuentaPorCobrar).filter(CuentaPorCobrar.id_factura == factura.id_factura).first()
            if cxc is not None:
                cxc.saldo_pendiente += ajuste_cxc

        session.commit()
        session.refresh(factura)

        logger.info(
            "Factura %s emitida: cliente=%s condicion_pago=%s total=%s usuario=%s",
            factura.numero_factura,
            id_cliente,
            condicion_pago,
            factura.total_venta,
            id_usuario,
        )

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="EMISION_FACTURA",
            modulo="VENTAS",
            detalle={
                "numero_factura": factura.numero_factura,
                "numero_control": factura.numero_control,
                "id_cliente": id_cliente,
                "condicion_pago": condicion_pago,
                "total_venta": str(factura.total_venta),
                "monto_iva": str(factura.monto_iva),
                "monto_descuento": str(factura.monto_descuento) if factura.monto_descuento > 0 else None,
                "autorizado_por_descuento": factura.autorizado_por_descuento,
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
        motivo = (motivo or "").strip()
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

        logger.info(
            "Factura %s anulada: motivo=%s monto_revertido_a_nota_credito=%s usuario=%s",
            factura.numero_factura,
            motivo,
            monto_pagado,
            id_usuario,
        )

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
        numero_factura: str | None = None,
        pagina: int = 1,
        por_pagina: int = 20,
        id_usuario: int | None = None,
    ) -> dict:
        require_permiso(session, id_usuario, "ventas", "ver")
        query = session.query(FacturaVenta).options(joinedload(FacturaVenta.cliente))
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
        if numero_factura:
            query = query.filter(FacturaVenta.numero_factura.ilike(f"%{numero_factura}%"))

        total = query.count()
        facturas = (
            query.order_by(FacturaVenta.fecha_emision.desc()).offset((pagina - 1) * por_pagina).limit(por_pagina).all()
        )
        return {"items": facturas, "total": total, "pagina": pagina, "por_pagina": por_pagina}

    @staticmethod
    def obtener_factura(session: Session, id_factura: int, id_usuario: int | None = None) -> dict:
        require_permiso(session, id_usuario, "ventas", "ver")
        factura = (
            session.query(FacturaVenta)
            .options(joinedload(FacturaVenta.cliente), joinedload(FacturaVenta.vendedor), joinedload(FacturaVenta.tasa))
            .filter(FacturaVenta.id_factura == id_factura)
            .first()
        )
        if factura is None:
            raise ValueError("Factura no encontrada")

        detalles = (
            session.query(FacturaDetalle)
            .options(joinedload(FacturaDetalle.producto))
            .filter(FacturaDetalle.id_factura == id_factura)
            .all()
        )
        return {"factura": factura, "detalles": detalles}

    @staticmethod
    def consultar_limite_disponible(session: Session, id_cliente: int, id_usuario: int | None = None) -> dict:
        """Para bloqueo visual proactivo en la UI (factura_form_dialog.py): cuanto puede
        cargarsele todavia a este cliente ANTES de armar/emitir la factura, sin duplicar
        la logica real de emitir_factura (misma consulta via _deuda_pendiente_cliente).
        Es solo informativo -- emitir_factura vuelve a validar todo server-side."""
        require_permiso(session, id_usuario, "ventas", "ver")
        cliente = session.get(Cliente, id_cliente)
        if cliente is None:
            raise ValueError("Cliente no encontrado")

        limite_credito = cliente.limite_credito if cliente.limite_credito is not None else Decimal("0.00")
        deuda_actual = _deuda_pendiente_cliente(session, id_cliente)
        return {
            "limite_credito": limite_credito,
            "deuda_actual": deuda_actual,
            "disponible": limite_credito - deuda_actual,
        }
