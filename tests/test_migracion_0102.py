"""Migracion 0102 (saldo en bolivares solo en las cuentas en bolivares) probada contra una base descartable propia.

La 0102 CORRIGE saldos de produccion (deja en cero el saldo en Bs que las cuentas en dolares acumularon por error) y
reemplaza el trigger de saldos, asi que se prueba en el estado exacto previo: con el trigger viejo una cuenta en dolares
acumula bolivares inventados (se ve aqui mismo, antes de migrar), y despues de la migracion ya no, sin tocar las cuentas
en bolivares ni en pesos.

Igual que test_migracion_0100.py: la base de test normal ya tiene la 0102 aplicada, asi que se arma otra
(<TEST_DB_NAME>_mig102) con el schema base + migraciones anteriores y se corre el archivo real sobre ella.
"""

import json
import re
import shutil
import urllib.parse
from decimal import Decimal

import pyodbc
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.migrar import MIGRATIONS_DIR, _ejecutar_batches, aplicar_migraciones
from app.db.models import AuditoriaCambioDB, BancoMovimiento
from app.services.pagos import PagoService
from tests.conftest import SCHEMA_PATH, TEST_DB_NAME, _odbc_connect_str
from tests.factories import crear_cuenta_bancaria
from tests.services.test_pagos import _crear_cxc

MIG_DB_NAME = f"{TEST_DB_NAME}_mig102"
ARCHIVO_0102 = MIGRATIONS_DIR / "0102_saldo_en_bolivares_solo_en_cuentas_en_bolivares.sql"
ARCHIVO_0098 = MIGRATIONS_DIR / "0098_saldo_en_pesos_de_las_cuentas_cop.sql"


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
def engine_pre_0102(tmp_path_factory):
    """Base con schema base + todas las migraciones anteriores a la 0102 (el trigger de saldos es el de la 0098)."""
    _recrear_base_descartable()
    _aplicar_schema_base()

    previas = tmp_path_factory.mktemp("migraciones_previas_0102")
    for archivo in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if archivo.name < ARCHIVO_0102.name:
            shutil.copy(archivo, previas / archivo.name)

    engine = create_engine("mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(_odbc_connect_str(MIG_DB_NAME)))
    aplicar_migraciones(engine, migrations_dir=previas)
    # El codigo actual (VentaService.emitir_factura, usado por _crear_cxc de
    # tests/services/test_pagos.py) exige piezas creadas por migraciones POSTERIORES
    # a la 0102 bajo prueba: dbo.correlativos (0104), la columna fecha_pago_origen
    # que el ORM inserta en notas_credito_clientes (0105) y la tabla
    # devoluciones_nota_credito (0106). Se aplican aparte para que los escenarios
    # puedan emitir facturas; no interfieren con la 0102.
    with engine.connect() as connection:
        for nombre in (
            "0104_correlativo_de_facturas.sql",
            "0105_fecha_pago_origen_en_notas_credito.sql",
            "0106_devoluciones_nota_credito.sql",
        ):
            _ejecutar_batches(connection, (MIGRATIONS_DIR / nombre).read_text(encoding="utf-8"))
        connection.commit()
    yield engine
    engine.dispose()
    _borrar_base_descartable()


def _ejecutar(engine, sql: str) -> None:
    with engine.connect() as connection:
        _ejecutar_batches(connection, sql)
        connection.commit()


def _trigger_de_la_0098() -> str:
    """Solo el trigger de saldos tal como lo dejo la 0098 (con su DROP previo): el estado "antes de la 0102"."""
    texto = ARCHIVO_0098.read_text(encoding="utf-8")
    return texto[texto.index("IF EXISTS (SELECT 1 FROM sys.triggers WHERE name = 'trg_banco_movimientos_saldo'") :]


@pytest.fixture()
def base_pre_0102(engine_pre_0102):
    _ejecutar(engine_pre_0102, _trigger_de_la_0098())
    yield engine_pre_0102
    _ejecutar(engine_pre_0102, _trigger_de_la_0098())


def _aplicar_0102(engine) -> None:
    _ejecutar(engine, ARCHIVO_0102.read_text(encoding="utf-8"))


def _cobro_por_zelle(session, cuenta, usd="20.00", bs="800.00", tasa="40.00"):
    cxc, admin = _crear_cxc(session, Decimal("1000.00"))
    return PagoService.registrar_pago_cobro(
        session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal(usd),
        metodo_pago="zelle",
        moneda="USD",
        monto_bolivares=Decimal(bs),
        tasa_cambio=Decimal(tasa),
        id_cuenta_bancaria=cuenta.id_cuenta,
        id_usuario=admin.id_usuario,
    )


def _saldos(engine, id_cuenta):
    with engine.connect() as connection:
        fila = connection.execute(
            text(
                "SELECT saldo_total_banco, saldo_total_banco_bs, saldo_total_banco_cop "
                "FROM dbo.cuentas_bancarias WHERE id_cuenta = :c"
            ),
            {"c": id_cuenta},
        ).one()
    return tuple(fila)


def test_antes_de_la_migracion_una_cuenta_en_dolares_acumulaba_bolivares_y_despues_ya_no(base_pre_0102):
    with Session(base_pre_0102) as session:
        cuenta = crear_cuenta_bancaria(session, moneda="USD")
        id_cuenta = cuenta.id_cuenta
        _cobro_por_zelle(session, cuenta)  # $20 con su equivalente de referencia: Bs 800

    # El defecto, con el trigger viejo: dolares Y bolivares inventados (dolares x tasa).
    assert _saldos(base_pre_0102, id_cuenta) == (Decimal("20.00"), Decimal("800.00"), Decimal("0.00"))

    _aplicar_0102(base_pre_0102)

    # Los Bs acumulados por error desaparecen; los dolares, que son el saldo real, no se tocan.
    assert _saldos(base_pre_0102, id_cuenta) == (Decimal("20.00"), Decimal("0.00"), Decimal("0.00"))

    with Session(base_pre_0102) as session:  # y los cobros que vengan ya no los acumulan
        _cobro_por_zelle(session, session.get(type(cuenta), id_cuenta), usd="5.00", bs="200.00")
    assert _saldos(base_pre_0102, id_cuenta) == (Decimal("25.00"), Decimal("0.00"), Decimal("0.00"))


def test_la_migracion_no_toca_las_cuentas_en_bolivares_ni_en_pesos(base_pre_0102):
    with Session(base_pre_0102) as session:
        ves = crear_cuenta_bancaria(session, moneda="VES", saldo_total_banco_bs=Decimal("5000.00"))
        cop = crear_cuenta_bancaria(session, moneda="COP", saldo_total_banco_cop=Decimal("90000.00"))
        ids = (ves.id_cuenta, cop.id_cuenta)

    _aplicar_0102(base_pre_0102)

    assert _saldos(base_pre_0102, ids[0])[1:] == (Decimal("5000.00"), Decimal("0.00"))
    assert _saldos(base_pre_0102, ids[1])[1:] == (Decimal("0.00"), Decimal("90000.00"))


def test_las_cuentas_en_bolivares_y_en_pesos_siguen_acumulando_su_saldo_local(base_pre_0102):
    _aplicar_0102(base_pre_0102)
    with Session(base_pre_0102) as session:
        ves = crear_cuenta_bancaria(session, moneda="VES")
        cop = crear_cuenta_bancaria(session, moneda="COP")
        for cuenta, local in ((ves, "400.00"), (cop, "40000.00")):
            session.add(
                BancoMovimiento(
                    id_cuenta=cuenta.id_cuenta,
                    tipo_movimiento="abono",
                    monto_movimiento=Decimal("10.00"),
                    monto_bolivares=Decimal(local),
                )
            )
        session.commit()
        ids = (ves.id_cuenta, cop.id_cuenta)

    assert _saldos(base_pre_0102, ids[0]) == (Decimal("10.00"), Decimal("400.00"), Decimal("0.00"))
    assert _saldos(base_pre_0102, ids[1]) == (Decimal("10.00"), Decimal("0.00"), Decimal("40000.00"))


def test_la_correccion_deja_constancia_del_valor_anterior(base_pre_0102):
    """El historial automatico de cambios (0092) guarda el saldo en Bs que se borro, por si hace falta restaurarlo."""
    with Session(base_pre_0102) as session:
        cuenta = crear_cuenta_bancaria(session, moneda="USD")
        id_cuenta = cuenta.id_cuenta
        _cobro_por_zelle(session, cuenta)

    _aplicar_0102(base_pre_0102)

    with Session(base_pre_0102) as session:
        cambios = (
            session.query(AuditoriaCambioDB)
            .filter(AuditoriaCambioDB.tabla == "cuentas_bancarias", AuditoriaCambioDB.clave == str(id_cuenta))
            .order_by(AuditoriaCambioDB.id_cambio)
            .all()
        )
    ultimo = cambios[-1]
    assert ultimo.operacion == "U"
    assert json.loads(ultimo.anterior)["saldo_total_banco_bs"] == 800
    assert json.loads(ultimo.nuevo)["saldo_total_banco_bs"] == 0


def test_aplicar_la_migracion_dos_veces_no_falla_ni_cambia_nada(base_pre_0102):
    with Session(base_pre_0102) as session:
        cuenta = crear_cuenta_bancaria(session, moneda="USD")
        id_cuenta = cuenta.id_cuenta
        _cobro_por_zelle(session, cuenta)

    _aplicar_0102(base_pre_0102)
    _aplicar_0102(base_pre_0102)

    assert _saldos(base_pre_0102, id_cuenta) == (Decimal("20.00"), Decimal("0.00"), Decimal("0.00"))
