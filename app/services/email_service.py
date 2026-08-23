import smtplib
from email.message import EmailMessage

from app import config


def enviar_correo(destinatario: str, asunto: str, cuerpo: str) -> None:
    """Unico punto de envio de correo de la app -- los tests monkeypatchean esta funcion
    para no golpear un servidor SMTP real (ver tests/services/test_recuperacion_acceso.py)."""
    if not config.SMTP_USER or not config.SMTP_PASSWORD:
        raise RuntimeError("SMTP no esta configurado (SMTP_USER/SMTP_PASSWORD faltantes en .env)")

    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = config.SMTP_FROM or config.SMTP_USER
    msg["To"] = destinatario
    msg.set_content(cuerpo)

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as server:
        if config.SMTP_USE_TLS:
            server.starttls()
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.send_message(msg)
