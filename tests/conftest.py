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
TEST_DB_NAME = os.getenv("TEST_DB_NAME", "distribuidora_dj_test")

# Orden de borrado. No basta con "hijas antes que padres": trg_factura_total_del /
# trg_compra_total_del recalculan total_venta/total_compra al borrar una linea de
# detalle, lo que dispara trg_factura_venta_cxc / trg_compras_cxp — si la cuenta por
# cobrar/pagar ya fue borrada en ese momento, el trigger la vuelve a crear porque su
# condicion es "NOT EXISTS". Por eso las lineas de detalle se borran ANTES que las
# cuentas por cobrar/pagar, no despues.
# Ademas, el schema tiene un ciclo real de FKs (usuarios.id_vendedor_usuario ->
# vendedores, vendedores.creado_por -> usuarios) que ningun orden lineal resuelve;
# por eso el fixture db_session deshabilita todas las FK (NOCHECK CONSTRAINT ALL)
# antes de borrar y las reactiva (WITH CHECK CHECK CONSTRAINT ALL) despues.
TABLES_DELETE_ORDER = [
    "comisiones_factura",
    "caja_movimientos",
    "banco_movimientos",
    "cuentas_por_pagar_otros",
    "cuentas_por_cobrar_otros",
    "notas_credito_clientes",
    "notas_credito_proveedores",
    "pagos_cobros",
    "pagos_proveedores",
    "factura_detalle",
    "compra_detalle",
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
    "clientes",
    "proveedores",
    "vendedores",
    "categorias",
    "categorias_cliente",
    "control_de_tasas",
    "rol_permisos",
    "permisos",
    "codigos_verificacion",
    "usuarios",
    "roles",
]


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


@pytest.fixture(scope="session")
def test_engine():
    _ensure_test_database_exists()
    _run_schema_script()
    engine = create_engine(
        "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(_odbc_connect_str(TEST_DB_NAME)),
        fast_executemany=True,
    )
    aplicar_migraciones(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(test_engine):
    with test_engine.connect() as connection:
        connection.execute(text("EXEC sp_msforeachtable 'ALTER TABLE ? NOCHECK CONSTRAINT ALL'"))
        for tabla in TABLES_DELETE_ORDER:
            connection.execute(text(f"DELETE FROM dbo.{tabla}"))
        connection.execute(text("EXEC sp_msforeachtable 'ALTER TABLE ? WITH CHECK CHECK CONSTRAINT ALL'"))
        connection.commit()

    session_factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
