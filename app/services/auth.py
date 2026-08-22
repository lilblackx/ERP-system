import bcrypt
from sqlalchemy.orm import Session, joinedload

from app.db.models import Usuario
from app.services.auditoria import AuditoriaService


def hash_password(plain: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# TODO(seguridad): solo se audita el login exitoso. No hay registro de intentos
# fallidos ni bloqueo tras N intentos -- sin rastro de fuerza bruta si el acceso no es
# unicamente desde red local. Hallazgo de auditoria 2026-08-22.
def authenticate(session: Session, nombre_usuario: str, clave: str) -> Usuario | None:
    usuario = (
        session.query(Usuario)
        .options(joinedload(Usuario.rol))
        .filter(Usuario.nombre_usuario == nombre_usuario, Usuario.estado == "ACTIVO")
        .first()
    )
    if usuario and usuario.clave and verify_password(clave, usuario.clave):
        AuditoriaService.registrar_evento(
            session,
            id_usuario=usuario.id_usuario,
            accion="LOGIN",
            modulo="AUTH",
            detalle=f"Usuario '{usuario.nombre_usuario}' inicio sesion",
        )
        _ = usuario.rol  # el commit de arriba expira los atributos ya cargados
        return usuario
    return None
