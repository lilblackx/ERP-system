import json
import math

import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.db.models import Ruta
from app.ui.mapa_widget import MapaWidget
from app.ui.message_box import MessageBox
from app.ui.styles import (
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_FIELD_BG,
    COLOR_PRIMARY,
    COLOR_PRIMARY_DARK,
    COLOR_PRIMARY_LIGHT,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    FONT_FAMILY,
    aplicar_sombra,
)

DIALOG_STYLE = f"""
QDialog {{
    background-color: {COLOR_CONTENT_BG};
    font-family: '{FONT_FAMILY}', Arial, sans-serif;
}}
QWidget#SectionCard {{
    background-color: {COLOR_CARD_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
}}
QLabel.FormLabel {{
    font-size: 12px;
    font-weight: 600;
    color: #334155;
    margin-bottom: 2px;
}}
QLabel.SectionTitle {{
    font-size: 11px;
    font-weight: bold;
    color: {COLOR_PRIMARY};
    letter-spacing: 0.8px;
    padding-bottom: 2px;
}}
QLineEdit {{
    background-color: #FFFFFF;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
    min-height: 20px;
}}
QLineEdit:focus {{
    border: 1.5px solid {COLOR_PRIMARY};
    background-color: #FFFFFF;
}}
QLineEdit::placeholder {{
    color: #94A3B8;
    font-size: 12px;
}}
QPushButton#BtnPrimary {{
    background-color: {COLOR_PRIMARY};
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 8px 22px;
    font-size: 13px;
    font-weight: bold;
}}
QPushButton#BtnPrimary:hover {{
    background-color: {COLOR_PRIMARY_LIGHT};
}}
QPushButton#BtnPrimary:pressed {{
    background-color: {COLOR_PRIMARY_DARK};
}}
QPushButton#BtnSecondary {{
    background-color: {COLOR_FIELD_BG};
    color: #475569;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#BtnSecondary:hover {{
    background-color: {COLOR_TABLE_HEADER};
    color: {COLOR_TEXT_DARK};
}}
QPushButton#BtnZona {{
    background-color: #FFFFFF;
    color: {COLOR_TEXT_DARK};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#BtnZona:hover {{
    background-color: {COLOR_TABLE_HEADER};
}}
"""


def _ordenar_por_angulo(vertices: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Reordena los vertices alrededor de su centroide (angulo respecto al centro) para
    que el poligono quede siempre sin auto-intersecciones sin importar en que orden el
    usuario los haya clickeado -- sin esto, clickear fuera del orden del perimetro
    producia una figura en forma de moño en vez de una zona con area limpia (reportado
    por el usuario, 2026-09-03). Con menos de 3 vertices no hay nada que reordenar (una
    linea entre 1-2 puntos no puede auto-intersectarse)."""
    if len(vertices) < 3:
        return list(vertices)
    centro_lat = sum(v[0] for v in vertices) / len(vertices)
    centro_lng = sum(v[1] for v in vertices) / len(vertices)
    return sorted(vertices, key=lambda v: math.atan2(v[0] - centro_lat, v[1] - centro_lng))


class RutaFormDialog(QDialog):
    """Dialogo de alta/edicion de rutas -- mismo patron visual que
    VendedorFormDialog (app/ui/vendedor_form_dialog.py). Nombre + descripcion (opcional)
    mas la zona de cobertura de la ruta: un poligono marcado con clicks en el mapa
    (MapaWidget(modo="zona"), migrations/0043) -- decision de negocio 2026-09-03: "una
    ruta no es un punto A/B, es una zona donde todos los clientes dentro de ella son
    atendidos por su vendedor", reemplazando el modelo anterior de origen/destino/
    trazado por calles (migrations/0039/0040)."""

    def __init__(self, ruta: Ruta | None = None, parent=None):
        super().__init__(parent)
        self.ruta = ruta
        # [(lat,lng), ...] vertices de la zona en el orden en que se marcaron (o se
        # cargaron al editar) -- es la fuente de verdad para "Deshacer ultimo punto"
        # (siempre quita el ultimo click, sin importar como se vea reordenado en el
        # mapa). Lo que se dibuja y se persiste como zona_geojson es
        # _ordenar_por_angulo(self._vertices), NUNCA esta lista cruda -- ver
        # _vertices_ordenados().
        self._vertices: list[tuple[float, float]] = []
        self.setWindowTitle("Editar Ruta" if ruta else "Nueva Ruta")
        # Mas ancho/alto que el resto de los dialogos de este tamaño (VendedorFormDialog,
        # etc.) a proposito -- pedido del usuario 2026-09-03: la zona se marca a puro
        # click sobre el mapa, asi que mas area de mapa hace la tarea mas facil.
        self.setFixedSize(620, 780)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()

        if ruta:
            self._precargar(ruta)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        icon_lbl = QLabel()
        fa_icon_name = "fa5s.edit" if self.ruta else "fa5s.draw-polygon"
        icon_lbl.setPixmap(qta.icon(fa_icon_name, color=COLOR_PRIMARY).pixmap(QSize(22, 22)))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(38, 38)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titles_layout = QVBoxLayout()
        titles_layout.setSpacing(1)
        titles_layout.setContentsMargins(0, 0, 0, 0)

        titulo_text = "Editar Ruta" if self.ruta else "Nueva Ruta"
        lbl_titulo = QLabel(titulo_text)
        lbl_titulo.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        lbl_subtitulo = QLabel("Zona de cobertura para asignar a los vendedores.")
        lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")

        titles_layout.addWidget(lbl_titulo)
        titles_layout.addWidget(lbl_subtitulo)

        header_layout.addWidget(icon_lbl)
        header_layout.addLayout(titles_layout)
        header_layout.addStretch()

        root.addWidget(header_widget)

        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 14)
        card_layout.setSpacing(8)

        titulo_card = QLabel("DATOS DE LA RUTA")
        titulo_card.setProperty("class", "SectionTitle")
        card_layout.addWidget(titulo_card)

        lbl_nombre = QLabel("Nombre <span style='color: #DC2626;'>*</span>")
        lbl_nombre.setProperty("class", "FormLabel")
        self.nombre_input = QLineEdit()
        self.nombre_input.setPlaceholderText("Ej: Ruta Centro")
        self.nombre_input.setFixedHeight(32)
        card_layout.addWidget(lbl_nombre)
        card_layout.addWidget(self.nombre_input)

        lbl_desc = QLabel("Descripción")
        lbl_desc.setProperty("class", "FormLabel")
        self.descripcion_input = QLineEdit()
        self.descripcion_input.setPlaceholderText("Opcional")
        self.descripcion_input.setFixedHeight(32)
        card_layout.addWidget(lbl_desc)
        card_layout.addWidget(self.descripcion_input)

        card_layout.addStretch()
        root.addWidget(card)

        # Tarjeta separada para el mapa, SIN aplicar_sombra() a proposito -- ver la nota
        # en app/ui/cliente_form_dialog.py::_make_card_ubicacion(): un QGraphicsEffect
        # (la sombra) en un ancestro de QWebEngineView hace que Qt intente renderizarlo
        # en un buffer offscreen para componer el efecto, y la ventana nativa del mapa
        # simplemente no se pinta. Diagnosticado 2026-09-01.
        card_mapa = QWidget()
        card_mapa.setObjectName("SectionCard")
        card_mapa_layout = QVBoxLayout(card_mapa)
        card_mapa_layout.setContentsMargins(16, 12, 16, 14)
        card_mapa_layout.setSpacing(8)

        lbl_zona = QLabel("ZONA DE COBERTURA <span style='color: #DC2626;'>*</span>")
        lbl_zona.setProperty("class", "SectionTitle")
        lbl_zona.setTextFormat(Qt.TextFormat.RichText)
        card_mapa_layout.addWidget(lbl_zona)

        lbl_instrucciones = QLabel("Haz clic en el mapa para marcar los vértices del contorno de la zona (mínimo 3).")
        lbl_instrucciones.setWordWrap(True)
        lbl_instrucciones.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        card_mapa_layout.addWidget(lbl_instrucciones)

        self.mapa = MapaWidget(editable=True, modo="zona", centrar_en_dispositivo=self.ruta is None)
        self.mapa.setMinimumHeight(340)
        self.mapa.vertice_zona_agregado.connect(self._on_vertice_agregado)
        card_mapa_layout.addWidget(self.mapa)

        # Fila de botones y contador en dos filas separadas (no una sola con stretch) --
        # con las etiquetas completas ("Deshacer último punto", "Limpiar zona") mas el
        # contador todo en una fila, el ancho fijo del dialogo (460px) no alcanzaba y Qt
        # recortaba el texto de los botones a la mitad (reportado por el usuario,
        # 2026-09-03). Textos mas cortos + contador en su propia fila deja margen de
        # sobra sin importar cuanto crezca el numero de verticces.
        acciones_layout = QHBoxLayout()
        acciones_layout.setSpacing(8)

        self.btn_deshacer = QPushButton("↩ Deshacer")
        self.btn_deshacer.setObjectName("BtnZona")
        self.btn_deshacer.setFixedHeight(28)
        self.btn_deshacer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_deshacer.clicked.connect(self._deshacer_vertice)

        self.btn_limpiar = QPushButton("🗑 Limpiar")
        self.btn_limpiar.setObjectName("BtnZona")
        self.btn_limpiar.setFixedHeight(28)
        self.btn_limpiar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_limpiar.clicked.connect(self._limpiar_zona)

        acciones_layout.addWidget(self.btn_deshacer)
        acciones_layout.addWidget(self.btn_limpiar)
        acciones_layout.addStretch()
        card_mapa_layout.addLayout(acciones_layout)

        self.lbl_contador = QLabel()
        self.lbl_contador.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        card_mapa_layout.addWidget(self.lbl_contador)

        root.addWidget(card_mapa, stretch=1)

        self._actualizar_contador()

        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 4, 0, 0)
        footer_layout.setSpacing(10)
        footer_layout.addStretch()

        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.setIcon(qta.icon("fa5s.times", color="#475569"))
        self.btn_cancelar.setObjectName("BtnSecondary")
        self.btn_cancelar.setFixedHeight(36)
        self.btn_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancelar.setAutoDefault(False)
        self.btn_cancelar.clicked.connect(self.reject)

        self.btn_guardar = QPushButton("Guardar Ruta")
        self.btn_guardar.setIcon(qta.icon("fa5s.save", color="#FFFFFF"))
        self.btn_guardar.setObjectName("BtnPrimary")
        self.btn_guardar.setFixedHeight(36)
        self.btn_guardar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guardar.setAutoDefault(False)
        self.btn_guardar.clicked.connect(self._validar_y_aceptar)

        footer_layout.addWidget(self.btn_cancelar)
        footer_layout.addWidget(self.btn_guardar)
        root.addLayout(footer_layout)

    def _vertices_ordenados(self) -> list[tuple[float, float]]:
        return _ordenar_por_angulo(self._vertices)

    def _redibujar_zona(self) -> None:
        self.mapa.establecer_zona(self._vertices_ordenados())
        self._actualizar_contador()

    def _on_vertice_agregado(self, lat: float, lng: float) -> None:
        self._vertices.append((lat, lng))
        self._redibujar_zona()

    def _deshacer_vertice(self) -> None:
        if not self._vertices:
            return
        self._vertices.pop()
        self._redibujar_zona()

    def _limpiar_zona(self) -> None:
        self._vertices = []
        self.mapa.limpiar_zona()
        self._actualizar_contador()

    def _actualizar_contador(self) -> None:
        n = len(self._vertices)
        texto = f"{n} vértice{'s' if n != 1 else ''} marcado{'s' if n != 1 else ''}"
        if n < 3:
            texto += " (mínimo 3)"
        self.lbl_contador.setText(texto)

    def _precargar(self, ruta: Ruta) -> None:
        self.nombre_input.setText(ruta.nombre_ruta or "")
        self.descripcion_input.setText(ruta.descripcion_ruta or "")
        if ruta.zona_geojson:
            self._vertices = [tuple(p) for p in json.loads(ruta.zona_geojson)]
            self._redibujar_zona()

    def _validar_y_aceptar(self) -> None:
        if not self.nombre_input.text().strip():
            MessageBox.warning(self, "Dato requerido", "El nombre de la ruta es obligatorio.")
            self.nombre_input.setFocus()
            return

        if len(self._vertices) < 3:
            MessageBox.warning(
                self,
                "Zona incompleta",
                "Marca al menos 3 vértices en el mapa para definir el contorno de la zona de cobertura.",
            )
            return

        self.accept()

    def get_data(self) -> dict:
        return {
            "nombre_ruta": self.nombre_input.text().strip(),
            "descripcion_ruta": self.descripcion_input.text().strip() or None,
            "zona_geojson": json.dumps(self._vertices_ordenados()),
        }
