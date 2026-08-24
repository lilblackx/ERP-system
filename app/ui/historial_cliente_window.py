"""Ventana para mostrar el historial de facturas y pagos de un cliente."""

import logging

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
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

from app.db.models import Cliente
from app.services.exportacion import exportar_excel, exportar_pdf
from app.services.historial_cliente import (
    obtener_historial_cliente,
    obtener_saldo_total_pendiente,
)
from app.ui.styles import (
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_DANGER,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_TEXT_DARK,
    TABLE_QSS,
)

logger = logging.getLogger(__name__)

# Columnas de la tabla de historial
COLS_HISTORIAL = [
    "ID Cuenta",
    "N° Factura",
    "Fecha Emisión",
    "Total Venta",
    "Estado Factura",
    "Condición Pago",
    "Días Crédito",
    "Observaciones",
    "Pagos",
    "Saldo Pendiente",
]


class HistorialClienteWindow(QDialog):
    """Ventana que muestra el historial de facturas y pagos de un cliente."""

    def __init__(self, session_factory, id_cliente: int, cliente: Cliente, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.id_cliente = id_cliente
        self.cliente = cliente
        self.setWindowTitle(f"Historial - {cliente.nombre_razon_social}")
        self.setMinimumSize(1400, 700)
        self._setup_ui()
        self.cargar_historial()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # Header con información del cliente
        root.addWidget(self._make_header())

        # Resumen de saldo pendiente
        root.addWidget(self._make_saldo_pendiente())

        # Tabla de historial
        root.addWidget(self._make_table())

        # Footer con botón cerrar
        root.addWidget(self._make_footer())

        self.setStyleSheet(f"background-color: {COLOR_PRIMARY};")

    def _make_header(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        lbl_titulo = QLabel("HISTORIAL DEL CLIENTE : ")
        lbl_titulo.setStyleSheet("font-size: 22px; font-weight: bold; color: white;")

        lbl_cliente = QLabel(self.cliente.nombre_razon_social or "")
        lbl_cliente.setStyleSheet(
            "color: white; font-size: 16px; font-weight: 600; font-family: 'Segoe UI', Arial, sans-serif;"
        )

        h.addWidget(lbl_titulo)
        h.addWidget(lbl_cliente)
        h.addStretch()
        return w

    def _make_saldo_pendiente(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(
            f"background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 8px; padding: 12px;"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(16, 12, 16, 12)

        lbl_icono = QLabel()
        lbl_icono.setPixmap(qta.icon("fa5s.wallet", color=COLOR_PRIMARY).pixmap(24, 24))
        lbl_icono.setStyleSheet("background: transparent;")

        self.lbl_saldo_pendiente = QLabel("Cargando saldo...")
        self.lbl_saldo_pendiente.setStyleSheet(f"color: {COLOR_TEXT_DARK}; font-size: 16px; font-weight: bold;")

        h.addWidget(lbl_icono)
        h.addWidget(self.lbl_saldo_pendiente)
        h.addStretch()
        return w

    def _make_table(self) -> QTableWidget:
        self.tabla = QTableWidget(0, len(COLS_HISTORIAL))
        self.tabla.setHorizontalHeaderLabels(COLS_HISTORIAL)
        self.tabla.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setShowGrid(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(9, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.setStyleSheet(TABLE_QSS)
        self.tabla.verticalHeader().setDefaultSectionSize(45)
        return self.tabla

    def _make_footer(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        h.addStretch()

        btn_exportar_excel = QPushButton("Exportar Excel")
        btn_exportar_excel.setIcon(qta.icon("fa5s.file-excel", color=COLOR_SUCCESS))
        btn_exportar_excel.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_exportar_excel.clicked.connect(self.exportar_excel)

        btn_exportar_pdf = QPushButton("Exportar PDF")
        btn_exportar_pdf.setIcon(qta.icon("fa5s.file-pdf", color=COLOR_DANGER))
        btn_exportar_pdf.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_exportar_pdf.clicked.connect(self.exportar_pdf)

        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setIcon(qta.icon("fa5s.times", color=COLOR_TEXT_DARK))
        btn_cerrar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_cerrar.clicked.connect(self.accept)

        h.addWidget(btn_exportar_excel)
        h.addWidget(btn_exportar_pdf)
        h.addWidget(btn_cerrar)
        return w

    def cargar_historial(self) -> None:
        session = self.session_factory()
        try:
            # Cargar historial
            historial = obtener_historial_cliente(session, self.id_cliente)
            self._poblar_tabla(historial)

            # Cargar saldo total pendiente
            saldo_total = obtener_saldo_total_pendiente(session, self.id_cliente)
            self.lbl_saldo_pendiente.setText(f"SALDO PENDIENTE : $ {float(saldo_total):,.2f}")

            # Color del saldo según si está vencido o no
            if saldo_total > 0:
                self.lbl_saldo_pendiente.setStyleSheet(f"color: {COLOR_DANGER}; font-size: 16px; font-weight: bold;")
            else:
                self.lbl_saldo_pendiente.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: 16px; font-weight: bold;")

        except Exception:
            logger.exception("Fallo al cargar el historial del cliente %s", self.id_cliente)
        finally:
            session.close()

    def _poblar_tabla(self, historial: list) -> None:
        self.tabla.setRowCount(len(historial))

        for fila, item in enumerate(historial):
            # ID Cuenta
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(item["id_cuenta"]) if item["id_cuenta"] else "N/A"))
            # N° Factura
            self.tabla.setItem(fila, 1, QTableWidgetItem(item["numero_factura"]))
            # Fecha Emisión
            self.tabla.setItem(fila, 2, QTableWidgetItem(item["fecha_emision"]))

            # Total Venta
            total_venta = f"${float(item['total_venta']):,.2f}"
            item_total = QTableWidgetItem(total_venta)
            item_total.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 3, item_total)

            # Estado Factura
            self.tabla.setItem(fila, 4, QTableWidgetItem(item["estado_factura"]))
            # Condición Pago
            self.tabla.setItem(fila, 5, QTableWidgetItem(item["condicion_pago"]))
            # Días Crédito
            dias = str(item["dias_credito"]) if item["dias_credito"] is not None else "0"
            item_dias = QTableWidgetItem(dias)
            item_dias.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 6, item_dias)
            # Observaciones
            self.tabla.setItem(fila, 7, QTableWidgetItem(item["observaciones_factura"] or ""))

            # Pagos (Abonos)
            pagado = f"${float(item['total_pagado']):,.2f}"
            item_pagado = QTableWidgetItem(pagado)
            item_pagado.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item_pagado.setData(Qt.ItemDataRole.ForegroundRole, QColor(COLOR_SUCCESS))
            font = item_pagado.font()
            font.setBold(True)
            item_pagado.setFont(font)
            self.tabla.setItem(fila, 8, item_pagado)

            # Saldo Pendiente
            saldo_pendiente = f"${float(item['saldo_pendiente']):,.2f}"
            item_saldo = QTableWidgetItem(saldo_pendiente)
            item_saldo.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if item["saldo_pendiente"] > 0:
                item_saldo.setData(Qt.ItemDataRole.ForegroundRole, QColor(COLOR_DANGER))
            else:
                item_saldo.setData(Qt.ItemDataRole.ForegroundRole, QColor(COLOR_SUCCESS))
            font = item_saldo.font()
            font.setBold(True)
            item_saldo.setFont(font)
            self.tabla.setItem(fila, 9, item_saldo)

    def exportar_excel(self) -> None:
        session = self.session_factory()
        try:
            historial = obtener_historial_cliente(session, self.id_cliente)

            # Preparar filas para exportación
            filas = [
                [
                    item["id_cuenta"] or "N/A",
                    item["numero_factura"],
                    item["fecha_emision"],
                    str(item["total_venta"]),
                    item["estado_factura"],
                    item["condicion_pago"],
                    str(item["dias_credito"] or 0),
                    item["observaciones_factura"] or "",
                    str(item["total_pagado"]),
                    str(item["saldo_pendiente"]),
                ]
                for item in historial
            ]

            nombre_archivo = f"historial_{self.cliente.nombre_razon_social or 'cliente'}"
            ruta, _ = QFileDialog.getSaveFileName(
                self, "Exportar Historial a Excel", f"{nombre_archivo}.xlsx", "Excel (*.xlsx)"
            )
            if not ruta:
                return

            exportar_excel(ruta, COLS_HISTORIAL, filas)
            QMessageBox.information(self, "Exportación completa", f"Se exportó el historial a:\n{ruta}")
        except Exception:
            logger.exception("Fallo al exportar historial a Excel")
            QMessageBox.critical(self, "Error", "No se pudo exportar el historial a Excel.")
        finally:
            session.close()

    def exportar_pdf(self) -> None:
        session = self.session_factory()
        try:
            historial = obtener_historial_cliente(session, self.id_cliente)

            # Preparar filas para exportación
            filas = [
                [
                    str(item["id_cuenta"] or "N/A"),
                    item["numero_factura"],
                    item["fecha_emision"],
                    str(item["total_venta"]),
                    item["estado_factura"],
                    item["condicion_pago"],
                    str(item["dias_credito"] or 0),
                    item["observaciones_factura"] or "",
                    str(item["total_pagado"]),
                    str(item["saldo_pendiente"]),
                ]
                for item in historial
            ]

            nombre_archivo = f"historial_{self.cliente.nombre_razon_social or 'cliente'}"
            ruta, _ = QFileDialog.getSaveFileName(
                self, "Exportar Historial a PDF", f"{nombre_archivo}.pdf", "PDF (*.pdf)"
            )
            if not ruta:
                return

            exportar_pdf(
                ruta,
                "Historial del Cliente",
                COLS_HISTORIAL,
                filas,
                cliente_nombre=self.cliente.nombre_razon_social,
            )
            QMessageBox.information(self, "Exportación completa", f"Se exportó el historial a:\n{ruta}")
        except Exception:
            logger.exception("Fallo al exportar historial a PDF")
            QMessageBox.critical(self, "Error", "No se pudo exportar el historial a PDF.")
        finally:
            session.close()
