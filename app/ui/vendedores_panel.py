"""
Panel completo del módulo Vendedores: tres pestañas -- "Vendedores" (listado, alta/edición,
activar/desactivar), "Rutas" (RutasPanel, catálogo de rutas de reparto/cobranza que se
asignan a cada vendedor) y "Mapa" (MapaRutasPanel, geolocalización de clientes/rutas).
Mismo patrón visual que app/ui/clientes_panel.py (paleta y tipografía de
app/ui/styles.py), y mismo criterio de QTabWidget que app/ui/usuarios_panel.py (Usuarios +
Roles y Permisos) -- nunca DELETE fisico, ver VendedorService.eliminar.
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import IntegrityError

from app.db.models import Usuario, Vendedor
from app.services.exportacion import exportar_excel, exportar_pdf
from app.services.permisos import PermisoDenegadoError
from app.services.vendedores import VendedorService
from app.ui.mapa_rutas_panel import MapaRutasPanel
from app.ui.message_box import MessageBox
from app.ui.rutas_panel import RutasPanel
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
    TABS_QSS,
    EstadoBadge,
    alinear_encabezados,
    aplicar_sombra,
)
from app.ui.toolbar_popups import BotonExportar
from app.ui.vendedor_form_dialog import VendedorFormDialog

logger = logging.getLogger(__name__)

COLS_VISIBLES = ["ID", "Nombre", "Código", "Identificación", "Ruta", "Teléfono", "Email", "Estado"]
COL_ID_INTERNO = 0  # oculto
POR_PAGINA = 20

ESTADOS_FILTRO = [
    ("Todos los estados", None),
    ("Activos", "ACTIVO"),
    ("Inactivos", "INACTIVO"),
]


class VendedoresPanel(QWidget):
    """Panel principal del módulo Vendedores: listado con búsqueda, alta/edición
    y activar/desactivar -- lo minimo necesario para poder emitir facturas
    (FacturaFormDialog exige un vendedor activo)."""

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.pagina_actual = 1
        self.total_paginas = 1
        # None hasta que el usuario abre la sub-pestaña "Mapa" -- ver _asegurar_tab_mapa().
        self.tab_mapa: MapaRutasPanel | None = None
        self.setObjectName("ContentArea")
        self._setup_ui()
        QTimer.singleShot(100, self.cargar_vendedores)

    def showEvent(self, event: QShowEvent) -> None:
        # Mismo motivo que en el resto de los paneles (ver DashboardPanel.showEvent):
        # MainWindow cachea el panel via QStackedWidget, asi que sin esto volver a
        # "Vendedores" desde otro modulo mostraba el listado viejo.
        super().showEvent(event)
        self.cargar_vendedores()
        actual = self.tabs.currentWidget()
        if actual is self.tab_rutas:
            self.tab_rutas.cargar()
        elif actual is self._mapa_placeholder:
            self._asegurar_tab_mapa()
        elif self.tab_mapa is not None and actual is self.tab_mapa:
            self.tab_mapa.cargar()

    # ── Construcción de la UI ─────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        root.addWidget(self._make_header())

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(TABS_QSS)
        self.tab_vendedores = self._make_tab_vendedores()
        self.tab_rutas = RutasPanel(self.session_factory, self.usuario)
        self.tabs.addTab(self.tab_vendedores, "Vendedores")
        self.tabs.addTab(self.tab_rutas, "Rutas")
        # Placeholder vacio en vez de crear MapaRutasPanel (y su QWebEngineView) de una
        # vez: lo primero que hace WebEngine al construirse es levantar el proceso de
        # GPU/renderer de Chromium, lo que en esta maquina produce un parpadeo visible de
        # toda la ventana -- reportado por el usuario, 2026-09-01, "al entrar a vendedores
        # la app se cierra y abre rapido" (no era un crash real, solo el costo de ese
        # arranque pagado sin que el usuario hubiera pedido ver el mapa todavia). Se
        # construye recien al entrar efectivamente a esta pestaña, ver
        # _asegurar_tab_mapa().
        self._mapa_placeholder = QWidget()
        self.tabs.addTab(self._mapa_placeholder, "Mapa")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, stretch=1)

        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

    def _asegurar_tab_mapa(self) -> None:
        if self.tab_mapa is not None:
            return
        idx = self.tabs.indexOf(self._mapa_placeholder)
        self.tab_mapa = MapaRutasPanel(self.session_factory, self.usuario)
        self.tabs.removeTab(idx)
        self.tabs.insertTab(idx, self.tab_mapa, "Mapa")
        self.tabs.setCurrentIndex(idx)
        self.tab_mapa.cargar()

    def _on_tab_changed(self, indice: int) -> None:
        widget = self.tabs.widget(indice)
        if widget is self.tab_rutas:
            self.tab_rutas.cargar()
        elif widget is self._mapa_placeholder:
            self._asegurar_tab_mapa()
        elif self.tab_mapa is not None and widget is self.tab_mapa:
            self.tab_mapa.cargar()

    def _make_tab_vendedores(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 12, 4, 4)
        v.setSpacing(16)

        v.addWidget(self._make_toolbar())
        v.addWidget(self._make_table(), stretch=1)
        v.addWidget(self._make_footer())
        return w

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
        self.buscar_input.addAction(
            qta.icon("fa5s.search", color=COLOR_TEXT_LIGHT), QLineEdit.ActionPosition.LeadingPosition
        )
        self.buscar_input.setObjectName("SearchInput")
        self.buscar_input.setStyleSheet(SEARCH_QSS)
        self.buscar_input.setFixedWidth(220)
        self.buscar_input.returnPressed.connect(self._buscar_desde_inicio)
        self.buscar_input.textChanged.connect(self._busqueda_dinamica)

        self.btn_nuevo = QPushButton("Nuevo Vendedor")
        self.btn_nuevo.setIcon(qta.icon("fa5s.user-plus", color="white"))
        self.btn_nuevo.setStyleSheet(BUTTON_PRIMARY_QSS)
        self.btn_nuevo.clicked.connect(self.nuevo_vendedor)

        # Filtro de estado -- antes no existia (hallazgo de auditoria, 2026-08-27): sin
        # el, no habia forma de ocultar de la lista a los vendedores retirados.
        self.estado_combo = QComboBox()
        for etiqueta, valor in ESTADOS_FILTRO:
            self.estado_combo.addItem(etiqueta, valor)
        self.estado_combo.currentIndexChanged.connect(self._buscar_desde_inicio)

        self.btn_exportar = BotonExportar(on_excel=self.exportar_excel_vendedores, on_pdf=self.exportar_pdf_vendedores)

        h.addWidget(self.buscar_input)
        h.addWidget(self.estado_combo)
        h.addSpacerItem(QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        h.addWidget(self.btn_nuevo)
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
        self.tabla.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        self.tabla.setColumnWidth(7, 110)
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
        btn_editar.clicked.connect(self.editar_vendedor)

        btn_estado = QPushButton("Cambiar estado")
        btn_estado.setIcon(qta.icon("fa5s.sync-alt", color=COLOR_TEXT_DARK))
        btn_estado.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_estado.clicked.connect(self.cambiar_estado_vendedor_seleccionado)

        h.addWidget(self.lbl_pagina)
        h.addWidget(self.btn_anterior)
        h.addWidget(self.btn_siguiente)
        h.addStretch()
        h.addWidget(btn_editar)
        h.addWidget(btn_estado)
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
        self.cargar_vendedores()

    def _pagina_anterior(self) -> None:
        if self.pagina_actual > 1:
            self.pagina_actual -= 1
            self.cargar_vendedores()

    def _pagina_siguiente(self) -> None:
        if self.pagina_actual < self.total_paginas:
            self.pagina_actual += 1
            self.cargar_vendedores()

    # ── Lógica de datos ───────────────────────────────────────────────────

    def cargar_vendedores(self) -> None:
        session = self.session_factory()
        try:
            resultado = VendedorService.listar(
                session,
                self.buscar_input.text().strip() or None,
                id_usuario=self.usuario.id_usuario,
                estado_vendedor=self.estado_combo.currentData(),
                pagina=self.pagina_actual,
                por_pagina=POR_PAGINA,
            )
            self._poblar_tabla(resultado)
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar vendedores.")
        except Exception:
            logger.exception("Fallo al cargar la lista de vendedores")
            MessageBox.critical(self, "Error de conexión", "No se pudo cargar la lista de vendedores.")
        finally:
            session.close()

    def _poblar_tabla(self, resultado: dict) -> None:
        vendedores: list[Vendedor] = resultado["items"]
        self.tabla.setRowCount(len(vendedores))
        for fila, v in enumerate(vendedores):
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(v.id_vendedor)))
            self.tabla.setItem(fila, 1, QTableWidgetItem(v.nombre_vendedor or ""))
            self.tabla.setItem(fila, 2, QTableWidgetItem(v.codigo_vendedor or ""))
            self.tabla.setItem(fila, 3, QTableWidgetItem(v.identificacion_vendedor or ""))
            self.tabla.setItem(fila, 4, QTableWidgetItem(v.ruta.nombre_ruta if v.ruta else ""))
            self.tabla.setItem(fila, 5, QTableWidgetItem(v.telefono_vendedor or ""))
            self.tabla.setItem(fila, 6, QTableWidgetItem(v.email_vendedor or ""))

            estado_vendedor = v.estado_vendedor or "ACTIVO"
            color_estado = COLOR_SUCCESS if estado_vendedor.upper() == "ACTIVO" else COLOR_DANGER
            badge = EstadoBadge(estado_vendedor.capitalize(), color_estado)
            self.tabla.setCellWidget(fila, 7, badge)

        total = resultado["total"]
        self.total_paginas = max(1, -(-total // POR_PAGINA))  # ceil sin importar math
        self.pagina_actual = min(self.pagina_actual, self.total_paginas)

        self.lbl_total.setText(f"{total} vendedor{'es' if total != 1 else ''}")
        self.lbl_pagina.setText(f"Página {self.pagina_actual} de {self.total_paginas}")
        self.btn_anterior.setEnabled(self.pagina_actual > 1)
        self.btn_siguiente.setEnabled(self.pagina_actual < self.total_paginas)

    def _filas_para_exportar(self, session) -> list[list]:
        resultado = VendedorService.listar(
            session,
            self.buscar_input.text().strip() or None,
            id_usuario=self.usuario.id_usuario,
            estado_vendedor=self.estado_combo.currentData(),
            pagina=1,
            por_pagina=1_000_000,
        )
        vendedores: list[Vendedor] = resultado["items"]
        return [
            [
                v.id_vendedor,
                v.nombre_vendedor,
                v.codigo_vendedor,
                v.identificacion_vendedor,
                v.ruta.nombre_ruta if v.ruta else "",
                v.telefono_vendedor,
                v.email_vendedor,
                v.estado_vendedor,
            ]
            for v in vendedores
        ]

    def exportar_excel_vendedores(self) -> None:
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar vendedores", "vendedores.xlsx", "Excel (*.xlsx)")
        if not ruta:
            return

        session = self.session_factory()
        try:
            filas = self._filas_para_exportar(session)
            exportar_excel(ruta, COLS_VISIBLES, filas)
            MessageBox.information(self, "Exportación completa", f"Se exportaron {len(filas)} vendedores a:\n{ruta}")
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar vendedores.")
        except Exception:
            logger.exception("Fallo al exportar la lista de vendedores a Excel")
            MessageBox.critical(self, "Error", "No se pudo exportar la lista de vendedores.")
        finally:
            session.close()

    def exportar_pdf_vendedores(self) -> None:
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar vendedores", "vendedores.pdf", "PDF (*.pdf)")
        if not ruta:
            return

        session = self.session_factory()
        try:
            filas = self._filas_para_exportar(session)

            filtros = {}
            texto_busqueda = self.buscar_input.text().strip()
            filtros["Búsqueda"] = texto_busqueda if texto_busqueda else "Todos"
            filtros["Estado"] = self.estado_combo.currentText()

            col_widths = [0.5, 2.0, 1.0, 1.2, 1.2, 1.3, 2.0, 1.0]

            exportar_pdf(
                ruta,
                "Reporte de Vendedores",
                COLS_VISIBLES,
                filas,
                filtros=filtros,
                col_widths=col_widths,
            )
            MessageBox.information(self, "Exportación completa", f"Se exportaron {len(filas)} vendedores a:\n{ruta}")
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar vendedores.")
        except Exception:
            logger.exception("Fallo al exportar la lista de vendedores a PDF")
            MessageBox.critical(self, "Error", "No se pudo exportar la lista de vendedores.")
        finally:
            session.close()

    def _fila_seleccionada_id(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            MessageBox.information(self, "Selección requerida", "Selecciona un vendedor de la lista.")
            return None
        return int(self.tabla.item(filas[0].row(), 0).text())

    def nuevo_vendedor(self) -> None:
        session = self.session_factory()
        try:
            dialogo = VendedorFormDialog(session, id_usuario=self.usuario.id_usuario, parent=self)
            if dialogo.exec():
                datos = dialogo.get_data()
                datos["creado_por"] = self.usuario.id_usuario
                VendedorService.crear(session, **datos)
                self.cargar_vendedores()
        except IntegrityError:
            session.rollback()
            MessageBox.warning(
                self, "Dato duplicado", "El código o la identificación ya están registrados en otro vendedor."
            )
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para crear vendedores.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al crear vendedor")
            MessageBox.critical(self, "Error", "No se pudo crear el vendedor.")
        finally:
            session.close()

    def editar_vendedor(self) -> None:
        id_vendedor = self._fila_seleccionada_id()
        if id_vendedor is None:
            return

        session = self.session_factory()
        try:
            vendedor = VendedorService.obtener(session, id_vendedor, id_usuario=self.usuario.id_usuario)
            dialogo = VendedorFormDialog(session, vendedor, id_usuario=self.usuario.id_usuario, parent=self)
            if dialogo.exec():
                VendedorService.actualizar(
                    session, id_vendedor, id_usuario=self.usuario.id_usuario, **dialogo.get_data()
                )
                self.cargar_vendedores()
        except IntegrityError:
            session.rollback()
            MessageBox.warning(
                self, "Dato duplicado", "El código o la identificación ya están registrados en otro vendedor."
            )
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para editar vendedores.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al editar vendedor")
            MessageBox.critical(self, "Error", "No se pudo guardar los cambios del vendedor.")
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

            respuesta = MessageBox.question(
                self, "Confirmar", f"¿Cambiar el estado del vendedor '{vendedor.nombre_vendedor}' a {nuevo_estado}?"
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return

            VendedorService.cambiar_estado(session, id_vendedor, nuevo_estado, id_usuario=self.usuario.id_usuario)
            self.cargar_vendedores()
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para cambiar el estado de vendedores.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al cambiar el estado del vendedor %s", id_vendedor)
            MessageBox.critical(self, "Error", "No se pudo cambiar el estado del vendedor.")
        finally:
            session.close()
