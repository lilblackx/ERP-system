"""Migracion 0078 (pagos_cobros_bcv) probada contra una base descartable propia.

La base de test normal (distribuidora_dj_test) ya tiene la 0078 aplicada y registrada en
dbo.schema_migrations, asi que no sirve para ejercitar el archivo. Aca se arma otra base
(<TEST_DB_NAME>_mig) con el schema base + migraciones 0001..0077 y se corre el archivo 0078
real sobre ella, volviendo al estado "previo a 0078" entre un test y otro.
"""

import re
import shutil
import urllib.parse

import pyodbc
import pytest
from sqlalchemy import create_engine, text

from app.db.migrar import MIGRATIONS_DIR, _ejecutar_batches, aplicar_migraciones
from tests.conftest import SCHEMA_PATH, TEST_DB_NAME, _odbc_connect_str

MIG_DB_NAME = f"{TEST_DB_NAME}_mig"
ARCHIVO_0078 = MIGRATIONS_DIR / "0078_pagos_cobros_bcv.sql"


def _recrear_base_descartable() -> None:
    conn = pyodbc.connect(_odbc_connect_str("master"), autocommit=True)
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"IF DB_ID(N'{MIG_DB_NAME}') IS NOT NULL BEGIN "
            f"ALTER DATABASE [{MIG_DB_NAME}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
            f"DROP DATABASE [{MIG_DB_NAME}]; END"
        )
        cursor.execute(f"CREATE DATABASE [{MIG_DB_NAME}]")
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
def engine_pre_0078(tmp_path_factory):
    """Base con schema base + migraciones 0001..0077 (todo lo anterior a 0078)."""
    _recrear_base_descartable()
    _aplicar_schema_base()

    previas = tmp_path_factory.mktemp("migraciones_previas")
    for archivo in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if archivo.name < ARCHIVO_0078.name:
            shutil.copy(archivo, previas / archivo.name)

    engine = create_engine("mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(_odbc_connect_str(MIG_DB_NAME)))
    aplicar_migraciones(engine, migrations_dir=previas)
    yield engine
    engine.dispose()
    conn = pyodbc.connect(_odbc_connect_str("master"), autocommit=True)
    try:
        conn.cursor().execute(
            f"IF DB_ID(N'{MIG_DB_NAME}') IS NOT NULL BEGIN "
            f"ALTER DATABASE [{MIG_DB_NAME}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
            f"DROP DATABASE [{MIG_DB_NAME}]; END"
        )
    finally:
        conn.close()


def _ejecutar(engine, sql: str) -> None:
    with engine.connect() as connection:
        _ejecutar_batches(connection, sql)
        connection.commit()


def _aplicar_0078(engine) -> None:
    _ejecutar(engine, ARCHIVO_0078.read_text(encoding="utf-8"))


_VOLVER_A_PRE_0078 = """
IF EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_banco_movimientos_pago_cobro_bcv')
    ALTER TABLE dbo.banco_movimientos DROP CONSTRAINT FK_banco_movimientos_pago_cobro_bcv;
GO
IF EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_caja_movimientos_pago_cobro_bcv')
    ALTER TABLE dbo.caja_movimientos DROP CONSTRAINT FK_caja_movimientos_pago_cobro_bcv;
GO
IF COL_LENGTH('dbo.banco_movimientos', 'id_pago_cobro_bcv') IS NOT NULL
    ALTER TABLE dbo.banco_movimientos DROP COLUMN id_pago_cobro_bcv;
GO
IF COL_LENGTH('dbo.caja_movimientos', 'id_pago_cobro_bcv') IS NOT NULL
    ALTER TABLE dbo.caja_movimientos DROP COLUMN id_pago_cobro_bcv;
GO
IF OBJECT_ID(N'dbo.pagos_cobros_bcv', N'U') IS NOT NULL
    DROP TABLE dbo.pagos_cobros_bcv;
GO
"""


@pytest.fixture()
def base_pre_0078(engine_pre_0078):
    _ejecutar(engine_pre_0078, _VOLVER_A_PRE_0078)
    yield engine_pre_0078


def _scalar(engine, sql: str, **params):
    with engine.connect() as connection:
        return connection.execute(text(sql), params).scalar()


def _columnas(engine, tabla: str) -> dict[str, tuple]:
    with engine.connect() as connection:
        filas = connection.execute(
            text(
                "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = :t"
            ),
            {"t": tabla},
        ).fetchall()
    return {fila[0]: (fila[1], fila[2]) for fila in filas}


def _fks(engine, tabla: str) -> set[tuple[str, str]]:
    """(nombre de la FK, tabla referenciada) de las FKs que salen de `tabla`."""
    with engine.connect() as connection:
        filas = connection.execute(
            text(
                "SELECT fk.name, OBJECT_NAME(fk.referenced_object_id) FROM sys.foreign_keys fk "
                "WHERE fk.parent_object_id = OBJECT_ID(:t)"
            ),
            {"t": f"dbo.{tabla}"},
        ).fetchall()
    return {(fila[0], fila[1]) for fila in filas}


def _checks(engine, tabla: str) -> set[str]:
    with engine.connect() as connection:
        filas = connection.execute(
            text("SELECT name FROM sys.check_constraints WHERE parent_object_id = OBJECT_ID(:t)"),
            {"t": f"dbo.{tabla}"},
        ).fetchall()
    return {fila[0] for fila in filas}


def test_aplicada_sobre_base_sin_0078_crea_tabla_columnas_y_constraints(base_pre_0078):
    assert _scalar(base_pre_0078, "SELECT OBJECT_ID(N'dbo.pagos_cobros_bcv', N'U')") is None

    _aplicar_0078(base_pre_0078)

    columnas = _columnas(base_pre_0078, "pagos_cobros_bcv")
    assert columnas["id_pago_cobro_bcv"] == ("bigint", "NO")
    assert columnas["id_cuenta_por_cobrar"] == ("bigint", "NO")
    assert columnas["monto"] == ("decimal", "NO")
    assert columnas["monto_bolivares"] == ("decimal", "YES")
    assert columnas["tasa_cambio"] == ("decimal", "YES")
    assert columnas["id_caja"] == ("bigint", "YES")
    assert columnas["id_cuenta_bancaria"] == ("bigint", "YES")

    assert _fks(base_pre_0078, "pagos_cobros_bcv") == {
        ("FK_pagos_cobros_bcv_cuenta", "cuentas_por_cobrar_bcv"),
        ("FK_pagos_cobros_bcv_cuenta_bancaria", "cuentas_bancarias"),
        ("FK_pagos_cobros_bcv_caja", "cajas"),
        ("FK_pagos_cobros_bcv_tasa", "control_de_tasas"),
        ("FK_pagos_cobros_bcv_creado_por", "usuarios"),
    }
    assert _checks(base_pre_0078, "pagos_cobros_bcv") == {
        "CK_pagos_cobros_bcv_metodo",
        "CK_pagos_cobros_bcv_monto",
        "CK_pagos_cobros_bcv_origen",
    }

    for tabla in ("banco_movimientos", "caja_movimientos"):
        assert _columnas(base_pre_0078, tabla)["id_pago_cobro_bcv"] == ("bigint", "YES")
    assert ("FK_banco_movimientos_pago_cobro_bcv", "pagos_cobros_bcv") in _fks(base_pre_0078, "banco_movimientos")
    assert ("FK_caja_movimientos_pago_cobro_bcv", "pagos_cobros_bcv") in _fks(base_pre_0078, "caja_movimientos")


def test_aplicada_sobre_base_sin_0078_no_toca_cuentas_por_cobrar_bcv(base_pre_0078):
    """La parte de la 0078 que corrige INT -> BIGINT solo debe actuar si hay INT: sobre una
    base que ya paso por la 0073 no debe tocar la tabla (tipos, FKs ni indices)."""
    antes = (
        _columnas(base_pre_0078, "cuentas_por_cobrar_bcv"),
        _fks(base_pre_0078, "cuentas_por_cobrar_bcv"),
    )
    indices_antes = _scalar(
        base_pre_0078,
        "SELECT COUNT(*) FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.cuentas_por_cobrar_bcv')",
    )

    _aplicar_0078(base_pre_0078)

    assert (
        _columnas(base_pre_0078, "cuentas_por_cobrar_bcv"),
        _fks(base_pre_0078, "cuentas_por_cobrar_bcv"),
    ) == antes
    assert (
        _scalar(
            base_pre_0078,
            "SELECT COUNT(*) FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.cuentas_por_cobrar_bcv')",
        )
        == indices_antes
    )


_BAJAR_CUENTAS_BCV_A_INT = """
ALTER TABLE dbo.cuentas_por_cobrar_bcv DROP CONSTRAINT FK_cuentas_por_cobrar_bcv_factura;
GO
ALTER TABLE dbo.cuentas_por_cobrar_bcv DROP CONSTRAINT FK_cuentas_por_cobrar_bcv_usuario;
GO
DROP INDEX IX_cuentas_por_cobrar_bcv_factura ON dbo.cuentas_por_cobrar_bcv;
GO
DROP INDEX IX_cuentas_por_cobrar_bcv_estado ON dbo.cuentas_por_cobrar_bcv;
GO
DROP INDEX IX_cuentas_por_cobrar_bcv_vencimiento ON dbo.cuentas_por_cobrar_bcv;
GO
DECLARE @pk SYSNAME = (SELECT name FROM sys.key_constraints
    WHERE parent_object_id = OBJECT_ID('dbo.cuentas_por_cobrar_bcv') AND type = 'PK');
DECLARE @sql NVARCHAR(400) = N'ALTER TABLE dbo.cuentas_por_cobrar_bcv DROP CONSTRAINT [' + @pk + N']';
EXEC (@sql);
GO
ALTER TABLE dbo.cuentas_por_cobrar_bcv ALTER COLUMN id_cuenta_por_cobrar INT NOT NULL;
GO
ALTER TABLE dbo.cuentas_por_cobrar_bcv ADD PRIMARY KEY (id_cuenta_por_cobrar);
GO
ALTER TABLE dbo.cuentas_por_cobrar_bcv ALTER COLUMN id_factura INT NOT NULL;
GO
ALTER TABLE dbo.cuentas_por_cobrar_bcv ALTER COLUMN creado_por INT NOT NULL;
GO
"""


ARCHIVO_0073 = MIGRATIONS_DIR / "0073_corregir_tipos_datos_cuentas_por_cobrar_bcv.sql"


def _verificar_cuentas_bcv_en_bigint_con_fks_e_indices(engine) -> None:
    columnas = _columnas(engine, "cuentas_por_cobrar_bcv")
    assert columnas["id_cuenta_por_cobrar"][0] == "bigint"
    assert columnas["id_factura"][0] == "bigint"
    assert columnas["creado_por"][0] == "bigint"
    assert _fks(engine, "cuentas_por_cobrar_bcv") >= {
        ("FK_cuentas_por_cobrar_bcv_factura", "factura_venta"),
        ("FK_cuentas_por_cobrar_bcv_usuario", "usuarios"),
    }
    with engine.connect() as connection:
        indices = {
            fila[0]
            for fila in connection.execute(
                text("SELECT name FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.cuentas_por_cobrar_bcv')")
            )
        }
    assert {
        "IX_cuentas_por_cobrar_bcv_factura",
        "IX_cuentas_por_cobrar_bcv_estado",
        "IX_cuentas_por_cobrar_bcv_vencimiento",
    } <= indices


def test_la_0073_corrige_int_a_bigint_aunque_la_pk_no_tenga_el_nombre_esperado(base_pre_0078):
    """La PK de cuentas_por_cobrar_bcv se creo sin nombre en la 0071, asi que SQL Server le puso uno
    generado. La 0073 la borraba por un nombre fijo que no existe: el DROP fallaba sin que el
    runner se enterara y la tabla quedaba en INT con la migracion marcada como aplicada."""
    _ejecutar(base_pre_0078, _BAJAR_CUENTAS_BCV_A_INT)
    assert _columnas(base_pre_0078, "cuentas_por_cobrar_bcv")["id_cuenta_por_cobrar"][0] == "int"

    _ejecutar(base_pre_0078, ARCHIVO_0073.read_text(encoding="utf-8"))

    _verificar_cuentas_bcv_en_bigint_con_fks_e_indices(base_pre_0078)


def test_la_0073_sobre_una_base_ya_en_bigint_no_hace_nada(base_pre_0078):
    antes = (_columnas(base_pre_0078, "cuentas_por_cobrar_bcv"), _fks(base_pre_0078, "cuentas_por_cobrar_bcv"))

    _ejecutar(base_pre_0078, ARCHIVO_0073.read_text(encoding="utf-8"))

    assert (_columnas(base_pre_0078, "cuentas_por_cobrar_bcv"), _fks(base_pre_0078, "cuentas_por_cobrar_bcv")) == antes


def test_si_cuentas_bcv_tiene_int_la_0078_lo_corrige_a_bigint_y_recrea_fks_e_indices(base_pre_0078):
    """Base que quedo con INT (la 0073 fallo en silencio y se registro igual): antes de crear
    pagos_cobros_bcv la 0078 debe dejar la tabla en BIGINT con sus FKs e indices, y crear la
    tabla de pagos sin error de tipos."""
    _ejecutar(base_pre_0078, _BAJAR_CUENTAS_BCV_A_INT)
    assert _columnas(base_pre_0078, "cuentas_por_cobrar_bcv")["id_cuenta_por_cobrar"][0] == "int"

    _aplicar_0078(base_pre_0078)

    _verificar_cuentas_bcv_en_bigint_con_fks_e_indices(base_pre_0078)
    assert _scalar(base_pre_0078, "SELECT OBJECT_ID(N'dbo.pagos_cobros_bcv', N'U')") is not None


def test_0078_repara_el_estado_intermedio_que_dejo_la_0073_fallida(base_pre_0078):
    """Estado real de las bases afectadas: id_cuenta_por_cobrar sigue en INT, pero id_factura y
    creado_por ya estan en BIGINT y las FKs/indices volvieron a crearse."""
    _ejecutar(base_pre_0078, _BAJAR_CUENTAS_BCV_A_INT)
    _ejecutar(
        base_pre_0078,
        """
        ALTER TABLE dbo.cuentas_por_cobrar_bcv ALTER COLUMN id_factura BIGINT NOT NULL;
        GO
        ALTER TABLE dbo.cuentas_por_cobrar_bcv ALTER COLUMN creado_por BIGINT NOT NULL;
        GO
        ALTER TABLE dbo.cuentas_por_cobrar_bcv ADD CONSTRAINT FK_cuentas_por_cobrar_bcv_factura
            FOREIGN KEY (id_factura) REFERENCES dbo.factura_venta(id_factura);
        GO
        CREATE INDEX IX_cuentas_por_cobrar_bcv_factura ON dbo.cuentas_por_cobrar_bcv(id_factura);
        GO
        """,
    )

    _aplicar_0078(base_pre_0078)

    _verificar_cuentas_bcv_en_bigint_con_fks_e_indices(base_pre_0078)
    assert _scalar(base_pre_0078, "SELECT OBJECT_ID(N'dbo.pagos_cobros_bcv', N'U')") is not None


def test_si_la_0078_fallo_a_medias_y_se_reaplica_termina_bien(base_pre_0078):
    """Estado de una corrida anterior que fallo despues de crear la tabla pero antes de las
    columnas en banco/caja: reaplicar debe converger al mismo schema final."""
    _aplicar_0078(base_pre_0078)
    _ejecutar(
        base_pre_0078,
        """
        ALTER TABLE dbo.caja_movimientos DROP CONSTRAINT FK_caja_movimientos_pago_cobro_bcv;
        GO
        ALTER TABLE dbo.caja_movimientos DROP COLUMN id_pago_cobro_bcv;
        GO
        """,
    )

    _aplicar_0078(base_pre_0078)

    assert _columnas(base_pre_0078, "caja_movimientos")["id_pago_cobro_bcv"] == ("bigint", "YES")
    assert ("FK_caja_movimientos_pago_cobro_bcv", "pagos_cobros_bcv") in _fks(base_pre_0078, "caja_movimientos")


def test_reaplicar_la_0078_no_borra_pagos_ya_registrados(base_pre_0078):
    """Correr el archivo otra vez (a mano, o un entorno cuyo schema_migrations no tiene la
    fila) no debe destruir los cobros BCV ya registrados ni el vinculo de sus movimientos."""
    _aplicar_0078(base_pre_0078)
    _ejecutar(
        base_pre_0078,
        """
        EXEC sp_msforeachtable 'ALTER TABLE ? NOCHECK CONSTRAINT ALL';
        GO
        INSERT INTO dbo.pagos_cobros_bcv (id_cuenta_por_cobrar, id_caja, metodo_pago, monto)
        VALUES (1, 1, 'efectivo', 25.00);
        GO
        """,
    )
    assert _scalar(base_pre_0078, "SELECT COUNT(*) FROM dbo.pagos_cobros_bcv") == 1

    _aplicar_0078(base_pre_0078)

    assert _scalar(base_pre_0078, "SELECT COUNT(*) FROM dbo.pagos_cobros_bcv") == 1
