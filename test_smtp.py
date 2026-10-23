"""Script de prueba para verificar la conexión SMTP y envío de correos.

Las credenciales se leen del .env (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM,
SMTP_USE_TLS, ver app/config.py) -- nunca se escriben en este archivo: esta en git."""

import smtplib
from email.message import EmailMessage

from app.config import SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USE_TLS, SMTP_USER


def probar_smtp():
    """Prueba la conexión SMTP y envío de correo."""
    print(f"Conectando a {SMTP_HOST}:{SMTP_PORT}...")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            print("[OK] Conexion establecida")

            if SMTP_USE_TLS:
                server.starttls()
                print("[OK] TLS activado")

            print(f"Autenticando como {SMTP_USER}...")
            server.login(SMTP_USER, SMTP_PASSWORD)
            print("[OK] Autenticacion exitosa")

            # Enviar correo de prueba
            destinatario = SMTP_USER  # Enviar a uno mismo para probar
            msg = EmailMessage()
            msg["Subject"] = "Prueba SMTP - ERP System"
            msg["From"] = SMTP_FROM
            msg["To"] = destinatario
            msg.set_content("Este es un correo de prueba del sistema ERP.")

            server.send_message(msg)
            print(f"[OK] Correo enviado a {destinatario}")
            print("\n[OK] SMTP funcionando correctamente")

    except smtplib.SMTPAuthenticationError as e:
        print(f"[ERROR] Error de autenticacion: {e}")
        print("  Verifica que SMTP_USER y SMTP_PASSWORD sean correctos")
        print("  Para Gmail, usa una App Password de 16 caracteres (no la clave normal)")
    except smtplib.SMTPException as e:
        print(f"[ERROR] Error SMTP: {e}")
    except Exception as e:
        print(f"[ERROR] Error: {e}")


if __name__ == "__main__":
    probar_smtp()
