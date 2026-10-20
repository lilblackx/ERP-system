"""Aviso breve que no bloquea ("toast"): confirma que algo se hizo sin pedir un clic.

Se usa para las confirmaciones de exito (ver MessageBox.information). Los errores, advertencias y
preguntas siguen siendo dialogos modales: esos si piden atencion.

Es una ventana aparte, sin marco, que no toma el foco ni recibe el mouse (WindowTransparentForInput),
anclada a la esquina inferior derecha de la ventana principal: asi nunca tapa ni intercepta nada, se
ve incluso encima de un dialogo modal y sobrevive si el dialogo que la origino se cierra al instante.
Solo hay uno a la vez: uno nuevo reemplaza al anterior.
"""

import unicodedata

import qtawesome as qta
from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QSize, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.ui.animaciones import DURACION_CORTA, DURACION_MEDIA, animaciones_activas
from app.ui.styles import (
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MEDIUM,
    COLOR_WARNING,
    FONT_FAMILY,
    color_con_alpha,
)

MARGEN = 24
ANCHO_MINIMO = 260
ANCHO_MAXIMO = 400
DESPLAZAMIENTO_ENTRADA = 14
DURACION_BASE_MS = 2800
DURACION_MAXIMA_MS = 7000

_TIPOS = {
    "exito": ("fa5s.check-circle", COLOR_SUCCESS),
    "aviso": ("fa5s.exclamation-triangle", COLOR_WARNING),
    "error": ("fa5s.times-circle", COLOR_DANGER),
}


def _sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").lower()


# Titulos de MessageBox.information que confirman una operacion terminada (lo demas -- "Selección
# requerida", "Sin datos", "Nada que facturar"... -- pide que el usuario lo lea y sigue siendo modal).
_PALABRAS_DE_EXITO = (
    "exito",
    "exitosa",
    "completa",
    "registrad",
    "creada",
    "creado",
    "aplicad",
    "devuelt",
    "emitid",
    "guardad",
    "generado",
    "impresion enviada",
    "activada",
    "cerrad",
    "desbloqueado",
    "listo",
)
# Aunque el titulo suene a exito, estos deben leerse con calma o aparecen justo antes de cerrar la ventana.
_NO_SON_TOAST = ("sesion cerrada", "codigo enviado")
LARGO_MAXIMO_TOAST = 300


def es_confirmacion_de_exito(titulo: str, texto: str = "") -> bool:
    normal = _sin_acentos(titulo)
    if normal.startswith("sin ") or any(frase in normal for frase in _NO_SON_TOAST):
        return False
    if len(texto) > LARGO_MAXIMO_TOAST:
        return False
    return any(palabra in normal for palabra in _PALABRAS_DE_EXITO)


def _ventana_anfitriona(parent: QWidget | None) -> QWidget | None:
    """La ventana principal: sube por la cadena de padres hasta el widget sin padre."""
    ventana = parent.window() if parent is not None else None
    while ventana is not None and ventana.parentWidget() is not None:
        ventana = ventana.parentWidget().window()
    return ventana


class Toast(QWidget):
    _actual: "Toast | None" = None

    def __init__(self, anfitriona: QWidget | None, titulo: str, texto: str, tipo: str = "exito"):
        super().__init__(
            None,
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._anfitriona = anfitriona
        self._cerrando = False
        icono, color = _TIPOS.get(tipo, _TIPOS["exito"])

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        tarjeta = QFrame()
        tarjeta.setObjectName("ToastCard")
        tarjeta.setStyleSheet(
            f"""
            QFrame#ToastCard {{
                background-color: {COLOR_CARD_BG};
                border: 1px solid {COLOR_BORDER};
                border-left: 4px solid {color};
                border-radius: 8px;
            }}
            QLabel {{ background: transparent; border: none; font-family: '{FONT_FAMILY}', Arial, sans-serif; }}
            """
        )
        fila = QHBoxLayout(tarjeta)
        fila.setContentsMargins(14, 12, 18, 12)
        fila.setSpacing(12)

        lbl_icono = QLabel()
        lbl_icono.setPixmap(qta.icon(icono, color=color).pixmap(QSize(20, 20)))
        lbl_icono.setFixedSize(30, 30)
        lbl_icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_icono.setStyleSheet(f"background-color: {color_con_alpha(color, 26)}; border-radius: 15px;")
        fila.addWidget(lbl_icono, 0, Qt.AlignmentFlag.AlignTop)

        columna = QVBoxLayout()
        columna.setSpacing(2)
        self.lbl_titulo = QLabel(titulo)
        self.lbl_titulo.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        columna.addWidget(self.lbl_titulo)
        self.lbl_texto = QLabel(texto)
        self.lbl_texto.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MEDIUM};")
        self.lbl_texto.setWordWrap(True)
        self.lbl_texto.setVisible(bool(texto))
        columna.addWidget(self.lbl_texto)
        fila.addLayout(columna, 1)
        raiz.addWidget(tarjeta)

        # Ancho segun el contenido (con tope) y alto segun cuantas lineas ocupa el texto a ese ancho: sin esto
        # un texto que se parte en varias lineas (una ruta de archivo) quedaba recortado.
        ancho = max(ANCHO_MINIMO, min(ANCHO_MAXIMO, self.sizeHint().width()))
        self.setFixedWidth(ancho)
        self.setFixedHeight(raiz.totalHeightForWidth(ancho))

        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.timeout.connect(self._ocultar)
        self.duracion_ms = min(DURACION_MAXIMA_MS, DURACION_BASE_MS + 40 * max(0, len(texto) - 60))

    # ── API ──────────────────────────────────────────────────────────────

    @staticmethod
    def mostrar(parent: QWidget | None, titulo: str, texto: str = "", tipo: str = "exito") -> "Toast":
        if Toast._actual is not None:
            Toast._actual._cerrar_ya()
        toast = Toast(_ventana_anfitriona(parent), titulo, texto, tipo)
        Toast._actual = toast
        toast._presentar()
        return toast

    # ── Ciclo de vida ────────────────────────────────────────────────────

    def _posicion_final(self) -> QPoint:
        if self._anfitriona is not None and self._anfitriona.isVisible():
            marco = self._anfitriona.frameGeometry()
        else:
            pantalla = QGuiApplication.primaryScreen()
            marco = pantalla.availableGeometry() if pantalla is not None else self.geometry()
        return QPoint(marco.right() - self.width() - MARGEN, marco.bottom() - self.height() - MARGEN)

    def _presentar(self) -> None:
        final = self._posicion_final()
        if animaciones_activas():
            self.setWindowOpacity(0.0)
            self.move(final + QPoint(0, DESPLAZAMIENTO_ENTRADA))
            self.show()
            self._animar(b"windowOpacity", 0.0, 1.0, DURACION_CORTA)
            self._animar(b"pos", self.pos(), final, DURACION_CORTA)
        else:
            self.move(final)
            self.show()
        self._temporizador.start(self.duracion_ms)

    def _animar(self, propiedad: bytes, desde, hasta, ms: int) -> None:
        animacion = QPropertyAnimation(self, propiedad, self)
        animacion.setDuration(ms)
        animacion.setStartValue(desde)
        animacion.setEndValue(hasta)
        animacion.setEasingCurve(QEasingCurve.Type.OutCubic)
        animacion.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _ocultar(self) -> None:
        if self._cerrando:
            return
        self._cerrando = True
        if not animaciones_activas():
            self._cerrar_ya()
            return
        animacion = QPropertyAnimation(self, b"windowOpacity", self)
        animacion.setDuration(DURACION_MEDIA)
        animacion.setStartValue(1.0)
        animacion.setEndValue(0.0)
        animacion.finished.connect(self._cerrar_ya)
        animacion.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _cerrar_ya(self) -> None:
        self._temporizador.stop()
        if Toast._actual is self:
            Toast._actual = None
        self.close()
        self.deleteLater()
