"""Fixtures de pytest contra una base de datos SQL Server de prueba real.

No se usa rollback-por-test: los servicios de app/services hacen su propio
session.commit(), así que en su lugar se usa una base de datos dedicada
(TEST_DB_NAME, por defecto "<DB_NAME>_test") que se limpia con DELETE en
orden de dependencia de FKs antes de cada test. Esto permite validar el
comportamiento real de los triggers del schema (schema_sqlserver.sql), que
no se pueden reproducir con SQLite ni con Base.metadata.create_all().

Requiere una instancia de SQL Server accesible (ver docker-compose.yml) y
las mismas variables de entorno que usa la app (.env), más opcionalmente
TEST_DB_NAME para no chocar con la base de datos real
"""

import os
import re
import time
import urllib.parse
from pathlib import Path

import pyodbc
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import (
    DB_DRIVER,
    DB_PASSWORD,
    DB_SERVER,
    DB_TRUST_SERVER_CERTIFICATE,
    DB_TRUSTED_CONNECTION,
    DB_USER,
)
from app.db.migrar import aplicar_migraciones

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema_sqlserver.sql"
# Con pytest-xdist cada worker (gw0, gw1, ...) usa SU propia base: comparten el servidor pero no las tablas, asi que
# los tests de un worker no borran los datos de otro. Las bases se crean la primera vez y se reutilizan despues.
_WORKER_XDIST = os.getenv("PYTEST_XDIST_WORKER")
if _WORKER_XDIST:
    # Varios workers abren ventanas a la vez: con la plataforma real se pelean el foco (y fallan tests como los de
    # `hasFocus`). Sin pantalla real cada proceso tiene su propio foco.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TEST_DB_NAME = os.getenv("TEST_DB_NAME", "distribuidora_dj_test") + (f"_{_WORKER_XDIST}" if _WORKER_XDIST else "")

# Orden de borrado. No basta con "hijas antes que padres": trg_factura_total_del /
# trg_compra_total_del recalculan total_venta/total_compra al borrar una linea de
# detalle, lo que dispara trg_factura_venta_cxc / trg_compras_cxp — si la cuenta por
# cobrar/pagar ya fue borrada en ese momento, el trigger la vuelve a crear porque su
# condicion es "NOT EXISTS". Por eso las lineas de detalle se borran ANTES que las
# cuentas por cobrar/pagar, no despues.
# Ademas, el schema tiene un ciclo real de FKs (usuarios.id_vendedor_usuario ->
# vendedores, vendedores.creado_por -> usuarios) que ningun orden lineal resuelve;
# por eso el fixture db_session deshabilita todas las FK (NOCHECK CONSTRAINT ALL)
# antes de borrar y las reactiva (CHECK CONSTRAINT ALL) despues.
TABLES_DELETE_ORDER = [
    "cola_correos",
    "clave_cifrado_servidor",
    "auditoria_cambios_db",
    "licencia_estaciones",
    "licencia_sistema",
    "comisiones_factura",
    "pagos_comisiones",
    "caja_movimientos",
    "banco_movimientos",
    "pagos_cobros_bcv",
    "conciliaciones_partida",
    "cuentas_por_pagar_otros",
    "cuentas_por_cobrar_otros",
    "aplicaciones_nota_credito_cliente",
    "aplicaciones_nota_credito_proveedor",
    "notas_credito_clientes",
    "notas_credito_proveedores",
    "pagos_cobros",
    "pagos_proveedores",
    "nota_devolucion_detalle",
    "nota_devolucion",
    "nota_recepcion_detalle",
    "nota_recepcion",
    "compra_oc_enmienda",
    "compra_oc_detalle",
    "compra_oc",
    "factura_detalle",
    "compra_detalle",
    "cuentas_por_cobrar_bcv",
    "cuentas_por_cobrar",
    "cuentas_por_pagar",
    "factura_venta",
    "compras",
    "producto_precios",
    "inventario",
    "cuentas_bancarias",
    "bancos",
    "cajas",
    "auditoria",
    "configuracion_empresa",
    "configuracion_smtp",
    "clientes",
    "proveedores",
    "vendedores",
    "rutas",
    "categorias",
    "categorias_cliente",
    "control_de_tasas",
    "rol_permisos",
    "permisos",
    "codigos_verificacion",
    "usuarios",
    "roles",
]


def matar_sesiones_y_borrar_login(cur, login: str, intentos: int = 20, pausa: float = 0.5) -> None:
    """Borra un login de prueba aunque le queden sesiones abiertas (p. ej. en el pool de ODBC).

    KILL es asincrono: la sesion sigue listada en sys.dm_exec_sessions un instante (estado KILLED/rollback) y
    un DROP LOGIN inmediato falla con "Could not drop login ... as the user is currently logged in" -- era el
    error de teardown, intermitente en CI. Por eso se repite: matar, esperar a que ya no quede ninguna sesion y
    solo entonces borrar, reintentando si entre medias el pool abrio otra."""
    ultimo_error: Exception | None = None
    for _ in range(intentos):
        sesiones = [
            r[0] for r in cur.execute("SELECT session_id FROM sys.dm_exec_sessions WHERE login_name = ?", login)
        ]
        for id_sesion in sesiones:
            try:
                cur.execute(f"KILL {int(id_sesion)}")
            except pyodbc.Error:
                pass  # la sesion ya murio entre el SELECT y el KILL: es lo que se queria
        if not sesiones:
            try:
                cur.execute(f"IF SUSER_ID(N'{login}') IS NOT NULL DROP LOGIN [{login}]")
                return
            except pyodbc.Error as error:
                ultimo_error = error
        time.sleep(pausa)
    raise AssertionError(f"No se pudo borrar el login de prueba {login!r} tras {intentos} intentos") from ultimo_error


def _odbc_connect_str(database: str) -> str:
    if DB_TRUSTED_CONNECTION.lower() in ("yes", "true", "1"):
        auth_part = "Trusted_Connection=yes;"
    else:
        auth_part = f"UID={DB_USER};PWD={DB_PASSWORD};"
    return (
        f"DRIVER={{{DB_DRIVER}}};"
        f"SERVER={DB_SERVER};"
        f"DATABASE={database};"
        f"{auth_part}"
        f"TrustServerCertificate={DB_TRUST_SERVER_CERTIFICATE};"
        # Como la app: los triggers de auditoria (0092) marcan "fuera de la app" lo que NO venga con
        # este nombre, y la campana avisaria de cada dato que la suite inserta.
        f"APP=NexoERP-Tests;"
    )


def _ensure_test_database_exists() -> None:
    conn = pyodbc.connect(_odbc_connect_str("master"), autocommit=True)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "IF DB_ID(?) IS NULL EXEC('CREATE DATABASE [' + ? + ']')",
            TEST_DB_NAME,
            TEST_DB_NAME,
        )
        # Solo es una base de pruebas: no hace falta esperar el vaciado del log en cada commit ni conservarlo para
        # recuperacion. Los servicios hacen muchos commits pequenos, y con esto cada uno deja de esperar al disco.
        cursor.execute(f"ALTER DATABASE [{TEST_DB_NAME}] SET DELAYED_DURABILITY = FORCED")
        cursor.execute(f"ALTER DATABASE [{TEST_DB_NAME}] SET RECOVERY SIMPLE")
    finally:
        conn.close()


def _run_schema_script() -> None:
    sql_text = SCHEMA_PATH.read_text(encoding="utf-8")
    batches = re.split(r"(?im)^\s*GO\s*$", sql_text)
    conn = pyodbc.connect(_odbc_connect_str(TEST_DB_NAME), autocommit=True)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT OBJECT_ID(N'dbo.usuarios', N'U')")
        # pyrefly: ignore [unsupported-operation]
        ya_existe = cursor.fetchone()[0] is not None
        if ya_existe:
            return
        for batch in batches:
            batch = batch.strip()
            if batch:
                cursor.execute(batch)
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _sin_http_real(monkeypatch):
    """Ningun test debe golpear la red. Un QThread de fondo (HttpWorker de geo_http)
    haciendo urllib.request.urlopen real provoco un segfault dentro de shiboken que
    tumbo un worker de xdist y congelo la suite en CI. Los tests que necesitan simular
    HTTP parchean urlopen ellos mismos (ver tests/ui/test_geo_http.py) -- ese patch
    interno sigue funcionando porque se aplica encima de este."""
    import urllib.request

    def _bloqueado(*_args, **_kwargs):
        raise OSError("Acceso a red deshabilitado durante los tests")

    monkeypatch.setattr(urllib.request, "urlopen", _bloqueado)


@pytest.fixture(autouse=True)
def _llave_del_servidor_en_carpeta_temporal(tmp_path, monkeypatch):
    """Ningun test debe crear ni leer la llave privada real del equipo (app/services/
    cifrado_servidor.py): se redirige a una carpeta temporal por test."""
    monkeypatch.setenv("CLAVE_SERVIDOR_RUTA", str(tmp_path / "clave_servidor.bin"))


@pytest.fixture(scope="session")
def test_engine():
    _ensure_test_database_exists()
    _run_schema_script()
    engine = create_engine(
        "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(_odbc_connect_str(TEST_DB_NAME)),
        fast_executemany=True,
        pool_size=5,
        max_overflow=0,
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    aplicar_migraciones(engine)
    yield engine
    engine.dispose()


_TABLAS_A_LIMPIAR = frozenset(TABLES_DELETE_ORDER)
_DESHABILITAR_FK = ";".join(f"ALTER TABLE dbo.{t} NOCHECK CONSTRAINT ALL" for t in TABLES_DELETE_ORDER)
# Sin "WITH CHECK": con las tablas recien vaciadas no hay nada que revalidar, y revalidar cada FK en cada test
# costaba ~0.6 s. Las FK quedan activas para todo INSERT/UPDATE posterior (solo cambia su marca "no confiable").
_REACTIVAR_FK = ";".join(f"ALTER TABLE dbo.{t} CHECK CONSTRAINT ALL" for t in TABLES_DELETE_ORDER)
_TABLAS_CON_FILAS = text(
    "SELECT t.name FROM sys.tables t "
    "JOIN sys.dm_db_partition_stats p ON p.object_id = t.object_id AND p.index_id IN (0, 1) "
    "WHERE SCHEMA_NAME(t.schema_id) = 'dbo' GROUP BY t.name HAVING SUM(p.row_count) > 0"
)
_PASADAS_MAXIMAS = 3


def _tablas_sucias(connection) -> list[str]:
    """Tablas de TABLES_DELETE_ORDER con filas, en ese mismo orden."""
    con_filas = set(connection.execute(_TABLAS_CON_FILAS).scalars()) & _TABLAS_A_LIMPIAR
    return [t for t in TABLES_DELETE_ORDER if t in con_filas]


def _vaciar_base(connection) -> None:
    """Deja vacias las tablas de TABLES_DELETE_ORDER tocando solo las que tienen filas: un test suele usar ~15 de las
    50, y cada DELETE (con sus triggers) cuesta ~8 ms. Un trigger puede repoblar una tabla ya revisada, asi que se
    vuelve a mirar hasta que no quede ninguna con datos."""
    sucias = _tablas_sucias(connection)
    if not sucias:
        return
    connection.execute(text(_DESHABILITAR_FK))
    for _ in range(_PASADAS_MAXIMAS):
        for tabla in sucias:
            connection.execute(text(f"DELETE FROM dbo.{tabla}"))
        sucias = _tablas_sucias(connection)
        if not sucias:
            break
    connection.execute(text(_REACTIVAR_FK))
    if sucias:
        raise RuntimeError(f"La limpieza de la base de pruebas dejo filas en: {', '.join(sucias)}")


@pytest.fixture()
def db_session(test_engine):
    with test_engine.connect() as connection:
        _vaciar_base(connection)
        connection.commit()

    session_factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    session = session_factory()
    try:
        yield session
    finally:
        try:
            session.rollback()
        except Exception:
            pass
        session.close()


def pytest_collection_modifyitems(items):
    """Marca con `db` los tests que usan la base real: `pytest -m "not db"` corre solo los que no la tocan (rapido)."""
    for item in items:
        if "db_session" in item.fixturenames:
            item.add_marker(pytest.mark.db)
