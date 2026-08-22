from sqlalchemy.orm import Session

from app.db.models import Permiso, Rol, RolPermiso, Usuario
from app.services.auditoria import AuditoriaService

# El catalogo de permisos (recurso + accion) se mantiene fijo via schema/seed, no se
# gestiona desde aqui. Este servicio solo administra roles y la matriz rol_permisos.


class PermisoDenegadoError(PermissionError):
    """Se lanza cuando un usuario no tiene el permiso requerido para una operacion.
    Subclase de PermissionError (no ValueError) a proposito: es un tipo de falla
    distinto a un dato invalido, y los llamadores pueden distinguirlos."""


def require_permiso(session: Session, id_usuario: int | None, recurso: str, accion: str) -> None:
    """Punto de entrada de autorizacion para el resto de los servicios.

    id_usuario=None (actor desconocido) se trata como NO autorizado -- no como "confiar
    por defecto". El rol 'ADMIN' bypassa la matriz de permisos por completo
    (superusuario): el seed de schema_sqlserver.sql no le asigna ninguna fila en
    rol_permisos a proposito, así que sin este bypass ADMIN quedaria bloqueado de todo.

    La consulta contra rol_permisos esta duplicada aqui en vez de reusar
    UsuarioService.verificar_permiso() (misma logica, app/services/usuarios.py) a
    proposito: usuarios.py necesita importar require_permiso() para proteger sus propios
    metodos de escritura, e importar UsuarioService desde aca crearia un ciclo.
    """
    if id_usuario is None:
        raise PermisoDenegadoError(
            f"Accion no autorizada: '{accion}' sobre '{recurso}' requiere un usuario autenticado"
        )

    usuario = session.get(Usuario, id_usuario)
    if usuario is None:
        raise PermisoDenegadoError(f"Accion no autorizada: usuario {id_usuario} no encontrado")

    if usuario.id_rol is None:
        raise PermisoDenegadoError(f"El usuario '{usuario.nombre_usuario}' no tiene rol asignado")

    rol = session.get(Rol, usuario.id_rol)
    if rol is not None and rol.nombre == "ADMIN":
        return

    tiene_permiso = (
        session.query(RolPermiso)
        .join(Permiso, Permiso.id_permiso == RolPermiso.id_permiso)
        .filter(RolPermiso.id_rol == usuario.id_rol, Permiso.recurso == recurso, Permiso.accion == accion)
        .first()
        is not None
    )
    if not tiene_permiso:
        raise PermisoDenegadoError(
            f"El usuario '{usuario.nombre_usuario}' no tiene permiso '{accion}' sobre '{recurso}'"
        )


class RolService:
    @staticmethod
    def listar_roles(session: Session, id_usuario: int | None = None) -> list[Rol]:
        require_permiso(session, id_usuario, "permisos", "ver")
        return session.query(Rol).order_by(Rol.nombre).all()

    @staticmethod
    def obtener_rol(session: Session, id_rol: int, id_usuario: int | None = None) -> Rol | None:
        require_permiso(session, id_usuario, "permisos", "ver")
        return session.get(Rol, id_rol)

    @staticmethod
    def _validar_nombre_unico(session: Session, nombre: str, excluir_id: int | None = None) -> None:
        query = session.query(Rol).filter(Rol.nombre == nombre)
        if excluir_id is not None:
            query = query.filter(Rol.id_rol != excluir_id)
        if query.first() is not None:
            raise ValueError(f"Ya existe un rol con nombre '{nombre}'")

    @staticmethod
    def crear_rol(session: Session, nombre: str, descripcion: str | None = None, id_usuario: int | None = None) -> Rol:
        require_permiso(session, id_usuario, "permisos", "crear")
        if not nombre:
            raise ValueError("nombre es requerido")
        RolService._validar_nombre_unico(session, nombre)

        rol = Rol(nombre=nombre, descripcion=descripcion)
        session.add(rol)
        session.commit()
        session.refresh(rol)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="CREAR_ROL",
            modulo="PERMISOS",
            detalle={"id_rol": rol.id_rol, "nombre": rol.nombre},
        )
        return rol

    @staticmethod
    def actualizar_rol(session: Session, id_rol: int, id_usuario: int | None = None, **datos) -> Rol:
        require_permiso(session, id_usuario, "permisos", "editar")
        rol = session.get(Rol, id_rol)
        if rol is None:
            raise ValueError("Rol no encontrado")

        nuevo_nombre = datos.get("nombre")
        if "nombre" in datos and not nuevo_nombre:
            raise ValueError("nombre es requerido")
        if nuevo_nombre and nuevo_nombre != rol.nombre:
            RolService._validar_nombre_unico(session, nuevo_nombre, excluir_id=id_rol)

        for campo, valor in datos.items():
            setattr(rol, campo, valor)
        session.commit()
        session.refresh(rol)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="ACTUALIZAR_ROL",
            modulo="PERMISOS",
            detalle={"id_rol": rol.id_rol, "campos": list(datos.keys())},
        )
        return rol

    @staticmethod
    def eliminar_rol(session: Session, id_rol: int, id_usuario: int | None = None) -> None:
        require_permiso(session, id_usuario, "permisos", "eliminar")
        rol = session.get(Rol, id_rol)
        if rol is None:
            return

        usuarios_con_rol = session.query(Usuario).filter(Usuario.id_rol == id_rol).count()
        if usuarios_con_rol > 0:
            # FK_usuarios_id_rol es ON DELETE SET NULL: sin este check, borrar el rol
            # no fallaria mudo dejaria a esos usuarios sin rol (y sin permisos).
            raise ValueError(f"No se puede eliminar: hay {usuarios_con_rol} usuario(s) con este rol")

        detalle = {"id_rol": rol.id_rol, "nombre": rol.nombre}
        session.delete(rol)
        session.commit()

        AuditoriaService.registrar_evento(
            session, id_usuario=id_usuario, accion="ELIMINAR_ROL", modulo="PERMISOS", detalle=detalle
        )


class PermisoService:
    @staticmethod
    def listar_permisos(
        session: Session, recurso: str | None = None, id_usuario: int | None = None
    ) -> list[Permiso]:
        require_permiso(session, id_usuario, "permisos", "ver")
        query = session.query(Permiso)
        if recurso:
            query = query.filter(Permiso.recurso == recurso)
        return query.order_by(Permiso.recurso, Permiso.accion).all()

    @staticmethod
    def obtener_matriz_rol(session: Session, id_rol: int, id_usuario: int | None = None) -> list[dict]:
        """Catalogo completo de permisos con un flag 'asignado' por cada uno, listo para
        pintar un checkbox-grid en la UI (una fila por permiso, marcado si el rol lo tiene)."""
        require_permiso(session, id_usuario, "permisos", "ver")
        if session.get(Rol, id_rol) is None:
            raise ValueError("Rol no encontrado")

        asignados = {
            id_permiso
            for (id_permiso,) in session.query(RolPermiso.id_permiso).filter(RolPermiso.id_rol == id_rol).all()
        }
        permisos = PermisoService.listar_permisos(session, id_usuario=id_usuario)
        return [
            {
                "id_permiso": permiso.id_permiso,
                "recurso": permiso.recurso,
                "accion": permiso.accion,
                "descripcion": permiso.descripcion,
                "asignado": permiso.id_permiso in asignados,
            }
            for permiso in permisos
        ]

    @staticmethod
    def asignar_permiso(session: Session, id_rol: int, id_permiso: int, id_usuario: int | None = None) -> RolPermiso:
        require_permiso(session, id_usuario, "permisos", "editar")
        if session.get(Rol, id_rol) is None:
            raise ValueError("Rol no encontrado")
        if session.get(Permiso, id_permiso) is None:
            raise ValueError("Permiso no encontrado")

        existente = session.get(RolPermiso, (id_rol, id_permiso))
        if existente is not None:
            return existente

        rol_permiso = RolPermiso(id_rol=id_rol, id_permiso=id_permiso)
        session.add(rol_permiso)
        session.commit()

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="ASIGNAR_PERMISO",
            modulo="PERMISOS",
            detalle={"id_rol": id_rol, "id_permiso": id_permiso},
        )
        return rol_permiso

    @staticmethod
    def revocar_permiso(session: Session, id_rol: int, id_permiso: int, id_usuario: int | None = None) -> None:
        require_permiso(session, id_usuario, "permisos", "editar")
        rol_permiso = session.get(RolPermiso, (id_rol, id_permiso))
        if rol_permiso is None:
            return

        session.delete(rol_permiso)
        session.commit()

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="REVOCAR_PERMISO",
            modulo="PERMISOS",
            detalle={"id_rol": id_rol, "id_permiso": id_permiso},
        )

    @staticmethod
    def establecer_permisos_rol(
        session: Session, id_rol: int, ids_permisos: list[int], id_usuario: int | None = None
    ) -> list[RolPermiso]:
        """Reemplaza de una vez el conjunto completo de permisos de un rol: pensado para
        guardar un checkbox-grid completo en una sola llamada en vez de un
        asignar/revocar por casilla."""
        require_permiso(session, id_usuario, "permisos", "editar")
        if session.get(Rol, id_rol) is None:
            raise ValueError("Rol no encontrado")

        ids_deseados = set(ids_permisos)
        if ids_deseados:
            encontrados = {
                id_permiso for (id_permiso,) in session.query(Permiso.id_permiso).filter(Permiso.id_permiso.in_(ids_deseados)).all()
            }
            faltantes = ids_deseados - encontrados
            if faltantes:
                raise ValueError(f"Permiso(s) no encontrado(s): {sorted(faltantes)}")

        actuales = {
            id_permiso
            for (id_permiso,) in session.query(RolPermiso.id_permiso).filter(RolPermiso.id_rol == id_rol).all()
        }

        a_quitar = actuales - ids_deseados
        a_agregar = ids_deseados - actuales

        if a_quitar:
            session.query(RolPermiso).filter(
                RolPermiso.id_rol == id_rol, RolPermiso.id_permiso.in_(a_quitar)
            ).delete(synchronize_session=False)
        for id_permiso in a_agregar:
            session.add(RolPermiso(id_rol=id_rol, id_permiso=id_permiso))

        session.commit()

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="ACTUALIZAR_MATRIZ_PERMISOS",
            modulo="PERMISOS",
            detalle={"id_rol": id_rol, "agregados": sorted(a_agregar), "quitados": sorted(a_quitar)},
        )
        return session.query(RolPermiso).filter(RolPermiso.id_rol == id_rol).all()
