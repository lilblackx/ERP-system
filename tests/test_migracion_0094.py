"""Migracion 0094 (estandarizar_codigos_de_cliente) probada contra una base descartable propia.

La 0094 MODIFICA datos de produccion (lleva codigo_cliente al formato CLI-000123), asi que se prueba
contra datos "sucios" realistas y, sobre todo, que cuando algo sale mal no deja NADA a medias: todo o nada.

Igual que test_migracion_0078.py: la base de test normal ya tiene la 0094 aplicada y registrada,
asi que se arma otra (<TEST_DB_NAME>_mig94) con el schema base + migraciones 0001..0093 y se corre
el archivo real sobre ella, volviendo al estado "previo a 0094" entre un test y otro.
"""

import re
import shutil
import urllib.parse
from decimal import Decimal

import pyodbc
import pytest
from sqlalchemy import create_engine, text

from app.db.migrar import MIGRATIONS_DIR, _ejecutar_batches, aplicar_migraciones
from tests.conftest import SCHEMA_PATH, TEST_DB_NAME, _odbc_connect_str

MIG_DB_NAME = f"{TEST_DB_NAME}_mig94"
ARCHIVO_0094 = MIGRATIONS_DIR / "0094_estandarizar_codigos_de_cliente.sql"


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


def _recrear_base_descartable() -> None:
    _borrar_base_descartable()
    conn = pyodbc.connect(_odbc_connect_str("master"), autocommit=True)
    try:
        conn.cursor().execute(f"CREATE DATABASE [{MIG_DB_NAME}]")
    finally:
        conn.close()


def _aplicar_schema_base() -> None:
    batches = re.split(r"(?im)^\s*GO\s*$", SCHEMA_PATH.read_text(encoding="utf-8"))
    conn = pyodbc.connect(_odbc_connect_str(MIG_DB_NAME), autocommit=True)
    try:
        cursor = conn.cursor()
        for batch in batches:
            batch = batch.strip()
            if batch:
                cursor.execute(batch)
    finally:
        conn.close()


@pytest.fixture(scope="module")
def engine_pre_0094(tmp_path_factory):
    """Base con schema base + migraciones 0001..0093 (todo lo anterior a 0094)."""
    _recrear_base_descartable()
    _aplicar_schema_base()

    previas = tmp_path_factory.mktemp("migraciones_previas_0094")
    for archivo in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if archivo.name < ARCHIVO_0094.name:
            shutil.copy(archivo, previas / archivo.name)

    engine = create_engine("mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(_odbc_connect_str(MIG_DB_NAME)))
    aplicar_migraciones(engine, migrations_dir=previas)
    yield engine
    engine.dispose()
    _borrar_base_descartable()


def _ejecutar(engine, sql: str) -> None:
    with engine.connect() as connection:
        _ejecutar_batches(connection, sql)
        connection.commit()


def _aplicar_0094(engine) -> None:
    _ejecutar(engine, ARCHIVO_0094.read_text(encoding="utf-8"))


# Vuelve al estado de la 0093: sin historial, DEFAULT numerico, secuencia en 1, sin clientes.
_VOLVER_A_PRE_0094 = """
DELETE FROM dbo.clientes;
GO
IF OBJECT_ID(N'dbo.clientes_codigo_anterior', N'U') IS NOT NULL DROP TABLE dbo.clientes_codigo_anterior;
GO
IF OBJECT_ID(N'dbo.trg_prueba_ensuciar_codigo', N'TR') IS NOT NULL DROP TRIGGER dbo.trg_prueba_ensuciar_codigo;
GO
IF OBJECT_ID(N'DF_clientes_codigo_cliente', N'D') IS NOT NULL
    ALTER TABLE dbo.clientes DROP CONSTRAINT DF_clientes_codigo_cliente;
GO
IF OBJECT_ID(N'dbo.seq_codigo_cliente', N'SO') IS NULL
    CREATE SEQUENCE dbo.seq_codigo_cliente AS BIGINT START WITH 1 INCREMENT BY 1 NO CYCLE NO CACHE;
GO
ALTER TABLE dbo.clientes ADD CONSTRAINT DF_clientes_codigo_cliente
    DEFAULT (CAST(NEXT VALUE FOR dbo.seq_codigo_cliente AS VARCHAR(20))) FOR [codigo_cliente];
GO
ALTER SEQUENCE dbo.seq_codigo_cliente RESTART WITH 1;
GO
"""


@pytest.fixture()
def base_pre_0094(engine_pre_0094):
    _ejecutar(engine_pre_0094, _VOLVER_A_PRE_0094)
    yield engine_pre_0094
    _ejecutar(engine_pre_0094, _VOLVER_A_PRE_0094)


def _insertar(engine, codigos: list[str | None]) -> None:
    """Un cliente por codigo, en orden (id_cliente creciente). NULL explicito = sin codigo."""
    with engine.begin() as connection:
        for i, codigo in enumerate(codigos):
            connection.execute(
                text(
                    "INSERT INTO dbo.clientes (nombre_razon_social, codigo_cliente, identificacion_cliente) "
                    "VALUES (:n, :c, :i)"
                ),
                {"n": f"Cliente {i}", "c": codigo, "i": f"ID-{i}"},
            )


def _codigos(engine) -> list[str | None]:
    with engine.connect() as connection:
        return [r[0] for r in connection.execute(text("SELECT codigo_cliente FROM dbo.clientes ORDER BY id_cliente"))]


def _ids(engine) -> list[int]:
    with engine.connect() as connection:
        return [r[0] for r in connection.execute(text("SELECT id_cliente FROM dbo.clientes ORDER BY id_cliente"))]


def _historial(engine) -> list[tuple]:
    with engine.connect() as connection:
        if connection.execute(text("SELECT OBJECT_ID(N'dbo.clientes_codigo_anterior', N'U')")).scalar() is None:
            return []
        return [
            tuple(r)
            for r in connection.execute(
                text("SELECT id_cliente, codigo_anterior, codigo_nuevo FROM dbo.clientes_codigo_anterior ORDER BY 1")
            )
        ]


def _siguiente_de_la_secuencia(engine) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text("SELECT NEXT VALUE FOR dbo.seq_codigo_cliente")).scalar())


def _alta_sin_codigo(engine) -> str:
    """Da de alta un cliente SIN codigo (como hace la app): lo asigna el DEFAULT de la columna."""
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO dbo.clientes (nombre_razon_social, identificacion_cliente) VALUES ('Nuevo', 'ID-NUEVO')")
        )
        return connection.execute(
            text("SELECT codigo_cliente FROM dbo.clientes WHERE identificacion_cliente='ID-NUEVO'")
        ).scalar()


def test_conserva_el_numero_de_cada_codigo_y_renumera_el_resto(base_pre_0094):
    # Por orden de creacion (id 1..10): texto con numero, numero suelto, NULL, vacio, texto sin numero,
    # numero con ceros, numero de 19 digitos (demasiado largo), con espacio, y dos que caen en el mismo numero (5).
    _insertar(
        base_pre_0094,
        ["CLI-001", "57", None, "", "ABC-9", "00012", "1234567890123456789", " 7", "CLI-5", "5"],
    )

    _aplicar_0094(base_pre_0094)

    # Conservan su numero: CLI-001->1, 57, 00012->12, y de los dos "5" gana el mas antiguo (id 9).
    # El resto sigue a partir del mayor numero conservado (57), en orden de creacion: ids 3,4,5,7,8,10.
    assert _codigos(base_pre_0094) == [
        "CLI-000001",
        "CLI-000057",
        "CLI-000058",
        "CLI-000059",
        "CLI-000060",
        "CLI-000012",
        "CLI-000061",
        "CLI-000062",
        "CLI-000005",
        "CLI-000063",
    ]
    # Cada cliente cuyo codigo cambio deja su codigo anterior registrado.
    ids = _ids(base_pre_0094)
    assert _historial(base_pre_0094) == [
        (ids[0], "CLI-001", "CLI-000001"),
        (ids[1], "57", "CLI-000057"),
        (ids[2], None, "CLI-000058"),
        (ids[3], "", "CLI-000059"),
        (ids[4], "ABC-9", "CLI-000060"),
        (ids[5], "00012", "CLI-000012"),
        (ids[6], "1234567890123456789", "CLI-000061"),
        (ids[7], " 7", "CLI-000062"),
        (ids[8], "CLI-5", "CLI-000005"),
        (ids[9], "5", "CLI-000063"),
    ]
    # El proximo cliente nuevo (via DEFAULT) sigue en el mismo formato, sin huecos ni choques.
    assert _alta_sin_codigo(base_pre_0094) == "CLI-000064"


def test_el_numero_ya_estandar_gana_al_repetido_aunque_sea_mas_nuevo(base_pre_0094):
    _insertar(base_pre_0094, ["5", "CLI-000005"])

    _aplicar_0094(base_pre_0094)

    # El id 2 ya estaba en formato estandar: se queda; el id 1 ("5") pasa a numero nuevo.
    assert _codigos(base_pre_0094) == ["CLI-000006", "CLI-000005"]
    assert _historial(base_pre_0094) == [(_ids(base_pre_0094)[0], "5", "CLI-000006")]


def test_todos_los_codigos_quedan_en_formato_estandar_y_unicos(base_pre_0094):
    _insertar(base_pre_0094, [f"CLI-{i:03d}" for i in range(1, 41)])

    _aplicar_0094(base_pre_0094)

    codigos = _codigos(base_pre_0094)
    assert all(re.fullmatch(r"CLI-\d{6}", c) for c in codigos)
    assert len(set(codigos)) == len(codigos) == 40
    assert codigos == [f"CLI-{i:06d}" for i in range(1, 41)]  # cada cliente conserva su numero


def test_si_ya_estaba_todo_en_formato_estandar_no_cambia_nada(base_pre_0094):
    _insertar(base_pre_0094, ["CLI-000003", "CLI-000010", "CLI-000007"])

    _aplicar_0094(base_pre_0094)

    assert _codigos(base_pre_0094) == ["CLI-000003", "CLI-000010", "CLI-000007"]
    assert _historial(base_pre_0094) == []
    assert _alta_sin_codigo(base_pre_0094) == "CLI-000011"


def test_sin_clientes_no_falla_y_el_primero_es_cli_000001(base_pre_0094):
    _aplicar_0094(base_pre_0094)

    assert _codigos(base_pre_0094) == []
    assert _alta_sin_codigo(base_pre_0094) == "CLI-000001"


def test_con_mas_de_seis_digitos_el_numero_simplemente_crece(base_pre_0094):
    _aplicar_0094(base_pre_0094)
    _ejecutar(base_pre_0094, "ALTER SEQUENCE dbo.seq_codigo_cliente RESTART WITH 1234567;")

    assert _alta_sin_codigo(base_pre_0094) == "CLI-1234567"  # sin truncar


def test_no_toca_ningun_otro_dato_del_cliente(base_pre_0094):
    _insertar(base_pre_0094, ["CLI-001"])
    with base_pre_0094.begin() as connection:
        connection.execute(
            text("UPDATE dbo.clientes SET telefono='0414', email='a@b.c', limite_credito=123.45, dias_credito=9")
        )

    _aplicar_0094(base_pre_0094)

    with base_pre_0094.connect() as connection:
        fila = connection.execute(
            text(
                "SELECT nombre_razon_social, identificacion_cliente, telefono, email, limite_credito, dias_credito "
                "FROM dbo.clientes"
            )
        ).one()
    assert tuple(fila) == ("Cliente 0", "ID-0", "0414", "a@b.c", Decimal("123.45"), 9)


def test_sin_la_secuencia_de_la_0093_aborta_sin_tocar_nada(base_pre_0094):
    _insertar(base_pre_0094, ["CLI-001", "5", None])
    # Simula una base a la que NO se le aplico la 0093: sin el DEFAULT ni la secuencia.
    _ejecutar(
        base_pre_0094,
        "ALTER TABLE dbo.clientes DROP CONSTRAINT DF_clientes_codigo_cliente;\n"
        "GO\n"
        "DROP SEQUENCE dbo.seq_codigo_cliente;",
    )

    with pytest.raises(Exception, match="0093"):
        _aplicar_0094(base_pre_0094)

    assert _codigos(base_pre_0094) == ["CLI-001", "5", None]
    assert _historial(base_pre_0094) == []


def test_si_una_verificacion_final_falla_se_revierte_todo(base_pre_0094):
    """Peor caso: el UPDATE sale bien pero algo (aca, un trigger malicioso) deja un codigo con formato
    invalido. Las verificaciones finales deben detectarlo y revertir TODO: clientes, historial,
    secuencia y DEFAULT."""
    _insertar(base_pre_0094, ["CLI-001", "57", None])
    _ejecutar(
        base_pre_0094,
        """
        CREATE TRIGGER dbo.trg_prueba_ensuciar_codigo ON dbo.clientes AFTER UPDATE AS
        BEGIN
            UPDATE c SET c.codigo_cliente = 'SUCIO' FROM dbo.clientes c JOIN inserted i ON i.id_cliente = c.id_cliente
            WHERE i.codigo_cliente = 'CLI-000058';
        END
        """,
    )

    with pytest.raises(Exception, match="formato"):
        _aplicar_0094(base_pre_0094)

    assert _codigos(base_pre_0094) == ["CLI-001", "57", None]  # exactamente como estaban
    assert _historial(base_pre_0094) == []
    assert _siguiente_de_la_secuencia(base_pre_0094) == 1  # la secuencia tampoco se movio
    with base_pre_0094.connect() as connection:
        definicion = connection.execute(
            text("SELECT definition FROM sys.default_constraints WHERE name = N'DF_clientes_codigo_cliente'")
        ).scalar()
    assert "CLI-" not in definicion  # el DEFAULT sigue siendo el de la 0093


def test_aplicada_dos_veces_no_cambia_nada_la_segunda(base_pre_0094):
    _insertar(base_pre_0094, ["CLI-001", "57", None])
    _aplicar_0094(base_pre_0094)
    antes = (_codigos(base_pre_0094), _historial(base_pre_0094))

    # Reaplicar el mismo SQL (el runner nunca lo hace, pero debe ser inocuo): el DEFAULT ya esta en el
    # formato nuevo y todos los codigos ya son estandar.
    _aplicar_0094(base_pre_0094)

    assert (_codigos(base_pre_0094), _historial(base_pre_0094)) == antes
