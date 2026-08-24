import re
from datetime import datetime

import bcrypt
from sqlalchemy.orm import Session, joinedload

from app.db.models import Usuario
from app.services.auditoria import AuditoriaService

MAX_INTENTOS_FALLIDOS = 5

PASSWORD_MIN_LENGTH = 8
PASSWORD_POLICY_DESCRIPCION = (
    f"minimo {PASSWORD_MIN_LENGTH} caracteres, con al menos una mayuscula, una minuscula, "
    "un numero y un caracter especial"
)


class CuentaBloqueadaError(Exception):
    """Se lanza cuando el usuario tiene la cuenta bloqueada por intentos fallidos.

    Distinto de "credenciales invalidas" (que sigue devolviendo None) -- aca ni
    siquiera se verifica la clave, para que agotar el bloqueo no sirva de oraculo de
    fuerza bruta mientras la cuenta esta bloqueada. No se auto-desbloquea con el tiempo:
    la unica salida es un codigo enviado al correo (app/services/recuperacion_acceso.py)
    o un ADMIN via UsuarioService.desbloquear_usuario()."""

    def __init__(self, bloqueado_desde: datetime):
        self.bloqueado_desde = bloqueado_desde
        super().__init__("Cuenta bloqueada por intentos fallidos. Solicite un codigo de desbloqueo a su correo.")


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
        return None

    if usuario.bloqueado_desde is not None:
        raise CuentaBloqueadaError(usuario.bloqueado_desde)

    if usuario.clave and verify_password(clave, usuario.clave):
        usuario.intentos_fallidos = 0
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
    if usuario.intentos_fallidos >= MAX_INTENTOS_FALLIDOS:
        usuario.bloqueado_desde = datetime.now()
    AuditoriaService.registrar_evento(
        session,
        id_usuario=usuario.id_usuario,
        accion=accion_fallo,
        modulo="AUTH",
        detalle=f"Intento fallido #{usuario.intentos_fallidos} para '{usuario.nombre_usuario}'",
    )
    return None
