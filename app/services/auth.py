import logging
import re
import socket
from datetime import datetime

import bcrypt
from sqlalchemy.orm import Session, joinedload

from app.db.models import Usuario
from app.services.auditoria import AuditoriaService
from app.services.bloqueo import MAX_INTENTOS_FALLIDOS, bloqueado_hasta

logger = logging.getLogger(__name__)

PASSWORD_MIN_LENGTH = 8
# bcrypt trunca (versiones viejas) o directamente rechaza (bcrypt>=4 para el paquete
# python) cualquier clave cuyos bytes UTF-8 superen 72 -- sin este tope, hash_password()
# podia fallar con un ValueError crudo de la libreria en vez de un mensaje claro, o peor,
# hashear silenciosamente solo los primeros 72 bytes y descartar el resto sin avisar
# (auditoria de Usuarios, 2026-08-27).
PASSWORD_MAX_BYTES = 72
PASSWORD_POLICY_DESCRIPCION = (
    f"minimo {PASSWORD_MIN_LENGTH} caracteres, con al menos una mayuscula, una minuscula, "
    "un numero y un caracter especial"
)


class CuentaBloqueadaError(Exception):
    """Se lanza cuando el usuario tiene la cuenta bloqueada por intentos fallidos.

    Distinto de "credenciales invalidas" (que sigue devolviendo None) -- aca ni
    siquiera se verifica la clave, para que agotar el bloqueo no sirva de oraculo de
    fuerza bruta mientras la cuenta esta bloqueada. El bloqueo es temporal y escalonado
    (ver app/services/bloqueo.py): vence solo, o se levanta antes con un codigo enviado al
    correo (app/services/recuperacion_acceso.py) o un ADMIN via
    UsuarioService.desbloquear_usuario()."""

    def __init__(self, bloqueado_desde: datetime, bloqueado_hasta: datetime | None = None):
        self.bloqueado_desde = bloqueado_desde
        self.bloqueado_hasta = bloqueado_hasta
        if bloqueado_hasta is not None:
            minutos = max(1, int((bloqueado_hasta - datetime.now()).total_seconds() // 60) + 1)
            cuando = f"Intente de nuevo en {minutos} min, "
        else:
            cuando = ""
        super().__init__(
            f"Cuenta bloqueada por intentos fallidos. {cuando}o solicite un código de desbloqueo a su correo."
        )


def hash_password(plain: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def validar_password_policy(password: str) -> None:
    """C6: politica minima de complejidad de clave. Se usa tanto al crear/editar un
    usuario (UsuarioService) como al fijar una clave nueva por recuperacion
    (RecuperacionAccesoService) -- un solo lugar para no duplicar las reglas."""
    faltantes = []
    if len(password) < PASSWORD_MIN_LENGTH:
        faltantes.append(f"minimo {PASSWORD_MIN_LENGTH} caracteres")
    if len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        faltantes.append(f"maximo {PASSWORD_MAX_BYTES} bytes (bcrypt no admite claves mas largas)")
    if not re.search(r"[A-Z]", password):
        faltantes.append("una mayuscula")
    if not re.search(r"[a-z]", password):
        faltantes.append("una minuscula")
    if not re.search(r"\d", password):
        faltantes.append("un numero")
    if not re.search(r"[^\w\s]", password):
        faltantes.append("un caracter especial")

    if faltantes:
        raise ValueError("La clave no cumple la politica de seguridad, falta: " + ", ".join(faltantes) + ".")


def authenticate(
    session: Session,
    nombre_usuario: str,
    clave: str,
    accion_exito: str = "LOGIN",
    accion_fallo: str = "LOGIN_FALLIDO",
) -> Usuario | None:
    """Verifica usuario+clave contra bcrypt, con el mismo conteo de intentos fallidos/
    bloqueo de cuenta sin importar el motivo de la verificacion.

    accion_exito/accion_fallo permiten reusar esta misma verificacion (y su proteccion
    de fuerza bruta) para flujos distintos al login principal -- ej. el dialogo de
    autorizacion de descuentos en facturacion (app/ui/autorizacion_dialog.py) pide
    usuario+clave de un supervisor sin cerrar la sesion del vendedor, y ese intento
    tambien debe contar contra el bloqueo de CUENTA del supervisor, pero logueado como
    'AUTORIZACION_DESCUENTO'/'AUTORIZACION_DESCUENTO_FALLIDA' en vez de 'LOGIN', para no
    ensuciar la auditoria con inicios de sesion que nunca ocurrieron."""
    usuario = (
        session.query(Usuario)
        .options(joinedload(Usuario.rol))
        .filter(Usuario.nombre_usuario == nombre_usuario, Usuario.estado == "ACTIVO")
        .first()
    )
    if usuario is None:
        logger.warning("Intento de login con usuario inexistente: '%s'", nombre_usuario)
        return None

    if usuario.bloqueado_desde is not None:
        hasta = bloqueado_hasta(usuario)
        if hasta is not None and datetime.now() < hasta:
            logger.warning("Intento de login contra cuenta bloqueada: '%s'", nombre_usuario)
            raise CuentaBloqueadaError(usuario.bloqueado_desde, hasta)
        # Bloqueo vencido: se levanta. intentos_fallidos NO se reinicia -- si falla de nuevo,
        # el siguiente bloqueo es mas largo (solo un login correcto lo pone en cero).
        usuario.bloqueado_desde = None

    if usuario.clave and verify_password(clave, usuario.clave):
        usuario.intentos_fallidos = 0
        logger.info(
            "Login exitoso: usuario='%s' accion=%s",
            usuario.nombre_usuario,
            accion_exito,
        )
        AuditoriaService.registrar_evento(
            session,
            id_usuario=usuario.id_usuario,
            accion=accion_exito,
            modulo="AUTH",
            detalle=f"Usuario '{usuario.nombre_usuario}' inicio sesion",
        )
        _ = usuario.rol  # el commit de arriba expira los atributos ya cargados
        return usuario

    usuario.intentos_fallidos += 1
    recien_bloqueada = usuario.intentos_fallidos >= MAX_INTENTOS_FALLIDOS
    if recien_bloqueada:
        usuario.bloqueado_desde = datetime.now()
        logger.warning(
            "Cuenta '%s' bloqueada tras %d intentos fallidos",
            usuario.nombre_usuario,
            usuario.intentos_fallidos,
        )
    else:
        logger.warning(
            "Login fallido: usuario='%s' intento=%d accion=%s",
            usuario.nombre_usuario,
            usuario.intentos_fallidos,
            accion_fallo,
        )
    AuditoriaService.registrar_evento(
        session,
        id_usuario=usuario.id_usuario,
        accion=accion_fallo,
        modulo="AUTH",
        # Desde que PC se intento: sin esto no hay forma de saber quien esta probando claves.
        detalle=f"Intento fallido #{usuario.intentos_fallidos} para '{usuario.nombre_usuario}' desde {_equipo()}",
    )
    if recien_bloqueada:
        _avisar_bloqueo_a_administradores(session, usuario)
    return None


def _equipo() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "equipo desconocido"


def _avisar_bloqueo_a_administradores(session: Session, bloqueado: Usuario) -> None:
    """Correo a los ADMIN activos cuando una cuenta se bloquea: puede ser alguien probando
    claves. Nunca interrumpe el login -- si el correo falla (SMTP sin configurar, servidor
    caido) solo se registra en el log; la campana de notificaciones avisa igual."""
    try:
        from app.services.cola_correos import CorreoService

        CorreoService.avisar_bloqueo_de_cuenta(session, bloqueado, _equipo())
    except Exception:
        session.rollback()
        logger.exception("No se pudo avisar a los administradores del bloqueo de '%s'", bloqueado.nombre_usuario)
