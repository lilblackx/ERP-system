"""Botones de barra de herramientas que despliegan un popup en vez de mostrar varios
controles sueltos inline -- ver docs/GUIA_ESTILO_UI.md seccion 3.

- `BotonFiltros`: agrupa varios QComboBox/QCheckBox de filtro (antes cada uno era un
  dropdown separado en la barra).
- `BotonExportar`: un solo boton "Exportar" que ofrece elegir Excel o PDF (antes eran
  dos botones "Exportar Excel"/"Exportar PDF" lado a lado).

Uso tipico de `BotonFiltros` (reemplaza los `h.addWidget(self.xxx_combo)` sueltos):

    self.estado_combo = QComboBox()
    for etiqueta, valor in ESTADOS_FILTRO:
        self.estado_combo.addItem(etiqueta, valor)
    self.estado_combo.currentIndexChanged.connect(self._buscar_desde_inicio)

    self.btn_filtrar = BotonFiltros([("Estado", self.estado_combo), ...])
    h.addWidget(self.btn_filtrar)  # en vez de h.addWidget(self.estado_combo)

Los widgets de filtro se siguen creando y conectando exactamente igual que antes
(mismo `currentIndexChanged`/`toggled`) -- BotonFiltros no cambia su comportamiento,
solo los saca de la barra visible y los agrupa en el popup, y además refleja cuántos
filtros están activos en el propio texto del botón ("Filtrar (2)").

Uso tipico de `BotonExportar`:

    self.btn_exportar = BotonExportar(on_excel=self.exportar_excel, on_pdf=self.exportar_pdf)
    h.addWidget(self.btn_exportar)
"""

from collections.abc import Callable

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui.styles import (
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_DANGER,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_TABLE_HOVER,
    COLOR_TEXT_DARK,
    FONT_FAMILY,
    aplicar_sombra,
)

POPUP_STYLE = f"""
QWidget#PopupCard {{
    background-color: {COLOR_CARD_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
    font-family: '{FONT_FAMILY}', Arial, sans-serif;
}}
QLabel#FiltroLabel {{
    font-size: 12px;
    font-weight: 600;
    color: #334155;
    margin-bottom: 2px;
    border: none;
    background: transparent;
}}
QComboBox {{
    background-color: #FFFFFF;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
    min-height: 20px;
}}
QComboBox:focus {{
    border: 1.5px solid {COLOR_PRIMARY};
}}
QCheckBox {{
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
    spacing: 8px;
    border: none;
    background: transparent;
}}
QPushButton#BtnLimpiarFiltros {{
    background-color: transparent;
    color: {COLOR_PRIMARY};
    border: none;
    padding: 4px 0px;
    font-size: 12px;
    font-weight: 600;
    text-align: left;
}}
QPushButton#BtnLimpiarFiltros:hover {{
    text-decoration: underline;
}}
QPushButton#ItemExportar {{
    background-color: transparent;
    color: {COLOR_TEXT_DARK};
    border: none;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 13px;
    text-align: left;
}}
QPushButton#ItemExportar:hover {{
    background-color: {COLOR_TABLE_HOVER};
}}
"""


class _PopupAnclado(QWidget):
    """Base comun: una tarjeta (`#PopupCard`) mostrada como `Qt.WindowType.Popup`
    (se cierra sola al perder el foco/Escape, igual que un QComboBox o QMenu) y
    posicionada debajo-izquierda del boton que la abre."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setStyleSheet(POPUP_STYLE)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.card = QWidget()
        self.card.setObjectName("PopupCard")
        aplicar_sombra(self.card)
        outer.addWidget(self.card)

    def mostrar_bajo(self, boton: QPushButton) -> None:
        punto = boton.mapToGlobal(boton.rect().bottomLeft())
        self.move(punto.x(), punto.y() + 4)
        self.show()


class _BotonConPopup(QPushButton):
    """Boton secundario estandar que alterna un `_PopupAnclado` propio al hacer
    click. Las subclases fijan `self._popup` antes de que el boton sea clickeable."""

    def __init__(self, texto: str, icono: str, parent=None):
        super().__init__(texto, parent)
        self.setIcon(qta.icon(icono, color=COLOR_TEXT_DARK))
        self.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoDefault(False)
        self._popup: _PopupAnclado | None = None
        self.clicked.connect(self._alternar_popup)

    def _alternar_popup(self) -> None:
        if self._popup is None:
            return
        if self._popup.isVisible():
            self._popup.hide()
            return
        self._popup.mostrar_bajo(self)


# ── Filtrar ──────────────────────────────────────────────────────────────────


class _FiltrosPopupCard(_PopupAnclado):
    def __init__(self, filtros: list[tuple[str, QWidget]], on_cambio: Callable[[], None], parent=None):
        super().__init__(parent)
        self._filtros = filtros
        self._on_cambio = on_cambio

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        for etiqueta, widget in filtros:
            if etiqueta:
                lbl = QLabel(etiqueta)
                lbl.setObjectName("FiltroLabel")
                layout.addWidget(lbl)
            layout.addWidget(widget)

        btn_limpiar = QPushButton("Limpiar filtros")
        btn_limpiar.setObjectName("BtnLimpiarFiltros")
        btn_limpiar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_limpiar.setAutoDefault(False)
        btn_limpiar.clicked.connect(self._limpiar)
        layout.addWidget(btn_limpiar)

        self.setFixedWidth(260)

    def _limpiar(self) -> None:
        for _, widget in self._filtros:
            widget.blockSignals(True)
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(0)
            elif isinstance(widget, QCheckBox):
                widget.setChecked(False)
            widget.blockSignals(False)
        self._on_cambio()


class BotonFiltros(_BotonConPopup):
    """Boton "Filtrar" que despliega `filtros` (pares etiqueta + QComboBox/QCheckBox
    ya creados y conectados por el caller) en un popup, y muestra la cantidad de
    filtros activos en su propio texto ("Filtrar (2)")."""

    def __init__(self, filtros: list[tuple[str, QWidget]], parent=None):
        super().__init__("Filtrar", "fa5s.filter", parent)
        self._filtros = filtros
        self._popup = _FiltrosPopupCard(filtros, self._actualizar_texto, parent=self)

        for _, widget in filtros:
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._actualizar_texto)
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(self._actualizar_texto)
        self._actualizar_texto()

    def _cantidad_filtros_activos(self) -> int:
        activos = 0
        for _, widget in self._filtros:
            if isinstance(widget, QComboBox) and widget.currentIndex() > 0:
                activos += 1
            elif isinstance(widget, QCheckBox) and widget.isChecked():
                activos += 1
        return activos

    def _actualizar_texto(self) -> None:
        activos = self._cantidad_filtros_activos()
        self.setText(f"Filtrar ({activos})" if activos else "Filtrar")
        self.setStyleSheet(
            BUTTON_SECONDARY_QSS
            if not activos
            else BUTTON_SECONDARY_QSS + f"QPushButton {{ border-color: {COLOR_PRIMARY}; color: {COLOR_PRIMARY}; }}"
        )


# ── Exportar ─────────────────────────────────────────────────────────────────


class _ExportarPopupCard(_PopupAnclado):
    def __init__(self, on_excel: Callable[[], None], on_pdf: Callable[[], None], parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(2)

        item_excel = QPushButton("  Exportar a Excel")
        item_excel.setObjectName("ItemExportar")
        item_excel.setIcon(qta.icon("fa5s.file-excel", color=COLOR_SUCCESS))
        item_excel.setCursor(Qt.CursorShape.PointingHandCursor)
        item_excel.setAutoDefault(False)
        item_excel.clicked.connect(lambda: (self.hide(), on_excel()))

        item_pdf = QPushButton("  Exportar a PDF")
        item_pdf.setObjectName("ItemExportar")
        item_pdf.setIcon(qta.icon("fa5s.file-pdf", color=COLOR_DANGER))
        item_pdf.setCursor(Qt.CursorShape.PointingHandCursor)
        item_pdf.setAutoDefault(False)
        item_pdf.clicked.connect(lambda: (self.hide(), on_pdf()))

        layout.addWidget(item_excel)
        layout.addWidget(item_pdf)
        self.setFixedWidth(190)


class BotonExportar(_BotonConPopup):
    """Boton "Exportar" que despliega un popup para elegir Excel o PDF, en vez de dos
    botones separados en la barra."""

    def __init__(self, on_excel: Callable[[], None], on_pdf: Callable[[], None], parent=None):
        super().__init__("Exportar", "fa5s.file-export", parent)
        self._popup = _ExportarPopupCard(on_excel, on_pdf, parent=self)


__all__ = ["BotonExportar", "BotonFiltros"]
