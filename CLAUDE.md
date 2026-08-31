# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Sistema de gestión (clientes, inventario, ventas, compras, tesorería) for a distributor.
See `docs/ESTADO_DEL_PROYECTO.md` for the authoritative, up-to-date account of what's
implemented, what design decisions were made and why, and what's still pending — read it
before making non-trivial backend changes.

**Stack**: Python 3.11+, SQLAlchemy 2.0 (`Mapped`/`mapped_column` style) as the ORM,
SQL Server as the database (via `pyodbc`, requires ODBC Driver 18 for SQL Server
installed on the OS — not a pip package), `bcrypt` for password hashing, PySide6 for
the desktop UI (not a web app — there is no HTTP API layer), `python-dotenv` for
`.env` config loading. SQL Server itself runs in Docker for local dev/test
(`docker-compose.yml`); the app and test suite run natively against it.

## Commands

Full environment setup (Docker DB, schema, venv) is documented in `README.md` — follow
it for first-time setup rather than re-deriving the steps here.

```bash
# Run the app (module form required — imports are absolute, `python app/main.py` breaks them)
python -m app.main

# Run the full test suite (needs the SQL Server container up: docker compose up -d)
pytest

# Run one file / one test
pytest tests/services/test_ventas.py
pytest tests/services/test_ventas.py::test_emitir_factura_credito_abre_cuenta_por_cobrar

# Install dev deps (adds pytest on top of requirements.txt)
pip install -r requirements-dev.txt

# Apply pending schema migrations (migrations/*.sql) to the configured database
python -m app.db.migrar
```

Tests run against a **real, dedicated SQL Server database** (`distribuidora_dj_test` by
default, override with `TEST_DB_NAME`), not mocks or SQLite — this is required because a
large share of the business logic lives in database triggers (see below) and can't be
exercised any other way. `tests/conftest.py` creates that database and applies
`schema_sqlserver.sql` to it on first run.

Lint/format: `ruff` (config in `pyproject.toml`), installed via `requirements-dev.txt`,
enforced in CI (`.github/workflows/tests.yml`).

```bash
ruff check .            # lint
ruff format .           # format in place
ruff format --check .   # verify only, no changes (what CI runs)
```

`pyrightconfig.json` exists for editor type-checking only, there's no `pyright` CLI
step in the test/build flow.

## Git

**Never run `git commit` or `git push` unless the user explicitly asks for it in that
message.** Finishing a task, the user saying "sí"/"dale"/"continua" to something else, or
tests passing are not implicit requests to commit — wait for an explicit instruction
each time.

## Architecture

**Layering**: `schema_sqlserver.sql` (DB + triggers) → `app/db/models.py` (SQLAlchemy
models) → `app/services/*.py` (one module per business domain, static methods taking a
`Session` as first arg and committing themselves) → `app/ui/*.py` (PySide6, only
login/clientes screens exist so far — most service modules have no UI yet).

**Business logic lives partly in SQL Server triggers, not in Python.** Stock
adjustments, running totals, opening AR/AP accounts on credit sales/purchases, and
applying payments are all done by triggers, not by the service layer. Before changing
`ventas.py`, `compras.py`, `pagos.py`, or `tesoreria.py`, read section 3 of
`docs/ESTADO_DEL_PROYECTO.md` — the trigger behavior imposes non-obvious constraints on
how the Python code must sequence inserts/deletes, e.g.:

- `emitir_factura`/`registrar_compra` insert the header with total = 0 and let the
  trigger fired by inserting the detail lines recalculate it — inserting the header with
  the real total upfront means the "open AR/AP account" trigger never fires (it only
  reacts to the total *changing*).
- `anular_factura`/`anular_compra` delete the detail lines (to trigger stock reversal)
  **before** deleting the associated AR/AP row, never after — deleting the AR/AP row
  first causes the total-recalc trigger to silently recreate it.
- Tables with triggers need `__table_args__ = {"implicit_returning": False}` in
  `models.py` (SQL Server disallows `OUTPUT inserted.*` on tables with triggers).
  `pagos_cobros`/`pagos_proveedores` additionally needed a trailing `SELECT` added to
  their `INSTEAD OF INSERT` triggers for SQLAlchemy to be able to read back the
  generated id at all — see the note in that section for why.

**`schema_sqlserver.sql` builds the schema once, from empty.** Table creation is
idempotent (`IF OBJECT_ID(...) IS NULL`), but triggers and constraints are not — it's
meant to run once against a brand-new database, and self-registers as the
`0000_baseline` row in `dbo.schema_migrations` when it does. Any schema change to an
environment that already has data (new trigger, `ALTER TABLE`, etc.) goes in a new
numbered file under `migrations/` instead of editing `schema_sqlserver.sql` — see
`migrations/README.md`. Apply pending ones with `python -m app.db.migrar`
(`app/db/migrar.py`), which tracks what's applied per environment in
`dbo.schema_migrations`.

**Test isolation** (`tests/conftest.py`): services call `session.commit()` themselves,
so per-test rollback doesn't work. Instead each test gets the same database cleaned by
`DELETE` in a specific order before it runs — that order is *not* just "children before
parents": deleting an AR/AP row before its detail lines can cause the recalc trigger to
recreate it. Follow the existing `TABLES_DELETE_ORDER` reasoning if you add a table.
`tests/factories.py` has one `crear_x()` helper per entity, inserting directly against
the models (not through the service under test).
