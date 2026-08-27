"""
TasaTicker: franja superior de todo el shell con la tasa de cambio vigente
(BCV / paralelo). Se oculta sola si el usuario no tiene permiso sobre el
recurso "tasas" o si todavía no hay ninguna tasa registrada -- no es
información crítica para operar, así que un fallo aquí nunca debe interrumpir
el resto de la aplicación con un diálogo de error.
"""

import logging
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from app.db.models import Usuario
from app.services.tasas import TasaService
from app.ui.styles import (
    COLOR_BORDER,
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
)
from app.ui.workers import QueryWorker

logger = logging.getLogger(__name__)


def _tarea_tasa_actual(session, id_usuario):
    return TasaService.obtener_tasa_actual(session, id_usuario=id_usuario)


def _formato_hace(minutos: int) -> str:
    if minutos < 1:
        return "Actualizado justo ahora"
    if minutos < 60:
        return f"Actualizado hace {minutos} min"
    horas = minutos // 60
    return f"Actualizado hace {horas} h"


class TasaTicker(QWidget):
    """Franja de tasas de cambio (Bs.), visible arriba de la sidebar y el contenido."""

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self._fecha_tasa = None
        self.setFixedHeight(38)
        # QSS CON selector de objectName, no una regla suelta -- mismo patron que
        # TopBar/TOPBAR_QSS (`QWidget#TopBar {...}`, app/ui/styles.py), la otra barra fija
        # del shell, que siempre se vio bien. Una regla sin selector
        # (`"background-color: white; border-bottom: ..."`) NO se aplica al widget: Qt la
        # trata como heredable y la pasa a todos los hijos, asi que cada bloque de texto
        # dibujaba su propio borde inferior y la linea aparecia SOLO debajo de ellos, con
        # huecos en el espacio vacio del medio -- la franja nunca pinto su propio borde
        # continuo (reportado por el usuario, 2026-08-27: "no se ve completa"; cambiar
        # color/grosor antes solo hacia mas notorios esos fragmentos). Ese mismo cascade
        # ademas le imponia `background-color: white` al separador vertical, que peleaba
        # contra su propio color de fondo.
        # WA_StyledBackground: un QWidget "pelado" (no QFrame/QLabel) no dibuja el
        # background/border de su QSS por si solo -- su paintEvent por defecto no llama al
        # estilo, asi que con el selector ya puesto la regla existia pero no se pintaba
        # (sintoma: se dejaron de ver los fragmentos heredados por los hijos, pero la
        # linea desaparecio del todo). Este atributo es lo que hace que el widget se pinte
        # a si mismo con el QSS.
        self.setObjectName("TasaTicker")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QWidget#TasaTicker {{ background-color: white; border-bottom: 1px solid {COLOR_BORDER}; }}"
        )
        self._build_ui()

        self._timer_elapsed = QTimer(self)
        self._timer_elapsed.timeout.connect(self._actualizar_elapsed)
        self._timer_elapsed.start(60_000)

        # A diferencia de los paneles del QStackedWidget, este widget nunca se
        # oculta/muestra al navegar (vive fuera del stack, siempre visible), asi
        # que un hook de showEvent no serviria -- se refresca con timer propio.
        self._timer_refresh = QTimer(self)
        self._timer_refresh.timeout.connect(self.cargar_tasa)
        self._timer_refresh.start(300_000)

        QTimer.singleShot(100, self.cargar_tasa)

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(14)

        self.bloque_bcv, self.lbl_valor_bcv, self.lbl_delta_bcv = self._make_bloque("Tasa BCV")
        # QLabel con background-color, no QFrame: QFrame.Shape.VLine con "color:" en QSS
        # no pinta nada (ver GUIA_ESTILO_UI.md 8.8). 1px con COLOR_BORDER, igual que la
        # linea inferior de la franja -- antes hizo falta subirlo a 2px oscuro para que se
        # notara, pero eso compensaba el bug real de arriba (el QSS sin selector le metia
        # `background-color: white` a este mismo hijo); resuelto ese cascade, el tono
        # estandar de bordes de la app alcanza.
        separador = QLabel()
        separador.setFixedWidth(1)
        separador.setFixedHeight(20)
        separador.setStyleSheet(f"background-color: {COLOR_BORDER};")
        self.bloque_paralelo, self.lbl_valor_paralelo, self.lbl_delta_paralelo = self._make_bloque("Dólar paralelo")

        self.lbl_actualizado = QLabel("")
        self.lbl_actualizado.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_MUTED}; background: transparent;")

        layout.addWidget(self.bloque_bcv)
        layout.addWidget(separador)
        layout.addWidget(self.bloque_paralelo)
        layout.addStretch()
        layout.addWidget(self.lbl_actualizado)

        self.setVisible(False)

    def _make_bloque(self, etiqueta: str) -> tuple[QWidget, QLabel, QLabel]:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        lbl_etiqueta = QLabel(etiqueta)
        lbl_etiqueta.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED}; background: transparent;")

        lbl_valor = QLabel("—")
        lbl_valor.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {COLOR_TEXT_DARK}; background: transparent;"
        )

        lbl_delta = QLabel("")
        lbl_delta.setStyleSheet(
            f"font-size: 11px; font-weight: bold; color: {COLOR_TEXT_MUTED}; background: transparent;"
        )

        h.addWidget(lbl_etiqueta)
        h.addWidget(lbl_valor)
        h.addWidget(lbl_delta)
        return w, lbl_valor, lbl_delta

    # ── Carga de datos ────────────────────────────────────────────────────

    def cargar_tasa(self) -> None:
        # El timer periodico (_timer_refresh) puede disparar esto antes de que
        # una carga anterior termine -- reasignar self._worker a un QThread nuevo
        # mientras el viejo sigue corriendo lo destruye a mitad de ejecucion y Qt
        # aborta el proceso ("QThread: Destroyed while thread is still running").
        if getattr(self, "_worker", None) is not None and self._worker.isRunning():
            return
        self._worker = QueryWorker(self.session_factory, _tarea_tasa_actual, id_usuario=self.usuario.id_usuario)
        self._worker.resultado.connect(self._mostrar_tasa)
        self._worker.error.connect(self._ocultar_por_error)
        self._worker.start()

    def _mostrar_tasa(self, datos: dict | None) -> None:
        if datos is None:
            self.setVisible(False)
            return

        self.lbl_valor_bcv.setText(f"Bs. {float(datos['tasa_bcv']):,.2f}")
        self._set_delta(self.lbl_delta_bcv, datos.get("porcentaje_vs_ayer_bcv"))

        if datos.get("tasa_paralelo") is not None:
            self.bloque_paralelo.setVisible(True)
            self.lbl_valor_paralelo.setText(f"Bs. {float(datos['tasa_paralelo']):,.2f}")
            self._set_delta(self.lbl_delta_paralelo, datos.get("porcentaje_vs_ayer_paralelo"))
        else:
            self.bloque_paralelo.setVisible(False)

        self._fecha_tasa = datos["fecha_tasa"]
        self._actualizar_elapsed()
        self.setVisible(True)
        # Mismo artefacto de primer pintado que en dialogos (ver GUIA_ESTILO_UI.md 8.1):
        # a diferencia de un QDialog, este widget nunca pasa por un showEvent propio de
        # navegacion (vive fuera del QStackedWidget, se crea una sola vez) -- este es el
        # unico momento en que pasa de oculto/sin datos a visible con contenido real, asi
        # que es el punto equivalente para forzar el repintado si DWM dejo el primer
        # pintado a medias (reportado por el usuario: el border-bottom de la franja no se
        # veia continuo en todo el ancho, 2026-08-27).
        QTimer.singleShot(0, self.update)

    def _set_delta(self, lbl: QLabel, porcentaje: float | None) -> None:
        if porcentaje is None:
            lbl.setText("")
            return
        if porcentaje > 0:
            color, icono = COLOR_SUCCESS, "▲"
        elif porcentaje < 0:
            color, icono = COLOR_DANGER, "▼"
        else:
            color, icono = COLOR_TEXT_MUTED, ""
        lbl.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {color}; background: transparent;")
        lbl.setText(f"{icono} {abs(porcentaje):.1f}%".strip())

    def _actualizar_elapsed(self) -> None:
        if self._fecha_tasa is None:
            return
        minutos = int((datetime.now() - self._fecha_tasa).total_seconds() // 60)
        self.lbl_actualizado.setText(_formato_hace(max(minutos, 0)))

    def _ocultar_por_error(self, mensaje: str) -> None:
        # No es informacion critica para operar (ej. usuario sin permiso "tasas"):
        # se oculta la franja en silencio en vez de interrumpir con un dialogo.
        logger.info("Franja de tasas oculta: %s", mensaje)
        self.setVisible(False)
