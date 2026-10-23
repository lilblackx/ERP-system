"""Migraciones 0085-0088 (estado de recepciones, rechazado fuera del stock, vinculo
compra_detalle -> linea de OC, enmiendas por linea) aplicadas sobre una base descartable
con DATOS reales del modelo anterior.

La base de test normal ya las tiene aplicadas desde cero (sin datos), asi que no prueba lo
que importa de estas migraciones: el ajuste/backfill sobre filas existentes. Aca se arma
una base (<TEST_DB_NAME>_mig2) con schema base + 0001..0084, se cargan datos con el
comportamiento viejo (triggers viejos de recepcion/devolucion) y se corren los 4 archivos
reales encima.
"""

import re
import shutil
import urllib.parse
from datetime import datetime
from decimal import Decimal

import pyodbc
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.migrar import MIGRATIONS_DIR, aplicar_migraciones
from app.db.models import (
    Compra,
    CompraOC,
    CompraOCDetalle,
    NotaDevolucion,
    NotaDevolucionDetalle,
    NotaRecepcion,
    NotaRecepcionDetalle,
)
from tests.conftest import SCHEMA_PATH, TEST_DB_NAME, _odbc_connect_str
from tests.factories import crear_producto, crear_proveedor, crear_usuario_admin

MIG_DB_NAME = f"{TEST_DB_NAME}_mig2"
PRIMERA_NUEVA = "0085_estado_recepcion_segun_facturado.sql"


def _db_en_master(sql: str) -> None:
    conn = pyodbc.connect(_odbc_connect_str("master"), autocommit=True)
    try:
        conn.cursor().execute(sql)
    finally:
        conn.close()


@pytest.fixture(scope="module")
def engine_pre_0085(tmp_path_factory):
    _db_en_master(
        f"IF DB_ID(N'{MIG_DB_NAME}') IS NOT NULL BEGIN "
        f"ALTER DATABASE [{MIG_DB_NAME}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
        f"DROP DATABASE [{MIG_DB_NAME}]; END"
    )
    _db_en_master(f"CREATE DATABASE [{MIG_DB_NAME}]")

    batches = re.split(r"(?im)^\s*GO\s*$", SCHEMA_PATH.read_text(encoding="utf-8"))
    conn = pyodbc.connect(_odbc_connect_str(MIG_DB_NAME), autocommit=True)
    try:
        cursor = conn.cursor()
        for batch in batches:
            if batch.strip():
                cursor.execute(batch.strip())
    finally:
        conn.close()

    previas = tmp_path_factory.mktemp("migraciones_previas_0085")
    for archivo in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if archivo.name < PRIMERA_NUEVA:
            shutil.copy(archivo, previas / archivo.name)

    engine = create_engine("mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(_odbc_connect_str(MIG_DB_NAME)))
    aplicar_migraciones(engine, migrations_dir=previas)
    yield engine
    engine.dispose()
    _db_en_master(
        f"IF DB_ID(N'{MIG_DB_NAME}') IS NOT NULL BEGIN "
        f"ALTER DATABASE [{MIG_DB_NAME}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
        f"DROP DATABASE [{MIG_DB_NAME}]; END"
    )


def _recibir(session, oc, linea, recibida, rechazada, usuario):
    nr = NotaRecepcion(
        id_oc=oc.id_oc,
        numero_nr=f"NR-T{linea.id_detalle}{datetime.now().microsecond}",
        id_usuario_recepcion=usuario.id_usuario,
    )
    session.add(nr)
    session.flush()
    session.add(
        NotaRecepcionDetalle(
            id_nr=nr.id_nr,
            id_oc_detalle=linea.id_detalle,
            id_producto=linea.id_producto,
            cantidad_recibida=Decimal(recibida),
            cantidad_rechazada=Decimal(rechazada),
            precio_unitario=linea.precio_unitario,
            total_linea=Decimal(recibida) * linea.precio_unitario,
        )
    )
    session.commit()
    return nr


def _oc_con_linea(session, proveedor, producto, usuario, solicitada):
    oc = CompraOC(numero_oc=f"ODC-T{producto.id_producto}", id_proveedor=proveedor.id_proveedor)
    session.add(oc)
    session.flush()
    linea = CompraOCDetalle(
        id_oc=oc.id_oc,
        id_producto=producto.id_producto,
        cantidad_solicitada=Decimal(solicitada),
        cantidad_pendiente=Decimal(solicitada),
        precio_unitario=Decimal("5.00"),
        total_linea=Decimal(solicitada) * Decimal("5.00"),
    )
    session.add(linea)
    session.commit()
    return oc, linea


def test_migraciones_ajustan_datos_existentes(engine_pre_0085):
    engine = engine_pre_0085
    with Session(engine) as session:
        admin = crear_usuario_admin(session)
        proveedor = crear_proveedor(session)

        # Producto P: 10 recibidas, 4 rechazadas, 1 ya devuelta. Con los triggers viejos el
        # stock queda 10 - 1 = 9 (lo rechazado sin devolver, 3, esta inflado).
        producto_p = crear_producto(session, cantidad_unidad=0)
        oc_p, linea_p = _oc_con_linea(session, proveedor, producto_p, admin, 10)
        nr_p = _recibir(session, oc_p, linea_p, "10", "4", admin)
        devolucion = NotaDevolucion(
            id_nr=nr_p.id_nr,
            numero_nota_devolucion="ND-T1",
            motivo="Defectuoso",
            cantidad_total=Decimal("1"),
            estado="DEVUELTO",
            id_usuario_creador=admin.id_usuario,
        )
        session.add(devolucion)
        session.flush()
        session.add(
            NotaDevolucionDetalle(
                id_devolucion=devolucion.id_devolucion,
                id_producto=producto_p.id_producto,
                cantidad_devuelta=Decimal("1"),
                precio_unitario=Decimal("5.00"),
                total_linea=Decimal("5.00"),
            )
        )
        linea_p.cantidad_facturada = Decimal("6")  # todo lo aceptado (10 - 4) ya facturado
        session.commit()
        session.refresh(producto_p)
        assert producto_p.cantidad_unidad == Decimal("9")

        # Producto Q: todo rechazado y, ademas, ya se vendio parte del stock inflado.
        producto_q = crear_producto(session, cantidad_unidad=0)
        oc_q, linea_q = _oc_con_linea(session, proveedor, producto_q, admin, 5)
        _recibir(session, oc_q, linea_q, "5", "5", admin)
        session.execute(
            text("UPDATE dbo.inventario SET cantidad_unidad = 2 WHERE id_producto = :p"),
            {"p": producto_q.id_producto},
        )
        session.commit()

        # Compra directa-desde-OC del modelo viejo: compra_detalle sin vinculo a la linea.
        compra = Compra(
            numero_compra="OC-T1",
            id_proveedor=proveedor.id_proveedor,
            id_usuario_compra=admin.id_usuario,
            total_compra=Decimal("0.00"),
            estado_compra="EMITIDA",
            condicion_pago="credito",
            id_oc=oc_p.id_oc,
        )
        session.add(compra)
        session.flush()
        session.execute(
            text(
                "INSERT INTO dbo.compra_detalle (id_compra, id_producto_compra, cantidad_producto, "
                "costo_unitario, stock_ya_contabilizado) VALUES (:c, :p, 6, 5.00, 1)"
            ),
            {"c": compra.id_compra, "p": producto_p.id_producto},
        )
        session.commit()
        ids = {
            "p": producto_p.id_producto,
            "q": producto_q.id_producto,
            "nr_p": nr_p.id_nr,
            "linea_p": linea_p.id_detalle,
            "compra": compra.id_compra,
        }

    aplicar_migraciones(engine)  # 0085..0088 pendientes

    with engine.connect() as conn:
        stock = dict(conn.execute(text("SELECT id_producto, cantidad_unidad FROM dbo.inventario")).fetchall())
        estado_nr = conn.execute(
            text("SELECT estado FROM dbo.nota_recepcion WHERE id_nr = :n"), {"n": ids["nr_p"]}
        ).scalar()
        vinculo = conn.execute(
            text("SELECT id_oc_detalle FROM dbo.compra_detalle WHERE id_compra = :c"), {"c": ids["compra"]}
        ).scalar()
        cajas = conn.execute(
            text("SELECT cantidad_caja_total FROM dbo.inventario WHERE id_producto = :p"), {"p": ids["p"]}
        ).scalar()

    # P: 9 - (4 rechazadas - 1 devuelta) = 6 = recibidas 10 - rechazadas 4.
    assert stock[ids["p"]] == Decimal("6")
    # Q: 2 - 5 no puede quedar negativo -> piso en 0.
    assert stock[ids["q"]] == Decimal("0")
    # NR de P: facturado 6 de 6 aceptadas -> FACTURADA (antes de 0085 todas eran RECIBIDA).
    assert estado_nr == "FACTURADA"
    # Backfill del vinculo: la OC tiene una sola linea de ese producto -> inequivoco.
    assert vinculo == ids["linea_p"]
    assert cajas is not None
