"""Aplica migraciones de schema pendientes (archivos .sql en migrations/) contra la base
configurada en .env. Ver migrations/README.md para la convención.

Uso: python -m app.db.migrar
"""

import re
from pathlib import Path

from sqlalchemy import text

from app.db.session import engine

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"

_CREATE_SCHEMA_MIGRATIONS = """
IF OBJECT_ID(N'dbo.schema_migrations', N'U') IS NULL
BEGIN
CREATE TABLE dbo.schema_migrations (
	[version] VARCHAR(255) NOT NULL,
	[aplicada_en] DATETIME NOT NULL DEFAULT GETDATE(),
	CONSTRAINT PK_schema_migrations PRIMARY KEY ([version])
);
END
"""


def _ejecutar_batches(connection, contenido_sql: str) -> None:
    for batch in re.split(r"(?im)^\s*GO\s*$", contenido_sql):
        batch = batch.strip()
        if batch:
            connection.execute(text(batch))


def aplicar_migraciones(motor=None, migrations_dir: Path | None = None) -> None:
    motor = motor if motor is not None else engine
    migrations_dir = migrations_dir if migrations_dir is not None else MIGRATIONS_DIR

    with motor.connect() as connection:
        existe_schema_base = connection.execute(text("SELECT OBJECT_ID(N'dbo.usuarios', N'U')")).scalar()
        if existe_schema_base is None:
            raise RuntimeError(
                "No se encontro el schema base (dbo.usuarios). Corre schema_sqlserver.sql "
                "primero -- ver README.md, seccion 'Crear la base de datos y el schema'."
            )

        connection.execute(text(_CREATE_SCHEMA_MIGRATIONS))
        connection.commit()

        aplicadas = {fila[0] for fila in connection.execute(text("SELECT [version] FROM dbo.schema_migrations"))}
        if not aplicadas:
            connection.execute(text("INSERT INTO dbo.schema_migrations ([version]) VALUES ('0000_baseline')"))
            connection.commit()
            aplicadas = {"0000_baseline"}

        archivos = sorted(p for p in migrations_dir.glob("*.sql"))
        pendientes = [archivo for archivo in archivos if archivo.name not in aplicadas]

        if not pendientes:
            print("No hay migraciones pendientes.")
            return

        for archivo in pendientes:
            print(f"Aplicando {archivo.name}...")
            _ejecutar_batches(connection, archivo.read_text(encoding="utf-8"))
            connection.execute(
                text("INSERT INTO dbo.schema_migrations ([version]) VALUES (:version)"),
                {"version": archivo.name},
            )
            connection.commit()

        print(f"{len(pendientes)} migracion(es) aplicada(s).")


if __name__ == "__main__":
    aplicar_migraciones()
