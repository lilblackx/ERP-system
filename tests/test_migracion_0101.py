"""Migracion 0101 (aplicaciones_nota_credito_proveedor) probada contra una base descartable propia.

Espejo de test_migracion_0100.py: la 0101 crea la tabla y VUELCA en ella las aplicaciones de notas de credito de
proveedor que hasta hoy solo existian como un evento de Auditoria con JSON. Se prueba con eventos "viejos" realistas y
con basura (JSON roto, notas o cuentas que ya no existen...): lo que se pueda enlazar se vuelca bien y lo que no, se
salta sin romper.

La base de test normal ya tiene la 0101 aplicada, asi que se arma otra (<TEST_DB_NAME>_mig101) con el schema base +
migraciones anteriores y se corre el archivo real sobre ella.
"""

import json
import re
import shutil
import urllib.parse
from datetime import datetime
from decimal import Decimal

import pyodbc
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.migrar import MIGRATIONS_DIR, _ejecutar_batches, aplicar_migraciones
from app.db.models import Auditoria, CuentaPorPagar
from app.services.compras import CompraService
from app.services.reportes import _aplicaciones_nc_proveedor
from tests.conftest import SCHEMA_PATH, TEST_DB_NAME, _odbc_connect_str
from tests.factories import crear_caja, crear_producto, crear_proveedor, crear_usuario_admin

MIG_DB_NAME = f"{TEST_DB_NAME}_mig101"
ARCHIVO_0101 = MIGRATIONS_DIR / "0101_aplicaciones_nota_credito_proveedor.sql"


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
def engine_pre_0101(tmp_path_factory):
    """Base con schema base + todas las migraciones anteriores a la 0101."""
    _recrear_base_descartable()
    _aplicar_schema_base()

    previas = tmp_path_factory.mktemp("migraciones_previas_0101")
    for archivo in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if archivo.name < ARCHIVO_0101.name:
            shutil.copy(archivo, previas / archivo.name)

    engine = create_engine("mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(_odbc_connect_str(MIG_DB_NAME)))
    aplicar_migraciones(engine, migrations_dir=previas)
    yield engine
    engine.dispose()
    _borrar_base_descartable()


_VOLVER_A_PRE_0101 = """
DELETE FROM dbo.auditoria WHERE accion LIKE N'APLICACION_NOTA_CREDITO%';
GO
IF OBJECT_ID(N'dbo.trg_cambios_aplicaciones_nota_credito_proveedor', N'TR') IS NOT NULL
    DROP TRIGGER dbo.trg_cambios_aplicaciones_nota_credito_proveedor;
GO
IF OBJECT_ID(N'dbo.aplicaciones_nota_credito_proveedor', N'U') IS NOT NULL
    DROP TABLE dbo.aplicaciones_nota_credito_proveedor;
GO
"""


def _ejecutar(engine, sql: str) -> None:
    with engine.connect() as connection:
        _ejecutar_batches(connection, sql)
        connection.commit()


@pytest.fixture()
def base_pre_0101(engine_pre_0101):
    _ejecutar(engine_pre_0101, _VOLVER_A_PRE_0101)
    yield engine_pre_0101
    _ejecutar(engine_pre_0101, _VOLVER_A_PRE_0101)


def _aplicar_0101(engine) -> None:
    _ejecutar(engine, ARCHIVO_0101.read_text(encoding="utf-8"))


def _escenario(session):
    """Una nota de proveedor de $40 (compra de contado anulada) y una deuda a credito de $100 del mismo proveedor."""
    admin = crear_usuario_admin(session)
    proveedor = crear_proveedor(session, limite_credito=Decimal("100000.00"))
    caja = crear_caja(session)
    from app.services.tesoreria import CajaService

    CajaService.abrir_caja(session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("1000.00"))
    producto = crear_producto(session, cantidad_unidad=10)
    pago = {
        "metodo_pago": "efectivo",
        "moneda": "USD",
        "monto_moneda_origen": Decimal("40.00"),
        "id_caja": caja.id_caja,
        "id_cuenta_bancaria": None,
        "referencia": None,
    }
    contado = CompraService.registrar_compra(
        session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "40.00"}],
        pago=pago,
    )
    CompraService.anular_compra(session, contado.id_compra, id_usuario=admin.id_usuario, motivo="Error")
    credito = CompraService.registrar_compra(
        session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "100.00"}],
    )
    from app.db.models import NotaCreditoProveedor

    nota = session.query(NotaCreditoProveedor).filter_by(id_compra_origen=contado.id_compra).one()
    cuenta = session.query(CuentaPorPagar).filter_by(id_compra=credito.id_compra).one()
    return admin, nota.id_nota_credito, cuenta.id_cuenta


def _evento_viejo(session, admin, detalle, accion="APLICACION_NOTA_CREDITO_PROVEEDOR", fecha=None):
    """Una aplicacion como se registraba ANTES de la 0101: solo un evento de Auditoria con el detalle en JSON."""
    session.add(
        Auditoria(
            id_usuario=admin.id_usuario,
            accion=accion,
            modulo="NOTAS_CREDITO",
            detalle=detalle if isinstance(detalle, str) else json.dumps(detalle),
            fecha_evento=fecha or datetime(2026, 5, 4, 10, 30),
        )
    )
    session.commit()


def _filas(engine) -> list[dict]:
    with engine.connect() as connection:
        resultado = connection.execute(
            text(
                "SELECT id_nota_credito, id_cuenta_por_pagar, monto, fecha_aplicacion, aplicado_por "
                "FROM dbo.aplicaciones_nota_credito_proveedor ORDER BY id_aplicacion"
            )
        )
        return [dict(fila._mapping) for fila in resultado]


def test_las_aplicaciones_viejas_se_vuelcan_con_su_nota_cuenta_monto_fecha_y_usuario(base_pre_0101):
    with Session(base_pre_0101) as session:
        admin, id_nota, id_cuenta = _escenario(session)
        _evento_viejo(
            session,
            admin,
            {
                "id_nota_credito": id_nota,
                "id_cuenta_por_pagar": id_cuenta,
                "numero_compra_destino": "C-1",
                "monto": "25.00",
                "saldo_restante_nota": "15.00",
            },
        )
        id_usuario = admin.id_usuario

    _aplicar_0101(base_pre_0101)

    (fila,) = _filas(base_pre_0101)
    assert (fila["id_nota_credito"], fila["id_cuenta_por_pagar"], fila["aplicado_por"]) == (
        id_nota,
        id_cuenta,
        id_usuario,
    )
    assert fila["monto"] == Decimal("25.00")
    assert fila["fecha_aplicacion"] == datetime(2026, 5, 4, 10, 30)


def test_lo_que_no_se_puede_enlazar_se_salta_sin_romper_la_migracion(base_pre_0101):
    with Session(base_pre_0101) as session:
        admin, id_nota, id_cuenta = _escenario(session)
        bueno = {"id_nota_credito": id_nota, "id_cuenta_por_pagar": id_cuenta, "monto": "25.00"}
        _evento_viejo(session, admin, bueno)
        _evento_viejo(session, admin, "esto no es json")
        _evento_viejo(session, admin, {"id_nota_credito": id_nota})  # sin cuenta ni monto
        _evento_viejo(session, admin, {**bueno, "id_nota_credito": 987_654_321})  # la nota ya no existe
        _evento_viejo(session, admin, {**bueno, "id_cuenta_por_pagar": 987_654_321})  # la cuenta ya no existe
        _evento_viejo(session, admin, {**bueno, "monto": "0.00"})
        _evento_viejo(session, admin, {**bueno, "monto": "-5.00"})
        _evento_viejo(session, admin, {**bueno, "monto": "abc"})
        _evento_viejo(session, admin, {**bueno, "id_nota_credito": "no-es-numero"})
        _evento_viejo(session, admin, bueno, accion="APLICACION_NOTA_CREDITO_CLIENTE")  # es de clientes

    _aplicar_0101(base_pre_0101)  # no lanza

    (fila,) = _filas(base_pre_0101)  # solo la aplicacion buena
    assert fila["monto"] == Decimal("25.00")


def test_sin_eventos_viejos_la_tabla_queda_vacia_y_con_sus_restricciones(base_pre_0101):
    _aplicar_0101(base_pre_0101)

    assert _filas(base_pre_0101) == []
    with base_pre_0101.connect() as connection:
        restricciones = {
            fila[0]
            for fila in connection.execute(
                text(
                    "SELECT name FROM sys.objects "
                    "WHERE parent_object_id = OBJECT_ID(N'dbo.aplicaciones_nota_credito_proveedor')"
                )
            )
        }
        trigger = connection.execute(
            text("SELECT OBJECT_ID(N'dbo.trg_cambios_aplicaciones_nota_credito_proveedor', N'TR')")
        ).scalar()
    assert {
        "FK_aplicaciones_nc_proveedor_nota",
        "FK_aplicaciones_nc_proveedor_cxp",
        "FK_aplicaciones_nc_proveedor_usuario",
        "CK_aplicaciones_nc_proveedor_monto",
    } <= restricciones
    assert trigger is not None


def test_lo_volcado_es_lo_que_ahora_lee_el_reporte(base_pre_0101):
    with Session(base_pre_0101) as session:
        admin, id_nota, id_cuenta = _escenario(session)
        _evento_viejo(session, admin, {"id_nota_credito": id_nota, "id_cuenta_por_pagar": id_cuenta, "monto": "25.00"})

    _aplicar_0101(base_pre_0101)

    with Session(base_pre_0101) as session:
        (aplicacion,) = _aplicaciones_nc_proveedor(session, ids_cuenta=[id_cuenta])
    assert aplicacion["id_nota_credito"] == id_nota
    assert aplicacion["id_cuenta"] == id_cuenta
    assert aplicacion["monto"] == Decimal("25.00")
    assert aplicacion["fecha"] == datetime(2026, 5, 4, 10, 30)
