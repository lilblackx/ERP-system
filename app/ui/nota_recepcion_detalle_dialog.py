"""Dialogo de solo lectura para ver el detalle completo de una nota de recepción
(cabecera + lineas). Mismo patron visual que orden_compra_detalle_dialog.py."""

import logging

from PySide6.QtCore import Qt
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
from sqlalchemy.orm import Session

from app.services.nota_recepcion import NotaRecepcionService
from app.services.permisos import PermisoDenegadoError
from app.ui.message_box import MessageBox
from app.ui.styles import (
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_PRIMARY,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MEDIUM,
    FONT_FAMILY,
    TABLE_QSS,
    alinear_encabezados,
    aplicar_sombra,
)

logger = logging.getLogger(__name__)

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
QLabel.FieldLabel {{
    font-size: 12px;
    font-weight: 600;
    color: {COLOR_TEXT_MEDIUM};
    margin-bottom: 2px;
}}
QLabel.FieldValue {{
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
}}
"""


class NotaRecepcionDetalleDialog(QDialog):
    """Dialogo de solo lectura para ver el detalle completo de una nota de recepcion."""

    def __init__(self, session: Session, id_nr: int, id_usuario: int | None = None, parent=None):
        super().__init__(parent)
        self.session = session
        self.id_nr = id_nr
        self.id_usuario = id_usuario
        self.nr = None
        self._load_data()
        self._build_ui()

    def _load_data(self) -> None:
        """Carga los datos de la nota de recepcion."""
        try:
            resultado = NotaRecepcionService.obtener_nota_recepcion(
                self.session, self.id_nr, id_usuario=self.id_usuario
            )
            self.nr = resultado["nota"]
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para ver detalles de recepciones.")
            self.reject()
        except Exception:
            logger.exception("Fallo al cargar nota de recepcion")
            MessageBox.critical(self, "Error", "No se pudo cargar la nota de recepcion.")
            self.reject()

    def _build_ui(self) -> None:
        if self.nr is None:
            return

        self.setWindowTitle(f"Detalle Recepción — {self.nr.numero_nr}")
        self.resize(900, 700)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # Header
        header = QWidget()
        header.setStyleSheet("background: transparent;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)

        lbl_titulo = QLabel(f"Detalle Recepción — {self.nr.numero_nr}")
        lbl_titulo.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        header_layout.addWidget(lbl_titulo)
        header_layout.addStretch()

        lbl_estado = QLabel(self.nr.estado.capitalize())
        lbl_estado.setStyleSheet(
            f"background-color: {COLOR_PRIMARY}; color: white; "
            f"font-size: 12px; font-weight: bold; padding: 4px 12px; border-radius: 12px;"
        )
        header_layout.addWidget(lbl_estado)

        root.addWidget(header)

        # Información de la recepción
        info_card = QWidget()
        info_card.setObjectName("SectionCard")
        aplicar_sombra(info_card)
        info_layout = QGridLayout(info_card)
        info_layout.setContentsMargins(16, 14, 16, 14)
        info_layout.setSpacing(12)

        row = 0
        info_layout.addWidget(QLabel("Orden de Compra:"), row, 0)
        info_layout.addWidget(QLabel(self.nr.oc.numero_oc if self.nr.oc else ""), row, 1)
        info_layout.addWidget(QLabel("Fecha Recepción:"), row, 2)
        fecha_str = self.nr.fecha_recepcion.strftime("%d/%m/%Y %H:%M") if self.nr.fecha_recepcion else ""
        info_layout.addWidget(QLabel(fecha_str), row, 3)

        row += 1
        info_layout.addWidget(QLabel("Proveedor:"), row, 0)
        proveedor = self.nr.oc.proveedor if self.nr.oc else None
        info_layout.addWidget(QLabel(proveedor.nombre_razon_social if proveedor else ""), row, 1)
        info_layout.addWidget(QLabel("Usuario:"), row, 2)
        usuario = self.nr.usuario_recepcion if self.nr.usuario_recepcion else None
        info_layout.addWidget(QLabel(usuario.nombre if usuario else ""), row, 3)

        if self.nr.observaciones:
            row += 1
            info_layout.addWidget(QLabel("Observaciones:"), row, 0)
            info_layout.addWidget(QLabel(self.nr.observaciones), row, 1, 1, 3)

        root.addWidget(info_card)

        # Tabla de detalles
        lbl_detalles = QLabel("Productos Recibidos")
        lbl_detalles.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        root.addWidget(lbl_detalles)

        self.tabla = self._crear_tabla_detalle()
        root.addWidget(self.tabla, stretch=1)

        # Footer
        footer = QHBoxLayout()
        footer.addStretch()
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setFixedHeight(34)
        btn_cerrar.clicked.connect(self.accept)
        footer.addWidget(btn_cerrar)
        root.addLayout(footer)

        self._poblar_tabla_detalle()

    def _crear_tabla_detalle(self) -> QTableWidget:
        columnas = ["Producto", "Cant. Solicitada", "Cant. Recibida", "Cant. Rechazada", "Precio Unitario", "Total"]
        tabla = QTableWidget(0, len(columnas))
        tabla.setHorizontalHeaderLabels(columnas)
        tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabla.setAlternatingRowColors(True)
        tabla.setShowGrid(False)
        tabla.verticalHeader().setVisible(False)
        tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(tabla)
        tabla.verticalHeader().setDefaultSectionSize(40)

        alinear_encabezados(
            tabla,
            {
                0: Qt.AlignmentFlag.AlignLeft,
                1: Qt.AlignmentFlag.AlignRight,
                2: Qt.AlignmentFlag.AlignRight,
                3: Qt.AlignmentFlag.AlignRight,
                4: Qt.AlignmentFlag.AlignRight,
                5: Qt.AlignmentFlag.AlignRight,
            },
        )

        return tabla

    def _poblar_tabla_detalle(self) -> None:
        if self.nr is None:
            return

        detalles = self.nr.detalles if self.nr.detalles else []
        self.tabla.setRowCount(len(detalles))

        for fila, detalle in enumerate(detalles):
            producto = detalle.producto if detalle.producto else None
            self.tabla.setItem(fila, 0, QTableWidgetItem(producto.nombre_producto if producto else ""))

            # Cantidad solicitada desde el detalle de la OC
            oc_detalle = detalle.oc_detalle if detalle.oc_detalle else None
            cantidad_solicitada = oc_detalle.cantidad_solicitada if oc_detalle else 0
            item_solicitada = QTableWidgetItem(f"{float(cantidad_solicitada):,.2f}")
            item_solicitada.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 1, item_solicitada)

            item_recibida = QTableWidgetItem(f"{float(detalle.cantidad_recibida):,.2f}")
            item_recibida.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 2, item_recibida)

            item_rechazada = QTableWidgetItem(f"{float(detalle.cantidad_rechazada):,.2f}")
            item_rechazada.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 3, item_rechazada)

            item_precio = QTableWidgetItem(f"${float(detalle.precio_unitario):,.4f}")
            item_precio.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 4, item_precio)

            item_total = QTableWidgetItem(f"${float(detalle.total_linea):,.2f}")
            item_total.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 5, item_total)
