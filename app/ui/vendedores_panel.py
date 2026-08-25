"""
Panel completo del módulo Vendedores.
Mismo patrón visual y de interacción que app/ui/clientes_panel.py (paleta y
tipografía de app/ui/styles.py): barra de herramientas, tabla estilizada,
alta/edición y activar/desactivar (nunca DELETE fisico, ver
VendedorService.eliminar).
"""

import logging

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
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

from app.db.models import Usuario, Vendedor
from app.services.vendedores import VendedorService
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    SEARCH_QSS,
    TABLE_QSS,
    alinear_encabezados,
    aplicar_sombra,
)
from app.ui.vendedor_form_dialog import VendedorFormDialog

logger = logging.getLogger(__name__)

COLS_VISIBLES = ["ID", "Nombre", "Código", "Identificación", "Teléfono", "Email", "Estado"]
COL_ID_INTERNO = 0  # oculto


class BadgeEstado(QWidget):
    """Mismo criterio visual que BadgeItem en clientes_panel.py."""

    def __init__(self, estado: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        activo = estado.upper() == "ACTIVO"
        bg_color = "#DCFCE7" if activo else "#FEF2F2"
        text_color = COLOR_SUCCESS if activo else COLOR_DANGER
        icon_name = "fa5s.check-circle" if activo else "fa5s.times-circle"

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon(icon_name, color=text_color).pixmap(12, 12))
        icon_lbl.setStyleSheet("background: transparent;")

        lbl = QLabel(estado.capitalize())
        lbl.setStyleSheet(f"background-color: transparent; color: {text_color}; font-size: 11px; font-weight: bold;")

        container = QWidget()
        container.setStyleSheet(f"background-color: {bg_color}; border-radius: 10px; padding: 2px 8px;")
        c_layout = QHBoxLayout(container)
        c_layout.setContentsMargins(6, 2, 6, 2)
        c_layout.setSpacing(4)
        c_layout.addWidget(icon_lbl)
        c_layout.addWidget(lbl)

        layout.addWidget(container)


class VendedoresPanel(QWidget):
    """Panel principal del módulo Vendedores: listado con búsqueda, alta/edición
    y activar/desactivar -- lo minimo necesario para poder emitir facturas
    (FacturaFormDialog exige un vendedor activo)."""

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.setObjectName("ContentArea")
        self._setup_ui()
        QTimer.singleShot(100, self.cargar_vendedores)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.cargar_vendedores()

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

        lbl = QLabel("Vendedores")
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
        self.buscar_input.setPlaceholderText("Buscar vendedor…")
        self.buscar_input.addAction(qta.icon("fa5s.search", color="#94A3B8"), QLineEdit.ActionPosition.LeadingPosition)
        self.buscar_input.setObjectName("SearchInput")
        self.buscar_input.setStyleSheet(SEARCH_QSS)
        self.buscar_input.setFixedWidth(220)
        self.buscar_input.returnPressed.connect(self.cargar_vendedores)
        self.buscar_input.textChanged.connect(self._busqueda_dinamica)

        self.btn_nuevo = QPushButton("Nuevo Vendedor")
        self.btn_nuevo.setIcon(qta.icon("fa5s.user-plus", color="white"))
        self.btn_nuevo.setStyleSheet(BUTTON_PRIMARY_QSS)
        self.btn_nuevo.clicked.connect(self.nuevo_vendedor)

        h.addWidget(self.buscar_input)
        h.addSpacerItem(QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        h.addWidget(self.btn_nuevo)
        return w

    def _make_table(self) -> QTableWidget:
        self.tabla = QTableWidget(0, len(COLS_VISIBLES))
        self.tabla.setHorizontalHeaderLabels(COLS_VISIBLES)
        alinear_encabezados(
            self.tabla,
            {
                1: Qt.AlignmentFlag.AlignLeft,
                2: Qt.AlignmentFlag.AlignLeft,
                3: Qt.AlignmentFlag.AlignLeft,
                4: Qt.AlignmentFlag.AlignLeft,
                5: Qt.AlignmentFlag.AlignLeft,
                6: Qt.AlignmentFlag.AlignCenter,
            },
        )
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
        self.tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(self.tabla)
        self.tabla.setColumnHidden(COL_ID_INTERNO, True)
        self.tabla.verticalHeader().setDefaultSectionSize(48)
        return self.tabla

    def _make_footer(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        self.lbl_pagina = QLabel("Mostrando todos los registros")
        self.lbl_pagina.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")

        btn_editar = QPushButton("Editar seleccionado")
        btn_editar.setIcon(qta.icon("fa5s.edit", color=COLOR_TEXT_DARK))
        btn_editar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_editar.clicked.connect(self.editar_vendedor)

        btn_estado = QPushButton("Cambiar estado")
        btn_estado.setIcon(qta.icon("fa5s.sync-alt", color=COLOR_TEXT_DARK))
        btn_estado.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_estado.clicked.connect(self.cambiar_estado_vendedor_seleccionado)

        h.addWidget(self.lbl_pagina)
        h.addStretch()
        h.addWidget(btn_editar)
        h.addWidget(btn_estado)
        return w

    # ── Timer para búsqueda dinámica (300 ms debounce) ────────────────────

    def _busqueda_dinamica(self) -> None:
        if not hasattr(self, "_timer_busqueda"):
            self._timer_busqueda = QTimer()
            self._timer_busqueda.setSingleShot(True)
            self._timer_busqueda.timeout.connect(self.cargar_vendedores)
        self._timer_busqueda.start(300)

    # ── Lógica de datos ───────────────────────────────────────────────────

    def cargar_vendedores(self) -> None:
        session = self.session_factory()
        try:
            vendedores = VendedorService.listar(
                session,
                self.buscar_input.text().strip() or None,
                id_usuario=self.usuario.id_usuario,
            )
            self._poblar_tabla(vendedores)
        except Exception:
            logger.exception("Fallo al cargar la lista de vendedores")
            QMessageBox.critical(self, "Error de conexión", "No se pudo cargar la lista de vendedores.")
        finally:
            session.close()

    def _poblar_tabla(self, vendedores: list[Vendedor]) -> None:
        self.tabla.setRowCount(len(vendedores))
        for fila, v in enumerate(vendedores):
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(v.id_vendedor)))
            self.tabla.setItem(fila, 1, QTableWidgetItem(v.nombre_vendedor or ""))
            self.tabla.setItem(fila, 2, QTableWidgetItem(v.codigo_vendedor or ""))
            self.tabla.setItem(fila, 3, QTableWidgetItem(v.identificacion_vendedor or ""))
            self.tabla.setItem(fila, 4, QTableWidgetItem(v.telefono_vendedor or ""))
            self.tabla.setItem(fila, 5, QTableWidgetItem(v.email_vendedor or ""))

            badge = BadgeEstado(v.estado_vendedor or "ACTIVO")
            self.tabla.setCellWidget(fila, 6, badge)

        total = len(vendedores)
        self.lbl_total.setText(f"{total} vendedor{'es' if total != 1 else ''}")
        self.lbl_pagina.setText(f"Mostrando {total} registro{'s' if total != 1 else ''}")

    def _fila_seleccionada_id(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            QMessageBox.information(self, "Selección requerida", "Selecciona un vendedor de la lista.")
            return None
        return int(self.tabla.item(filas[0].row(), 0).text())

    def nuevo_vendedor(self) -> None:
        session = self.session_factory()
        try:
            dialogo = VendedorFormDialog(parent=self)
            if dialogo.exec():
                datos = dialogo.get_data()
                datos["creado_por"] = self.usuario.id_usuario
                VendedorService.crear(session, **datos)
                self.cargar_vendedores()
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "Dato inválido", str(exc))
        except Exception:
            session.rollback()
            logger.exception("Fallo al crear vendedor")
            QMessageBox.critical(self, "Error", "No se pudo crear el vendedor.")
        finally:
            session.close()

    def editar_vendedor(self) -> None:
        id_vendedor = self._fila_seleccionada_id()
        if id_vendedor is None:
            return

        session = self.session_factory()
        try:
            vendedor = VendedorService.obtener(session, id_vendedor, id_usuario=self.usuario.id_usuario)
            dialogo = VendedorFormDialog(vendedor, parent=self)
            if dialogo.exec():
                VendedorService.actualizar(
                    session, id_vendedor, id_usuario=self.usuario.id_usuario, **dialogo.get_data()
                )
                self.cargar_vendedores()
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "Dato inválido", str(exc))
        except Exception:
            session.rollback()
            logger.exception("Fallo al editar vendedor")
            QMessageBox.critical(self, "Error", "No se pudo guardar los cambios del vendedor.")
        finally:
            session.close()

    def cambiar_estado_vendedor_seleccionado(self) -> None:
        id_vendedor = self._fila_seleccionada_id()
        if id_vendedor is None:
            return

        session = self.session_factory()
        try:
            vendedor = VendedorService.obtener(session, id_vendedor, id_usuario=self.usuario.id_usuario)
            estado_actual = vendedor.estado_vendedor or "ACTIVO"
            nuevo_estado = "INACTIVO" if estado_actual == "ACTIVO" else "ACTIVO"

            respuesta = QMessageBox.question(
                self, "Confirmar", f"¿Cambiar el estado del vendedor '{vendedor.nombre_vendedor}' a {nuevo_estado}?"
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return

            VendedorService.cambiar_estado(session, id_vendedor, nuevo_estado, id_usuario=self.usuario.id_usuario)
            self.cargar_vendedores()
        except Exception:
            session.rollback()
            logger.exception("Fallo al cambiar el estado del vendedor %s", id_vendedor)
            QMessageBox.critical(self, "Error", "No se pudo cambiar el estado del vendedor.")
        finally:
            session.close()
