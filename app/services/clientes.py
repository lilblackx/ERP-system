from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.db.models import Cliente, Vendedor
from app.services.auditoria import AuditoriaService
from app.services.busqueda_sql import contiene
from app.services.busqueda_sql import escapar_like as _escapar_like
from app.services.paginacion import paginar
from app.services.permisos import require_permiso

ESTADOS_VALIDOS = {"ACTIVO", "INACTIVO"}


def _validar_requeridos(datos: dict) -> None:
    if not datos.get("id_legal"):
        raise ValueError("id_legal (tipo de identificación) es requerido")
    if not datos.get("identificacion_cliente"):
        raise ValueError("identificacion_cliente (número) es requerido")
    # is None (no falsy) a proposito: latitud/longitud=0.0 son coordenadas legitimas
    # (ecuador / meridiano de Greenwich) y `not 0.0` es True en Python -- un `not
    # datos.get(...)` como el resto de los checks de arriba las rechazaria por error.
    if datos.get("latitud") is None:
        raise ValueError("latitud es requerida")
    if datos.get("longitud") is None:
        raise ValueError("longitud es requerida")


def _validar_unico(session: Session, campo: str, valor: str, excluir_id: int | None = None) -> None:
    query = session.query(Cliente).filter(getattr(Cliente, campo) == valor)
    if excluir_id is not None:
        query = query.filter(Cliente.id_cliente != excluir_id)
    if query.first() is not None:
        raise ValueError(f"Ya existe un cliente con {campo}='{valor}'")


def _validar_rango_coordenadas(latitud, longitud) -> None:
    """Solo el rango -- la obligatoriedad se valida aparte en cada callsite (mismo
    criterio 'no permite vaciar' que codigo_cliente/identificacion_cliente): en creacion
    via _validar_requeridos(), en edicion inline en update_cliente()."""
    if latitud is not None:
        try:
            latitud_valor = float(latitud)
        except (TypeError, ValueError) as e:
            raise ValueError("latitud debe ser un número válido") from e
        if not (-90 <= latitud_valor <= 90):
            raise ValueError("latitud debe estar entre -90 y 90")
    if longitud is not None:
        try:
            longitud_valor = float(longitud)
        except (TypeError, ValueError) as e:
            raise ValueError("longitud debe ser un número válido") from e
        if not (-180 <= longitud_valor <= 180):
            raise ValueError("longitud debe estar entre -180 y 180")


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
        like = f"%{_escapar_like(texto_busqueda)}%"
        query = query.filter(
            or_(
                *(
                    contiene(session, columna, like)
                    for columna in (
                        Cliente.nombre_razon_social,
                        Cliente.id_legal,
                        Cliente.codigo_cliente,
                        Cliente.identificacion_cliente,
                        Cliente.email,
                        Cliente.telefono,
                    )
                )
            )
        )
    if identificacion:
        like = f"%{_escapar_like(identificacion)}%"
        query = query.filter(contiene(session, Cliente.identificacion_cliente, like))
    if estado_cliente:
        query = query.filter(Cliente.estado_cliente == estado_cliente)
    if id_vendedor:
        query = query.filter(Cliente.vendedor_cliente == id_vendedor)
    if id_categoria:
        query = query.filter(Cliente.id_categoria_cliente == id_categoria)
    return paginar(query, pagina, por_pagina, Cliente.nombre_razon_social, Cliente.id_cliente)


def create_cliente(session: Session, **datos) -> Cliente:
    require_permiso(session, datos.get("creado_por"), "clientes", "crear")
    _validar_requeridos(datos)

    # codigo_cliente es autoincremental en SQL (DEFAULT = NEXT VALUE FOR
    # dbo.seq_codigo_cliente, migrations/0093): lo normal es NO mandarlo y que el motor lo
    # asigne de forma atomica entre estaciones (la UI nunca lo manda). Un codigo explicito
    # se sigue aceptando -- importaciones de datos, tests -- y gana sobre el DEFAULT. Un ""
    # explicito es un intento de guardar vacio y se rechaza, mismo criterio "no permite
    # vaciar" que update_cliente().
    if datos.get("codigo_cliente") == "":
        raise ValueError("codigo_cliente es requerido")
    if datos.get("codigo_cliente") is None:
        datos.pop("codigo_cliente", None)  # omitido del INSERT -> lo llena el DEFAULT

    # Validate uniqueness for both identificacion_cliente and codigo_cliente
    _validar_unico(session, "identificacion_cliente", datos["identificacion_cliente"])
    if "codigo_cliente" in datos:
        _validar_unico(session, "codigo_cliente", datos["codigo_cliente"])

    _validar_rango_coordenadas(datos.get("latitud"), datos.get("longitud"))

    cliente = Cliente(**datos)
    session.add(cliente)
    try:
        session.commit()
    except IntegrityError as e:
        session.rollback()
        # Normalize DB unique constraint failures into ValueError for caller/tests
        # Prefer a descriptive message; tests usually only check exception type.
        raise ValueError("Error al crear cliente: código o identificación duplicado") from e

    session.refresh(cliente)  # trae el codigo_cliente asignado por la secuencia

    AuditoriaService.registrar_evento(
        session,
        id_usuario=cliente.creado_por,
        accion="CREAR_CLIENTE",
        modulo="CLIENTES",
        detalle={
            "id_cliente": cliente.id_cliente,
            "nombre_razon_social": cliente.nombre_razon_social,
        },
    )
    return cliente


def update_cliente(session: Session, id_cliente: int, id_usuario: int | None = None, **datos) -> Cliente:
    require_permiso(session, id_usuario, "clientes", "editar")
    cliente = session.get(Cliente, id_cliente)
    if cliente is None:
        raise ValueError("Cliente no encontrado")

    # codigo_cliente es de solo lectura una vez creado: lo asigna SQL y no se reasigna. Mandar
    # el mismo valor que ya tiene (ej. un formulario que reenvia todos sus campos) es inocuo.
    if "codigo_cliente" in datos:
        if not datos["codigo_cliente"]:
            raise ValueError("codigo_cliente es requerido")
        if datos["codigo_cliente"] != cliente.codigo_cliente:
            raise ValueError("codigo_cliente es de solo lectura: lo asigna el sistema y no se puede modificar")
    if "id_legal" in datos and not datos["id_legal"]:
        raise ValueError("id_legal (tipo de identificación) es requerido")
    if "identificacion_cliente" in datos and not datos["identificacion_cliente"]:
        raise ValueError("identificacion_cliente (número) es requerido")
    if "latitud" in datos and datos["latitud"] is None:
        raise ValueError("latitud es requerida")
    if "longitud" in datos and datos["longitud"] is None:
        raise ValueError("longitud es requerida")

    nueva_identificacion = datos.get("identificacion_cliente")
    if nueva_identificacion and nueva_identificacion != cliente.identificacion_cliente:
        _validar_unico(
            session,
            "identificacion_cliente",
            nueva_identificacion,
            excluir_id=id_cliente,
        )

    nueva_latitud = datos["latitud"] if "latitud" in datos else cliente.latitud
    nueva_longitud = datos["longitud"] if "longitud" in datos else cliente.longitud
    _validar_rango_coordenadas(nueva_latitud, nueva_longitud)

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


def listar_clientes_por_ruta(session: Session, id_ruta: int, id_usuario: int | None = None) -> list[Cliente]:
    """Clientes geolocalizados cuyo vendedor pertenece a la ruta dada -- para pintarlos
    junto al punto de la ruta en el mapa general (app/ui/mapa_rutas_panel.py). El vinculo
    es indirecto (Cliente -> Vendedor -> Ruta): un cliente no se asigna a una ruta
    directamente, hereda la del vendedor que lo atiende."""
    require_permiso(session, id_usuario, "clientes", "ver")
    return (
        session.query(Cliente)
        .join(Vendedor, Cliente.vendedor_cliente == Vendedor.id_vendedor)
        .filter(
            Vendedor.id_ruta == id_ruta,
            Cliente.latitud.isnot(None),
            Cliente.longitud.isnot(None),
        )
        .order_by(Cliente.nombre_razon_social)
        .all()
    )
