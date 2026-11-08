"""Busqueda por texto: un solo lugar para armar el LIKE de todos los listados.

Antes cada servicio armaba el suyo (`ilike(f"%{texto}%")`) y salian dos problemas:

  * `ilike` de SQLAlchemy en SQL Server se traduce a `lower(columna) LIKE lower(patron)`. Con la colacion por defecto
    (`*_CI_*`, que ya ignora mayusculas) el `lower()` no cambia ninguna coincidencia pero obliga a evaluar la funcion
    sobre CADA fila de cada columna buscada: en una tabla grande es cerca de 1/3 del tiempo de la consulta, y mas en
    columnas largas (el detalle de auditoria). `contiene()` usa `LIKE` directo cuando la base ya es insensible a
    mayusculas y cae a `ilike` si no lo es.
  * Varios listados no escapaban `%` y `_`: buscar "CREAR_CLIENTE" tambien encontraba "CREARXCLIENTE", y buscar "%"
    devolvia todo. `patron_contiene()` los escapa.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

_ESCAPE = "\\"
_COLACION_INSENSIBLE: dict[int, bool] = {}


def escapar_like(texto: str) -> str:
    """Escapa `\\`, `%` y `_`: son comodines de LIKE y deben buscarse literalmente."""
    return texto.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def patron_contiene(texto: str) -> str:
    """Patron LIKE "contiene `texto`" (con sus comodines ya escapados)."""
    return f"%{escapar_like(texto)}%"


def _busqueda_insensible_a_mayusculas(session: Session) -> bool:
    """True si la colacion de la base ya ignora mayusculas/minusculas. Se consulta una vez por motor."""
    motor = session.get_bind()
    clave = id(getattr(motor, "engine", motor))
    if clave not in _COLACION_INSENSIBLE:
        try:
            colacion = session.execute(
                text("SELECT CAST(DATABASEPROPERTYEX(DB_NAME(), 'Collation') AS VARCHAR(128))")
            ).scalar()
            _COLACION_INSENSIBLE[clave] = "_CI_" in (colacion or "").upper()
        except Exception:
            return False  # sin certeza: el camino seguro (y no se cachea)
    return _COLACION_INSENSIBLE[clave]


def contiene(session: Session, columna, patron: str):
    """Condicion "`columna` coincide con `patron`" sin distinguir mayusculas. `patron` ya viene armado y escapado
    (ver `patron_contiene`)."""
    if _busqueda_insensible_a_mayusculas(session):
        return columna.like(patron, escape=_ESCAPE)
    return columna.ilike(patron, escape=_ESCAPE)
