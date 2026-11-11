import logging

from pyodbc import Error as PyodbcError
from sqlalchemy import create_engine, event
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_database_url
from app.services.db_utils import es_conexion_perdida

logger = logging.getLogger(__name__)

# pool_pre_ping: prueba la conexion antes de usarla y la descarta si esta muerta (turnos
# de caja o sesiones de UI abiertas muchas horas, o cortes de red via AnyDesk -- ver C5).
# pool_recycle=1800: reciclado preventivo cada 30 min, defensa adicional para conexiones
# cortadas silenciosamente por un firewall/NAT intermedio que pre_ping no siempre detecta.
# pool_timeout=30: limite de espera por una conexion libre del pool (igual al default de
# SQLAlchemy, fijado explicito para dejar la intencion documentada).
engine = create_engine(
    get_database_url(),
    fast_executemany=True,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_timeout=30,
)


_ESCRIBIO = "_escribio_en_la_transaccion"


def _es_consulta(statement) -> bool:
    """True si `statement` solo lee (SELECT / WITH ... SELECT); un INSERT/UPDATE/DELETE, un SET o un EXEC no."""
    if getattr(statement, "is_select", False):
        return True
    if getattr(statement, "is_dml", False):
        return False
    texto = str(statement).lstrip().upper()
    return texto.startswith(("SELECT", "WITH"))


class SesionResiliente(Session):
    """Sesion que sobrevive a una conexion cortada mientras solo ha LEIDO.

    Un dialogo o panel mantiene su sesion (y con ella una conexion del pool) abierta mientras el usuario lo tiene en
    pantalla. Si la red o el servidor cierran esa conexion inactiva (10054 / "Communication link failure"), la primera
    consulta del siguiente clic fallaba aunque la base estuviera bien: `pool_pre_ping` solo prueba las conexiones al
    sacarlas del pool, no las que una sesion ya tiene en su poder.

    Si la consulta que falla es una lectura y la transaccion no tiene nada que perder (ninguna escritura ya enviada ni
    cambios pendientes en la sesion), se hace rollback -- que descarta la conexion muerta -- y se repite UNA vez con una
    conexion nueva. Con escrituras de por medio no se repite aqui: la transaccion entera se perdio en el servidor y el
    error sube a quien envuelve la operacion (`reintentar_en_deadlock(..., session=...)`)."""

    def execute(self, statement, *args, **kwargs):
        try:
            resultado = super().execute(statement, *args, **kwargs)
        except (DBAPIError, PyodbcError) as exc:
            if not (es_conexion_perdida(exc) and self._se_puede_repetir(statement)):
                raise
            logger.warning(
                "Conexion con la base perdida durante una lectura: se repite con una conexion nueva (%s)", exc
            )
            self.rollback()
            resultado = super().execute(statement, *args, **kwargs)
        if not _es_consulta(statement):
            self.info[_ESCRIBIO] = True
        return resultado

    def _se_puede_repetir(self, statement) -> bool:
        return (
            _es_consulta(statement)
            and not self.info.get(_ESCRIBIO, False)
            and not (self.new or self.dirty or self.deleted)
        )


@event.listens_for(SesionResiliente, "after_flush")
def _marcar_escritura(session, flush_context) -> None:
    session.info[_ESCRIBIO] = True


@event.listens_for(SesionResiliente, "after_transaction_end")
def _olvidar_escritura(session, transaction) -> None:
    if transaction.parent is None:  # la transaccion raiz termino (commit o rollback): empieza una limpia
        session.info[_ESCRIBIO] = False


SessionLocal = sessionmaker(bind=engine, class_=SesionResiliente, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass
