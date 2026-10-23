"""Blindaje de la base de datos: clave protegida con DPAPI, DENY de borrado del historial de dinero
para el usuario de la app, y bitacora automatica de cambios a dinero/stock (migrations/0091-0092)."""

import json
from decimal import Decimal

import pyodbc
import pytest
from sqlalchemy import text

from app import config, proteger_env
from app.db.models import AuditoriaCambioDB
from app.services.auditoria_base import AuditoriaBaseService
from app.services.notificaciones import NotificacionesService
from app.services.permisos import PermisoDenegadoError
from app.utils import dpapi
from tests.conftest import TEST_DB_NAME, _odbc_connect_str
from tests.factories import (
    crear_caja,
    crear_cliente,
    crear_precio_producto,
    crear_producto,
    crear_usuario,
    crear_usuario_admin,
    crear_vendedor,
)

solo_windows = pytest.mark.skipif(not dpapi.DISPONIBLE, reason="DPAPI solo existe en Windows")


# ── Clave protegida con DPAPI ───────────────────────────────────────────────────


def test_una_clave_en_claro_se_devuelve_igual():
    assert config.desproteger_clave("MiClave123") == "MiClave123"
    assert config.desproteger_clave("") == ""


@solo_windows
def test_la_clave_protegida_no_es_legible_y_se_recupera_en_esta_pc():
    protegida = config.proteger_clave("Cl4ve-Secreta-Base")

    assert protegida.startswith("dpapi:")
    assert "Cl4ve-Secreta-Base" not in protegida
    assert config.desproteger_clave(protegida) == "Cl4ve-Secreta-Base"


@solo_windows
def test_un_valor_protegido_para_otra_pc_o_corrupto_devuelve_vacio():
    assert config.desproteger_clave("dpapi:AAAA-no-es-base64-valido") == ""
    assert config.desproteger_clave("dpapi:" + "QUJDREVGRw==") == ""  # base64 valido, pero no es un blob DPAPI


@solo_windows
def test_proteger_env_cambia_las_claves_y_revertir_las_deja_como_estaban():
    original = "DB_SERVER=localhost\nDB_PASSWORD=Cl4ve-Base\nSMTP_PASSWORD=abcd efgh\nOTRA=1\n"

    protegido, cambiadas = proteger_env.transformar(original)

    assert cambiadas == ["DB_PASSWORD", "SMTP_PASSWORD"]
    assert "Cl4ve-Base" not in protegido and "abcd efgh" not in protegido
    assert "DB_PASSWORD_DPAPI=dpapi:" in protegido and "\nDB_PASSWORD=" not in protegido
    assert "OTRA=1" in protegido and "DB_SERVER=localhost" in protegido

    vuelto, cambiadas = proteger_env.transformar(protegido, revertir=True)
    assert cambiadas == ["DB_PASSWORD", "SMTP_PASSWORD"]
    assert vuelto == original


@solo_windows
def test_proteger_env_es_idempotente_y_deja_copia(tmp_path):
    archivo = tmp_path / ".env"
    archivo.write_text("DB_PASSWORD=Cl4ve-Base\n", encoding="utf-8")

    assert proteger_env.procesar_archivo(archivo) == ["DB_PASSWORD"]
    assert proteger_env.procesar_archivo(archivo) == []  # ya protegida: nada que hacer
    assert (tmp_path / ".env.bak").read_text(encoding="utf-8") == "DB_PASSWORD=Cl4ve-Base\n"


def test_la_cadena_de_conexion_se_identifica_como_la_app_y_cifra():
    url = config.get_database_url()

    assert "APP%3DNexoERP%3B" in url
    assert "Encrypt%3Dyes" in url


# ── DENY: el usuario de la app no puede borrar el historial de dinero ───────────

LOGIN_PRUEBA = "dj_blindaje_prueba"
CLAVE_PRUEBA = "Prueba-Blindaje-2026!x"


def _admin_pyodbc():
    return pyodbc.connect(_odbc_connect_str(TEST_DB_NAME), autocommit=True)


def _limpiar_login(cur):
    """El pool de conexiones de ODBC mantiene viva la sesion tras close(): se la mata antes de
    borrar el login (si no, SQL Server rechaza el DROP porque 'esta conectado')."""
    cur.execute(
        "DECLARE @k NVARCHAR(MAX) = N''; "
        "SELECT @k += N'KILL ' + CAST(session_id AS NVARCHAR(10)) + N';' "
        f"FROM sys.dm_exec_sessions WHERE login_name = N'{LOGIN_PRUEBA}'; EXEC (@k);"
    )
    cur.execute(f"IF USER_ID('{LOGIN_PRUEBA}') IS NOT NULL DROP USER [{LOGIN_PRUEBA}]")
    cur.execute(f"IF SUSER_ID('{LOGIN_PRUEBA}') IS NOT NULL DROP LOGIN [{LOGIN_PRUEBA}]")


@pytest.fixture()
def usuario_limitado(db_session):
    """Login SQL creado igual que lo hace el instalador para el usuario de la app."""
    from app import instalacion

    admin = _admin_pyodbc()
    cur = admin.cursor()
    _limpiar_login(cur)
    motor = instalacion._motor(config.DB_SERVER, TEST_DB_NAME, config.DB_USER, config.DB_PASSWORD)
    try:
        instalacion._crear_usuario_app(motor, TEST_DB_NAME, LOGIN_PRUEBA, CLAVE_PRUEBA)
    finally:
        motor.dispose()
    cadena = (
        f"DRIVER={{{config.DB_DRIVER}}};SERVER={config.DB_SERVER};DATABASE={TEST_DB_NAME};"
        f"UID={LOGIN_PRUEBA};PWD={CLAVE_PRUEBA};TrustServerCertificate={config.DB_TRUST_SERVER_CERTIFICATE};"
    )
    conn = pyodbc.connect(cadena, autocommit=True)
    yield conn
    conn.close()
    _limpiar_login(cur)
    admin.close()


@pytest.mark.parametrize(
    "tabla",
    [
        "caja_movimientos",
        "banco_movimientos",
        "pagos_cobros",
        "pagos_proveedores",
        "pagos_cobros_bcv",
        "pagos_comisiones",
        "notas_credito_clientes",
        "notas_credito_proveedores",
        "conciliaciones_partida",
        "auditoria",
        "auditoria_cambios_db",
    ],
)
def test_el_usuario_de_la_app_no_puede_borrar_el_historial_de_dinero(usuario_limitado, tabla):
    with pytest.raises(pyodbc.Error, match="DELETE permission was denied|permiso DELETE"):
        usuario_limitado.cursor().execute(f"DELETE FROM dbo.{tabla} WHERE 1 = 0")


@pytest.mark.parametrize("tabla", ["auditoria", "auditoria_cambios_db"])
def test_la_bitacora_no_se_puede_reescribir(usuario_limitado, tabla):
    columna = "detalle" if tabla == "auditoria" else "nuevo"
    with pytest.raises(pyodbc.Error, match="UPDATE permission was denied|permiso UPDATE"):
        usuario_limitado.cursor().execute(f"UPDATE dbo.{tabla} SET {columna} = NULL WHERE 1 = 0")


def test_el_usuario_de_la_app_sigue_pudiendo_hacer_su_trabajo_normal(usuario_limitado):
    cur = usuario_limitado.cursor()
    cur.execute("SELECT COUNT(*) FROM dbo.caja_movimientos")  # leer
    cur.execute("INSERT INTO dbo.auditoria (accion, modulo, detalle) VALUES ('PRUEBA', 'PRUEBA', 'x')")  # insertar
    cur.execute("DELETE FROM dbo.clientes WHERE 1 = 0")  # borrar en tablas que la app si borra
    cur.execute("DELETE FROM dbo.cuentas_por_cobrar WHERE 1 = 0")
    cur.execute("UPDATE dbo.cuentas_por_cobrar SET saldo_pendiente = saldo_pendiente WHERE 1 = 0")


# ── Bitacora automatica de cambios ──────────────────────────────────────────────


def _cambios(db_session, tabla=None):
    db_session.expire_all()
    consulta = db_session.query(AuditoriaCambioDB).order_by(AuditoriaCambioDB.id_cambio)
    if tabla:
        consulta = consulta.filter(AuditoriaCambioDB.tabla == tabla)
    return consulta.all()


def test_un_cambio_de_stock_deja_valor_anterior_y_nuevo(db_session):
    producto = crear_producto(db_session, cantidad_unidad=10)
    db_session.query(AuditoriaCambioDB).delete()
    db_session.commit()

    producto.cantidad_unidad = Decimal("7")
    db_session.commit()

    (cambio,) = [c for c in _cambios(db_session, "inventario") if c.operacion == "U"]
    assert cambio.clave == str(producto.id_producto)
    assert json.loads(cambio.anterior)["cantidad_unidad"] == 10
    assert json.loads(cambio.nuevo)["cantidad_unidad"] == 7
    assert cambio.fuera_de_la_app is False  # la suite se identifica como la app
    assert cambio.aplicacion == "NexoERP-Tests"


def test_una_actualizacion_sin_cambios_no_deja_fila(db_session):
    producto = crear_producto(db_session, cantidad_unidad=10)
    db_session.query(AuditoriaCambioDB).delete()
    db_session.commit()

    db_session.execute(
        text("UPDATE dbo.inventario SET cantidad_unidad = cantidad_unidad WHERE id_producto = :p"),
        {"p": producto.id_producto},
    )
    db_session.commit()

    assert _cambios(db_session, "inventario") == []


def test_altas_y_borrados_de_movimientos_de_caja_quedan_registrados(db_session):
    from app.db.models import CajaMovimiento

    caja = crear_caja(db_session)
    movimiento = CajaMovimiento(id_caja=caja.id_caja, tipo_movimiento="entrada", monto_movimiento=Decimal("5.00"))
    db_session.add(movimiento)
    db_session.commit()
    id_movimiento = movimiento.id_movimiento

    db_session.execute(text("DELETE FROM dbo.caja_movimientos WHERE id_movimiento = :m"), {"m": id_movimiento})
    db_session.commit()

    operaciones = [c.operacion for c in _cambios(db_session, "caja_movimientos") if c.clave == str(id_movimiento)]
    assert operaciones == ["I", "D"]
    borrado = [c for c in _cambios(db_session, "caja_movimientos") if c.operacion == "D"][0]
    assert borrado.nuevo is None and json.loads(borrado.anterior)["monto_movimiento"] == 5


def test_los_cobros_de_una_venta_de_contado_quedan_registrados_pese_al_trigger_instead_of(db_session):
    from tests.factories import pago_contado

    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=20)
    crear_precio_producto(db_session, producto, "10.00")
    cliente = crear_cliente(db_session)
    from app.services.ventas import VentaService

    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "10.00"}],
    )

    assert [c.operacion for c in _cambios(db_session, "pagos_cobros")] == ["I"]
    assert any(c.operacion == "U" for c in _cambios(db_session, "inventario"))  # el stock bajo
    assert {c.tabla for c in _cambios(db_session)} >= {"pagos_cobros", "inventario", "cuentas_por_cobrar"}


def test_un_cambio_hecho_desde_otro_programa_queda_marcado_y_la_campana_avisa(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=10)
    assert AuditoriaBaseService.contar_cambios_fuera_de_la_app(db_session) == 0

    # "Excel": mismo usuario SQL, pero otro programa (APP distinto al de la app).
    excel = pyodbc.connect(
        _odbc_connect_str(TEST_DB_NAME).replace("APP=NexoERP-Tests;", "APP=Microsoft Excel;"), autocommit=True
    )
    excel.cursor().execute(
        "UPDATE dbo.inventario SET cantidad_unidad = 9999 WHERE id_producto = ?", producto.id_producto
    )
    excel.close()

    (cambio,) = [c for c in _cambios(db_session, "inventario") if c.fuera_de_la_app]
    assert cambio.aplicacion == "Microsoft Excel"
    assert json.loads(cambio.nuevo)["cantidad_unidad"] == 9999
    assert json.loads(cambio.anterior)["cantidad_unidad"] == 10  # sirve para restaurarlo
    assert AuditoriaBaseService.contar_cambios_fuera_de_la_app(db_session) == 1

    claves = [n.clave for n in NotificacionesService.obtener(db_session, admin.id_usuario)]
    assert "cambios_directos_base" in claves


def test_la_campana_no_avisa_de_cambios_directos_a_quien_no_ve_la_auditoria(db_session):
    cajero = crear_usuario(db_session, estado="ACTIVO")
    producto = crear_producto(db_session, cantidad_unidad=10)
    excel = pyodbc.connect(_odbc_connect_str(TEST_DB_NAME).replace("APP=NexoERP-Tests;", "APP=SSMS;"), autocommit=True)
    excel.cursor().execute("UPDATE dbo.inventario SET cantidad_unidad = 1 WHERE id_producto = ?", producto.id_producto)
    excel.close()

    claves = [n.clave for n in NotificacionesService.obtener(db_session, cajero.id_usuario)]
    assert "cambios_directos_base" not in claves


def test_listar_cambios_exige_permiso_y_filtra_por_origen(db_session):
    admin = crear_usuario_admin(db_session)
    crear_producto(db_session, cantidad_unidad=10)

    with pytest.raises(PermisoDenegadoError):
        AuditoriaBaseService.listar_cambios(db_session, id_usuario=None)
    assert AuditoriaBaseService.listar_cambios(db_session, admin.id_usuario, solo_fuera_de_la_app=True) == []
    assert len(AuditoriaBaseService.listar_cambios(db_session, admin.id_usuario, tabla="inventario")) >= 1


def test_el_id_unico_de_la_bitacora_no_se_reutiliza(db_session):
    # Cada fila tiene su propia clave aunque el mismo registro cambie varias veces.
    producto = crear_producto(db_session, cantidad_unidad=10)
    for stock in (9, 8, 7):
        producto.cantidad_unidad = Decimal(stock)
        db_session.commit()

    ids = [c.id_cambio for c in _cambios(db_session, "inventario")]
    assert len(ids) == len(set(ids)) >= 3
