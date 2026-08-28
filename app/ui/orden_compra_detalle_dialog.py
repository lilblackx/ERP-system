"""Dialogo de solo lectura para ver el detalle completo de una orden de compra
(cabecera + lineas). Mismo patron visual que factura_detalle_dialog.py."""

import logging

import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.styles import (
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_FIELD_BG,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
    FONT_FAMILY,
    TABLE_QSS,
    alinear_encabezados,
    aplicar_sombra,
    color_con_alpha,
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
QWidget#FieldChip {{
    background-color: {COLOR_FIELD_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
}}
QLabel.FormLabel {{
    font-size: 11px;
    font-weight: 600;
    color: {COLOR_TEXT_MUTED};
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
QLabel.FormValue {{
    font-size: 13px;
    font-weight: 600;
    color: {COLOR_TEXT_DARK};
}}
QLabel.SectionTitle {{
    font-size: 11px;
    font-weight: bold;
    color: {COLOR_PRIMARY};
    letter-spacing: 0.8px;
    padding-bottom: 2px;
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

logger = logging.getLogger(__name__)

COLORES_ESTADO_OC = {
    "PENDIENTE": COLOR_WARNING,
    "PARCIAL": COLOR_PRIMARY,
    "COMPLETA": COLOR_SUCCESS,
    "ANULADA": COLOR_DANGER,
}


class OrdenCompraDetalleDialog(QDialog):
    """Vista de solo lectura de una orden de compra: cabecera + lineas.
    `datos` es el dict devuelto por `CompraOCService.obtener_oc()`
    ({"oc": CompraOC, "detalles": [CompraOCDetalle, ...]})."""

    def __init__(self, datos: dict, parent=None):
        super().__init__(parent)
        self.datos = datos
        self.oc = datos["oc"]
        self.detalles = datos["detalles"]
        self.setWindowTitle(f"Orden de Compra {self.oc.numero_oc}")
        self.resize(720, 600)
        self.setMinimumSize(720, 600)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        root.addWidget(self._make_header())
        root.addWidget(self._make_ficha())
        root.addWidget(self._make_tabla_items(), stretch=1)
        root.addLayout(self._make_footer())

    def _make_header(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.file-signature", color=COLOR_PRIMARY).pixmap(QSize(22, 22)))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(38, 38)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titulos = QVBoxLayout()
        titulos.setSpacing(1)
        titulos.setContentsMargins(0, 0, 0, 0)

        lbl_titulo = QLabel(f"Orden de Compra {self.oc.numero_oc}")
        lbl_titulo.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        lbl_subtitulo = QLabel("Detalle de la orden")
        lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        titulos.addWidget(lbl_titulo)
        titulos.addWidget(lbl_subtitulo)

        h.addWidget(icon_lbl)
        h.addLayout(titulos)
        h.addStretch()

        color_estado = COLORES_ESTADO_OC.get(self.oc.estado, COLOR_TEXT_MUTED)
        badge = QLabel(self.oc.estado.capitalize())
        badge.setStyleSheet(
            f"background-color: {color_con_alpha(color_estado, alpha=45)}; color: {color_estado};"
            f" border: 1px solid {color_estado}; border-radius: 6px;"
            " padding: 4px 12px; font-size: 12px; font-weight: bold;"
        )
        h.addWidget(badge)
        return w

    def _campo_chip(self, etiqueta: str, valor: str) -> QWidget:
        """Envuelve un par etiqueta/valor en su propia tarjeta chica."""
        chip = QWidget()
        chip.setObjectName("FieldChip")
        layout = QVBoxLayout(chip)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        lbl_etq = QLabel(etiqueta)
        lbl_etq.setProperty("class", "FormLabel")
        lbl_val = QLabel(valor)
        lbl_val.setProperty("class", "FormValue")
        lbl_val.setWordWrap(True)
        layout.addWidget(lbl_etq)
        layout.addWidget(lbl_val)
        return chip

    def _make_ficha(self) -> QWidget:
        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(10)

        titulo_row = QHBoxLayout()
        titulo_row.setSpacing(6)
        icono_titulo = QLabel()
        icono_titulo.setPixmap(qta.icon("fa5s.info-circle", color=COLOR_PRIMARY).pixmap(QSize(12, 12)))
        titulo = QLabel("DATOS DE LA ORDEN")
        titulo.setProperty("class", "SectionTitle")
        titulo_row.addWidget(icono_titulo)
        titulo_row.addWidget(titulo)
        titulo_row.addStretch()
        layout.addLayout(titulo_row)

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        proveedor = self.oc.proveedor.nombre_razon_social if self.oc.proveedor else "—"
        fecha = self.oc.fecha_oc.strftime("%d/%m/%Y %H:%M") if self.oc.fecha_oc else "—"
        fecha_entrega = (
            self.oc.fecha_estimada_entrega.strftime("%d/%m/%Y") if self.oc.fecha_estimada_entrega else "Sin definir"
        )
        creador = self.oc.usuario_creador.nombre_usuario if self.oc.usuario_creador else "—"

        campos = [
            ("N° ODC", self.oc.numero_oc),
            ("Proveedor", proveedor),
            ("Fecha de emisión", fecha),
            ("Fecha estimada entrega", fecha_entrega),
            ("Total Productos", f"{float(self.oc.cantidad_solicitada):,.2f}"),
            ("Cant. recibida", f"{float(self.oc.cantidad_recibida):,.2f}"),
            ("Total", f"${float(self.oc.total_oc):,.2f}"),
            ("Creado por", creador),
            ("Observaciones", self.oc.observaciones or "—"),
        ]
        for i, (etiqueta, valor) in enumerate(campos):
            fila, columna = divmod(i, 3)
            grid.addWidget(self._campo_chip(etiqueta, valor), fila, columna)

        layout.addLayout(grid)
        return card

    def _make_tabla_items(self) -> QTableWidget:
        columnas = ["Producto", "Cantidad Producto", "Cantidad Pendiente", "Precio Unitario", "Total"]
        tabla = QTableWidget(len(self.detalles), len(columnas))
        tabla.setHorizontalHeaderLabels(columnas)
        alinear_encabezados(
            tabla,
            {
                0: Qt.AlignmentFlag.AlignLeft,
                1: Qt.AlignmentFlag.AlignRight,
                2: Qt.AlignmentFlag.AlignRight,
                3: Qt.AlignmentFlag.AlignRight,
                4: Qt.AlignmentFlag.AlignRight,
            },
        )
        tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabla.setAlternatingRowColors(True)
        tabla.setShowGrid(False)
        tabla.verticalHeader().setVisible(False)
        tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(tabla)

        for fila, detalle in enumerate(self.detalles):
            nombre = detalle.producto.nombre_producto if detalle.producto else "Producto eliminado"
            cantidad_solicitada = float(detalle.cantidad_solicitada)
            cantidad_pendiente = float(detalle.cantidad_pendiente)
            precio = float(detalle.precio_unitario)
            total = cantidad_solicitada * precio

            item_nombre = QTableWidgetItem(nombre)
            tabla.setItem(fila, 0, item_nombre)
            item_cant_sol = QTableWidgetItem(f"{cantidad_solicitada:,.2f}")
            item_cant_sol.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tabla.setItem(fila, 1, item_cant_sol)
            item_cant_pen = QTableWidgetItem(f"{cantidad_pendiente:,.2f}")
            item_cant_pen.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tabla.setItem(fila, 2, item_cant_pen)
            item_precio = QTableWidgetItem(f"${precio:,.2f}")
            item_precio.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tabla.setItem(fila, 3, item_precio)
            item_total = QTableWidgetItem(f"${total:,.2f}")
            item_total.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tabla.setItem(fila, 4, item_total)

        return tabla

    def _make_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 4, 0, 0)
        footer.setSpacing(10)

        col_totales = QVBoxLayout()
        col_totales.setSpacing(1)
        lbl_total = QLabel(f"Total de la orden: ${float(self.oc.total_oc):,.2f}")
        lbl_total.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        col_totales.addWidget(lbl_total)

        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setIcon(qta.icon("fa5s.times", color="#475569"))
        btn_cerrar.setObjectName("BtnSecondary")
        btn_cerrar.setFixedHeight(36)
        btn_cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cerrar.setAutoDefault(False)
        btn_cerrar.clicked.connect(self.accept)

        footer.addLayout(col_totales)
        footer.addStretch()
        footer.addWidget(btn_cerrar)
        return footer
