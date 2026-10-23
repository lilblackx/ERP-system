import base64
import os
import sys
import urllib.parse

from dotenv import load_dotenv

from app.rutas import ARCHIVO_CONFIG, EMPAQUETADA
from app.utils import dpapi

# Desarrollo: .env en la raiz del proyecto. Instalada: config.env en ProgramData, que escribe el
# instalador (conexion a SQL Server, rol SERVIDOR/ESTACION, etc.) -- ningun .env suelto se lee.
load_dotenv(ARCHIVO_CONFIG) if EMPAQUETADA else load_dotenv()

DB_SERVER = os.getenv("DB_SERVER", "localhost,1433")
DB_NAME = os.getenv("DB_NAME", "distribuidora_dj")
DB_USER = os.getenv("DB_USER", "sa")
# Nombre con el que la app se identifica ante SQL Server (APP_NAME()). Los triggers de
# auditoria (migrations/0092) marcan como "fuera de la app" todo cambio a dinero/stock que NO
# venga con este nombre: Excel, SSMS o cualquier programa conectado con la clave de la base.
NOMBRE_APLICACION_SQL = "NexoERP"

# Prefijo del valor protegido con DPAPI de esta maquina en el .env/config.env
# (DB_PASSWORD_DPAPI=dpapi:<base64>): el archivo copiado a otra PC no revela la clave. Se genera con
# `python -m app.proteger_env` (y el instalador lo escribe asi). DB_PASSWORD en claro sigue
# funcionando (desarrollo, docker-compose lo lee del .env).
PREFIJO_DPAPI = "dpapi:"


def desproteger_clave(valor: str) -> str:
    """'dpapi:<base64>' -> clave en claro (solo en la PC que la protegio). Cualquier otro valor se
    devuelve igual. Si DPAPI no puede descifrarla (archivo copiado a otra PC) devuelve '' y
    validar_configuracion() avisa que falta la clave, en vez de mandar basura a SQL Server."""
    if not valor.startswith(PREFIJO_DPAPI):
        return valor
    try:
        return dpapi.desproteger(base64.b64decode(valor[len(PREFIJO_DPAPI) :])).decode("utf-8")
    except Exception:
        return ""


def proteger_clave(clave: str) -> str:
    """Clave en claro -> 'dpapi:<base64>' (solo Windows; en otros sistemas no hay DPAPI y se
    devuelve la clave tal cual para no dejar el archivo ilegible)."""
    if not dpapi.DISPONIBLE:
        return clave
    return PREFIJO_DPAPI + base64.b64encode(dpapi.proteger(clave.encode("utf-8"))).decode("ascii")


DB_PASSWORD = desproteger_clave(os.getenv("DB_PASSWORD_DPAPI", "")) or os.getenv("DB_PASSWORD", "")
DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")
DB_TRUST_SERVER_CERTIFICATE = os.getenv("DB_TRUST_SERVER_CERTIFICATE", "yes")
DB_TRUSTED_CONNECTION = os.getenv("DB_TRUSTED_CONNECTION", "no")

# Envio de codigos de desbloqueo/recuperacion de clave (app/services/email_service.py).
# RESPALDO: lo que se guarda en Configuracion > Correo (tabla configuracion_smtp, ver
# app/services/smtp_config.py) tiene prioridad sobre estas variables.
# Con Gmail/Google Workspace: smtp.gmail.com:587 + App Password de 16 caracteres (no la
# clave normal de la cuenta) -- se genera en la configuracion de seguridad de la cuenta
# de Google, con verificacion en 2 pasos activada.
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = desproteger_clave(os.getenv("SMTP_PASSWORD_DPAPI", "")) or os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "yes").lower() in ("yes", "true", "1")

# Rol de esta instalacion (lo fija el instalador): SERVIDOR (activa y renueva la licencia, aloja
# SQL Server) o ESTACION (se conecta al servidor y solo lee el estado de licencia). Un valor
# desconocido cae a ESTACION, el rol con menos privilegios.
_MODO = os.getenv("MODO_INSTALACION", "SERVIDOR").strip().upper()
MODO_INSTALACION = _MODO if _MODO in ("SERVIDOR", "ESTACION") else "ESTACION"

# Licenciamiento (app/services/licencia.py). La app solo aplica el modo "solo lectura" si
# hay URL del servidor Y clave publica configuradas -- sin ellas (desarrollo, tests) el
# chequeo queda apagado. En un ejecutable empaquetado (sys.frozen) se IGNORA el .env y se
# usan solo los valores horneados en app/licencia_embebida.py (generado por el script de
# empaquetado): si no, borrar o editar el .env bastaria para apagar la proteccion.
if getattr(sys, "frozen", False):
    try:
        from app.licencia_embebida import LICENCIA_PUBLIC_KEY_B64, LICENCIA_URL
    except ImportError:
        LICENCIA_URL, LICENCIA_PUBLIC_KEY_B64 = "", ""
else:
    LICENCIA_URL = os.getenv("LICENCIA_URL", "").rstrip("/")
    LICENCIA_PUBLIC_KEY_B64 = os.getenv("LICENCIA_PUBLIC_KEY", "")


def validar_configuracion() -> None:
    """Falla rapido con un mensaje claro si falta configuracion esencial en .env, en vez
    de dejar que el primer intento de conexion falle mas tarde con un error crudo de
    pyodbc (C23). SMTP no se valida aca a proposito: ya falla con un RuntimeError claro
    en email_service.enviar_correo() recien cuando de verdad hace falta mandar un correo
    (desbloqueo/recuperar clave) -- es una funcionalidad opcional para poder usar el resto
    de la app, forzarla al arrancar rompe el caso de uso normal de instalar sin SMTP
    configurado todavia (ver seccion 10 de docs/ESTADO_DEL_PROYECTO.md)."""
    if DB_TRUSTED_CONNECTION.lower() not in ("yes", "true", "1") and not DB_PASSWORD:
        if os.getenv("DB_PASSWORD_DPAPI"):
            raise RuntimeError(
                "No se pudo descifrar DB_PASSWORD_DPAPI: esta protegida para otra PC. Vuelva a protegerla "
                "en esta (python -m app.proteger_env) o escriba DB_PASSWORD en el .env."
            )
        raise RuntimeError(
            "DB_PASSWORD no esta configurado (o esta vacio) en .env. "
            "Ver README.md, seccion '1. Base de datos (Docker)'."
        )


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
        # Conexion cifrada siempre (el driver 18 ya lo hace por defecto; se deja explicito). La
        # confianza en el certificado la decide DB_TRUST_SERVER_CERTIFICATE: con un certificado
        # propio instalado en las estaciones se puede poner 'no' y evitar un intermediario en la red.
        f"Encrypt=yes;"
        f"TrustServerCertificate={DB_TRUST_SERVER_CERTIFICATE};"
        f"APP={NOMBRE_APLICACION_SQL};"
    )
    return "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(odbc_str)
