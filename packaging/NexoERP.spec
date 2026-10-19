# -*- mode: python ; coding: utf-8 -*-
# Especificacion de PyInstaller. Genera UNA carpeta (onedir) con dos ejecutables que comparten
# las mismas librerias:
#   NexoERP.exe  la aplicacion (con ventana)
#   Nexo-Servicio.exe      servicio de Windows de licencia (solo en el servidor)
# Las utilidades del instalador (Nexo-Herramientas.exe) van aparte: ver Herramientas.spec.
# Construir con packaging\construir.ps1 (no llamar a pyinstaller a mano: antes hay que generar
# app/licencia_embebida.py).
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

RAIZ = Path(SPECPATH).parent

datos = [
    (str(RAIZ / "app" / "ui" / "web"), "app/ui/web"),  # Leaflet para el mapa
    (str(RAIZ / "app" / "assets"), "app/assets"),  # logo e icono de la app
    (str(RAIZ / "migrations"), "migrations"),  # migraciones SQL
    (str(RAIZ / "schema_sqlserver.sql"), "."),  # esquema base para instalar un servidor nuevo
]
datos += collect_data_files("qtawesome")  # fuentes de iconos

modulos_ocultos = (
    collect_submodules("app")  # servicios/paneles que se importan por nombre
    + collect_submodules("winrt")  # geolocalizacion nativa de Windows (importa dentro de una funcion)
    + ["pyodbc", "win32timezone"]
)

excluir = ["tkinter", "pytest", "PyQt5", "PyQt6", "matplotlib", "IPython", "pip", "setuptools"]


def analisis(script):
    return Analysis(
        [str(RAIZ / "packaging" / "entradas" / script)],
        pathex=[str(RAIZ)],
        datas=datos,
        hiddenimports=modulos_ocultos,
        excludes=excluir,
        noarchive=False,
    )


a_app = analisis("app_gui.py")
a_servicio = analisis("servicio.py")

MERGE(
    (a_app, "NexoERP", "NexoERP"),
    (a_servicio, "Nexo-Servicio", "Nexo-Servicio"),
)

exe_app = EXE(
    PYZ(a_app.pure),
    a_app.scripts,
    [],
    exclude_binaries=True,
    name="NexoERP",
    console=False,
    icon=str(RAIZ / "app" / "assets" / "icono.ico"),
)
exe_servicio = EXE(
    PYZ(a_servicio.pure),
    a_servicio.scripts,
    [],
    exclude_binaries=True,
    name="Nexo-Servicio",
    console=True,  # consola: permite `Nexo-Servicio.exe debug`; como servicio no se muestra
)
COLLECT(
    exe_app,
    a_app.binaries,
    a_app.datas,
    exe_servicio,
    a_servicio.binaries,
    a_servicio.datas,
    name="NexoERP",
)
