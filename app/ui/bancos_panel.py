"""
Panel completo del módulo Bancos.
Incluye barra de herramientas, tabla estilizada con datos reales y acciones CRUD.
Diseño moderno integrado en el MainWindow (no como ventana flotante).
"""

import logging

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
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

from app.db.models import Banco, Usuario
from app.ui.banco_form_dialog import BancoFormDialog
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_SUCCESS,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MUTED,
    SEARCH_QSS,
    TABLE_QSS,
    EstadoBadge,
    alinear_encabezados,
)
from app.ui.toolbar_popups import BotonFiltros

logger = logging.getLogger(__name__)

# Columnas visibles en la tabla (índice oculto 0 = ID interno)
COLS_VISIBLES = ["ID", "Código", "Nombre", "Tipo", "RIF", "Teléfono", "Correo", "Estado"]
COL_ID_INTERNO = 0  # oculto
POR_PAGINA = 20

ESTADOS_FILTRO = [
    ("Todos los estados", None),
    ("Activos", "ACTIVO"),
    ("Inactivos", "INACTIVO"),
]

COLORES_ESTADO_BANCO = {
    "ACTIVO": COLOR_SUCCESS,
    "INACTIVO": COLOR_TEXT_MUTED,
}


class BancosPanel(QWidget):
    """
    Panel principal del módulo Bancos.
    Encapsula la barra de herramientas y la tabla de datos en un solo widget
    para ser insertado directamente en el área de contenido del MainWindow.
    """

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.pagina_actual = 1
        self.total_paginas = 1
        self.bancos = []
        self._search_timer = None
        self.setObjectName("ContentArea")
        self._setup_ui()
        # Cargar bancos inmediatamente
        self.cargar_bancos()

    def showEvent(self, event: QShowEvent) -> None:
        # MainWindow cachea el panel y lo reutiliza via QStackedWidget
        super().showEvent(event)
        self.cargar_bancos()

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

        lbl = QLabel("LISTA DE BANCOS")
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

        # Barra de búsqueda
        self.buscar_input = QLineEdit()
        self.buscar_input.setPlaceholderText("Buscar por código, nombre, RIF o teléfono…")
        self.buscar_input.addAction(
            qta.icon("fa5s.search", color=COLOR_TEXT_LIGHT), QLineEdit.ActionPosition.LeadingPosition
        )
        self.buscar_input.setObjectName("SearchInput")
        self.buscar_input.setStyleSheet(SEARCH_QSS)
        self.buscar_input.setFixedWidth(320)
        self.buscar_input.returnPressed.connect(self._buscar_desde_inicio)
        self.buscar_input.textChanged.connect(self._busqueda_dinamica)

        # Botón nuevo banco
        self.btn_nuevo = QPushButton("Nuevo Banco")
        self.btn_nuevo.setIcon(qta.icon("fa5s.plus", color="white"))
        self.btn_nuevo.setStyleSheet(BUTTON_PRIMARY_QSS)
        self.btn_nuevo.clicked.connect(self.nuevo_banco)

        # Filtro de estado
        self.estado_combo = QComboBox()
        for etiqueta, valor in ESTADOS_FILTRO:
            self.estado_combo.addItem(etiqueta, valor)
        self.estado_combo.currentIndexChanged.connect(self._buscar_desde_inicio)

        self.btn_filtrar = BotonFiltros([("Estado", self.estado_combo)])

        h.addWidget(self.buscar_input)
        h.addSpacerItem(QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        h.addWidget(self.btn_nuevo)
        h.addWidget(self.btn_filtrar)
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
                6: Qt.AlignmentFlag.AlignLeft,
                7: Qt.AlignmentFlag.AlignCenter,
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
        self.tabla.setStyleSheet(TABLE_QSS)
        self.tabla.doubleClicked.connect(self.editar_banco)
        self.tabla.itemSelectionChanged.connect(self._on_selection_changed)
        return self.tabla

    def _make_footer(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        self.lbl_paginacion = QLabel("Página 1 de 1")
        self.lbl_paginacion.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 13px;")

        self.btn_editar = QPushButton("Editar")
        self.btn_editar.setIcon(qta.icon("fa5s.edit", color=COLOR_TEXT_LIGHT))
        self.btn_editar.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_editar.setEnabled(False)
        self.btn_editar.clicked.connect(self.editar_banco)

        self.btn_eliminar = QPushButton("Eliminar")
        self.btn_eliminar.setIcon(qta.icon("fa5s.trash", color=COLOR_TEXT_LIGHT))
        self.btn_eliminar.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_eliminar.setEnabled(False)
        self.btn_eliminar.clicked.connect(self.eliminar_banco)

        self.btn_anterior = QPushButton("Anterior")
        self.btn_anterior.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_anterior.setEnabled(False)
        self.btn_anterior.clicked.connect(self.pagina_anterior)

        self.btn_siguiente = QPushButton("Siguiente")
        self.btn_siguiente.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_siguiente.setEnabled(False)
        self.btn_siguiente.clicked.connect(self.pagina_siguiente)

        h.addWidget(self.lbl_paginacion)
        h.addStretch()
        h.addWidget(self.btn_editar)
        h.addWidget(self.btn_eliminar)
        h.addWidget(self.btn_anterior)
        h.addWidget(self.btn_siguiente)
        return w

    # ── Carga de datos ─────────────────────────────────────────────────────

    def cargar_bancos(self):
        """Carga la lista de bancos desde la base de datos."""
        session = self.session_factory()
        try:
            # Primero cargar todos los bancos sin filtros para depuración
            query = session.query(Banco)

            # Filtro de estado
            estado_filtro = self.estado_combo.currentData()
            logger.info(f"Filtro de estado: {estado_filtro}")
            if estado_filtro:
                query = query.filter(Banco.estado_banco == estado_filtro)

            # Filtro de búsqueda
            busqueda = self.buscar_input.text().strip()
            logger.info(f"Búsqueda: '{busqueda}'")
            if busqueda:
                like_pattern = f"%{busqueda}%"
                query = query.filter(
                    (Banco.codigo_banco.ilike(like_pattern))
                    | (Banco.nombre_banco.ilike(like_pattern))
                    | (Banco.identificacion_banco.ilike(like_pattern))
                    | (Banco.numero_telefono_banco.ilike(like_pattern))
                )

            self.bancos = query.order_by(Banco.nombre_banco).all()
            logger.info(f"Cargados {len(self.bancos)} bancos de la base de datos")
            for banco in self.bancos:
                logger.info(
                    f"  - ID: {banco.id_banco}, Nombre: {banco.nombre_banco}, "
                    f"Código: {banco.codigo_banco}, Estado: {banco.estado_banco}"
                )
            self._actualizar_tabla()
            self._actualizar_paginacion()
        except Exception as e:
            logger.exception(f"Error al cargar bancos: {e}")
            self.bancos = []
            self._actualizar_tabla()
            self._actualizar_paginacion()
        finally:
            session.close()

    def _actualizar_tabla(self):
        """Actualiza la tabla con los bancos cargados (respetando paginación)."""
        self.tabla.setRowCount(0)

        # Calcular índices para la página actual
        inicio = (self.pagina_actual - 1) * POR_PAGINA
        fin = min(inicio + POR_PAGINA, len(self.bancos))

        bancos_pagina = self.bancos[inicio:fin]

        for _idx, banco in enumerate(bancos_pagina):
            row = self.tabla.rowCount()
            self.tabla.insertRow(row)

            # ID (oculto)
            self.tabla.setItem(row, COL_ID_INTERNO, QTableWidgetItem(str(banco.id_banco)))

            # Código
            self.tabla.setItem(row, 1, QTableWidgetItem(banco.codigo_banco or "N/A"))

            # Nombre
            self.tabla.setItem(row, 2, QTableWidgetItem(banco.nombre_banco or "N/A"))

            # Tipo
            self.tabla.setItem(row, 3, QTableWidgetItem(banco.tipo_banco or "N/A"))

            # RIF
            self.tabla.setItem(row, 4, QTableWidgetItem(banco.identificacion_banco or "N/A"))

            # Teléfono
            self.tabla.setItem(row, 5, QTableWidgetItem(banco.numero_telefono_banco or "N/A"))

            # Correo
            self.tabla.setItem(row, 6, QTableWidgetItem(banco.correo_banco or "N/A"))

            # Estado
            estado = banco.estado_banco or "N/A"
            color_estado = COLORES_ESTADO_BANCO.get(estado, COLOR_TEXT_MUTED)
            estado_widget = EstadoBadge(estado, color_estado)
            self.tabla.setCellWidget(row, 7, estado_widget)

        self.lbl_total.setText(f"{len(self.bancos)} bancos")

    def _actualizar_paginacion(self):
        """Actualiza los controles de paginación."""
        total = len(self.bancos)
        self.total_paginas = max(1, (total + POR_PAGINA - 1) // POR_PAGINA)
        self.lbl_paginacion.setText(f"Página {self.pagina_actual} de {self.total_paginas}")
        self.btn_anterior.setEnabled(self.pagina_actual > 1)
        self.btn_siguiente.setEnabled(self.pagina_actual < self.total_paginas)

    # ── Búsqueda y filtros ─────────────────────────────────────────────────

    def _buscar_desde_inicio(self):
        """Realiza búsqueda desde la página 1."""
        self.pagina_actual = 1
        self.cargar_bancos()

    def _busqueda_dinamica(self):
        """Búsqueda en tiempo real con debounce."""
        if hasattr(self, "_search_timer") and self._search_timer is not None:
            self._search_timer.stop()
        self._search_timer = QTimer.singleShot(300, self._buscar_desde_inicio)

    # ── Paginación ────────────────────────────────────────────────────────

    def pagina_anterior(self):
        if self.pagina_actual > 1:
            self.pagina_actual -= 1
            self._actualizar_tabla()
            self._actualizar_paginacion()

    def pagina_siguiente(self):
        if self.pagina_actual < self.total_paginas:
            self.pagina_actual += 1
            self._actualizar_tabla()
            self._actualizar_paginacion()

    # ── CRUD ─────────────────────────────────────────────────────────────

    def nuevo_banco(self):
        """Abre el diálogo para crear un nuevo banco."""
        session = self.session_factory()
        try:
            dialog = BancoFormDialog(session, parent=self)
            if dialog.exec():
                data = dialog.get_data()
                self._guardar_banco(session, data)
                self.cargar_bancos()
        except Exception:
            logger.exception("Error al crear banco")
        finally:
            session.close()

    def editar_banco(self):
        """Abre el diálogo para editar el banco seleccionado."""
        row = self.tabla.currentRow()
        if row < 0:
            return

        item = self.tabla.item(row, COL_ID_INTERNO)
        if item is None:
            return

        banco_id = int(item.text())
        session = self.session_factory()
        try:
            banco = session.query(Banco).filter(Banco.id_banco == banco_id).first()
            if banco:
                dialog = BancoFormDialog(session, banco, parent=self)
                if dialog.exec():
                    data = dialog.get_data()
                    self._actualizar_banco(session, banco, data)
                    self.cargar_bancos()
        except Exception:
            logger.exception("Error al editar banco")
        finally:
            session.close()

    def eliminar_banco(self):
        """Elimina el banco seleccionado."""
        row = self.tabla.currentRow()
        if row < 0:
            return

        item = self.tabla.item(row, COL_ID_INTERNO)
        if item is None:
            return

        banco_id = int(item.text())
        session = self.session_factory()
        try:
            banco = session.query(Banco).filter(Banco.id_banco == banco_id).first()
            if banco:
                reply = QMessageBox.question(
                    self,
                    "Confirmar eliminación",
                    f"¿Está seguro de eliminar el banco '{banco.nombre_banco}'?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    session.delete(banco)
                    session.commit()
                    logger.info(f"Banco eliminado: {banco.nombre_banco}")
                    self.cargar_bancos()
        except Exception:
            logger.exception("Error al eliminar banco")
        finally:
            session.close()

    def _on_selection_changed(self):
        """Habilita/deshabilita los botones de editar y eliminar según la selección."""
        has_selection = self.tabla.currentRow() >= 0
        self.btn_editar.setEnabled(has_selection)
        self.btn_eliminar.setEnabled(has_selection)

    def _guardar_banco(self, session, data: dict):
        """Guarda un nuevo banco en la base de datos."""
        from datetime import datetime

        banco = Banco(
            codigo_banco=data["codigo_banco"],
            nombre_banco=data["nombre_banco"],
            tipo_banco=data["tipo_banco"],
            identificacion_banco=data["identificacion_banco"],
            correo_banco=data["correo_banco"],
            numero_telefono_banco=data["numero_telefono_banco"],
            creado_por=self.usuario.id_usuario,
            fecha_creacion=datetime.now(),
            estado_banco="ACTIVO",
        )
        session.add(banco)
        session.commit()
        logger.info(f"Banco creado: {data['nombre_banco']}")

    def _actualizar_banco(self, session, banco: Banco, data: dict):
        """Actualiza un banco existente."""

        banco.codigo_banco = data["codigo_banco"]
        banco.nombre_banco = data["nombre_banco"]
        banco.tipo_banco = data["tipo_banco"]
        banco.identificacion_banco = data["identificacion_banco"]
        banco.correo_banco = data["correo_banco"]
        banco.numero_telefono_banco = data["numero_telefono_banco"]
        banco.modificado_por = self.usuario.id_usuario
        session.commit()
        logger.info(f"Banco actualizado: {data['nombre_banco']}")
