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

from app.db.models import Banco, Usuario
from app.services.bancos import BancoService
from app.services.exportacion import exportar_excel, exportar_pdf
from app.services.permisos import PermisoDenegadoError
from app.ui.banco_form_dialog import BancoFormDialog
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
    EstadoBadge,
    alinear_encabezados,
    aplicar_sombra,
)
from app.ui.toolbar_popups import BotonExportar, BotonFiltros

logger = logging.getLogger(__name__)

COLS_VISIBLES = ["ID", "Código", "Nombre", "Tipo", "Identificación", "Teléfono", "Email", "Estado"]
COL_ID_INTERNO = 0  # oculto
POR_PAGINA = 20

ESTADOS_FILTRO = [
    ("Todos los estados", None),
    ("Activos", "ACTIVO"),
    ("Inactivos", "INACTIVO"),
]


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
        self.setObjectName("ContentArea")
        self._setup_ui()
        # Carga inicial diferida para no bloquear el arranque
        QTimer.singleShot(100, self.cargar_bancos)

    def showEvent(self, event: QShowEvent) -> None:
        # MainWindow cachea el panel y lo reutiliza via QStackedWidget -- sin
        # esto, volver a "Bancos" desde otro modulo mostraria el listado viejo.
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

        # Barra de busqueda unica: matchea nombre, identificacion, codigo
        self.buscar_input = QLineEdit()
        self.buscar_input.setPlaceholderText("Buscar por nombre, identificación o código…")
        self.buscar_input.addAction(qta.icon("fa5s.search", color="#94A3B8"), QLineEdit.ActionPosition.LeadingPosition)
        self.buscar_input.setObjectName("SearchInput")
        self.buscar_input.setStyleSheet(SEARCH_QSS)
        self.buscar_input.setFixedWidth(320)
        self.buscar_input.returnPressed.connect(self._buscar_desde_inicio)
        self.buscar_input.textChanged.connect(self._busqueda_dinamica)

        # Botones primarios
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
        self.btn_exportar = BotonExportar(on_excel=self.exportar_excel_bancos, on_pdf=self.exportar_pdf_bancos)

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
                7: Qt.AlignmentFlag.AlignLeft,
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
        self.tabla.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        self.tabla.setColumnWidth(7, 120)
        self.tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(self.tabla)
        self.tabla.setColumnHidden(COL_ID_INTERNO, True)
        self.tabla.verticalHeader().setDefaultSectionSize(45)
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
        btn_editar.clicked.connect(self.editar_banco)

        btn_estado = QPushButton("Cambiar estado")
        btn_estado.setIcon(qta.icon("fa5s.sync-alt", color=COLOR_TEXT_DARK))
        btn_estado.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_estado.clicked.connect(self.cambiar_estado_banco_seleccionado)

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
        self.cargar_bancos()

    def _pagina_anterior(self) -> None:
        if self.pagina_actual > 1:
            self.pagina_actual -= 1
            self.cargar_bancos()

    def _pagina_siguiente(self) -> None:
        if self.pagina_actual < self.total_paginas:
            self.pagina_actual += 1
            self.cargar_bancos()

    # ── Lógica de datos ───────────────────────────────────────────────────

    def cargar_bancos(self) -> None:
        session = self.session_factory()
        try:
            resultado = BancoService.listar(
                session,
                texto_busqueda=self.buscar_input.text().strip() or None,
                estado_banco=self.estado_combo.currentData(),
                id_usuario=self.usuario.id_usuario,
                pagina=self.pagina_actual,
                por_pagina=POR_PAGINA,
            )
            self._poblar_tabla(resultado)
        except PermisoDenegadoError:
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar bancos.")
        except Exception:
            logger.exception("Fallo al cargar la lista de bancos")
            QMessageBox.critical(self, "Error de conexión", "No se pudo cargar la lista de bancos.")
        finally:
            session.close()

    def _poblar_tabla(self, resultado: dict) -> None:
        bancos: list[Banco] = resultado["items"]
        self.tabla.setRowCount(len(bancos))
        for fila, b in enumerate(bancos):
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(b.id_banco)))
            self.tabla.setItem(fila, 1, QTableWidgetItem(b.codigo_banco or ""))
            self.tabla.setItem(fila, 2, QTableWidgetItem(b.nombre_banco or ""))
            self.tabla.setItem(fila, 3, QTableWidgetItem(b.tipo_banco or ""))
            self.tabla.setItem(fila, 4, QTableWidgetItem(b.identificacion_banco or ""))
            self.tabla.setItem(fila, 5, QTableWidgetItem(b.numero_telefono_banco or ""))
            self.tabla.setItem(fila, 6, QTableWidgetItem(b.correo_banco or ""))

            estado_banco = b.estado_banco or "ACTIVO"
            color_estado = COLOR_SUCCESS if estado_banco.upper() == "ACTIVO" else COLOR_DANGER
            badge = EstadoBadge(estado_banco.capitalize(), color_estado)
            self.tabla.setCellWidget(fila, 7, badge)

        total = resultado["total"]
        self.total_paginas = max(1, -(-total // POR_PAGINA))
        self.pagina_actual = min(self.pagina_actual, self.total_paginas)

        self.lbl_total.setText(f"{total} banco{'s' if total != 1 else ''}")
        self.lbl_pagina.setText(f"Página {self.pagina_actual} de {self.total_paginas}")
        self.btn_anterior.setEnabled(self.pagina_actual > 1)
        self.btn_siguiente.setEnabled(self.pagina_actual < self.total_paginas)

    def _filas_para_exportar(self, session) -> list[list]:
        resultado = BancoService.listar(
            session,
            texto_busqueda=self.buscar_input.text().strip() or None,
            estado_banco=self.estado_combo.currentData(),
            id_usuario=self.usuario.id_usuario,
            pagina=1,
            por_pagina=1_000_000,
        )
        bancos = resultado["items"]
        return [
            [
                b.id_banco,
                b.codigo_banco,
                b.nombre_banco,
                b.tipo_banco,
                b.identificacion_banco,
                b.numero_telefono_banco,
                b.correo_banco,
                b.estado_banco,
            ]
            for b in bancos
        ]

    def exportar_excel_bancos(self) -> None:
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar bancos", "bancos.xlsx", "Excel (*.xlsx)")
        if not ruta:
            return

        session = self.session_factory()
        try:
            filas = self._filas_para_exportar(session)
            exportar_excel(ruta, COLS_VISIBLES, filas)
            QMessageBox.information(self, "Exportación completa", f"Se exportaron {len(filas)} bancos a:\n{ruta}")
        except PermisoDenegadoError:
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar bancos.")
        except Exception:
            logger.exception("Fallo al exportar la lista de bancos a Excel")
            QMessageBox.critical(self, "Error", "No se pudo exportar la lista de bancos.")
        finally:
            session.close()

    def exportar_pdf_bancos(self) -> None:
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar bancos", "bancos.pdf", "PDF (*.pdf)")
        if not ruta:
            return

        session = self.session_factory()
        try:
            filas = self._filas_para_exportar(session)

            filtros = {}
            texto_busqueda = self.buscar_input.text().strip()
            filtros["Búsqueda"] = texto_busqueda if texto_busqueda else "Todos"
            filtros["Estado"] = self.estado_combo.currentText()

            col_widths = [0.5, 1.0, 2.5, 1.2, 1.5, 1.3, 2.0, 1.0]

            exportar_pdf(
                ruta,
                "Reporte de Bancos",
                COLS_VISIBLES,
                filas,
                filtros=filtros,
                col_widths=col_widths,
            )
            QMessageBox.information(self, "Exportación completa", f"Se exportaron {len(filas)} bancos a:\n{ruta}")
        except PermisoDenegadoError:
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar bancos.")
        except Exception:
            logger.exception("Fallo al exportar la lista de bancos a PDF")
            QMessageBox.critical(self, "Error", "No se pudo exportar la lista de bancos.")
        finally:
            session.close()

    def _fila_seleccionada_id(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            QMessageBox.information(self, "Selección requerida", "Selecciona un banco de la lista.")
            return None
        item = self.tabla.item(filas[0].row(), 0)
        if item is None:
            QMessageBox.warning(self, "Error", "No se pudo obtener el ID del banco seleccionado.")
            return None
        return int(item.text())

    def nuevo_banco(self) -> None:
        session = self.session_factory()
        try:
            dialogo = BancoFormDialog(session, parent=self)
            if dialogo.exec():
                datos = dialogo.get_data()
                datos["creado_por"] = self.usuario.id_usuario
                BancoService.crear(session, **datos)
                self.cargar_bancos()
        except IntegrityError:
            session.rollback()
            QMessageBox.warning(
                self, "Dato duplicado", "El código o la identificación ya están registrados en otro banco."
            )
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para crear bancos.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al crear banco")
            QMessageBox.critical(self, "Error", "No se pudo crear el banco.")
        finally:
            session.close()

    def editar_banco(self) -> None:
        id_banco = self._fila_seleccionada_id()
        if id_banco is None:
            return

        session = self.session_factory()
        try:
            banco = session.get(Banco, id_banco)
            dialogo = BancoFormDialog(session, banco, parent=self)
            if dialogo.exec():
                BancoService.actualizar(session, id_banco, id_usuario=self.usuario.id_usuario, **dialogo.get_data())
                self.cargar_bancos()
        except IntegrityError:
            session.rollback()
            QMessageBox.warning(
                self, "Dato duplicado", "El código o la identificación ya están registrados en otro banco."
            )
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para editar bancos.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al editar banco")
            QMessageBox.critical(self, "Error", "No se pudo guardar los cambios del banco.")
        finally:
            session.close()

    def cambiar_estado_banco_seleccionado(self) -> None:
        id_banco = self._fila_seleccionada_id()
        if id_banco is None:
            return

        session = self.session_factory()
        try:
            banco = session.get(Banco, id_banco)
            estado_actual = banco.estado_banco or "ACTIVO"
            nuevo_estado = "INACTIVO" if estado_actual == "ACTIVO" else "ACTIVO"

            respuesta = QMessageBox.question(
                self, "Confirmar", f"¿Cambiar el estado del banco '{banco.nombre_banco}' a {nuevo_estado}?"
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return

            BancoService.cambiar_estado(session, id_banco, nuevo_estado, id_usuario=self.usuario.id_usuario)
            self.cargar_bancos()
        except PermisoDenegadoError:
            session.rollback()
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para cambiar el estado de bancos.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al cambiar el estado del banco %s", id_banco)
            QMessageBox.critical(self, "Error", "No se pudo cambiar el estado del banco.")
        finally:
            session.close()
