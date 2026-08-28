import smtplib
from email.message import EmailMessage

from app import config


def enviar_correo(destinatario: str, asunto: str, cuerpo: str, cuerpo_html: str | None = None) -> None:
    """Unico punto de envio de correo de la app -- los tests monkeypatchean esta funcion
    para no golpear un servidor SMTP real (ver tests/services/test_recuperacion_acceso.py).

    `cuerpo` (texto plano) siempre se manda -- es el fallback que muestran los clientes de
    correo que no renderizan HTML, y es ademas lo unico que la suite de tests inspecciona
    (ver `_extraer_codigo` en test_recuperacion_acceso.py, que parsea la primera linea).
    `cuerpo_html` es opcional: si se pasa, el mensaje se arma como multipart/alternative
    (RFC 2046) con ambas versiones -- el cliente de correo elige la que sepa mostrar."""
    if not config.SMTP_USER or not config.SMTP_PASSWORD:
        raise RuntimeError("SMTP no esta configurado (SMTP_USER/SMTP_PASSWORD faltantes en .env)")

    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = config.SMTP_FROM or config.SMTP_USER
    msg["To"] = destinatario
    msg.set_content(cuerpo)
    if cuerpo_html is not None:
        msg.add_alternative(cuerpo_html, subtype="html")

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as server:
        if config.SMTP_USE_TLS:
            server.starttls()
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.send_message(msg)
