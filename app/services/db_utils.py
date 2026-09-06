"""Utilidades transversales de acceso a datos -- reintentos ante deadlock de SQL Server.

SQL Server puede elegir cualquiera de las transacciones en conflicto como "víctima" de un
deadlock y abortarla con el error 1205, incluso cuando el código ya toma los locks en un
orden consistente (ver el comentario sobre sorted() en VentaService.emitir_factura) --
bajo carga concurrente alta, dos transacciones que compiten por filas distintas pero
comparten una página de índice pueden generar un deadlock que ningún orden de acceso a
nivel de aplicación previene. Sin reintento, el cajero ve un error crudo de pyodbc y debe
repetir la operación a mano; reintentar automáticamente 1-2 veces con backoff exponencial
corto resuelve la mayoría de los casos de forma transparente.
"""

import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

from pyodbc import OperationalError as PyodbcOperationalError
from sqlalchemy import text
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


def aplicar_lock_timeout(session: Session) -> None:
    """Limita a LOCK_TIMEOUT_MS la espera por un lock (UPDLOCK/ROWLOCK) en esta sesion,
    en vez del default de SQL Server de esperar indefinidamente. Llamar al inicio de
    cada operacion de escritura que tome UPDLOCK, antes del primer SELECT ... WITH
    (UPDLOCK, ROWLOCK)."""
    session.execute(text(f"SET LOCK_TIMEOUT {LOCK_TIMEOUT_MS}"))


def reintentar_en_deadlock(func: Callable[[], T], max_intentos: int = 3) -> T:
    """Ejecuta `func` reintentando si SQL Server aborta la transacción por deadlock
    (error 1205 / SQLSTATE 40001). Backoff exponencial corto con jitter para no
    sincronizar reintentos de dos transacciones que volvieron a chocar. `func` debe
    encapsular la operación completa (incluido su propio commit/rollback) -- si la
    sesión quedó en un estado inválido tras el deadlock, el caller es responsable de
    haber hecho rollback antes de que este helper reintente."""
    ultimo_error: BaseException | None = None
    for intento in range(max_intentos):
        try:
            return func()
        except (SqlAlchemyOperationalError, PyodbcOperationalError) as exc:
            if not _es_deadlock(exc) or intento == max_intentos - 1:
                raise
            ultimo_error = exc
            espera = (0.1 * (2**intento)) + random.uniform(0, 0.05)
            logger.warning(
                "Deadlock detectado (intento %s/%s), reintentando en %.2fs", intento + 1, max_intentos, espera
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
