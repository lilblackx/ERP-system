from sqlalchemy.orm import Session, joinedload

from app.db.models import Permiso, Rol, RolPermiso, Usuario, Vendedor
from app.services.auditoria import AuditoriaService
from app.services.auth import hash_password, validar_password_policy
from app.services.permisos import require_permiso

ESTADOS_VALIDOS = {"ACTIVO", "INACTIVO"}


def _validar_nombre_usuario_unico(session: Session, nombre_usuario: str, excluir_id: int | None = None) -> None:
    query = session.query(Usuario).filter(Usuario.nombre_usuario == nombre_usuario)
    if excluir_id is not None:
        query = query.filter(Usuario.id_usuario != excluir_id)
    if query.first() is not None:
        raise ValueError(f"El nombre de usuario '{nombre_usuario}' ya esta en uso")


def _resolver_vinculo_vendedor(session: Session, id_rol: int | None, id_vendedor_usuario: int | None) -> int | None:
    if not id_rol or not id_vendedor_usuario:
        return None

    rol = session.get(Rol, id_rol)
    if rol is None:
        raise ValueError("Rol no encontrado")
    if rol.nombre != "VENDEDOR":
        # Solo se vincula la entidad vendedores cuando el rol asignado es VENDEDOR.
        return None

    if session.get(Vendedor, id_vendedor_usuario) is None:
        raise ValueError("Vendedor no encontrado")
    return id_vendedor_usuario


class UsuarioService:
    @staticmethod
    def crear_usuario(
        session: Session,
        nombre_usuario: str,
        nombre: str | None,
        apellido: str | None,
        email: str | None,
        clave: str,
        id_rol: int | None,
        id_vendedor_usuario: int | None = None,
        realizado_por: int | None = None,
    ) -> Usuario:
        require_permiso(session, realizado_por, "usuarios", "crear")
        if not nombre_usuario:
            raise ValueError("nombre_usuario es requerido")
        if not clave:
            raise ValueError("clave es requerida")
        validar_password_policy(clave)

        _validar_nombre_usuario_unico(session, nombre_usuario)
        id_vendedor_usuario = _resolver_vinculo_vendedor(session, id_rol, id_vendedor_usuario)

        usuario = Usuario(
            nombre_usuario=nombre_usuario,
            nombre=nombre,
            apellido=apellido,
            email=email,
            clave=hash_password(clave),
            id_rol=id_rol,
            id_vendedor_usuario=id_vendedor_usuario,
        )
        session.add(usuario)
        session.commit()
        session.refresh(usuario)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=realizado_por,
            accion="CREAR_USUARIO",
            modulo="USUARIOS",
            detalle={"id_usuario": usuario.id_usuario, "nombre_usuario": usuario.nombre_usuario},
        )
        return usuario

    @staticmethod
    def editar_usuario(
        session: Session,
        id_usuario: int,
        datos: dict,
        nueva_clave: str | None = None,
        realizado_por: int | None = None,
    ) -> Usuario:
        require_permiso(session, realizado_por, "usuarios", "editar")
        usuario = session.get(Usuario, id_usuario)
        if usuario is None:
            raise ValueError("Usuario no encontrado")

        datos = {k: v for k, v in datos.items() if k != "clave"}

        nuevo_nombre_usuario = datos.get("nombre_usuario")
        if nuevo_nombre_usuario and nuevo_nombre_usuario != usuario.nombre_usuario:
            _validar_nombre_usuario_unico(session, nuevo_nombre_usuario, excluir_id=id_usuario)

        for campo, valor in datos.items():
            setattr(usuario, campo, valor)

        if "id_rol" in datos or "id_vendedor_usuario" in datos:
            usuario.id_vendedor_usuario = _resolver_vinculo_vendedor(
                session, usuario.id_rol, usuario.id_vendedor_usuario
            )

        if nueva_clave:
            validar_password_policy(nueva_clave)
            usuario.clave = hash_password(nueva_clave)

        session.commit()
        session.refresh(usuario)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=realizado_por,
            accion="ACTUALIZAR_USUARIO",
            modulo="USUARIOS",
            detalle={
                "id_usuario": usuario.id_usuario,
                "campos": list(datos.keys()),
                "clave_restablecida": bool(nueva_clave),
            },
        )
        return usuario

    @staticmethod
    def cambiar_estado(
        session: Session, id_usuario: int, nuevo_estado: str, realizado_por: int | None = None
    ) -> Usuario:
        require_permiso(session, realizado_por, "usuarios", "editar")
        if nuevo_estado not in ESTADOS_VALIDOS:
            raise ValueError(f"nuevo_estado debe ser uno de {ESTADOS_VALIDOS}")

        usuario = session.get(Usuario, id_usuario)
        if usuario is None:
            raise ValueError("Usuario no encontrado")

        usuario.estado = nuevo_estado
        session.commit()
        session.refresh(usuario)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=realizado_por,
            accion="CAMBIO_ESTADO_USUARIO",
            modulo="USUARIOS",
            detalle={"id_usuario": usuario.id_usuario, "nuevo_estado": nuevo_estado},
        )
        return usuario

    @staticmethod
    def desbloquear_usuario(session: Session, id_usuario: int, realizado_por: int | None = None) -> Usuario:
        """Via de escape manual para C7: si el usuario no tiene correo registrado (o el
        envio de codigo falla), no hay auto-desbloqueo por tiempo -- un ADMIN tiene que
        limpiar el bloqueo a mano. Sin panel de UI todavia (usuarios sigue en
        PlaceholderView), pero el metodo de servicio ya existe para cuando se construya."""
        require_permiso(session, realizado_por, "usuarios", "editar")
        usuario = session.get(Usuario, id_usuario)
        if usuario is None:
            raise ValueError("Usuario no encontrado")

        usuario.bloqueado_desde = None
        usuario.intentos_fallidos = 0
        session.commit()
        session.refresh(usuario)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=realizado_por,
            accion="DESBLOQUEO_MANUAL_USUARIO",
            modulo="USUARIOS",
            detalle={"id_usuario": usuario.id_usuario},
        )
        return usuario

    @staticmethod
    def listar_usuarios(
        session: Session,
        texto_busqueda: str | None = None,
        id_rol: int | None = None,
        estado: str | None = None,
        id_usuario: int | None = None,
    ) -> list[dict]:
        require_permiso(session, id_usuario, "usuarios", "ver")
        query = session.query(Usuario).options(joinedload(Usuario.rol))

        if texto_busqueda:
            like = f"%{texto_busqueda}%"
            query = query.filter(
                Usuario.nombre_usuario.ilike(like) | Usuario.nombre.ilike(like) | Usuario.apellido.ilike(like)
            )
        if id_rol:
            query = query.filter(Usuario.id_rol == id_rol)
        if estado:
            query = query.filter(Usuario.estado == estado)

        usuarios = query.order_by(Usuario.nombre_usuario).all()
        return [
            {
                "id_usuario": usuario.id_usuario,
                "nombre_usuario": usuario.nombre_usuario,
                "nombre_completo": " ".join(filter(None, [usuario.nombre, usuario.apellido])) or None,
                "rol": usuario.rol.nombre if usuario.rol else None,
                "estado": usuario.estado,
            }
            for usuario in usuarios
        ]

    # Misma consulta que require_permiso() en app/services/permisos.py (el punto de
    # entrada de autorizacion real, con el bypass de ADMIN incluido) -- duplicada en vez
    # de reusada para evitar un import circular (permisos.py no puede importar
    # UsuarioService si usuarios.py importa require_permiso). Hallazgo de auditoria
    # 2026-08-22, resuelto el mismo dia.
    @staticmethod
    def verificar_permiso(session: Session, id_usuario: int, recurso: str, accion: str) -> bool:
        usuario = session.get(Usuario, id_usuario)
        if usuario is None or usuario.id_rol is None:
            return False

        existe = (
            session.query(RolPermiso)
            .join(Permiso, Permiso.id_permiso == RolPermiso.id_permiso)
            .filter(
                RolPermiso.id_rol == usuario.id_rol,
                Permiso.recurso == recurso,
                Permiso.accion == accion,
            )
            .first()
        )
        return existe is not None
