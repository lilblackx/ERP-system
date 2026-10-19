"""Panel desplegable de la campana de notificaciones (reemplaza al QMenu: un menu no admite
filas de dos lineas, estado leido/no leido ni un encabezado con acciones).

Es un popup (Qt.Popup): se cierra solo al hacer click fuera o con Esc. No consulta ni guarda
nada: recibe las filas ya calculadas por TopBar y avisa por señales lo que el usuario hace."""

import qtawesome as qta
from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services.notificaciones import SEVERIDAD_ALTA, SEVERIDAD_MEDIA, Notificacion
from app.ui.styles import (
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_INFO_BG,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_TEXT_DARK,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MUTED,
    COLOR_TOPBAR_BORDER,
    COLOR_WARNING,
    aplicar_sombra,
)

ANCHO_PANEL = 380
ALTO_MAX_LISTA = 330
MARGEN_SOMBRA = 14


def color_severidad(severidad: str) -> str:
    if severidad == SEVERIDAD_ALTA:
        return COLOR_DANGER
    if severidad == SEVERIDAD_MEDIA:
        return COLOR_WARNING
    return COLOR_PRIMARY


class _FilaNotificacion(QFrame):
    """Una alerta: punto de severidad, titulo, detalle y flecha. Las no leidas llevan fondo
    azul claro y titulo en negrita; las leidas se atenuan pero siguen siendo clickeables.

    Es un QFrame y no un QPushButton: el alto de un boton sale de su texto, no del layout
    interno, y la fila quedaba colapsada."""

    clicked = Signal()

    def __init__(self, notificacion: Notificacion, leida: bool, parent=None):
        super().__init__(parent)
        self.notificacion = notificacion
        self.leida = leida
        self.setObjectName("FilaNotificacion")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        fondo = "transparent" if leida else COLOR_INFO_BG
        self.setStyleSheet(f"""
            QFrame#FilaNotificacion {{
                background-color: {fondo};
                border: none;
                border-radius: 8px;
            }}
            QFrame#FilaNotificacion:hover {{
                background-color: {COLOR_CONTENT_BG};
            }}
        """)

        fila = QHBoxLayout(self)
        fila.setContentsMargins(12, 10, 12, 10)
        fila.setSpacing(12)

        color = COLOR_TEXT_LIGHT if leida else color_severidad(notificacion.severidad)
        punto = QLabel()
        punto.setPixmap(qta.icon("fa5s.circle", color=color).pixmap(QSize(10, 10)))
        punto.setFixedSize(10, 10)
        punto.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        punto.setStyleSheet("background: transparent;")
        fila.addWidget(punto, alignment=Qt.AlignmentFlag.AlignTop)

        textos = QVBoxLayout()
        textos.setSpacing(2)
        titulo = QLabel(notificacion.titulo)
        peso, color_titulo = ("normal", COLOR_TEXT_MUTED) if leida else ("bold", COLOR_TEXT_DARK)
        titulo.setStyleSheet(f"font-size: 13px; font-weight: {peso}; color: {color_titulo}; background: transparent;")
        detalle = QLabel(notificacion.detalle)
        detalle.setWordWrap(True)
        detalle.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED}; background: transparent;")
        for etiqueta in (titulo, detalle):
            etiqueta.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        textos.addWidget(titulo)
        textos.addWidget(detalle)
        fila.addLayout(textos, stretch=1)

        flecha = QLabel()
        flecha.setPixmap(qta.icon("fa5s.chevron-right", color=COLOR_TEXT_LIGHT).pixmap(QSize(10, 10)))
        flecha.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        flecha.setStyleSheet("background: transparent;")
        fila.addWidget(flecha, alignment=Qt.AlignmentFlag.AlignVCenter)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (override de Qt)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class PanelNotificaciones(QFrame):
    """Señales:
    notificacion_elegida(Notificacion): click en una fila (TopBar la marca leida y navega).
    marcar_todas_leidas(): click en "Marcar todas como leídas"."""

    notificacion_elegida = Signal(object)
    marcar_todas_leidas = Signal()

    def __init__(self, parent=None):
        # NoDropShadowWindowHint: Windows le dibuja a todo Popup una sombra rectangular propia que,
        # con fondo translucido, se ve como un borde negro duro fuera de la tarjeta redondeada. La
        # sombra suave la pone aplicar_sombra() sobre la tarjeta.
        super().__init__(
            parent,
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(ANCHO_PANEL + 2 * MARGEN_SOMBRA)

        externo = QVBoxLayout(self)
        externo.setContentsMargins(MARGEN_SOMBRA, MARGEN_SOMBRA - 6, MARGEN_SOMBRA, MARGEN_SOMBRA + 2)

        self._tarjeta = QFrame()
        self._tarjeta.setObjectName("PanelNotificaciones")
        self._tarjeta.setStyleSheet(f"""
            QFrame#PanelNotificaciones {{
                background-color: {COLOR_CARD_BG};
                border: 1px solid {COLOR_BORDER};
                border-radius: 12px;
            }}
        """)
        aplicar_sombra(self._tarjeta, blur=24, y_offset=6, alpha=45)
        externo.addWidget(self._tarjeta)

        self._layout = QVBoxLayout(self._tarjeta)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(4)

        self._build_encabezado()

        self._cuerpo = QWidget()
        self._cuerpo.setStyleSheet("background: transparent;")
        self._layout_cuerpo = QVBoxLayout(self._cuerpo)
        self._layout_cuerpo.setContentsMargins(0, 0, 0, 0)
        self._layout_cuerpo.setSpacing(2)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._scroll.setWidget(self._cuerpo)
        self._layout.addWidget(self._scroll)

        self.filas: list[_FilaNotificacion] = []

    def _build_encabezado(self) -> None:
        encabezado = QWidget()
        encabezado.setStyleSheet("background: transparent;")
        fila = QHBoxLayout(encabezado)
        fila.setContentsMargins(8, 4, 4, 4)
        fila.setSpacing(8)

        titulo = QLabel("Notificaciones")
        titulo.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        self.lbl_sin_leer = QLabel()
        self.lbl_sin_leer.setStyleSheet(
            f"font-size: 11px; font-weight: bold; color: {COLOR_PRIMARY};"
            f" background-color: {COLOR_INFO_BG}; border-radius: 9px; padding: 2px 8px;"
        )
        self.btn_marcar_todas = QPushButton("Marcar todas como leídas")
        self.btn_marcar_todas.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_marcar_todas.setFlat(True)
        self.btn_marcar_todas.setStyleSheet(f"""
            QPushButton {{
                color: {COLOR_PRIMARY}; font-size: 12px; font-weight: 600;
                border: none; background: transparent; padding: 4px 6px; border-radius: 6px;
            }}
            QPushButton:hover {{ background-color: {COLOR_INFO_BG}; }}
            QPushButton:disabled {{ color: {COLOR_TEXT_LIGHT}; }}
        """)
        self.btn_marcar_todas.clicked.connect(self.marcar_todas_leidas.emit)

        fila.addWidget(titulo)
        fila.addWidget(self.lbl_sin_leer)
        fila.addStretch()
        fila.addWidget(self.btn_marcar_todas)
        self._layout.addWidget(encabezado)

        separador = QFrame()
        separador.setFixedHeight(1)
        separador.setStyleSheet(f"background-color: {COLOR_TOPBAR_BORDER}; border: none;")
        self._layout.addWidget(separador)

    def set_filas(self, filas: list[tuple[Notificacion, bool]]) -> None:
        """`filas` = [(notificacion, leida), ...] en el orden a mostrar."""
        while self._layout_cuerpo.count():
            item = self._layout_cuerpo.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.filas = []

        sin_leer = sum(1 for _, leida in filas if not leida)
        self.lbl_sin_leer.setText(f"{sin_leer} sin leer")
        self.lbl_sin_leer.setVisible(sin_leer > 0)
        self.btn_marcar_todas.setEnabled(sin_leer > 0)
        self.btn_marcar_todas.setVisible(bool(filas))

        if not filas:
            self._layout_cuerpo.addWidget(self._estado_vacio())
        for notificacion, leida in filas:
            fila = _FilaNotificacion(notificacion, leida)
            fila.clicked.connect(lambda _checked=False, n=notificacion: self.notificacion_elegida.emit(n))
            self._layout_cuerpo.addWidget(fila)
            self.filas.append(fila)
        self._layout_cuerpo.addStretch()
        self._ajustar_alto()

    def _estado_vacio(self) -> QWidget:
        caja = QWidget()
        caja.setStyleSheet("background: transparent;")
        v = QVBoxLayout(caja)
        v.setContentsMargins(0, 28, 0, 28)
        v.setSpacing(8)
        icono = QLabel()
        icono.setPixmap(qta.icon("fa5s.check-circle", color=COLOR_SUCCESS).pixmap(QSize(30, 30)))
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        texto = QLabel("No hay alertas por ahora")
        texto.setAlignment(Qt.AlignmentFlag.AlignCenter)
        texto.setStyleSheet(f"font-size: 13px; color: {COLOR_TEXT_MUTED};")
        v.addWidget(icono)
        v.addWidget(texto)
        return caja

    def _ajustar_alto(self) -> None:
        """Alto exacto del contenido hasta ALTO_MAX_LISTA; pasado ese tope, la lista hace scroll."""
        self._layout_cuerpo.activate()
        alto = min(self._layout_cuerpo.minimumSize().height(), ALTO_MAX_LISTA)
        self._scroll.setFixedHeight(max(alto, 1))
        self.adjustSize()

    def mostrar_bajo(self, boton: QWidget) -> None:
        """Abre el panel con su borde derecho alineado al del boton de la campana."""
        self.adjustSize()
        derecha = boton.mapToGlobal(QPoint(boton.width(), boton.height()))
        self.move(derecha.x() - self.width() + MARGEN_SOMBRA, derecha.y())
        self.show()
