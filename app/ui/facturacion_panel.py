"""
Panel completo del módulo Facturación / Ventas.
Mismo patrón visual y de interacción que app/ui/clientes_panel.py e
app/ui/inventario_panel.py (paleta y tipografía de app/ui/styles.py): barra de
herramientas, tabla estilizada, paginación (ya provista por
VentaService.listar_facturas()) y exportación a Excel (R-10).
"""

import logging

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.db.models import FacturaVenta, Usuario
from app.services.exportacion import exportar_excel
from app.services.ventas import VentaService
from app.ui.factura_detalle_dialog import FacturaDetalleDialog
from app.ui.factura_form_dialog import FacturaFormDialog
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    COLORES_ESTADO_FACTURA,
    SEARCH_QSS,
    TABLE_QSS,
    color_con_alpha,
)

logger = logging.getLogger(__name__)

COLS_VISIBLES = ["ID", "N° Factura", "Cliente", "Fecha", "Condición", "Total", "Estado"]
COL_ID_INTERNO = 0  # oculto
POR_PAGINA = 20

ESTADOS_FILTRO = [
    ("Todos los estados", None),
    ("Emitida", "EMITIDA"),
    ("Pagada", "PAGADA"),
    ("Parcial", "PARCIAL"),
    ("Vencida", "VENCIDA"),
    ("Anulada", "ANULADA"),
]
CONDICIONES_FILTRO = [
    ("Contado y crédito", None),
    ("Contado", "contado"),
    ("Crédito", "credito"),
]


class EstadoFacturaBadge(QWidget):
    """Badge de color por estado de factura (EMITIDA/PAGADA/PARCIAL/VENCIDA/ANULADA),
    mismo criterio visual que BadgeItem en clientes_panel.py/inventario_panel.py pero
    con mas de 2 estados posibles -- ver COLORES_ESTADO_FACTURA en app/ui/styles.py."""

    def __init__(self, estado: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        color = COLORES_ESTADO_FACTURA.get(estado, COLOR_TEXT_MUTED)
        lbl = QLabel(estado.capitalize())
        lbl.setStyleSheet(
            f"background-color: {color_con_alpha(color)}; color: {color}; border-radius: 10px;"
            " padding: 2px 10px; font-size: 11px; font-weight: bold;"
        )
        layout.addWidget(lbl)


class FacturacionPanel(QWidget):
    """Panel principal del módulo Facturación: listado de facturas con búsqueda por
    número, filtro por estado/condición de pago, paginación, emisión de nuevas
    facturas (carrito), ver detalle y anulación."""

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.pagina_actual = 1
        self.total_paginas = 1
        self.setObjectName("ContentArea")
        self._setup_ui()
        QTimer.singleShot(100, self.cargar_facturas)

    # ── Construcción de la UI ─────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        root.addWidget(self._make_header())
        root.addWidget(self._make_toolbar())
        root.addWidget(self._make_table())
        root.addWidget(self._make_footer())

        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

    def _make_header(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("Facturación de Ventas")
        lbl.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        self.lbl_total = QLabel("Cargando…")
        self.lbl_total.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 13px;"
            f" background-color: {COLOR_TABLE_HEADER}; border-radius: 10px;"
            " padding: 3px 10px;"
        )

        h.addWidget(lbl)
        h.addWidget(self.lbl_total)
        h.addStretch()
        return w

    def _make_toolbar(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(
            f"background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 8px; padding: 4px;"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)

        self.buscar_input = QLineEdit()
        self.buscar_input.setPlaceholderText("Buscar por N° de factura…")
        self.buscar_input.addAction(qta.icon("fa5s.search", color="#94A3B8"), QLineEdit.ActionPosition.LeadingPosition)
        self.buscar_input.setObjectName("SearchInput")
        self.buscar_input.setStyleSheet(SEARCH_QSS)
        self.buscar_input.setFixedWidth(200)
        self.buscar_input.returnPressed.connect(self._buscar_desde_inicio)
        self.buscar_input.textChanged.connect(self._busqueda_dinamica)

        self.estado_combo = QComboBox()
        self.estado_combo.setFixedHeight(34)
        for etiqueta, valor in ESTADOS_FILTRO:
            self.estado_combo.addItem(etiqueta, valor)
        self.estado_combo.currentIndexChanged.connect(self._buscar_desde_inicio)

        self.condicion_combo = QComboBox()
        self.condicion_combo.setFixedHeight(34)
        for etiqueta, valor in CONDICIONES_FILTRO:
            self.condicion_combo.addItem(etiqueta, valor)
        self.condicion_combo.currentIndexChanged.connect(self._buscar_desde_inicio)

        self.btn_nueva_factura = QPushButton("Nueva Factura")
        self.btn_nueva_factura.setIcon(qta.icon("fa5s.plus", color="white"))
        self.btn_nueva_factura.setStyleSheet(BUTTON_PRIMARY_QSS)
        self.btn_nueva_factura.clicked.connect(self.nueva_factura)

        btn_exportar = QPushButton("Exportar")
        btn_exportar.setIcon(qta.icon("fa5s.file-export", color=COLOR_TEXT_DARK))
        btn_exportar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_exportar.clicked.connect(self.exportar_facturas)

        h.addWidget(self.buscar_input)
        h.addWidget(self.estado_combo)
        h.addWidget(self.condicion_combo)
        h.addSpacerItem(QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        h.addWidget(self.btn_nueva_factura)
        h.addWidget(btn_exportar)
        return w

    def _make_table(self) -> QTableWidget:
        self.tabla = QTableWidget(0, len(COLS_VISIBLES))
        self.tabla.setHorizontalHeaderLabels(COLS_VISIBLES)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setShowGrid(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.tabla.setColumnWidth(6, 110)
        self.tabla.setStyleSheet(
            TABLE_QSS
            + """
            QTableWidget { alternate-background-color: #F8FAFC; }
        """
        )
        self.tabla.setColumnHidden(COL_ID_INTERNO, True)
        self.tabla.verticalHeader().setDefaultSectionSize(48)
        self.tabla.doubleClicked.connect(self.ver_detalle_factura)
        return self.tabla

    def _make_footer(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        self.lbl_pagina = QLabel("Página 1")
        self.lbl_pagina.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")

        self.btn_anterior = QPushButton()
        self.btn_anterior.setIcon(qta.icon("fa5s.chevron-left", color=COLOR_TEXT_DARK))
        self.btn_anterior.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_anterior.setFixedWidth(40)
        self.btn_anterior.clicked.connect(self._pagina_anterior)

        self.btn_siguiente = QPushButton()
        self.btn_siguiente.setIcon(qta.icon("fa5s.chevron-right", color=COLOR_TEXT_DARK))
        self.btn_siguiente.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_siguiente.setFixedWidth(40)
        self.btn_siguiente.clicked.connect(self._pagina_siguiente)

        btn_detalle = QPushButton("Ver detalle")
        btn_detalle.setIcon(qta.icon("fa5s.eye", color=COLOR_TEXT_DARK))
        btn_detalle.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_detalle.clicked.connect(self.ver_detalle_factura)

        btn_anular = QPushButton("Anular factura")
        btn_anular.setIcon(qta.icon("fa5s.ban", color=COLOR_TEXT_DARK))
        btn_anular.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_anular.clicked.connect(self.anular_factura_seleccionada)

        h.addWidget(self.lbl_pagina)
        h.addWidget(self.btn_anterior)
        h.addWidget(self.btn_siguiente)
        h.addStretch()
        h.addWidget(btn_detalle)
        h.addWidget(btn_anular)
        return w

    # ── Timer para búsqueda dinámica (300 ms debounce) ────────────────────

    def _busqueda_dinamica(self) -> None:
        if not hasattr(self, "_timer_busqueda"):
            self._timer_busqueda = QTimer()
            self._timer_busqueda.setSingleShot(True)
            self._timer_busqueda.timeout.connect(self._buscar_desde_inicio)
        self._timer_busqueda.start(300)

    def _buscar_desde_inicio(self) -> None:
        self.pagina_actual = 1
        self.cargar_facturas()

    def _pagina_anterior(self) -> None:
        if self.pagina_actual > 1:
            self.pagina_actual -= 1
            self.cargar_facturas()

    def _pagina_siguiente(self) -> None:
        if self.pagina_actual < self.total_paginas:
            self.pagina_actual += 1
            self.cargar_facturas()

    # ── Lógica de datos ───────────────────────────────────────────────────

    def cargar_facturas(self) -> None:
        session = self.session_factory()
        try:
            resultado = VentaService.listar_facturas(
                session,
                numero_factura=self.buscar_input.text().strip() or None,
                estado=self.estado_combo.currentData(),
                condicion_pago=self.condicion_combo.currentData(),
                pagina=self.pagina_actual,
                por_pagina=POR_PAGINA,
                id_usuario=self.usuario.id_usuario,
            )
            self._poblar_tabla(resultado)
        except Exception:
            logger.exception("Fallo al cargar el listado de facturas")
            QMessageBox.critical(self, "Error de conexión", "No se pudo cargar el listado de facturas.")
        finally:
            session.close()

    def _poblar_tabla(self, resultado: dict) -> None:
        facturas: list[FacturaVenta] = resultado["items"]
        self.tabla.setRowCount(len(facturas))
        for fila, f in enumerate(facturas):
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(f.id_factura)))
            self.tabla.setItem(fila, 1, QTableWidgetItem(f.numero_factura))
            self.tabla.setItem(fila, 2, QTableWidgetItem(f.cliente.nombre_razon_social if f.cliente else ""))

            fecha = f.fecha_emision.strftime("%d/%m/%Y") if f.fecha_emision else ""
            self.tabla.setItem(fila, 3, QTableWidgetItem(fecha))

            condicion = "Contado" if f.condicion_pago == "contado" else "Crédito"
            self.tabla.setItem(fila, 4, QTableWidgetItem(condicion))

            item_total = QTableWidgetItem(f"${float(f.total_venta):,.2f}")
            item_total.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 5, item_total)

            badge = EstadoFacturaBadge(f.estado_factura or "EMITIDA")
            self.tabla.setCellWidget(fila, 6, badge)

        total = resultado["total"]
        self.total_paginas = max(1, -(-total // POR_PAGINA))  # ceil sin importar math
        self.pagina_actual = min(self.pagina_actual, self.total_paginas)

        self.lbl_total.setText(f"{total} factura{'s' if total != 1 else ''}")
        self.lbl_pagina.setText(f"Página {self.pagina_actual} de {self.total_paginas}")
        self.btn_anterior.setEnabled(self.pagina_actual > 1)
        self.btn_siguiente.setEnabled(self.pagina_actual < self.total_paginas)

    def _fila_seleccionada_id(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            QMessageBox.information(self, "Selección requerida", "Selecciona una factura de la lista.")
            return None
        return int(self.tabla.item(filas[0].row(), 0).text())

    def nueva_factura(self) -> None:
        session = self.session_factory()
        try:
            dialogo = FacturaFormDialog(session, self.usuario.id_usuario, parent=self)
            if dialogo.exec():
                datos = dialogo.get_data()
                factura = VentaService.emitir_factura(session, id_usuario=self.usuario.id_usuario, **datos)
                self.cargar_facturas()
                QMessageBox.information(self, "Factura emitida", f"Factura {factura.numero_factura} emitida con éxito.")
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "No se pudo emitir la factura", str(exc))
        except Exception:
            session.rollback()
            logger.exception("Fallo al emitir factura")
            QMessageBox.critical(self, "Error", "No se pudo emitir la factura.")
        finally:
            session.close()

    def ver_detalle_factura(self) -> None:
        id_factura = self._fila_seleccionada_id()
        if id_factura is None:
            return

        session = self.session_factory()
        try:
            datos = VentaService.obtener_factura(session, id_factura, id_usuario=self.usuario.id_usuario)
            dialogo = FacturaDetalleDialog(datos, parent=self)
            dialogo.exec()
        except ValueError as exc:
            QMessageBox.warning(self, "No se pudo abrir la factura", str(exc))
        except Exception:
            logger.exception("Fallo al cargar el detalle de la factura %s", id_factura)
            QMessageBox.critical(self, "Error", "No se pudo cargar el detalle de la factura.")
        finally:
            session.close()

    def anular_factura_seleccionada(self) -> None:
        id_factura = self._fila_seleccionada_id()
        if id_factura is None:
            return

        motivo, ok = QInputDialog.getText(self, "Anular factura", "Motivo de la anulación:")
        motivo = motivo.strip()
        if not ok or not motivo:
            return

        respuesta = QMessageBox.question(
            self, "Confirmar", "¿Anular esta factura? Se repondrá el stock vendido y no se puede deshacer."
        )
        if respuesta != QMessageBox.StandardButton.Yes:
            return

        session = self.session_factory()
        try:
            VentaService.anular_factura(session, id_factura, id_usuario=self.usuario.id_usuario, motivo=motivo)
            self.cargar_facturas()
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "No se pudo anular la factura", str(exc))
        except Exception:
            session.rollback()
            logger.exception("Fallo al anular la factura %s", id_factura)
            QMessageBox.critical(self, "Error", "No se pudo anular la factura.")
        finally:
            session.close()

    def exportar_facturas(self) -> None:
        # R-09: se pide el destino ANTES de generar el archivo -- se escribe directo ahi,
        # nunca a un temporal.
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar facturas", "facturas.xlsx", "Excel (*.xlsx)")
        if not ruta:
            return

        session = self.session_factory()
        try:
            resultado = VentaService.listar_facturas(
                session,
                numero_factura=self.buscar_input.text().strip() or None,
                estado=self.estado_combo.currentData(),
                condicion_pago=self.condicion_combo.currentData(),
                pagina=1,
                por_pagina=1_000_000,
                id_usuario=self.usuario.id_usuario,
            )
            filas = [
                [
                    f.id_factura,
                    f.numero_factura,
                    f.cliente.nombre_razon_social if f.cliente else None,
                    f.fecha_emision.strftime("%d/%m/%Y") if f.fecha_emision else None,
                    "Contado" if f.condicion_pago == "contado" else "Crédito",
                    float(f.total_venta),
                    f.estado_factura,
                ]
                for f in resultado["items"]
            ]
            exportar_excel(ruta, COLS_VISIBLES, filas)
            QMessageBox.information(self, "Exportación completa", f"Se exportaron {len(filas)} facturas a:\n{ruta}")
        except Exception:
            logger.exception("Fallo al exportar el listado de facturas")
            QMessageBox.critical(self, "Error", "No se pudo exportar el listado de facturas.")
        finally:
            session.close()
