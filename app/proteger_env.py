"""Protege con DPAPI (de ESTA PC) las contrasenas que viven en el archivo de configuracion.

Hoy DB_PASSWORD queda en texto plano en el .env (desarrollo) o config.env (instalada) de cada PC:
quien copie el archivo -- o lo lea desde otro usuario/programa -- tiene la clave de la base. Este
comando reemplaza `DB_PASSWORD=...` por `DB_PASSWORD_DPAPI=dpapi:...`, que SOLO descifra esta PC
(app/utils/dpapi.py); copiado a otra maquina no sirve. Igual con SMTP_PASSWORD.

    python -m app.proteger_env              # protege el .env / config.env de esta instalacion
    python -m app.proteger_env RUTA         # otro archivo
    python -m app.proteger_env --revertir   # vuelve a texto plano (p. ej. para docker compose en desarrollo)

Deja una copia `<archivo>.bak` antes de tocar nada. Solo Windows (en otros sistemas no hay DPAPI y
el comando no hace nada). `docker compose` lee DB_PASSWORD del .env: en una PC de desarrollo que use
Docker conviene dejarlo sin proteger.
"""

import shutil
import sys
from pathlib import Path

from app import config
from app.rutas import ARCHIVO_CONFIG, EMPAQUETADA, RAIZ_PROYECTO
from app.utils import dpapi

CLAVES = ("DB_PASSWORD", "SMTP_PASSWORD")
SUFIJO = "_DPAPI"


def _separar(linea: str) -> tuple[str, str] | None:
    if "=" not in linea or linea.lstrip().startswith("#"):
        return None
    nombre, _, valor = linea.partition("=")
    return nombre.strip(), valor


def transformar(texto: str, revertir: bool = False) -> tuple[str, list[str]]:
    """Devuelve (texto nuevo, nombres de las variables que cambiaron). Pura: no toca disco."""
    cambiadas: list[str] = []
    lineas = []
    for linea in texto.splitlines():
        par = _separar(linea)
        if par is None:
            lineas.append(linea)
            continue
        nombre, valor = par
        for clave in CLAVES:
            if not revertir and nombre == clave and valor and not valor.startswith(config.PREFIJO_DPAPI):
                lineas.append(f"{clave}{SUFIJO}={config.proteger_clave(valor)}")
                cambiadas.append(clave)
                break
            if revertir and nombre == f"{clave}{SUFIJO}":
                clara = config.desproteger_clave(valor)
                if not clara:
                    raise ValueError(f"No se pudo descifrar {nombre} en esta PC (esta protegida para otra).")
                lineas.append(f"{clave}={clara}")
                cambiadas.append(clave)
                break
        else:
            lineas.append(linea)
    return "\n".join(lineas) + ("\n" if texto.endswith("\n") else ""), cambiadas


def procesar_archivo(ruta: Path, revertir: bool = False) -> list[str]:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe {ruta}")
    nuevo, cambiadas = transformar(ruta.read_text(encoding="utf-8"), revertir=revertir)
    if cambiadas:
        shutil.copy2(ruta, ruta.with_name(ruta.name + ".bak"))
        ruta.write_text(nuevo, encoding="utf-8")
    return cambiadas


def main(argv: list[str]) -> int:
    revertir = "--revertir" in argv
    rutas = [a for a in argv[1:] if not a.startswith("--")]
    ruta = Path(rutas[0]) if rutas else (ARCHIVO_CONFIG if EMPAQUETADA else RAIZ_PROYECTO / ".env")
    if not dpapi.DISPONIBLE:
        print("DPAPI solo existe en Windows: no se hizo nada.")
        return 1
    try:
        cambiadas = procesar_archivo(ruta, revertir=revertir)
    except (FileNotFoundError, ValueError) as exc:
        print(exc)
        return 1
    if not cambiadas:
        print(f"{ruta}: nada que {'revertir' if revertir else 'proteger'}.")
        return 0
    accion = "vueltas a texto plano" if revertir else "protegidas con DPAPI de esta PC"
    print(f"{ruta}: {', '.join(cambiadas)} {accion}. Copia anterior en {ruta.name}.bak (borrela cuando verifique).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
