import smtplib
import socket
import ssl
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import ConfiguracionSmtp
from app.services.auditoria import AuditoriaService
from app.services.email_service import AjustesSmtp, ajustes_desde_entorno, probar_conexion
from app.services.permisos import require_permiso

_SENTINEL = object()

_MENSAJE_SIN_CONEXION = "No se pudo conectar a {host}:{puerto}. Revise el servidor, el puerto y la conexión a internet."


@dataclass(frozen=True)
class ProveedorCorreo:
    """Servicio de correo conocido: el usuario elige uno y servidor/puerto/TLS salen de aca,
    en vez de pedirselos (un usuario normal no sabe que es un puerto SMTP)."""

    clave: str
    nombre: str
    host: str
    puerto: int
    usar_tls: bool
    ayuda: str


# El orden es el del selector. Todos usan STARTTLS en 587, salvo que se indique otra cosa.
PROVEEDORES: tuple[ProveedorCorreo, ...] = (
    ProveedorCorreo(
        "gmail",
        "Gmail",
        "smtp.gmail.com",
        587,
        True,
        "Use una contraseña de aplicación de 16 caracteres, no la clave normal de la cuenta. Se genera en "
        "Cuenta de Google > Seguridad > Verificación en 2 pasos > Contraseñas de aplicaciones.",
    ),
    ProveedorCorreo(
        "outlook",
        "Outlook / Hotmail",
        "smtp-mail.outlook.com",
        587,
        True,
        "Si la cuenta tiene verificación en 2 pasos, use una contraseña de aplicación "
        "(cuenta de Microsoft > Seguridad > Opciones de seguridad avanzadas).",
    ),
    ProveedorCorreo(
        "microsoft365",
        "Microsoft 365 (correo de empresa)",
        "smtp.office365.com",
        587,
        True,
        "La cuenta debe tener habilitado el envío SMTP autenticado; si no funciona, consulte al "
        "administrador de Microsoft 365.",
    ),
    ProveedorCorreo(
        "yahoo",
        "Yahoo",
        "smtp.mail.yahoo.com",
        587,
        True,
        "Use una contraseña de aplicación, que se genera en Seguridad de la cuenta de Yahoo.",
    ),
    ProveedorCorreo(
        "icloud",
        "iCloud",
        "smtp.mail.me.com",
        587,
        True,
        "Use una contraseña específica de la app, que se genera en appleid.apple.com > Seguridad.",
    ),
    ProveedorCorreo(
        "zoho",
        "Zoho Mail",
        "smtp.zoho.com",
        587,
        True,
        "Si la cuenta tiene verificación en 2 pasos, use una contraseña de aplicación.",
    ),
)

PROVEEDOR_OTRO = "otro"


def proveedor_por_clave(clave: str | None) -> ProveedorCorreo | None:
    return next((p for p in PROVEEDORES if p.clave == clave), None)


def proveedor_de_servidor(host: str | None, puerto: int | None, usar_tls: bool | None) -> str:
    """Clave del proveedor del catalogo que coincide EXACTAMENTE con servidor+puerto+TLS
    guardados, o PROVEEDOR_OTRO. Asi no hace falta una columna 'proveedor' en la base: el
    selector se reconstruye al abrir la pantalla, y una configuracion manual que casualmente
    apunta a un servidor conocido se muestra como ese proveedor (es lo mismo)."""
    for p in PROVEEDORES:
        if (p.host.lower(), p.puerto, p.usar_tls) == ((host or "").strip().lower(), puerto, usar_tls):
            return p.clave
    return PROVEEDOR_OTRO


class SmtpConfigService:
    """Configuracion del servidor SMTP editable desde la app (Configuracion > Correo).

    Reusa el permiso 'empresa' (ver/editar), igual que el resto de esa pantalla: no hay un
    recurso propio en el catalogo de permisos y agregar uno obligaria a migrar el seed."""

    @staticmethod
    def obtener_configuracion(session: Session, id_usuario: int | None = None) -> ConfiguracionSmtp | None:
        require_permiso(session, id_usuario, "empresa", "ver")
        return session.query(ConfiguracionSmtp).order_by(ConfiguracionSmtp.id_config).first()

    @staticmethod
    def obtener_efectiva(session: Session) -> AjustesSmtp:
        """Ajustes con los que realmente se manda el correo. Sin gate de permiso, a
        proposito: los usa el flujo de desbloqueo/recuperar clave, que corre sin ningun
        usuario autenticado. Gana lo guardado en la base si ya trae usuario y clave; si no
        (nunca se configuro desde la app, o quedo a medias) se usa el .env."""
        fila = session.query(ConfiguracionSmtp).order_by(ConfiguracionSmtp.id_config).first()
        if fila is not None and fila.usuario and fila.password:
            return AjustesSmtp(
                host=fila.host,
                puerto=fila.puerto,
                usuario=fila.usuario,
                password=fila.password,
                remitente=fila.remitente or "",
                usar_tls=bool(fila.usar_tls),
            )
        return ajustes_desde_entorno()

    @staticmethod
    def guardar_configuracion(
        session: Session,
        host: str,
        puerto: int,
        usuario: str | None,
        password: str | None = _SENTINEL,
        remitente: str | None = None,
        usar_tls: bool = True,
        modificado_por: int | None = None,
    ) -> ConfiguracionSmtp:
        """Actualiza el registro singleton, o lo crea si no existe.

        `password` usa un sentinel, igual que logo_bytes en EmpresaService: omitido, la
        clave guardada no se toca (la UI nunca la muestra, asi que guardar sin reescribirla
        no puede borrarla); para vaciarla hay que pasar password=None o ''."""
        require_permiso(session, modificado_por, "empresa", "editar")

        host = (host or "").strip()
        if not host:
            raise ValueError("El servidor SMTP es requerido")
        try:
            puerto = int(puerto)
        except (TypeError, ValueError) as e:
            raise ValueError("El puerto debe ser un número") from e
        if not 1 <= puerto <= 65535:
            raise ValueError("El puerto debe estar entre 1 y 65535")

        fila = session.query(ConfiguracionSmtp).order_by(ConfiguracionSmtp.id_config).first()
        if fila is None:
            fila = ConfiguracionSmtp()
            session.add(fila)

        fila.host = host
        fila.puerto = puerto
        fila.usuario = (usuario or "").strip() or None
        fila.remitente = (remitente or "").strip() or None
        fila.usar_tls = usar_tls
        fila.modificado_por = modificado_por
        if password is not _SENTINEL:
            fila.password = password or None

        session.commit()
        session.refresh(fila)

        # La clave no va a la auditoria: solo si hay una guardada.
        AuditoriaService.registrar_evento(
            session,
            id_usuario=modificado_por,
            accion="ACTUALIZAR_CONFIGURACION_SMTP",
            modulo="EMPRESA",
            detalle={
                "host": fila.host,
                "puerto": fila.puerto,
                "usuario": fila.usuario,
                "usar_tls": fila.usar_tls,
                "tiene_password": bool(fila.password),
            },
        )
        return fila

    @staticmethod
    def probar_conexion(ajustes: AjustesSmtp) -> None:
        """Prueba conectar y autenticar con `ajustes` (sin enviar ningun correo). Cualquier
        falla se re-lanza como ValueError con un mensaje que el usuario pueda accionar --
        el texto crudo de smtplib ("(535, b'5.7.8 Username and Password not accepted...")
        no le dice que hacer."""
        if not ajustes.configurado:
            raise ValueError("Ingrese el usuario y la contraseña para probar la conexión.")
        try:
            probar_conexion(ajustes)
        except smtplib.SMTPAuthenticationError as e:
            raise ValueError(
                "El servidor rechazó el usuario o la contraseña. Con Gmail hay que usar una "
                "contraseña de aplicación de 16 caracteres, no la clave normal de la cuenta."
            ) from e
        except (smtplib.SMTPServerDisconnected, ssl.SSLError) as e:
            raise ValueError(
                "El servidor cerró la conexión. Revise el puerto y la opción TLS: "
                "587 con TLS (STARTTLS), 465 usa SSL directo, 25 normalmente sin TLS."
            ) from e
        except smtplib.SMTPConnectError as e:
            raise ValueError(_MENSAJE_SIN_CONEXION.format(host=ajustes.host, puerto=ajustes.puerto)) from e
        # SMTPException hereda de OSError: tiene que ir ANTES del except OSError de abajo,
        # si no cualquier error SMTP caeria en el mensaje de "sin conexion".
        except smtplib.SMTPException as e:
            raise ValueError(f"Error del servidor de correo: {e}") from e
        except (socket.gaierror, TimeoutError, ConnectionError, OSError) as e:
            raise ValueError(_MENSAJE_SIN_CONEXION.format(host=ajustes.host, puerto=ajustes.puerto)) from e
