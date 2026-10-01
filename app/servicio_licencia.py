"""
Servicio de Windows del SERVIDOR: mantiene viva la licencia de TODA la red aunque nadie tenga
la app abierta. Cada pocos minutos valida contra el servidor de licencias, le informa las
estaciones registradas y guarda el token renovado en SQL Server, de donde lo leen las
estaciones. Si este servicio se detiene o la licencia se revoca, el token vence en <= 7 dias
y todas las PCs quedan en solo lectura.

Uso (en una consola de PowerShell **como Administrador**, desde la carpeta del proyecto):

    python -m app.servicio_licencia instalar     # instala (inicio automatico) y arranca
    python -m app.servicio_licencia estado
    python -m app.servicio_licencia detener
    python -m app.servicio_licencia iniciar
    python -m app.servicio_licencia desinstalar
    python -m app.servicio_licencia ciclo        # una pasada en la consola, sin servicio (diagnostico)

Requiere pywin32 y, la primera vez en un entorno virtual:  python -m pywin32_postinstall -install
"""

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

# pythonservice.exe carga este archivo por ruta, sin la raiz del proyecto en sys.path.
RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
if not getattr(sys, "frozen", False) and str(RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO))

from app import config  # noqa: E402
from app.rutas import DIR_DATOS  # noqa: E402
from app.services.licencia import (  # noqa: E402
    MODO_SERVIDOR,
    EstadoLicencia,
    LicenciaRedError,
    LicenciaService,
)

logger = logging.getLogger("servicio_licencia")

NOMBRE_SERVICIO = "DistribuidoraDJLicencia"
NOMBRE_VISIBLE = "Distribuidora DJ - Licencia"
DESCRIPCION = (
    "Mantiene validada la licencia de Distribuidora DJ para el servidor y todas sus estaciones. "
    "Si se detiene, las estaciones pasan a solo lectura al agotarse el periodo de gracia."
)
# Cada cuanto valida. La revocacion de una licencia llega a las estaciones en <= este intervalo
# (mas el refresco de ~30 s de su cache).
INTERVALO_SEG = max(60, int(os.getenv("LICENCIA_SERVICIO_INTERVALO_SEG", "600")))


def ciclo() -> EstadoLicencia | None:
    """Una pasada: renueva el token y reporta estaciones. Nunca lanza (el servicio no debe
    caerse por un fallo de red o de base de datos; reintenta en el siguiente ciclo)."""
    if not LicenciaService.habilitada():
        logger.info("Licenciamiento no habilitado (faltan LICENCIA_URL / LICENCIA_PUBLIC_KEY)")
        return None
    if config.MODO_INSTALACION != MODO_SERVIDOR:
        logger.warning("Este equipo no esta instalado como SERVIDOR; el servicio no hace nada")
        return None
    try:
        estado = LicenciaService.validar_en_linea()
    except LicenciaRedError as exc:
        logger.warning("Sin conexion con el servidor de licencias: %s", exc)
        return LicenciaService.estado_actual()
    except Exception:
        logger.exception("Fallo inesperado validando la licencia")
        return None
    logger.info("Licencia: %s (%s)", estado.estado, estado.mensaje)
    return estado


try:
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil

    _HAY_PYWIN32 = True
except ImportError:  # no-Windows o pywin32 sin instalar: el resto del modulo sigue sirviendo
    _HAY_PYWIN32 = False

if _HAY_PYWIN32:

    class ServicioLicencia(win32serviceutil.ServiceFramework):
        _svc_name_ = NOMBRE_SERVICIO
        _svc_display_name_ = NOMBRE_VISIBLE
        _svc_description_ = DESCRIPCION

        def __init__(self, args):
            super().__init__(args)
            self._detener = win32event.CreateEvent(None, 0, 0, None)

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self._detener)

        def SvcDoRun(self):
            # El SCM arranca los servicios con cwd=System32: se pasa a la carpeta de datos de la app.
            os.chdir(DIR_DATOS)
            from app.logging_config import setup_logging

            setup_logging()
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE, servicemanager.PYS_SERVICE_STARTED, (self._svc_name_, "")
            )
            logger.info("Servicio de licencia iniciado (intervalo %s s)", INTERVALO_SEG)
            while True:
                ciclo()
                if win32event.WaitForSingleObject(self._detener, INTERVALO_SEG * 1000) == win32event.WAIT_OBJECT_0:
                    break
            logger.info("Servicio de licencia detenido")


def _requiere_pywin32() -> None:
    if not _HAY_PYWIN32:
        sys.exit("Falta pywin32: pip install pywin32  (y luego: python -m pywin32_postinstall -install)")


def _sc(*args: str) -> None:
    subprocess.run(["sc.exe", *args], check=False)


def _instalar() -> None:
    _requiere_pywin32()
    win32serviceutil.HandleCommandLine(ServicioLicencia, argv=[sys.argv[0], "--startup", "auto", "install"])
    # Si el proceso se cae, Windows lo reinicia (a los 60 s, hasta 3 veces; el contador se limpia a las 24 h).
    _sc("failure", NOMBRE_SERVICIO, "reset=", "86400", "actions=", "restart/60000/restart/60000/restart/60000")
    win32serviceutil.StartService(NOMBRE_SERVICIO)
    print(f"Servicio '{NOMBRE_VISIBLE}' instalado e iniciado (inicio automatico).")


def main(argv: list[str]) -> None:
    orden = argv[1] if len(argv) > 1 else ""
    if orden == "ciclo":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        inicio = time.time()
        estado = ciclo()
        print(f"{estado.estado if estado else 'sin cambios'}  ({time.time() - inicio:.1f} s)")
        return
    if orden == "instalar":
        _instalar()
        return
    traduccion = {"iniciar": "start", "detener": "stop", "desinstalar": "remove", "estado": "query"}
    if orden in traduccion:
        _requiere_pywin32()
        if orden == "estado":
            _sc("query", NOMBRE_SERVICIO)
            return
        win32serviceutil.HandleCommandLine(ServicioLicencia, argv=[argv[0], traduccion[orden]])
        return
    sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
