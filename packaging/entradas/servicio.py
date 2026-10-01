"""Punto de entrada de DJ-Servicio.exe: el servicio de Windows de licencia (solo en el servidor).

Sin argumentos, lo arranca el Administrador de servicios de Windows (SCM). Con argumentos
(`debug`, `ciclo`) sirve para diagnosticar desde una consola. El instalador lo registra con
`sc.exe create ... binPath= "...\\DJ-Servicio.exe"` en vez de `pywin32 install`: asi el
registro no depende de pythonservice.exe, que no existe en una app empaquetada.
"""

import multiprocessing
import sys

import servicemanager
import win32serviceutil

from app.servicio_licencia import ServicioLicencia
from app.servicio_licencia import main as cli

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(ServicioLicencia)
        servicemanager.StartServiceCtrlDispatcher()
    elif sys.argv[1] == "debug":
        # Corre el servicio en primer plano (Ctrl+C para salir), sin instalarlo ni ser administrador.
        win32serviceutil.HandleCommandLine(ServicioLicencia, argv=[sys.argv[0], "debug"])
    else:
        cli(sys.argv)
