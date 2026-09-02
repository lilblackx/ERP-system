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
from app.services.permisos import PermisoDenegadoError
from app.ui.cliente_form_dialog import ClienteFormDialog
from app.ui.historial_cliente_window import HistorialClienteWindow
from app.ui.message_box import MessageBox
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
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MUTED,
    SEARCH_QSS,
    TABLE_QSS,
    EstadoBadge,
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
POR_PAGINA = 20

ESTADOS_FILTRO = [
    ("Todos los estados", None),
    ("Activos", "ACTIVO"),
    ("Inactivos", "INACTIVO"),
]


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
        self.pagina_actual = 1
        self.total_paginas = 1
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

        # Barra de busqueda unica: matchea nombre, identificacion, codigo, email o
        # telefono (ver ClienteService.list_clientes) -- antes eran dos cajas separadas
        # (nombre / identificacion) que se combinaban con AND, obligando a saber en cual
        # escribir cada dato.
        self.buscar_input = QLineEdit()
        self.buscar_input.setPlaceholderText("Buscar por nombre, identificación, email o teléfono…")
        self.buscar_input.addAction(
            qta.icon("fa5s.search", color=COLOR_TEXT_LIGHT), QLineEdit.ActionPosition.LeadingPosition
        )
        self.buscar_input.setObjectName("SearchInput")
        self.buscar_input.setStyleSheet(SEARCH_QSS)
        self.buscar_input.setFixedWidth(320)
        self.buscar_input.returnPressed.connect(self._buscar_desde_inicio)
        self.buscar_input.textChanged.connect(self._busqueda_dinamica)

        # Botones primarios
        self.btn_nuevo = QPushButton("Nuevo Cliente")
        self.btn_nuevo.setIcon(qta.icon("fa5s.plus", color="white"))
        self.btn_nuevo.setStyleSheet(BUTTON_PRIMARY_QSS)
        self.btn_nuevo.clicked.connect(self.nuevo_cliente)

        # Filtro de estado
        self.estado_combo = QComboBox()
        for etiqueta, valor in ESTADOS_FILTRO:
            self.estado_combo.addItem(etiqueta, valor)
        self.estado_combo.currentIndexChanged.connect(self._buscar_desde_inicio)

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
        self.vendedor_combo.currentIndexChanged.connect(self._buscar_desde_inicio)

        # Filtro de categoría
        self.categoria_combo = QComboBox()
        self.categoria_combo.addItem("Todas las categorías", None)
        session = self.session_factory()
        try:
            for categoria in session.query(CategoriaCliente).order_by(CategoriaCliente.nombre):
                self.categoria_combo.addItem(categoria.nombre, categoria.id_categoria_cliente)
        finally:
            session.close()
        self.categoria_combo.currentIndexChanged.connect(self._buscar_desde_inicio)

        self.btn_filtrar = BotonFiltros(
            [
                ("Estado", self.estado_combo),
                ("Vendedor", self.vendedor_combo),
                ("Categoría", self.categoria_combo),
            ]
        )
        self.btn_exportar = BotonExportar(on_excel=self.exportar_excel_clientes, on_pdf=self.exportar_pdf_clientes)

        h.addWidget(self.buscar_input)
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
        # Antes esto agregaba QSS propio encima de TABLE_QSS (fondo "#E3F2FD" a mano para
        # filas no-alternas y su propio color de seleccion) -- una version vieja/paralela
        # de lo que TABLE_QSS ya resuelve, que ademas dejaba las filas SIN seleccionar con
        # un tinte azul en vez de blanco/gris como el resto de los paneles (reportado por
        # el usuario, 2026-08-27) y no reflejaba el ajuste global de color de seleccion.
        # TABLE_QSS solo, igual que inventario_panel.py/vendedores_panel.py/usuarios_panel.py.
        self.tabla.setStyleSheet(TABLE_QSS)
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

        btn_editar = QPushButton("Editar seleccionado")
        btn_editar.setIcon(qta.icon("fa5s.edit", color=COLOR_TEXT_DARK))
        btn_editar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_editar.clicked.connect(self.editar_cliente)

        btn_estado = QPushButton("Cambiar estado")
        btn_estado.setIcon(qta.icon("fa5s.sync-alt", color=COLOR_TEXT_DARK))
        btn_estado.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_estado.clicked.connect(self.cambiar_estado_cliente_seleccionado)

        # Antes solo se llegaba al historial con doble clic en la fila -- sin ningun
        # boton visible que lo indicara (hallazgo de UX). ver_historial_cliente() ya
        # existia, este boton solo lo hace descubrible.
        btn_historial = QPushButton("Ver historial")
        btn_historial.setIcon(qta.icon("fa5s.history", color=COLOR_TEXT_DARK))
        btn_historial.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_historial.clicked.connect(self.ver_historial_cliente)

        h.addWidget(self.lbl_pagina)
        h.addWidget(self.btn_anterior)
        h.addWidget(self.btn_siguiente)
        h.addStretch()
        h.addWidget(btn_editar)
        h.addWidget(btn_estado)
        h.addWidget(btn_historial)
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
        self.cargar_clientes()

    def _pagina_anterior(self) -> None:
        if self.pagina_actual > 1:
            self.pagina_actual -= 1
            self.cargar_clientes()

    def _pagina_siguiente(self) -> None:
        if self.pagina_actual < self.total_paginas:
            self.pagina_actual += 1
            self.cargar_clientes()

    # ── Lógica de datos ───────────────────────────────────────────────────

    def cargar_clientes(self) -> None:
        session = self.session_factory()
        try:
            resultado = list_clientes(
                session,
                self.buscar_input.text().strip() or None,
                id_usuario=self.usuario.id_usuario,
                estado_cliente=self.estado_combo.currentData(),
                id_vendedor=self.vendedor_combo.currentData(),
                id_categoria=self.categoria_combo.currentData(),
                pagina=self.pagina_actual,
                por_pagina=POR_PAGINA,
            )
            self._poblar_tabla(resultado)
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar clientes.")
        except Exception:
            logger.exception("Fallo al cargar la lista de clientes")
            MessageBox.critical(self, "Error de conexión", "No se pudo cargar la lista de clientes.")
        finally:
            session.close()

    def _poblar_tabla(self, resultado: dict) -> None:
        clientes: list[Cliente] = resultado["items"]
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
            estado_cliente = c.estado_cliente or "ACTIVO"
            color_estado = COLOR_SUCCESS if estado_cliente.upper() == "ACTIVO" else COLOR_DANGER
            badge = EstadoBadge(estado_cliente.capitalize(), color_estado)
            self.tabla.setCellWidget(fila, 9, badge)

        total = resultado["total"]
        self.total_paginas = max(1, -(-total // POR_PAGINA))  # ceil sin importar math
        self.pagina_actual = min(self.pagina_actual, self.total_paginas)

        self.lbl_total.setText(f"{total} cliente{'s' if total != 1 else ''}")
        self.lbl_pagina.setText(f"Página {self.pagina_actual} de {self.total_paginas}")
        self.btn_anterior.setEnabled(self.pagina_actual > 1)
        self.btn_siguiente.setEnabled(self.pagina_actual < self.total_paginas)

    def _filas_para_exportar(self, session) -> list[list]:
        resultado = list_clientes(
            session,
            self.buscar_input.text().strip() or None,
            id_usuario=self.usuario.id_usuario,
            estado_cliente=self.estado_combo.currentData(),
            id_vendedor=self.vendedor_combo.currentData(),
            id_categoria=self.categoria_combo.currentData(),
            pagina=1,
            por_pagina=1_000_000,
        )
        clientes = resultado["items"]
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
            MessageBox.information(self, "Exportación completa", f"Se exportaron {len(filas)} clientes a:\n{ruta}")
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar clientes.")
        except Exception:
            logger.exception("Fallo al exportar la lista de clientes a Excel")
            MessageBox.critical(self, "Error", "No se pudo exportar la lista de clientes.")
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
            MessageBox.information(self, "Exportación completa", f"Se exportaron {len(filas)} clientes a:\n{ruta}")
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar clientes.")
        except Exception:
            logger.exception("Fallo al exportar la lista de clientes a PDF")
            MessageBox.critical(self, "Error", "No se pudo exportar la lista de clientes.")
        finally:
            session.close()

    def _fila_seleccionada_id(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            MessageBox.information(self, "Selección requerida", "Selecciona un cliente de la lista.")
            return None
        item = self.tabla.item(filas[0].row(), 0)
        if item is None:
            MessageBox.warning(self, "Error", "No se pudo obtener el ID del cliente seleccionado.")
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
            MessageBox.warning(
                self, "Dato duplicado", "El código o la identificación ya están registrados en otro cliente."
            )
        except ValueError as exc:
            # Mensaje ya pensado para el usuario final ("codigo_cliente es requerido",
            # etc.) -- no es un str(exc) tecnico, mismo criterio que C3.
            session.rollback()
            MessageBox.warning(self, "Dato invalido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para crear clientes.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al crear cliente")
            MessageBox.critical(self, "Error", "No se pudo crear el cliente.")
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
            MessageBox.warning(
                self, "Dato duplicado", "El código o la identificación ya están registrados en otro cliente."
            )
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, "Dato invalido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para editar clientes.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al editar cliente")
            MessageBox.critical(self, "Error", "No se pudo guardar los cambios del cliente.")
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

            respuesta = MessageBox.question(
                self, "Confirmar", f"¿Cambiar el estado del cliente '{cliente.nombre_razon_social}' a {nuevo_estado}?"
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return

            cambiar_estado_cliente(session, id_cliente, nuevo_estado, id_usuario=self.usuario.id_usuario)
            self.cargar_clientes()
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para cambiar el estado de clientes.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al cambiar el estado del cliente %s", id_cliente)
            MessageBox.critical(self, "Error", "No se pudo cambiar el estado del cliente.")
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
                MessageBox.warning(self, "Cliente no encontrado", "El cliente seleccionado no existe.")
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
            MessageBox.critical(self, "Error", "No se pudo abrir el historial del cliente.")
        finally:
            session.close()
