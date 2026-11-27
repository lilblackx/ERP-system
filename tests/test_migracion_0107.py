"""Migracion 0107 (correlativos de todos los documentos) probada como la vivira produccion: una base sin la 0104, con
numeros que ya saltaron de bloque, a la que se le aplican de una vez todas las migraciones pendientes (lo mismo que
hace el instalador al actualizar).

Igual que test_migracion_0102.py: la base de test normal ya esta al dia, asi que se arma otra (<TEST_DB_NAME>_mig107).
"""

import re
import shutil
import urllib.parse

import pyodbc
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.migrar import MIGRATIONS_DIR, _ejecutar_batches, aplicar_migraciones
from app.services.correlativos import siguiente_numero
from tests.conftest import SCHEMA_PATH, TEST_DB_NAME, _odbc_connect_str

MIG_DB_NAME = f"{TEST_DB_NAME}_mig107"
PRIMERA_PENDIENTE = "0104"

# (correlativo, tabla, columna, numero heredado mas alto, ultimo numero que debe quedar)
DOCUMENTOS = [
    ("factura_venta", "factura_venta", "numero_factura", "FV-040006", 40006),
    ("nota_credito_cliente", "notas_credito_clientes", "numero_nota_credito", "NC-010002", 10002),
    ("compra", "compras", "numero_compra", "OC-020003", 20003),
    ("orden_compra", "compra_oc", "numero_oc", "ODC-030001", 30001),
    ("enmienda_oc", "compra_oc_enmienda", "numero_enmienda", "ENM-000007", 7),
    ("nota_recepcion", "nota_recepcion", "numero_nr", "NR-010005", 10005),
    ("nota_devolucion", "nota_devolucion", "numero_nota_devolucion", "ND-000003", 3),
]


def _borrar_base_descartable() -> None:
    conn = pyodbc.connect(_odbc_connect_str("master"), autocommit=True)
    try:
        conn.cursor().execute(
            f"IF DB_ID(N'{MIG_DB_NAME}') IS NOT NULL BEGIN "
            f"ALTER DATABASE [{MIG_DB_NAME}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
            f"DROP DATABASE [{MIG_DB_NAME}]; END"
        )
    finally:
        conn.close()


def _sentencia_insert(cursor, tabla: str, columna: str, numero: str) -> str:
    """INSERT minimo: el numero del documento y un valor cualquiera en cada columna obligatoria sin valor por
    defecto (las claves foraneas van desactivadas al sembrar: aqui solo importa el numero)."""
    filas = cursor.execute(
        "SELECT c.name, t.name FROM sys.columns c JOIN sys.types t ON t.user_type_id = c.user_type_id "
        "WHERE c.object_id = OBJECT_ID(?) AND c.is_nullable = 0 AND c.is_identity = 0 AND c.is_computed = 0 "
        "AND c.default_object_id = 0 AND c.name <> ?",
        f"dbo.{tabla}",
        columna,
    ).fetchall()
    textos = {"varchar", "nvarchar", "char", "nchar"}
    fechas = {"date", "datetime", "datetime2"}
    columnas, valores = [columna], [f"'{numero}'"]
    if tabla == "factura_venta":
        filas = [f for f in filas if f[0] != "numero_control"]
        columnas.append("numero_control")
        valores.append("'00-" + numero[3:].zfill(8) + "'")
    for nombre, tipo in filas:
        columnas.append(nombre)
        valores.append("'x'" if tipo in textos else "GETDATE()" if tipo in fechas else "1")
    return f"INSERT INTO dbo.{tabla} ({', '.join(columnas)}) VALUES ({', '.join(valores)})"


def _sembrar_documentos_heredados() -> None:
    conn = pyodbc.connect(_odbc_connect_str(MIG_DB_NAME), autocommit=True)
    try:
        cursor = conn.cursor()
        for _, tabla, columna, numero, _ in DOCUMENTOS:
            cursor.execute(f"ALTER TABLE dbo.{tabla} NOCHECK CONSTRAINT ALL")
            cursor.execute(f"DISABLE TRIGGER ALL ON dbo.{tabla}")
            # Los CHECK con lista de valores no aceptan el relleno generico: se quitan en esta base descartable.
            for (check,) in cursor.execute(
                "SELECT name FROM sys.check_constraints WHERE parent_object_id = OBJECT_ID(?)", f"dbo.{tabla}"
            ).fetchall():
                cursor.execute(f"ALTER TABLE dbo.{tabla} DROP CONSTRAINT [{check}]")
            cursor.execute(_sentencia_insert(cursor, tabla, columna, numero))
            cursor.execute(f"ENABLE TRIGGER ALL ON dbo.{tabla}")
    finally:
        conn.close()


@pytest.fixture(scope="module")
def engine_actualizado(tmp_path_factory):
    _borrar_base_descartable()
    conn = pyodbc.connect(_odbc_connect_str("master"), autocommit=True)
    try:
        conn.cursor().execute(f"CREATE DATABASE [{MIG_DB_NAME}]")
    finally:
        conn.close()
    conn = pyodbc.connect(_odbc_connect_str(MIG_DB_NAME), autocommit=True)
    try:
        cursor = conn.cursor()
        for batch in re.split(r"(?im)^\s*GO\s*$", SCHEMA_PATH.read_text(encoding="utf-8")):
            if batch.strip():
                cursor.execute(batch.strip())
    finally:
        conn.close()

    previas = tmp_path_factory.mktemp("migraciones_previas_0104")
    for archivo in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if archivo.name < PRIMERA_PENDIENTE:
            shutil.copy(archivo, previas / archivo.name)
    engine = create_engine("mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(_odbc_connect_str(MIG_DB_NAME)))
    aplicar_migraciones(engine, migrations_dir=previas)
    _sembrar_documentos_heredados()

    aplicar_migraciones(engine)  # lo que hace el instalador al actualizar
    yield engine
    engine.dispose()
    _borrar_base_descartable()


@pytest.mark.parametrize(("correlativo", "ultimo"), [(d[0], d[4]) for d in DOCUMENTOS], ids=[d[0] for d in DOCUMENTOS])
def test_cada_correlativo_continua_desde_el_numero_mas_alto_ya_emitido(engine_actualizado, correlativo, ultimo):
    with Session(engine_actualizado) as session:
        assert siguiente_numero(session, correlativo) == ultimo + 1
        session.rollback()
        # Revertido: el numero no se quemo.
        assert siguiente_numero(session, correlativo) == ultimo + 1
        session.rollback()


@pytest.mark.parametrize(("correlativo", "tabla", "columna", "heredado", "ultimo"), DOCUMENTOS, ids=lambda v: str(v))
def test_la_base_rechaza_un_numero_que_no_salio_del_correlativo(
    engine_actualizado, correlativo, tabla, columna, heredado, ultimo
):
    """Una estacion con la version anterior numera por su cuenta (por IDENTITY o MAX(id)+1): si la base aceptara ese
    numero, el correlativo chocaria despues contra el y la emision quedaria bloqueada."""
    prefijo = heredado.split("-")[0]
    ajeno = f"{prefijo}-{ultimo + 1:06d}"

    with engine_actualizado.connect() as connection:
        with pytest.raises(DBAPIError, match="correlativo"):
            connection.execute(text(f"UPDATE dbo.{tabla} SET {columna} = :n"), {"n": ajeno})
        connection.rollback()
        assert connection.execute(text(f"SELECT {columna} FROM dbo.{tabla}")).scalar() == heredado


@pytest.mark.parametrize(("correlativo", "tabla", "columna", "heredado", "ultimo"), DOCUMENTOS, ids=lambda v: str(v))
def test_la_base_acepta_el_numero_que_entrega_el_correlativo_y_no_estorba_otros_cambios(
    engine_actualizado, correlativo, tabla, columna, heredado, ultimo
):
    prefijo = heredado.split("-")[0]
    with Session(engine_actualizado) as session:
        # Reescribir el mismo numero (documentos heredados) no se rechaza.
        session.execute(text(f"UPDATE dbo.{tabla} SET {columna} = {columna}"))
        numero = siguiente_numero(session, correlativo)
        session.execute(text(f"UPDATE dbo.{tabla} SET {columna} = :n"), {"n": f"{prefijo}-{numero:06d}"})
        session.rollback()


def test_el_usuario_de_la_app_no_puede_borrar_los_correlativos(engine_actualizado):
    with engine_actualizado.connect() as connection:
        negado = connection.execute(
            text(
                "SELECT COUNT(*) FROM sys.database_permissions p "
                "WHERE p.major_id = OBJECT_ID(N'dbo.correlativos') AND p.permission_name = 'DELETE' "
                "AND p.state_desc = 'DENY' "
                "AND p.grantee_principal_id = DATABASE_PRINCIPAL_ID(N'nexo_app_sin_borrado')"
            )
        ).scalar()
    assert negado == 1


def test_volver_a_correr_la_migracion_no_baja_ningun_correlativo(engine_actualizado):
    archivo = next(MIGRATIONS_DIR.glob("0107_*.sql"))
    with engine_actualizado.connect() as connection:
        connection.execute(text("UPDATE dbo.correlativos SET ultimo_numero = 99999 WHERE nombre = 'compra'"))
        connection.commit()
        _ejecutar_batches(connection, archivo.read_text(encoding="utf-8"))
        connection.commit()
        ultimo = connection.execute(text("SELECT ultimo_numero FROM dbo.correlativos WHERE nombre = 'compra'")).scalar()
    assert ultimo == 99999
