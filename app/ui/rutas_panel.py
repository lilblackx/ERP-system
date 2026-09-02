"""Pestaña "Rutas" del módulo Vendedores: catálogo de rutas de reparto/cobranza que
luego se asignan a cada vendedor (VendedorFormDialog). Mismo patrón visual y de
interacción que app/ui/vendedores_panel.py, pero embebido como pestaña (mismo criterio
que RolesPermisosPanel dentro de UsuariosPanel, ver app/ui/usuarios_panel.py) y sin
exportación -- no hay pedido de reporte para este catálogo, solo alta/edición/estado."""

import logging

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer
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
from sqlalchemy.exc import IntegrityError

from app.db.models import Ruta, Usuario
from app.services.permisos import PermisoDenegadoError
from app.services.rutas import RutaService
from app.ui.ruta_form_dialog import RutaFormDialog
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_TEXT_DARK,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MUTED,
    SEARCH_QSS,
    TABLE_QSS,
    EstadoBadge,
    alinear_encabezados,
    aplicar_sombra,
)

logger = logging.getLogger(__name__)

COLS_VISIBLES = ["ID", "Nombre", "Descripción", "Estado"]
COL_ID_INTERNO = 0  # oculto
POR_PAGINA = 20

ESTADOS_FILTRO = [
    ("Todos los estados", None),
    ("Activas", "ACTIVO"),
    ("Inactivas", "INACTIVO"),
]


class RutasPanel(QWidget):
    """Listado de rutas con búsqueda, alta/edición y activar/desactivar -- sin DELETE
    fisico, ver RutaService.eliminar()."""

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.pagina_actual = 1
        self.total_paginas = 1
        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")
        self._setup_ui()

    def cargar(self) -> None:
        self.cargar_rutas()

    # ── Construcción de la UI ─────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        # Margen chico pero no-cero, mismo motivo que RolesPermisosPanel/tab_usuarios en
        # UsuariosPanel: con 0 la tabla (con aplicar_sombra) queda pegada al borde de la
        # pestaña sin lugar para pintar su sombra.
        root.setContentsMargins(4, 12, 4, 4)
        root.setSpacing(16)

        root.addWidget(self._make_toolbar())
        root.addWidget(self._make_table(), stretch=1)
        root.addWidget(self._make_footer())

    def _make_toolbar(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(
            f"background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 8px; padding: 4px;"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)

        self.buscar_input = QLineEdit()
        self.buscar_input.setPlaceholderText("Buscar ruta…")
        self.buscar_input.addAction(
            qta.icon("fa5s.search", color=COLOR_TEXT_LIGHT), QLineEdit.ActionPosition.LeadingPosition
        )
        self.buscar_input.setObjectName("SearchInput")
        self.buscar_input.setStyleSheet(SEARCH_QSS)
        self.buscar_input.setFixedWidth(220)
        self.buscar_input.returnPressed.connect(self._buscar_desde_inicio)
        self.buscar_input.textChanged.connect(self._busqueda_dinamica)

        self.btn_nuevo = QPushButton("Nueva Ruta")
        self.btn_nuevo.setIcon(qta.icon("fa5s.route", color="white"))
        self.btn_nuevo.setStyleSheet(BUTTON_PRIMARY_QSS)
        self.btn_nuevo.clicked.connect(self.nueva_ruta)

        self.estado_combo = QComboBox()
        for etiqueta, valor in ESTADOS_FILTRO:
            self.estado_combo.addItem(etiqueta, valor)
        self.estado_combo.currentIndexChanged.connect(self._buscar_desde_inicio)

        h.addWidget(self.buscar_input)
        h.addWidget(self.estado_combo)
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
                3: Qt.AlignmentFlag.AlignCenter,
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
        self.tabla.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.tabla.setColumnWidth(3, 110)
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

        self.lbl_total = QLabel("Cargando…")
        self.lbl_total.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")

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

        btn_editar = QPushButton("Editar seleccionada")
        btn_editar.setIcon(qta.icon("fa5s.edit", color=COLOR_TEXT_DARK))
        btn_editar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_editar.clicked.connect(self.editar_ruta)

        btn_estado = QPushButton("Cambiar estado")
        btn_estado.setIcon(qta.icon("fa5s.sync-alt", color=COLOR_TEXT_DARK))
        btn_estado.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_estado.clicked.connect(self.cambiar_estado_ruta_seleccionada)

        h.addWidget(self.lbl_total)
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
        self.cargar_rutas()

    def _pagina_anterior(self) -> None:
        if self.pagina_actual > 1:
            self.pagina_actual -= 1
            self.cargar_rutas()

    def _pagina_siguiente(self) -> None:
        if self.pagina_actual < self.total_paginas:
            self.pagina_actual += 1
            self.cargar_rutas()

    # ── Lógica de datos ───────────────────────────────────────────────────

    def cargar_rutas(self) -> None:
        session = self.session_factory()
        try:
            resultado = RutaService.listar(
                session,
                self.buscar_input.text().strip() or None,
                id_usuario=self.usuario.id_usuario,
                estado_ruta=self.estado_combo.currentData(),
                pagina=self.pagina_actual,
                por_pagina=POR_PAGINA,
            )
            self._poblar_tabla(resultado)
        except PermisoDenegadoError:
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar rutas.")
        except Exception:
            logger.exception("Fallo al cargar la lista de rutas")
            QMessageBox.critical(self, "Error de conexión", "No se pudo cargar la lista de rutas.")
        finally:
            session.close()

    def _poblar_tabla(self, resultado: dict) -> None:
        rutas: list[Ruta] = resultado["items"]
        self.tabla.setRowCount(len(rutas))
        for fila, r in enumerate(rutas):
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(r.id_ruta)))
            self.tabla.setItem(fila, 1, QTableWidgetItem(r.nombre_ruta or ""))
            self.tabla.setItem(fila, 2, QTableWidgetItem(r.descripcion_ruta or ""))

            estado_ruta = r.estado_ruta or "ACTIVO"
            color_estado = COLOR_SUCCESS if estado_ruta.upper() == "ACTIVO" else COLOR_DANGER
            badge = EstadoBadge(estado_ruta.capitalize(), color_estado)
            self.tabla.setCellWidget(fila, 3, badge)

        total = resultado["total"]
        self.total_paginas = max(1, -(-total // POR_PAGINA))  # ceil sin importar math
        self.pagina_actual = min(self.pagina_actual, self.total_paginas)

        self.lbl_total.setText(f"{total} ruta{'s' if total != 1 else ''}")
        self.lbl_pagina.setText(f"Página {self.pagina_actual} de {self.total_paginas}")
        self.btn_anterior.setEnabled(self.pagina_actual > 1)
        self.btn_siguiente.setEnabled(self.pagina_actual < self.total_paginas)

    def _fila_seleccionada_id(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            QMessageBox.information(self, "Selección requerida", "Selecciona una ruta de la lista.")
            return None
        return int(self.tabla.item(filas[0].row(), 0).text())

    def nueva_ruta(self) -> None:
        session = self.session_factory()
        try:
            dialogo = RutaFormDialog(parent=self)
            if dialogo.exec():
                datos = dialogo.get_data()
                datos["creado_por"] = self.usuario.id_usuario
                RutaService.crear(session, **datos)
                self.cargar_rutas()
        except IntegrityError:
            session.rollback()
            QMessageBox.warning(self, "Dato duplicado", "Ya existe una ruta con ese nombre.")
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para crear rutas.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al crear ruta")
            QMessageBox.critical(self, "Error", "No se pudo crear la ruta.")
        finally:
            session.close()

    def editar_ruta(self) -> None:
        id_ruta = self._fila_seleccionada_id()
        if id_ruta is None:
            return

        session = self.session_factory()
        try:
            ruta = RutaService.obtener(session, id_ruta, id_usuario=self.usuario.id_usuario)
            dialogo = RutaFormDialog(ruta, parent=self)
            if dialogo.exec():
                RutaService.actualizar(session, id_ruta, id_usuario=self.usuario.id_usuario, **dialogo.get_data())
                self.cargar_rutas()
        except IntegrityError:
            session.rollback()
            QMessageBox.warning(self, "Dato duplicado", "Ya existe una ruta con ese nombre.")
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para editar rutas.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al editar ruta")
            QMessageBox.critical(self, "Error", "No se pudo guardar los cambios de la ruta.")
        finally:
            session.close()

    def cambiar_estado_ruta_seleccionada(self) -> None:
        id_ruta = self._fila_seleccionada_id()
        if id_ruta is None:
            return

        session = self.session_factory()
        try:
            ruta = RutaService.obtener(session, id_ruta, id_usuario=self.usuario.id_usuario)
            estado_actual = ruta.estado_ruta or "ACTIVO"
            nuevo_estado = "INACTIVO" if estado_actual == "ACTIVO" else "ACTIVO"

            respuesta = QMessageBox.question(
                self, "Confirmar", f"¿Cambiar el estado de la ruta '{ruta.nombre_ruta}' a {nuevo_estado}?"
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return

            RutaService.cambiar_estado(session, id_ruta, nuevo_estado, id_usuario=self.usuario.id_usuario)
            self.cargar_rutas()
        except PermisoDenegadoError:
            session.rollback()
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para cambiar el estado de rutas.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al cambiar el estado de la ruta %s", id_ruta)
            QMessageBox.critical(self, "Error", "No se pudo cambiar el estado de la ruta.")
        finally:
            session.close()
