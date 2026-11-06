"""Ventana "Novedades": lo que cambio en cada version, lo util resaltado y una linea general de mejoras.

Se abre sola la primera vez que un usuario entra despues de una actualizacion, ya filtrada por los modulos que su rol
puede ver (app/novedades.py), y se puede reabrir desde el pie del menu lateral. Todo el texto va como TEXTO PLANO.
"""

from __future__ import annotations

import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.novedades import ETIQUETAS_TIPO, TIPOS_DE_CAMBIO, Cambio, Entrega
from app.ui.pantalla import ajustar_tamano
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    COLOR_BLUE_LIGHTER,
    COLOR_BORDER,
    COLOR_INFO_BG,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_SUCCESS_BG,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    DIALOGO_QSS,
)

# Colores de la etiqueta de cada tipo: (fondo, texto)
COLORES_TIPO = {
    "nuevo": (COLOR_SUCCESS_BG, COLOR_SUCCESS),
    "mejorado": (COLOR_INFO_BG, COLOR_PRIMARY),
}


def _plano(lbl: QLabel) -> QLabel:
    lbl.setTextFormat(Qt.TextFormat.PlainText)
    return lbl


class NovedadesDialog(QDialog):
    def __init__(self, entregas: list[Entrega], titulo: str, subtitulo: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Novedades")
        ajustar_tamano(self, 660, 500, 520, 400)
        self.setStyleSheet(DIALOGO_QSS)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.entregas = entregas

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(24, 20, 24, 20)
        raiz.setSpacing(14)
        raiz.addWidget(self._encabezado(titulo, subtitulo))

        # Las versiones van en un area desplazable: con varias versiones juntas la lista es larga.
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setFrameShape(QFrame.Shape.NoFrame)
        desplazable.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        desplazable.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        contenido = QWidget()
        contenido.setObjectName("NovedadesContenido")
        contenido.setStyleSheet("QWidget#NovedadesContenido { background: transparent; }")
        lista = QVBoxLayout(contenido)
        lista.setContentsMargins(2, 2, 8, 6)
        lista.setSpacing(14)
        for entrega in entregas:
            lista.addWidget(self._tarjeta_entrega(entrega))
        lista.addStretch()
        desplazable.setWidget(contenido)
        desplazable.viewport().setStyleSheet("background: transparent;")
        raiz.addWidget(desplazable, stretch=1)

        pie = QHBoxLayout()
        pie.addStretch()
        self.btn_entendido = QPushButton("Entendido")
        self.btn_entendido.setStyleSheet(BUTTON_PRIMARY_QSS)
        self.btn_entendido.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_entendido.setDefault(True)
        self.btn_entendido.clicked.connect(self.accept)
        pie.addWidget(self.btn_entendido)
        raiz.addLayout(pie)

    @staticmethod
    def _encabezado(titulo: str, subtitulo: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)
        icono = QLabel()
        icono.setPixmap(qta.icon("fa5s.newspaper", color=COLOR_PRIMARY).pixmap(QSize(20, 20)))
        icono.setStyleSheet(
            f"background-color: {COLOR_INFO_BG}; border: 1.5px solid {COLOR_BLUE_LIGHTER}; "
            "border-radius: 8px; padding: 6px;"
        )
        icono.setFixedSize(38, 38)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        textos = QVBoxLayout()
        textos.setSpacing(1)
        textos.setContentsMargins(0, 0, 0, 0)
        t = _plano(QLabel(titulo))
        t.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        s = _plano(QLabel(subtitulo))
        s.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        textos.addWidget(t)
        textos.addWidget(s)
        h.addWidget(icono)
        h.addLayout(textos)
        h.addStretch()
        return w

    def _tarjeta_entrega(self, entrega: Entrega) -> QWidget:
        card = QWidget()
        card.setObjectName("SectionCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(10)

        cab = QHBoxLayout()
        version = _plano(QLabel(f"Versión {entrega.version}"))
        version.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        fecha = _plano(QLabel(entrega.fecha_legible))
        fecha.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        cab.addWidget(version)
        cab.addStretch()
        cab.addWidget(fecha)
        lay.addLayout(cab)

        if entrega.titulo:
            titulo = _plano(QLabel(entrega.titulo))
            titulo.setWordWrap(True)
            titulo.setStyleSheet(f"font-size: 13px; color: {COLOR_TEXT_MUTED};")
            lay.addWidget(titulo)

        # Primero lo mas util (destacado), luego el resto por tipo; la linea "general" va al final, discreta.
        concretos = [c for c in entrega.cambios if c.tipo != "general"]
        for cambio in [c for c in concretos if c.destacado]:
            lay.addWidget(self._fila_cambio(cambio))
        for tipo in TIPOS_DE_CAMBIO:
            for cambio in (c for c in concretos if c.tipo == tipo and not c.destacado):
                lay.addWidget(self._fila_cambio(cambio))
        for cambio in (c for c in entrega.cambios if c.tipo == "general"):
            lay.addWidget(self._linea_general(cambio))
        return card

    @staticmethod
    def _linea_general(cambio: Cambio) -> QWidget:
        """La linea de "mejoras de estabilidad": sin etiqueta ni resalte, separada por una linea fina."""
        caja = QWidget()
        v = QVBoxLayout(caja)
        v.setContentsMargins(0, 4, 0, 0)
        v.setSpacing(8)
        separador = QFrame()
        separador.setFrameShape(QFrame.Shape.HLine)
        separador.setStyleSheet(f"background-color: {COLOR_BORDER}; max-height: 1px; border: none;")
        v.addWidget(separador)
        texto = _plano(QLabel(cambio.texto))
        texto.setWordWrap(True)
        texto.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        v.addWidget(texto)
        return caja

    @staticmethod
    def _fila_cambio(cambio: Cambio) -> QWidget:
        fila = QFrame()
        fila.setObjectName("CambioDestacado" if cambio.destacado else "CambioNormal")
        # Selector por objectName: una hoja sin selector se heredaria a las etiquetas hijas (fondos grises).
        fila.setStyleSheet(
            f"QFrame#CambioDestacado {{ background-color: {COLOR_INFO_BG}; border: 1px solid {COLOR_BLUE_LIGHTER};"
            " border-radius: 8px; }"
            "QFrame#CambioNormal { background: transparent; border: none; }"
        )
        h = QHBoxLayout(fila)
        pad = 10 if cambio.destacado else 0
        h.setContentsMargins(pad, 8 if cambio.destacado else 2, pad, 8 if cambio.destacado else 2)
        h.setSpacing(12)
        fondo, texto_color = COLORES_TIPO.get(cambio.tipo, COLORES_TIPO["mejorado"])
        etiqueta = _plano(QLabel(ETIQUETAS_TIPO.get(cambio.tipo, cambio.tipo.upper())))
        etiqueta.setFixedWidth(86)
        etiqueta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        etiqueta.setStyleSheet(
            f"background-color: {fondo}; color: {texto_color}; border: none; border-radius: 9px; padding: 2px 0; "
            "font-size: 10px; font-weight: bold; letter-spacing: 0.8px;"
        )
        texto = _plano(QLabel(cambio.texto))
        texto.setWordWrap(True)
        peso = "600" if cambio.destacado else "normal"
        texto.setStyleSheet(
            f"font-size: 13px; font-weight: {peso}; color: {COLOR_TEXT_DARK}; background: transparent; border: none;"
        )
        h.addWidget(etiqueta, alignment=Qt.AlignmentFlag.AlignTop)
        h.addWidget(texto, stretch=1)
        return fila
