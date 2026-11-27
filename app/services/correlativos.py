"""Correlativos transaccionales (migrations/0104 y 0107).

A diferencia de IDENTITY o SEQUENCE, el numero se reserva con un UPDATE dentro de la
MISMA transaccion de la operacion que lo usa: si esa transaccion revierte -- error,
deadlock reintentado, o apagado forzoso de SQL Server a mitad de la emision -- el
incremento se deshace con ella y el numero queda libre. Es la unica forma de numerar
"sin huecos" en SQL Server.
"""

import logging

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.services.db_utils import _es_lock_timeout

logger = logging.getLogger(__name__)

MENSAJE_CORRELATIVO_OCUPADO = (
    "Otra estacion esta registrando un documento y la numeracion no se libero a tiempo. Intente de nuevo."
)


def siguiente_numero(session: Session, nombre: str) -> int:
    """Devuelve el siguiente numero del correlativo `nombre` y lo consume.

    Debe llamarse dentro de la transaccion del llamador (el commit/rollback de esa
    transaccion es lo que garantiza que el numero no se queme si la operacion falla).
    UPDLOCK+HOLDLOCK serializan emisiones concurrentes sobre la misma fila hasta el
    fin de la transaccion.
    """
    try:
        ultimo = session.execute(
            text(
                "UPDATE dbo.correlativos WITH (UPDLOCK, HOLDLOCK) "
                "SET [ultimo_numero] = [ultimo_numero] + 1 "
                "OUTPUT inserted.[ultimo_numero] "
                "WHERE [nombre] = :nombre"
            ),
            {"nombre": nombre},
        ).scalar()
    except DBAPIError as e:
        # Solo la espera agotada se traduce: un deadlock sigue de largo para que reintentar_en_deadlock lo repita.
        if not _es_lock_timeout(e):
            raise
        session.rollback()
        raise ValueError(MENSAJE_CORRELATIVO_OCUPADO) from e
    if ultimo is None:
        raise ValueError(
            f"El correlativo '{nombre}' no existe en dbo.correlativos; "
            "verifica que la migracion correspondiente este aplicada"
        )
    return int(ultimo)
