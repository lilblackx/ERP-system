"""
Aviso al usuario cuando el modo solo lectura de la licencia le bloquea una escritura
(ver app/services/licencia.py::registrar_aviso_bloqueo). El hook de bloqueo puede
dispararse desde un hilo de fondo (QueryWorker), asi que se pasa por una señal de Qt para
mostrar el dialogo siempre en el hilo de la interfaz.
"""

import time

from PySide6.QtCore import QObject, Signal

from app.services.licencia import EstadoLicencia
from app.ui.message_box import MessageBox

# Un guardado puede disparar varias escrituras seguidas y los paneles muestran su propio
# error generico justo despues: se avisa una vez por intervalo, no una vez por sentencia.
INTERVALO_ENTRE_AVISOS_SEG = 30


class AvisoLicencia(QObject):
    _bloqueado = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ultimo_aviso = 0.0
        self._bloqueado.connect(self._mostrar)

    def notificar(self, estado: EstadoLicencia) -> None:
        self._bloqueado.emit(estado.mensaje)

    def _mostrar(self, mensaje: str) -> None:
        ahora = time.monotonic()
        if ahora - self._ultimo_aviso < INTERVALO_ENTRE_AVISOS_SEG:
            return
        self._ultimo_aviso = ahora
        MessageBox.warning(
            None,
            "Licencia",
            f"{mensaje}\n\nLa aplicación está en modo solo lectura: no se pueden registrar ni "
            "modificar datos. Gestione la licencia en Configuración > Licencia.",
        )
