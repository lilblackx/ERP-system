"""Tests de app/instalacion.py (las herramientas que usa el instalador), contra SQL Server real.
Crean una base y un login temporales (dj_inst_test / dj_inst_app) y los eliminan al terminar."""

import json

import bcrypt
import pyodbc
import pytest

from app import instalacion
from app.config import DB_PASSWORD, DB_SERVER, DB_USER
from app.instalacion import ErrorInstalacion, main

BASE = "dj_inst_test"
USUARIO_APP = "dj_inst_app"
CLAVE_APP = "Cl4veSegura-Prueba9"
CLAVE_ADMIN_APP = "Admin-Prueba-2026"


def _admin_pyodbc(base="master"):
    cadena = instalacion._cadena_odbc(DB_SERVER, base, DB_USER, DB_PASSWORD, False)
    return pyodbc.connect(cadena, autocommit=True)


def _limpiar():
    conn = _admin_pyodbc()
    try:
        cur = conn.cursor()
        cur.execute(
            f"IF DB_ID(N'{BASE}') IS NOT NULL BEGIN "
            f"ALTER DATABASE [{BASE}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [{BASE}]; END"
        )
        # Las pruebas llaman a las herramientas en el mismo proceso: puede quedar alguna sesion del login
        # abierta en el pool de SQLAlchemy y SQL Server no deja borrar un login con sesiones activas.
        cur.execute(
            "DECLARE @k NVARCHAR(MAX) = N''; "
            "SELECT @k += N'KILL ' + CAST(session_id AS NVARCHAR(10)) + N'; ' "
            f"FROM sys.dm_exec_sessions WHERE login_name = N'{USUARIO_APP}'; EXEC (@k);"
        )
        cur.execute(
            f"IF EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'{USUARIO_APP}') DROP LOGIN [{USUARIO_APP}]"
        )
    finally:
        conn.close()


def _ejecutar(comando, datos, tmp_path):
    entrada, salida = tmp_path / "entrada.json", tmp_path / "salida.txt"
    entrada.write_text(json.dumps(datos), encoding="utf-8")
    codigo = main([comando, "--entrada", str(entrada), "--salida", str(salida)])
    estado, _, mensaje = salida.read_text(encoding="utf-8").partition("\n")
    return codigo, estado, mensaje.strip()


def _datos_servidor(tmp_path, **extra):
    return {
        "servidor": DB_SERVER,
        "base": BASE,
        "usuario_admin": DB_USER,
        "clave_admin": DB_PASSWORD,
        "usuario_app": USUARIO_APP,
        "clave_app": CLAVE_APP,
        "clave_admin_app": CLAVE_ADMIN_APP,
        "config_destino": str(tmp_path / "config.env"),
        **extra,
    }


@pytest.fixture(scope="module")
def servidor_instalado(tmp_path_factory):
    _limpiar()
    tmp = tmp_path_factory.mktemp("instalacion")
    _, estado, mensaje = _ejecutar("servidor", _datos_servidor(tmp), tmp)
    assert estado == "OK", mensaje
    yield tmp, mensaje
    _limpiar()


def test_generar_clave_es_robusta():
    claves = {instalacion.cmd_generar_clave({}) for _ in range(20)}
    assert len(claves) == 20
    for c in claves:
        assert len(c) == 20
        assert any(x.islower() for x in c) and any(x.isupper() for x in c) and any(x.isdigit() for x in c)


def test_probar_conexion_valida_y_con_clave_mala(tmp_path):
    codigo, estado, mensaje = _ejecutar(
        "probar", {"servidor": DB_SERVER, "usuario": DB_USER, "clave": DB_PASSWORD}, tmp_path
    )
    assert (codigo, estado) == (0, "OK")
    assert "SQL Server" in mensaje
    codigo, estado, mensaje = _ejecutar(
        "probar", {"servidor": DB_SERVER, "usuario": DB_USER, "clave": "clave-incorrecta-xyz"}, tmp_path
    )
    assert (codigo, estado) == (1, "ERROR")
    assert "usuario o la contrasena" in mensaje


def test_probar_servidor_inexistente_da_un_mensaje_util(tmp_path):
    _, estado, mensaje = _ejecutar("probar", {"servidor": "127.0.0.1,1", "usuario": "x", "clave": "y"}, tmp_path)
    assert estado == "ERROR"
    assert "TCP/IP" in mensaje


def test_servidor_crea_esquema_usuario_y_config(servidor_instalado):
    tmp, mensaje = servidor_instalado
    assert "Esquema creado" in mensaje
    assert "Migraciones al dia" in mensaje
    assert "'admin' creado" in mensaje
    with _admin_pyodbc(BASE) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM dbo.schema_migrations")
        assert cur.fetchone()[0] > 50
        cur.execute(
            "SELECT r.nombre FROM dbo.usuarios u JOIN dbo.roles r ON r.id_rol = u.id_rol "
            "WHERE u.nombre_usuario = 'admin'"
        )
        assert cur.fetchone()[0] == "ADMIN"
    config = instalacion._leer_config(tmp / "config.env")
    assert config["MODO_INSTALACION"] == "SERVIDOR"
    assert config["DB_USER"] == USUARIO_APP
    assert config["DB_PASSWORD"] == CLAVE_APP
    assert config["DB_NAME"] == BASE
    datos = (tmp / "datos_estaciones.txt").read_text(encoding="utf-8")
    assert CLAVE_APP in datos
    assert BASE in datos


def test_la_clave_de_admin_de_la_app_funciona(servidor_instalado):
    with _admin_pyodbc(BASE) as conn:
        cur = conn.cursor()
        cur.execute("SELECT clave FROM dbo.usuarios WHERE nombre_usuario = 'admin'")
        assert bcrypt.checkpw(CLAVE_ADMIN_APP.encode(), cur.fetchone()[0].encode())


def test_el_usuario_de_la_app_puede_operar_pero_no_cambiar_el_esquema(servidor_instalado):
    cadena = instalacion._cadena_odbc(DB_SERVER, BASE, USUARIO_APP, CLAVE_APP, False)
    with pyodbc.connect(cadena, autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM dbo.usuarios")
        assert cur.fetchone()[0] >= 1
        cur.execute("INSERT INTO dbo.categorias (nombre) VALUES ('Prueba instalador')")
        cur.execute("DELETE FROM dbo.categorias WHERE nombre = 'Prueba instalador'")
        for sentencia in (
            "CREATE TABLE dbo.intruso (x INT)",
            "DROP TABLE dbo.categorias",
            "ALTER TABLE dbo.categorias ADD y INT",
        ):
            with pytest.raises(pyodbc.ProgrammingError):
                cur.execute(sentencia)


def test_servidor_es_idempotente_y_conserva_la_clave_de_admin(servidor_instalado):
    tmp, _ = servidor_instalado
    _, estado, mensaje = _ejecutar("servidor", _datos_servidor(tmp, clave_admin_app="Otra-Clave-Distinta-1"), tmp)
    assert estado == "OK", mensaje
    assert "ya tenia esquema" in mensaje
    assert "ya existia" in mensaje
    with _admin_pyodbc(BASE) as conn:
        cur = conn.cursor()
        cur.execute("SELECT clave FROM dbo.usuarios WHERE nombre_usuario = 'admin'")
        assert bcrypt.checkpw(CLAVE_ADMIN_APP.encode(), cur.fetchone()[0].encode())


@pytest.mark.parametrize(
    ("extra", "texto"),
    [
        ({"base": "x; DROP DATABASE master"}, "base de datos"),
        ({"usuario_app": "bad name'--"}, "usuario SQL"),
        ({"clave_app": "corta"}, "al menos 12"),
        ({"clave_admin_app": "debil"}, "no valida"),
    ],
)
def test_servidor_rechaza_datos_invalidos(tmp_path, extra, texto):
    _, estado, mensaje = _ejecutar("servidor", _datos_servidor(tmp_path, **extra), tmp_path)
    assert estado == "ERROR"
    assert texto in mensaje


def test_servidor_con_credenciales_de_admin_incorrectas(tmp_path):
    _, estado, mensaje = _ejecutar("servidor", _datos_servidor(tmp_path, clave_admin="mala-clave-123"), tmp_path)
    assert estado == "ERROR"
    assert "usuario o la contrasena" in mensaje
    assert not (tmp_path / "config.env").exists()  # no deja configuracion a medias


def test_estacion_valida_la_conexion_y_escribe_config(servidor_instalado, tmp_path):
    destino = tmp_path / "config.env"
    destino.write_text("SMTP_USER=correo@ejemplo.com\n", encoding="utf-8")
    codigo, estado, mensaje = _ejecutar(
        "estacion",
        {
            "servidor": DB_SERVER,
            "base": BASE,
            "usuario": USUARIO_APP,
            "clave": CLAVE_APP,
            "config_destino": str(destino),
        },
        tmp_path,
    )
    assert (codigo, estado) == (0, "OK"), mensaje
    config = instalacion._leer_config(destino)
    assert config["MODO_INSTALACION"] == "ESTACION"
    assert config["DB_USER"] == USUARIO_APP
    assert config["SMTP_USER"] == "correo@ejemplo.com"  # conserva lo que ya habia


def test_estacion_con_clave_incorrecta_no_escribe_config(servidor_instalado, tmp_path):
    destino = tmp_path / "config.env"
    _, estado, mensaje = _ejecutar(
        "estacion",
        {"servidor": DB_SERVER, "base": BASE, "usuario": USUARIO_APP, "clave": "mala", "config_destino": str(destino)},
        tmp_path,
    )
    assert estado == "ERROR"
    assert "contrasena" in mensaje
    assert not destino.exists()


def test_estacion_contra_base_sin_esquema(tmp_path):
    datos = {
        "servidor": DB_SERVER,
        "base": "master",
        "usuario": DB_USER,
        "clave": DB_PASSWORD,
        "config_destino": str(tmp_path / "c.env"),
    }
    _, estado, mensaje = _ejecutar("estacion", datos, tmp_path)
    assert estado == "ERROR"
    assert "esquema" in mensaje


def test_actualizar_aplica_migraciones_con_admin(servidor_instalado):
    tmp, _ = servidor_instalado
    datos = {"usuario_admin": DB_USER, "clave_admin": DB_PASSWORD, "config_destino": str(tmp / "config.env")}
    codigo, estado, mensaje = _ejecutar("actualizar", datos, tmp)
    assert (codigo, estado) == (0, "OK"), mensaje


def test_actualizar_sin_instalacion_previa(tmp_path):
    datos = {"usuario_admin": "x", "clave_admin": "y", "config_destino": str(tmp_path / "nada.env")}
    _, estado, mensaje = _ejecutar("actualizar", datos, tmp_path)
    assert estado == "ERROR"
    assert "instalacion previa" in mensaje


def test_host_para_estaciones_no_devuelve_localhost():
    assert instalacion._host_para_estaciones("localhost,1433").endswith(",1433")
    assert not instalacion._host_para_estaciones("localhost,1433").startswith("localhost")
    assert instalacion._host_para_estaciones("SRV-CAJA\\SQLEXPRESS") == "SRV-CAJA\\SQLEXPRESS"
    assert instalacion._host_para_estaciones("192.168.0.5,1433") == "192.168.0.5,1433"


def test_servidor_sin_nombre_de_servidor():
    with pytest.raises(ErrorInstalacion, match="servidor"):
        instalacion._servidor_sql({"servidor": "  "})


def test_validar_clave_acepta_y_rechaza(tmp_path):
    _, estado, _ = _ejecutar("validar-clave", {"clave": "Admin-Prueba-2026"}, tmp_path)
    assert estado == "OK"
    _, estado, mensaje = _ejecutar("validar-clave", {"clave": "debil"}, tmp_path)
    assert estado == "ERROR"
    assert "politica" in mensaje


def test_probar_con_requiere_sysadmin(servidor_instalado, tmp_path):
    base = {"servidor": DB_SERVER, "requiere_sysadmin": True}
    _, estado, _ = _ejecutar("probar", {**base, "usuario": DB_USER, "clave": DB_PASSWORD}, tmp_path)
    assert estado == "OK"
    # El usuario SQL de la app NO es administrador: el instalador no debe dejar continuar con el.
    _, estado, mensaje = _ejecutar("probar", {**base, "usuario": USUARIO_APP, "clave": CLAVE_APP}, tmp_path)
    assert estado == "ERROR"
    assert "sysadmin" in mensaje
