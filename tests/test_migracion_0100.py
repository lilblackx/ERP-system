"""Migracion 0100 (aplicaciones_nota_credito_cliente) probada contra una base descartable propia.

La 0100 crea la tabla de aplicaciones y VUELCA en ella las aplicaciones que hasta hoy solo existian como un evento de
Auditoria con el detalle en JSON. Eso toca datos de produccion, asi que se prueba con eventos "viejos" realistas y con
basura (JSON roto, notas que ya no existen...): lo que se pueda enlazar se vuelca bien y lo que no, se salta sin romper.

Igual que test_migracion_0094.py: la base de test normal ya tiene la 0100 aplicada, asi que se arma otra
(<TEST_DB_NAME>_mig100) con el schema base + migraciones anteriores a la 0100 y se corre el archivo real sobre ella.
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
from app.db.models import Auditoria, CuentaPorCobrar
from app.services.notas_credito import NotaCreditoService
from app.services.reportes import _aplicaciones_nc_cliente
from app.services.ventas import VentaService
from tests.conftest import SCHEMA_PATH, TEST_DB_NAME, _odbc_connect_str
from tests.factories import (
    crear_cliente,
    crear_precio_producto,
    crear_producto,
    crear_usuario_admin,
    crear_vendedor,
)

MIG_DB_NAME = f"{TEST_DB_NAME}_mig100"
ARCHIVO_0100 = MIGRATIONS_DIR / "0100_aplicaciones_nota_credito_cliente.sql"


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
def engine_pre_0100(tmp_path_factory):
    """Base con schema base + todas las migraciones anteriores a la 0100."""
    _recrear_base_descartable()
    _aplicar_schema_base()

    previas = tmp_path_factory.mktemp("migraciones_previas_0100")
    for archivo in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if archivo.name < ARCHIVO_0100.name:
            shutil.copy(archivo, previas / archivo.name)

    engine = create_engine("mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(_odbc_connect_str(MIG_DB_NAME)))
    aplicar_migraciones(engine, migrations_dir=previas)
    # El codigo actual exige piezas creadas por migraciones POSTERIORES a la 0100
    # bajo prueba (emitir_factura -> dbo.correlativos de la 0104; los INSERT del ORM
    # a notas_credito_clientes llevan fecha_pago_origen de la 0105 y la devolucion de
    # NC escribe devoluciones_nota_credito de la 0106). Se aplican aparte para que los
    # escenarios puedan ejercitar el codigo real; no interfieren con la 0100.
    with engine.connect() as connection:
        for nombre in (
            "0104_correlativo_de_facturas.sql",
            "0105_fecha_pago_origen_en_notas_credito.sql",
            "0106_devoluciones_nota_credito.sql",
            "0107_correlativos_de_documentos.sql",
        ):
            _ejecutar_batches(connection, (MIGRATIONS_DIR / nombre).read_text(encoding="utf-8"))
        connection.commit()
    yield engine
    engine.dispose()
    _borrar_base_descartable()


_VOLVER_A_PRE_0100 = """
DELETE FROM dbo.auditoria WHERE accion LIKE N'APLICACION_NOTA_CREDITO%';
GO
IF OBJECT_ID(N'dbo.trg_cambios_aplicaciones_nota_credito_cliente', N'TR') IS NOT NULL
    DROP TRIGGER dbo.trg_cambios_aplicaciones_nota_credito_cliente;
GO
IF OBJECT_ID(N'dbo.aplicaciones_nota_credito_cliente', N'U') IS NOT NULL
    DROP TABLE dbo.aplicaciones_nota_credito_cliente;
GO
"""


def _ejecutar(engine, sql: str) -> None:
    with engine.connect() as connection:
        _ejecutar_batches(connection, sql)
        connection.commit()


@pytest.fixture()
def base_pre_0100(engine_pre_0100):
    _ejecutar(engine_pre_0100, _VOLVER_A_PRE_0100)
    yield engine_pre_0100
    _ejecutar(engine_pre_0100, _VOLVER_A_PRE_0100)


def _aplicar_0100(engine) -> None:
    _ejecutar(engine, ARCHIVO_0100.read_text(encoding="utf-8"))


def _escenario(session):
    """Un cliente con una factura origen, una nota de credito de $50 y una factura a credito destino de $80."""
    admin = crear_usuario_admin(session)
    vendedor = crear_vendedor(session)
    producto = crear_producto(session, cantidad_unidad=100)
    crear_precio_producto(session, producto, "80.00")
    cliente = crear_cliente(session, limite_credito=Decimal("100000.00"), dias_credito=30)

    def credito():
        return VentaService.emitir_factura(
            session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "80.00"}],
        )

    origen = credito()
    destino = credito()
    nota = NotaCreditoService.crear_nota_credito_cliente(
        session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=origen.id_factura,
        monto=Decimal("50.00"),
        motivo="Ajuste",
        id_usuario=admin.id_usuario,
    )
    return admin, cliente, origen, destino, nota


def _evento_viejo(session, admin, detalle, accion="APLICACION_NOTA_CREDITO_CLIENTE", fecha=None):
    """Una aplicacion como se registraba ANTES de la 0100: solo un evento de Auditoria con el detalle en JSON."""
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
                "SELECT id_nota_credito, id_cuenta_por_cobrar, monto, fecha_aplicacion, aplicado_por "
                "FROM dbo.aplicaciones_nota_credito_cliente ORDER BY id_aplicacion"
            )
        )
        return [dict(fila._mapping) for fila in resultado]


def test_las_aplicaciones_viejas_se_vuelcan_con_su_nota_cuenta_monto_fecha_y_usuario(base_pre_0100):
    with Session(base_pre_0100) as session:
        admin, _cliente, _origen, destino, nota = _escenario(session)
        _evento_viejo(
            session,
            admin,
            {
                "numero_nota_credito": nota.numero_nota_credito,
                "id_factura_destino": destino.id_factura,
                "numero_factura_destino": destino.numero_factura,
                "monto": "20.00",
                "saldo_restante_nota": "30.00",
            },
            fecha=datetime(2026, 5, 4, 10, 30),
        )
        cuenta = session.query(CuentaPorCobrar).filter_by(id_factura=destino.id_factura).one()
        ids = (nota.id_nota_credito, cuenta.id_cuenta_por_cobrar, admin.id_usuario)

    _aplicar_0100(base_pre_0100)

    (fila,) = _filas(base_pre_0100)
    assert (fila["id_nota_credito"], fila["id_cuenta_por_cobrar"], fila["aplicado_por"]) == ids
    assert fila["monto"] == Decimal("20.00")
    assert fila["fecha_aplicacion"] == datetime(2026, 5, 4, 10, 30)


def test_varias_aplicaciones_de_la_misma_nota_se_vuelcan_todas_en_orden(base_pre_0100):
    with Session(base_pre_0100) as session:
        admin, _cliente, _origen, destino, nota = _escenario(session)
        for monto, fecha in (("10.00", datetime(2026, 5, 4)), ("15.00", datetime(2026, 5, 6))):
            _evento_viejo(
                session,
                admin,
                {
                    "numero_nota_credito": nota.numero_nota_credito,
                    "id_factura_destino": destino.id_factura,
                    "monto": monto,
                },
                fecha=fecha,
            )

    _aplicar_0100(base_pre_0100)

    assert [f["monto"] for f in _filas(base_pre_0100)] == [Decimal("10.00"), Decimal("15.00")]


def test_lo_que_no_se_puede_enlazar_se_salta_sin_romper_la_migracion(base_pre_0100):
    with Session(base_pre_0100) as session:
        admin, _cliente, _origen, destino, nota = _escenario(session)
        bueno = {
            "numero_nota_credito": nota.numero_nota_credito,
            "id_factura_destino": destino.id_factura,
            "monto": "20.00",
        }
        _evento_viejo(session, admin, bueno)
        _evento_viejo(session, admin, "esto no es json")
        _evento_viejo(session, admin, {"numero_nota_credito": nota.numero_nota_credito})  # sin factura ni monto
        _evento_viejo(session, admin, {**bueno, "numero_nota_credito": "NC-NO-EXISTE"})
        _evento_viejo(session, admin, {**bueno, "id_factura_destino": 987_654_321})  # factura sin cuenta
        _evento_viejo(session, admin, {**bueno, "monto": "0.00"})
        _evento_viejo(session, admin, {**bueno, "monto": "-5.00"})
        _evento_viejo(session, admin, {**bueno, "monto": "abc"})
        _evento_viejo(session, admin, {**bueno, "id_factura_destino": "no-es-numero"})
        _evento_viejo(session, admin, bueno, accion="APLICACION_NOTA_CREDITO_PROVEEDOR")  # es de proveedores

    _aplicar_0100(base_pre_0100)  # no lanza

    (fila,) = _filas(base_pre_0100)  # solo la aplicacion buena
    assert fila["monto"] == Decimal("20.00")


def test_sin_eventos_viejos_la_tabla_queda_vacia_y_con_sus_restricciones(base_pre_0100):
    _aplicar_0100(base_pre_0100)

    assert _filas(base_pre_0100) == []
    with base_pre_0100.connect() as connection:
        restricciones = {
            fila[0]
            for fila in connection.execute(
                text(
                    "SELECT name FROM sys.objects "
                    "WHERE parent_object_id = OBJECT_ID(N'dbo.aplicaciones_nota_credito_cliente')"
                )
            )
        }
        trigger = connection.execute(
            text("SELECT OBJECT_ID(N'dbo.trg_cambios_aplicaciones_nota_credito_cliente', N'TR')")
        ).scalar()
    assert {
        "FK_aplicaciones_nc_cliente_nota",
        "FK_aplicaciones_nc_cliente_cxc",
        "FK_aplicaciones_nc_cliente_usuario",
        "CK_aplicaciones_nc_cliente_monto",
    } <= restricciones
    assert trigger is not None


def test_lo_volcado_es_lo_que_ahora_lee_el_reporte(base_pre_0100):
    with Session(base_pre_0100) as session:
        admin, _cliente, _origen, destino, nota = _escenario(session)
        id_destino, numero_nota = destino.id_factura, nota.numero_nota_credito
        _evento_viejo(
            session,
            admin,
            {"numero_nota_credito": numero_nota, "id_factura_destino": id_destino, "monto": "20.00"},
        )

    _aplicar_0100(base_pre_0100)

    with Session(base_pre_0100) as session:
        (aplicacion,) = _aplicaciones_nc_cliente(session, ids_factura=[id_destino])
    assert aplicacion["numero_nota_credito"] == numero_nota
    assert aplicacion["id_factura"] == id_destino
    assert aplicacion["monto"] == Decimal("20.00")
    assert aplicacion["fecha"] == datetime(2026, 5, 4, 10, 30)
