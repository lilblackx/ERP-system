from sqlalchemy import text

from app.db.migrar import aplicar_migraciones


def _limpiar_schema_migrations(test_engine) -> None:
    with test_engine.connect() as connection:
        connection.execute(
            text("IF OBJECT_ID(N'dbo.schema_migrations', N'U') IS NOT NULL DROP TABLE dbo.schema_migrations")
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
