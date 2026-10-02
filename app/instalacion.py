"""
Herramientas que ejecuta el instalador (Inno Setup, packaging/instalador.iss), empaquetadas
como DJ-Herramientas.exe. Inno no puede hablar con SQL Server, asi que cada paso de base de
datos es un subcomando de este modulo.

Contrato con el instalador (para no pasar claves por la linea de comandos, que otros procesos
pueden ver):

    DJ-Herramientas.exe <comando> --entrada entrada.json --salida resultado.txt

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

from app.rutas import ARCHIVO_CONFIG, RAIZ_PROYECTO

DRIVER_ODBC = "ODBC Driver 18 for SQL Server"
_IDENTIFICADOR_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,39}$")
_LOCALES = {"", ".", "(local)", "localhost", "127.0.0.1", "::1"}


class ErrorInstalacion(Exception):
    """Mensaje pensado para mostrarse tal cual al usuario del instalador."""


# ── Conexion ────────────────────────────────────────────────────────────────


def _cadena_odbc(servidor: str, base: str, usuario: str, clave: str, windows_auth: bool) -> str:
    autenticacion = "Trusted_Connection=yes;" if windows_auth else f"UID={usuario};PWD={clave.replace('}', '}}')};"
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


def _escribir_config(destino: Path, valores: dict[str, str]) -> None:
    """Escribe/actualiza config.env conservando las claves que ya tenia (SMTP, etc.)."""
    existentes: dict[str, str] = {}
    if destino.exists():
        for linea in destino.read_text(encoding="utf-8").splitlines():
            if "=" in linea and not linea.lstrip().startswith("#"):
                clave, _, valor = linea.partition("=")
                existentes[clave.strip()] = valor
    existentes.update(valores)
    destino.parent.mkdir(parents=True, exist_ok=True)
    cuerpo = "# Generado por el instalador de Distribuidora DJ. Editar con cuidado.\n"
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
        return f"SIN CAMBIOS: la instancia '{nombre}' ya esta configurada (puerto {puerto})."
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
    return f"CONFIGURADO: instancia '{nombre}' ({descripcion}). El servicio de SQL Server se reinicio."


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
    _escribir_config(
        destino,
        {
            "DB_SERVER": servidor,
            "DB_NAME": base,
            "DB_USER": usuario_app,
            "DB_PASSWORD": clave_app,
            "DB_DRIVER": DRIVER_ODBC,
            "DB_TRUST_SERVER_CERTIFICATE": "yes",
            "DB_TRUSTED_CONNECTION": "no",
            "MODO_INSTALACION": "SERVIDOR",
        },
    )
    host_estaciones = _host_para_estaciones(servidor)
    (destino.parent / "datos_estaciones.txt").write_text(
        "DATOS PARA INSTALAR LAS ESTACIONES\n"
        "==================================\n"
        "En cada PC cliente ejecute el instalador, elija 'Estacion' e ingrese:\n\n"
        f"  Servidor SQL : {host_estaciones}\n"
        f"  Base de datos: {base}\n"
        f"  Usuario SQL  : {usuario_app}\n"
        f"  Contrasena   : {clave_app}\n\n"
        "Guarde esta informacion en un lugar seguro y elimine este archivo cuando termine.\n"
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
    _escribir_config(
        destino,
        {
            "DB_SERVER": servidor,
            "DB_NAME": base,
            "DB_USER": usuario,
            "DB_PASSWORD": clave,
            "DB_DRIVER": DRIVER_ODBC,
            "DB_TRUST_SERVER_CERTIFICATE": "yes",
            "DB_TRUSTED_CONNECTION": "no",
            "MODO_INSTALACION": "ESTACION",
        },
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
