import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CodigoVerificacion, Usuario
from app.services.auditoria import AuditoriaService
from app.services.auth import hash_password, validar_password_policy
from app.services.email_service import enviar_correo

VALIDEZ_CODIGO = timedelta(minutes=15)
MAX_INTENTOS_VERIFICACION = 5

TIPO_DESBLOQUEO = "DESBLOQUEO"
TIPO_RECUPERAR_CLAVE = "RECUPERAR_CLAVE"

MENSAJE_SOLICITUD_GENERICO = "Si el usuario existe y tiene un correo registrado, se envio un codigo."


def _generar_codigo() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _hash_codigo(codigo: str) -> str:
    return hashlib.sha256(codigo.encode("utf-8")).hexdigest()


def _buscar_usuario(session: Session, nombre_usuario: str) -> Usuario | None:
    return session.query(Usuario).filter(Usuario.nombre_usuario == nombre_usuario).first()


def _crear_y_enviar_codigo(session: Session, usuario: Usuario, tipo: str) -> None:
    codigo = _generar_codigo()
    registro = CodigoVerificacion(
        id_usuario=usuario.id_usuario,
        tipo=tipo,
        codigo_hash=_hash_codigo(codigo),
        fecha_expiracion=datetime.now() + VALIDEZ_CODIGO,
    )
    session.add(registro)
    session.commit()

    asunto = "Codigo de desbloqueo de cuenta" if tipo == TIPO_DESBLOQUEO else "Codigo para recuperar tu clave"
    cuerpo = (
        f"Tu codigo es: {codigo}\n\n"
        f"Vence en {int(VALIDEZ_CODIGO.total_seconds() // 60)} minutos. Si no solicitaste "
        "esto, ignora este correo."
    )
    enviar_correo(usuario.email, asunto, cuerpo)

    AuditoriaService.registrar_evento(
        session,
        id_usuario=usuario.id_usuario,
        accion=f"SOLICITUD_{tipo}",
        modulo="AUTH",
        detalle=f"Codigo enviado a '{usuario.nombre_usuario}'",
    )


def _solicitar_codigo(session: Session, nombre_usuario: str, tipo: str) -> None:
    """No revela si el usuario existe o tiene correo -- siempre responde generico
    (MENSAJE_SOLICITUD_GENERICO), igual que authenticate() no distingue usuario
    inexistente de clave incorrecta."""
    usuario = _buscar_usuario(session, nombre_usuario)
    if usuario is not None and usuario.email:
        _crear_y_enviar_codigo(session, usuario, tipo)


def _consumir_codigo(session: Session, usuario: Usuario, tipo: str, codigo_ingresado: str) -> None:
    """Verifica el codigo vigente mas reciente de ese tipo para el usuario. Lanza
    ValueError con un mensaje apto para mostrar tal cual al usuario (mismo criterio que
    C3: nunca un str(exc) tecnico)."""
    registro = (
        session.execute(
            select(CodigoVerificacion)
            .where(
                CodigoVerificacion.id_usuario == usuario.id_usuario,
                CodigoVerificacion.tipo == tipo,
                CodigoVerificacion.usado == False,  # noqa: E712 -- BIT en mssql, "IS 0" no es sintaxis valida
            )
            .order_by(CodigoVerificacion.fecha_creacion.desc())
        )
        .scalars()
        .first()
    )
    if registro is None:
        raise ValueError("No hay un codigo pendiente para este usuario. Solicite uno nuevo.")

    if registro.fecha_expiracion < datetime.now():
        registro.usado = True
        session.commit()
        raise ValueError("El codigo vencio. Solicite uno nuevo.")

    if registro.intentos_verificacion >= MAX_INTENTOS_VERIFICACION:
        registro.usado = True
        session.commit()
        raise ValueError("Se agotaron los intentos para este codigo. Solicite uno nuevo.")

    if not hmac.compare_digest(_hash_codigo(codigo_ingresado), registro.codigo_hash):
        registro.intentos_verificacion += 1
        if registro.intentos_verificacion >= MAX_INTENTOS_VERIFICACION:
            registro.usado = True
        session.commit()
        raise ValueError("Codigo incorrecto.")

    registro.usado = True
    session.commit()


class RecuperacionAccesoService:
    @staticmethod
    def solicitar_codigo_desbloqueo(session: Session, nombre_usuario: str) -> str:
        _solicitar_codigo(session, nombre_usuario, TIPO_DESBLOQUEO)
        return MENSAJE_SOLICITUD_GENERICO

    @staticmethod
    def verificar_codigo_desbloqueo(session: Session, nombre_usuario: str, codigo: str) -> None:
        usuario = _buscar_usuario(session, nombre_usuario)
        if usuario is None:
            raise ValueError("Codigo incorrecto.")

        _consumir_codigo(session, usuario, TIPO_DESBLOQUEO, codigo)

        usuario.bloqueado_desde = None
        usuario.intentos_fallidos = 0
        session.commit()

        AuditoriaService.registrar_evento(
            session,
            id_usuario=usuario.id_usuario,
            accion="DESBLOQUEO_EXITOSO",
            modulo="AUTH",
            detalle=f"Cuenta '{usuario.nombre_usuario}' desbloqueada por codigo",
        )

    @staticmethod
    def solicitar_codigo_recuperacion(session: Session, nombre_usuario: str) -> str:
        _solicitar_codigo(session, nombre_usuario, TIPO_RECUPERAR_CLAVE)
        return MENSAJE_SOLICITUD_GENERICO

    @staticmethod
    def verificar_codigo_y_cambiar_clave(
        session: Session, nombre_usuario: str, codigo: str, nueva_clave: str
    ) -> None:
        usuario = _buscar_usuario(session, nombre_usuario)
        if usuario is None:
            raise ValueError("Codigo incorrecto.")

        # Se valida la politica ANTES de consumir el codigo: si la clave elegida no
        # cumple, no tiene sentido quemar el codigo (ni sus intentos) por un problema
        # que no tiene nada que ver con el codigo en si -- el usuario deberia poder
        # reintentar con otra clave sin pedir un codigo nuevo.
        validar_password_policy(nueva_clave)
        _consumir_codigo(session, usuario, TIPO_RECUPERAR_CLAVE, codigo)

        usuario.clave = hash_password(nueva_clave)
        usuario.bloqueado_desde = None
        usuario.intentos_fallidos = 0
        session.commit()

        AuditoriaService.registrar_evento(
            session,
            id_usuario=usuario.id_usuario,
            accion="CLAVE_RESTABLECIDA",
            modulo="AUTH",
            detalle=f"Clave restablecida por codigo para '{usuario.nombre_usuario}'",
        )
