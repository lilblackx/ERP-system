"""Punto de entrada de DistribuidoraDJ.exe (la aplicacion con ventana)."""

import multiprocessing

from app.main import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
