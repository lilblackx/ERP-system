"""
Herramientas que ejecuta el instalador (Inno Setup, packaging/instalador.iss), empaquetadas
como Nexo-Herramientas.exe. Inno no puede hablar con SQL Server, asi que cada paso de base de
datos es un subcomando de este modulo.

Contrato con el instalador (para no pasar claves por la linea de comandos, que otros procesos
pueden ver):

    Nexo-Herramientas.exe <comando> --entrada entrada.json --salida resultado.txt

`entrada.json` lleva los datos y las claves; el instalador lo borra al terminar.
`resultado.txt` empieza con "OK" o "ERROR" en la primera linea y sigue con un mensaje para
mostrar al usuario. Codigo de salida: 0 si OK, 1 si ERROR.

Comandos:
    probar       prueba una conexion (SQL Server accesible, credenciales validas); con
                 requiere_sysadmin=true exige ademas que el usuario sea administrador
    configurar-sql  deja el SQL Server LOCAL listo para la app: TCP/IP habilitado, puerto fijo y modo de
                 autenticacion mixto (cambios en el registro + reinicio del servicio; requiere administrador
                 de Windows). El mensaje empieza con SIN CAMBIOS, CAMBIOS (solo_diagnostico), CONFIGURADO u
                 OMITIDO (servidor remoto)
    probar-drive prueba que se pueda escribir en la carpeta de Google Drive (existe la unidad, se crea la
                 carpeta si falta y un archivo de prueba se escribe, lee y borra)
    respaldos    crea en SQL Server Agent los trabajos de respaldo (completo diario 19:00, log cada 30 min),
                 limpieza por dias de retencion y mantenimiento semanal; con ruta_drive (obligatoria, se prueba antes)
                 programa ademas la copia a Google Drive para escritorio. Con alerta_correos + smtp_* configura
                 Database Mail y agrega a cada trabajo un paso que avisa por correo (HTML, importancia alta) si
                 falla. Falla si el SQL Server es Express (sin Agent)
    validar-clave  valida una contrasena contra la politica de la app (usuario `admin`)
    servidor     crea la base, el esquema, el usuario SQL propio de la app y el usuario `admin`,
                 y escribe config.env (MODO_INSTALACION=SERVIDOR) + datos_estaciones.txt
    estacion     valida la conexion con los datos del servidor y escribe config.env
                 (MODO_INSTALACION=ESTACION)
    actualizar   aplica las migraciones pendientes (reinstalacion/actualizacion del servidor)
    generar-clave  escribe una clave aleatoria segura en --salida
"""

import argparse
import json
import re
import secrets
import socket
import string
import subprocess
import sys
import urllib.parse
from pathlib import Path

import pyodbc
from sqlalchemy import create_engine, text

from app import config as app_config
from app.rutas import ARCHIVO_CONFIG, RAIZ_PROYECTO
from app.services import datos_estaciones
from app.utils import dpapi

DRIVER_ODBC = "ODBC Driver 18 for SQL Server"
ROL_APP_SIN_BORRADO = "nexo_app_sin_borrado"
NOMBRE_ARCHIVO_DATOS_ESTACIONES = datos_estaciones.NOMBRE_ARCHIVO
_IDENTIFICADOR_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,39}$")
_LOCALES = {"", ".", "(local)", "localhost", "127.0.0.1", "::1"}


class ErrorInstalacion(Exception):
    """Mensaje pensado para mostrarse tal cual al usuario del instalador."""


# ── Conexion ────────────────────────────────────────────────────────────────


def _cadena_odbc(servidor: str, base: str, usuario: str, clave: str, windows_auth: bool) -> str:
    # PWD entre llaves: sin ellas un ';' o '{' en la clave corta/rompe la cadena y SQL Server la rechaza.
    clave_odbc = "{" + clave.replace("}", "}}") + "}"
    autenticacion = "Trusted_Connection=yes;" if windows_auth else f"UID={usuario};PWD={clave_odbc};"
    return (
        f"DRIVER={{{DRIVER_ODBC}}};SERVER={servidor};DATABASE={base};{autenticacion}"
        "TrustServerCertificate=yes;Connection Timeout=10;"
    )


def _motor(servidor: str, base: str, usuario: str, clave: str, windows_auth: bool = False):
    cadena = _cadena_odbc(servidor, base, usuario, clave, windows_auth)
    return create_engine("mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(cadena), pool_pre_ping=True)


def _servidor_sql(datos: dict) -> str:
    """'host' o 'host\\instancia' + puerto opcional -> valor para SERVER= de ODBC."""
    host = str(datos.get("servidor", "")).strip()
    if not host:
        raise ErrorInstalacion("Falta el nombre o la direccion del servidor SQL.")
    puerto = str(datos.get("puerto", "")).strip()
    return f"{host},{puerto}" if puerto and "\\" not in host and "," not in host else host


def _traducir_error(exc: Exception) -> str:
    """Los errores de pyodbc traen codigos y texto de driver; el usuario del instalador necesita
    saber que hacer."""
    texto = str(exc)
    if "Login failed" in texto or "28000" in texto or "18456" in texto:
        return "SQL Server rechazo el usuario o la contrasena."
    if "Cannot open database" in texto:
        return "La base de datos indicada no existe o el usuario no tiene acceso a ella."
    if any(c in texto for c in ("08001", "Named Pipes", "TCP Provider", "timeout", "10061", "10060")):
        return (
            "No se pudo conectar con el servidor SQL. Revise el nombre/direccion y el puerto, que el "
            "servicio de SQL Server este iniciado, que TCP/IP este habilitado en SQL Server Configuration "
            "Manager y que el firewall permita el puerto."
        )
    if "IM002" in texto or "Data source name not found" in texto:
        return f"Falta '{DRIVER_ODBC}' en este equipo. Instalelo y vuelva a ejecutar el instalador."
    return texto.splitlines()[0][:300]


# ── Archivos de configuracion ───────────────────────────────────────────────


def _valores_clave_db(clave: str) -> tuple[dict[str, str], tuple[str, ...]]:
    """Como guardar la clave de la base en config.env: protegida con DPAPI de esta PC
    (DB_PASSWORD_DPAPI) y SIN la variable en claro, para que copiar el archivo a otra maquina no
    entregue la clave (ver app/proteger_env.py). Sin DPAPI (no Windows) queda en claro."""
    if dpapi.DISPONIBLE:
        return {"DB_PASSWORD_DPAPI": app_config.proteger_clave(clave)}, ("DB_PASSWORD",)
    return {"DB_PASSWORD": clave}, ()


def _clave_db(config: dict[str, str]) -> str:
    """Clave de la base de un config.env ya leido (protegida o en claro)."""
    return app_config.desproteger_clave(config.get("DB_PASSWORD_DPAPI", "")) or config.get("DB_PASSWORD", "")


def _escribir_config(destino: Path, valores: dict[str, str], quitar: tuple[str, ...] = ()) -> None:
    """Escribe/actualiza config.env conservando las claves que ya tenia (SMTP, etc.)."""
    existentes: dict[str, str] = {}
    if destino.exists():
        for linea in destino.read_text(encoding="utf-8").splitlines():
            if "=" in linea and not linea.lstrip().startswith("#"):
                clave, _, valor = linea.partition("=")
                existentes[clave.strip()] = valor
    existentes.update(valores)
    for nombre in quitar:
        existentes.pop(nombre, None)
    destino.parent.mkdir(parents=True, exist_ok=True)
    cuerpo = "# Generado por el instalador de Nexo ERP. Editar con cuidado.\n"
    cuerpo += "".join(f"{k}={v}\n" for k, v in existentes.items())
    destino.write_text(cuerpo, encoding="utf-8")


def _leer_config(ruta: Path) -> dict[str, str]:
    valores: dict[str, str] = {}
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if "=" in linea and not linea.lstrip().startswith("#"):
                clave, _, valor = linea.partition("=")
                valores[clave.strip()] = valor
    return valores


def _host_para_estaciones(servidor: str) -> str:
    """Las estaciones no pueden usar 'localhost': se les da el nombre de esta PC."""
    host = servidor.split(",")[0].split("\\")[0].strip()
    resto = servidor[len(servidor.split(",")[0].split("\\")[0]) :]
    return (socket.gethostname() if host.lower() in _LOCALES else host) + resto


# ── Configuracion del SQL Server local (registro de Windows + servicio) ──────
#
# Lo que el administrador haria a mano en SQL Server Configuration Manager y en las propiedades del
# servidor. Todo pasa por _reg_* y _servicio_*, que los tests reemplazan (winreg solo existe en Windows).

RAIZ_SQL = r"SOFTWARE\Microsoft\Microsoft SQL Server"
_INSTANCIA_PREDETERMINADA = "MSSQLSERVER"
_SERVICIO_EN_EJECUCION = 4


def _reg_leer(ruta: str, nombre: str):
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ruta, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as clave:
            return winreg.QueryValueEx(clave, nombre)[0]
    except FileNotFoundError:
        return None


def _reg_escribir(ruta: str, nombre: str, valor: int | str) -> None:
    import winreg

    tipo = winreg.REG_DWORD if isinstance(valor, int) else winreg.REG_SZ
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ruta, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as clave:
        winreg.SetValueEx(clave, nombre, 0, tipo, valor)


def _reg_valores(ruta: str) -> dict[str, str]:
    import winreg

    valores: dict[str, str] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ruta, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as clave:
            i = 0
            while True:
                try:
                    nombre, valor, _ = winreg.EnumValue(clave, i)
                except OSError:
                    break
                valores[nombre] = valor
                i += 1
    except FileNotFoundError:
        pass
    return valores


def _estado_servicio(servicio: str) -> int | None:
    """Codigo de estado de `sc query` (4 = en ejecucion); None si el servicio no existe."""
    r = subprocess.run(["sc", "query", servicio], capture_output=True, text=True)
    m = re.search(r"(?:STATE|ESTADO)\s*:\s*(\d+)", r.stdout)
    return int(m.group(1)) if m else None


def _net(accion: str, servicio: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(["net", accion, servicio, *extra], capture_output=True, text=True, timeout=300)


NOMBRE_REGLA_FIREWALL = "Nexo ERP - SQL Server (solo red local)"


def _netsh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["netsh", "advfirewall", "firewall", *args], capture_output=True, text=True, timeout=60)


def _asegurar_regla_firewall(puerto: str) -> str:
    """Abre el puerto de SQL Server en el Firewall de Windows SOLO para la red local
    (remoteip=LocalSubnet). Sin esto, quien conectaba al servidor desde otra subred -- o, con una
    regla generica "permitir 1433", desde cualquier lugar -- podia probar la clave de la base. La
    regla anterior con este nombre se reemplaza. Nunca aborta la instalacion: si no hay permisos
    de administrador solo avisa, y el firewall queda como estaba."""
    try:
        _netsh("delete", "rule", f"name={NOMBRE_REGLA_FIREWALL}")
        r = _netsh(
            "add",
            "rule",
            f"name={NOMBRE_REGLA_FIREWALL}",
            "dir=in",
            "action=allow",
            "protocol=TCP",
            f"localport={puerto}",
            "remoteip=LocalSubnet",
            "profile=any",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Firewall: no se pudo configurar ({exc}). Abra el puerto {puerto} solo para la red local a mano."
    if r.returncode != 0:
        return (
            f"Firewall: no se pudo crear la regla (ejecute como administrador). Abra el puerto {puerto} "
            "solo para la red local a mano."
        )
    return f"Firewall: el puerto {puerto} acepta conexiones solo de la red local."


def _es_local(host: str) -> bool:
    return host.strip().lower() in _LOCALES or host.strip().lower() == socket.gethostname().lower()


def _instancias_sql() -> dict[str, str]:
    """{nombre de instancia: id en el registro (p. ej. MSSQL16.SQLEXPRESS)}."""
    return _reg_valores(RAIZ_SQL + r"\Instance Names\SQL")


def _instancia_destino(servidor: str, instancias: dict[str, str]) -> tuple[str, str]:
    if not instancias:
        raise ErrorInstalacion("No se encontro ninguna instancia de SQL Server en este equipo.")
    _, _, pedida = servidor.split(",")[0].partition("\\")
    pedida = pedida.strip()
    por_nombre = {n.upper(): n for n in instancias}
    if pedida:
        if pedida.upper() not in por_nombre:
            raise ErrorInstalacion(
                f"No existe la instancia '{pedida}' de SQL Server. "
                f"Instancias de este equipo: {', '.join(sorted(instancias))}."
            )
        nombre = por_nombre[pedida.upper()]
    elif _INSTANCIA_PREDETERMINADA in por_nombre:
        nombre = por_nombre[_INSTANCIA_PREDETERMINADA]
    elif len(instancias) == 1:
        nombre = next(iter(instancias))
    else:
        raise ErrorInstalacion(
            f"Hay varias instancias de SQL Server ({', '.join(sorted(instancias))}). Indique el servidor como "
            "equipo\\instancia."
        )
    return nombre, instancias[nombre]


def _ruta_instancia(id_instancia: str) -> str:
    return f"{RAIZ_SQL}\\{id_instancia}\\MSSQLServer"


def _ruta_tcp(id_instancia: str) -> str:
    return _ruta_instancia(id_instancia) + r"\SuperSocketNetLib\Tcp"


def _validar_puerto(valor) -> str:
    texto = str(valor or "").strip() or "1433"
    if not texto.isdigit() or not 1 <= int(texto) <= 65535:
        raise ErrorInstalacion("El puerto TCP debe ser un numero entre 1 y 65535.")
    return str(int(texto))


def _cambios_necesarios(id_instancia: str, puerto: str) -> list[str]:
    tcp = _ruta_tcp(id_instancia)
    cambios = []
    if _reg_leer(_ruta_instancia(id_instancia), "LoginMode") != 2:
        cambios.append("autenticacion mixta (SQL Server y Windows)")
    if _reg_leer(tcp, "Enabled") != 1:
        cambios.append("habilitar el protocolo TCP/IP")
    if _reg_leer(tcp, "ListenOnAllIPs") == 0:
        cambios.append("escuchar en todas las direcciones IP")
    if str(_reg_leer(tcp + r"\IPAll", "TcpPort") or "") != puerto or str(
        _reg_leer(tcp + r"\IPAll", "TcpDynamicPorts") or ""
    ):
        cambios.append(f"puerto TCP fijo {puerto}")
    return cambios


def _reiniciar_servicio(nombre_instancia: str) -> None:
    predeterminada = nombre_instancia.upper() == _INSTANCIA_PREDETERMINADA
    servicio = _INSTANCIA_PREDETERMINADA if predeterminada else f"MSSQL${nombre_instancia}"
    agente = "SQLSERVERAGENT" if predeterminada else f"SQLAgent${nombre_instancia}"
    agente_activo = _estado_servicio(agente) == _SERVICIO_EN_EJECUCION
    if _estado_servicio(servicio) == _SERVICIO_EN_EJECUCION:
        _net("stop", servicio, "/y")  # /y: detiene tambien los servicios que dependen de este (SQL Agent)
        if _estado_servicio(servicio) == _SERVICIO_EN_EJECUCION:
            raise ErrorInstalacion(f"No se pudo detener el servicio {servicio}. Detengalo manualmente y reintente.")
    resultado = _net("start", servicio)
    if _estado_servicio(servicio) != _SERVICIO_EN_EJECUCION:
        detalle = (resultado.stdout or resultado.stderr).strip().splitlines()
        raise ErrorInstalacion(
            f"El servicio {servicio} no volvio a iniciar tras el cambio de configuracion. "
            f"{detalle[-1] if detalle else ''}".strip()
        )
    if agente_activo:
        _net("start", agente)


def cmd_configurar_sql(datos: dict) -> str:
    servidor = str(datos.get("servidor", "")).strip() or "localhost"
    host = servidor.split(",")[0].split("\\")[0]
    if not _es_local(host):
        return (
            "OMITIDO: el servidor SQL no es este equipo; configure TCP/IP, el puerto y el modo mixto en ese servidor."
        )
    puerto = _validar_puerto(datos.get("puerto"))
    instancias = _instancias_sql()
    nombre, id_instancia = _instancia_destino(servidor, instancias)

    for otra, id_otra in instancias.items():
        if id_otra != id_instancia and str(_reg_leer(_ruta_tcp(id_otra) + r"\IPAll", "TcpPort") or "") == puerto:
            raise ErrorInstalacion(
                f"El puerto {puerto} ya lo usa la instancia '{otra}' de SQL Server. Indique otro puerto."
            )

    cambios = _cambios_necesarios(id_instancia, puerto)
    if not cambios:
        firewall = "" if datos.get("solo_diagnostico") else " " + _asegurar_regla_firewall(puerto)
        return f"SIN CAMBIOS: la instancia '{nombre}' ya esta configurada (puerto {puerto}).{firewall}"
    descripcion = "; ".join(cambios)
    if datos.get("solo_diagnostico"):
        return f"CAMBIOS: {descripcion}"

    tcp = _ruta_tcp(id_instancia)
    try:
        _reg_escribir(_ruta_instancia(id_instancia), "LoginMode", 2)
        _reg_escribir(tcp, "Enabled", 1)
        if _reg_leer(tcp, "ListenOnAllIPs") == 0:
            _reg_escribir(tcp, "ListenOnAllIPs", 1)
        _reg_escribir(tcp + r"\IPAll", "TcpPort", puerto)
        _reg_escribir(tcp + r"\IPAll", "TcpDynamicPorts", "")
    except PermissionError as exc:
        raise ErrorInstalacion("Se necesitan permisos de administrador de Windows para configurar SQL Server.") from exc
    _reiniciar_servicio(nombre)
    return (
        f"CONFIGURADO: instancia '{nombre}' ({descripcion}). El servicio de SQL Server se reinicio. "
        + _asegurar_regla_firewall(puerto)
    )


# ── Comandos ────────────────────────────────────────────────────────────────


def cmd_probar(datos: dict) -> str:
    servidor = _servidor_sql(datos)
    motor = _motor(
        servidor,
        datos.get("base") or "master",
        datos.get("usuario", ""),
        datos.get("clave", ""),
        bool(datos.get("windows_auth")),
    )
    try:
        with motor.connect() as c:
            version = c.execute(text("SELECT CAST(SERVERPROPERTY('ProductVersion') AS VARCHAR(30))")).scalar()
            edicion = c.execute(text("SELECT CAST(SERVERPROPERTY('Edition') AS VARCHAR(60))")).scalar()
            es_admin = c.execute(text("SELECT IS_SRVROLEMEMBER('sysadmin')")).scalar()
    except Exception as exc:
        raise ErrorInstalacion(_traducir_error(exc)) from exc
    finally:
        motor.dispose()
    if datos.get("requiere_sysadmin") and not es_admin:
        raise ErrorInstalacion(
            "Ese usuario no es administrador (sysadmin) de SQL Server. Se necesita para crear la base de "
            "datos y el usuario de la aplicacion. Use 'sa' o un administrador, o deje el usuario vacio para "
            "usar la autenticacion de Windows si su cuenta de Windows es administradora de SQL Server."
        )
    return f"Conexion exitosa. SQL Server {version} ({edicion})."


def _ejecutar_autocommit(motor, sentencias: list[str]) -> None:
    """Ejecuta cada sentencia fuera de una transaccion (CREATE DATABASE, ALTER ROLE y los lotes del
    esquema no pueden ir dentro de una)."""
    with motor.connect().execution_options(isolation_level="AUTOCOMMIT") as conexion:
        for sentencia in sentencias:
            conexion.exec_driver_sql(sentencia)


def _aplicar_esquema(motor) -> bool:
    """Crea el esquema base si la base esta vacia. Devuelve True si lo creo."""
    with motor.connect() as c:
        if c.execute(text("SELECT OBJECT_ID(N'dbo.usuarios', N'U')")).scalar() is not None:
            return False
    sql = (RAIZ_PROYECTO / "schema_sqlserver.sql").read_text(encoding="utf-8")
    lotes = [b.strip() for b in re.split(r"(?im)^\s*GO\s*$", sql) if b.strip()]
    _ejecutar_autocommit(motor, lotes)
    return True


def _validar_entradas_servidor(base: str, usuario_app: str, clave_app: str, clave_admin_app: str) -> None:
    """Todo lo que se interpola en SQL se valida AQUI, antes de tocar el servidor: ningun valor
    del usuario llega a una sentencia sin pasar por una lista blanca de caracteres."""
    from app.services.auth import validar_password_policy

    if not _IDENTIFICADOR_RE.match(base):
        raise ErrorInstalacion("El nombre de la base de datos solo admite letras, numeros y guion bajo (3 a 40).")
    if not _IDENTIFICADOR_RE.match(usuario_app):
        raise ErrorInstalacion("El usuario SQL de la aplicacion solo admite letras, numeros y guion bajo (3 a 40).")
    if len(clave_app) < 12:
        raise ErrorInstalacion("La contrasena del usuario SQL de la aplicacion debe tener al menos 12 caracteres.")
    try:
        validar_password_policy(clave_admin_app)
    except ValueError as exc:
        raise ErrorInstalacion(f"Contrasena del usuario 'admin' no valida: {exc}") from exc


def _crear_usuario_app(motor, base: str, usuario: str, clave: str) -> None:
    """Login SQL propio de la app con los permisos minimos que necesita: leer, escribir y ejecutar.
    Nada de DDL ni db_owner: las migraciones las aplica el instalador con credenciales de admin.
    (`base` y `usuario` ya pasaron por _validar_entradas_servidor.)"""
    clave_sql = clave.replace("'", "''")
    _ejecutar_autocommit(
        motor,
        [
            f"IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'{usuario}') "
            f"CREATE LOGIN [{usuario}] WITH PASSWORD = N'{clave_sql}', CHECK_POLICY = ON, DEFAULT_DATABASE = [{base}] "
            f"ELSE ALTER LOGIN [{usuario}] WITH PASSWORD = N'{clave_sql}'",
            f"IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'{usuario}') "
            f"CREATE USER [{usuario}] FOR LOGIN [{usuario}]",
            f"ALTER ROLE db_datareader ADD MEMBER [{usuario}]",
            f"ALTER ROLE db_datawriter ADD MEMBER [{usuario}]",
            f"GRANT EXECUTE TO [{usuario}]",
            # Rol con DENY de borrado sobre el historial de dinero (migrations/0091). Si todavia no existe
            # (la migracion corre despues), ella misma agrega a los miembros de db_datawriter.
            f"IF DATABASE_PRINCIPAL_ID(N'{ROL_APP_SIN_BORRADO}') IS NOT NULL "
            f"ALTER ROLE [{ROL_APP_SIN_BORRADO}] ADD MEMBER [{usuario}]",
        ],
    )


def _crear_admin_app(motor, clave: str) -> str:
    from app.services.auth import hash_password

    with motor.begin() as c:
        if c.execute(text("SELECT COUNT(*) FROM dbo.usuarios WHERE nombre_usuario = 'admin'")).scalar():
            return "El usuario 'admin' ya existia; se conserva su contrasena."
        id_rol = c.execute(text("SELECT id_rol FROM dbo.roles WHERE nombre = 'ADMIN'")).scalar()
        if id_rol is None:
            raise ErrorInstalacion("El esquema no tiene el rol ADMIN; la base no se creo correctamente.")
        c.execute(
            text(
                "INSERT INTO dbo.usuarios (nombre_usuario, nombre, clave, id_rol) "
                "VALUES ('admin', 'Administrador', :c, :r)"
            ),
            {"c": hash_password(clave), "r": id_rol},
        )
    return "Usuario 'admin' creado."


def cmd_servidor(datos: dict) -> str:
    from app.db.migrar import aplicar_migraciones

    servidor = _servidor_sql(datos)
    base = str(datos.get("base", "")).strip()
    usuario_app = str(datos.get("usuario_app", "dj_app")).strip()
    clave_app = str(datos.get("clave_app", ""))
    _validar_entradas_servidor(base, usuario_app, clave_app, str(datos.get("clave_admin_app", "")))
    usuario_admin, clave_admin = datos.get("usuario_admin", ""), datos.get("clave_admin", "")
    windows_auth = bool(datos.get("windows_auth"))
    destino = Path(datos.get("config_destino") or ARCHIVO_CONFIG)

    mensajes: list[str] = []
    try:
        motor_master = _motor(servidor, "master", usuario_admin, clave_admin, windows_auth)
        try:
            with motor_master.connect() as c:
                solo_windows = c.execute(
                    text("SELECT CAST(SERVERPROPERTY('IsIntegratedSecurityOnly') AS INT)")
                ).scalar()
            if solo_windows:
                # El usuario SQL de la app (y todas las estaciones) no podrian conectarse: se falla ahora, con una
                # explicacion, y no despues de instalar cuando "no entra nadie".
                raise ErrorInstalacion(
                    "SQL Server esta en modo de autenticacion solo de Windows. La aplicacion necesita el modo mixto "
                    "('SQL Server and Windows Authentication mode'): en SQL Server Management Studio, clic derecho "
                    "en el servidor > Propiedades > Seguridad, elija ese modo, reinicie el servicio de SQL Server y "
                    "vuelva a ejecutar el instalador."
                )
            _ejecutar_autocommit(motor_master, [f"IF DB_ID(N'{base}') IS NULL CREATE DATABASE [{base}]"])
        finally:
            motor_master.dispose()

        motor = _motor(servidor, base, usuario_admin, clave_admin, windows_auth)
        try:
            mensajes.append("Esquema creado." if _aplicar_esquema(motor) else "La base ya tenia esquema.")
            aplicar_migraciones(motor)
            mensajes.append("Migraciones al dia.")
            _crear_usuario_app(motor, base, usuario_app, clave_app)
            mensajes.append(f"Usuario SQL '{usuario_app}' listo (solo lectura/escritura de datos).")
            mensajes.append(_crear_admin_app(motor, str(datos.get("clave_admin_app", ""))))
        finally:
            motor.dispose()
    except ErrorInstalacion:
        raise
    except Exception as exc:
        raise ErrorInstalacion(_traducir_error(exc)) from exc

    # Con puerto fijo (lo deja configurar-sql) las estaciones se conectan por host,puerto: no dependen del
    # servicio SQL Browser ni del nombre de instancia.
    if str(datos.get("puerto", "")).strip():
        servidor = f"{servidor.split(',')[0].split(chr(92))[0]},{str(datos['puerto']).strip()}"
    valores_clave, quitar_clave = _valores_clave_db(clave_app)
    _escribir_config(
        destino,
        {
            "DB_SERVER": servidor,
            "DB_NAME": base,
            "DB_USER": usuario_app,
            **valores_clave,
            "DB_DRIVER": DRIVER_ODBC,
            "DB_TRUST_SERVER_CERTIFICATE": "yes",
            "DB_TRUSTED_CONNECTION": "no",
            "MODO_INSTALACION": "SERVIDOR",
        },
        quitar=quitar_clave,
    )
    host_estaciones = _host_para_estaciones(servidor)
    (destino.parent / NOMBRE_ARCHIVO_DATOS_ESTACIONES).write_text(
        "DATOS PARA INSTALAR LAS ESTACIONES\n"
        "==================================\n"
        "En cada PC cliente ejecute el instalador, elija 'Estacion' e ingrese:\n\n"
        f"  Servidor SQL : {host_estaciones}\n"
        f"  Base de datos: {base}\n"
        f"  Usuario SQL  : {usuario_app}\n"
        f"  Contrasena   : {clave_app}\n\n"
        f"ESTE ARCHIVO SE ELIMINA SOLO el {datos_estaciones.fecha_de_borrado():%d/%m/%Y a las %H:%M} "
        f"({datos_estaciones.HORAS_VIGENCIA} horas despues de instalar el servidor), siempre que el servicio de "
        "Nexo ERP o la aplicacion este en marcha en este equipo. Guarde estos datos en un lugar seguro antes.\n"
        "El servidor debe aceptar conexiones TCP/IP en ese puerto y el firewall debe permitirlas.\n",
        encoding="utf-8",
    )
    mensajes.append(f"Configuracion guardada en {destino}.")
    return "\n".join(mensajes)


def cmd_estacion(datos: dict) -> str:
    from app.db.migrar import verificar_migraciones_al_dia

    servidor = _servidor_sql(datos)
    base, usuario, clave = str(datos.get("base", "")).strip(), datos.get("usuario", ""), datos.get("clave", "")
    destino = Path(datos.get("config_destino") or ARCHIVO_CONFIG)
    motor = _motor(servidor, base, usuario, clave)
    try:
        with motor.connect() as c:
            if c.execute(text("SELECT OBJECT_ID(N'dbo.usuarios', N'U')")).scalar() is None:
                raise ErrorInstalacion(
                    "La base existe pero no tiene el esquema de la aplicacion. ¿Es la base correcta?"
                )
        try:
            verificar_migraciones_al_dia(motor)
        except RuntimeError as exc:
            raise ErrorInstalacion(
                "La base del servidor tiene un esquema distinto al de esta version de la aplicacion. "
                "Actualice primero el servidor con este mismo instalador.\n\n" + str(exc)
            ) from exc
    except ErrorInstalacion:
        raise
    except Exception as exc:
        raise ErrorInstalacion(_traducir_error(exc)) from exc
    finally:
        motor.dispose()
    valores_clave, quitar_clave = _valores_clave_db(clave)
    _escribir_config(
        destino,
        {
            "DB_SERVER": servidor,
            "DB_NAME": base,
            "DB_USER": usuario,
            **valores_clave,
            "DB_DRIVER": DRIVER_ODBC,
            "DB_TRUST_SERVER_CERTIFICATE": "yes",
            "DB_TRUSTED_CONNECTION": "no",
            "MODO_INSTALACION": "ESTACION",
        },
        quitar=quitar_clave,
    )
    return f"Conexion con el servidor verificada. Configuracion guardada en {destino}."


def cmd_actualizar(datos: dict) -> str:
    from app.db.migrar import aplicar_migraciones

    destino = Path(datos.get("config_destino") or ARCHIVO_CONFIG)
    config = _leer_config(destino)
    if not config.get("DB_SERVER"):
        raise ErrorInstalacion(f"No hay una instalacion previa configurada en {destino}.")
    motor = _motor(
        config["DB_SERVER"],
        config["DB_NAME"],
        datos.get("usuario_admin", ""),
        datos.get("clave_admin", ""),
        bool(datos.get("windows_auth")),
    )
    try:
        aplicar_migraciones(motor)
    except Exception as exc:
        raise ErrorInstalacion(_traducir_error(exc)) from exc
    finally:
        motor.dispose()
    return "Base de datos actualizada."


# ── Respaldos automaticos (trabajos de SQL Server Agent + copia a Google Drive) ──────
#
# Los respaldos son trabajos de SQL Server Agent (se ven y se editan en SSMS > SQL Server Agent > Trabajos):
# SQL Server no deja crear por script un "Plan de mantenimiento" propiamente dicho. La copia a Google Drive
# no puede hacerla SQL Agent (corre con otra cuenta de Windows, que no ve la unidad de Google Drive para
# escritorio del usuario): la hace una tarea programada de Windows con la sesion del usuario que instala.

TRABAJO_COMPLETO = "Nexo ERP - Respaldo completo"
TRABAJO_LOG = "Nexo ERP - Respaldo de log de transacciones"
TRABAJO_MANTENIMIENTO = "Nexo ERP - Mantenimiento semanal"
TAREA_COPIA_DRIVE = "Nexo ERP - Copia de respaldos a Google Drive"
CARPETA_RESPALDOS_DEFECTO = r"C:\Respaldos\Nexo"
DIAS_RETENCION_DEFECTO = 3  # vale para los respaldos completos y los de log, en local y en Drive
_RUTA_RE = re.compile(r"""^(?:[A-Za-z]:[\\/]|\\\\|/)[^'"<>|*?;\r\n]+$""")
_EDICION_EXPRESS = 4  # SERVERPROPERTY('EngineEdition'): Express no incluye SQL Server Agent
PERFIL_CORREO = "Nexo ERP - Alertas"
CUENTA_CORREO = "Nexo ERP - Alertas"
SMTP_HOST_DEFECTO = "smtp.gmail.com"
SMTP_PUERTO_DEFECTO = 587
_CORREO_RE = re.compile(r"""^[^@\s;,'"<>]+@[^@\s;,'"<>]+\.[^@\s;,'"<>]+$""")
_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$")


def _validar_alertas(datos: dict) -> dict | None:
    """None = sin alertas por correo (no se indico ningun destinatario)."""
    crudo = str(datos.get("alerta_correos") or "")
    destinatarios = [c.strip() for c in re.split(r"[;,]", crudo) if c.strip()]
    if not destinatarios:
        return None
    for correo in destinatarios:
        if not _CORREO_RE.match(correo):
            raise ErrorInstalacion(f"El correo '{correo}' para las alertas no es valido.")
    usuario = str(datos.get("smtp_usuario") or "").strip()
    clave = str(datos.get("smtp_clave") or "")
    if not usuario or not clave:
        raise ErrorInstalacion(
            "Para enviar alertas por correo indique el correo remitente y su contrasena (en Gmail, una "
            "'contrasena de aplicacion')."
        )
    remitente = str(datos.get("smtp_remitente") or usuario).strip()
    host = str(datos.get("smtp_host") or SMTP_HOST_DEFECTO).strip()
    if not _CORREO_RE.match(remitente) or not _HOST_RE.match(host):
        raise ErrorInstalacion("El correo remitente o el servidor SMTP de las alertas no son validos.")
    try:
        puerto = int(str(datos.get("smtp_puerto") or SMTP_PUERTO_DEFECTO).strip())
    except ValueError:
        puerto = 0
    if not 1 <= puerto <= 65535:
        raise ErrorInstalacion("El puerto SMTP de las alertas debe ser un numero entre 1 y 65535.")
    return {
        "destinatarios": ";".join(destinatarios),
        "usuario": usuario,
        "clave": clave,
        "remitente": remitente,
        "host": host,
        "puerto": puerto,
    }


def _ruta_valida(valor: str, que: str) -> str:
    """Las rutas terminan dentro de sentencias SQL y de un script de PowerShell: lista blanca de caracteres."""
    ruta = valor.strip().rstrip("\\/") if len(valor.strip()) > 3 else valor.strip()
    if not _RUTA_RE.match(ruta):
        raise ErrorInstalacion(
            f"{que} debe ser una ruta completa (ej. C:\\Respaldos\\Nexo) sin comillas ni los caracteres < > | * ? ;"
        )
    return ruta


def _ejecutar_con_parametros(motor, sentencias: list[tuple[str, tuple]]) -> None:
    with motor.connect().execution_options(isolation_level="AUTOCOMMIT") as conexion:
        for sql, parametros in sentencias:
            cursor = conexion.connection.cursor()
            try:
                cursor.execute(sql, *parametros)
                # BACKUP emite mensajes informativos: el controlador solo termina de ejecutar (y de informar
                # errores) cuando se recorren todos los resultados.
                while cursor.nextset():
                    pass
            finally:
                cursor.close()


def _alta_trabajo(
    nombre: str,
    descripcion: str,
    pasos: list[tuple[str, str, str]],
    programacion: dict,
    comando_alerta: str | None = None,
) -> tuple:
    """Sentencia (sql, parametros) que borra el trabajo si existe y lo crea con sus pasos y horario.
    `pasos`: (nombre, comando T-SQL, base de datos). Con `comando_alerta`, se agrega al final un paso de alerta
    al que va cualquier paso que falle (y que deja el trabajo como fallido)."""
    lineas = [
        "IF EXISTS (SELECT 1 FROM msdb.dbo.sysjobs WHERE name = ?) "
        "EXEC msdb.dbo.sp_delete_job @job_name = ?, @delete_unused_schedule = 1;",
        "DECLARE @propietario SYSNAME = SUSER_SNAME(0x01);",
        "EXEC msdb.dbo.sp_add_job @job_name = ?, @description = ?, @owner_login_name = @propietario;",
    ]
    parametros: list = [nombre, nombre, nombre, descripcion]
    for i, (paso, comando, base) in enumerate(pasos):
        siguiente = 3 if i < len(pasos) - 1 else 1  # 3 = pasar al paso siguiente, 1 = terminar bien
        # 4 = si falla, ir al paso de alerta; 2 = terminar con fallo.
        if comando_alerta:
            ante_fallo = f"@on_fail_action = 4, @on_fail_step_id = {len(pasos) + 1}"
        else:
            ante_fallo = "@on_fail_action = 2"
        lineas.append(
            "EXEC msdb.dbo.sp_add_jobstep @job_name = ?, @step_name = ?, @subsystem = N'TSQL', @command = ?, "
            f"@database_name = ?, @on_success_action = {siguiente}, {ante_fallo};"
        )
        parametros += [nombre, paso, comando, base]
    if comando_alerta:
        lineas.append(
            "EXEC msdb.dbo.sp_add_jobstep @job_name = ?, @step_name = N'Enviar alerta por correo', "
            "@subsystem = N'TSQL', @command = ?, @database_name = N'master', @on_success_action = 2, "
            "@on_fail_action = 2;"
        )
        parametros += [nombre, comando_alerta]
    campos = ", ".join(f"@{k} = {v}" for k, v in programacion.items())
    lineas.append(f"EXEC msdb.dbo.sp_add_jobschedule @job_name = ?, @name = ?, {campos};")
    parametros += [nombre, nombre]
    lineas.append("EXEC msdb.dbo.sp_add_jobserver @job_name = ?, @server_name = N'(local)';")
    parametros.append(nombre)
    return "\n".join(lineas), tuple(parametros)


def _comando_respaldo(base: str, carpeta: str, tipo: str) -> str:
    """T-SQL de un respaldo con nombre `<base>_FULL|LOG_<fecha>_<hora>.bak|.trn` dentro de `carpeta`."""
    separador = "/" if "/" in carpeta and "\\" not in carpeta else "\\"
    etiqueta, objeto, extension = ("FULL", "DATABASE", "bak") if tipo == "full" else ("LOG", "LOG", "trn")
    return (
        f"DECLARE @f NVARCHAR(500) = N'{carpeta}{separador}{base}_{etiqueta}_' "
        f"+ FORMAT(GETDATE(), 'yyyyMMdd_HHmmss') + N'.{extension}';\n"
        f"BACKUP {objeto} [{base}] TO DISK = @f WITH COMPRESSION, CHECKSUM, INIT;"
    )


def _comando_limpieza(carpeta: str, dias: int) -> str:
    return (
        f"DECLARE @corte DATETIME = DATEADD(DAY, -{dias}, GETDATE());\n"
        f"EXEC master.dbo.xp_delete_file 0, N'{carpeta}', N'bak', @corte, 0;\n"
        f"EXEC master.dbo.xp_delete_file 0, N'{carpeta}', N'trn', @corte, 0;"
    )


def _asegurar_agente(instancia: str | None) -> str:
    """SQL Server Agent con inicio automatico y en ejecucion (solo para un SQL Server de este equipo)."""
    servicio = f"SQLAgent${instancia}" if instancia else "SQLSERVERAGENT"
    if _estado_servicio(servicio) is None:
        return f"No se encontro el servicio {servicio}: inicielo manualmente para que corran los respaldos."
    subprocess.run(["sc", "config", servicio, "start=", "auto"], capture_output=True, text=True)
    if _estado_servicio(servicio) != _SERVICIO_EN_EJECUCION:
        _net("start", servicio)
    if _estado_servicio(servicio) != _SERVICIO_EN_EJECUCION:
        return f"No se pudo iniciar el servicio {servicio}: inicielo manualmente para que corran los respaldos."
    return ""


def _reiniciar_agente(instancia: str | None) -> str:
    """SQL Server Agent solo lee el perfil de Database Mail al arrancar."""
    servicio = f"SQLAgent${instancia}" if instancia else "SQLSERVERAGENT"
    if _estado_servicio(servicio) is None:
        return f"No se encontro el servicio {servicio}: reinicielo manualmente para activar las alertas por correo."
    if _estado_servicio(servicio) == _SERVICIO_EN_EJECUCION:
        _net("stop", servicio, "/y")
    _net("start", servicio)
    if _estado_servicio(servicio) != _SERVICIO_EN_EJECUCION:
        return (
            f"No se pudo reiniciar el servicio {servicio}: reinicielo manualmente para activar las alertas por correo."
        )
    return ""


def _lit(texto: str) -> str:
    """Literal NVARCHAR de T-SQL. Los textos fijos del instalador usan entidades HTML (&oacute;) para no llevar
    caracteres no ASCII."""
    return "N'" + texto.replace("'", "''") + "'"


def _html_correo(titulo: str, color: str, filas: list[tuple[str, str]], detalle: str | None, pie: str) -> str:
    """Expresion T-SQL (NVARCHAR) con el cuerpo HTML de un correo de alerta. `filas`: (etiqueta, expresion T-SQL ya
    escapada para HTML); `detalle`: expresion T-SQL del texto del error (se muestra aparte, en bloque de codigo)."""
    partes = [
        _lit(
            '<html><body style="margin:0;padding:0;background:#f3f4f6;font-family:Segoe UI,Arial,sans-serif;">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;'
            'padding:24px 0;"><tr><td align="center">'
            '<table role="presentation" width="620" cellpadding="0" cellspacing="0" style="background:#ffffff;'
            'border-radius:8px;overflow:hidden;border:1px solid #e5e7eb;">'
            f'<tr><td style="background:{color};padding:18px 24px;color:#ffffff;">'
            '<div style="font-size:12px;letter-spacing:1px;text-transform:uppercase;opacity:.85;">Nexo ERP</div>'
            f'<div style="font-size:20px;font-weight:600;margin-top:4px;">{titulo}</div></td></tr>'
            '<tr><td style="padding:20px 24px;"><table role="presentation" width="100%" cellpadding="0" '
            'cellspacing="0" style="font-size:14px;color:#111827;">'
        )
    ]
    for etiqueta, expresion in filas:
        partes.append(
            _lit(
                '<tr><td style="padding:7px 12px 7px 0;color:#6b7280;white-space:nowrap;vertical-align:top;'
                f'border-bottom:1px solid #f3f4f6;">{etiqueta}</td><td style="padding:7px 0;font-weight:600;'
                'border-bottom:1px solid #f3f4f6;">'
            )
        )
        partes.append(expresion)
        partes.append(_lit("</td></tr>"))
    partes.append(_lit("</table>"))
    if detalle is not None:
        partes.append(
            _lit(
                '<div style="margin-top:18px;font-size:12px;color:#6b7280;text-transform:uppercase;'
                'letter-spacing:.5px;">Detalle del error</div><pre style="margin:6px 0 0;padding:12px;'
                "background:#fef2f2;border:1px solid #fecaca;border-radius:6px;color:#7f1d1d;font-size:12px;"
                "white-space:pre-wrap;word-break:break-word;"
                'font-family:Consolas,monospace;">'
            )
        )
        partes.append(detalle)
        partes.append(_lit("</pre>"))
    partes.append(
        _lit(
            f'</td></tr><tr><td style="padding:14px 24px;background:#f9fafb;color:#6b7280;font-size:12px;">{pie}'
            "</td></tr></table></td></tr></table></body></html>"
        )
    )
    # NVARCHAR(MAX) desde el principio: concatenando literales de hasta 4000 caracteres el resultado se truncaria.
    return "CAST(N'' AS NVARCHAR(MAX)) + " + " + ".join(partes)


def _escapar_html_sql(expresion: str) -> str:
    return f"REPLACE(REPLACE(REPLACE({expresion}, N'&', N'&amp;'), N'<', N'&lt;'), N'>', N'&gt;')"


def _envio_correo(destinatarios: str, asunto: str, cuerpo: str) -> str:
    """sp_send_dbmail: siempre HTML y con importancia alta. `asunto` y `cuerpo` son expresiones T-SQL."""
    return (
        "EXEC msdb.dbo.sp_send_dbmail "
        f"@profile_name = {_lit(PERFIL_CORREO)}, @recipients = {_lit(destinatarios)}, @subject = {asunto}, "
        f"@body = {cuerpo}, @body_format = 'HTML', @importance = 'High';"
    )


def _comando_alerta_fallo(destinatarios: str) -> str:
    """Paso final de cada trabajo, al que van los pasos cuando fallan: manda el correo de alerta (HTML, importancia
    alta) con el trabajo, el paso y el error. Las notificaciones propias de SQL Agent no permiten cambiar ni el
    formato ni la importancia, por eso la alerta se envia desde aqui y no desde un operador.
    $(ESCAPE_NONE(JOBID)) es un token de SQL Agent: se reemplaza al ejecutarse el paso."""
    cuerpo = _html_correo(
        "Fall&oacute; un trabajo de respaldo o mantenimiento",
        "#b91c1c",
        [
            ("Servidor", "@@SERVERNAME"),
            ("Trabajo", "@trabajo"),
            ("Paso que fall&oacute;", "@paso"),
            ("Fecha y hora", "CONVERT(NVARCHAR(30), @inicio, 120)"),
        ],
        "@detalle",
        "Revise el trabajo en SSMS &gt; SQL Server Agent &gt; Trabajos &gt; Ver historial. "
        "Mientras no se corrija, los respaldos pueden no estar realiz&aacute;ndose.",
    )
    return (
        "DECLARE @id UNIQUEIDENTIFIER = CONVERT(UNIQUEIDENTIFIER, $(ESCAPE_NONE(JOBID)));\n"
        "DECLARE @trabajo NVARCHAR(128), @paso NVARCHAR(128), @detalle NVARCHAR(MAX), @inicio DATETIME;\n"
        "SELECT @trabajo = name FROM msdb.dbo.sysjobs WHERE job_id = @id;\n"
        "SELECT TOP 1 @paso = step_name, @detalle = message, @inicio = msdb.dbo.agent_datetime(run_date, run_time)\n"
        "FROM msdb.dbo.sysjobhistory WHERE job_id = @id AND step_id > 0 AND run_status = 0 ORDER BY instance_id DESC;\n"
        "SET @trabajo = ISNULL(@trabajo, N'(desconocido)');\n"
        "SET @paso = ISNULL(@paso, N'(desconocido)');\n"
        "SET @inicio = ISNULL(@inicio, GETDATE());\n"
        "SET @detalle = " + _escapar_html_sql("LEFT(ISNULL(@detalle, " + _lit("(sin detalle)") + "), 3000)") + ";\n"
        "SET @trabajo = " + _escapar_html_sql("@trabajo") + ";\n"
        "SET @paso = " + _escapar_html_sql("@paso") + ";\n"
        "DECLARE @cuerpo NVARCHAR(MAX) = " + cuerpo + ";\n"
        "DECLARE @asunto NVARCHAR(255) = N'[Nexo ERP] ALERTA: fall' + NCHAR(243) + N' el trabajo ' "
        "+ LEFT(@trabajo, 100) + N' en ' + @@SERVERNAME;\n" + _envio_correo(destinatarios, "@asunto", "@cuerpo")
    )


def _comando_correo_prueba(destinatarios: str, base: str, carpeta: str, dias: int) -> str:
    cuerpo = _html_correo(
        "Alertas de respaldo configuradas",
        "#15803d",
        [
            ("Servidor", "@@SERVERNAME"),
            ("Base de datos", _lit(base)),
            ("Carpeta de respaldos", _lit(carpeta)),
            ("Respaldo completo", _lit("Todos los d&iacute;as a las 7:00 pm")),
            ("Respaldo de log", _lit("Cada 30 minutos")),
            ("Se conservan", _lit(f"{dias} d&iacute;as")),
            ("Reciben la alerta", _lit(destinatarios.replace(";", "<br>"))),
        ],
        None,
        "Este es un correo de prueba. A partir de ahora recibir&aacute; un aviso, con importancia alta, si falla "
        "alg&uacute;n trabajo de respaldo o mantenimiento de Nexo ERP en este servidor.",
    )
    return (
        f"DECLARE @cuerpo NVARCHAR(MAX) = {cuerpo};\n"
        "DECLARE @asunto NVARCHAR(255) = N'[Nexo ERP] Alertas de respaldo configuradas en ' + @@SERVERNAME;\n"
        + _envio_correo(destinatarios, "@asunto", "@cuerpo")
    )


def _configurar_alertas(motor, alertas: dict, instancia: str | None, es_local: bool, contexto: dict) -> str:
    """Database Mail (cuenta y perfil propios), perfil asignado a SQL Agent (que se reinicia) y correo de prueba.
    Los trabajos ya llevan su paso de alerta (ver _comando_alerta_fallo). Devuelve un aviso si algo no quedo listo;
    "" si todo salio bien."""
    try:
        _ejecutar_con_parametros(
            motor,
            [
                ("EXEC sp_configure 'show advanced options', 1; RECONFIGURE;", ()),
                ("EXEC sp_configure 'Database Mail XPs', 1; RECONFIGURE;", ()),
                (
                    "IF EXISTS (SELECT 1 FROM msdb.dbo.sysmail_profile WHERE name = ?) "
                    "EXEC msdb.dbo.sysmail_delete_profile_sp @profile_name = ?;",
                    (PERFIL_CORREO, PERFIL_CORREO),
                ),
                (
                    "IF EXISTS (SELECT 1 FROM msdb.dbo.sysmail_account WHERE name = ?) "
                    "EXEC msdb.dbo.sysmail_delete_account_sp @account_name = ?;",
                    (CUENTA_CORREO, CUENTA_CORREO),
                ),
                (
                    "EXEC msdb.dbo.sysmail_add_account_sp @account_name = ?, @email_address = ?, "
                    "@display_name = N'Nexo ERP', @mailserver_name = ?, @port = ?, @enable_ssl = 1, "
                    "@username = ?, @password = ?",
                    (
                        CUENTA_CORREO,
                        alertas["remitente"],
                        alertas["host"],
                        alertas["puerto"],
                        alertas["usuario"],
                        alertas["clave"],
                    ),
                ),
                ("EXEC msdb.dbo.sysmail_add_profile_sp @profile_name = ?", (PERFIL_CORREO,)),
                (
                    "EXEC msdb.dbo.sysmail_add_profileaccount_sp @profile_name = ?, @account_name = ?, "
                    "@sequence_number = 1",
                    (PERFIL_CORREO, CUENTA_CORREO),
                ),
                (
                    "EXEC msdb.dbo.sp_set_sqlagent_properties @databasemail_profile = ?, @use_databasemail = 1",
                    (PERFIL_CORREO,),
                ),
            ],
        )
    except Exception as exc:
        return (
            "Las alertas por correo quedaron a medias: los trabajos tienen su paso de alerta, pero no se pudo "
            f"configurar Database Mail ({_traducir_error(exc)}). Configurelo en SSMS > Management > Database Mail "
            f"con un perfil llamado '{PERFIL_CORREO}'."
        )
    if es_local:
        aviso = _reiniciar_agente(instancia)
        if aviso:
            return aviso
    try:
        _ejecutar_con_parametros(
            motor,
            [
                (
                    _comando_correo_prueba(
                        alertas["destinatarios"], contexto["base"], contexto["carpeta"], contexto["dias"]
                    ),
                    (),
                )
            ],
        )
    except Exception as exc:
        return f"No se pudo enviar el correo de prueba de las alertas: {_traducir_error(exc)}"
    return ""


def _usuario_windows() -> str:
    import os

    dominio, usuario = os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", "")
    return f"{dominio}\\{usuario}" if dominio and usuario else usuario


def _ruta_drive_obligatoria(datos: dict) -> str:
    ruta = str(datos.get("ruta_drive", "")).strip()
    if not ruta:
        raise ErrorInstalacion(
            "La carpeta de Google Drive es obligatoria: los respaldos se copian ahi para tenerlos fuera de este "
            "equipo. Indique una ruta (ej. G:\\Mi unidad\\Nexo)."
        )
    return _ruta_valida(ruta, "La ruta de Google Drive")


def _probar_ruta_drive(ruta: str) -> str:
    """Comprueba que se pueda escribir en `ruta` con el usuario que ejecuta el instalador (el mismo con el que
    correra la tarea de copia): la unidad existe, la carpeta existe o se puede crear, y un archivo de prueba se
    escribe, se lee y se borra. Solo se crea el ultimo nivel de la ruta: un error de tipeo en una carpeta padre
    no debe dejar carpetas sobrantes en Google Drive."""
    carpeta = Path(ruta)
    if not carpeta.anchor or not Path(carpeta.anchor).exists():
        raise ErrorInstalacion(
            f"No existe la unidad {carpeta.anchor or ruta}. Abra Google Drive para escritorio, inicie sesion y "
            "verifique la letra de unidad (o la ruta de la carpeta sincronizada)."
        )
    if not carpeta.exists():
        if not carpeta.parent.exists():
            raise ErrorInstalacion(
                f"No existe la carpeta {carpeta.parent}. Verifique la ruta (mayusculas, tildes y espacios) o "
                "cree primero esa carpeta en Google Drive."
            )
        try:
            carpeta.mkdir()
        except OSError as exc:
            raise ErrorInstalacion(f"No se pudo crear la carpeta {ruta}: {exc.strerror or exc}") from exc
    elif not carpeta.is_dir():
        raise ErrorInstalacion(f"{ruta} existe pero no es una carpeta.")
    archivo = carpeta / f"nexo_prueba_{secrets.token_hex(4)}.tmp"
    contenido = "Prueba de escritura de Nexo ERP. Se puede borrar."
    try:
        archivo.write_text(contenido, encoding="utf-8")
        if archivo.read_text(encoding="utf-8") != contenido:
            raise ErrorInstalacion(f"Se escribio un archivo de prueba en {ruta} pero no se pudo leer igual.")
        archivo.unlink()
    except OSError as exc:
        raise ErrorInstalacion(f"No se pudo escribir en {ruta}: {exc.strerror or exc}") from exc
    return f"La carpeta funciona: se escribio, leyo y borro un archivo de prueba en {ruta}."


def cmd_probar_drive(datos: dict) -> str:
    return _probar_ruta_drive(_ruta_drive_obligatoria(datos))


def _programar_copia_drive(carpeta: str, ruta_drive: str, dias: int, directorio_datos: Path) -> str:
    """Script de PowerShell + tarea programada (cada 30 min, con la sesion del usuario que instala) que copia a
    `ruta_drive` los respaldos nuevos de `carpeta` y borra de Drive los de mas de `dias` dias."""
    script = directorio_datos / "copiar_respaldos_drive.ps1"
    directorio_datos.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "# Generado por el instalador de Nexo ERP. Copia los respaldos a Google Drive para escritorio.\n"
        f"$origen = '{carpeta}'\n"
        f"$destino = '{ruta_drive}'\n"
        f"$dias = {dias}\n"
        "$fallos = 0\n"
        "if (-not (Test-Path -LiteralPath $destino)) {\n"
        "    New-Item -ItemType Directory -Path $destino -Force -ErrorAction SilentlyContinue | Out-Null\n"
        "}\n"
        "if (-not (Test-Path -LiteralPath $destino)) { exit 1 }  # Drive para escritorio no esta iniciado\n"
        "$ext = '.bak', '.trn'\n"
        "# Se omiten los archivos de los ultimos 2 minutos: SQL Server puede seguir escribiendolos.\n"
        "$limite = (Get-Date).AddMinutes(-2)\n"
        "Get-ChildItem -LiteralPath $origen -File |\n"
        "    Where-Object { $ext -contains $_.Extension -and $_.LastWriteTime -lt $limite } |\n"
        "    ForEach-Object {\n"
        "        $copia = Join-Path $destino $_.Name\n"
        "        if (-not (Test-Path -LiteralPath $copia)) {\n"
        "            try { Copy-Item -LiteralPath $_.FullName -Destination $copia -ErrorAction Stop }\n"
        "            catch { $fallos++ }\n"
        "        }\n"
        "    }\n"
        "$corte = (Get-Date).AddDays(-$dias)\n"
        "Get-ChildItem -LiteralPath $destino -File |\n"
        "    Where-Object { $ext -contains $_.Extension -and $_.LastWriteTime -lt $corte } |\n"
        "    Remove-Item -Force -ErrorAction SilentlyContinue\n"
        "if ($fallos -gt 0) { exit 1 }\n",
        encoding="utf-8-sig",
    )
    comando = f'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{script}"'
    argumentos = ["schtasks", "/Create", "/TN", TAREA_COPIA_DRIVE, "/TR", comando, "/SC", "MINUTE", "/MO", "30", "/F"]
    usuario = _usuario_windows()
    if usuario:
        argumentos += ["/RU", usuario, "/IT"]
    r = subprocess.run(argumentos, capture_output=True, text=True)
    if r.returncode != 0:
        detalle = (r.stderr or r.stdout).strip().splitlines()
        return (
            f"No se pudo crear la tarea programada de copia a Google Drive: {detalle[-1] if detalle else r.returncode}"
        )
    return ""


def cmd_respaldos(datos: dict) -> str:
    servidor = _servidor_sql(datos)
    base = str(datos.get("base", "")).strip()
    if not _IDENTIFICADOR_RE.match(base):
        raise ErrorInstalacion("El nombre de la base de datos solo admite letras, numeros y guion bajo (3 a 40).")
    carpeta = _ruta_valida(str(datos.get("carpeta") or CARPETA_RESPALDOS_DEFECTO), "La carpeta de respaldos")
    ruta_drive = _ruta_drive_obligatoria(datos)
    if not datos.get("omitir_prueba_drive"):
        _probar_ruta_drive(ruta_drive)
    try:
        dias = int(str(datos.get("dias_retencion") or DIAS_RETENCION_DEFECTO).strip())
    except ValueError:
        dias = 0
    if not 1 <= dias <= 3650:
        raise ErrorInstalacion("Los dias de retencion de los respaldos deben ser un numero entre 1 y 3650.")
    alertas = _validar_alertas(datos)
    comando_alerta = _comando_alerta_fallo(alertas["destinatarios"]) if alertas else None
    directorio_datos = Path(datos.get("config_destino") or ARCHIVO_CONFIG).parent

    avisos: list[str] = []
    alertas_listas = False
    es_local = _es_local(servidor.split(",")[0].split("\\")[0])
    motor = _motor(
        servidor,
        "master",
        datos.get("usuario_admin", ""),
        datos.get("clave_admin", ""),
        bool(datos.get("windows_auth")),
    )
    try:
        with motor.connect() as c:
            edicion = c.execute(text("SELECT CAST(SERVERPROPERTY('EngineEdition') AS INT)")).scalar()
            instancia = c.execute(text("SELECT CAST(SERVERPROPERTY('InstanceName') AS NVARCHAR(128))")).scalar()
        if edicion == _EDICION_EXPRESS:
            raise ErrorInstalacion(
                "Esta edicion de SQL Server (Express) no incluye SQL Server Agent, que ejecuta los respaldos "
                "automaticos. Se necesita SQL Server Standard o superior."
            )
        _ejecutar_con_parametros(
            motor,
            [
                ("EXEC master.dbo.xp_create_subdir ?", (carpeta,)),
                # Sin modelo de recuperacion completo no se pueden respaldar los logs de transacciones.
                (f"ALTER DATABASE [{base}] SET RECOVERY FULL", ()),
                # El log solo se puede respaldar despues de un respaldo completo: se hace uno ya.
                (_comando_respaldo(base, carpeta, "full"), ()),
                _alta_trabajo(
                    TRABAJO_COMPLETO,
                    "Respaldo completo diario de la base de Nexo ERP, y borrado de respaldos antiguos.",
                    [
                        ("Respaldo completo", _comando_respaldo(base, carpeta, "full"), "master"),
                        ("Borrar respaldos antiguos", _comando_limpieza(carpeta, dias), "master"),
                    ],
                    {"freq_type": 4, "freq_interval": 1, "active_start_time": 190000},
                    comando_alerta,
                ),
                _alta_trabajo(
                    TRABAJO_LOG,
                    "Respaldo del log de transacciones de Nexo ERP cada 30 minutos.",
                    [("Respaldo de log", _comando_respaldo(base, carpeta, "log"), "master")],
                    {
                        "freq_type": 4,
                        "freq_interval": 1,
                        "freq_subday_type": 4,
                        "freq_subday_interval": 30,
                        "active_start_time": 0,
                        "active_end_time": 235959,
                    },
                    comando_alerta,
                ),
                _alta_trabajo(
                    TRABAJO_MANTENIMIENTO,
                    "Verificacion de integridad y actualizacion de estadisticas de la base de Nexo ERP (domingos).",
                    [
                        ("Verificar integridad", f"DBCC CHECKDB ([{base}]) WITH NO_INFOMSGS;", "master"),
                        ("Actualizar estadisticas", "EXEC sp_updatestats;", base),
                    ],
                    {"freq_type": 8, "freq_interval": 1, "freq_recurrence_factor": 1, "active_start_time": 30000},
                    comando_alerta,
                ),
            ],
        )
        if alertas:
            try:
                aviso = _configurar_alertas(
                    motor, alertas, instancia, es_local, {"base": base, "carpeta": carpeta, "dias": dias}
                )
            except Exception as exc:
                aviso = f"No se pudieron configurar las alertas por correo: {_traducir_error(exc)}"
            if aviso:
                avisos.append(aviso)
            else:
                alertas_listas = True
    except ErrorInstalacion:
        raise
    except Exception as exc:
        raise ErrorInstalacion(_traducir_error(exc)) from exc
    finally:
        motor.dispose()

    if es_local:
        aviso = _asegurar_agente(instancia)
        if aviso:
            avisos.append(aviso)
    mensajes = [
        f"Respaldos listos en {carpeta}: completo diario a las 19:00, log cada 30 minutos, "
        f"se conservan {dias} dias. Trabajos visibles en SSMS > SQL Server Agent > Trabajos."
    ]
    if alertas_listas:
        mensajes.append(
            f"Alertas por correo si falla un trabajo: {alertas['destinatarios']} (se envio un correo de prueba)."
        )
    aviso = _programar_copia_drive(carpeta, ruta_drive, dias, directorio_datos)
    if aviso:
        avisos.append(aviso)
    else:
        mensajes.append(
            f"Copia a Google Drive cada 30 minutos hacia {ruta_drive} (requiere Google Drive para escritorio abierto)."
        )
    return "\n".join(mensajes + avisos)


def cmd_validar_clave(datos: dict) -> str:
    from app.services.auth import validar_password_policy

    try:
        validar_password_policy(str(datos.get("clave", "")))
    except ValueError as exc:
        raise ErrorInstalacion(str(exc)) from exc
    return "Contrasena valida."


def cmd_generar_clave(_datos: dict) -> str:
    alfabeto = string.ascii_letters + string.digits
    while True:
        clave = "".join(secrets.choice(alfabeto) for _ in range(20))
        if any(c.islower() for c in clave) and any(c.isupper() for c in clave) and any(c.isdigit() for c in clave):
            return clave


COMANDOS = {
    "probar": cmd_probar,
    "servidor": cmd_servidor,
    "estacion": cmd_estacion,
    "actualizar": cmd_actualizar,
    "configurar-sql": cmd_configurar_sql,
    "respaldos": cmd_respaldos,
    "probar-drive": cmd_probar_drive,
    "validar-clave": cmd_validar_clave,
    "generar-clave": cmd_generar_clave,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("comando", choices=sorted(COMANDOS))
    parser.add_argument("--entrada", help="JSON con los datos del comando")
    parser.add_argument("--salida", required=True, help="archivo de resultado (OK/ERROR + mensaje)")
    args = parser.parse_args(argv)

    salida = Path(args.salida)
    try:
        datos = json.loads(Path(args.entrada).read_text(encoding="utf-8-sig")) if args.entrada else {}
        mensaje = COMANDOS[args.comando](datos)
        estado = "OK"
    except ErrorInstalacion as exc:
        estado, mensaje = "ERROR", str(exc)
    except pyodbc.Error as exc:
        estado, mensaje = "ERROR", _traducir_error(exc)
    except Exception as exc:  # nunca dejar al instalador sin resultado
        estado, mensaje = "ERROR", f"Error inesperado: {exc.__class__.__name__}: {exc}"
    salida.parent.mkdir(parents=True, exist_ok=True)
    # Sin BOM y con saltos de linea simples: el instalador (Pascal) lo lee como texto plano.
    salida.write_text(f"{estado}\n{mensaje}\n", encoding="utf-8", newline="\n")
    return 0 if estado == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
