"""Correo saliente: lo envia SOLO el servidor.

Una estacion nunca habla con el servidor SMTP ni conoce la contrasena de la cuenta (esta
cifrada con una llave que solo tiene el servidor, ver cifrado_servidor.py). Cuando una
estacion necesita mandar un correo -- codigo de desbloqueo/recuperacion de clave, aviso de
seguridad -- lo deja en `cola_correos`, y el servidor lo despacha:

- el servicio de Windows del servidor (app/servicio_licencia.py) revisa la cola cada pocos
  segundos, aunque nadie tenga la app abierta, y
- la app abierta en el servidor tambien la revisa (app/ui/main_window.py), por si el servicio
  no esta instalado.

Ambos pueden correr a la vez sin duplicar envios: cada correo se "reclama" con un UPDATE
atomico (PENDIENTE -> ENVIANDO) antes de mandarse.

El SERVIDOR que necesita mandar un correo por su cuenta (p. ej. un usuario que se bloquea en
la propia PC del servidor) lo envia directo, sin pasar por la cola.

Los codigos de verificacion vencen a los 15 min: un correo que no se alcanzo a enviar antes
de su vencimiento se descarta (no tiene sentido mandar un codigo ya vencido). Al enviarse o
vencer se borra el contenido del mensaje, para que los codigos no queden en la base.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import ColaCorreo, Usuario
from app.services import cifrado_servidor
from app.services.email_service import enviar_correo
from app.services.smtp_config import SmtpConfigService

logger = logging.getLogger(__name__)

MAX_INTENTOS_ENVIO = 3
# Un correo en ENVIANDO mas de este tiempo se da por colgado (el proceso que lo reclamo se
# cayo) y vuelve a PENDIENTE.
TIMEOUT_ENVIANDO = timedelta(minutes=5)
RETENCION_HISTORIAL = timedelta(days=7)
VALIDEZ_POR_DEFECTO = timedelta(minutes=15)
ENFRIAMIENTO_AVISO_BLOQUEO = timedelta(minutes=30)

TIPO_AVISO_BLOQUEO = "AVISO_BLOQUEO"


class CorreoService:
    @staticmethod
    def enviar_o_encolar(
        session: Session,
        destinatario: str,
        asunto: str,
        cuerpo: str,
        cuerpo_html: str | None = None,
        tipo: str = "GENERAL",
        referencia: str | None = None,
        validez: timedelta = VALIDEZ_POR_DEFECTO,
        creado_por: int | None = None,
        enviar=None,
    ) -> bool:
        """En el servidor envia directo (y deja pasar el error si falla, igual que antes); en
        una estacion deja el correo en la cola. Devuelve True si se envio ya, False si quedo
        en cola. `enviar` permite inyectar la funcion de envio (los tests la reemplazan)."""
        if cifrado_servidor.es_servidor():
            (enviar or enviar_correo)(
                destinatario,
                asunto,
                cuerpo,
                cuerpo_html=cuerpo_html,
                ajustes=SmtpConfigService.obtener_efectiva(session),
            )
            return True

        ahora = datetime.now()
        session.add(
            ColaCorreo(
                tipo=tipo,
                referencia=referencia,
                destinatario=destinatario,
                asunto=asunto,
                cuerpo=cuerpo,
                cuerpo_html=cuerpo_html,
                fecha_creacion=ahora,
                fecha_actualizacion=ahora,
                fecha_vencimiento=ahora + validez,
                creado_por=creado_por,
            )
        )
        session.commit()
        return False

    @staticmethod
    def procesar_pendientes(session: Session, limite: int = 20) -> dict[str, int]:
        """Despacha los correos pendientes. Solo en el SERVIDOR (en una estacion no hace nada:
        no puede descifrar la contrasena). Nunca lanza por un correo que falle: lo reintenta en
        la proxima pasada y, tras MAX_INTENTOS_ENVIO, lo marca ERROR."""
        resultado = {"enviados": 0, "errores": 0, "vencidos": 0}
        if not cifrado_servidor.es_servidor():
            return resultado

        ahora = datetime.now()
        CorreoService._recuperar_colgados(session, ahora)
        resultado["vencidos"] = CorreoService._descartar_vencidos(session, ahora)

        ids = [
            fila[0]
            for fila in session.execute(
                text(
                    "UPDATE TOP (:limite) dbo.cola_correos "
                    "SET estado = 'ENVIANDO', intentos = intentos + 1, fecha_actualizacion = :ahora "
                    "OUTPUT inserted.id_correo "
                    "WHERE estado = 'PENDIENTE' AND fecha_vencimiento > :ahora"
                ),
                {"limite": limite, "ahora": ahora},
            ).fetchall()
        ]
        session.commit()
        if not ids:
            return resultado

        ajustes = SmtpConfigService.obtener_efectiva(session)
        for id_correo in sorted(ids):
            correo = session.get(ColaCorreo, id_correo)
            if correo is None:
                continue
            try:
                enviar_correo(
                    correo.destinatario,
                    correo.asunto,
                    correo.cuerpo,
                    cuerpo_html=correo.cuerpo_html,
                    ajustes=ajustes,
                )
            except Exception as exc:
                resultado["errores"] += 1
                CorreoService._registrar_fallo(session, correo, exc)
                continue
            correo.estado = "ENVIADO"
            correo.fecha_envio = datetime.now()
            correo.fecha_actualizacion = datetime.now()
            correo.error = None
            CorreoService._limpiar_contenido(correo)
            session.commit()
            resultado["enviados"] += 1

        CorreoService._purgar_historial(session, ahora)
        return resultado

    @staticmethod
    def _limpiar_contenido(correo: ColaCorreo) -> None:
        correo.cuerpo = ""
        correo.cuerpo_html = None

    @staticmethod
    def _registrar_fallo(session: Session, correo: ColaCorreo, exc: Exception) -> None:
        logger.warning("No se pudo enviar el correo %s (intento %s): %s", correo.id_correo, correo.intentos, exc)
        correo.error = str(exc)[:500]
        correo.fecha_actualizacion = datetime.now()
        if correo.intentos >= MAX_INTENTOS_ENVIO:
            correo.estado = "ERROR"
            CorreoService._limpiar_contenido(correo)
        else:
            correo.estado = "PENDIENTE"
        session.commit()

    @staticmethod
    def _recuperar_colgados(session: Session, ahora: datetime) -> None:
        session.execute(
            text(
                "UPDATE dbo.cola_correos SET estado = 'PENDIENTE', fecha_actualizacion = :ahora "
                "WHERE estado = 'ENVIANDO' AND fecha_actualizacion < :limite"
            ),
            {"ahora": ahora, "limite": ahora - TIMEOUT_ENVIANDO},
        )
        session.commit()

    @staticmethod
    def _descartar_vencidos(session: Session, ahora: datetime) -> int:
        vencidos = (
            session.query(ColaCorreo)
            .filter(ColaCorreo.estado == "PENDIENTE", ColaCorreo.fecha_vencimiento <= ahora)
            .all()
        )
        for correo in vencidos:
            correo.estado = "ERROR"
            correo.error = "Vencido antes de poder enviarse"
            correo.fecha_actualizacion = ahora
            CorreoService._limpiar_contenido(correo)
        session.commit()
        return len(vencidos)

    @staticmethod
    def _purgar_historial(session: Session, ahora: datetime) -> None:
        session.query(ColaCorreo).filter(
            ColaCorreo.estado.in_(("ENVIADO", "ERROR")),
            ColaCorreo.fecha_actualizacion < ahora - RETENCION_HISTORIAL,
        ).delete(synchronize_session=False)
        session.commit()

    # ── Avisos de seguridad a los administradores ───────────────────────────

    @staticmethod
    def avisar_bloqueo_de_cuenta(session: Session, bloqueado: Usuario, equipo: str) -> int:
        """Correo a cada ADMIN activo con correo registrado cuando una cuenta se bloquea por
        intentos fallidos (alguien puede estar probando claves). Un solo aviso por cuenta cada
        30 min, para que bloquear a proposito no sea una forma de llenar el correo del ADMIN.
        Devuelve a cuantos administradores se les aviso (o encolo)."""
        from app.db.models import Rol

        if CorreoService._aviso_reciente(session, bloqueado.id_usuario):
            return 0
        administradores = (
            session.query(Usuario)
            .join(Rol, Rol.id_rol == Usuario.id_rol)
            .filter(Rol.nombre == "ADMIN", Usuario.estado == "ACTIVO", Usuario.email.isnot(None))
            .all()
        )
        asunto = f"Cuenta bloqueada por intentos fallidos: {bloqueado.nombre_usuario}"
        cuerpo = (
            f"La cuenta '{bloqueado.nombre_usuario}' se bloqueó tras {bloqueado.intentos_fallidos} intentos "
            f"fallidos de inicio de sesión desde el equipo '{equipo}' ({datetime.now():%d/%m/%Y %H:%M}).\n\n"
            "Si no fue el propio usuario, alguien puede estar probando claves. El bloqueo es temporal; "
            "un administrador puede levantarlo antes desde Usuarios."
        )
        avisados = 0
        for admin in administradores:
            if not admin.email:
                continue
            try:
                CorreoService.enviar_o_encolar(
                    session,
                    admin.email,
                    asunto,
                    cuerpo,
                    tipo=TIPO_AVISO_BLOQUEO,
                    referencia=str(bloqueado.id_usuario),
                    validez=timedelta(hours=1),
                )
                avisados += 1
            except Exception:
                session.rollback()
                logger.exception(
                    "No se pudo avisar a '%s' del bloqueo de '%s'", admin.nombre_usuario, bloqueado.nombre_usuario
                )
        if administradores and not avisados:
            return 0
        # Marca para el enfriamiento aunque el envio directo (servidor) no pase por la cola.
        CorreoService._marcar_aviso(session, bloqueado.id_usuario)
        return avisados

    @staticmethod
    def _aviso_reciente(session: Session, id_usuario: int) -> bool:
        return (
            session.query(ColaCorreo.id_correo)
            .filter(
                ColaCorreo.tipo == TIPO_AVISO_BLOQUEO,
                ColaCorreo.referencia == str(id_usuario),
                ColaCorreo.fecha_creacion > datetime.now() - ENFRIAMIENTO_AVISO_BLOQUEO,
            )
            .first()
            is not None
        )

    @staticmethod
    def _marcar_aviso(session: Session, id_usuario: int) -> None:
        """Deja una fila ya ENVIADA como constancia del aviso (para el enfriamiento) cuando el
        envio fue directo; si el aviso se encolo ya hay una fila y no hace falta otra."""
        if CorreoService._aviso_reciente(session, id_usuario):
            return
        ahora = datetime.now()
        session.add(
            ColaCorreo(
                tipo=TIPO_AVISO_BLOQUEO,
                referencia=str(id_usuario),
                destinatario="administradores",
                asunto="Aviso de bloqueo enviado",
                cuerpo="",
                estado="ENVIADO",
                intentos=1,
                fecha_creacion=ahora,
                fecha_actualizacion=ahora,
                fecha_vencimiento=ahora,
                fecha_envio=ahora,
            )
        )
        session.commit()
