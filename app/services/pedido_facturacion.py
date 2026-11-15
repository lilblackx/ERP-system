"""Los dos pasos de `VentaService.emitir_factura(id_pedido=...)` que tocan el pedido (migrations/0100).

Viven aparte de `pedidos.py` (que importa a `ventas.py` para convertir un pedido en factura) para que la factura
pueda cerrar el pedido en SU misma transaccion sin un import circular: o quedan las dos filas (la factura y el
pedido FACTURADO), o ninguna.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Pedido


def bloquear_pedido_a_facturar(session: Session, id_pedido: int, id_cliente: int, id_vendedor: int) -> Pedido:
    """Lee el pedido con UPDLOCK y comprueba que se puede facturar: dos cajeros que lo convierten a la vez no
    pueden emitir dos facturas (el segundo espera el commit del primero y lo encuentra ya FACTURADO).
    `populate_existing` evita usar una copia vieja del pedido que la sesion ya tuviera en memoria.

    Cliente y vendedor de la factura deben ser los del pedido: la comision es del vendedor que tomo el pedido, y
    una factura a nombre de otro se la llevaria sin que el pedido lo diga."""
    pedido = session.execute(
        select(Pedido)
        .where(Pedido.id_pedido == id_pedido)
        .with_hint(Pedido, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if pedido is None:
        raise ValueError("Pedido no encontrado")
    if pedido.estado != "APROBADO":
        raise ValueError(f"El pedido {pedido.numero_pedido} esta {pedido.estado}: solo se factura uno APROBADO")
    if pedido.id_cliente != id_cliente:
        raise ValueError(f"El pedido {pedido.numero_pedido} es de otro cliente")
    if pedido.id_vendedor != id_vendedor:
        raise ValueError(f"El pedido {pedido.numero_pedido} es de otro vendedor")
    return pedido


def marcar_pedido_facturado(pedido: Pedido, id_factura: int, id_usuario: int | None) -> None:
    """Cierra el pedido: FACTURADO, enlazado a su factura y sin reserva que vencer."""
    pedido.estado = "FACTURADO"
    pedido.id_factura = id_factura
    pedido.fecha_vencimiento_reserva = None
    pedido.id_usuario_revisor = pedido.id_usuario_revisor or id_usuario
    pedido.fecha_modificacion = func.getdate()
