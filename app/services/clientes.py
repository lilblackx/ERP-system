from sqlalchemy.orm import Session, joinedload

from app.db.models import Cliente
from app.services.auditoria import AuditoriaService


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


def list_clientes(session: Session, texto_busqueda: str | None = None) -> list[Cliente]:
    query = session.query(Cliente).options(
        joinedload(Cliente.vendedor), joinedload(Cliente.categoria)
    )
    if texto_busqueda:
        like = f"%{texto_busqueda}%"
        query = query.filter(
            Cliente.nombre_razon_social.ilike(like)
            | Cliente.identificacion_cliente.ilike(like)
            | Cliente.codigo_cliente.ilike(like)
        )
    return query.order_by(Cliente.nombre_razon_social).all()


def create_cliente(session: Session, **datos) -> Cliente:
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


def delete_cliente(session: Session, id_cliente: int, id_usuario: int | None = None) -> None:
    cliente = session.get(Cliente, id_cliente)
    if cliente is None:
        return
    detalle = {"id_cliente": cliente.id_cliente, "nombre_razon_social": cliente.nombre_razon_social}
    session.delete(cliente)
    session.commit()

    AuditoriaService.registrar_evento(
        session, id_usuario=id_usuario, accion="ELIMINAR_CLIENTE", modulo="CLIENTES", detalle=detalle
    )
