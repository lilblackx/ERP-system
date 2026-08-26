"""
Panel completo del módulo Clientes.
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
    QFileDialog,
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
from sqlalchemy.exc import IntegrityError

from app.db.models import CategoriaCliente, Cliente, Usuario, Vendedor
from app.services.clientes import (
    cambiar_estado_cliente,
    create_cliente,
    list_clientes,
    update_cliente,
)
from app.services.exportacion import exportar_excel, exportar_pdf
from app.ui.cliente_form_dialog import ClienteFormDialog
from app.ui.historial_cliente_window import HistorialClienteWindow
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    SEARCH_QSS,
    TABLE_QSS,
    alinear_encabezados,
    aplicar_sombra,
)
from app.ui.toolbar_popups import BotonExportar, BotonFiltros

logger = logging.getLogger(__name__)

# Columnas visibles en la tabla (índice oculto 0 = ID interno)
COLS_VISIBLES = [
    "ID",
    "Nombre Completo",
    "Identificación",
    "Email",
    "Teléfono",
    "Dirección",
    "Vendedor",
    "Crédito",
    "Días",
    "Estado",
]
COL_ID_INTERNO = 0  # oculto

ESTADOS_FILTRO = [
    ("Todos los estados", None),
    ("Activos", "ACTIVO"),
    ("Inactivos", "INACTIVO"),
]


class BadgeItem(QWidget):
    """Widget badge para mostrar estado ACTIVO / INACTIVO de forma visual."""

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


class AccionesItem(QWidget):
    """Botones de acción por fila: Editar + Activar/Desactivar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_editar = QPushButton(" Editar")
        self.btn_editar.setIcon(qta.icon("fa5s.edit", color=COLOR_PRIMARY))
        self.btn_editar.setStyleSheet(f"""
            QPushButton {{
                background-color: #EFF6FF; color: {COLOR_PRIMARY};
                border: 1px solid #BFDBFE; border-radius: 5px;
                padding: 4px 10px; font-size: 11px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #DBEAFE; }}
        """)

        self.btn_estado = QPushButton(" Estado")
        self.btn_estado.setIcon(qta.icon("fa5s.sync-alt", color=COLOR_SUCCESS))
        self.btn_estado.setStyleSheet(f"""
            QPushButton {{
                background-color: #F0FDF4; color: {COLOR_SUCCESS};
                border: 1px solid #BBF7D0; border-radius: 5px;
                padding: 4px 10px; font-size: 11px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #DCFCE7; }}
        """)

        layout.addWidget(self.btn_editar)
        layout.addWidget(self.btn_estado)


class ClientesPanel(QWidget):
    """
    Panel principal del módulo Clientes.
    Encapsula la barra de herramientas y la tabla de datos en un solo widget
    para ser insertado directamente en el área de contenido del MainWindow.
    """

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.setObjectName("ContentArea")
        self._setup_ui()
        # Carga inicial diferida para no bloquear el arranque
        QTimer.singleShot(100, self.cargar_clientes)

    def showEvent(self, event: QShowEvent) -> None:
        # MainWindow cachea el panel y lo reutiliza via QStackedWidget -- sin
        # esto, volver a "Clientes" desde otro modulo mostraba el listado viejo
        # (mismo problema que DashboardPanel/FacturacionPanel).
        super().showEvent(event)
        self.cargar_clientes()

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

        lbl = QLabel("LISTA DE CLIENTES")
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

        # Buscar por nombre
        self.buscar_input = QLineEdit()
        self.buscar_input.setPlaceholderText("Buscar por nombre…")
        self.buscar_input.addAction(qta.icon("fa5s.search", color="#94A3B8"), QLineEdit.ActionPosition.LeadingPosition)
        self.buscar_input.setObjectName("SearchInput")
        self.buscar_input.setStyleSheet(SEARCH_QSS)
        self.buscar_input.setFixedWidth(220)
        self.buscar_input.returnPressed.connect(self.cargar_clientes)
        self.buscar_input.textChanged.connect(self._busqueda_dinamica)

        # Buscar por identificación
        self.buscar_identificacion_input = QLineEdit()
        self.buscar_identificacion_input.setPlaceholderText("Buscar por identificación…")
        self.buscar_identificacion_input.addAction(qta.icon("fa5s.id-card", color="#94A3B8"), QLineEdit.ActionPosition.LeadingPosition)
        self.buscar_identificacion_input.setObjectName("SearchInput")
        self.buscar_identificacion_input.setStyleSheet(SEARCH_QSS)
        self.buscar_identificacion_input.setFixedWidth(220)
        self.buscar_identificacion_input.returnPressed.connect(self.cargar_clientes)
        self.buscar_identificacion_input.textChanged.connect(self._busqueda_dinamica)

        # Botones primarios
        self.btn_nuevo = QPushButton("Nuevo Cliente")
        self.btn_nuevo.setIcon(qta.icon("fa5s.plus", color="white"))
        self.btn_nuevo.setStyleSheet(BUTTON_PRIMARY_QSS)
        self.btn_nuevo.clicked.connect(self.nuevo_cliente)

        # Filtro de estado
        self.estado_combo = QComboBox()
        for etiqueta, valor in ESTADOS_FILTRO:
            self.estado_combo.addItem(etiqueta, valor)
        self.estado_combo.currentIndexChanged.connect(self.cargar_clientes)

        # Filtro de vendedor
        self.vendedor_combo = QComboBox()
        self.vendedor_combo.addItem("Todos los vendedores", None)
        session = self.session_factory()
        try:
            vendedores = (
                session.query(Vendedor).filter(Vendedor.estado_vendedor == "ACTIVO").order_by(Vendedor.nombre_vendedor)
            )
            for vendedor in vendedores:
                self.vendedor_combo.addItem(vendedor.nombre_vendedor, vendedor.id_vendedor)
        finally:
            session.close()
        self.vendedor_combo.currentIndexChanged.connect(self.cargar_clientes)

        # Filtro de categoría
        self.categoria_combo = QComboBox()
        self.categoria_combo.addItem("Todas las categorías", None)
        session = self.session_factory()
        try:
            for categoria in session.query(CategoriaCliente).order_by(CategoriaCliente.nombre):
                self.categoria_combo.addItem(categoria.nombre, categoria.id_categoria_cliente)
        finally:
            session.close()
        self.categoria_combo.currentIndexChanged.connect(self.cargar_clientes)

        self.btn_filtrar = BotonFiltros(
            [
                ("Estado", self.estado_combo),
                ("Vendedor", self.vendedor_combo),
                ("Categoría", self.categoria_combo),
            ]
        )
        self.btn_exportar = BotonExportar(on_excel=self.exportar_excel_clientes, on_pdf=self.exportar_pdf_clientes)

        h.addWidget(self.buscar_input)
        h.addWidget(self.buscar_identificacion_input)
        h.addSpacerItem(QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        h.addWidget(self.btn_nuevo)
        h.addWidget(self.btn_filtrar)
        h.addWidget(self.btn_exportar)
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
                7: Qt.AlignmentFlag.AlignRight,
                8: Qt.AlignmentFlag.AlignCenter,
                9: Qt.AlignmentFlag.AlignCenter,
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
        self.tabla.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(9, QHeaderView.ResizeMode.Fixed)
        self.tabla.setColumnWidth(9, 120)
        self.tabla.setStyleSheet(
            TABLE_QSS
            + """
            QTableWidget::item { padding: 8px; }
            QTableWidget::item:alternate { background-color: #F8FAFC; }
            QTableWidget::item:!alternate { background-color: #E3F2FD; }
            QTableWidget::item:selected { background-color: #DBEAFE; color: #0D47A1; }
        """
        )
        aplicar_sombra(self.tabla)
        self.tabla.setColumnHidden(COL_ID_INTERNO, True)  # ID oculto
        self.tabla.verticalHeader().setDefaultSectionSize(48)
        self.tabla.doubleClicked.connect(self.ver_historial_cliente)
        return self.tabla

    def _make_footer(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        self.lbl_pagina = QLabel("Mostrando todos los registros")
        self.lbl_pagina.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")

        btn_editar = QPushButton("EDITAR SELECCIONADO")
        btn_editar.setIcon(qta.icon("fa5s.edit", color=COLOR_TEXT_DARK))
        btn_editar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_editar.clicked.connect(self.editar_cliente)

        btn_estado = QPushButton("CAMBIAR ESTADO")
        btn_estado.setIcon(qta.icon("fa5s.sync-alt", color=COLOR_TEXT_DARK))
        btn_estado.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_estado.clicked.connect(self.cambiar_estado_cliente_seleccionado)

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
            self._timer_busqueda.timeout.connect(self.cargar_clientes)
        self._timer_busqueda.start(300)

    # ── Lógica de datos ───────────────────────────────────────────────────

    def cargar_clientes(self) -> None:
        session = self.session_factory()
        try:
            clientes = list_clientes(
                session,
                self.buscar_input.text().strip() or None,
                id_usuario=self.usuario.id_usuario,
                estado_cliente=self.estado_combo.currentData(),
                id_vendedor=self.vendedor_combo.currentData(),
                id_categoria=self.categoria_combo.currentData(),
                identificacion=self.buscar_identificacion_input.text().strip() or None,
            )
            self._poblar_tabla(clientes)
        except Exception:
            logger.exception("Fallo al cargar la lista de clientes")
            QMessageBox.critical(self, "Error de conexión", "No se pudo cargar la lista de clientes.")
        finally:
            session.close()

    def _poblar_tabla(self, clientes: list[Cliente]) -> None:
        self.tabla.setRowCount(len(clientes))
        for fila, c in enumerate(clientes):
            # Columna 0: ID (oculta)
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(c.id_cliente)))
            # Columna 1: Nombre Completo
            self.tabla.setItem(fila, 1, QTableWidgetItem(c.nombre_razon_social or ""))
            # Columna 2: Identificación
            if c.id_legal and c.identificacion_cliente:
                identificacion = f"{c.id_legal}-{c.identificacion_cliente}"
            else:
                identificacion = c.id_legal or c.identificacion_cliente or ""
            self.tabla.setItem(fila, 2, QTableWidgetItem(identificacion))
            # Columna 3: Email
            self.tabla.setItem(fila, 3, QTableWidgetItem(c.email or ""))
            # Columna 4: Teléfono
            self.tabla.setItem(fila, 4, QTableWidgetItem(c.telefono or ""))
            # Columna 5: Dirección
            self.tabla.setItem(fila, 5, QTableWidgetItem(c.direccion or ""))

            # Columna 6: Vendedor
            nombre_vendedor = c.vendedor.nombre_vendedor if c.vendedor else ""
            self.tabla.setItem(fila, 6, QTableWidgetItem(nombre_vendedor))

            # Columna 7: Crédito
            cred = f"${float(c.limite_credito):,.2f}" if c.limite_credito else "$0.00"
            item_cred = QTableWidgetItem(cred)
            item_cred.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 7, item_cred)

            # Columna 8: Días de crédito
            dias = str(c.dias_credito) if c.dias_credito is not None else "0"
            item_dias = QTableWidgetItem(dias)
            item_dias.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 8, item_dias)

            # Columna 9: Badge de estado
            badge = BadgeItem(c.estado_cliente or "ACTIVO")
            self.tabla.setCellWidget(fila, 9, badge)

        total = len(clientes)
        self.lbl_total.setText(f"{total} cliente{'s' if total != 1 else ''}")
        self.lbl_pagina.setText(f"Mostrando {total} registro{'s' if total != 1 else ''}")

    def _filas_para_exportar(self, session) -> list[list]:
        clientes = list_clientes(
            session,
            self.buscar_input.text().strip() or None,
            id_usuario=self.usuario.id_usuario,
            estado_cliente=self.estado_combo.currentData(),
            id_vendedor=self.vendedor_combo.currentData(),
            id_categoria=self.categoria_combo.currentData(),
            identificacion=self.buscar_identificacion_input.text().strip() or None,
        )
        return [
            [
                c.id_cliente,
                c.nombre_razon_social,
                f"{c.id_legal}-{c.identificacion_cliente}"
                if c.id_legal and c.identificacion_cliente
                else (c.id_legal or c.identificacion_cliente or ""),
                c.email,
                c.telefono,
                c.direccion,
                c.vendedor.nombre_vendedor if c.vendedor else "",
                float(c.limite_credito) if c.limite_credito else 0,
                c.dias_credito if c.dias_credito is not None else 0,
                c.estado_cliente,
            ]
            for c in clientes
        ]

    def exportar_excel_clientes(self) -> None:
        # R-09: se pide el destino ANTES de generar el archivo -- se escribe directo ahi,
        # nunca a un temporal, asi que no hay nada que purgar si el usuario cancela.
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar clientes", "clientes.xlsx", "Excel (*.xlsx)")
        if not ruta:
            return

        session = self.session_factory()
        try:
            filas = self._filas_para_exportar(session)
            exportar_excel(ruta, COLS_VISIBLES, filas)
            QMessageBox.information(self, "Exportación completa", f"Se exportaron {len(filas)} clientes a:\n{ruta}")
        except Exception:
            logger.exception("Fallo al exportar la lista de clientes a Excel")
            QMessageBox.critical(self, "Error", "No se pudo exportar la lista de clientes.")
        finally:
            session.close()

    def exportar_pdf_clientes(self) -> None:
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar clientes", "clientes.pdf", "PDF (*.pdf)")
        if not ruta:
            return

        session = self.session_factory()
        try:
            filas = self._filas_para_exportar(session)

            # Construir diccionario de filtros aplicados (siempre mostrar todos)
            filtros = {}
            texto_busqueda = self.buscar_input.text().strip()
            filtros["Búsqueda"] = texto_busqueda if texto_busqueda else "Todos"

            estado = self.estado_combo.currentText()
            filtros["Estado"] = estado

            vendedor = self.vendedor_combo.currentText()
            filtros["Vendedor"] = vendedor

            categoria = self.categoria_combo.currentText()
            filtros["Categoría"] = categoria

            # Anchos de columnas optimizados para mejor legibilidad
            # ID: pequeño, Nombre: grande, Identificación: medio, Email: grande, etc.
            col_widths = [0.5, 2.5, 1.2, 2.0, 1.2, 1.5, 1.5, 1.0, 0.8, 1.0]

            exportar_pdf(
                ruta,
                "Reporte de Clientes",
                COLS_VISIBLES,
                filas,
                filtros=filtros,
                col_widths=col_widths,
            )
            QMessageBox.information(self, "Exportación completa", f"Se exportaron {len(filas)} clientes a:\n{ruta}")
        except Exception:
            logger.exception("Fallo al exportar la lista de clientes a PDF")
            QMessageBox.critical(self, "Error", "No se pudo exportar la lista de clientes.")
        finally:
            session.close()

    def _fila_seleccionada_id(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            QMessageBox.information(self, "Selección requerida", "Selecciona un cliente de la lista.")
            return None
        item = self.tabla.item(filas[0].row(), 0)
        if item is None:
            QMessageBox.warning(self, "Error", "No se pudo obtener el ID del cliente seleccionado.")
            return None
        return int(item.text())

    def nuevo_cliente(self) -> None:
        session = self.session_factory()
        try:
            dialogo = ClienteFormDialog(session, parent=self)
            if dialogo.exec():
                datos = dialogo.get_data()
                datos["creado_por"] = self.usuario.id_usuario
                create_cliente(session, **datos)
                self.cargar_clientes()
        except IntegrityError:
            session.rollback()
            QMessageBox.warning(
                self, "Dato duplicado", "El código o la identificación ya están registrados en otro cliente."
            )
        except ValueError as exc:
            # Mensaje ya pensado para el usuario final ("codigo_cliente es requerido",
            # etc.) -- no es un str(exc) tecnico, mismo criterio que C3.
            session.rollback()
            QMessageBox.warning(self, "Dato invalido", str(exc))
        except Exception:
            session.rollback()
            logger.exception("Fallo al crear cliente")
            QMessageBox.critical(self, "Error", "No se pudo crear el cliente.")
        finally:
            session.close()

    def editar_cliente(self) -> None:
        id_cliente = self._fila_seleccionada_id()
        if id_cliente is None:
            return

        session = self.session_factory()
        try:
            cliente = session.get(Cliente, id_cliente)
            dialogo = ClienteFormDialog(session, cliente, parent=self)
            if dialogo.exec():
                update_cliente(session, id_cliente, id_usuario=self.usuario.id_usuario, **dialogo.get_data())
                self.cargar_clientes()
        except IntegrityError:
            session.rollback()
            QMessageBox.warning(
                self, "Dato duplicado", "El código o la identificación ya están registrados en otro cliente."
            )
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "Dato invalido", str(exc))
        except Exception:
            session.rollback()
            logger.exception("Fallo al editar cliente")
            QMessageBox.critical(self, "Error", "No se pudo guardar los cambios del cliente.")
        finally:
            session.close()

    def cambiar_estado_cliente_seleccionado(self) -> None:
        id_cliente = self._fila_seleccionada_id()
        if id_cliente is None:
            return

        session = self.session_factory()
        try:
            cliente = session.get(Cliente, id_cliente)
            estado_actual = cliente.estado_cliente or "ACTIVO"
            nuevo_estado = "INACTIVO" if estado_actual == "ACTIVO" else "ACTIVO"

            respuesta = QMessageBox.question(
                self, "Confirmar", f"¿Cambiar el estado del cliente '{cliente.nombre_razon_social}' a {nuevo_estado}?"
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return

            cambiar_estado_cliente(session, id_cliente, nuevo_estado, id_usuario=self.usuario.id_usuario)
            self.cargar_clientes()
        except Exception:
            session.rollback()
            logger.exception("Fallo al cambiar el estado del cliente %s", id_cliente)
            QMessageBox.critical(self, "Error", "No se pudo cambiar el estado del cliente.")
        finally:
            session.close()

    def ver_historial_cliente(self) -> None:
        id_cliente = self._fila_seleccionada_id()
        if id_cliente is None:
            return

        session = self.session_factory()
        try:
            cliente = session.get(Cliente, id_cliente)
            if cliente is None:
                QMessageBox.warning(self, "Cliente no encontrado", "El cliente seleccionado no existe.")
                return

            dialogo = HistorialClienteWindow(
                self.session_factory,
                id_cliente,
                cliente,
                self.usuario.id_usuario,
                parent=self,
            )
            dialogo.exec()
        except Exception:
            logger.exception("Fallo al abrir el historial del cliente %s", id_cliente)
            QMessageBox.critical(self, "Error", "No se pudo abrir el historial del cliente.")
        finally:
            session.close()
