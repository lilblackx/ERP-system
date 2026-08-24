import pytest
from sqlalchemy import text

from app.db.migrar import _CREATE_SCHEMA_MIGRATIONS, aplicar_migraciones, verificar_migraciones_al_dia


def _limpiar_schema_migrations(test_engine) -> None:
    with test_engine.connect() as connection:
        connection.execute(
            text("IF OBJECT_ID(N'dbo.schema_migrations', N'U') IS NOT NULL DROP TABLE dbo.schema_migrations")
        )
        connection.commit()


@pytest.fixture(autouse=True)
def _preservar_schema_migrations_real(test_engine):
    """Estos tests dropean/recrean dbo.schema_migrations contra la base de datos de test
    REAL (test_engine es la misma base que usa db_session, no una copia aislada) para
    poder probar el bootstrap de aplicar_migraciones(). Sin este fixture, correr esta
    suite borra el registro de que las migraciones reales de migrations/ (por ejemplo
    0001_reversion_automatica_pagos.sql) ya se aplicaron -- los objetos SQL siguen
    existiendo, pero migrar.py los cree pendientes de nuevo y falla con "already exists"
    en la siguiente corrida. Bug real encontrado el 2026-08-22 corriendo la suite
    completa entre dos migraciones nuevas. Este fixture guarda el contenido real antes de
    cada test de este archivo y lo restaura despues, sin importar que haga el test."""
    with test_engine.connect() as connection:
        existe = connection.execute(text("SELECT OBJECT_ID(N'dbo.schema_migrations', N'U')")).scalar()
        filas_previas = []
        if existe is not None:
            filas_previas = connection.execute(
                text("SELECT [version], [aplicada_en] FROM dbo.schema_migrations")
            ).fetchall()

    yield

    with test_engine.connect() as connection:
        connection.execute(
            text("IF OBJECT_ID(N'dbo.schema_migrations', N'U') IS NOT NULL DROP TABLE dbo.schema_migrations")
        )
        connection.execute(text(_CREATE_SCHEMA_MIGRATIONS))
        for version, aplicada_en in filas_previas:
            connection.execute(
                text("INSERT INTO dbo.schema_migrations ([version], [aplicada_en]) VALUES (:v, :a)"),
                {"v": version, "a": aplicada_en},
            )
        connection.commit()


def test_bootstrap_crea_tabla_y_registra_baseline(test_engine, tmp_path):
    _limpiar_schema_migrations(test_engine)

    aplicar_migraciones(motor=test_engine, migrations_dir=tmp_path)

    with test_engine.connect() as connection:
        version = connection.execute(text("SELECT [version] FROM dbo.schema_migrations")).scalar()
    assert version == "0000_baseline"


def test_correr_dos_veces_sin_migraciones_nuevas_es_idempotente(test_engine, tmp_path):
    _limpiar_schema_migrations(test_engine)

    aplicar_migraciones(motor=test_engine, migrations_dir=tmp_path)
    aplicar_migraciones(motor=test_engine, migrations_dir=tmp_path)

    with test_engine.connect() as connection:
        versiones = [fila[0] for fila in connection.execute(text("SELECT [version] FROM dbo.schema_migrations"))]
    assert versiones == ["0000_baseline"]


def test_aplica_migracion_pendiente_y_no_la_repite(test_engine, tmp_path):
    _limpiar_schema_migrations(test_engine)
    (tmp_path / "0001_tabla_de_prueba.sql").write_text(
        "CREATE TABLE dbo.zz_migracion_prueba ([id] INT NOT NULL PRIMARY KEY);\nGO\n",
        encoding="utf-8",
    )

    try:
        aplicar_migraciones(motor=test_engine, migrations_dir=tmp_path)

        with test_engine.connect() as connection:
            versiones = {fila[0] for fila in connection.execute(text("SELECT [version] FROM dbo.schema_migrations"))}
            assert versiones == {"0000_baseline", "0001_tabla_de_prueba.sql"}
            existe = connection.execute(text("SELECT OBJECT_ID(N'dbo.zz_migracion_prueba', N'U')")).scalar()
            assert existe is not None

        # Segunda corrida: no debe volver a ejecutar el archivo ya aplicado. Como el
        # CREATE TABLE de la migracion no tiene guardia IF NOT EXISTS, repetirlo fallaria
        # porque la tabla ya existe -- que esto no explote confirma que se saltea.
        aplicar_migraciones(motor=test_engine, migrations_dir=tmp_path)
    finally:
        with test_engine.connect() as connection:
            connection.execute(
                text("IF OBJECT_ID(N'dbo.zz_migracion_prueba', N'U') IS NOT NULL DROP TABLE dbo.zz_migracion_prueba")
            )
            connection.commit()


# --- verificar_migraciones_al_dia (C25) ---------------------------------------------
# Solo lee, no aplica ni crea nada -- por eso estos tests no necesitan el try/finally de
# limpieza de dbo.zz_migracion_prueba que usa el de arriba.


def test_verificar_migraciones_al_dia_sin_pendientes_no_lanza(test_engine, tmp_path):
    _limpiar_schema_migrations(test_engine)

    verificar_migraciones_al_dia(motor=test_engine, migrations_dir=tmp_path)  # no debe lanzar


def test_verificar_migraciones_al_dia_con_pendiente_lanza(test_engine, tmp_path):
    _limpiar_schema_migrations(test_engine)
    (tmp_path / "0001_pendiente_de_prueba.sql").write_text("SELECT 1;\nGO\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="0001_pendiente_de_prueba.sql"):
        verificar_migraciones_al_dia(motor=test_engine, migrations_dir=tmp_path)


def test_aplica_migracion_con_alter_database_fuera_de_transaccion(test_engine, tmp_path):
    """ALTER DATABASE no puede correr dentro de una transaccion abierta (Msg 226 de SQL
    Server) -- la conexion normal del runner esta en modo manual-commit (autobegin de
    SQLAlchemy), asi que sin la ruta autocommit de _ejecutar_batches este archivo fallaria.
    AUTO_UPDATE_STATISTICS ON es idempotente (ya es el default), se usa solo para probar el
    enrutamiento sin dejar la base de test en un estado distinto al que ya tenia."""
    _limpiar_schema_migrations(test_engine)
    (tmp_path / "0001_alter_database_de_prueba.sql").write_text(
        "ALTER DATABASE CURRENT SET AUTO_UPDATE_STATISTICS ON;\nGO\n",
        encoding="utf-8",
    )

    aplicar_migraciones(motor=test_engine, migrations_dir=tmp_path)

    with test_engine.connect() as connection:
        versiones = {fila[0] for fila in connection.execute(text("SELECT [version] FROM dbo.schema_migrations"))}
    assert versiones == {"0000_baseline", "0001_alter_database_de_prueba.sql"}


def test_verificar_migraciones_al_dia_no_modifica_nada(test_engine, tmp_path):
    """A diferencia de aplicar_migraciones(), esta funcion no debe crear
    dbo.schema_migrations ni escribir la fila 0000_baseline -- es de solo lectura."""
    _limpiar_schema_migrations(test_engine)

    verificar_migraciones_al_dia(motor=test_engine, migrations_dir=tmp_path)

    with test_engine.connect() as connection:
        existe = connection.execute(text("SELECT OBJECT_ID(N'dbo.schema_migrations', N'U')")).scalar()
    assert existe is None
