"""Rutas de la app, tanto en desarrollo como empaquetada con PyInstaller.

En desarrollo todo vive en la raiz del proyecto (el .env, logs/). Instalada, el programa
queda en una carpeta de solo lectura (Program Files) y lo que cambia -- configuracion,
logs, estado de licencia -- va a la carpeta DistribuidoraDJ dentro de ProgramData, que el instalador crea con
permiso de escritura para los usuarios.
"""

import os
import sys
from pathlib import Path

EMPAQUETADA = bool(getattr(sys, "frozen", False))
RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
# Logo e icono de la app (empaquetados como datos, ver packaging/DistribuidoraDJ.spec).
# Nombre del producto tal como lo ve el usuario (titulos de ventana, login, sidebar). Los
# nombres internos (carpeta ProgramData, servicio, registro) siguen siendo DistribuidoraDJ: no
# se renombran para no romper instalaciones existentes.
NOMBRE_APP = "Nexo ERP"
DIR_ASSETS = Path(__file__).resolve().parent / "assets"
ARCHIVO_LOGO = DIR_ASSETS / "logo.png"
ARCHIVO_ICONO = DIR_ASSETS / "icono.ico"

DIR_DATOS = (Path(os.getenv("PROGRAMDATA") or Path.home()) / "DistribuidoraDJ") if EMPAQUETADA else RAIZ_PROYECTO
DIR_LOGS = DIR_DATOS / "logs"
ARCHIVO_CONFIG = DIR_DATOS / "config.env"
