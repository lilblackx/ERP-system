"""Cifrado local con DPAPI de Windows (alcance de MAQUINA).

Protege secretos que viven en un archivo de esta PC (contrasena de la base en el .env, llave
privada del servidor): lo descifra cualquier proceso/usuario de ESTA maquina -- el servicio de
Windows y el usuario interactivo -- pero copiar el archivo a otra PC no sirve. No protege de
alguien con sesion en la propia maquina; para eso no hay solucion sin pedir una clave al
arrancar.

En Linux/Mac (CI, desarrollo) DPAPI no existe: `proteger`/`desproteger` devuelven los bytes
tal cual y `DISPONIBLE` es False -- quien guarda el secreto debe, al menos, dejar el archivo
con permisos 0600 (ver cifrado_servidor.guardar_privada).

Sin dependencias de app.* a proposito: lo importan app/config.py (que corre antes que todo
lo demas) y los servicios.
"""

import ctypes
import sys

DISPONIBLE = sys.platform == "win32"

_CRYPTPROTECT_LOCAL_MACHINE = 0x4


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _llamar(datos: bytes, proteger: bool) -> bytes:
    buffer = ctypes.create_string_buffer(datos, len(datos))  # referencia viva hasta que DPAPI termine
    entrada = _Blob(len(datos), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    salida = _Blob()
    funcion = ctypes.windll.crypt32.CryptProtectData if proteger else ctypes.windll.crypt32.CryptUnprotectData  # type: ignore[attr-defined]
    # Misma aridad: (in, descripcion, entropia, reservado, prompt, flags, out).
    if not funcion(ctypes.byref(entrada), None, None, None, None, _CRYPTPROTECT_LOCAL_MACHINE, ctypes.byref(salida)):
        raise OSError("DPAPI fallo")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(salida.pbData, ctypes.c_void_p))  # type: ignore[attr-defined]


def proteger(datos: bytes) -> bytes:
    return _llamar(datos, True) if DISPONIBLE else datos


def desproteger(datos: bytes) -> bytes:
    return _llamar(datos, False) if DISPONIBLE else datos
