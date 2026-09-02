import functools
import json

import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.db.models import Ruta
from app.ui.geo_http import HttpWorker, calcular_ruta_por_calles
from app.ui.mapa_widget import MapaWidget
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
"""


class RutaFormDialog(QDialog):
    """Dialogo de alta/edicion de rutas -- mismo patron visual que
    VendedorFormDialog (app/ui/vendedor_form_dialog.py). Nombre + descripcion (opcional)
    mas el recorrido real de la ruta: origen y destino marcados en el mapa
    (MapaWidget(modo="ruta"), migrations/0040), con el trazado por calles entre ambos
    calculado automaticamente (ver _recalcular_trazado) y guardado junto con la ruta."""

    def __init__(self, ruta: Ruta | None = None, parent=None):
        super().__init__(parent)
        self.ruta = ruta
        # [[lat,lng], ...] del ultimo trazado calculado (real por calles, o linea recta
        # de respaldo) -- ver _recalcular_trazado(). None hasta que origen y destino
        # esten ambos fijos.
        self._trazado_actual: list[tuple[float, float]] | None = None
        self._worker_trazado = None
        self.setWindowTitle("Editar Ruta" if ruta else "Nueva Ruta")
        self.setFixedSize(460, 700)
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
        fa_icon_name = "fa5s.edit" if self.ruta else "fa5s.route"
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

        lbl_subtitulo = QLabel("Ruta de reparto/cobranza para asignar a los vendedores.")
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

        lbl_ubicacion = QLabel("RECORRIDO (ORIGEN → DESTINO) <span style='color: #DC2626;'>*</span>")
        lbl_ubicacion.setProperty("class", "SectionTitle")
        lbl_ubicacion.setTextFormat(Qt.TextFormat.RichText)
        card_mapa_layout.addWidget(lbl_ubicacion)

        # Control segmentado: que punto recibe el proximo click/busqueda/ubicacion
        # precisa en el mapa (modo="ruta" de MapaWidget). Arranca en "Origen"; al fijarlo
        # el propio mapa avanza el objetivo a "Destino" (ver _on_punto_ruta_cambiado),
        # asi que este toggle se sincroniza reflejando ese avance, no solo disparandolo.
        objetivo_layout = QHBoxLayout()
        objetivo_layout.setSpacing(6)
        lbl_marcando = QLabel("Marcando:")
        lbl_marcando.setProperty("class", "FormLabel")
        self.btn_origen_activo = QPushButton("📍 Origen")
        self.btn_origen_activo.setCheckable(True)
        self.btn_origen_activo.setChecked(True)
        self.btn_destino_activo = QPushButton("🏁 Destino")
        self.btn_destino_activo.setCheckable(True)
        for btn in (self.btn_origen_activo, self.btn_destino_activo):
            btn.setFixedHeight(28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._grupo_objetivo = QButtonGroup(self)
        self._grupo_objetivo.setExclusive(True)
        self._grupo_objetivo.addButton(self.btn_origen_activo)
        self._grupo_objetivo.addButton(self.btn_destino_activo)
        self.btn_origen_activo.toggled.connect(lambda marcado: marcado and self.mapa.set_objetivo_activo("origen"))
        self.btn_destino_activo.toggled.connect(lambda marcado: marcado and self.mapa.set_objetivo_activo("destino"))
        objetivo_layout.addWidget(lbl_marcando)
        objetivo_layout.addWidget(self.btn_origen_activo)
        objetivo_layout.addWidget(self.btn_destino_activo)
        objetivo_layout.addStretch()
        card_mapa_layout.addLayout(objetivo_layout)

        self.mapa = MapaWidget(editable=True, modo="ruta", centrar_en_dispositivo=self.ruta is None)
        self.mapa.setMinimumHeight(200)
        self.mapa.punto_ruta_cambiado.connect(self._on_punto_ruta_cambiado)
        card_mapa_layout.addWidget(self.mapa)

        self.lbl_calculando = QLabel("Calculando trazado por calles…")
        self.lbl_calculando.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        self.lbl_calculando.setVisible(False)
        card_mapa_layout.addWidget(self.lbl_calculando)

        card_mapa_layout.addWidget(self._make_fila_coordenadas("Origen", "origen"))
        card_mapa_layout.addWidget(self._make_fila_coordenadas("Destino", "destino"))

        root.addWidget(card_mapa, stretch=1)

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

    def _make_fila_coordenadas(self, etiqueta: str, prefijo: str) -> QWidget:
        """Fila "Origen"/"Destino" con sus inputs de lat/lng -- guarda los QLineEdit como
        self.<prefijo>_lat_input/self.<prefijo>_lng_input para que el resto del dialogo
        (precargar, validar, get_data) los use por nombre."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)

        lbl = QLabel(f"{etiqueta} <span style='color: #DC2626;'>*</span>")
        lbl.setProperty("class", "FormLabel")
        lbl.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(lbl)

        fila = QHBoxLayout()
        fila.setSpacing(8)

        lat_input = QLineEdit()
        lat_input.setPlaceholderText("Latitud, ej: 10.4806")
        lat_input.setFixedHeight(32)

        lng_input = QLineEdit()
        lng_input.setPlaceholderText("Longitud, ej: -66.9036")
        lng_input.setFixedHeight(32)

        if prefijo == "origen":
            self.origen_lat_input, self.origen_lng_input = lat_input, lng_input
            lat_input.editingFinished.connect(self._on_origen_editado)
            lng_input.editingFinished.connect(self._on_origen_editado)
        else:
            self.destino_lat_input, self.destino_lng_input = lat_input, lng_input
            lat_input.editingFinished.connect(self._on_destino_editado)
            lng_input.editingFinished.connect(self._on_destino_editado)

        fila.addWidget(lat_input)
        fila.addWidget(lng_input)
        v.addLayout(fila)
        return w

    def _leer_par(self, lat_input: QLineEdit, lng_input: QLineEdit) -> tuple[float, float] | None:
        lat_texto = lat_input.text().strip()
        lng_texto = lng_input.text().strip()
        if not lat_texto or not lng_texto:
            return None
        try:
            return float(lat_texto), float(lng_texto)
        except ValueError:
            return None

    def _leer_origen(self) -> tuple[float, float] | None:
        return self._leer_par(self.origen_lat_input, self.origen_lng_input)

    def _leer_destino(self) -> tuple[float, float] | None:
        return self._leer_par(self.destino_lat_input, self.destino_lng_input)

    def _on_punto_ruta_cambiado(self, rol: str, lat: float, lng: float) -> None:
        if rol == "origen":
            self.origen_lat_input.setText(f"{lat:.7f}")
            self.origen_lng_input.setText(f"{lng:.7f}")
            self.mapa.set_origen(lat, lng)
            # Espeja el auto-avance que ya hizo MapaWidget internamente (ver
            # MapaWidget._on_click_js/_aplicar_punto) -- sin esto el toggle se queda
            # marcado en "Origen" mientras el mapa ya esta esperando el destino.
            self.btn_destino_activo.setChecked(True)
        else:
            self.destino_lat_input.setText(f"{lat:.7f}")
            self.destino_lng_input.setText(f"{lng:.7f}")
            self.mapa.set_destino(lat, lng)
        self._recalcular_trazado()

    def _on_origen_editado(self) -> None:
        origen = self._leer_origen()
        if origen is not None:
            self.mapa.set_origen(*origen)
        self._recalcular_trazado()

    def _on_destino_editado(self) -> None:
        destino = self._leer_destino()
        if destino is not None:
            self.mapa.set_destino(*destino)
        self._recalcular_trazado()

    def _recalcular_trazado(self) -> None:
        origen = self._leer_origen()
        destino = self._leer_destino()
        if origen is None or destino is None:
            self.mapa.limpiar_trazado()
            self._trazado_actual = None
            return
        # Linea recta de inmediato -- nunca deja el trazado vacio mientras se calcula el
        # real por calles (OSRM es un servicio publico sin SLA, puede tardar o fallar).
        # Se reemplaza sola si _on_trazado_calculado llega a tiempo con una respuesta.
        self._trazado_actual = [origen, destino]
        self.mapa.dibujar_trazado(self._trazado_actual)

        self.lbl_calculando.setVisible(True)
        self._worker_trazado = HttpWorker(functools.partial(calcular_ruta_por_calles, origen, destino), self)
        self._worker_trazado.resultado.connect(functools.partial(self._on_trazado_calculado, origen, destino))
        self._worker_trazado.start()

    def _on_trazado_calculado(
        self, origen: tuple[float, float], destino: tuple[float, float], puntos: list[tuple[float, float]] | None
    ) -> None:
        self.lbl_calculando.setVisible(False)
        # Si el usuario ya siguio editando origen/destino mientras esta respuesta viajaba
        # por la red, descartarla -- ya no corresponde al par de puntos actual (uno mas
        # reciente ya disparo su propio calculo).
        if self._leer_origen() != origen or self._leer_destino() != destino:
            return
        if puntos:
            self._trazado_actual = puntos
            self.mapa.dibujar_trazado(self._trazado_actual)

    def _precargar(self, ruta: Ruta) -> None:
        self.nombre_input.setText(ruta.nombre_ruta or "")
        self.descripcion_input.setText(ruta.descripcion_ruta or "")
        if ruta.latitud is not None and ruta.longitud is not None:
            lat, lng = float(ruta.latitud), float(ruta.longitud)
            self.origen_lat_input.setText(f"{lat:.7f}")
            self.origen_lng_input.setText(f"{lng:.7f}")
            self.mapa.set_origen(lat, lng)
        if ruta.destino_latitud is not None and ruta.destino_longitud is not None:
            lat, lng = float(ruta.destino_latitud), float(ruta.destino_longitud)
            self.destino_lat_input.setText(f"{lat:.7f}")
            self.destino_lng_input.setText(f"{lng:.7f}")
            self.mapa.set_destino(lat, lng)
        # Dibuja el trazado ya guardado en vez de recalcularlo -- llamar a OSRM de nuevo
        # solo porque se abrio el dialogo para editar/ver seria una llamada de red
        # innecesaria (RutaFormDialog._recalcular_trazado solo se dispara cuando el
        # usuario efectivamente cambia origen o destino).
        if ruta.trazado_geojson:
            self._trazado_actual = [tuple(p) for p in json.loads(ruta.trazado_geojson)]
            self.mapa.dibujar_trazado(self._trazado_actual)

    def _validar_y_aceptar(self) -> None:
        if not self.nombre_input.text().strip():
            QMessageBox.warning(self, "Dato requerido", "El nombre de la ruta es obligatorio.")
            self.nombre_input.setFocus()
            return

        origen = self._leer_origen()
        destino = self._leer_destino()
        if origen is None or destino is None:
            QMessageBox.warning(
                self,
                "Dato requerido",
                "El origen y el destino de la ruta son obligatorios. Marca ambos puntos en "
                "el mapa (busca un lugar, hace click o usa tu ubicación) o ingresa las "
                "coordenadas.",
            )
            return
        for etiqueta, (lat, lng) in (("origen", origen), ("destino", destino)):
            if not (-90 <= lat <= 90):
                QMessageBox.warning(self, "Dato inválido", f"La latitud de {etiqueta} debe estar entre -90 y 90.")
                return
            if not (-180 <= lng <= 180):
                QMessageBox.warning(self, "Dato inválido", f"La longitud de {etiqueta} debe estar entre -180 y 180.")
                return

        self.accept()

    def get_data(self) -> dict:
        origen = self._leer_origen()
        destino = self._leer_destino()
        return {
            "nombre_ruta": self.nombre_input.text().strip(),
            "descripcion_ruta": self.descripcion_input.text().strip() or None,
            "latitud": origen[0] if origen else None,
            "longitud": origen[1] if origen else None,
            "destino_latitud": destino[0] if destino else None,
            "destino_longitud": destino[1] if destino else None,
            "trazado_geojson": json.dumps(self._trazado_actual) if self._trazado_actual else None,
        }
