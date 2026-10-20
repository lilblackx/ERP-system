"""Indicador de actividad en segundo plano: una barra fina que aparece solo si algo tarda.

`GestorActividad` cuenta los QueryWorker en marcha (ver workers.py); la barra (`BarraCarga`, en
MainWindow bajo la barra superior) espera un momento antes de mostrarse, asi que las consultas
rapidas no la hacen parpadear. Solo corre una animacion mientras esta visible; con las animaciones
apagadas queda una barra fija.

No ayuda con las cargas que todavia corren en el hilo de la interfaz: ese hilo esta bloqueado y
tampoco puede pintar la barra. Esas hay que pasarlas a QueryWorker.
"""

from PySide6.QtCore import QEasingCurve, QObject, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from app.ui.animaciones import animaciones_activas
from app.ui.styles import COLOR_PRIMARY

ALTO_BARRA = 3
RETRASO_MOSTRAR_MS = 250
CICLO_MS = 1100
FRACCION_SEGMENTO = 0.3


class GestorActividad(QObject):
    """Cuenta de tareas en segundo plano; emite `actividad(True/False)` al pasar de 0 a 1 y de 1 a 0."""

    actividad = Signal(bool)

    _instancia: "GestorActividad | None" = None

    def __init__(self) -> None:
        super().__init__()
        self._cuenta = 0

    @classmethod
    def instancia(cls) -> "GestorActividad":
        if cls._instancia is None:
            cls._instancia = cls()
        return cls._instancia

    @property
    def hay_actividad(self) -> bool:
        return self._cuenta > 0

    def iniciar(self) -> None:
        self._cuenta += 1
        if self._cuenta == 1:
            self.actividad.emit(True)

    def terminar(self) -> None:
        if self._cuenta == 0:
            return
        self._cuenta -= 1
        if self._cuenta == 0:
            self.actividad.emit(False)


class BarraCarga(QWidget):
    def __init__(self, gestor: GestorActividad | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(ALTO_BARRA)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._activa = False
        self._posicion = 0.0

        self._retraso = QTimer(self)
        self._retraso.setSingleShot(True)
        self._retraso.setInterval(RETRASO_MOSTRAR_MS)
        self._retraso.timeout.connect(self._mostrar)

        self._animacion = QVariantAnimation(self)
        self._animacion.setStartValue(0.0)
        self._animacion.setEndValue(1.0)
        self._animacion.setDuration(CICLO_MS)
        self._animacion.setLoopCount(-1)
        self._animacion.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._animacion.valueChanged.connect(self._avanzar)

        gestor = gestor or GestorActividad.instancia()
        gestor.actividad.connect(self._on_actividad)
        if gestor.hay_actividad:
            self._on_actividad(True)

    @property
    def visible_ocupada(self) -> bool:
        return self._activa

    def _on_actividad(self, hay: bool) -> None:
        if hay:
            if not self._activa and not self._retraso.isActive():
                self._retraso.start()
        else:
            self._retraso.stop()
            self._activa = False
            self._animacion.stop()
            self.update()

    def _mostrar(self) -> None:
        self._activa = True
        if animaciones_activas():
            self._animacion.start()
        self.update()

    def _avanzar(self, valor) -> None:
        self._posicion = float(valor)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (nombre impuesto por Qt)
        if not self._activa:
            return
        pintor = QPainter(self)
        color = QColor(COLOR_PRIMARY)
        ancho = self.width()
        if self._animacion.state() != QVariantAnimation.State.Running:
            color.setAlpha(110)  # animaciones apagadas: barra fija, solo indica "trabajando"
            pintor.fillRect(QRectF(0, 0, ancho, self.height()), color)
        else:
            largo = ancho * FRACCION_SEGMENTO
            x = -largo + (ancho + largo) * self._posicion
            pintor.fillRect(QRectF(x, 0, largo, self.height()), color)
        pintor.end()
