import re

from sqlalchemy.orm import Session, joinedload

from app.db.models import Permiso, Rol, RolPermiso, Usuario, Vendedor
from app.services.auditoria import AuditoriaService
from app.services.auth import hash_password, validar_password_policy
from app.services.permisos import require_permiso

ESTADOS_VALIDOS = {"ACTIVO", "INACTIVO"}

# Mismos limites que las columnas de la tabla usuarios (app/db/models.py) -- sin esto,
# pegar un texto muy largo en cualquiera de estos campos dispara un error crudo de SQL
# Server (truncamiento) en vez de un mensaje claro (auditoria de Usuarios, 2026-08-27).
NOMBRE_USUARIO_MAX = 50
NOMBRE_MAX = 100
APELLIDO_MAX = 100
EMAIL_MAX = 150

# Chequeo de forma, no de entregabilidad real (validar eso requeriria enviar un correo) --
# suficiente para atrapar un typo obvio ("asdf", "juan@") antes de que el usuario quede sin
# forma de recibir su codigo de desbloqueo/recuperacion (RecuperacionAccesoService).
_EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validar_longitudes(nombre_usuario: str, nombre: str | None, apellido: str | None, email: str | None) -> None:
    if len(nombre_usuario) > NOMBRE_USUARIO_MAX:
        raise ValueError(f"nombre_usuario no puede superar {NOMBRE_USUARIO_MAX} caracteres")
    if nombre and len(nombre) > NOMBRE_MAX:
        raise ValueError(f"nombre no puede superar {NOMBRE_MAX} caracteres")
    if apellido and len(apellido) > APELLIDO_MAX:
        raise ValueError(f"apellido no puede superar {APELLIDO_MAX} caracteres")
    if email and len(email) > EMAIL_MAX:
        raise ValueError(f"email no puede superar {EMAIL_MAX} caracteres")
    if email and not _EMAIL_REGEX.match(email):
        raise ValueError(f"'{email}' no tiene un formato de correo valido")


def _validar_nombre_usuario_unico(session: Session, nombre_usuario: str, excluir_id: int | None = None) -> None:
    query = session.query(Usuario).filter(Usuario.nombre_usuario == nombre_usuario)
    if excluir_id is not None:
        query = query.filter(Usuario.id_usuario != excluir_id)
    if query.first() is not None:
        raise ValueError(f"El nombre de usuario '{nombre_usuario}' ya esta en uso")


def _validar_email_unico(session: Session, email: str, excluir_id: int | None = None) -> None:
    # El correo identifica a donde van los codigos de desbloqueo/recuperacion de clave
    # (RecuperacionAccesoService) -- si dos usuarios comparten uno, cada solicitud (que
    # busca por nombre_usuario, no por email) igual termina mandando el codigo a una
    # casilla que el OTRO usuario tambien puede leer.
    query = session.query(Usuario).filter(Usuario.email == email)
    if excluir_id is not None:
        query = query.filter(Usuario.id_usuario != excluir_id)
    if query.first() is not None:
        raise ValueError(f"El correo '{email}' ya esta en uso por otro usuario")


def _resolver_vinculo_vendedor(
    session: Session, id_rol: int | None, id_vendedor_usuario: int | None, excluir_id_usuario: int | None = None
) -> int | None:
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

    # Un Vendedor no puede quedar vinculado a mas de un login: dos usuarios distintos
    # viendo/operando como el mismo vendedor mezclaria reportes y comisiones entre
    # ambos sin ninguna forma de distinguir quien hizo que.
    query = session.query(Usuario).filter(Usuario.id_vendedor_usuario == id_vendedor_usuario)
    if excluir_id_usuario is not None:
        query = query.filter(Usuario.id_usuario != excluir_id_usuario)
    otro = query.first()
    if otro is not None:
        raise ValueError(f"El vendedor ya esta vinculado al usuario '{otro.nombre_usuario}'")

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
        if not email:
            # El correo no es solo un dato de contacto: es a donde
            # RecuperacionAccesoService envia los codigos de desbloqueo/recuperacion de
            # clave (app/services/recuperacion_acceso.py) -- un usuario sin correo
            # registrado queda sin forma de desbloquearse ni recuperar su clave solo
            # (_solicitar_codigo() no envia nada si usuario.email esta vacio, y responde
            # el mismo mensaje generico igual, sin avisar que fallo).
            raise ValueError("email es requerido: es a donde se envian los codigos de desbloqueo/recuperacion de clave")
        if not clave:
            raise ValueError("clave es requerida")
        validar_password_policy(clave)
        _validar_longitudes(nombre_usuario, nombre, apellido, email)

        _validar_nombre_usuario_unico(session, nombre_usuario)
        _validar_email_unico(session, email)
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

        if "email" in datos and not datos["email"]:
            # Mismo motivo que en crear_usuario(): no dejar que una edicion vacie el
            # correo de un usuario existente, o lo deja sin forma de desbloquearse ni
            # recuperar su clave solo.
            raise ValueError("email es requerido: es a donde se envian los codigos de desbloqueo/recuperacion de clave")

        _validar_longitudes(
            datos.get("nombre_usuario", usuario.nombre_usuario),
            datos.get("nombre", usuario.nombre),
            datos.get("apellido", usuario.apellido),
            datos.get("email", usuario.email),
        )

        nuevo_nombre_usuario = datos.get("nombre_usuario")
        if nuevo_nombre_usuario and nuevo_nombre_usuario != usuario.nombre_usuario:
            _validar_nombre_usuario_unico(session, nuevo_nombre_usuario, excluir_id=id_usuario)

        nuevo_email = datos.get("email")
        if nuevo_email and nuevo_email != usuario.email:
            _validar_email_unico(session, nuevo_email, excluir_id=id_usuario)

        for campo, valor in datos.items():
            setattr(usuario, campo, valor)

        if "id_rol" in datos or "id_vendedor_usuario" in datos:
            usuario.id_vendedor_usuario = _resolver_vinculo_vendedor(
                session, usuario.id_rol, usuario.id_vendedor_usuario, excluir_id_usuario=id_usuario
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

        if nuevo_estado == "INACTIVO":
            # Auditoria de Usuarios (2026-08-27): antes este guard solo existia en la UI
            # (usuarios_panel.py) -- cualquier otro punto de entrada al servicio podia
            # desactivar la propia cuenta sin aviso.
            if id_usuario == realizado_por:
                raise ValueError("No puedes desactivar tu propia cuenta")

            rol = session.get(Rol, usuario.id_rol) if usuario.id_rol is not None else None
            if rol is not None and rol.nombre == "ADMIN":
                # Sin esto, dos ADMIN podrian desactivarse mutuamente (cada uno no puede
                # desactivarse a si mismo, pero si al otro) hasta dejar el sistema sin
                # ningun ADMIN activo -- sin nadie que pueda gestionar Usuarios/Permisos
                # salvo tocando la base directo.
                otros_admins_activos = (
                    session.query(Usuario)
                    .join(Rol, Rol.id_rol == Usuario.id_rol)
                    .filter(Rol.nombre == "ADMIN", Usuario.estado == "ACTIVO", Usuario.id_usuario != id_usuario)
                    .count()
                )
                if otros_admins_activos == 0:
                    raise ValueError("No se puede desactivar: es el unico administrador activo del sistema")

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
        if usuario.estado != "ACTIVO" or usuario.bloqueado_desde is not None:
            return False

        # Bypass de ADMIN: el seed no le asigna filas en rol_permisos (ver
        # require_permiso()), asi que sin esto un ADMIN quedaba evaluado como si no
        # tuviera ningun permiso -- bug preexistente sin caller real hasta que
        # app/ui/sidebar.py empezo a usar este metodo para filtrar el menu por rol
        # (2026-08-27): sin el bypass, un ADMIN se hubiera quedado sin ver ningun modulo.
        rol = session.get(Rol, usuario.id_rol)
        if rol is not None and rol.nombre == "ADMIN":
            return True

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
