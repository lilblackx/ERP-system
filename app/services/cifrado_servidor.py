"""Cifrado de la contrasena SMTP: la escribe cualquier estacion, solo el servidor la lee.

Esquema hibrido, porque una contrasena de aplicacion puede ser mas larga de lo que RSA admite
directo: se genera una clave AES-256-GCM al azar por cada contrasena, se cifra el texto con
ella, y esa clave AES se cifra con la llave PUBLICA RSA-2048 (OAEP/SHA-256) del servidor.
El resultado es `base64( rsa(clave_aes) [256 B] + nonce [12 B] + aes_gcm(texto) )`.

- La llave publica vive en la base (clave_cifrado_servidor, migrations/0089): la usa
  cualquier estacion al guardar la contrasena en Configuracion > Correo.
- La llave PRIVADA vive solo en un archivo del servidor, protegido con DPAPI de esa maquina
  (app/utils/dpapi.py): quien lea la base, o copie el archivo a otra PC, solo ve texto cifrado.
  En una estacion no existe ese archivo, asi que `descifrar` devuelve None y NUNCA puede
  enviar correo con esa cuenta (los correos los manda el servidor, ver cola_correos.py).
- Si el servidor se reinstala y pierde el archivo, `asegurar_clave` genera un par nuevo y la
  contrasena guardada deja de poder leerse: hay que escribirla otra vez (se avisa en el log).

Los tests redirigen el archivo con la variable de entorno CLAVE_SERVIDOR_RUTA (o monkeypatch
de `ruta_clave_privada`) para no tocar el del equipo.
"""

import base64
import logging
import os
import stat
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.orm import Session

from app import config
from app.db.models import ClaveCifradoServidor, ConfiguracionSmtp
from app.rutas import DIR_DATOS
from app.utils import dpapi

logger = logging.getLogger(__name__)

MODO_SERVIDOR = "SERVIDOR"
_TAMANO_RSA = 2048
_BYTES_RSA = _TAMANO_RSA // 8
_BYTES_NONCE = 12
_OAEP = padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)


class CifradoNoDisponibleError(Exception):
    """Todavia no hay llave del servidor: nadie la inicializo abriendo la app en el servidor."""


def ruta_clave_privada() -> Path:
    return Path(os.getenv("CLAVE_SERVIDOR_RUTA") or (DIR_DATOS / "clave_servidor.bin"))


def es_servidor() -> bool:
    return config.MODO_INSTALACION == MODO_SERVIDOR


# ── Llave privada (solo servidor) ──────────────────────────────────────────


def _cargar_privada() -> rsa.RSAPrivateKey | None:
    ruta = ruta_clave_privada()
    if not ruta.exists():
        return None
    try:
        pem = dpapi.desproteger(ruta.read_bytes())
        clave = serialization.load_pem_private_key(pem, password=None)
    except Exception:
        logger.exception("No se pudo leer la llave privada del servidor (%s)", ruta)
        return None
    return clave if isinstance(clave, rsa.RSAPrivateKey) else None


def _guardar_privada(clave: rsa.RSAPrivateKey) -> None:
    pem = clave.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    ruta = ruta_clave_privada()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(dpapi.proteger(pem))
    try:
        # Sin DPAPI (Linux/Mac) lo unico que protege el archivo son los permisos.
        os.chmod(ruta, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _pem_publica(clave: rsa.RSAPrivateKey | rsa.RSAPublicKey) -> str:
    publica = clave.public_key() if isinstance(clave, rsa.RSAPrivateKey) else clave
    return publica.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(
        "ascii"
    )


def _publica_en_base(session: Session) -> str | None:
    fila = session.get(ClaveCifradoServidor, 1)
    return fila.clave_publica if fila is not None else None


def hay_clave_privada() -> bool:
    return _cargar_privada() is not None


def asegurar_clave(session: Session) -> bool:
    """Deja lista la llave del servidor. Solo en el SERVIDOR (en una estacion no hace nada y
    devuelve False): crea el par si no existe, y si la base tiene una llave publica que ya no
    corresponde a la privada local (servidor reinstalado), genera un par nuevo -- la
    contrasena SMTP guardada con la llave vieja queda inservible y se borra para que la UI
    pida escribirla de nuevo. Devuelve True si la llave quedo operativa."""
    if not es_servidor():
        return False

    privada = _cargar_privada()
    publica_base = _publica_en_base(session)
    if privada is not None and publica_base is not None and publica_base.strip() == _pem_publica(privada).strip():
        return True

    reemplaza = publica_base is not None
    if privada is None:
        privada = rsa.generate_private_key(public_exponent=65537, key_size=_TAMANO_RSA)
        _guardar_privada(privada)
    pem = _pem_publica(privada)

    fila = session.get(ClaveCifradoServidor, 1)
    if fila is None:
        session.add(ClaveCifradoServidor(id=1, clave_publica=pem))
    else:
        fila.clave_publica = pem
    if reemplaza:
        smtp = session.query(ConfiguracionSmtp).order_by(ConfiguracionSmtp.id_config).first()
        if smtp is not None and smtp.password_cifrada:
            logger.warning(
                "La llave del servidor cambio: la contrasena SMTP guardada ya no se puede leer; hay que "
                "escribirla de nuevo en Configuracion > Correo."
            )
            smtp.password_cifrada = None
    session.commit()
    return True


# ── Cifrar (cualquier estacion) / descifrar (solo servidor) ─────────────────


def cifrar(session: Session, texto: str) -> str:
    """Cifra `texto` con la llave publica del servidor. Lanza CifradoNoDisponibleError si el
    servidor todavia no la creo (en el SERVIDOR se crea sola)."""
    if es_servidor():
        asegurar_clave(session)
    pem = _publica_en_base(session)
    if pem is None:
        raise CifradoNoDisponibleError(
            "El servidor todavía no preparó el cifrado de la contraseña. Abra la aplicación en el "
            "servidor una vez y vuelva a intentar."
        )
    publica = serialization.load_pem_public_key(pem.encode("ascii"))
    assert isinstance(publica, rsa.RSAPublicKey)
    clave_aes = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(_BYTES_NONCE)
    cifrado = AESGCM(clave_aes).encrypt(nonce, texto.encode("utf-8"), None)
    return base64.b64encode(publica.encrypt(clave_aes, _OAEP) + nonce + cifrado).decode("ascii")


def descifrar(token: str | None) -> str | None:
    """Descifra con la llave privada local. None si no hay token o si esta PC no tiene la
    llave (una estacion): quien llama lo trata como "contrasena no disponible"."""
    if not token:
        return None
    privada = _cargar_privada()
    if privada is None:
        return None
    try:
        crudo = base64.b64decode(token)
        clave_aes = privada.decrypt(crudo[:_BYTES_RSA], _OAEP)
        nonce = crudo[_BYTES_RSA : _BYTES_RSA + _BYTES_NONCE]
        return AESGCM(clave_aes).decrypt(nonce, crudo[_BYTES_RSA + _BYTES_NONCE :], None).decode("utf-8")
    except Exception:
        logger.exception("No se pudo descifrar la contrasena SMTP (llave distinta o dato corrupto)")
        return None
