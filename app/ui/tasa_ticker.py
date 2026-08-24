"""
TasaTicker: franja superior de todo el shell con la tasa de cambio vigente
(BCV / paralelo). Se oculta sola si el usuario no tiene permiso sobre el
recurso "tasas" o si todavía no hay ninguna tasa registrada -- no es
información crítica para operar, así que un fallo aquí nunca debe interrumpir
el resto de la aplicación con un diálogo de error.
"""

import logging
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from app.db.models import Usuario
from app.services.tasas import TasaService
from app.ui.styles import (
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    COLOR_TOPBAR_BORDER,
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
        self.setStyleSheet(f"background-color: white; border-bottom: 1px solid {COLOR_TOPBAR_BORDER};")
        self._build_ui()

        self._timer_elapsed = QTimer(self)
        self._timer_elapsed.timeout.connect(self._actualizar_elapsed)
        self._timer_elapsed.start(60_000)

        QTimer.singleShot(100, self.cargar_tasa)

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(14)

        self.bloque_bcv, self.lbl_valor_bcv, self.lbl_delta_bcv = self._make_bloque("Tasa BCV")
        separador = QFrame()
        separador.setFrameShape(QFrame.Shape.VLine)
        separador.setStyleSheet(f"color: {COLOR_TOPBAR_BORDER};")
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
