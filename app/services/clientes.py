from sqlalchemy.orm import Session, joinedload

from app.db.models import Cliente
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso

ESTADOS_VALIDOS = {"ACTIVO", "INACTIVO"}


def _validar_requeridos(datos: dict) -> None:
    if not datos.get("codigo_cliente"):
        raise ValueError("codigo_cliente es requerido")
    if not datos.get("id_legal"):
        raise ValueError("id_legal (tipo de identificación) es requerido")
    if not datos.get("identificacion_cliente"):
        raise ValueError("identificacion_cliente (número) es requerido")


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
    estado_cliente: str | None = None,
    id_vendedor: int | None = None,
    id_categoria: int | None = None,
    identificacion: str | None = None,
    pagina: int = 1,
    por_pagina: int = 20,
) -> dict:
    """D-01, mismo patron que ProductoService.buscar()/VentaService.listar_facturas():
    el catalogo de clientes puede crecer sin cota, asi que ClientesPanel (2026-08-27) lo
    pagina en vez de traer todo a memoria -- antes devolvia un list[Cliente] plano sin
    paginado real (`limite` solo capaba filas, no llevaba cuenta de pagina/total).
    Selectores tipo buscar-mientras-se-escribe (ej. app/ui/factura_form_dialog.py) piden
    `por_pagina=LIMITE_CATALOGO` y leen `resultado["items"]`, mismo patron que
    ProductoService.buscar()."""
    require_permiso(session, id_usuario, "clientes", "ver")
    query = session.query(Cliente).options(joinedload(Cliente.vendedor), joinedload(Cliente.categoria))
    if texto_busqueda:
        # Barra de busqueda unica del listado (ClientesPanel): matchea CUALQUIERA de los
        # datos que se muestran en pantalla -- nombre, identificacion, codigo, email o
        # telefono -- en vez de exigir que el usuario sepa en cual de dos cajas separadas
        # escribir. `identificacion` (abajo) se mantiene aparte para uso programatico/
        # selectores que si necesiten un filtro AND preciso solo por ese campo.
        like = f"%{texto_busqueda}%"
        query = query.filter(
            Cliente.nombre_razon_social.ilike(like)
            | Cliente.id_legal.ilike(like)
            | Cliente.codigo_cliente.ilike(like)
            | Cliente.identificacion_cliente.ilike(like)
            | Cliente.email.ilike(like)
            | Cliente.telefono.ilike(like)
        )
    if identificacion:
        like = f"%{identificacion}%"
        query = query.filter(Cliente.identificacion_cliente.ilike(like))
    if estado_cliente:
        query = query.filter(Cliente.estado_cliente == estado_cliente)
    if id_vendedor:
        query = query.filter(Cliente.vendedor_cliente == id_vendedor)
    if id_categoria:
        query = query.filter(Cliente.id_categoria_cliente == id_categoria)
    query = query.order_by(Cliente.nombre_razon_social)

    total = query.count()
    clientes = query.offset((pagina - 1) * por_pagina).limit(por_pagina).all()
    return {"items": clientes, "total": total, "pagina": pagina, "por_pagina": por_pagina}


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
    if "id_legal" in datos and not datos["id_legal"]:
        raise ValueError("id_legal (tipo de identificación) es requerido")
    if "identificacion_cliente" in datos and not datos["identificacion_cliente"]:
        raise ValueError("identificacion_cliente (número) es requerido")

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
