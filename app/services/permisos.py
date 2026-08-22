from sqlalchemy.orm import Session

from app.db.models import Permiso, Rol, RolPermiso, Usuario
from app.services.auditoria import AuditoriaService

# El catalogo de permisos (recurso + accion) se mantiene fijo via schema/seed, no se
# gestiona desde aqui. Este servicio solo administra roles y la matriz rol_permisos.


class RolService:
    @staticmethod
    def listar_roles(session: Session) -> list[Rol]:
        return session.query(Rol).order_by(Rol.nombre).all()

    @staticmethod
    def obtener_rol(session: Session, id_rol: int) -> Rol | None:
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
    def listar_permisos(session: Session, recurso: str | None = None) -> list[Permiso]:
        query = session.query(Permiso)
        if recurso:
            query = query.filter(Permiso.recurso == recurso)
        return query.order_by(Permiso.recurso, Permiso.accion).all()

    @staticmethod
    def obtener_matriz_rol(session: Session, id_rol: int) -> list[dict]:
        """Catalogo completo de permisos con un flag 'asignado' por cada uno, listo para
        pintar un checkbox-grid en la UI (una fila por permiso, marcado si el rol lo tiene)."""
        if session.get(Rol, id_rol) is None:
            raise ValueError("Rol no encontrado")

        asignados = {
            id_permiso
            for (id_permiso,) in session.query(RolPermiso.id_permiso).filter(RolPermiso.id_rol == id_rol).all()
        }
        permisos = PermisoService.listar_permisos(session)
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
