"""Ventana "Detalle del cambio" COMPARTIDA por la auditoria de productos y la auditoria general.

El listado corta el detalle al ancho de su columna; aqui se ve entero: quien, cuando, que accion, cada cambio con su
valor anterior y su valor nuevo, los datos del registro y el texto completo.

SEGURIDAD: el `detalle` de un evento puede traer texto libre escrito por usuarios (motivos, observaciones). Todo lo que
se muestra aqui va como TEXTO PLANO (nunca se interpreta como HTML): por defecto Qt decide con una heuristica
(Qt::AutoText) si un QLabel es HTML, y un "<a href=...>" escrito en un motivo se renderizaria como un enlace falso.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence

import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.pantalla import ajustar_tamano, hacer_desplazable
from app.ui.styles import (
    COLOR_BLUE_LIGHTER,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_DANGER,
    COLOR_INFO_BG,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    DIALOGO_QSS,
    TABLE_QSS,
    alinear_encabezados,
    aplicar_sombra,
    dar_ancho_a_texto,
)

# Claves del `detalle` que son la lista de cambios (antes/despues): se muestran en la tabla "Cambios", no entre los
# "Datos del registro".
CLAVES_DE_CAMBIOS = frozenset(
    {
        "cambios_relevantes",
        "cambios",
        "movimientos",
        "cambios_precio",
        "precio_anterior",
        "precio_nuevo",
        "margen_anterior",
        "margen_nuevo",
    }
)


def etiqueta_por_defecto(campo: str) -> str:
    texto = campo.replace("_", " ").strip()
    return texto[:1].upper() + texto[1:] if texto else campo


def texto_valor(valor) -> str:
    """Valor tal cual (sin truncar); vacio / None se muestra como guion."""
    if valor is None or str(valor).strip() in ("", "None"):
        return "—"
    return str(valor)


def filas_de_cambios(
    detalle: str | None, etiquetar: Callable[[str], str] = etiqueta_por_defecto
) -> list[tuple[str, str, str]]:
    """(campo, valor anterior, valor nuevo) de un registro de auditoria, COMPLETOS: sin truncar descripciones ni
    cortar la lista de campos. Cubre los formatos que guarda el sistema (cambios_relevantes, cambios, movimientos de
    stock, cambios_precio y los campos sueltos del formato antiguo). Texto plano o JSON sin cambios -> lista vacia.
    `etiquetar` traduce el nombre interno del campo a una etiqueta legible."""
    if not detalle or not detalle.strip().startswith("{"):
        return []
    try:
        datos = json.loads(detalle)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(datos, dict):
        return []

    filas: list[tuple[str, str, str]] = []
    for clave in ("cambios_relevantes", "cambios"):
        for cambio in datos.get(clave) or []:
            if not isinstance(cambio, dict):
                continue
            filas.append(
                (
                    etiquetar(cambio.get("campo", "")),
                    texto_valor(cambio.get("valor_anterior")),
                    texto_valor(cambio.get("valor_nuevo")),
                )
            )
    for mov in datos.get("movimientos") or []:
        if not isinstance(mov, dict):
            continue
        nuevo = texto_valor(mov.get("valor_nuevo"))
        if mov.get("tipo_movimiento"):
            nuevo += f"  ({mov['tipo_movimiento']}: {mov.get('diferencia', '')})"
        filas.append((etiquetar(mov.get("campo", "")), texto_valor(mov.get("valor_anterior")), nuevo))
    precios = datos.get("cambios_precio")
    for clave, cambio in precios.items() if isinstance(precios, dict) else []:
        if not isinstance(cambio, dict):
            continue
        anterior, nuevo = cambio.get("anterior"), cambio.get("nuevo")
        filas.append(
            (
                clave.replace("_", " ").title(),
                f"${anterior}" if anterior is not None else "—",
                f"${nuevo}" if nuevo is not None else "—",
            )
        )
    if "precio_anterior" in datos or "precio_nuevo" in datos:
        filas.append(
            (
                "Precio",
                f"${datos['precio_anterior']}" if datos.get("precio_anterior") is not None else "—",
                f"${datos['precio_nuevo']}" if datos.get("precio_nuevo") is not None else "—",
            )
        )
    if "margen_anterior" in datos or "margen_nuevo" in datos:
        filas.append(
            ("Ganancia (%)", texto_valor(datos.get("margen_anterior")), texto_valor(datos.get("margen_nuevo")))
        )
    if "nuevo_estado" in datos:
        filas.append(("Estado", "—", texto_valor(datos["nuevo_estado"])))
    return filas


class DetalleAuditoriaDialog(QDialog):
    """Detalle completo de un registro de auditoria.

    `datos`: {"fecha", "usuario", "accion", "modulo", "extras": [(etiqueta, valor), ...] (opcional: p. ej. el producto),
    "cambios": [(campo, antes, despues)], "registro": [(campo, valor)] (opcional), "detalle": texto completo}."""

    def __init__(self, datos: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Detalle del cambio")
        ajustar_tamano(self, 860, 860, 700, 560)
        self.setStyleSheet(DIALOGO_QSS)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.tabla_cambios: QTableWidget | None = None
        self.tabla_registro: QTableWidget | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        root.addWidget(self._encabezado(datos))
        root.addWidget(self._tarjeta_datos(datos))
        if datos.get("cambios"):
            root.addWidget(
                self._tarjeta_tabla("Cambios", ["Campo", "Valor anterior", "Valor nuevo"], datos["cambios"], True)
            )
        if datos.get("registro"):
            root.addWidget(self._tarjeta_tabla("Datos del registro", ["Campo", "Valor"], datos["registro"], False))
        root.addWidget(self._tarjeta_texto(datos.get("detalle") or "Sin información adicional."), stretch=1)

        pie = QHBoxLayout()
        pie.addStretch()
        btn = QPushButton("Cerrar")
        btn.setIcon(qta.icon("fa5s.times", color=COLOR_PRIMARY))
        btn.setObjectName("BtnSecondary")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setAutoDefault(False)
        btn.clicked.connect(self.accept)
        pie.addWidget(btn)
        root.addLayout(pie)
        hacer_desplazable(self)  # en pantallas chicas el contenido se desplaza en vez de cortarse

    @staticmethod
    def _plano(lbl: QLabel) -> QLabel:
        lbl.setTextFormat(Qt.TextFormat.PlainText)  # nunca HTML: ver la nota de seguridad del modulo
        return lbl

    def _encabezado(self, datos: dict) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)
        icono = QLabel()
        icono.setPixmap(qta.icon("fa5s.search", color=COLOR_PRIMARY).pixmap(QSize(20, 20)))
        icono.setStyleSheet(
            f"background-color: {COLOR_INFO_BG}; border: 1.5px solid {COLOR_BLUE_LIGHTER}; "
            "border-radius: 8px; padding: 6px;"
        )
        icono.setFixedSize(38, 38)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        titulos = QVBoxLayout()
        titulos.setSpacing(1)
        titulos.setContentsMargins(0, 0, 0, 0)
        titulo = self._plano(QLabel("Detalle del cambio"))
        titulo.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        sub = self._plano(QLabel(f"{datos['accion']}  ·  {datos['fecha']}"))
        sub.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        titulos.addWidget(titulo)
        titulos.addWidget(sub)
        h.addWidget(icono)
        h.addLayout(titulos)
        h.addStretch()
        return w

    @staticmethod
    def _tarjeta() -> tuple[QWidget, QVBoxLayout]:
        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 14)
        lay.setSpacing(8)
        return card, lay

    def _titulo_seccion(self, texto: str) -> QLabel:
        lbl = self._plano(QLabel(texto))
        lbl.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {COLOR_TEXT_DARK};")
        return lbl

    def _tarjeta_datos(self, datos: dict) -> QWidget:
        card, lay = self._tarjeta()
        grilla = QGridLayout()
        grilla.setHorizontalSpacing(24)
        grilla.setVerticalSpacing(8)
        campos: Sequence[tuple[str, object]] = [
            ("Fecha", datos["fecha"]),
            ("Usuario", datos["usuario"]),
            ("Acción", datos["accion"]),
            ("Módulo", datos["modulo"]),
            *datos.get("extras", []),
        ]
        for i, (etiqueta, valor) in enumerate(campos):
            fila, col = divmod(i, 3)
            bloque = QVBoxLayout()
            bloque.setSpacing(1)
            e = self._plano(QLabel(str(etiqueta)))
            e.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {COLOR_TEXT_MUTED};")
            v = self._plano(QLabel(str(valor)))
            v.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_DARK};")
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            bloque.addWidget(e)
            bloque.addWidget(v)
            grilla.addLayout(bloque, fila, col)
        lay.addLayout(grilla)
        return card

    def _tarjeta_tabla(self, titulo: str, columnas: list[str], filas: Sequence[Sequence[str]], antes_despues: bool):
        card, lay = self._tarjeta()
        lay.addWidget(self._titulo_seccion(f"{titulo} ({len(filas)})"))
        tabla = QTableWidget(len(filas), len(columnas))
        tabla.setHorizontalHeaderLabels(columnas)
        tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tabla.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        tabla.setAlternatingRowColors(True)
        tabla.setShowGrid(False)
        tabla.setWordWrap(True)  # un valor largo (descripcion) baja de linea en vez de cortarse
        tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tabla.verticalHeader().setVisible(False)
        tabla.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        dar_ancho_a_texto(tabla, tuple(range(1, len(columnas))), filas_a_texto=True)
        # El encabezado se alinea igual que sus celdas.
        alinear_encabezados(tabla, {i: Qt.AlignmentFlag.AlignLeft for i in range(len(columnas))})
        for fila, valores in enumerate(filas):
            for col, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                item.setToolTip(valor)
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                if col == 0:
                    fuente = item.font()
                    fuente.setBold(True)
                    item.setFont(fuente)
                elif antes_despues:
                    item.setForeground(QColor(COLOR_DANGER if col == 1 else COLOR_SUCCESS))
                tabla.setItem(fila, col, item)
        tabla.setStyleSheet(TABLE_QSS)
        tabla.resizeRowsToContents()
        for fila in range(tabla.rowCount()):
            tabla.setRowHeight(fila, max(tabla.rowHeight(fila), 38))
        # Altura segun lo que ocupan las filas (con un tope; si hay mas, desplazamiento vertical)
        alto_filas = sum(tabla.rowHeight(f) for f in range(tabla.rowCount()))
        tabla.setFixedHeight(min(380, tabla.horizontalHeader().height() + alto_filas + 6))
        if antes_despues:
            self.tabla_cambios = tabla
        else:
            self.tabla_registro = tabla
        lay.addWidget(tabla)
        return card

    def _tarjeta_texto(self, texto: str) -> QWidget:
        card, lay = self._tarjeta()
        lay.addWidget(self._titulo_seccion("Detalle completo"))
        caja = QPlainTextEdit()  # QPlainTextEdit solo muestra texto plano
        caja.setReadOnly(True)
        caja.setPlainText(texto)
        caja.setMinimumHeight(110)
        caja.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 6px; padding: 8px; font-size: 13px; color: {COLOR_TEXT_DARK}; }}"
        )
        self.texto_detalle = caja
        lay.addWidget(caja)
        return card
