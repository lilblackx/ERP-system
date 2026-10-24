"""Animaciones de la interfaz: un solo lugar para las duraciones, el interruptor general y los efectos.

Reglas (para que la app no se sienta lenta):
  - Duraciones de 100 a 220 ms con curva OutCubic; nada que dure mas.
  - Solo se anima opacidad, posicion o un fondo que se superpone: nunca la geometria de un widget
    pesado ni QGraphicsEffect (obliga a pintar el widget entero fuera de pantalla en cada cuadro
    y rompe el mapa web).
  - Una animacion a la vez por zona, y ninguna infinita fuera de la barra de carga.
  - Todo se apaga con `animaciones_activas() == False`: el efecto se omite y el estado final se
    aplica de inmediato, asi que ningun flujo depende de que una animacion termine.

El interruptor se apaga solo en una sesion de Escritorio remoto (RDP), donde las animaciones se
ven entrecortadas; con la variable de entorno NEXO_SIN_ANIMACIONES=1; con la preferencia "Reducir
animaciones" (Configuracion > Apariencia), que se guarda por equipo; y en los tests (conftest).
"""

import json
import logging
import os
import sys
import weakref
from collections.abc import Callable
from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QTableWidget, QWidget

from app.rutas import DIR_DATOS

logger = logging.getLogger(__name__)

DURACION_MICRO = 100
DURACION_CORTA = 150
DURACION_MEDIA = 220

ARCHIVO_PREFERENCIAS = DIR_DATOS / "preferencias_ui.json"

_forzado: bool | None = None
_sesion_remota_cache: bool | None = None
_reducir_cache: bool | None = None


# ── Interruptor general ─────────────────────────────────────────────────────


def forzar(activas: bool | None) -> None:
    """Fija el interruptor a mano (tests); None vuelve al calculo normal."""
    global _forzado
    _forzado = activas


def sesion_remota() -> bool:
    """True si la app corre dentro de una sesion de Escritorio remoto de Windows."""
    global _sesion_remota_cache
    if _sesion_remota_cache is None:
        remota = False
        if sys.platform == "win32":
            try:
                import ctypes

                remota = bool(ctypes.windll.user32.GetSystemMetrics(0x1000))  # SM_REMOTESESSION
            except Exception:
                logger.debug("No se pudo consultar si la sesion es remota", exc_info=True)
        _sesion_remota_cache = remota
    return _sesion_remota_cache


def _leer_preferencias(archivo: Path) -> dict:
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        logger.warning("No se pudo leer %s; se usan las preferencias por defecto", archivo, exc_info=True)
        return {}
    return datos if isinstance(datos, dict) else {}


def reducir_animaciones() -> bool:
    """Preferencia "Reducir animaciones" de este equipo."""
    global _reducir_cache
    if _reducir_cache is None:
        _reducir_cache = bool(_leer_preferencias(ARCHIVO_PREFERENCIAS).get("reducir_animaciones", False))
    return _reducir_cache


def establecer_reducir_animaciones(valor: bool, archivo: Path | None = None) -> None:
    """Guarda la preferencia. Si no se puede escribir el archivo, vale solo en esta sesion."""
    global _reducir_cache
    archivo = archivo or ARCHIVO_PREFERENCIAS
    _reducir_cache = bool(valor)
    datos = _leer_preferencias(archivo)
    datos["reducir_animaciones"] = bool(valor)
    try:
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_text(json.dumps(datos), encoding="utf-8")
    except OSError:
        logger.warning("No se pudo guardar %s", archivo, exc_info=True)


def animaciones_activas() -> bool:
    if _forzado is not None:
        return _forzado
    if os.environ.get("NEXO_SIN_ANIMACIONES") == "1":
        return False
    return not (reducir_animaciones() or sesion_remota())


# ── Primitivas ──────────────────────────────────────────────────────────────


def _con_objetivo(objetivo: QObject, accion: Callable[..., None]) -> Callable[..., None]:
    """Callback para una señal de una animacion hija de `objetivo`: llama `accion(objetivo, *argumentos)`.

    Un cierre que captura al propio objetivo lo mantiene vivo (referencia de Python) mientras exista la
    animacion. Si es la ultima referencia, al borrarse la animacion (DeleteWhenStopped) se suelta y destruye
    al objetivo a mitad de la destruccion de su propia hija: Qt aborta al azar. Aqui solo se guarda una
    referencia debil, y `accion` recibe el objetivo como parametro en vez de capturarlo."""
    referencia = weakref.ref(objetivo)

    def _llamar(*argumentos) -> None:
        destino = referencia()
        if destino is not None:
            accion(destino, *argumentos)

    return _llamar


def animar_propiedad(
    objetivo: QObject,
    propiedad: bytes,
    desde,
    hasta,
    ms: int = DURACION_CORTA,
    curva: QEasingCurve.Type = QEasingCurve.Type.OutCubic,
    al_terminar: Callable[[], None] | None = None,
) -> QPropertyAnimation | None:
    """Anima una propiedad de Qt. Sin animaciones: aplica `hasta` de inmediato (y llama `al_terminar`)."""
    if not animaciones_activas():
        objetivo.setProperty(propiedad.decode(), hasta)
        if al_terminar is not None:
            al_terminar()
        return None
    animacion = QPropertyAnimation(objetivo, propiedad, objetivo)
    animacion.setDuration(ms)
    animacion.setStartValue(desde)
    animacion.setEndValue(hasta)
    animacion.setEasingCurve(curva)
    if al_terminar is not None:
        animacion.finished.connect(al_terminar)
    animacion.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    return animacion


def fundido_entrada(ventana: QWidget, ms: int = DURACION_MICRO) -> None:
    """Aparicion suave de una ventana con su opacidad nativa (barata en Windows)."""
    if not animaciones_activas():
        return
    ventana.setWindowOpacity(0.0)
    animar_propiedad(
        ventana,
        b"windowOpacity",
        0.0,
        1.0,
        ms,
        QEasingCurve.Type.OutQuad,
        al_terminar=_con_objetivo(ventana, lambda v: v.setWindowOpacity(1.0)),
    )


def sacudir(ventana: QWidget, amplitud: int = 8, ms: int = 280) -> None:
    """Sacudida horizontal corta ("no se pudo"): dos o tres oscilaciones que se amortiguan."""
    if not animaciones_activas() or ventana.property("_sacudiendo"):
        return
    origen = ventana.pos()
    ventana.setProperty("_sacudiendo", True)
    animacion = QPropertyAnimation(ventana, b"pos", ventana)
    animacion.setDuration(ms)
    for fraccion, factor in ((0.0, 0), (0.2, -1.0), (0.4, 0.8), (0.6, -0.5), (0.8, 0.25), (1.0, 0)):
        animacion.setKeyValueAt(fraccion, QPoint(origen.x() + int(amplitud * factor), origen.y()))

    def _terminar(v: QWidget) -> None:
        v.move(origen)
        v.setProperty("_sacudiendo", False)

    animacion.finished.connect(_con_objetivo(ventana, _terminar))
    animacion.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


def marcar_error(campo: QWidget, ms: int = 900) -> None:
    """Pone el campo en rojo un momento. Necesita en su QSS una regla `[error="true"]`."""
    campo.setProperty("error", "true")
    _repulir(campo)

    def _quitar() -> None:
        campo.setProperty("error", "false")
        _repulir(campo)

    from PySide6.QtCore import QTimer

    QTimer.singleShot(ms, _quitar)


def _repulir(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class _Destello(QWidget):
    """Capa translucida que se desvanece encima de un widget o de una zona de una tabla."""

    def __init__(self, padre: QWidget, rect: QRect, color: QColor, radio: int = 4):
        super().__init__(padre)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._color = QColor(color)
        self._radio = radio
        self.setGeometry(rect)

    def set_alfa(self, alfa: int) -> None:
        self._color.setAlpha(max(0, min(255, alfa)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (nombre impuesto por Qt)
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(self._color)
        pintor.drawRoundedRect(self.rect(), self._radio, self._radio)
        pintor.end()


def _desvanecer(capa: _Destello, ms: int, alfa_inicial: int) -> None:
    animacion = QVariantAnimation(capa)
    animacion.setDuration(ms)
    animacion.setStartValue(float(alfa_inicial))
    animacion.setEndValue(0.0)
    animacion.setEasingCurve(QEasingCurve.Type.OutQuad)
    animacion.valueChanged.connect(_con_objetivo(capa, lambda c, valor: c.set_alfa(int(valor))))
    animacion.finished.connect(capa.deleteLater)
    animacion.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)


def destello(widget: QWidget, color: str = "#22c55e", ms: int = 600, alfa: int = 90) -> None:
    """Resalta un widget con un color que se desvanece (confirma "esto cambio")."""
    if not animaciones_activas() or not widget.isVisible():
        return
    capa = _Destello(widget, widget.rect(), QColor(color))
    capa.set_alfa(alfa)
    capa.show()
    capa.raise_()
    _desvanecer(capa, ms, alfa)


def destello_fila(tabla: QTableWidget, fila: int, color: str = "#22c55e", ms: int = 700, alfa: int = 80) -> None:
    """Resalta una fila de la tabla (la capa vive en el viewport y no toca los items)."""
    if not animaciones_activas() or not tabla.isVisible() or not 0 <= fila < tabla.rowCount():
        return
    ultima = tabla.columnCount() - 1
    if ultima < 0:
        return
    rect = tabla.visualRect(tabla.model().index(fila, 0)).united(tabla.visualRect(tabla.model().index(fila, ultima)))
    if rect.isEmpty():
        return
    capa = _Destello(tabla.viewport(), rect, QColor(color), radio=0)
    capa.set_alfa(alfa)
    capa.show()
    capa.raise_()
    _desvanecer(capa, ms, alfa)


def contar(etiqueta: QLabel, destino: float, formatear: Callable[[float], str], ms: int = 500) -> None:
    """El numero de la etiqueta sube desde 0 hasta `destino`. Sin animaciones: lo muestra de una vez."""
    if not animaciones_activas() or destino == 0:
        etiqueta.setText(formatear(destino))
        return
    # El ancho final se reserva de entrada: sin esto la etiqueta crece con cada digito y empuja a sus vecinas.
    etiqueta.setMinimumWidth(etiqueta.fontMetrics().horizontalAdvance(formatear(destino)))
    animacion = QVariantAnimation(etiqueta)
    animacion.setDuration(ms)
    animacion.setStartValue(0.0)
    animacion.setEndValue(float(destino))
    animacion.setEasingCurve(QEasingCurve.Type.OutCubic)
    animacion.valueChanged.connect(_con_objetivo(etiqueta, lambda e, valor: e.setText(formatear(float(valor)))))

    def _terminar(e: QLabel) -> None:
        e.setText(formatear(destino))
        e.setMinimumWidth(0)

    animacion.finished.connect(_con_objetivo(etiqueta, _terminar))
    animacion.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)


def rebote(widget: QWidget, crecimiento: int = 4, ms: int = 260) -> None:
    """Un solo latido (el widget crece y vuelve): avisa algo nuevo sin quedarse moviendo."""
    if not animaciones_activas() or not widget.isVisible():
        return
    base = widget.geometry()
    grande = base.adjusted(-crecimiento // 2, -crecimiento // 2, crecimiento // 2, crecimiento // 2)
    animacion = QPropertyAnimation(widget, b"geometry", widget)
    animacion.setDuration(ms)
    animacion.setKeyValueAt(0.0, base)
    animacion.setKeyValueAt(0.4, grande)
    animacion.setKeyValueAt(1.0, base)
    animacion.setEasingCurve(QEasingCurve.Type.OutCubic)
    animacion.finished.connect(_con_objetivo(widget, lambda w: w.setGeometry(base)))
    animacion.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


# ── Boton ocupado (icono giratorio) ─────────────────────────────────────────

_INTERVALO_GIRO_MS = 50
_PASO_GIRO_GRADOS = 20


def ocupar_boton(boton: QPushButton, color: str = "#64748b") -> None:
    """Deshabilita el boton y le pone un icono que gira mientras dura la accion larga.

    Si la accion corre en el hilo de la interfaz (un pago, imprimir) el icono no puede girar -- ese hilo esta
    ocupado --, pero el estado ocupado se pinta antes de empezar para que se vea que ya se pulso."""
    boton.setEnabled(False)
    try:
        if boton.property("_ocupado") or not animaciones_activas():
            return
        boton.setProperty("_ocupado", True)
        boton.setProperty("_icono_previo", boton.icon())
        giro = qta.Spin(boton, interval=_INTERVALO_GIRO_MS, step=_PASO_GIRO_GRADOS)
        boton._giro = giro  # referencia viva mientras gira
        boton.setIcon(qta.icon("fa5s.spinner", color=color, color_disabled=color, animation=giro))
    finally:
        boton.repaint()


def liberar_boton(boton: QPushButton) -> None:
    """Revierte `ocupar_boton`: icono original y boton habilitado."""
    giro = getattr(boton, "_giro", None)
    if giro is not None:
        giro.stop()
        boton._giro = None
    if boton.property("_ocupado"):
        boton.setProperty("_ocupado", False)
        previo = boton.property("_icono_previo")
        if previo is not None:
            boton.setIcon(previo)
    boton.setEnabled(True)


# ── Aparicion suave de los dialogos ─────────────────────────────────────────

# Dialogos que no deben animarse: el de factura es el mas denso de la app y ya tiene un truco de
# repintado para su primer pintado (ver factura_form_dialog.showEvent).
_DIALOGOS_SIN_FUNDIDO = {"FacturaFormDialog"}


def _tiene_web(ventana: QWidget) -> bool:
    """La ventana nativa de QWebEngineView no se pinta bien dentro de una ventana con opacidad."""
    return any("WebEngine" in hijo.metaObject().className() for hijo in ventana.findChildren(QWidget))


class FiltroFundidoDialogos(QObject):
    """Filtro de eventos de la aplicacion: cada QDialog que se abre aparece con un fundido corto."""

    def eventFilter(self, objeto, evento) -> bool:  # noqa: N802 (nombre impuesto por Qt)
        if (
            evento.type() == QEvent.Type.Show
            and isinstance(objeto, QDialog)
            and objeto.isWindow()
            and not objeto.property("sin_fundido")
            and type(objeto).__name__ not in _DIALOGOS_SIN_FUNDIDO
            and animaciones_activas()
            and not objeto.isMaximized()
            and not _tiene_web(objeto)
        ):
            fundido_entrada(objeto)
        return False
