"""Worker generico para ejecutar consultas de servicio fuera del hilo de GUI.

R-03: sin esto, cualquier consulta de agregacion sobre un rango de fechas (el
primer reporte) congela la ventana -- Windows la marca "No responde" porque
Qt no puede procesar el bucle de eventos mientras el hilo principal espera la
base de datos.

Las sesiones de SQLAlchemy no son thread-safe, asi que el worker abre su
propia sesion (via `session_factory`, normalmente `SessionLocal`) dentro del
hilo en el que corre -- nunca reutiliza una sesion creada en el hilo de GUI.

Uso tipico desde un panel:

    def _tarea(session):
        return ReportesService.aging_cxc(session, id_usuario=self.usuario.id_usuario)

    self._worker = QueryWorker(SessionLocal, _tarea)
    self._worker.resultado.connect(self._mostrar_resultado)
    self._worker.error.connect(self._mostrar_error)
    self._worker.start()

`self._worker` debe guardarse como atributo de instancia (ej. `self._worker`)
mientras corre -- si la referencia se pierde, Python puede recolectar el
objeto QThread a mitad de ejecucion.
"""

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)

# Una tarea que pasa de aqui sin terminar queda en el log: la barra de carga sigue encendida mientras corre, y sin este
# aviso no hay forma de saber cual tarea (una consulta bloqueada, la red caida) la mantiene asi.
SEGUNDOS_TAREA_LENTA = 30


class QueryWorker(QThread):
    """Ejecuta `tarea(session, *args, **kwargs)` en un hilo aparte.

    Señales:
        progreso(int): opcional -- `tarea` puede reportar avance conectando su
            primer parametro extra a `self.progreso.emit`, ver `emitir_progreso`.
        resultado(object): valor devuelto por `tarea`, emitido si no hubo excepcion.
        error(str): mensaje de la excepcion, emitido en vez de `resultado`.
    """

    progreso = Signal(int)
    resultado = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        session_factory: Callable[[], Any],
        tarea: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self._session_factory = session_factory
        self._tarea = tarea
        self._args = args
        self._kwargs = kwargs
        # Los refrescos automaticos y la busqueda mientras se escribe se marcan `silencioso = True`
        # antes de start(): no deben encender la barra de carga (ver app/ui/carga.py).
        self.silencioso = False
        self._contado = False
        self._candado_conteo = threading.Lock()

    def start(self, *args: Any, **kwargs: Any) -> None:
        # La cuenta de la barra se abre aqui y se cierra al final de run(), no con las señales
        # started/finished: esas llegan encoladas al propio worker, y si el panel lo reemplaza
        # (`self._worker = QueryWorker(...)`) entre que el hilo termina y que la señal se entrega,
        # Qt descarta la señal y la barra queda encendida para siempre.
        if not self.silencioso:
            from app.ui.carga import GestorActividad

            with self._candado_conteo:
                abrir = not self._contado
                self._contado = True
            if abrir:
                GestorActividad.instancia().iniciar()
        super().start(*args, **kwargs)

    def _cerrar_conteo(self) -> None:
        with self._candado_conteo:
            cerrar = self._contado
            self._contado = False
        if cerrar:
            from app.ui.carga import GestorActividad

            GestorActividad.instancia().terminar()

    def emitir_progreso(self, valor: int) -> None:
        """Callback que `tarea` puede invocar para reportar avance (0-100)."""
        self.progreso.emit(valor)

    def run(self) -> None:
        nombre_tarea = getattr(self._tarea, "__name__", repr(self._tarea))
        inicio = time.monotonic()
        vigilante = threading.Timer(
            SEGUNDOS_TAREA_LENTA,
            logger.warning,
            ("La tarea en segundo plano '%s' lleva mas de %d s sin terminar", nombre_tarea, SEGUNDOS_TAREA_LENTA),
        )
        vigilante.daemon = True
        vigilante.start()
        try:
            session = self._session_factory()
            try:
                resultado = self._tarea(session, *self._args, **self._kwargs)
            except Exception as exc:
                logger.exception("Fallo la tarea en segundo plano '%s'", nombre_tarea)
                self.error.emit(str(exc))
            else:
                self.resultado.emit(resultado)
            finally:
                session.close()
        finally:
            vigilante.cancel()
            duracion = time.monotonic() - inicio
            if duracion >= SEGUNDOS_TAREA_LENTA:
                logger.warning("La tarea en segundo plano '%s' termino tras %.0f s", nombre_tarea, duracion)
            self._cerrar_conteo()
