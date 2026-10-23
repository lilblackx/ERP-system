"""Tests de app/instalacion.py (las herramientas que usa el instalador), contra SQL Server real.
Crean una base y un login temporales (dj_inst_test / dj_inst_app) y los eliminan al terminar."""

import json
from pathlib import Path

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
    assert instalacion._clave_db(config) == CLAVE_APP
    if instalacion.dpapi.DISPONIBLE:
        # Protegida con DPAPI de esta PC: el archivo no trae la clave en claro.
        assert "DB_PASSWORD" not in config and CLAVE_APP not in (tmp / "config.env").read_text(encoding="utf-8")
    assert config["DB_NAME"] == BASE
    datos = (tmp / "datos_estaciones.txt").read_text(encoding="utf-8")
    assert CLAVE_APP in datos
    # El archivo avisa que se borra solo, y cuando (24 h): ver app/services/datos_estaciones.py.
    assert "SE ELIMINA SOLO" in datos and "24 horas" in datos
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


# ── configurar-sql: registro de Windows y servicio simulados (no se toca el SQL Server real) ──


class _SqlFalso:
    """Registro + servicios en memoria. Estado inicial: Express recien instalado (solo Windows auth,
    TCP deshabilitado, puerto dinamico)."""

    def __init__(self, monkeypatch, instancias=None):
        self.reg = {}
        self.servicios = {}
        self.acciones = []
        for nombre, id_ in ({"SQLEXPRESS": "MSSQL16.SQLEXPRESS"} if instancias is None else instancias).items():
            self.reg[(instalacion.RAIZ_SQL + r"\Instance Names\SQL", nombre)] = id_
            self.reg[(instalacion._ruta_instancia(id_), "LoginMode")] = 1
            self.reg[(instalacion._ruta_tcp(id_), "Enabled")] = 0
            self.reg[(instalacion._ruta_tcp(id_) + r"\IPAll", "TcpPort")] = ""
            self.reg[(instalacion._ruta_tcp(id_) + r"\IPAll", "TcpDynamicPorts")] = "52111"
            self.servicios[nombre if nombre == "MSSQLSERVER" else f"MSSQL${nombre}"] = 4
        monkeypatch.setattr(instalacion, "_reg_leer", lambda ruta, nombre: self.reg.get((ruta, nombre)))
        monkeypatch.setattr(
            instalacion, "_reg_escribir", lambda ruta, nombre, valor: self.reg.__setitem__((ruta, nombre), valor)
        )
        monkeypatch.setattr(
            instalacion,
            "_reg_valores",
            lambda ruta: {n: v for (r, n), v in self.reg.items() if r == ruta},
        )
        monkeypatch.setattr(instalacion, "_estado_servicio", lambda s: self.servicios.get(s))
        monkeypatch.setattr(instalacion, "_net", self._net)
        self.firewall = []
        monkeypatch.setattr(instalacion, "_netsh", self._netsh)

    def _netsh(self, *args):
        self.firewall.append(args)

        class R:
            stdout = stderr = ""
            returncode = 0

        return R()

    def _net(self, accion, servicio, *extra):
        self.acciones.append((accion, servicio))
        if servicio in self.servicios:
            self.servicios[servicio] = 4 if accion == "start" else 1

        class R:
            stdout = stderr = ""
            returncode = 0

        return R()


def test_configurar_sql_diagnostico_no_modifica_nada(monkeypatch, tmp_path):
    sql = _SqlFalso(monkeypatch)
    antes = dict(sql.reg)
    _, estado, mensaje = _ejecutar(
        "configurar-sql", {"servidor": "localhost", "puerto": "1433", "solo_diagnostico": True}, tmp_path
    )
    assert estado == "OK"
    assert mensaje.startswith("CAMBIOS:")
    assert "TCP/IP" in mensaje and "mixta" in mensaje and "1433" in mensaje
    assert sql.reg == antes and sql.acciones == []


def test_configurar_sql_aplica_los_cambios_y_reinicia(monkeypatch, tmp_path):
    sql = _SqlFalso(monkeypatch)
    _, estado, mensaje = _ejecutar("configurar-sql", {"servidor": "localhost", "puerto": "1433"}, tmp_path)
    assert estado == "OK" and mensaje.startswith("CONFIGURADO:")
    id_ = "MSSQL16.SQLEXPRESS"
    assert sql.reg[(instalacion._ruta_instancia(id_), "LoginMode")] == 2
    assert sql.reg[(instalacion._ruta_tcp(id_), "Enabled")] == 1
    assert sql.reg[(instalacion._ruta_tcp(id_) + r"\IPAll", "TcpPort")] == "1433"
    assert sql.reg[(instalacion._ruta_tcp(id_) + r"\IPAll", "TcpDynamicPorts")] == ""
    assert sql.acciones == [("stop", "MSSQL$SQLEXPRESS"), ("start", "MSSQL$SQLEXPRESS")]
    # Segunda vez: ya esta todo, no hay cambios ni reinicio.
    sql.acciones.clear()
    _, estado, mensaje = _ejecutar("configurar-sql", {"servidor": "localhost", "puerto": "1433"}, tmp_path)
    assert mensaje.startswith("SIN CAMBIOS:") and sql.acciones == []


def test_configurar_sql_reinicia_sql_agent_si_estaba_activo(monkeypatch, tmp_path):
    sql = _SqlFalso(monkeypatch)
    sql.servicios["SQLAgent$SQLEXPRESS"] = 4
    _ejecutar("configurar-sql", {"servidor": "localhost", "puerto": "1433"}, tmp_path)
    assert ("start", "SQLAgent$SQLEXPRESS") in sql.acciones


def test_configurar_sql_servidor_remoto_se_omite(monkeypatch, tmp_path):
    sql = _SqlFalso(monkeypatch)
    _, estado, mensaje = _ejecutar("configurar-sql", {"servidor": "OTRO-PC,1433", "puerto": "1433"}, tmp_path)
    assert estado == "OK" and mensaje.startswith("OMITIDO:") and sql.acciones == []


def test_configurar_sql_instancia_inexistente_o_ambigua(monkeypatch, tmp_path):
    _SqlFalso(monkeypatch, {"UNO": "MSSQL16.UNO", "DOS": "MSSQL16.DOS"})
    _, estado, mensaje = _ejecutar("configurar-sql", {"servidor": "localhost\\TRES", "puerto": "1433"}, tmp_path)
    assert estado == "ERROR" and "TRES" in mensaje and "UNO" in mensaje
    _, estado, mensaje = _ejecutar("configurar-sql", {"servidor": "localhost", "puerto": "1433"}, tmp_path)
    assert estado == "ERROR" and "varias instancias" in mensaje


def test_configurar_sql_puerto_ocupado_por_otra_instancia(monkeypatch, tmp_path):
    sql = _SqlFalso(monkeypatch, {"UNO": "MSSQL16.UNO", "DOS": "MSSQL16.DOS"})
    sql.reg[(instalacion._ruta_tcp("MSSQL16.UNO") + r"\IPAll", "TcpPort")] = "1433"
    _, estado, mensaje = _ejecutar("configurar-sql", {"servidor": "localhost\\DOS", "puerto": "1433"}, tmp_path)
    assert estado == "ERROR" and "UNO" in mensaje and sql.acciones == []


@pytest.mark.parametrize("puerto", ["abc", "0", "70000"])
def test_configurar_sql_puerto_invalido(monkeypatch, tmp_path, puerto):
    _SqlFalso(monkeypatch)
    _, estado, mensaje = _ejecutar("configurar-sql", {"servidor": "localhost", "puerto": puerto}, tmp_path)
    assert estado == "ERROR" and "puerto" in mensaje.lower()


def test_configurar_sql_sin_sql_server(monkeypatch, tmp_path):
    _SqlFalso(monkeypatch, instancias={})
    _, estado, mensaje = _ejecutar("configurar-sql", {"servidor": "localhost", "puerto": "1433"}, tmp_path)
    assert estado == "ERROR" and "ninguna instancia" in mensaje


def test_configurar_sql_servicio_que_no_arranca(monkeypatch, tmp_path):
    sql = _SqlFalso(monkeypatch)
    monkeypatch.setattr(instalacion, "_net", lambda accion, servicio, *e: sql._net("stop", servicio))
    _, estado, mensaje = _ejecutar("configurar-sql", {"servidor": "localhost", "puerto": "1433"}, tmp_path)
    assert estado == "ERROR" and "no volvio a iniciar" in mensaje


def test_configurar_sql_instancia_predeterminada_de_sql_server_2019(monkeypatch, tmp_path):
    # SQL Server 2019 instalado a mano: instancia predeterminada (MSSQL15), TCP ya habilitado en 1433,
    # solo falta el modo mixto. Solo se cambia eso y se reinicia MSSQLSERVER (con su SQL Agent).
    sql = _SqlFalso(monkeypatch, {"MSSQLSERVER": "MSSQL15.MSSQLSERVER"})
    id_ = "MSSQL15.MSSQLSERVER"
    sql.reg[(instalacion._ruta_tcp(id_), "Enabled")] = 1
    sql.reg[(instalacion._ruta_tcp(id_) + r"\IPAll", "TcpPort")] = "1433"
    sql.reg[(instalacion._ruta_tcp(id_) + r"\IPAll", "TcpDynamicPorts")] = ""
    sql.servicios["SQLSERVERAGENT"] = 4
    _, estado, mensaje = _ejecutar(
        "configurar-sql", {"servidor": "localhost", "puerto": "1433", "solo_diagnostico": True}, tmp_path
    )
    assert estado == "OK" and mensaje.startswith("CAMBIOS:") and "mixta" in mensaje
    assert "TCP/IP" not in mensaje and "puerto" not in mensaje
    _ejecutar("configurar-sql", {"servidor": "localhost", "puerto": "1433"}, tmp_path)
    assert sql.reg[(instalacion._ruta_instancia(id_), "LoginMode")] == 2
    assert sql.acciones == [("stop", "MSSQLSERVER"), ("start", "MSSQLSERVER"), ("start", "SQLSERVERAGENT")]


# ── respaldos: trabajos de SQL Server Agent reales; la unica carpeta es la del contenedor de SQL Server ──

CARPETA_RESPALDOS_TEST = "/var/opt/mssql/data/nexo_respaldos_test"
RUTA_DRIVE_TEST = "G:\\Mi unidad\\Nexo"
TRABAJOS_RESPALDO = (
    instalacion.TRABAJO_COMPLETO,
    instalacion.TRABAJO_LOG,
    instalacion.TRABAJO_MANTENIMIENTO,
)


def _borrar_trabajos_respaldo():
    with _admin_pyodbc() as conn:
        for nombre in TRABAJOS_RESPALDO:
            conn.execute(
                f"IF EXISTS (SELECT 1 FROM msdb.dbo.sysjobs WHERE name = N'{nombre}') "
                f"EXEC msdb.dbo.sp_delete_job @job_name = N'{nombre}', @delete_unused_schedule = 1"
            )


@pytest.fixture
def respaldos_sin_efectos_externos(monkeypatch):
    """No se toca el servicio SQL Agent ni el Programador de tareas de la PC donde corren los tests."""
    llamadas = {"agente": [], "drive": []}
    monkeypatch.setattr(instalacion, "_asegurar_agente", lambda i: llamadas["agente"].append(i) or "")
    monkeypatch.setattr(instalacion, "_programar_copia_drive", lambda *a: llamadas["drive"].append(a) or "")
    _borrar_trabajos_respaldo()
    yield llamadas
    _borrar_trabajos_respaldo()


def _datos_respaldos(**extra):
    return {
        "servidor": DB_SERVER,
        "base": BASE,
        "usuario_admin": DB_USER,
        "clave_admin": DB_PASSWORD,
        "carpeta": CARPETA_RESPALDOS_TEST,
        "ruta_drive": RUTA_DRIVE_TEST,
        "omitir_prueba_drive": True,  # la prueba de la carpeta de Drive tiene sus propios tests
        **extra,
    }


def test_respaldos_crea_los_trabajos_con_sus_horarios(servidor_instalado, respaldos_sin_efectos_externos, tmp_path):
    _, estado, mensaje = _ejecutar("respaldos", _datos_respaldos(dias_retencion="15"), tmp_path)
    assert estado == "OK", mensaje
    assert "15 dias" in mensaje
    with _admin_pyodbc() as conn:
        cur = conn.cursor()
        cur.execute("SELECT recovery_model_desc FROM sys.databases WHERE name = ?", BASE)
        assert cur.fetchone()[0] == "FULL"
        cur.execute(
            "SELECT j.name, s.freq_type, s.freq_subday_type, s.freq_subday_interval, s.active_start_time "
            "FROM msdb.dbo.sysjobs j JOIN msdb.dbo.sysjobschedules js ON js.job_id = j.job_id "
            "JOIN msdb.dbo.sysschedules s ON s.schedule_id = js.schedule_id WHERE j.name LIKE N'Nexo ERP -%'"
        )
        horarios = {fila[0]: tuple(fila[1:]) for fila in cur.fetchall()}
        assert horarios[instalacion.TRABAJO_COMPLETO] == (4, 1, 0, 190000)  # diario 19:00
        assert horarios[instalacion.TRABAJO_LOG] == (4, 4, 30, 0)  # cada 30 minutos
        assert horarios[instalacion.TRABAJO_MANTENIMIENTO][0] == 8  # semanal
        cur.execute(
            "SELECT s.step_name, s.command FROM msdb.dbo.sysjobsteps s JOIN msdb.dbo.sysjobs j ON j.job_id = s.job_id "
            "WHERE j.name = ? ORDER BY s.step_id",
            instalacion.TRABAJO_COMPLETO,
        )
        pasos = cur.fetchall()
        assert [p[0] for p in pasos] == ["Respaldo completo", "Borrar respaldos antiguos"]
        assert f"BACKUP DATABASE [{BASE}]" in pasos[0][1] and "DATEADD(DAY, -15" in pasos[1][1]
        # El respaldo completo inicial ya existe: sin el, el primer respaldo de log fallaria.
        cur.execute(
            "SELECT COUNT(*) FROM msdb.dbo.backupset WHERE database_name = ? AND type = 'D' "
            "AND is_copy_only = 0 AND backup_start_date > DATEADD(MINUTE, -5, GETDATE())",
            BASE,
        )
        assert cur.fetchone()[0] >= 1
    assert respaldos_sin_efectos_externos["agente"] == [None]
    (copia_drive,) = respaldos_sin_efectos_externos["drive"]
    assert copia_drive[:3] == (CARPETA_RESPALDOS_TEST, RUTA_DRIVE_TEST, 15)


def test_respaldos_se_pueden_repetir_sin_duplicar_trabajos(
    servidor_instalado, respaldos_sin_efectos_externos, tmp_path
):
    for _ in range(2):
        _, estado, mensaje = _ejecutar("respaldos", _datos_respaldos(), tmp_path)
        assert estado == "OK", mensaje
    with _admin_pyodbc() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM msdb.dbo.sysjobs WHERE name LIKE N'Nexo ERP -%'")
        assert cur.fetchone()[0] == 3


def test_respaldos_los_comandos_de_los_pasos_se_ejecutan(servidor_instalado, respaldos_sin_efectos_externos, tmp_path):
    # Los comandos de los pasos son los que correra SQL Agent: se ejecutan tal cual, uno a uno.
    _, estado, mensaje = _ejecutar("respaldos", _datos_respaldos(), tmp_path)
    assert estado == "OK", mensaje
    with _admin_pyodbc() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT s.command FROM msdb.dbo.sysjobsteps s JOIN msdb.dbo.sysjobs j ON j.job_id = s.job_id "
            "WHERE j.name IN (?, ?) ORDER BY j.name, s.step_id",
            instalacion.TRABAJO_COMPLETO,
            instalacion.TRABAJO_LOG,
        )
        comandos = [fila[0] for fila in cur.fetchall()]
        assert len(comandos) == 3
        for comando in comandos:
            conn.execute(comando)


def test_respaldos_con_ruta_de_drive_programa_la_copia(servidor_instalado, respaldos_sin_efectos_externos, tmp_path):
    ruta = r"G:\Mi unidad\Respaldos Nexo"
    datos = _datos_respaldos(ruta_drive=ruta, config_destino=str(tmp_path / "c.env"))
    _, estado, mensaje = _ejecutar("respaldos", datos, tmp_path)
    assert estado == "OK", mensaje
    assert "Google Drive" in mensaje and ruta in mensaje
    assert respaldos_sin_efectos_externos["drive"] == [(CARPETA_RESPALDOS_TEST, ruta, 3, tmp_path)]


@pytest.mark.parametrize(
    "extra, texto",
    [
        ({"carpeta": "respaldos"}, "ruta completa"),
        ({"carpeta": "C:\\Res'paldos"}, "ruta completa"),
        ({"ruta_drive": "Mi unidad\\Nexo"}, "ruta completa"),
        ({"ruta_drive": "G:\\Mi unidad';--"}, "ruta completa"),
        ({"dias_retencion": "0"}, "dias de retencion"),
        ({"dias_retencion": "mucho"}, "dias de retencion"),
        ({"base": "mala; DROP"}, "base de datos"),
    ],
)
def test_respaldos_rechaza_datos_invalidos(extra, texto, tmp_path):
    _, estado, mensaje = _ejecutar("respaldos", _datos_respaldos(**extra), tmp_path)
    assert estado == "ERROR" and texto in mensaje


def test_respaldos_en_sql_server_express_explica_que_falta_sql_agent(monkeypatch, servidor_instalado, tmp_path):
    original = instalacion._motor

    class _Conexion:
        def __init__(self, real):
            self._real = real

        def __enter__(self):
            self._c = self._real.connect().__enter__()
            return self

        def __exit__(self, *a):
            return self._c.__exit__(*a)

        def execute(self, consulta, *a, **k):
            if "EngineEdition" in str(consulta):
                return type("R", (), {"scalar": lambda s: 4})()
            return self._c.execute(consulta, *a, **k)

    class _MotorExpress:
        def __init__(self, real):
            self._real = real

        def connect(self):
            return _Conexion(self._real)

        def dispose(self):
            self._real.dispose()

    monkeypatch.setattr(instalacion, "_motor", lambda *a, **k: _MotorExpress(original(*a, **k)))
    _, estado, mensaje = _ejecutar("respaldos", _datos_respaldos(), tmp_path)
    assert estado == "ERROR" and "SQL Server Agent" in mensaje


def test_copia_drive_escribe_el_script_y_crea_la_tarea(monkeypatch, tmp_path):
    ejecutados = []

    class R:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(instalacion.subprocess, "run", lambda args, **k: ejecutados.append(args) or R())
    monkeypatch.setattr(instalacion, "_usuario_windows", lambda: "PC\\luis")
    aviso = instalacion._programar_copia_drive(r"C:\Respaldos\Nexo", r"G:\Mi unidad\Nexo", 45, tmp_path)
    assert aviso == ""
    script = (tmp_path / "copiar_respaldos_drive.ps1").read_text(encoding="utf-8-sig")
    assert r"$origen = 'C:\Respaldos\Nexo'" in script
    assert r"$destino = 'G:\Mi unidad\Nexo'" in script
    assert "$dias = 45" in script
    (schtasks,) = ejecutados
    assert schtasks[:2] == ["schtasks", "/Create"]
    assert schtasks[schtasks.index("/MO") + 1] == "30"
    assert schtasks[schtasks.index("/RU") + 1] == "PC\\luis" and "/IT" in schtasks


def test_copia_drive_si_falla_la_tarea_devuelve_un_aviso(monkeypatch, tmp_path):
    class R:
        returncode, stdout, stderr = 1, "", "ERROR: Acceso denegado."

    monkeypatch.setattr(instalacion.subprocess, "run", lambda args, **k: R())
    aviso = instalacion._programar_copia_drive(r"C:\R", r"G:\D", 30, tmp_path)
    assert "Acceso denegado" in aviso


# ── respaldos: alertas por correo cuando falla un trabajo ──

ALERTAS = {
    "alerta_correos": "uno@ejemplo.com; dos@ejemplo.com",
    "smtp_usuario": "remitente@ejemplo.com",
    "smtp_clave": "clave de aplicacion",
}
CONTEXTO_ALERTAS = {"base": "mi_base", "carpeta": r"C:\Respaldos\Nexo", "dias": 3}


def _pasos_del_trabajo(nombre):
    with _admin_pyodbc() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT s.step_id, s.step_name, s.command, s.on_success_action, s.on_fail_action, s.on_fail_step_id "
            "FROM msdb.dbo.sysjobsteps s JOIN msdb.dbo.sysjobs j ON j.job_id = s.job_id WHERE j.name = ? "
            "ORDER BY s.step_id",
            nombre,
        )
        return cur.fetchall()


def test_respaldos_con_alertas_agrega_un_paso_de_alerta_html_de_importancia_alta(
    servidor_instalado, respaldos_sin_efectos_externos, tmp_path
):
    # En el SQL Server de pruebas (Linux) no existe Database Mail: aqui se verifica la estructura de los trabajos;
    # el envio real se prueba en SQL Server para Windows.
    _, estado, mensaje = _ejecutar("respaldos", _datos_respaldos(**ALERTAS), tmp_path)
    assert estado == "OK", mensaje
    esperado = {
        instalacion.TRABAJO_COMPLETO: 2,
        instalacion.TRABAJO_LOG: 1,
        instalacion.TRABAJO_MANTENIMIENTO: 2,
    }
    for trabajo, n_pasos in esperado.items():
        pasos = _pasos_del_trabajo(trabajo)
        assert len(pasos) == n_pasos + 1
        *reales, alerta = pasos
        assert alerta[1] == "Enviar alerta por correo"
        assert alerta[3] == 2 and alerta[4] == 2  # el trabajo termina como fallido
        for paso in reales:
            assert paso[5] == alerta[0] and paso[4] == 4  # si falla, va al paso de alerta
        assert "@importance = 'High'" in alerta[2] and "@body_format = 'HTML'" in alerta[2]
        assert "uno@ejemplo.com;dos@ejemplo.com" in alerta[2]
    with _admin_pyodbc() as conn:
        cur = conn.cursor()
        # La alerta la envia el paso (formato e importancia propios), no una notificacion de operador de SQL Agent.
        cur.execute("SELECT COUNT(*) FROM msdb.dbo.sysjobs WHERE name LIKE N'Nexo ERP -%' AND notify_level_email <> 0")
        assert cur.fetchone()[0] == 0


def test_respaldos_sin_destinatarios_no_agrega_paso_de_alerta(
    servidor_instalado, respaldos_sin_efectos_externos, tmp_path
):
    _, estado, mensaje = _ejecutar("respaldos", _datos_respaldos(), tmp_path)
    assert estado == "OK" and "Alertas por correo" not in mensaje
    assert [p[1] for p in _pasos_del_trabajo(instalacion.TRABAJO_LOG)] == ["Respaldo de log"]
    assert _pasos_del_trabajo(instalacion.TRABAJO_LOG)[0][4] == 2  # si falla, el trabajo termina fallido


def test_respaldos_repetidos_con_alertas_actualizan_los_destinatarios(
    servidor_instalado, respaldos_sin_efectos_externos, tmp_path
):
    _ejecutar("respaldos", _datos_respaldos(**ALERTAS), tmp_path)
    _, estado, mensaje = _ejecutar(
        "respaldos", _datos_respaldos(**{**ALERTAS, "alerta_correos": "tres@ejemplo.com"}), tmp_path
    )
    assert estado == "OK", mensaje
    alerta = _pasos_del_trabajo(instalacion.TRABAJO_LOG)[-1]
    assert "tres@ejemplo.com" in alerta[2] and "uno@ejemplo.com" not in alerta[2]


def test_el_correo_de_alerta_es_html_ascii_y_no_se_trunca():
    comando = instalacion._comando_alerta_fallo("a@x.com;b@x.com")
    assert comando.isascii()  # los acentos van como entidades HTML / NCHAR: no depende de la codificacion
    assert "$(ESCAPE_NONE(JOBID))" in comando  # token de SQL Agent: identifica el trabajo que fallo
    assert "@importance = 'High'" in comando and "@body_format = 'HTML'" in comando
    assert "CAST(N'' AS NVARCHAR(MAX)) + " in comando  # concatenar literales de 4000 caracteres truncaria el cuerpo
    assert "REPLACE(REPLACE(REPLACE(@detalle" in comando or "@detalle = REPLACE(REPLACE(REPLACE(" in comando


def test_el_correo_de_prueba_tambien_es_html_de_importancia_alta():
    comando = instalacion._comando_correo_prueba("a@x.com;b@x.com", "mi_base", r"C:\Respaldos\Nexo", 3)
    assert comando.isascii()
    assert "@importance = 'High'" in comando and "@body_format = 'HTML'" in comando
    assert "mi_base" in comando and "a@x.com<br>b@x.com" in comando and "3 d&iacute;as" in comando


def test_alertas_configura_database_mail_reinicia_agente_y_envia_prueba(monkeypatch):
    ejecutadas = []
    monkeypatch.setattr(instalacion, "_ejecutar_con_parametros", lambda motor, s: ejecutadas.extend(s))
    reinicios = []
    monkeypatch.setattr(instalacion, "_reiniciar_agente", lambda i: reinicios.append(i) or "")
    alertas = instalacion._validar_alertas({**ALERTAS, "smtp_puerto": "465"})
    assert instalacion._configurar_alertas(object(), alertas, "SQL2019", True, CONTEXTO_ALERTAS) == ""
    sqls = [s for s, _ in ejecutadas]
    cuenta = next(p for s, p in ejecutadas if "sysmail_add_account_sp" in s)
    assert cuenta == (
        instalacion.CUENTA_CORREO,
        "remitente@ejemplo.com",
        "smtp.gmail.com",
        465,
        "remitente@ejemplo.com",
        "clave de aplicacion",
    )
    assert any("sp_set_sqlagent_properties" in s for s in sqls)
    assert "sp_send_dbmail" in sqls[-1] and "@importance = 'High'" in sqls[-1]
    assert reinicios == ["SQL2019"]


def test_alertas_servidor_remoto_no_reinicia_el_agente(monkeypatch):
    monkeypatch.setattr(instalacion, "_ejecutar_con_parametros", lambda motor, s: None)
    monkeypatch.setattr(instalacion, "_reiniciar_agente", lambda i: pytest.fail("no debe reiniciar"))
    alertas = instalacion._validar_alertas(ALERTAS)
    assert instalacion._configurar_alertas(object(), alertas, None, False, CONTEXTO_ALERTAS) == ""


def test_alertas_si_database_mail_falla_deja_un_aviso(monkeypatch):
    def ejecutar(motor, sentencias):
        if any("Database Mail XPs" in s for s, _ in sentencias):
            raise RuntimeError("Database Mail no disponible")

    monkeypatch.setattr(instalacion, "_ejecutar_con_parametros", ejecutar)
    alertas = instalacion._validar_alertas(ALERTAS)
    aviso = instalacion._configurar_alertas(object(), alertas, None, True, CONTEXTO_ALERTAS)
    assert "a medias" in aviso and "Database Mail" in aviso


@pytest.mark.parametrize(
    "extra, texto",
    [
        ({"alerta_correos": "no-es-un-correo"}, "no es valido"),
        ({"alerta_correos": "a@b.com; x'y@b.com"}, "no es valido"),
        ({"smtp_usuario": ""}, "correo remitente"),
        ({"smtp_clave": ""}, "correo remitente"),
        ({"smtp_host": "host;malo"}, "no son validos"),
        ({"smtp_puerto": "0"}, "puerto SMTP"),
    ],
)
def test_respaldos_rechaza_alertas_invalidas(extra, texto, tmp_path):
    _, estado, mensaje = _ejecutar("respaldos", _datos_respaldos(**{**ALERTAS, **extra}), tmp_path)
    assert estado == "ERROR" and texto in mensaje


@pytest.mark.parametrize("comando", ["alerta", "prueba"])
def test_los_comandos_de_correo_son_t_sql_valido(comando):
    # SET PARSEONLY compila el lote sin ejecutarlo (no hace falta Database Mail): atrapa errores de sintaxis.
    if comando == "alerta":
        sql = instalacion._comando_alerta_fallo("a@x.com;b@x.com").replace("$(ESCAPE_NONE(JOBID))", "0x01")
    else:
        sql = instalacion._comando_correo_prueba("a@x.com;b@x.com", "mi_base", r"C:\Respaldos\Nexo", 3)
    with _admin_pyodbc() as conn:
        conn.execute("SET PARSEONLY ON")
        try:
            conn.execute(sql)
        finally:
            conn.execute("SET PARSEONLY OFF")


# ── carpeta de Google Drive: obligatoria y con prueba de escritura ──


def _unidad_inexistente():
    import string

    return next(f"{letra}:\\" for letra in reversed(string.ascii_uppercase) if not Path(f"{letra}:\\").exists())


def test_probar_drive_escribe_lee_y_borra_un_archivo_de_prueba(tmp_path):
    carpeta = tmp_path / "Drive" / "Nexo"
    (tmp_path / "Drive").mkdir()
    codigo, estado, mensaje = _ejecutar("probar-drive", {"ruta_drive": str(carpeta)}, tmp_path)
    assert (codigo, estado) == (0, "OK"), mensaje
    assert carpeta.is_dir() and list(carpeta.iterdir()) == []  # se creo el ultimo nivel y no quedo nada


def test_probar_drive_con_la_carpeta_ya_existente(tmp_path):
    _, estado, mensaje = _ejecutar("probar-drive", {"ruta_drive": str(tmp_path)}, tmp_path)
    assert estado == "OK", mensaje


def test_probar_drive_no_crea_carpetas_padre_por_un_error_de_tipeo(tmp_path):
    destino = tmp_path / "Mi unidd" / "Nexo"
    _, estado, mensaje = _ejecutar("probar-drive", {"ruta_drive": str(destino)}, tmp_path)
    assert estado == "ERROR" and "No existe la carpeta" in mensaje
    assert not (tmp_path / "Mi unidd").exists()


def test_probar_drive_con_unidad_inexistente_pide_abrir_google_drive(tmp_path):
    ruta = _unidad_inexistente() + "Mi unidad\\Nexo"
    _, estado, mensaje = _ejecutar("probar-drive", {"ruta_drive": ruta}, tmp_path)
    assert estado == "ERROR" and "Google Drive para escritorio" in mensaje


def test_probar_drive_si_la_ruta_es_un_archivo(tmp_path):
    archivo = tmp_path / "x.txt"
    archivo.write_text("x")
    _, estado, mensaje = _ejecutar("probar-drive", {"ruta_drive": str(archivo)}, tmp_path)
    assert estado == "ERROR" and "no es una carpeta" in mensaje


def test_probar_drive_sin_permiso_de_escritura(monkeypatch, tmp_path):
    def sin_permiso(self, *a, **k):
        raise PermissionError(13, "Acceso denegado")

    monkeypatch.setattr(Path, "write_text", sin_permiso)
    with pytest.raises(ErrorInstalacion, match="No se pudo escribir.*Acceso denegado"):
        instalacion._probar_ruta_drive(str(tmp_path))


@pytest.mark.parametrize("ruta", ["", "   ", "Mi unidad\\Nexo"])
def test_probar_drive_exige_una_ruta_completa(ruta, tmp_path):
    _, estado, mensaje = _ejecutar("probar-drive", {"ruta_drive": ruta}, tmp_path)
    assert estado == "ERROR" and ("obligatoria" in mensaje or "ruta completa" in mensaje)


def test_respaldos_exige_la_ruta_de_drive_y_no_crea_nada_sin_ella(
    servidor_instalado, respaldos_sin_efectos_externos, tmp_path
):
    _, estado, mensaje = _ejecutar("respaldos", _datos_respaldos(ruta_drive=""), tmp_path)
    assert estado == "ERROR" and "obligatoria" in mensaje
    with _admin_pyodbc() as conn:
        assert conn.execute("SELECT COUNT(*) FROM msdb.dbo.sysjobs WHERE name LIKE N'Nexo ERP -%'").fetchone()[0] == 0


def test_respaldos_con_drive_que_no_funciona_falla_antes_de_tocar_sql_server(
    servidor_instalado, respaldos_sin_efectos_externos, tmp_path
):
    datos = _datos_respaldos(ruta_drive=_unidad_inexistente() + "Nexo", omitir_prueba_drive=False)
    _, estado, mensaje = _ejecutar("respaldos", datos, tmp_path)
    assert estado == "ERROR" and "Google Drive para escritorio" in mensaje
    with _admin_pyodbc() as conn:
        assert conn.execute("SELECT COUNT(*) FROM msdb.dbo.sysjobs WHERE name LIKE N'Nexo ERP -%'").fetchone()[0] == 0


def test_respaldos_prueba_la_carpeta_de_drive_antes_de_crear_los_trabajos(
    servidor_instalado, respaldos_sin_efectos_externos, tmp_path
):
    drive = tmp_path / "Drive"
    drive.mkdir()
    datos = _datos_respaldos(ruta_drive=str(drive / "Nexo"), omitir_prueba_drive=False)
    _, estado, mensaje = _ejecutar("respaldos", datos, tmp_path)
    assert estado == "OK", mensaje
    assert (drive / "Nexo").is_dir() and list((drive / "Nexo").iterdir()) == []


# --- firewall: SQL Server solo para la red local --------------------------------------


def test_configurar_sql_abre_el_puerto_solo_a_la_red_local(monkeypatch, tmp_path):
    sql = _SqlFalso(monkeypatch)

    _, estado, mensaje = _ejecutar("configurar-sql", {"servidor": "localhost", "puerto": "1433"}, tmp_path)

    assert estado == "OK" and "Firewall:" in mensaje and "solo de la red local" in mensaje
    alta = next(a for a in sql.firewall if a[0] == "add")
    assert "remoteip=LocalSubnet" in alta and "localport=1433" in alta and "action=allow" in alta
    # La regla anterior con el mismo nombre se reemplaza (no se acumulan duplicadas).
    assert sql.firewall[0][0] == "delete"


def test_configurar_sql_reaplica_el_firewall_aunque_no_haya_otros_cambios(monkeypatch, tmp_path):
    sql = _SqlFalso(monkeypatch)
    _ejecutar("configurar-sql", {"servidor": "localhost", "puerto": "1433"}, tmp_path)
    sql.firewall.clear()

    _, _, mensaje = _ejecutar("configurar-sql", {"servidor": "localhost", "puerto": "1433"}, tmp_path)

    assert mensaje.startswith("SIN CAMBIOS:") and "Firewall:" in mensaje
    assert any(a[0] == "add" for a in sql.firewall)


def test_configurar_sql_diagnostico_no_toca_el_firewall(monkeypatch, tmp_path):
    sql = _SqlFalso(monkeypatch)

    _ejecutar("configurar-sql", {"servidor": "localhost", "puerto": "1433", "solo_diagnostico": True}, tmp_path)

    assert sql.firewall == []


def test_si_no_hay_permisos_para_el_firewall_avisa_pero_no_aborta(monkeypatch, tmp_path):
    sql = _SqlFalso(monkeypatch)

    class _Denegado:
        stdout = stderr = ""
        returncode = 1

    monkeypatch.setattr(instalacion, "_netsh", lambda *a: _Denegado())

    _, estado, mensaje = _ejecutar("configurar-sql", {"servidor": "localhost", "puerto": "1433"}, tmp_path)

    assert estado == "OK" and mensaje.startswith("CONFIGURADO:")
    assert "ejecute como administrador" in mensaje
    assert sql.acciones  # SQL Server se configuro y reinicio igual


def test_servidor_remoto_no_toca_el_firewall_local(monkeypatch, tmp_path):
    sql = _SqlFalso(monkeypatch)

    _ejecutar("configurar-sql", {"servidor": "OTRO-PC,1433", "puerto": "1433"}, tmp_path)

    assert sql.firewall == []
