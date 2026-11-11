"""Utilidades transversales de acceso a datos -- reintentos ante deadlock de SQL Server y conexion perdida.

SQL Server puede elegir cualquiera de las transacciones en conflicto como "víctima" de un
deadlock y abortarla con el error 1205, incluso cuando el código ya toma los locks en un
orden consistente (ver el comentario sobre sorted() en VentaService.emitir_factura) --
bajo carga concurrente alta, dos transacciones que compiten por filas distintas pero
comparten una página de índice pueden generar un deadlock que ningún orden de acceso a
nivel de aplicación previene. Sin reintento, el cajero ve un error crudo de pyodbc y debe
repetir la operación a mano; reintentar automáticamente 1-2 veces con backoff exponencial
corto resuelve la mayoría de los casos de forma transparente.

La conexion tambien puede perderse (un firewall o la red cierra una conexion inactiva, el servidor se reinicia): el
error llega como 10054 / 08S01 "Communication link failure". Una operacion que falla asi se repite una vez con una
conexion nueva; y quien muestra el error al usuario no debe enseñarle el SQL crudo (ver `mensaje_de_error_bd`).
"""

import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

from pyodbc import Error as PyodbcError
from pyodbc import OperationalError as PyodbcOperationalError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError as SqlAlchemyDBAPIError
from sqlalchemy.exc import OperationalError as SqlAlchemyOperationalError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Código de error de SQL Server para "transaction was deadlocked ... victim".
_SQLSTATE_DEADLOCK = "40001"
_ERROR_DEADLOCK_TEXTO = "deadlock"

# Sin `SET LOCK_TIMEOUT`, el default de SQL Server es -1 (esperar indefinidamente un
# lock). Bajo un UPDLOCK/ROWLOCK sostenido (ej. una sesion de cajero que quedo colgada a
# mitad de una transaccion), una segunda operacion contra la misma fila esperaria para
# siempre en vez de fallar con un error claro -- 30s es suficiente margen para
# contencion normal (otra transaccion terminando su commit) sin dejar al usuario
# esperando indefinidamente frente a una fila realmente trabada.
LOCK_TIMEOUT_MS = 30000
# Error 1222 de SQL Server: "Lock request time out period exceeded."
_ERROR_LOCK_TIMEOUT_TEXTO = "lock request time out period exceeded"


def _es_deadlock(exc: BaseException) -> bool:
    if not isinstance(exc, (SqlAlchemyOperationalError, PyodbcOperationalError)):
        return False
    texto = str(exc).lower()
    return _SQLSTATE_DEADLOCK in texto or _ERROR_DEADLOCK_TEXTO in texto


def _es_lock_timeout(exc: BaseException) -> bool:
    if not isinstance(exc, (SqlAlchemyOperationalError, PyodbcOperationalError)):
        return False
    return _ERROR_LOCK_TIMEOUT_TEXTO in str(exc).lower()


# Marcas de un corte de conexion (no de un error de la consulta): codigos SQLSTATE de "connection exception" y los
# textos del driver/Windows cuando el otro extremo cierra el socket.
_SQLSTATES_CONEXION = ("08S01", "08001", "08003", "08004", "08007", "08S02")
_MARCAS_CONEXION_PERDIDA = (
    "communication link failure",
    "tcp provider",
    "(10054)",
    "(10053)",
    "(10060)",
    "(10061)",
    "forcibly closed",
    "se ha forzado la interrupci",
    "connection is closed",
    "connection reset",
    "server has gone away",
    "login timeout expired",
    "unable to establish connection",
    "no se puede establecer una conexi",
)

MENSAJE_CONEXION_PERDIDA = (
    "Se perdió la conexión con el servidor. Revisa la red e inténtalo de nuevo; si sigue, avisa a soporte."
)
MENSAJE_BD_OCUPADA = "El sistema está ocupado con otra operación. Inténtalo de nuevo en unos segundos."
MENSAJE_BD_GENERICO = (
    "Ocurrió un error al acceder a la base de datos. Inténtalo de nuevo; si continúa, avisa a soporte."
)


def es_conexion_perdida(exc: BaseException) -> bool:
    """True si `exc` es un corte de la conexion con la base (no un error de la consulta). SQLAlchemy ya marca como
    `connection_invalidated` los cortes que detecta el pool; el resto se reconoce por el SQLSTATE o el texto del
    driver."""
    if getattr(exc, "connection_invalidated", False):
        return True
    cadena = exc
    for _ in range(4):  # SQLAlchemy envuelve el error del driver en `.orig`
        if cadena is None:
            break
        if isinstance(cadena, (SqlAlchemyDBAPIError, PyodbcError)):
            texto = str(cadena).lower()
            if any(estado.lower() in texto for estado in _SQLSTATES_CONEXION):
                return True
            if any(marca in texto for marca in _MARCAS_CONEXION_PERDIDA):
                return True
        cadena = getattr(cadena, "orig", None)
    return False


def mensaje_de_error_bd(exc: BaseException) -> str | None:
    """Mensaje para el usuario si `exc` es un error de la base de datos (conexion perdida, bloqueo, deadlock u otro);
    None si no lo es. Nunca incluye el SQL ni el texto del driver: eso queda en el log."""
    if es_conexion_perdida(exc):
        return MENSAJE_CONEXION_PERDIDA
    if _es_deadlock(exc) or _es_lock_timeout(exc):
        return MENSAJE_BD_OCUPADA
    if isinstance(exc, (SqlAlchemyDBAPIError, PyodbcError)):
        return MENSAJE_BD_GENERICO
    return None


# Huellas de un error de base de datos crudo (el texto que un `str(exc)` deja pasar al usuario).
_HUELLAS_ERROR_BD_CRUDO = (
    "pyodbc",
    "[sql:",
    "odbc driver",
    "sqlalche.me",
    "sqlalchemy.exc",
    "(background on this error",
)


def mensaje_de_texto_bd(texto: str) -> str | None:
    """Si `texto` es un error de base de datos crudo (con el SQL o el texto del driver), el mensaje legible que
    corresponde; None si es un mensaje normal. Es la red de seguridad de la interfaz: los avisos se arman con
    `f"No se pudo X: {exc}"` en decenas de sitios y ninguno debe enseñar el SQL (ver `MessageBox`)."""
    bajo = texto.lower()
    if not any(huella in bajo for huella in _HUELLAS_ERROR_BD_CRUDO):
        return None
    if any(marca in bajo for marca in _MARCAS_CONEXION_PERDIDA) or any(e.lower() in bajo for e in _SQLSTATES_CONEXION):
        return MENSAJE_CONEXION_PERDIDA
    if _SQLSTATE_DEADLOCK in bajo or _ERROR_DEADLOCK_TEXTO in bajo or _ERROR_LOCK_TIMEOUT_TEXTO in bajo:
        return MENSAJE_BD_OCUPADA
    return MENSAJE_BD_GENERICO


def aplicar_lock_timeout(session: Session) -> None:
    """Limita a LOCK_TIMEOUT_MS la espera por un lock (UPDLOCK/ROWLOCK) en esta sesion,
    en vez del default de SQL Server de esperar indefinidamente. Llamar al inicio de
    cada operacion de escritura que tome UPDLOCK, antes del primer SELECT ... WITH
    (UPDLOCK, ROWLOCK)."""
    session.execute(text(f"SET LOCK_TIMEOUT {LOCK_TIMEOUT_MS}"))


def reintentar_en_deadlock(func: Callable[[], T], max_intentos: int = 3, session: Session | None = None) -> T:
    """Ejecuta `func` reintentando si SQL Server aborta la transacción por deadlock
    (error 1205 / SQLSTATE 40001), y UNA vez si la conexión se cortó (ver `es_conexion_perdida`). Backoff
    exponencial corto con jitter para no sincronizar reintentos de dos transacciones que volvieron a chocar.
    `func` debe encapsular la operación completa (incluido su propio commit/rollback) -- si la
    sesión quedó en un estado inválido tras el deadlock, el caller es responsable de
    haber hecho rollback antes de que este helper reintente.

    Con una conexion perdida la sesion queda inutilizable hasta un rollback: pasar `session` para que el helper lo haga
    y la repeticion tome una conexion nueva del pool (que la prueba antes de entregarla). Sin `session` no se
    reintenta: repetir sobre una sesion invalida solo fallaria otra vez. La repeticion es segura porque una
    conexion cortada pierde la transaccion entera en el servidor (nada quedo a medias)."""
    ultimo_error: BaseException | None = None
    reconectado = False
    for intento in range(max_intentos):
        try:
            return func()
        except (SqlAlchemyDBAPIError, PyodbcError) as exc:
            if es_conexion_perdida(exc):
                if session is None or reconectado:
                    raise
                reconectado = True
                logger.warning("Conexion con la base perdida (%s): se repite la operacion con una conexion nueva", exc)
                try:
                    session.rollback()
                except Exception:
                    logger.exception("No se pudo hacer rollback tras perder la conexion")
                    raise exc from None
                ultimo_error = exc
                continue
            if not _es_deadlock(exc) or intento == max_intentos - 1:
                raise
            ultimo_error = exc
            espera = (0.1 * (2**intento)) + random.uniform(0, 0.05)
            logger.warning(
                "Deadlock detectado (intento %s/%s), reintentando en %.2fs",
                intento + 1,
                max_intentos,
                espera,
            )
            time.sleep(espera)
    raise ultimo_error  # pragma: no cover -- inalcanzable, el loop siempre retorna o lanza


_ERRORES_TRIGGER_TRADUCCION = {
    "exactamente un origen": "Indique exactamente un método de pago (efectivo, transferencia o cheque)",
    "saldo excedido": "El pago excede el saldo pendiente de la cuenta",
    "saldo pendiente": "El pago excede el saldo pendiente de la cuenta",
    "monto negativo": "El monto debe ser mayor a cero",
    "limite credito": "La compra excede el límite de crédito otorgado al cliente o proveedor",
    "cantidad minima": "La venta dejaría el stock por debajo de la cantidad mínima configurada",
    "cantidad negativa": "La cantidad debe ser mayor a cero",
    "producto inactivo": "No se puede vender/comprar productos inactivos",
    "cliente inactivo": "No se puede facturar a clientes inactivos",
    "proveedor inactivo": "No se puede comprar a proveedores inactivos",
}


def traducir_error_trigger(exc: Exception) -> str:
    """Traduce mensajes de error crudos de triggers SQL Server a mensajes amigables
    para el usuario. Si no hay coincidencia, retorna un mensaje genérico."""
    texto = str(exc).lower()
    for clave, traduccion in _ERRORES_TRIGGER_TRADUCCION.items():
        if clave in texto:
            return traduccion
    return f"Error en la operación: {str(exc)}"
