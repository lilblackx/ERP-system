# -*- mode: python ; coding: utf-8 -*-
# DJ-Herramientas.exe: ejecutable unico (onefile) y liviano -- sin Qt -- con las utilidades que el
# instalador corre contra SQL Server (app/instalacion.py). Va aparte de la aplicacion porque el
# instalador lo necesita ANTES de copiar nada (probar la conexion en las paginas del asistente).
from pathlib import Path

RAIZ = Path(SPECPATH).parent

a = Analysis(
    [str(RAIZ / "packaging" / "entradas" / "herramientas.py")],
    pathex=[str(RAIZ)],
    datas=[
        (str(RAIZ / "migrations"), "migrations"),
        (str(RAIZ / "schema_sqlserver.sql"), "."),
    ],
    hiddenimports=["pyodbc"],
    excludes=["PySide6", "shiboken6", "qtawesome", "tkinter", "pytest", "matplotlib", "IPython", "reportlab", "openpyxl"],
)

exe = EXE(
    PYZ(a.pure),
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DJ-Herramientas",
    console=True,
    upx=False,
)
