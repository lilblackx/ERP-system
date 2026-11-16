"""Stock apartado por pedidos de venta (migrations/0100).

`inventario.cantidad_unidad` es el stock REAL y solo lo mueven los triggers de factura_detalle. Un pedido
no lo toca: aparta unidades, y lo disponible es `cantidad_unidad - reservado`. Este modulo vive aparte de
`pedidos.py` porque `ventas.py` lo necesita (la factura no puede vender lo que otro pedido tiene apartado) y
`pedidos.py` importa a `ventas.py` para convertir un pedido en factura.

Que aparta stock:
  * APROBADO: hasta que se factura o se anula.
  * ENVIADO : solo hasta `fecha_vencimiento_reserva`.
La hora es la del servidor SQL (`GETDATE()`), no la de la PC: todas las estaciones comparten un solo reloj.
Este predicado vive SOLO aqui (`_aparta_stock`): no hay una vista SQL que lo repita.

Quien decide algo con estos numeros (crear, aprobar o facturar) debe haber bloqueado ANTES las filas de
inventario con UPDLOCK: crear un pedido exige ese mismo lock, y leer la reserva sin tenerlo dejaria colar otra
reserva entre la lectura y la decision.
"""

from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Pedido, PedidoDetalle

ESTADOS_ABIERTOS = ("ENVIADO", "APROBADO")


def _aparta_stock():
    return or_(
        Pedido.estado == "APROBADO",
        and_(Pedido.estado == "ENVIADO", Pedido.fecha_vencimiento_reserva > func.getdate()),
    )


def unidades_de_linea(cantidad: Decimal, tipo_venta: str, unidades_por_caja: Decimal | None) -> Decimal:
    """Unidades de inventario que representa una linea: un bulto son `cantidad_caja` unidades (1 si el producto
    no tiene caja configurada, igual que el chequeo de stock de emitir_factura); una venta por unidad, la
    cantidad."""
    if tipo_venta == "bulto":
        return Decimal(str(cantidad)) * Decimal(str(unidades_por_caja or 1))
    return Decimal(str(cantidad))


def anotar_reservado(session: Session, productos: list, excluir_pedido: int | None = None) -> None:
    """Deja en cada producto (`Inventario`) la cantidad apartada por pedidos como `cantidad_reservada`, un atributo
    suelto (no es una columna) para que las pantallas muestren y validen contra el stock DISPONIBLE. Una consulta
    para toda la lista. No bloquea nada: es para mostrar; quien factura vuelve a validar con locks."""
    reservado = reservado_por_producto(session, [p.id_producto for p in productos], excluir_pedido)
    for producto in productos:
        producto.cantidad_reservada = reservado[producto.id_producto]


def reservado_por_producto(
    session: Session, ids_producto: Iterable[int], excluir_pedido: int | None = None
) -> dict[int, Decimal]:
    """{id_producto: unidades apartadas por pedidos vigentes} en UNA sola consulta (0 para un producto sin reserva).
    `excluir_pedido` no se cuenta: el pedido que se esta aprobando o facturando no debe bloquearse a si mismo."""
    ids = list(ids_producto)
    reservado = {id_producto: Decimal("0") for id_producto in ids}
    if not ids:
        return reservado
    consulta = (
        select(PedidoDetalle.id_producto, func.sum(PedidoDetalle.unidades_reservadas))
        .join(Pedido, Pedido.id_pedido == PedidoDetalle.id_pedido)
        .where(PedidoDetalle.id_producto.in_(ids), _aparta_stock())
        .group_by(PedidoDetalle.id_producto)
    )
    if excluir_pedido is not None:
        consulta = consulta.where(Pedido.id_pedido != excluir_pedido)
    for id_producto, total in session.execute(consulta):
        reservado[id_producto] = Decimal(str(total))
    return reservado
