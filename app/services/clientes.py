from sqlalchemy.orm import Session, joinedload

from app.db.models import Cliente
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso

ESTADOS_VALIDOS = {"ACTIVO", "INACTIVO"}


def _validar_requeridos(datos: dict) -> None:
    if not datos.get("codigo_cliente"):
        raise ValueError("codigo_cliente es requerido")
    if not datos.get("identificacion_cliente"):
        raise ValueError("identificacion_cliente es requerido")


def _validar_unico(session: Session, campo: str, valor: str, excluir_id: int | None = None) -> None:
    query = session.query(Cliente).filter(getattr(Cliente, campo) == valor)
    if excluir_id is not None:
        query = query.filter(Cliente.id_cliente != excluir_id)
    if query.first() is not None:
        raise ValueError(f"Ya existe un cliente con {campo}='{valor}'")


def list_clientes(
    session: Session,
    texto_busqueda: str | None = None,
    id_usuario: int | None = None,
    limite: int | None = None,
) -> list[Cliente]:
    """limite: tope opcional de filas (D-01) -- pensado para selectores tipo
    buscar-mientras-se-escribe (ej. app/ui/factura_form_dialog.py) que no necesitan traer
    el catalogo completo a memoria en cada tecla. None preserva el comportamiento
    original (sin limite) para los callers que si necesitan el listado completo."""
    require_permiso(session, id_usuario, "clientes", "ver")
    query = session.query(Cliente).options(joinedload(Cliente.vendedor), joinedload(Cliente.categoria))
    if texto_busqueda:
        like = f"%{texto_busqueda}%"
        query = query.filter(
            Cliente.nombre_razon_social.ilike(like)
            | Cliente.identificacion_cliente.ilike(like)
            | Cliente.codigo_cliente.ilike(like)
        )
    query = query.order_by(Cliente.nombre_razon_social)
    if limite is not None:
        query = query.limit(limite)
    return query.all()


def create_cliente(session: Session, **datos) -> Cliente:
    require_permiso(session, datos.get("creado_por"), "clientes", "crear")
    _validar_requeridos(datos)
    _validar_unico(session, "codigo_cliente", datos["codigo_cliente"])
    _validar_unico(session, "identificacion_cliente", datos["identificacion_cliente"])
    cliente = Cliente(**datos)
    session.add(cliente)
    session.commit()
    session.refresh(cliente)

    AuditoriaService.registrar_evento(
        session,
        id_usuario=cliente.creado_por,
        accion="CREAR_CLIENTE",
        modulo="CLIENTES",
        detalle={"id_cliente": cliente.id_cliente, "nombre_razon_social": cliente.nombre_razon_social},
    )
    return cliente


def update_cliente(session: Session, id_cliente: int, id_usuario: int | None = None, **datos) -> Cliente:
    require_permiso(session, id_usuario, "clientes", "editar")
    cliente = session.get(Cliente, id_cliente)
    if cliente is None:
        raise ValueError("Cliente no encontrado")

    if "codigo_cliente" in datos and not datos["codigo_cliente"]:
        raise ValueError("codigo_cliente es requerido")
    if "identificacion_cliente" in datos and not datos["identificacion_cliente"]:
        raise ValueError("identificacion_cliente es requerido")

    nuevo_codigo = datos.get("codigo_cliente")
    if nuevo_codigo and nuevo_codigo != cliente.codigo_cliente:
        _validar_unico(session, "codigo_cliente", nuevo_codigo, excluir_id=id_cliente)

    nueva_identificacion = datos.get("identificacion_cliente")
    if nueva_identificacion and nueva_identificacion != cliente.identificacion_cliente:
        _validar_unico(session, "identificacion_cliente", nueva_identificacion, excluir_id=id_cliente)

    for campo, valor in datos.items():
        setattr(cliente, campo, valor)
    session.commit()
    session.refresh(cliente)

    AuditoriaService.registrar_evento(
        session,
        id_usuario=id_usuario,
        accion="ACTUALIZAR_CLIENTE",
        modulo="CLIENTES",
        detalle={"id_cliente": cliente.id_cliente, "campos": list(datos.keys())},
    )
    return cliente


# Un cliente nunca se borra fisicamente: FK_factura_venta_id_cliente_factura es
# ON DELETE NO ACTION, asi que borrar uno con facturas emitidas revienta con un
# IntegrityError crudo de pyodbc -- y aunque no tenga ninguna todavia, podria tenerlas
# despues, asi que la politica es no permitir el DELETE nunca. Usar
# cambiar_estado_cliente(..., "INACTIVO") para retirarlo de circulacion preservando el
# historial. Decision de producto 2026-08-22 (hallazgo de auditoria del mismo dia).
def delete_cliente(session: Session, id_cliente: int, id_usuario: int | None = None) -> None:
    require_permiso(session, id_usuario, "clientes", "eliminar")
    raise ValueError(
        "No se puede eliminar un cliente para proteger la integridad de los datos. "
        "Use cambiar_estado_cliente() para desactivarlo."
    )


def cambiar_estado_cliente(
    session: Session, id_cliente: int, nuevo_estado: str, id_usuario: int | None = None
) -> Cliente:
    require_permiso(session, id_usuario, "clientes", "eliminar")
    if nuevo_estado not in ESTADOS_VALIDOS:
        raise ValueError(f"nuevo_estado debe ser uno de {ESTADOS_VALIDOS}")
    cliente = session.get(Cliente, id_cliente)
    if cliente is None:
        raise ValueError("Cliente no encontrado")

    cliente.estado_cliente = nuevo_estado
    session.commit()
    session.refresh(cliente)

    AuditoriaService.registrar_evento(
        session,
        id_usuario=id_usuario,
        accion="CAMBIAR_ESTADO_CLIENTE",
        modulo="CLIENTES",
        detalle={"id_cliente": cliente.id_cliente, "nuevo_estado": nuevo_estado},
    )
    return cliente
