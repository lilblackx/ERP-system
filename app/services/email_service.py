import smtplib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from email.message import EmailMessage

from app import config


@dataclass(frozen=True)
class AjustesSmtp:
    """Credenciales/servidor con los que se envia un correo. Vienen de la base
    (Configuracion > Correo, ver app/services/smtp_config.py) o, como respaldo, del .env."""

    host: str
    puerto: int
    usuario: str
    password: str
    remitente: str
    usar_tls: bool

    @property
    def configurado(self) -> bool:
        return bool(self.usuario and self.password)


def ajustes_desde_entorno() -> AjustesSmtp:
    return AjustesSmtp(
        host=config.SMTP_HOST,
        puerto=config.SMTP_PORT,
        usuario=config.SMTP_USER,
        password=config.SMTP_PASSWORD,
        remitente=config.SMTP_FROM,
        usar_tls=config.SMTP_USE_TLS,
    )


PUERTO_SSL_DIRECTO = 465


def _autenticar(server: smtplib.SMTP, ajustes: AjustesSmtp) -> None:
    """server.login() con un detalle de Gmail: ante una clave mala responde 535 a AUTH PLAIN
    y luego CIERRA la conexion, justo cuando smtplib reintenta con AUTH LOGIN -- el error que
    llega es SMTPServerDisconnected, no SMTPAuthenticationError. Una desconexion durante el
    login se trata como credenciales rechazadas, que es lo que realmente paso."""
    try:
        server.login(ajustes.usuario, ajustes.password)
    except smtplib.SMTPServerDisconnected as e:
        raise smtplib.SMTPAuthenticationError(535, b"El servidor cerro la conexion al autenticar") from e


@contextmanager
def _conexion_autenticada(ajustes: AjustesSmtp) -> Iterator[smtplib.SMTP]:
    """Abre la conexion y se autentica. El puerto 465 es SSL desde el primer byte
    (SMTP_SSL); el resto arranca en claro y sube a TLS con STARTTLS si `usar_tls`."""
    if ajustes.puerto == PUERTO_SSL_DIRECTO:
        with smtplib.SMTP_SSL(ajustes.host, ajustes.puerto, timeout=10) as server:
            _autenticar(server, ajustes)
            yield server
        return
    with smtplib.SMTP(ajustes.host, ajustes.puerto, timeout=10) as server:
        if ajustes.usar_tls:
            server.starttls()
        _autenticar(server, ajustes)
        yield server


def probar_conexion(ajustes: AjustesSmtp) -> None:
    """Se conecta y autentica contra el servidor sin enviar nada. Lanza la excepcion de
    smtplib/socket correspondiente si algo falla -- ver SmtpConfigService.probar_conexion
    para la version con mensajes pensados para el usuario."""
    with _conexion_autenticada(ajustes):
        pass


def enviar_correo(
    destinatario: str,
    asunto: str,
    cuerpo: str,
    cuerpo_html: str | None = None,
    ajustes: AjustesSmtp | None = None,
) -> None:
    """Unico punto de envio de correo de la app -- los tests monkeypatchean esta funcion
    para no golpear un servidor SMTP real (ver tests/services/test_recuperacion_acceso.py).

    `cuerpo` (texto plano) siempre se manda -- es el fallback que muestran los clientes de
    correo que no renderizan HTML, y es ademas lo unico que la suite de tests inspecciona
    (ver `_extraer_codigo` en test_recuperacion_acceso.py, que parsea la primera linea).
    `cuerpo_html` es opcional: si se pasa, el mensaje se arma como multipart/alternative
    (RFC 2046) con ambas versiones -- el cliente de correo elige la que sepa mostrar.

    `ajustes` es el servidor SMTP a usar; sin el, se usan las variables SMTP_* del .env."""
    if ajustes is None:
        ajustes = ajustes_desde_entorno()
    if not ajustes.configurado:
        raise RuntimeError("SMTP no esta configurado (usuario/clave faltantes en Configuracion > Correo)")

    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = ajustes.remitente or ajustes.usuario
    msg["To"] = destinatario
    msg.set_content(cuerpo)
    if cuerpo_html is not None:
        msg.add_alternative(cuerpo_html, subtype="html")

    with _conexion_autenticada(ajustes) as server:
        server.send_message(msg)
