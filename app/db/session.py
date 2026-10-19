from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_database_url

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
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass
