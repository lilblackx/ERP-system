import os
import urllib.parse

from dotenv import load_dotenv

load_dotenv()

DB_SERVER = os.getenv("DB_SERVER", "localhost,1433")
DB_NAME = os.getenv("DB_NAME", "distribuidora_dj")
DB_USER = os.getenv("DB_USER", "sa")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")
DB_TRUST_SERVER_CERTIFICATE = os.getenv("DB_TRUST_SERVER_CERTIFICATE", "yes")
DB_TRUSTED_CONNECTION = os.getenv("DB_TRUSTED_CONNECTION", "no")

# Envio de codigos de desbloqueo/recuperacion de clave (app/services/email_service.py).
# Con Gmail/Google Workspace: smtp.gmail.com:587 + App Password de 16 caracteres (no la
# clave normal de la cuenta) -- se genera en la configuracion de seguridad de la cuenta
# de Google, con verificacion en 2 pasos activada.
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "yes").lower() in ("yes", "true", "1")


def get_database_url() -> str:
    if DB_TRUSTED_CONNECTION.lower() in ("yes", "true", "1"):
        auth_part = "Trusted_Connection=yes;"
    else:
        auth_part = f"UID={DB_USER};PWD={DB_PASSWORD};"

    odbc_str = (
        f"DRIVER={{{DB_DRIVER}}};"
        f"SERVER={DB_SERVER};"
        f"DATABASE={DB_NAME};"
        f"{auth_part}"
        f"TrustServerCertificate={DB_TRUST_SERVER_CERTIFICATE};"
    )
    return "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(odbc_str)
