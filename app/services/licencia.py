"""
Licenciamiento de la app (cliente). Una licencia por EMPRESA, no por PC:

    SERVIDOR  ── activa la clave (atada a su hardware), la renueva contra Cloudflare cada
                 pocos minutos (servicio de Windows, app/servicio_licencia.py) y guarda el
                 token firmado en SQL Server (tabla licencia_sistema).
    ESTACION  ── se conecta a ese SQL Server, lee el token y lo verifica (firma Ed25519,
                 vencimiento, gracia, limite de estaciones). No activa ni renueva nada.

Cuatro piezas:

1. Activar/validar contra el servidor de licencias (licencias/worker/). El token firmado trae
   `valido_hasta` (maximo 7 dias: la gracia sin internet del SERVIDOR), `max_estaciones` y la
   lista de estaciones autorizadas.
2. `estado_actual`: calcula el estado SIN red, a partir del token en la base. Verifica la
   firma con la clave publica embebida; en el servidor, que el token sea de ESTA PC; el
   vencimiento; que el reloj no haya retrocedido; y que esta estacion tenga puesto.
3. Registro de estaciones: cada PC que abre la app se anota en licencia_estaciones; el
   servidor manda esa lista a Cloudflare, que fija quienes entran (las mas antiguas primero).
4. Modo "solo lectura": un hook a nivel de motor SQLAlchemy (`instalar_gate`) rechaza
   INSERT/UPDATE/DELETE sobre las tablas de negocio cuando el estado no es ACTIVA. Es un unico
   punto de control para todos los servicios (hacen commit por su cuenta, ver CLAUDE.md).

Limite honesto: esto sube el costo de usar la app sin licencia, no lo hace imposible -- el
codigo corre en la PC del cliente. Ver licencias/README.md.
"""

import base64
import ctypes
import hashlib
import json
import logging
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy import event, text

from app import config

logger = logging.getLogger(__name__)

# ── Estados ─────────────────────────────────────────────────────────────────

ESTADO_ACTIVA = "ACTIVA"
ESTADO_SIN_LICENCIA = "SIN_LICENCIA"
ESTADO_VENCIDA = "VENCIDA"
ESTADO_REVOCADA = "REVOCADA"
ESTADO_VALIDAR_EN_LINEA = "VALIDAR_EN_LINEA"  # el servidor paso la gracia sin renovar el token
ESTADO_INVALIDA = "INVALIDA"  # firma mala, otra PC, o reloj movido hacia atras
ESTADO_LIMITE_ESTACIONES = "LIMITE_ESTACIONES"  # esta estacion no tiene puesto en la licencia

MODO_SERVIDOR = "SERVIDOR"
MODO_ESTACION = "ESTACION"

TOLERANCIA_RELOJ_SEG = 900  # 15 min de desajuste normal entre relojes antes de sospechar
PERSISTIR_RELOJ_CADA_SEG = 300
CACHE_DB_SEG = 30  # cuanto se confia en la lectura de licencia_sistema antes de releerla
REGISTRO_ESTACION_CADA_SEG = 600
VENTANA_ESTACIONES_SEG = 30 * 86400  # igual que el servidor: una estacion inactiva 30 dias libera su puesto
TIMEOUT_HTTP_SEG = 10

# Tablas que SI se pueden escribir en modo solo lectura: el login (intentos fallidos,
# bloqueo), la recuperacion de clave, la auditoria y las propias tablas de licencia no pueden
# quedar bloqueadas o el cliente no podria ni entrar a renovar la licencia.
TABLAS_EXENTAS = frozenset(
    {
        "usuarios",
        "auditoria",
        "codigos_verificacion",
        "schema_migrations",
        "licencia_sistema",
        "licencia_estaciones",
    }
)

_ESCRITURA_RE = re.compile(
    r"^\s*(?:INSERT\s+INTO|UPDATE|DELETE(?:\s+FROM)?|MERGE\s+INTO|TRUNCATE\s+TABLE)\s+(?:\[?dbo\]?\.)?\[?(\w+)\]?",
    re.IGNORECASE,
)

# Marca de tiempo mas reciente vista en esta PC, para detectar que alguien atraso el reloj.
# Va en ProgramData (visible para el servicio de Windows, que corre como otro usuario) y cifrada
# con DPAPI a nivel de maquina.
RUTA_RELOJ = Path(os.getenv("PROGRAMDATA") or Path.home()) / "DistribuidoraDJ" / "reloj.dat"
# Segunda copia de las marcas, en HKLM (solo la puede escribir el servicio o un administrador: un
# usuario normal no puede borrarla). None la desactiva (pruebas).
CLAVE_REGISTRO: str | None = r"SOFTWARE\DistribuidoraDJ"


class LicenciaError(Exception):
    """Error de negocio mostrable al usuario (clave invalida, ya usada en otra PC, etc.)."""


class LicenciaRedError(LicenciaError):
    """No se pudo hablar con el servidor (sin internet, timeout, 5xx)."""


class LicenciaSoloLecturaError(Exception):
    """La licencia no permite escribir; lanzado por el hook de motor (`instalar_gate`)."""


class TokenInvalidoError(Exception):
    pass


@dataclass(frozen=True)
class EstadoLicencia:
    estado: str
    mensaje: str
    plan: str | None = None
    cliente: str | None = None
    expira: datetime | None = None
    valido_hasta: datetime | None = None
    max_estaciones: int | None = None

    @property
    def permite_escritura(self) -> bool:
        return self.estado == ESTADO_ACTIVA


# ── Token firmado ───────────────────────────────────────────────────────────


def _b64u_decode(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def verificar_token(token: str, clave_publica_b64: str | None = None) -> dict:
    """Verifica la firma Ed25519 del token (`payload_b64url.firma_b64url`) y devuelve el
    payload. Lanza TokenInvalidoError si la firma o el formato no cuadran."""
    clave_publica_b64 = clave_publica_b64 or config.LICENCIA_PUBLIC_KEY_B64
    try:
        payload_b64, firma_b64 = token.split(".")
        clave = Ed25519PublicKey.from_public_bytes(base64.b64decode(clave_publica_b64))
        clave.verify(_b64u_decode(firma_b64), payload_b64.encode("ascii"))
        payload = json.loads(_b64u_decode(payload_b64))
    except (ValueError, InvalidSignature, TypeError) as exc:
        raise TokenInvalidoError("Firma de licencia invalida") from exc
    if not isinstance(payload, dict) or "hw" not in payload or "valido_hasta" not in payload:
        raise TokenInvalidoError("Token de licencia mal formado")
    return payload


# ── Identificador de esta PC ───────────────────────────────────────────────

_hw_id_cache: str | None = None


def hw_id() -> str:
    """Huella (SHA-256) de esta PC: MachineGuid de Windows + serial del volumen C:. Se
    manda al servidor en vez de los valores crudos."""
    global _hw_id_cache
    if _hw_id_cache is not None:
        return _hw_id_cache
    partes: list[str] = []
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            ) as llave:
                partes.append(str(winreg.QueryValueEx(llave, "MachineGuid")[0]))
        except OSError:
            logger.warning("No se pudo leer MachineGuid")
        try:
            serial = ctypes.c_uint32(0)
            ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p("C:\\"), None, 0, ctypes.byref(serial), None, None, None, 0
            )
            partes.append(f"{serial.value:08x}")
        except (OSError, AttributeError):
            logger.warning("No se pudo leer el serial del volumen")
    if not partes:
        partes.append(str(uuid.getnode()))
    _hw_id_cache = hashlib.sha256("|".join(partes).encode("utf-8")).hexdigest()
    return _hw_id_cache


# ── Reloj (anti-retroceso), cifrado con DPAPI de maquina ───────────────────

_CRYPTPROTECT_LOCAL_MACHINE = 0x4


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(datos: bytes, proteger: bool) -> bytes:
    """CryptProtectData / CryptUnprotectData con alcance de MAQUINA: lo descifra cualquier
    usuario de esta PC (el servicio de Windows y el usuario interactivo), pero copiar el
    archivo a otra PC no sirve."""
    buffer = ctypes.create_string_buffer(datos, len(datos))  # referencia viva hasta que DPAPI termine
    entrada = _Blob(len(datos), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    salida = _Blob()
    funcion = ctypes.windll.crypt32.CryptProtectData if proteger else ctypes.windll.crypt32.CryptUnprotectData
    # Misma aridad: (in, descripcion, entropia, reservado, prompt, flags, out).
    if not funcion(ctypes.byref(entrada), None, None, None, None, _CRYPTPROTECT_LOCAL_MACHINE, ctypes.byref(salida)):
        raise OSError("DPAPI fallo")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(salida.pbData, ctypes.c_void_p))


# Marcas de tiempo contra la manipulacion del reloj de Windows. Se guardan en TRES sitios (archivo,
# registro y base de datos) y siempre manda la mas reciente: borrar uno solo no reinicia nada.
#
#   ultimo_visto    la hora mas alta que esta PC ha visto. Si el reloj queda por DEBAJO, alguien lo atraso.
#   ancla_servidor  la hora del servidor de licencias (`emitido` del ultimo token), a prueba de reloj local.
#   ancla_tick      contador de arranque de Windows (GetTickCount64) en ese instante. NO depende de la
#                   fecha del sistema, asi que `ancla_servidor + (tick_ahora - ancla_tick)` es una COTA
#                   INFERIOR de la hora real: tras un reinicio el contador vuelve a 0 y la cota solo se
#                   queda mas baja (nunca mas alta), asi que no da falsos positivos.
_MARCAS_VACIAS = {"ultimo_visto": 0.0, "ancla_servidor": 0.0, "ancla_tick": 0}
_NOMBRE_VALOR_REGISTRO = "Reloj"


def _tick_ms() -> int:
    if sys.platform == "win32":
        try:
            funcion = ctypes.windll.kernel32.GetTickCount64
            funcion.restype = ctypes.c_uint64
            return int(funcion())
        except (OSError, AttributeError):
            pass
    return int(time.monotonic() * 1000)


def _normalizar_marcas(bruto) -> dict:
    marcas = dict(_MARCAS_VACIAS)
    if isinstance(bruto, dict):
        for clave, tipo in (("ultimo_visto", float), ("ancla_servidor", float), ("ancla_tick", int)):
            try:
                marcas[clave] = tipo(bruto.get(clave) or 0)
            except (TypeError, ValueError):
                pass
    return marcas


def _fusionar_marcas(*lista: dict) -> dict:
    """Lo mas reciente gana: ultimo_visto = el mayor; el ancla es la del token mas nuevo (con SU tick)."""
    resultado = dict(_MARCAS_VACIAS)
    for marcas in lista:
        marcas = _normalizar_marcas(marcas)
        resultado["ultimo_visto"] = max(resultado["ultimo_visto"], marcas["ultimo_visto"])
        if marcas["ancla_servidor"] > resultado["ancla_servidor"]:
            resultado["ancla_servidor"], resultado["ancla_tick"] = marcas["ancla_servidor"], marcas["ancla_tick"]
    return resultado


def _empaquetar_marcas(marcas: dict) -> str:
    crudo = json.dumps(marcas).encode("utf-8")
    protegido = sys.platform == "win32"
    contenido = _dpapi(crudo, True) if protegido else crudo
    return json.dumps({"v": 2, "dpapi": protegido, "datos": base64.b64encode(contenido).decode("ascii")})


def _desempaquetar_marcas(texto: str) -> dict:
    envoltorio = json.loads(texto)
    contenido = base64.b64decode(envoltorio["datos"])
    crudo = _dpapi(contenido, False) if envoltorio.get("dpapi") else contenido
    return _normalizar_marcas(json.loads(crudo))


def _leer_marcas_archivo() -> dict:
    try:
        return _desempaquetar_marcas(RUTA_RELOJ.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return dict(_MARCAS_VACIAS)
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("reloj.dat ilegible; se ignora")
        return dict(_MARCAS_VACIAS)


def _leer_marcas_registro() -> dict:
    if not CLAVE_REGISTRO or sys.platform != "win32":
        return dict(_MARCAS_VACIAS)
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, CLAVE_REGISTRO, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY
        ) as llave:
            return _desempaquetar_marcas(winreg.QueryValueEx(llave, _NOMBRE_VALOR_REGISTRO)[0])
    except (OSError, ValueError, KeyError, TypeError):
        return dict(_MARCAS_VACIAS)


def _escribir_marcas_archivo(texto: str) -> None:
    RUTA_RELOJ.parent.mkdir(parents=True, exist_ok=True)
    temporal = RUTA_RELOJ.with_suffix(".tmp")
    temporal.write_text(texto, encoding="utf-8")
    os.replace(temporal, RUTA_RELOJ)


def _escribir_marcas_registro(texto: str) -> None:
    if not CLAVE_REGISTRO or sys.platform != "win32":
        return
    try:
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_LOCAL_MACHINE, CLAVE_REGISTRO, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY
        ) as llave:
            winreg.SetValueEx(llave, _NOMBRE_VALOR_REGISTRO, 0, winreg.REG_SZ, texto)
    except OSError:
        # Un usuario normal no puede escribir en HKLM: lo hace el servicio / el instalador.
        logger.debug("No se pudo escribir la marca en el registro (falta de permisos)")


_marcas_cache: tuple[dict, float] = (dict(_MARCAS_VACIAS), 0.0)  # (marcas locales, monotonic hasta el que valen)


def _marcas_locales() -> dict:
    """Marcas de archivo + registro, cacheadas 60 s: el gate las pide en cada escritura."""
    global _marcas_cache
    marcas, vigente_hasta = _marcas_cache
    if time.monotonic() < vigente_hasta:
        return marcas
    marcas = _fusionar_marcas(_leer_marcas_archivo(), _leer_marcas_registro())
    _marcas_cache = (marcas, time.monotonic() + 60)
    return marcas


def _guardar_marcas_locales(nuevas: dict, reemplazar: bool = False) -> dict:
    """Escribe archivo y registro. `reemplazar=True` solo tras una validacion en linea: ahi la hora del
    servidor de licencias es la verdad y borra cualquier marca adelantada por un reloj mal puesto."""
    global _marcas_cache
    marcas = _normalizar_marcas(nuevas) if reemplazar else _fusionar_marcas(_marcas_locales(), nuevas)
    texto = _empaquetar_marcas(marcas)
    try:
        _escribir_marcas_archivo(texto)
    except OSError:
        logger.warning("No se pudo escribir reloj.dat", exc_info=True)
    _escribir_marcas_registro(texto)
    _marcas_cache = (marcas, time.monotonic() + 60)
    return marcas


def _marcas_efectivas(datos: dict | None) -> dict:
    """Marcas locales + las de la base de datos (que viven en la fila de licencia_sistema)."""
    return _fusionar_marcas(_marcas_locales(), datos or {})


def _piso_de_tiempo(marcas: dict) -> tuple[float, float]:
    """(piso_total, piso_del_ancla): la hora que NO puede ser anterior. El piso del ancla es una cota
    inferior fiable de la hora real; el total ademas incluye lo mas alto que se haya visto."""
    ancla = marcas["ancla_servidor"]
    transcurrido = max(0, _tick_ms() - marcas["ancla_tick"]) / 1000 if ancla else 0.0
    piso_ancla = ancla + transcurrido
    return max(marcas["ultimo_visto"], piso_ancla), piso_ancla


# ── Almacen de la licencia (SQL Server) ─────────────────────────────────────


class AlmacenDB:
    """Lee/escribe la fila unica de dbo.licencia_sistema. Abre su propia sesion corta (nunca
    reutiliza la de un servicio), asi que sirve desde cualquier hilo y desde el hook del gate."""

    def leer(self) -> dict | None:
        from app.db.session import SessionLocal

        session = SessionLocal()
        try:
            fila = (
                session.execute(
                    text(
                        "SELECT clave, token, rechazo, mensaje, ultimo_visto, ancla_servidor, ancla_tick "
                        "FROM dbo.licencia_sistema WHERE id = 1"
                    )
                )
                .mappings()
                .first()
            )
            return dict(fila) if fila else None
        finally:
            session.close()

    def guardar(self, datos: dict) -> None:
        from app.db.session import SessionLocal

        valores = {
            "clave": datos.get("clave"),
            "token": datos.get("token"),
            "rechazo": datos.get("rechazo"),
            "mensaje": (datos.get("mensaje") or None) and datos["mensaje"][:300],
        }
        session = SessionLocal()
        try:
            actualizadas = session.execute(
                text(
                    "UPDATE dbo.licencia_sistema SET clave = :clave, token = :token, rechazo = :rechazo, "
                    "mensaje = :mensaje, actualizado_en = GETDATE() WHERE id = 1"
                ),
                valores,
            ).rowcount
            if not actualizadas:
                session.execute(
                    text(
                        "INSERT INTO dbo.licencia_sistema (id, clave, token, rechazo, mensaje) "
                        "VALUES (1, :clave, :token, :rechazo, :mensaje)"
                    ),
                    valores,
                )
            session.commit()
        finally:
            session.close()

    def guardar_marcas(self, marcas: dict, reemplazar: bool = False) -> None:
        """Copia de las marcas de tiempo en la fila de licencia (si todavia no hay fila, no hay nada que marcar)."""
        from app.db.session import SessionLocal

        valores = {
            "uv": int(marcas["ultimo_visto"]),
            "asv": int(marcas["ancla_servidor"]),
            "atk": int(marcas["ancla_tick"]),
        }
        if reemplazar:
            sentencia = (
                "UPDATE dbo.licencia_sistema SET ultimo_visto = :uv, ancla_servidor = :asv, ancla_tick = :atk "
                "WHERE id = 1"
            )
        else:
            sentencia = (
                "UPDATE dbo.licencia_sistema SET "
                "ultimo_visto = CASE WHEN ultimo_visto IS NULL OR ultimo_visto < :uv THEN :uv ELSE ultimo_visto END "
                "WHERE id = 1"
            )
            valores = {"uv": valores["uv"]}
        session = SessionLocal()
        try:
            session.execute(text(sentencia), valores)
            session.commit()
        finally:
            session.close()

    def hora_servidor(self) -> float:
        """Hora UTC del SQL Server (epoch). Las estaciones la usan en vez de su propio reloj."""
        from app.db.session import SessionLocal

        session = SessionLocal()
        try:
            return float(session.execute(text("SELECT DATEDIFF_BIG(SECOND, '1970-01-01', SYSUTCDATETIME())")).scalar())
        finally:
            session.close()

    def estaciones(self) -> list[dict]:
        from app.db.session import SessionLocal

        session = SessionLocal()
        try:
            filas = session.execute(
                text("SELECT hw_id, nombre, primera_vez, ultima_vez FROM dbo.licencia_estaciones ORDER BY primera_vez")
            ).mappings()
            return [dict(f) for f in filas]
        finally:
            session.close()

    def registrar_estacion(self, hw: str, nombre: str) -> None:
        from app.db.session import SessionLocal

        session = SessionLocal()
        try:
            actualizadas = session.execute(
                text("UPDATE dbo.licencia_estaciones SET nombre = :nombre, ultima_vez = GETDATE() WHERE hw_id = :hw"),
                {"hw": hw, "nombre": nombre},
            ).rowcount
            if not actualizadas:
                session.execute(
                    text("INSERT INTO dbo.licencia_estaciones (hw_id, nombre) VALUES (:hw, :nombre)"),
                    {"hw": hw, "nombre": nombre},
                )
            session.commit()
        finally:
            session.close()


# ── Servicio ────────────────────────────────────────────────────────────────

_lock = threading.RLock()
_almacen = AlmacenDB()
_cache: dict | None = None
_cache_vigente_hasta = 0.0
_ultimo_reloj_persistido = 0.0
_ultimo_registro_estacion = 0.0
# (hora UTC del SQL Server, monotonic en ese instante): las estaciones calculan "ahora" a partir de aqui
# y NO de su reloj, que el usuario de esa PC puede cambiar. monotonic() no depende de la fecha de Windows.
_ancla_hora: tuple[float, float] | None = None


def invalidar_cache() -> None:
    global _cache, _cache_vigente_hasta
    with _lock:
        _cache, _cache_vigente_hasta = None, 0.0


def _datos_actuales() -> dict | None:
    """Fila de licencia_sistema, con cache corto: el gate la consulta en cada escritura y no
    puede ir a la base cada vez. Si la base no responde se usa la ultima lectura buena."""
    global _cache, _cache_vigente_hasta
    ahora = time.monotonic()
    with _lock:
        if ahora < _cache_vigente_hasta:
            return _cache
        try:
            _cache = _almacen.leer()
        except Exception:
            logger.warning("No se pudo leer licencia_sistema", exc_info=True)
            if _cache is None:
                raise
        else:
            _anclar_hora_del_servidor_sql()
        _cache_vigente_hasta = ahora + CACHE_DB_SEG
        return _cache


def _anclar_hora_del_servidor_sql() -> None:
    global _ancla_hora
    try:
        _ancla_hora = (float(_almacen.hora_servidor()), time.monotonic())
    except Exception:
        logger.debug("No se pudo leer la hora del servidor SQL", exc_info=True)


def _ahora_estacion() -> float:
    """Hora actual segun el SQL Server, avanzada con el reloj monotonico. Sin ancla (no se pudo consultar
    nunca) cae al reloj local."""
    with _lock:
        if _ancla_hora is None:
            return time.time()
        hora_sql, monotonico = _ancla_hora
        return hora_sql + (time.monotonic() - monotonico)


def _guardar(datos: dict) -> None:
    global _cache, _cache_vigente_hasta
    with _lock:
        _almacen.guardar(datos)
        _cache, _cache_vigente_hasta = datos, time.monotonic() + CACHE_DB_SEG


def _post(ruta: str, cuerpo: dict) -> tuple[int, dict]:
    peticion = urllib.request.Request(
        f"{config.LICENCIA_URL}{ruta}",
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "DistribuidoraDJ/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_HTTP_SEG) as respuesta:
            return respuesta.status, json.loads(respuesta.read())
    except urllib.error.HTTPError as exc:
        try:
            cuerpo_error = json.loads(exc.read())
        except ValueError:
            cuerpo_error = {}
        if exc.code >= 500:
            raise LicenciaRedError("El servidor de licencias no esta disponible. Intente mas tarde.") from exc
        return exc.code, cuerpo_error
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise LicenciaRedError("No se pudo conectar con el servidor de licencias. Revise su internet.") from exc


def _normalizar_clave(clave: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", clave.upper())


def _es_servidor() -> bool:
    return config.MODO_INSTALACION == MODO_SERVIDOR


def _exigir_servidor() -> None:
    if not _es_servidor():
        raise LicenciaError("Esta es una estacion: la licencia se gestiona en el servidor.")


def _estaciones_reportadas() -> list[dict]:
    """Estaciones vistas en los ultimos 30 dias, en el formato que espera el servidor de licencias."""
    limite = time.time() - VENTANA_ESTACIONES_SEG
    reportadas = []
    for fila in _almacen.estaciones():
        ultima = fila["ultima_vez"].timestamp()
        if ultima >= limite:
            reportadas.append({"hw": fila["hw_id"].strip(), "nombre": fila["nombre"], "ultima": int(ultima)})
    return reportadas


class LicenciaService:
    @staticmethod
    def habilitada() -> bool:
        return bool(config.LICENCIA_URL and config.LICENCIA_PUBLIC_KEY_B64)

    @staticmethod
    def estado_actual(ahora: float | None = None) -> EstadoLicencia:
        if not LicenciaService.habilitada():
            return EstadoLicencia(ESTADO_ACTIVA, "Licenciamiento no habilitado en este entorno.")
        try:
            datos = _datos_actuales()
        except Exception:
            return EstadoLicencia(ESTADO_INVALIDA, "No se pudo consultar la licencia en el servidor.")
        if ahora is None:
            # Estacion: la hora la da el SQL Server (el reloj de esta PC no cuenta). Servidor: su propio
            # reloj, vigilado por las marcas de tiempo de mas abajo.
            ahora = time.time() if _es_servidor() else _ahora_estacion()

        sin_licencia = EstadoLicencia(
            ESTADO_SIN_LICENCIA,
            "Esta instalacion no tiene una licencia activada."
            if _es_servidor()
            else "El servidor no tiene una licencia activada.",
        )
        if not datos:
            return sin_licencia
        if datos.get("rechazo"):
            estado = ESTADO_VENCIDA if datos["rechazo"] == "VENCIDA" else ESTADO_REVOCADA
            return EstadoLicencia(estado, datos.get("mensaje") or "La licencia fue rechazada por el servidor.")
        if not datos.get("token"):
            return sin_licencia

        try:
            payload = verificar_token(datos["token"])
        except TokenInvalidoError:
            return EstadoLicencia(ESTADO_INVALIDA, "La licencia guardada no es valida. Vuelva a activarla.")
        # Solo el servidor comprueba el hardware: el token es de SU PC, las estaciones no lo
        # son. Una base copiada a otro servidor trae un token que ese equipo no puede renovar.
        if _es_servidor() and payload["hw"] != hw_id():
            return EstadoLicencia(ESTADO_INVALIDA, "La licencia pertenece a otra computadora.")

        info = {
            "plan": payload.get("plan"),
            "cliente": payload.get("cliente"),
            "expira": datetime.fromtimestamp(payload["expira"]) if payload.get("expira") else None,
            "valido_hasta": datetime.fromtimestamp(payload["valido_hasta"]),
            "max_estaciones": payload.get("max_estaciones"),
        }

        ultimo_visto = 0.0
        if _es_servidor():
            with _lock:
                marcas = _marcas_efectivas(datos)
            piso, piso_ancla = _piso_de_tiempo(marcas)
            ultimo_visto = marcas["ultimo_visto"]
            if ahora < piso - TOLERANCIA_RELOJ_SEG:
                return EstadoLicencia(
                    ESTADO_INVALIDA,
                    "La fecha y hora del equipo son anteriores a la ultima vez que se uso la app o a la hora del "
                    "servidor de licencias. Corrija la fecha y hora de Windows y conectese a internet para "
                    "validar la licencia.",
                    **info,
                )
            # La cota del ancla es una hora real minima: si el reloj va por detras (dentro de la tolerancia)
            # se usa ella para decidir el vencimiento.
            ahora = max(ahora, piso_ancla)
        if payload.get("expira") and ahora > payload["expira"]:
            return EstadoLicencia(ESTADO_VENCIDA, "La licencia esta vencida. Renuevela para seguir operando.", **info)
        if ahora > payload["valido_hasta"]:
            return EstadoLicencia(
                ESTADO_VALIDAR_EN_LINEA,
                "El servidor lleva demasiado tiempo sin validar la licencia. Revise su conexion a internet "
                "y el servicio de licencia.",
                **info,
            )

        # Puesto de esta PC. Tokens viejos (sin max_estaciones) no limitan. Un puesto libre se
        # concede de inmediato aunque el token aun no liste a esta estacion (se registro hace poco).
        maximo = payload.get("max_estaciones")
        if maximo is not None:
            autorizadas = payload.get("estaciones", [])
            if hw_id() not in autorizadas and len(autorizadas) >= maximo:
                return EstadoLicencia(
                    ESTADO_LIMITE_ESTACIONES,
                    f"La licencia permite {maximo} estacion(es) y ya estan ocupadas. "
                    "Amplie el numero de estaciones con su proveedor.",
                    **info,
                )

        if _es_servidor():
            LicenciaService._persistir_reloj(ahora, ultimo_visto)
        return EstadoLicencia(ESTADO_ACTIVA, "Licencia activa.", **info)

    @staticmethod
    def _persistir_reloj(ahora: float, ultimo_visto: float) -> None:
        global _ultimo_reloj_persistido
        with _lock:
            if ahora > ultimo_visto and ahora - _ultimo_reloj_persistido > PERSISTIR_RELOJ_CADA_SEG:
                marcas = _guardar_marcas_locales({"ultimo_visto": ahora})
                _ultimo_reloj_persistido = ahora
                try:
                    _almacen.guardar_marcas(marcas)
                except Exception:
                    logger.warning("No se pudo guardar la marca de tiempo en la base de datos", exc_info=True)

    @staticmethod
    def _guardar_token(clave: str, token: str) -> None:
        payload = verificar_token(token)  # nunca guardar algo que no verifica
        _guardar({"clave": clave, "token": token, "rechazo": None, "mensaje": None})
        # La licencia acaba de confirmarse con el servidor de licencias: su hora (`emitido`) es la verdad.
        # Se REEMPLAZAN las marcas (no se fusionan), asi un reloj adelantado por error no deja la app
        # bloqueada para siempre.
        emitido = float(payload.get("emitido") or time.time())
        marcas = _guardar_marcas_locales(
            {"ultimo_visto": emitido, "ancla_servidor": emitido, "ancla_tick": _tick_ms()}, reemplazar=True
        )
        try:
            _almacen.guardar_marcas(marcas, reemplazar=True)
        except Exception:
            logger.warning("No se pudo guardar la marca de tiempo en la base de datos", exc_info=True)

    @staticmethod
    def activar(clave: str) -> EstadoLicencia:
        _exigir_servidor()
        clave = _normalizar_clave(clave)
        if len(clave) < 16:
            raise LicenciaError("La clave de licencia no tiene el formato correcto.")
        LicenciaService.registrar_estacion(forzar=True)
        estado, cuerpo = _post(
            "/v1/activar", {"clave": clave, "hw_id": hw_id(), "estaciones": _estaciones_reportadas()}
        )
        token = cuerpo.get("token")
        if estado != 200 or not token:
            raise LicenciaError(cuerpo.get("error") or "No se pudo activar la licencia.")
        try:
            LicenciaService._guardar_token(clave, token)
        except TokenInvalidoError as exc:
            raise LicenciaError("El servidor devolvio una licencia invalida.") from exc
        return LicenciaService.estado_actual()

    @staticmethod
    def validar_en_linea() -> EstadoLicencia:
        """Renueva el token contra el servidor (solo en el servidor). Sin internet no cambia
        nada: el token guardado sigue valiendo hasta su `valido_hasta`. Si el servidor rechaza
        la licencia (revocada/vencida/otra PC), queda registrado y el estado deja de ser ACTIVA
        de inmediato para toda la red."""
        _exigir_servidor()
        with _lock:
            datos = _datos_actuales()
        if not datos or not datos.get("clave"):
            return LicenciaService.estado_actual()
        estado, cuerpo = _post(
            "/v1/validar", {"clave": datos["clave"], "hw_id": hw_id(), "estaciones": _estaciones_reportadas()}
        )
        if estado == 200 and cuerpo.get("token"):
            try:
                LicenciaService._guardar_token(datos["clave"], cuerpo["token"])
            except TokenInvalidoError:
                logger.error("El servidor devolvio un token que no verifica")
        elif estado in (401, 403, 404, 409):
            _guardar(
                {
                    "clave": datos["clave"],
                    "token": None,
                    "rechazo": cuerpo.get("codigo") or "REVOCADA",
                    "mensaje": cuerpo.get("error"),
                }
            )
        return LicenciaService.estado_actual()

    @staticmethod
    def registrar_estacion(forzar: bool = False) -> None:
        """Anota esta PC en licencia_estaciones (se llama al abrir la app y cada hora). Es
        silencioso: un fallo aqui nunca debe impedir trabajar."""
        global _ultimo_registro_estacion
        ahora = time.monotonic()
        with _lock:
            if not forzar and ahora - _ultimo_registro_estacion < REGISTRO_ESTACION_CADA_SEG:
                return
            try:
                _almacen.registrar_estacion(hw_id(), socket.gethostname()[:60])
                _ultimo_registro_estacion = ahora
            except Exception:
                logger.warning("No se pudo registrar esta estacion", exc_info=True)

    @staticmethod
    def refrescar_periodico() -> EstadoLicencia:
        """Lo que la app hace cada hora (y al abrir): registrar esta PC y ponerse al dia. El
        servidor ademas renueva el token; la estacion solo relee el estado desde la base."""
        LicenciaService.registrar_estacion()
        if _es_servidor():
            try:
                return LicenciaService.validar_en_linea()
            except LicenciaRedError:
                return LicenciaService.estado_actual()
        invalidar_cache()
        return LicenciaService.estado_actual()

    @staticmethod
    def estaciones_registradas() -> list[dict]:
        """Para la pestaña Licencia: nombre, ultima vez vista y si hoy tiene puesto."""
        datos = _datos_actuales()
        autorizadas: set[str] = set()
        if datos and datos.get("token"):
            try:
                autorizadas = set(verificar_token(datos["token"]).get("estaciones", []))
            except TokenInvalidoError:
                pass
        return [
            {
                "nombre": f["nombre"],
                "ultima_vez": f["ultima_vez"],
                "autorizada": f["hw_id"].strip() in autorizadas,
                "esta_pc": f["hw_id"].strip() == hw_id(),
            }
            for f in _almacen.estaciones()
        ]

    @staticmethod
    def olvidar() -> None:
        """Solo para pruebas / soporte: borra la licencia guardada."""
        _guardar({"clave": None, "token": None, "rechazo": None, "mensaje": None})


# ── Gate de solo lectura ────────────────────────────────────────────────────

_gate_instalado_en: set[int] = set()
_aviso_bloqueo = None  # callable(EstadoLicencia) | None, lo registra la UI


def registrar_aviso_bloqueo(funcion) -> None:
    """La UI registra aqui como avisar al usuario cuando se le bloquea una escritura. Los
    paneles atrapan cualquier Exception y muestran un "no se pudo guardar" generico; sin
    este aviso el usuario no sabria que la causa es la licencia."""
    global _aviso_bloqueo
    _aviso_bloqueo = funcion


def _hook_antes_de_ejecutar(conn, cursor, statement, parameters, context, executemany):
    coincidencia = _ESCRITURA_RE.match(statement)
    if coincidencia is None or coincidencia.group(1).lower() in TABLAS_EXENTAS:
        return
    estado = LicenciaService.estado_actual()
    if not estado.permite_escritura:
        if _aviso_bloqueo is not None:
            try:
                _aviso_bloqueo(estado)
            except Exception:
                logger.exception("Fallo el aviso de bloqueo por licencia")
        raise LicenciaSoloLecturaError(estado.mensaje)


def instalar_gate(motor) -> None:
    """Engancha el chequeo de licencia al motor SQLAlchemy dado. Idempotente."""
    if id(motor) in _gate_instalado_en:
        return
    event.listen(motor, "before_cursor_execute", _hook_antes_de_ejecutar)
    _gate_instalado_en.add(id(motor))
