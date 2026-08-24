"""Dialogo de solo lectura para ver el detalle completo de una factura ya emitida
(cabecera + lineas). Mismo patron visual que cliente_form_dialog.py/
producto_form_dialog.py (paleta y tipografia de app/ui/styles.py)."""

import logging

import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.empresa import EmpresaService
from app.ui.factura_pdf import generar_pdf_factura
from app.ui.styles import (
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_PRIMARY,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    COLORES_ESTADO_FACTURA,
    FONT_FAMILY,
    TABLE_QSS,
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
QLabel.FormLabel {{
    font-size: 11px;
    font-weight: 600;
    color: #64748B;
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
    background-color: #F1F5F9;
    color: #475569;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#BtnSecondary:hover {{
    background-color: #E2E8F0;
    color: {COLOR_TEXT_DARK};
}}
QPushButton#BtnImprimir {{
    background-color: #EFF6FF;
    color: {COLOR_PRIMARY};
    border: 1px solid #BFDBFE;
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: bold;
}}
QPushButton#BtnImprimir:hover {{
    background-color: #DBEAFE;
}}
"""

logger = logging.getLogger(__name__)


class FacturaDetalleDialog(QDialog):
    """Vista de solo lectura de una factura: cabecera + lineas. `datos` es el dict
    devuelto por `VentaService.obtener_factura()` ({"factura": FacturaVenta,
    "detalles": [FacturaDetalle, ...]}). `session`/`id_usuario` se usan solo para poder
    exportar la factura digital a PDF (necesita los datos de la empresa, ver
    EmpresaService.obtener_configuracion)."""

    def __init__(self, datos: dict, session, id_usuario: int | None, parent=None):
        super().__init__(parent)
        self.datos = datos
        self.factura = datos["factura"]
        self.detalles = datos["detalles"]
        self.session = session
        self.id_usuario = id_usuario
        self.setWindowTitle(f"Factura {self.factura.numero_factura}")
        self.setFixedSize(720, 560)
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
        icon_lbl.setPixmap(qta.icon("fa5s.file-invoice", color=COLOR_PRIMARY).pixmap(QSize(22, 22)))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(38, 38)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titulos = QVBoxLayout()
        titulos.setSpacing(1)
        titulos.setContentsMargins(0, 0, 0, 0)

        lbl_titulo = QLabel(f"Factura {self.factura.numero_factura}")
        lbl_titulo.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        lbl_subtitulo = QLabel("Detalle de la venta")
        lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        titulos.addWidget(lbl_titulo)
        titulos.addWidget(lbl_subtitulo)

        h.addWidget(icon_lbl)
        h.addLayout(titulos)
        h.addStretch()

        estado = self.factura.estado_factura or "EMITIDA"
        color_estado = COLORES_ESTADO_FACTURA.get(estado, COLOR_TEXT_MUTED)
        badge = QLabel(estado.capitalize())
        badge.setStyleSheet(
            f"background-color: {color_con_alpha(color_estado)}; color: {color_estado}; border-radius: 6px;"
            " padding: 4px 12px; font-size: 12px; font-weight: bold;"
        )
        h.addWidget(badge)
        return w

    def _make_ficha(self) -> QWidget:
        card = QWidget()
        card.setObjectName("SectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        titulo = QLabel("DATOS DE LA FACTURA")
        titulo.setProperty("class", "SectionTitle")
        layout.addWidget(titulo)

        grid = QGridLayout()
        grid.setSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        cliente = self.factura.cliente
        vendedor = self.factura.vendedor
        fecha = self.factura.fecha_emision.strftime("%d/%m/%Y %H:%M") if self.factura.fecha_emision else "—"
        vencimiento = (
            self.factura.fecha_vencimiento.strftime("%d/%m/%Y") if self.factura.fecha_vencimiento else "Sin definir"
        )
        condicion = "Contado" if self.factura.condicion_pago == "contado" else "Crédito"
        tasa = self.factura.tasa
        tasa_texto = f"{float(tasa.tasa_dolar_bcv):,.2f} Bs/USD" if tasa else "—"

        campos = [
            ("N° de Control", self.factura.numero_control),
            ("Cliente", cliente.nombre_razon_social if cliente else "—"),
            ("Fecha de emisión", fecha),
            ("Condición de pago", condicion),
            ("Vendedor", vendedor.nombre_vendedor if vendedor else "Sin vendedor"),
            ("Vencimiento", vencimiento if self.factura.condicion_pago == "credito" else "N/A"),
            ("Tasa BCV aplicada", tasa_texto),
            ("Observaciones", self.factura.observaciones_factura or "—"),
        ]
        for i, (etiqueta, valor) in enumerate(campos):
            fila, columna = divmod(i, 3)
            bloque = QVBoxLayout()
            bloque.setSpacing(1)
            lbl_etq = QLabel(etiqueta)
            lbl_etq.setProperty("class", "FormLabel")
            lbl_val = QLabel(str(valor))
            lbl_val.setProperty("class", "FormValue")
            lbl_val.setWordWrap(True)
            bloque.addWidget(lbl_etq)
            bloque.addWidget(lbl_val)
            grid.addLayout(bloque, fila, columna)

        layout.addLayout(grid)
        return card

    def _make_tabla_items(self) -> QTableWidget:
        columnas = ["Producto", "Cantidad", "Precio Unitario", "Subtotal"]
        tabla = QTableWidget(len(self.detalles), len(columnas))
        tabla.setHorizontalHeaderLabels(columnas)
        tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabla.setAlternatingRowColors(True)
        tabla.setShowGrid(False)
        tabla.verticalHeader().setVisible(False)
        tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tabla.setStyleSheet(TABLE_QSS)

        for fila, detalle in enumerate(self.detalles):
            nombre = detalle.producto.nombre_producto if detalle.producto else "Producto eliminado"
            cantidad = float(detalle.cantidad_producto)
            precio = float(detalle.precio_unitario)
            subtotal = cantidad * precio

            item_nombre = QTableWidgetItem(nombre)
            if detalle.observaciones_item:
                item_nombre.setToolTip(detalle.observaciones_item)
            tabla.setItem(fila, 0, item_nombre)
            item_cant = QTableWidgetItem(f"{cantidad:,.2f}")
            item_cant.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tabla.setItem(fila, 1, item_cant)
            item_precio = QTableWidgetItem(f"${precio:,.2f}")
            item_precio.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tabla.setItem(fila, 2, item_precio)
            item_subtotal = QTableWidgetItem(f"${subtotal:,.2f}")
            item_subtotal.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tabla.setItem(fila, 3, item_subtotal)

        return tabla

    def _make_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 4, 0, 0)
        footer.setSpacing(10)

        total_a_pagar = (
            float(self.factura.total_venta)
            - float(self.factura.monto_descuento or 0)
            + float(self.factura.monto_iva or 0)
        )
        lbl_total = QLabel(f"Total a pagar: ${total_a_pagar:,.2f}")
        lbl_total.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        btn_exportar = QPushButton(" Exportar PDF")
        btn_exportar.setIcon(qta.icon("fa5s.file-pdf", color=COLOR_PRIMARY))
        btn_exportar.setObjectName("BtnImprimir")
        btn_exportar.setFixedHeight(36)
        btn_exportar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_exportar.clicked.connect(self.exportar_pdf)

        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setIcon(qta.icon("fa5s.times", color="#475569"))
        btn_cerrar.setObjectName("BtnSecondary")
        btn_cerrar.setFixedHeight(36)
        btn_cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cerrar.clicked.connect(self.accept)

        footer.addWidget(lbl_total)
        footer.addStretch()
        footer.addWidget(btn_exportar)
        footer.addWidget(btn_cerrar)
        return footer

    def exportar_pdf(self) -> None:
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Exportar factura", f"{self.factura.numero_factura}.pdf", "PDF (*.pdf)"
        )
        if not ruta:
            return

        try:
            config_empresa = EmpresaService.obtener_configuracion(self.session, id_usuario=self.id_usuario)
            generar_pdf_factura(self.datos, config_empresa, ruta)
            QMessageBox.information(self, "Exportación completa", f"Factura exportada a:\n{ruta}")
        except Exception:
            logger.exception("Fallo al exportar la factura %s a PDF", self.factura.numero_factura)
            QMessageBox.critical(self, "Error", "No se pudo exportar la factura a PDF.")
