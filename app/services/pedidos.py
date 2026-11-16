"""Pedidos de venta tomados por los vendedores (migrations/0100), con reserva de stock.

Un pedido no es una factura: no mueve inventario, no abre cuentas por cobrar ni genera comisiones. Aparta
unidades (ver `reservas_stock`) mientras espera que caja/admin lo revise, y se convierte en factura con
`convertir_a_factura` (que llama a `VentaService.emitir_factura(id_pedido=...)`: el pedido y la factura se
cierran en el mismo commit).

Ciclo de vida:

    ENVIADO  --aprobar-->  APROBADO  --convertir_a_factura-->  FACTURADO
    ENVIADO  --rechazar--> RECHAZADO
    ENVIADO  --48 h sin revisar--> VENCIDO --aprobar (si aun hay stock)--> APROBADO
    ENVIADO o APROBADO --anular--> ANULADO  (APROBADO solo lo anula quien revisa)

Alcance: un usuario VENDEDOR solo crea pedidos a su nombre, solo para los clientes que tiene asignados y solo
ve y anula los suyos mientras no estan aprobados. Se aplica aqui, en el servicio, no en la pantalla (mismo criterio que
`alcance_vendedor.py`).
"""

import logging
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, literal_column, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db.models import Cliente, Inventario, Pedido, PedidoDetalle, Vendedor
from app.services.alcance_vendedor import vendedor_propio
from app.services.auditoria import AuditoriaService
from app.services.db_utils import aplicar_lock_timeout, confirmar_transaccion, traducir_error_trigger
from app.services.paginacion import paginar
from app.services.permisos import PermisoDenegadoError, require_permiso
from app.services.reservas_stock import reservado_por_producto, unidades_de_linea
from app.services.ventas import VentaService

logger = logging.getLogger(__name__)

# Cuanto tiempo aparta stock un pedido ENVIADO que nadie revisa. Un pedido APROBADO no vence: aparta hasta que
# se factura o se anula.
VIGENCIA_RESERVA_HORAS = 48

# Lo que el usuario "esta esperando" si el commit agota el LOCK_TIMEOUT (ver db_utils.confirmar_transaccion).
_ESPERA = "un registro (stock o pedido)"

_CONDICIONES = ("contado", "credito")
_TIPOS_VENTA = ("bulto", "unidad")
_ESTADOS = ("ENVIADO", "APROBADO", "RECHAZADO", "FACTURADO", "ANULADO", "VENCIDO")

# Lo que cabe en pedido_detalle.cantidad NUMERIC(12,2) y .precio_unitario NUMERIC(18,2).
_TOPE_CANTIDAD = Decimal(10) ** 10
_TOPE_PRECIO = Decimal(10) ** 16


def _a_decimal(valor, campo: str, tope: Decimal) -> Decimal:
    """`valor` como Decimal finito y menor que `tope` (lo que cabe en la columna). Un pedido llega de un celular:
    "NaN" y "Infinity" son Decimal validos que no se pueden guardar ni comparar, y "1e400" no cabe en NUMERIC."""
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Cada item requiere {campo} numerico") from exc
    if not numero.is_finite() or abs(numero) >= tope:
        raise ValueError(f"{campo} debe ser un numero menor a {tope:,}")
    return numero


def _normalizar_items(items: list[dict]) -> list[dict]:
    """Valida y normaliza las lineas: cantidad y precio como Decimal > 0, tipo_venta 'bulto' o 'unidad'
    (por defecto 'unidad', igual que una linea de factura sin tipo)."""
    if not items:
        raise ValueError("El pedido debe tener al menos un item")
    normalizados = []
    for item in items:
        if not item.get("id_producto"):
            raise ValueError("Cada item requiere id_producto")
        cantidad = _a_decimal(item.get("cantidad"), "cantidad", _TOPE_CANTIDAD)
        precio = _a_decimal(item.get("precio_unitario"), "precio_unitario", _TOPE_PRECIO)
        if cantidad <= 0:
            raise ValueError("Cada item requiere una cantidad mayor a cero")
        if precio <= 0:
            raise ValueError("Cada item requiere un precio_unitario mayor a cero")
        tipo_venta = item.get("tipo_venta") or "unidad"
        if tipo_venta not in _TIPOS_VENTA:
            raise ValueError("tipo_venta debe ser 'bulto' o 'unidad'")
        normalizados.append(
            {
                "id_producto": int(item["id_producto"]),
                "cantidad": cantidad,
                "precio_unitario": precio,
                "tipo_venta": tipo_venta,
                "descripcion": item.get("descripcion"),
            }
        )
    return normalizados


def _bloquear_producto(session: Session, id_producto: int) -> Inventario:
    """Lee el producto con UPDLOCK: dos pedidos que apartan el mismo producto a la vez se esperan en vez de leer
    el mismo disponible (mismo patron que la validacion de stock de emitir_factura)."""
    producto = session.execute(
        select(Inventario)
        .where(Inventario.id_producto == id_producto)
        .with_hint(Inventario, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if producto is None:
        raise ValueError(f"Producto {id_producto} no encontrado")
    if producto.estado_producto != "ACTIVO":
        raise ValueError(f"El producto '{producto.nombre_producto}' esta inactivo")
    return producto


def _bloquear_pedido(session: Session, id_pedido: int) -> Pedido:
    pedido = session.execute(
        select(Pedido)
        .where(Pedido.id_pedido == id_pedido)
        .with_hint(Pedido, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if pedido is None:
        raise ValueError("Pedido no encontrado")
    return pedido


def _unidades_por_producto(detalles: list) -> dict[int, Decimal]:
    """{id_producto: unidades de inventario que piden las lineas} (suma lineas repetidas del mismo producto)."""
    total: dict[int, Decimal] = {}
    for detalle in detalles:
        total[detalle.id_producto] = total.get(detalle.id_producto, Decimal("0")) + detalle.unidades_reservadas
    return total


class PedidoService:
    @staticmethod
    def crear_pedido(
        session: Session,
        id_usuario: int | None,
        id_cliente: int,
        items: list[dict],
        condicion_pago: str = "contado",
        observaciones: str | None = None,
        id_vendedor: int | None = None,
        id_cliente_local: str | None = None,
    ) -> Pedido:
        """Crea un pedido ENVIADO y aparta su stock en la misma transaccion.

        `items`: [{"id_producto", "cantidad", "precio_unitario", "tipo_venta": "bulto"|"unidad", "descripcion"?}].
        Un usuario vendedor siempre crea el pedido a su nombre (`id_vendedor` se ignora); caja/admin deben indicarlo.
        `id_cliente_local` es el identificador que genera la app movil: reenviar el mismo pedido devuelve el que
        ya existe en vez de duplicarlo (el envio se corto despues de llegar al servidor)."""
        require_permiso(session, id_usuario, "pedidos", "crear")
        aplicar_lock_timeout(session)

        propio = vendedor_propio(session, id_usuario)
        id_vendedor = propio if propio is not None else id_vendedor
        if id_vendedor is None:
            raise ValueError("El vendedor es obligatorio para crear un pedido")

        if id_cliente_local:
            existente = PedidoService._buscar_por_id_local(session, id_vendedor, id_cliente_local)
            if existente is not None:
                return existente

        vendedor = session.get(Vendedor, id_vendedor)
        if vendedor is None:
            raise ValueError("Vendedor no encontrado")
        if vendedor.estado_vendedor != "ACTIVO":
            raise ValueError(f"El vendedor '{vendedor.nombre_vendedor}' esta inactivo")

        cliente = session.get(Cliente, id_cliente)
        if cliente is None:
            raise ValueError("Cliente no encontrado")
        if cliente.estado_cliente != "ACTIVO":
            raise ValueError(f"El cliente '{cliente.nombre_razon_social}' esta inactivo")
        if propio is not None and cliente.vendedor_cliente != propio:
            raise PermisoDenegadoError("Ese cliente no esta asignado a tu usuario: solo puedes pedir para los tuyos.")

        if condicion_pago not in _CONDICIONES:
            raise ValueError("condicion_pago debe ser 'contado' o 'credito'")
        if condicion_pago == "credito" and not (cliente.dias_credito or 0) > 0:
            raise ValueError(
                f"El cliente '{cliente.nombre_razon_social}' no tiene credito: el pedido debe ser de contado"
            )
        if observaciones is not None and len(observaciones) > 255:
            raise ValueError("observaciones no puede superar 255 caracteres")
        if id_cliente_local is not None and len(id_cliente_local) > 64:
            raise ValueError("id_cliente_local no puede superar 64 caracteres")

        lineas = _normalizar_items(items)

        # Productos en orden de id: dos pedidos concurrentes que comparten productos y los cargaron en distinto
        # orden tomarian los locks cruzados y SQL Server abortaria uno por deadlock.
        pedido_por_producto: dict[int, Decimal] = {}
        productos: dict[int, Inventario] = {}
        for id_producto in sorted({linea["id_producto"] for linea in lineas}):
            productos[id_producto] = _bloquear_producto(session, id_producto)
        for linea in lineas:
            producto = productos[linea["id_producto"]]
            # El trigger de factura_detalle descuenta `cantidad * cantidad_caja` por un bulto: sin cajas
            # configuradas descontaria 0 y el pedido apartaria unidades que la factura nunca bajaria.
            if linea["tipo_venta"] == "bulto" and not producto.cantidad_caja:
                raise ValueError(
                    f"'{producto.nombre_producto}' no tiene unidades por caja configuradas: no se puede pedir por bulto"
                )
            linea["unidades"] = unidades_de_linea(linea["cantidad"], linea["tipo_venta"], producto.cantidad_caja)
            pedido_por_producto[producto.id_producto] = (
                pedido_por_producto.get(producto.id_producto, Decimal("0")) + linea["unidades"]
            )

        # Una sola consulta, con las filas de inventario ya bloqueadas (ver reservas_stock).
        reservado = reservado_por_producto(session, productos)
        for id_producto, requeridas in pedido_por_producto.items():
            producto = productos[id_producto]
            disponible = (producto.cantidad_unidad or Decimal("0")) - reservado[id_producto]
            if requeridas > disponible:
                apartadas = reservado[id_producto]
                raise ValueError(
                    f"Stock insuficiente para '{producto.nombre_producto}': disponible {disponible} unidades "
                    f"({apartadas} apartadas por otros pedidos), solicitado {requeridas} unidades"
                )
            # Misma regla que emitir_factura: la venta no puede dejar el stock bajo el minimo configurado. Se
            # exige ya aqui para no aprobar un pedido que luego no se podria facturar.
            saldo = disponible - requeridas
            if saldo < (producto.cantidad_minima or 0):
                raise ValueError(
                    f"El pedido dejaría el stock de '{producto.nombre_producto}' en {saldo} unidades, "
                    f"por debajo del mínimo configurado ({producto.cantidad_minima})"
                )

        pedido = Pedido(
            id_cliente=id_cliente,
            id_vendedor=id_vendedor,
            condicion_pago=condicion_pago,
            estado="ENVIADO",
            observaciones=observaciones,
            id_cliente_local=id_cliente_local or None,
            id_usuario_creador=id_usuario,
            # La hora del servidor SQL, la misma con la que reservas_stock decide si la reserva ya vencio.
            fecha_vencimiento_reserva=func.dateadd(literal_column("HOUR"), VIGENCIA_RESERVA_HORAS, func.getdate()),
        )
        try:
            session.add(pedido)
            session.flush()  # aqui es donde el indice unico de id_cliente_local rechaza un envio repetido
            for linea in lineas:
                session.add(
                    PedidoDetalle(
                        id_pedido=pedido.id_pedido,
                        id_producto=linea["id_producto"],
                        descripcion=linea["descripcion"],
                        cantidad=linea["cantidad"],
                        tipo_venta=linea["tipo_venta"],
                        unidades_reservadas=linea["unidades"],
                        precio_unitario=linea["precio_unitario"],
                    )
                )
            confirmar_transaccion(session, _ESPERA)
        except (ValueError, IntegrityError) as exc:
            session.rollback()
            # Dos envios simultaneos del mismo id_cliente_local: el indice unico deja pasar solo uno y el otro
            # recibe el pedido ya creado, no un error.
            if id_cliente_local:
                existente = PedidoService._buscar_por_id_local(session, id_vendedor, id_cliente_local)
                if existente is not None:
                    return existente
            if isinstance(exc, IntegrityError):
                raise ValueError(traducir_error_trigger(exc)) from exc
            raise
        session.refresh(pedido)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="CREAR_PEDIDO",
            modulo="PEDIDOS",
            detalle={
                "id_pedido": pedido.id_pedido,
                "numero_pedido": pedido.numero_pedido,
                "id_cliente": id_cliente,
                "id_vendedor": id_vendedor,
                "lineas": len(lineas),
            },
        )
        logger.info("Pedido %s creado por usuario %s (vendedor %s)", pedido.numero_pedido, id_usuario, id_vendedor)
        return pedido

    @staticmethod
    def _buscar_por_id_local(session: Session, id_vendedor: int, id_cliente_local: str) -> Pedido | None:
        return (
            session.execute(
                select(Pedido)
                .options(joinedload(Pedido.detalles))
                .where(Pedido.id_vendedor == id_vendedor, Pedido.id_cliente_local == id_cliente_local)
            )
            .unique()
            .scalar_one_or_none()
        )

    @staticmethod
    def listar_pedidos(
        session: Session,
        id_usuario: int | None,
        estado: str | None = None,
        id_cliente: int | None = None,
        id_vendedor: int | None = None,
        pagina: int = 1,
        por_pagina: int = 20,
    ) -> dict:
        """Pedidos paginados, los mas recientes primero. Un vendedor solo ve los suyos aunque pida otro."""
        require_permiso(session, id_usuario, "pedidos", "ver")
        if estado is not None and estado not in _ESTADOS:
            raise ValueError(f"estado debe ser uno de {', '.join(_ESTADOS)}")

        propio = vendedor_propio(session, id_usuario)
        id_vendedor = propio if propio is not None else id_vendedor

        # selectinload (no joinedload) para las lineas: con una coleccion unida el LIMIT de la pagina contaria filas
        # de lineas y no pedidos. Se cargan para que `Pedido.total` no haga una consulta por fila.
        consulta = session.query(Pedido).options(
            joinedload(Pedido.cliente), joinedload(Pedido.vendedor), selectinload(Pedido.detalles)
        )
        if estado is not None:
            consulta = consulta.filter(Pedido.estado == estado)
        if id_cliente is not None:
            consulta = consulta.filter(Pedido.id_cliente == id_cliente)
        if id_vendedor is not None:
            consulta = consulta.filter(Pedido.id_vendedor == id_vendedor)
        return paginar(consulta, pagina, por_pagina, Pedido.fecha_creacion.desc(), Pedido.id_pedido.desc())

    @staticmethod
    def obtener_pedido(session: Session, id_pedido: int, id_usuario: int | None) -> Pedido:
        """El pedido con sus lineas. Un vendedor solo puede ver los suyos."""
        require_permiso(session, id_usuario, "pedidos", "ver")
        pedido = (
            session.execute(
                select(Pedido)
                .options(joinedload(Pedido.detalles), joinedload(Pedido.cliente), joinedload(Pedido.vendedor))
                .where(Pedido.id_pedido == id_pedido)
            )
            .unique()
            .scalar_one_or_none()
        )
        if pedido is None:
            raise ValueError("Pedido no encontrado")
        propio = vendedor_propio(session, id_usuario)
        if propio is not None and pedido.id_vendedor != propio:
            raise PermisoDenegadoError("Ese pedido es de otro vendedor: tu usuario solo ve los suyos.")
        return pedido

    @staticmethod
    def detalle_pedido(session: Session, id_pedido: int, id_usuario: int | None) -> dict:
        """El pedido y sus lineas como datos simples (sin objetos ligados a la sesion): sirve para mostrarlo en un
        dialogo o para prellenar la factura sin que la pantalla dependa de que la sesion siga abierta."""
        pedido = PedidoService.obtener_pedido(session, id_pedido, id_usuario)
        ids = [d.id_producto for d in pedido.detalles]
        productos = {p.id_producto: p for p in session.query(Inventario).filter(Inventario.id_producto.in_(ids)).all()}
        lineas = []
        for d in pedido.detalles:
            producto = productos.get(d.id_producto)
            lineas.append(
                {
                    "id_producto": d.id_producto,
                    "codigo": producto.cod_producto if producto else "",
                    "nombre": producto.nombre_producto if producto else f"Producto {d.id_producto}",
                    "descripcion": d.descripcion,
                    "cantidad": d.cantidad,
                    "tipo_venta": d.tipo_venta,
                    "unidades": d.unidades_reservadas,
                    "precio_unitario": d.precio_unitario,
                    "subtotal": d.cantidad * d.precio_unitario,
                }
            )
        return {
            "id_pedido": pedido.id_pedido,
            "numero_pedido": pedido.numero_pedido,
            "estado": pedido.estado,
            "id_cliente": pedido.id_cliente,
            "cliente": pedido.cliente.nombre_razon_social if pedido.cliente else "",
            "id_vendedor": pedido.id_vendedor,
            "vendedor": pedido.vendedor.nombre_vendedor if pedido.vendedor else "",
            "condicion_pago": pedido.condicion_pago,
            "observaciones": pedido.observaciones,
            "motivo": pedido.motivo,
            "fecha_creacion": pedido.fecha_creacion,
            "fecha_vencimiento_reserva": pedido.fecha_vencimiento_reserva,
            "id_factura": pedido.id_factura,
            "total": pedido.total,
            "lineas": lineas,
        }

    @staticmethod
    def datos_para_facturar(session: Session, id_pedido: int, id_usuario: int | None) -> dict:
        """`detalle_pedido` de un pedido APROBADO, para prellenar el formulario de factura. Pide el mismo permiso que
        facturarlo (`pedidos:editar`): verlo no basta para convertirlo en factura."""
        require_permiso(session, id_usuario, "pedidos", "editar")
        datos = PedidoService.detalle_pedido(session, id_pedido, id_usuario)
        if datos["estado"] != "APROBADO":
            raise ValueError(f"El pedido {datos['numero_pedido']} esta {datos['estado']}: solo se factura uno APROBADO")
        return datos

    @staticmethod
    def aprobar_pedido(session: Session, id_pedido: int, id_usuario: int | None) -> Pedido:
        """ENVIADO (o VENCIDO) -> APROBADO. Vuelve a comprobar el stock: si el pedido vencio, su reserva se
        solto y otro pudo apartarlo. Desde aqui el pedido aparta stock sin vencer."""
        require_permiso(session, id_usuario, "pedidos", "editar")
        aplicar_lock_timeout(session)
        pedido = _bloquear_pedido(session, id_pedido)
        if pedido.estado not in ("ENVIADO", "VENCIDO"):
            raise ValueError(f"El pedido {pedido.numero_pedido} esta {pedido.estado}: no se puede aprobar")

        detalles = session.query(PedidoDetalle).filter(PedidoDetalle.id_pedido == id_pedido).all()
        requeridas_por_producto = _unidades_por_producto(detalles)
        # Todos los locks primero (en orden de id) y la reserva ajena en una sola consulta despues.
        productos = {
            id_producto: _bloquear_producto(session, id_producto) for id_producto in sorted(requeridas_por_producto)
        }
        reservado = reservado_por_producto(session, productos, excluir_pedido=id_pedido)
        for id_producto, requeridas in sorted(requeridas_por_producto.items()):
            producto = productos[id_producto]
            disponible = (producto.cantidad_unidad or Decimal("0")) - reservado[id_producto]
            if requeridas > disponible:
                raise ValueError(
                    f"Stock insuficiente para '{producto.nombre_producto}': disponible {disponible} unidades "
                    f"(sin contar este pedido), el pedido necesita {requeridas}"
                )

        pedido.estado = "APROBADO"
        pedido.fecha_vencimiento_reserva = None
        pedido.id_usuario_revisor = id_usuario
        pedido.fecha_revision = func.getdate()
        pedido.fecha_modificacion = func.getdate()
        confirmar_transaccion(session, _ESPERA)
        session.refresh(pedido)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="APROBAR_PEDIDO",
            modulo="PEDIDOS",
            detalle={"id_pedido": pedido.id_pedido, "numero_pedido": pedido.numero_pedido},
        )
        return pedido

    @staticmethod
    def rechazar_pedido(session: Session, id_pedido: int, motivo: str, id_usuario: int | None) -> Pedido:
        """ENVIADO (o VENCIDO) -> RECHAZADO, con motivo obligatorio (lo ve el vendedor)."""
        require_permiso(session, id_usuario, "pedidos", "editar")
        motivo = (motivo or "").strip()
        if not motivo:
            raise ValueError("El motivo del rechazo es obligatorio")
        if len(motivo) > 255:
            raise ValueError("El motivo no puede superar 255 caracteres")
        aplicar_lock_timeout(session)
        pedido = _bloquear_pedido(session, id_pedido)
        if pedido.estado not in ("ENVIADO", "VENCIDO"):
            raise ValueError(f"El pedido {pedido.numero_pedido} esta {pedido.estado}: no se puede rechazar")

        pedido.estado = "RECHAZADO"
        pedido.motivo = motivo
        pedido.fecha_vencimiento_reserva = None
        pedido.id_usuario_revisor = id_usuario
        pedido.fecha_revision = func.getdate()
        pedido.fecha_modificacion = func.getdate()
        confirmar_transaccion(session, _ESPERA)
        session.refresh(pedido)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="RECHAZAR_PEDIDO",
            modulo="PEDIDOS",
            detalle={"id_pedido": pedido.id_pedido, "numero_pedido": pedido.numero_pedido, "motivo": motivo},
        )
        return pedido

    @staticmethod
    def anular_pedido(session: Session, id_pedido: int, id_usuario: int | None, motivo: str | None = None) -> Pedido:
        """Libera la reserva. Quien revisa (`pedidos:editar`) anula un pedido ENVIADO, VENCIDO o APROBADO; un
        vendedor solo anula los suyos y solo mientras estan ENVIADOS o VENCIDOS (aprobado ya es un compromiso
        con caja)."""
        try:
            require_permiso(session, id_usuario, "pedidos", "editar")
            es_revisor = True
        except PermisoDenegadoError:
            require_permiso(session, id_usuario, "pedidos", "crear")
            es_revisor = False
        if motivo is not None and len(motivo) > 255:
            raise ValueError("El motivo no puede superar 255 caracteres")

        aplicar_lock_timeout(session)
        pedido = _bloquear_pedido(session, id_pedido)
        if not es_revisor:
            if pedido.id_vendedor != vendedor_propio(session, id_usuario):
                raise PermisoDenegadoError("Ese pedido es de otro vendedor: solo puedes anular los tuyos.")
            if pedido.estado not in ("ENVIADO", "VENCIDO"):
                raise PermisoDenegadoError(
                    f"El pedido {pedido.numero_pedido} esta {pedido.estado}: pide a caja que lo anule."
                )
        if pedido.estado not in ("ENVIADO", "APROBADO", "VENCIDO"):
            raise ValueError(f"El pedido {pedido.numero_pedido} esta {pedido.estado}: no se puede anular")

        pedido.estado = "ANULADO"
        if motivo:
            pedido.motivo = motivo
        pedido.fecha_vencimiento_reserva = None
        pedido.fecha_modificacion = func.getdate()
        confirmar_transaccion(session, _ESPERA)
        session.refresh(pedido)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="ANULAR_PEDIDO",
            modulo="PEDIDOS",
            detalle={"id_pedido": pedido.id_pedido, "numero_pedido": pedido.numero_pedido, "motivo": motivo},
        )
        return pedido

    @staticmethod
    def vencer_pendientes(session: Session) -> int:
        """Marca VENCIDO a los pedidos ENVIADOS cuya reserva ya paso. Solo cambia el estado visible: el stock
        ya se solto solo (la reserva se calcula con la hora del servidor). Lo corre una tarea del servidor, no un
        usuario; no pide permiso. Devuelve cuantos marco."""
        resultado = session.execute(
            update(Pedido)
            .where(Pedido.estado == "ENVIADO", Pedido.fecha_vencimiento_reserva <= func.getdate())
            .values(estado="VENCIDO", fecha_modificacion=func.getdate())
        )
        session.commit()
        return resultado.rowcount or 0

    @staticmethod
    def convertir_a_factura(session: Session, id_pedido: int, id_usuario: int | None, **opciones_factura):
        """Factura un pedido APROBADO con sus mismas lineas, cliente, vendedor y condicion de pago.

        `opciones_factura` se pasa tal cual a `VentaService.emitir_factura` (pagos de una factura de contado,
        descuento, dias de credito, porcentaje BCV...). La factura exige ademas `ventas:crear`. Si falla (precio
        por debajo de la lista, credito vencido, stock) el pedido sigue APROBADO."""
        require_permiso(session, id_usuario, "pedidos", "editar")
        pedido = (
            session.execute(select(Pedido).options(joinedload(Pedido.detalles)).where(Pedido.id_pedido == id_pedido))
            .unique()
            .scalar_one_or_none()
        )
        if pedido is None:
            raise ValueError("Pedido no encontrado")
        if pedido.estado != "APROBADO":
            raise ValueError(f"El pedido {pedido.numero_pedido} esta {pedido.estado}: solo se factura uno APROBADO")

        items = [
            {
                "id_producto": d.id_producto,
                "cantidad": d.cantidad,
                "precio_unitario": d.precio_unitario,
                "tipo_venta": d.tipo_venta,
                "descripcion": d.descripcion,
            }
            for d in pedido.detalles
        ]
        factura = VentaService.emitir_factura(
            session,
            id_cliente=pedido.id_cliente,
            id_usuario=id_usuario,
            id_vendedor=pedido.id_vendedor,
            condicion_pago=pedido.condicion_pago,
            items=items,
            observaciones=pedido.observaciones,
            id_pedido=id_pedido,
            **opciones_factura,
        )
        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="FACTURAR_PEDIDO",
            modulo="PEDIDOS",
            detalle={
                "id_pedido": id_pedido,
                "numero_pedido": pedido.numero_pedido,
                "id_factura": factura.id_factura,
            },
        )
        return factura
