import logging
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    Caja,
    Cliente,
    ComisionFactura,
    ConfiguracionEmpresa,
    ControlDeTasa,
    CuentaBancaria,
    CuentaPorCobrar,
    FacturaDetalle,
    FacturaVenta,
    Inventario,
    NotaCreditoCliente,
    PagoCobro,
    ProductoPrecio,
    Vendedor,
)
from app.services.auditoria import AuditoriaService
from app.services.comisiones import ComisionService
from app.services.db_utils import _es_deadlock
from app.services.notas_credito import NotaCreditoService
from app.services.pagos import PagoService
from app.services.permisos import require_permiso
from app.services.tesoreria import BancoService, CajaService

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


def _cxc_vencida(cxc: CuentaPorCobrar, hoy: date) -> bool:
    return cxc.fecha_vencimiento is not None and cxc.fecha_vencimiento < hoy


def _calcular_estado_visual(estado_factura: str, cxc: CuentaPorCobrar | None, hoy: date) -> str:
    """Estado que se muestra en la UI (Emitida/Pagada/Parcial/Vencida/Anulada) --
    FacturaVenta.estado_factura en la base solo distingue EMITIDA/ANULADA (ver
    anular_factura), el resto se deriva de la cuenta por cobrar asociada. 'vencida' nunca
    se persiste en cuentas_por_cobrar.estado (el CHECK la admite pero ningun trigger la
    asigna) -- se calcula en el momento con el mismo criterio que
    DashboardService.CUENTA_ABIERTA / historial_cliente.py / reportes.py: pendiente o
    parcial con fecha_vencimiento ya pasada (hallazgo N1 de la auditoria de facturacion
    2026-08-25: antes la UI ofrecia un filtro/badge de 5 estados que nunca podia
    coincidir con nada porque la columna real es binaria)."""
    if estado_factura == "ANULADA":
        return "ANULADA"
    if cxc is None:
        return "EMITIDA"
    if cxc.estado == "pagada":
        return "PAGADA"
    if _cxc_vencida(cxc, hoy):
        return "VENCIDA"
    if cxc.estado == "parcial":
        return "PARCIAL"
    return "EMITIDA"


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


def _convertir_a_usd(monto_moneda_origen: Decimal, moneda: str, tasa: ControlDeTasa | None) -> Decimal:
    """Equivalente en USD de un monto tendido en `moneda` -- USD/USDT es 1:1 (USDT se
    trata como stablecoin fijo al dolar, practica estandar), VES/COP se convierten con la
    tasa vigente snapshoteada en la factura."""
    if moneda in ("USD", "USDT"):
        return monto_moneda_origen
    if tasa is None:
        raise ValueError(f"No hay tasa de cambio configurada para convertir un pago en {moneda}")
    if moneda == "VES":
        return (monto_moneda_origen / tasa.tasa_dolar_bcv).quantize(Decimal("0.01"))
    if moneda == "COP":
        if not tasa.tasa_cop:
            raise ValueError("No hay tasa COP configurada para convertir este pago")
        return (monto_moneda_origen / tasa.tasa_cop).quantize(Decimal("0.01"))
    raise ValueError(f"moneda de pago invalida: {moneda}")


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
        pagos: list[dict] | None = None,
        dias_credito_personalizados: int | None = None,
        motivo_dias_credito: str | None = None,
        id_autorizador_dias_credito: int | None = None,
        metodo_vuelto: str | None = None,
        id_caja_vuelto: int | None = None,
        id_cuenta_bancaria_vuelto: int | None = None,
        referencia_vuelto: str | None = None,
        id_autorizador_vuelto: int | None = None,
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

        # Una factura de contado exige registrar como minimo una forma de pago (se abre y
        # se liquida la cuenta por cobrar en la misma transaccion, ver mas abajo); una de
        # credito sigue el flujo de siempre y no admite pagos en el momento de emitir.
        pagos = pagos or []
        if condicion_pago == "contado" and not pagos:
            raise ValueError("Una factura de contado requiere al menos una forma de pago")
        if condicion_pago == "credito" and pagos:
            raise ValueError("condicion_pago='credito' no admite pagos al emitir la factura")
        if pagos:
            require_permiso(session, id_usuario, "pagos", "crear")

        if observaciones is not None and len(observaciones) > 255:
            raise ValueError("observaciones no puede superar 255 caracteres")

        # Credito exige que el cliente tenga dias_credito configurados (>0) -- un cliente
        # nuevo sin configurar queda forzado a contado, ver docs/ESTADO_DEL_PROYECTO.md.
        # dias_credito_personalizados permite dar una cantidad distinta a la configurada
        # para esta factura puntual, pero requiere autorizacion de un supervisor con
        # permiso 'creditos'/'crear' (motivo_dias_credito + id_autorizador_dias_credito),
        # simetrico al mecanismo ya existente para descuentos mas abajo. Este gate aplica
        # siempre que condicion_pago == 'credito', incluso si el caller pasa
        # fecha_vencimiento explicita -- es un gate de elegibilidad del cliente, no de
        # calculo de fecha (una venta a credito puede seguir cargandose con una fecha ya
        # vencida/backdateada, ver test_por_cobrar_suma_saldos_abiertos_y_cuenta_vencidas,
        # pero el cliente igual debe calificar para credito).
        dias_credito_aplicados = None
        hubo_override_dias_credito = False
        if condicion_pago == "credito":
            dias_credito_cliente = cliente.dias_credito or 0
            if dias_credito_cliente <= 0:
                raise ValueError(
                    f"El cliente '{cliente.nombre_razon_social}' no tiene dias de credito "
                    "configurados y no puede facturarse a credito"
                )
            dias_credito_aplicados = dias_credito_cliente
            if dias_credito_personalizados is not None and dias_credito_personalizados != dias_credito_cliente:
                if dias_credito_personalizados <= 0:
                    raise ValueError("dias_credito_personalizados debe ser mayor a 0")
                if not motivo_dias_credito:
                    raise ValueError("El cambio de dias de credito requiere un motivo")
                if id_autorizador_dias_credito is None:
                    raise ValueError("El cambio de dias de credito requiere autorizacion de un supervisor")
                require_permiso(session, id_autorizador_dias_credito, "creditos", "crear")
                dias_credito_aplicados = dias_credito_personalizados
                hubo_override_dias_credito = True
            if fecha_vencimiento is None:
                fecha_vencimiento = date.today() + timedelta(days=dias_credito_aplicados)
        elif dias_credito_personalizados is not None:
            raise ValueError("dias_credito_personalizados solo aplica a condicion_pago='credito'")

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
        # Existencia primero: sin este chequeo, un id_producto inexistente cae directo en
        # el gate de precio de lista de abajo (no aparece en precios_lista porque no
        # existe, ni en ninguna tabla) y el usuario ve "no tiene precio configurado" en
        # vez de "no encontrado" -- un mensaje enganoso que sugiere que el producto existe
        # pero le falta el precio. El chequeo real con lock (UPDLOCK/ROWLOCK) sigue
        # ocurriendo mas abajo al validar stock; este es solo para dar el mensaje correcto
        # antes de evaluar nada mas.
        productos_existentes = {
            p.id_producto
            for p in session.query(Inventario.id_producto).filter(Inventario.id_producto.in_(ids_producto_items))
        }
        ids_inexistentes = ids_producto_items - productos_existentes
        if ids_inexistentes:
            raise ValueError(f"Producto {next(iter(ids_inexistentes))} no encontrado")

        precios_lista = {
            precio.id_producto: precio.precio_venta
            for precio in session.query(ProductoPrecio).filter(ProductoPrecio.id_producto.in_(ids_producto_items)).all()
        }
        # Todo producto vendible debe tener un precio de lista configurado -- sin uno, no
        # hay forma de detectar automaticamente si el vendedor le puso un precio bajo
        # (requiere autorizacion) o alto (genera comision, ver ComisionService), dejando
        # ese hueco sin control. Bloquea aca, antes de tocar stock/CxC/comisiones -- si un
        # producto nuevo todavia no tiene precio, se le asigna uno en Inventario primero.
        ids_sin_precio = ids_producto_items - precios_lista.keys()
        if ids_sin_precio:
            productos_sin_precio = ", ".join(
                p.nombre_producto
                for p in session.query(Inventario).filter(Inventario.id_producto.in_(ids_sin_precio)).all()
            )
            raise ValueError(
                f"Los siguientes productos no tienen precio de venta configurado: {productos_sin_precio}. "
                "Configure un precio en Inventario antes de venderlos."
            )
        hay_precio_bajo_lista = any(
            Decimal(str(item["precio_unitario"])) < precios_lista[item["id_producto"]] for item in items
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

        # sorted() por id_producto: dos facturas concurrentes que comparten productos
        # pero los cargaron en distinto orden en el carrito adquiririan los locks en
        # orden cruzado sin esto -> deadlock de SQL Server. Un orden total fijo (el
        # mismo para cualquier transaccion) elimina la posibilidad de cruce.
        for id_producto, cantidad_requerida in sorted(cantidades_por_producto.items()):
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
            # Validar que la venta no deje stock por debajo de cantidad_minima
            saldo_posterior = producto.cantidad_unidad - cantidad_requerida
            if saldo_posterior < (producto.cantidad_minima or 0):
                raise ValueError(
                    f"La venta de {cantidad_requerida} unidades de '{producto.nombre_producto}' "
                    f"dejaría stock en {saldo_posterior}, por debajo del mínimo configurado "
                    f"({producto.cantidad_minima})"
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
        # Lo que efectivamente se le suma a la cuenta por cobrar (subtotal - descuento +
        # IVA) -- se usa tanto para el limite de credito (solo credito) como para validar
        # que la suma de formas de pago cubra la factura (solo contado, ver mas abajo).
        total_a_cobrar = subtotal_con_descuento + monto_iva

        # --- Validar limite de credito del cliente ---
        if condicion_pago == "credito":
            # WITH (UPDLOCK, ROWLOCK): mismo patron que el stock mas arriba (hallazgo #2
            # de la auditoria de facturacion) -- sin esto, dos ventas a credito
            # concurrentes al MISMO cliente pueden ambas leer la misma deuda_actual antes
            # de que ninguna haya commiteado su propia CuentaPorCobrar, pasar la
            # validacion cada una por separado, y juntas superar limite_credito. Bloquea
            # la fila del cliente hasta el commit/rollback de esta transaccion -- la
            # segunda venta concurrente espera aca y, gracias a READ_COMMITTED_SNAPSHOT
            # (migrations/0015), su propia lectura de deuda_actual despues de obtener el
            # lock ya ve la CuentaPorCobrar que la primera transaccion dejo commiteada.
            session.execute(
                select(Cliente)
                .where(Cliente.id_cliente == id_cliente)
                .with_hint(Cliente, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
            ).scalar_one()
            deuda_actual = _deuda_pendiente_cliente(session, id_cliente)
            limite_credito = cliente.limite_credito if cliente.limite_credito is not None else Decimal("0.00")
            if deuda_actual + total_a_cobrar > limite_credito:
                raise ValueError(
                    f"El cliente excede su limite de credito: deuda actual {deuda_actual} + "
                    f"nueva factura {total_a_cobrar} > limite {limite_credito}"
                )

        # id_tasa: si no se paso explicitamente, se toma un snapshot de la tasa de cambio
        # vigente al momento de la venta (mismo criterio que ComisionService/
        # NotaCreditoService -- efecto secundario interno de una accion ya autorizada, no
        # requiere su propio require_permiso de "tasas"). Se resuelve ANTES de validar los
        # pagos de contado porque hace falta la tasa para convertir montos en VES/COP.
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

        # --- Contado: validar que la suma de las formas de pago (convertidas a USD) cubra
        # el total ANTES de insertar nada -- si falta, la factura no se emite. Se guarda el
        # equivalente USD ya calculado por linea para no recalcularlo (ni arriesgar un
        # resultado distinto si la tasa cambiara) al aplicar los pagos mas abajo.
        pagos_usd: list[Decimal] = []
        total_pagado = Decimal("0.00")
        if condicion_pago == "contado":
            for pago_linea in pagos:
                monto_origen = Decimal(str(pago_linea["monto_moneda_origen"]))
                if monto_origen <= 0:
                    raise ValueError("Cada forma de pago requiere un monto mayor a cero")
                monto_usd = _convertir_a_usd(monto_origen, pago_linea["moneda"], tasa_vigente)
                pagos_usd.append(monto_usd)
                total_pagado += monto_usd
            if total_pagado < total_a_cobrar:
                raise ValueError(
                    f"Las formas de pago suman ${total_pagado} y no cubren el total de la "
                    f"factura (${total_a_cobrar}); faltan ${total_a_cobrar - total_pagado}"
                )

        # --- Vuelto (cambio): el excedente de pagos sobre total_a_cobrar SIEMPRE se
        # entrega al cliente (no existe "saldo a favor" como metodo de vuelto, decision de
        # alcance) -- ver migrations/0027_vuelto_factura.sql. Efectivo es libre y se
        # registra como egreso real de caja (mas abajo, DESPUES de aplicar los pagos de
        # contado -- ver el comentario en ese bloque sobre por que el saldo se valida ahi y
        # no aca); pago_movil/transferencia exige referencia bancaria + autorizacion de un
        # usuario con permiso 'vueltos_bancarios'/'crear' (mismo mecanismo que 'descuentos'/
        # 'creditos' -- ADMIN bypassa siempre, ningun rol lo tiene por default).
        monto_vuelto = Decimal("0.00")
        if condicion_pago == "contado":
            monto_vuelto = (total_pagado - total_a_cobrar).quantize(Decimal("0.01"))
        elif metodo_vuelto is not None:
            raise ValueError("metodo_vuelto solo aplica a facturas de contado")

        # Si hay vuelto y el caller no indico un metodo explicito, pero las formas de pago
        # usaron una unica caja (efectivo), el vuelto se infiere de esa misma caja -- mismo
        # criterio que un cajero real (el cambio sale del mismo cajon de donde entro el
        # efectivo), sin obligar a declarar lo obvio. Solo se infiere efectivo: pago_movil/
        # transferencia siempre requieren seleccion explicita + autorizacion, nunca se
        # infieren (y si hay mas de una caja involucrada o ninguna, no hay una unica
        # respuesta obvia -- se exige explicitar mas abajo).
        if monto_vuelto > 0 and metodo_vuelto is None and id_caja_vuelto is None and id_cuenta_bancaria_vuelto is None:
            cajas_usadas = {p.get("id_caja") for p in pagos if p.get("id_caja") is not None}
            if len(cajas_usadas) == 1:
                metodo_vuelto = "efectivo"
                (id_caja_vuelto,) = cajas_usadas

        caja_vuelto = None
        if monto_vuelto > 0:
            if metodo_vuelto not in ("efectivo", "pago_movil", "transferencia"):
                raise ValueError(
                    "Esta factura tiene vuelto: indique metodo_vuelto ('efectivo', 'pago_movil' o 'transferencia')"
                )
            if metodo_vuelto == "efectivo":
                if id_caja_vuelto is None:
                    raise ValueError("El vuelto en efectivo requiere indicar la caja de origen")
                if id_cuenta_bancaria_vuelto is not None:
                    raise ValueError("El vuelto en efectivo no admite cuenta bancaria de origen")
                # WITH (UPDLOCK, ROWLOCK): mismo patron que Inventario/Cliente mas arriba --
                # bloquea la fila hasta el commit para que dos vueltos concurrentes de la
                # misma caja no lean el mismo saldo stale (C1). Solo se valida aca que la
                # caja exista y tenga turno abierto; el saldo en si se compara MAS ABAJO,
                # despues de aplicar los pagos de contado -- un vuelto en efectivo suele
                # financiarse con el propio efectivo que el cliente acaba de entregar en
                # esta misma factura, que todavia no se aplico en este punto.
                caja_vuelto = session.execute(
                    select(Caja)
                    .where(Caja.id_caja == id_caja_vuelto)
                    .with_hint(Caja, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
                ).scalar_one_or_none()
                if caja_vuelto is None:
                    raise ValueError("Caja de vuelto no encontrada")
                if caja_vuelto.fecha_apertura is None or caja_vuelto.fecha_cierre is not None:
                    raise ValueError(f"La caja '{caja_vuelto.nombre_caja}' no tiene un turno abierto")
            else:
                if id_cuenta_bancaria_vuelto is None:
                    raise ValueError("El vuelto por pago movil/transferencia requiere una cuenta bancaria de origen")
                if id_caja_vuelto is not None:
                    raise ValueError("El vuelto por pago movil/transferencia no admite caja de origen")
                cuenta_vuelto = session.get(CuentaBancaria, id_cuenta_bancaria_vuelto)
                if cuenta_vuelto is None:
                    raise ValueError("Cuenta bancaria de vuelto no encontrada")
                if cuenta_vuelto.estado_cuenta != "ACTIVO":
                    raise ValueError(f"La cuenta bancaria '{cuenta_vuelto.numero_cuenta}' esta inactiva")
                referencia_vuelto = (referencia_vuelto or "").strip()
                if len(referencia_vuelto) < 4:
                    raise ValueError(
                        "El vuelto por pago movil/transferencia requiere una referencia "
                        "bancaria de al menos 4 caracteres"
                    )
                if len(referencia_vuelto) > 50:
                    raise ValueError("La referencia bancaria del vuelto no puede superar 50 caracteres")
                if id_autorizador_vuelto is None:
                    raise ValueError("El vuelto por pago movil/transferencia requiere autorizacion de un supervisor")
                require_permiso(session, id_autorizador_vuelto, "vueltos_bancarios", "crear")
        elif metodo_vuelto is not None:
            raise ValueError("metodo_vuelto solo aplica si hay vuelto a favor del cliente")

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
            dias_credito_aplicados=dias_credito_aplicados,
            motivo_dias_credito=motivo_dias_credito if hubo_override_dias_credito else None,
            autorizado_por_dias_credito=id_autorizador_dias_credito if hubo_override_dias_credito else None,
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
        # transaccion, antes de comprometer. Desde migrations/0024 el trigger abre cuenta
        # por cobrar tanto para credito como para contado, asi que el ajuste aplica a
        # ambas condiciones (antes era solo credito).
        cxc = session.query(CuentaPorCobrar).filter(CuentaPorCobrar.id_factura == factura.id_factura).first()
        ajuste_cxc = monto_iva - monto_descuento
        if cxc is not None and ajuste_cxc != 0:
            cxc.saldo_pendiente += ajuste_cxc

        # --- Contado: liquidar la cuenta por cobrar recien abierta con las formas de pago
        # ya validadas arriba, en la MISMA transaccion (se aplica con _aplicar_pago_cobro,
        # que hace flush pero no commit -- el commit unico de mas abajo cubre factura +
        # detalle + comision + cuenta por cobrar + pagos + vuelto, todo o nada). Si la suma
        # tendida excede el total (p. ej. efectivo con vuelto), cada linea se recorta al
        # saldo restante -- el excedente es el vuelto ya validado/calculado mas arriba
        # (monto_vuelto). Una linea que quede en 0 (ya cubierta por lineas anteriores) no
        # aplica nada a la cuenta por cobrar, pero su excedente igual se registra como
        # ingreso en el origen de ESA linea (ver mas abajo) -- sin esto, el efectivo/banco
        # que si entro fisicamente mas alla de lo que necesitaba la factura quedaria sin
        # asiento, y el egreso del vuelto (mas abajo, unico y contra el origen elegido por
        # el cajero) lo restaria una segunda vez.
        if condicion_pago == "contado" and cxc is not None:
            for pago_linea, monto_usd in zip(pagos, pagos_usd, strict=True):
                monto_a_aplicar = min(monto_usd, cxc.saldo_pendiente)
                if monto_a_aplicar > 0:
                    PagoService._aplicar_pago_cobro(
                        session,
                        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
                        monto=monto_a_aplicar,
                        metodo_pago=pago_linea["metodo_pago"],
                        moneda=pago_linea["moneda"],
                        monto_moneda_origen=pago_linea["monto_moneda_origen"],
                        id_cuenta_bancaria=pago_linea.get("id_cuenta_bancaria"),
                        id_caja=pago_linea.get("id_caja"),
                        id_tasa=id_tasa,
                        referencia=pago_linea.get("referencia"),
                        fecha_pago=factura.fecha_emision,
                        id_usuario=id_usuario,
                    )

                excedente_linea = (monto_usd - monto_a_aplicar).quantize(Decimal("0.01"))
                if excedente_linea > 0:
                    descripcion_excedente = f"Excedente de pago factura {factura.numero_factura} (vuelto pendiente)"
                    id_caja_linea = pago_linea.get("id_caja")
                    id_cuenta_linea = pago_linea.get("id_cuenta_bancaria")
                    if id_caja_linea is not None:
                        CajaService._registrar_ingreso_excedente(
                            session,
                            id_caja=id_caja_linea,
                            monto=excedente_linea,
                            descripcion=descripcion_excedente,
                            id_usuario=id_usuario,
                            fecha=factura.fecha_emision,
                        )
                    elif id_cuenta_linea is not None:
                        BancoService._registrar_ingreso_excedente(
                            session,
                            id_cuenta=id_cuenta_linea,
                            monto=excedente_linea,
                            descripcion=descripcion_excedente,
                            id_usuario=id_usuario,
                            fecha=factura.fecha_emision,
                        )

        if monto_vuelto > 0:
            descripcion_vuelto = f"Vuelto factura {factura.numero_factura}"
            fecha_vuelto: datetime = factura.fecha_emision
            if metodo_vuelto == "efectivo":
                # id_caja_vuelto/caja_vuelto ya se validaron como no-None mas arriba (unico
                # camino para llegar aca con metodo_vuelto == "efectivo").
                assert id_caja_vuelto is not None and caja_vuelto is not None
                # Recien aca, con los pagos de contado ya aplicados (el efectivo entregado
                # por el cliente en ESTA factura ya se sumo al saldo de caja via
                # _aplicar_pago_cobro -> trg_pagos_cobros_io), se compara el saldo real.
                saldo_actual_caja = CajaService.calcular_saldo_actual(session, id_caja_vuelto)
                if saldo_actual_caja < monto_vuelto:
                    raise ValueError(
                        f"La caja '{caja_vuelto.nombre_caja}' no tiene saldo suficiente para el "
                        f"vuelto: disponible ${saldo_actual_caja}, requerido ${monto_vuelto}"
                    )
                CajaService._registrar_egreso_vuelto(
                    session,
                    id_caja=id_caja_vuelto,
                    monto=monto_vuelto,
                    descripcion=descripcion_vuelto,
                    id_usuario=id_usuario,
                    fecha=fecha_vuelto,
                )
            else:
                # id_cuenta_bancaria_vuelto/referencia_vuelto ya se validaron como no-None
                # mas arriba (unico camino para llegar aca con metodo_vuelto bancario).
                assert id_cuenta_bancaria_vuelto is not None and referencia_vuelto is not None
                BancoService._registrar_egreso_vuelto(
                    session,
                    id_cuenta=id_cuenta_bancaria_vuelto,
                    monto=monto_vuelto,
                    descripcion=descripcion_vuelto,
                    referencia=referencia_vuelto,
                    id_usuario=id_usuario,
                    fecha=fecha_vuelto,
                )

            factura.monto_vuelto = monto_vuelto
            factura.metodo_vuelto = metodo_vuelto
            factura.referencia_vuelto = referencia_vuelto if metodo_vuelto != "efectivo" else None
            factura.autorizado_por_vuelto = id_autorizador_vuelto if metodo_vuelto != "efectivo" else None
            factura.fecha_autorizacion_vuelto = datetime.now() if metodo_vuelto != "efectivo" else None

        try:
            session.commit()
        except Exception as e:
            session.rollback()
            if _es_deadlock(e):
                # Se relanza tal cual (no como ValueError) para que el caller pueda
                # distinguirlo y reintentar la operacion completa -- ver
                # app.services.db_utils.reintentar_en_deadlock.
                raise
            raise ValueError(f"Error al emitir factura: {str(e)}") from e
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
                "dias_credito_aplicados": factura.dias_credito_aplicados,
                "autorizado_por_dias_credito": factura.autorizado_por_dias_credito,
                "monto_vuelto": str(factura.monto_vuelto) if factura.monto_vuelto > 0 else None,
                "metodo_vuelto": factura.metodo_vuelto,
                "autorizado_por_vuelto": factura.autorizado_por_vuelto,
                "pagos": (
                    [
                        {"metodo_pago": p["metodo_pago"], "moneda": p["moneda"], "monto_usd": str(monto_usd)}
                        for p, monto_usd in zip(pagos, pagos_usd, strict=True)
                    ]
                    if condicion_pago == "contado"
                    else None
                ),
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
            # WITH (UPDLOCK, ROWLOCK): mismo patron que C1/C18/C22/C24 (ver tambien
            # PagoComisionService.pagar_comisiones_vendedor) -- sin esto, un pago de
            # comisiones concurrente puede marcar 'pagada' una de estas filas justo
            # despues de leerla aca como 'pendiente' pero antes del DELETE de mas abajo:
            # la anulacion pasaria el guard igual y borraria una comision que el vendedor
            # ya cobro de verdad.
            comisiones = (
                session.execute(
                    select(ComisionFactura)
                    .where(ComisionFactura.id_factura_detalle.in_(ids_detalle))
                    .with_hint(ComisionFactura, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
                )
                .scalars()
                .all()
            )
            if any(comision.estado_pago == "pagada" for comision in comisiones):
                raise ValueError("No se puede anular: hay comisiones ya pagadas sobre esta factura.")
            # 'liberada' (cliente ya pago la factura, el vendedor aun no cobro la
            # comision) tambien bloquea la anulacion: el dinero de la venta ya entro
            # (contado, o credito ya cobrado via trg_cxc_libera_comisiones,
            # migrations/0045), asi que el vendedor ya tiene derecho a esa comision --
            # borrarla silenciosamente le haria perder un ingreso ya generado sin dejar
            # rastro. A diferencia de 'pendiente' (cliente todavia no pago, no hay nada
            # que preservar), esta no se resuelve sola: anular de todas formas requiere
            # decidir aparte que hacer con esa comision (pagarla igual, o no).
            if any(comision.estado_pago == "liberada" for comision in comisiones):
                raise ValueError(
                    "No se puede anular: hay comisiones liberadas (venta ya cobrada) sin pagar al vendedor "
                    "sobre esta factura."
                )
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

        # La nota de credito se crea AHORA, con el nucleo interno sin commit propio
        # (NotaCreditoService._crear_nota_credito_cliente), en la MISMA transaccion que la
        # anulacion -- antes cada una comiteaba por separado (la anulacion arriba, la nota
        # de credito en su propio commit() dentro del metodo publico): si esa segunda
        # insercion fallaba, la anulacion ya habia quedado comprometida sin su
        # compensacion, y el dinero que el cliente ya pago desaparecia contablemente sin
        # dejar rastro ni forma de revertir. numero_nota_credito se captura en una
        # variable local ANTES del commit -- despues de comitear la sesion expira los
        # atributos por defecto, y no hace falta un refresh extra solo para loguear/auditar
        # un string que ya no cambia.
        numero_nota_credito = None
        if monto_pagado > 0:
            nota_credito = NotaCreditoService._crear_nota_credito_cliente(
                session,
                id_cliente=factura.id_cliente_factura,
                id_factura_origen=id_factura,
                monto=monto_pagado,
                motivo=motivo,
                id_usuario=id_usuario,
            )
            numero_nota_credito = nota_credito.numero_nota_credito

        session.commit()
        session.refresh(factura)

        logger.info(
            "Factura %s anulada: motivo=%s monto_revertido_a_nota_credito=%s nota_credito=%s usuario=%s",
            factura.numero_factura,
            motivo,
            monto_pagado,
            numero_nota_credito,
            id_usuario,
        )

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="ANULACION_FACTURA",
            modulo="VENTAS",
            detalle={
                "numero_factura": factura.numero_factura,
                "motivo": motivo,
                "nota_credito_generada": numero_nota_credito,
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
        nombre_cliente: str | None = None,
        texto_busqueda: str | None = None,
        pagina: int = 1,
        por_pagina: int = 20,
        id_usuario: int | None = None,
    ) -> dict:
        require_permiso(session, id_usuario, "ventas", "ver")
        # joinedload(vendedor): FacturacionPanel muestra el vendedor en el listado
        # (hallazgo #12 de la auditoria de facturacion) -- sin esto cada fila dispara su
        # propio SELECT lazy al acceder a factura.vendedor.nombre_vendedor (N+1).
        query = session.query(FacturaVenta).options(joinedload(FacturaVenta.cliente), joinedload(FacturaVenta.vendedor))
        if fecha_desde:
            query = query.filter(FacturaVenta.fecha_emision >= fecha_desde)
        if fecha_hasta:
            query = query.filter(FacturaVenta.fecha_emision <= fecha_hasta)
        if id_cliente:
            query = query.filter(FacturaVenta.id_cliente_factura == id_cliente)
        if condicion_pago:
            query = query.filter(FacturaVenta.condicion_pago == condicion_pago)
        if numero_factura:
            query = query.filter(FacturaVenta.numero_factura.ilike(f"%{numero_factura}%"))
        if nombre_cliente:
            # Usar subquery para filtrar por nombre de cliente sin afectar los joinedloads
            subq_cliente = session.query(Cliente.id_cliente).filter(
                Cliente.nombre_razon_social.ilike(f"%{nombre_cliente}%")
            )
            query = query.filter(FacturaVenta.id_cliente_factura.in_(subq_cliente))
        if texto_busqueda:
            # Barra de busqueda unica del listado (FacturacionPanel): matchea CUALQUIERA
            # de los datos que se muestran en pantalla -- numero de factura, cliente o
            # vendedor -- en vez de exigir que el cajero sepa en cual de dos/tres cajas
            # separadas escribir. numero_factura/nombre_cliente (arriba) se mantienen
            # aparte para uso programatico/tests que quieran un filtro AND preciso.
            like = f"%{texto_busqueda}%"
            subq_cliente_texto = session.query(Cliente.id_cliente).filter(Cliente.nombre_razon_social.ilike(like))
            subq_vendedor_texto = session.query(Vendedor.id_vendedor).filter(Vendedor.nombre_vendedor.ilike(like))
            query = query.filter(
                FacturaVenta.numero_factura.ilike(like)
                | FacturaVenta.id_cliente_factura.in_(subq_cliente_texto)
                | FacturaVenta.id_vendedor.in_(subq_vendedor_texto)
            )

        hoy = date.today()
        if estado:
            # estado_factura solo es EMITIDA/ANULADA en la base -- PAGADA/PARCIAL/VENCIDA
            # se derivan de cuentas_por_cobrar (ver _calcular_estado_visual). Se filtra por
            # subquery de id_factura en vez de un join directo para no arriesgar el
            # fanout de filas que un join normal produciria junto a los joinedload de
            # cliente/vendedor de arriba (hallazgo N1 de la auditoria 2026-08-25).
            if estado == "ANULADA":
                query = query.filter(FacturaVenta.estado_factura == "ANULADA")
            elif estado == "PAGADA":
                subq = session.query(CuentaPorCobrar.id_factura).filter(CuentaPorCobrar.estado == "pagada")
                query = query.filter(FacturaVenta.id_factura.in_(subq))
            elif estado == "PARCIAL":
                subq = session.query(CuentaPorCobrar.id_factura).filter(
                    CuentaPorCobrar.estado == "parcial",
                    or_(CuentaPorCobrar.fecha_vencimiento.is_(None), CuentaPorCobrar.fecha_vencimiento >= hoy),
                )
                query = query.filter(FacturaVenta.id_factura.in_(subq))
            elif estado == "VENCIDA":
                subq = session.query(CuentaPorCobrar.id_factura).filter(
                    CuentaPorCobrar.estado.in_(("pendiente", "parcial")),
                    CuentaPorCobrar.fecha_vencimiento < hoy,
                )
                query = query.filter(FacturaVenta.id_factura.in_(subq))
            elif estado == "EMITIDA":
                subq_abierta_no_vencida = session.query(CuentaPorCobrar.id_factura).filter(
                    CuentaPorCobrar.estado == "pendiente",
                    or_(CuentaPorCobrar.fecha_vencimiento.is_(None), CuentaPorCobrar.fecha_vencimiento >= hoy),
                )
                subq_con_cxc = session.query(CuentaPorCobrar.id_factura)
                query = query.filter(
                    FacturaVenta.estado_factura == "EMITIDA",
                    or_(
                        FacturaVenta.id_factura.notin_(subq_con_cxc),
                        FacturaVenta.id_factura.in_(subq_abierta_no_vencida),
                    ),
                )

        total = query.count()
        facturas = (
            query.order_by(FacturaVenta.fecha_emision.desc()).offset((pagina - 1) * por_pagina).limit(por_pagina).all()
        )

        # estado_visual: atributo Python plano (no mapeado), calculado en un solo batch
        # para toda la pagina en vez de N+1 -- ver _calcular_estado_visual.
        ids_pagina = [f.id_factura for f in facturas]
        cxc_por_factura = {}
        if ids_pagina:
            cxc_por_factura = {
                c.id_factura: c
                for c in session.query(CuentaPorCobrar).filter(CuentaPorCobrar.id_factura.in_(ids_pagina)).all()
            }

        # Metodos de pago para ventas de contado -- una factura puede tener varias lineas
        # de pago con metodos distintos (PagoLineaDialog en la UI permite repartir el
        # total). Se agrupan TODAS las lineas por cxc (antes un dict {id_cxc: ultimo_pago}
        # se quedaba con una arbitraria y descartaba el resto en silencio).
        pagos_por_cxc: dict[int, list[PagoCobro]] = {}
        if cxc_por_factura:
            ids_cxc = [c.id_cuenta_por_cobrar for c in cxc_por_factura.values()]
            if ids_cxc:
                for p in session.query(PagoCobro).filter(PagoCobro.id_cuenta_por_cobrar.in_(ids_cxc)).all():
                    pagos_por_cxc.setdefault(p.id_cuenta_por_cobrar, []).append(p)

        for f in facturas:
            f.estado_visual = _calcular_estado_visual(f.estado_factura, cxc_por_factura.get(f.id_factura), hoy)

            # "mixto" es un sentinel para mas de un metodo distinto -- ver
            # historial_cliente.obtener_historial_cliente() para el mismo criterio.
            f.metodo_pago = None
            if f.condicion_pago == "contado":
                cxc = cxc_por_factura.get(f.id_factura)
                if cxc:
                    metodos_distintos = list(
                        dict.fromkeys(p.metodo_pago for p in pagos_por_cxc.get(cxc.id_cuenta_por_cobrar, []))
                    )
                    if len(metodos_distintos) == 1:
                        f.metodo_pago = metodos_distintos[0]
                    elif len(metodos_distintos) > 1:
                        f.metodo_pago = "mixto"

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

        cxc = session.query(CuentaPorCobrar).filter(CuentaPorCobrar.id_factura == id_factura).first()
        factura.estado_visual = _calcular_estado_visual(factura.estado_factura, cxc, date.today())

        # Todas las lineas de pago para ventas de contado -- una factura puede tener mas
        # de una (PagoLineaDialog permite repartir el total entre varios metodos/monedas),
        # y el detalle de factura necesita mostrarlas TODAS, no solo la primera (antes
        # `.first()` descartaba el resto en silencio). "mixto" en `metodo_pago` es el mismo
        # sentinel que usa listar_facturas()/historial_cliente para mas de un metodo
        # distinto -- queda ademas la lista completa en "pagos" para el desglose.
        pagos_cobro: list[PagoCobro] = []
        if factura.condicion_pago == "contado" and cxc:
            pagos_cobro = (
                session.query(PagoCobro)
                .filter(PagoCobro.id_cuenta_por_cobrar == cxc.id_cuenta_por_cobrar)
                .order_by(PagoCobro.fecha_pago)
                .all()
            )
        metodo_pago = None
        if pagos_cobro:
            metodos_distintos = list(dict.fromkeys(p.metodo_pago for p in pagos_cobro))
            metodo_pago = metodos_distintos[0] if len(metodos_distintos) == 1 else "mixto"

        detalles = (
            session.query(FacturaDetalle)
            .options(joinedload(FacturaDetalle.producto))
            .filter(FacturaDetalle.id_factura == id_factura)
            .all()
        )

        # Nota de credito que esta factura genero al anularse (si la hubo) -- a lo sumo
        # una por factura (anular_factura crea una sola, ver NotaCreditoService). Se
        # incluye aca para que FacturaDetalleDialog pueda ofrecer un atajo directo de
        # "Devolver esta nota" sin que el usuario tenga que ir a buscarla al historial
        # del cliente.
        nota_credito = (
            session.query(NotaCreditoCliente).filter(NotaCreditoCliente.id_factura_origen == id_factura).first()
        )

        return {
            "factura": factura,
            "detalles": detalles,
            "metodo_pago": metodo_pago,
            "pagos": pagos_cobro,
            "nota_credito": nota_credito,
        }

    @staticmethod
    def consultar_limite_disponible(session: Session, id_cliente: int, id_usuario: int | None = None) -> dict:
        """Para bloqueo visual proactivo en la UI (factura_form_dialog.py): cuanto puede
        cargarsele todavia a este cliente ANTES de armar/emitir la factura, sin duplicar
        la logica real de emitir_factura (misma consulta via _deuda_pendiente_cliente).
        Es solo informativo -- emitir_factura vuelve a validar todo server-side.

        elegible_credito refleja el mismo gate que emitir_factura() aplica (cliente.
        dias_credito > 0) -- sin esto, un cliente sin dias de credito configurados
        mostraba igual un "disponible" positivo (si limite_credito > 0) que no tiene
        ningun efecto real: no puede facturarse a credito por ningun monto (hallazgo #9
        de la auditoria de facturacion)."""
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
            "elegible_credito": (cliente.dias_credito or 0) > 0,
        }
