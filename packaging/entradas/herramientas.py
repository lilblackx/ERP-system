"""Punto de entrada de DJ-Herramientas.exe: lo que el instalador ejecuta contra SQL Server
(ver app/instalacion.py). Es una aplicacion de consola; el instalador la corre oculta."""

import multiprocessing
import sys

from app.instalacion import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
