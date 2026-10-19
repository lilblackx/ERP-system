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
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


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

    def emitir_progreso(self, valor: int) -> None:
        """Callback que `tarea` puede invocar para reportar avance (0-100)."""
        self.progreso.emit(valor)

    def run(self) -> None:
        session = self._session_factory()
        try:
            resultado = self._tarea(session, *self._args, **self._kwargs)
        except Exception as exc:
            nombre_tarea = getattr(self._tarea, "__name__", repr(self._tarea))
            logger.exception("Fallo la tarea en segundo plano '%s'", nombre_tarea)
            self.error.emit(str(exc))
        else:
            self.resultado.emit(resultado)
        finally:
            session.close()
