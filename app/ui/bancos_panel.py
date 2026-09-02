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
from sqlalchemy.exc import IntegrityError

from app.db.models import Banco, Usuario
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import BancoService
from app.ui.banco_form_dialog import BancoFormDialog
from app.ui.message_box import MessageBox
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
    "INACTIVO": "#dc3545",  # Rojo para estado inactivo
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

        self.btn_anterior = QPushButton()
        self.btn_anterior.setIcon(qta.icon("fa5s.chevron-left", color=COLOR_TEXT_DARK))
        self.btn_anterior.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_anterior.setFixedWidth(40)
        self.btn_anterior.setEnabled(False)
        self.btn_anterior.clicked.connect(self.pagina_anterior)

        self.btn_siguiente = QPushButton()
        self.btn_siguiente.setIcon(qta.icon("fa5s.chevron-right", color=COLOR_TEXT_DARK))
        self.btn_siguiente.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_siguiente.setFixedWidth(40)
        self.btn_siguiente.setEnabled(False)
        self.btn_siguiente.clicked.connect(self.pagina_siguiente)

        # Sin boton "Eliminar" a proposito -- igual que vendedores/rutas/cuentas
        # bancarias, un banco nunca se borra fisicamente (ver BancoService.eliminar_banco,
        # que siempre lanza ValueError). "Cambiar estado" es la unica forma de retirarlo
        # de circulacion, preservando el historial de las cuentas bancarias que lo
        # referencian.
        self.btn_editar = QPushButton("Editar seleccionado")
        self.btn_editar.setIcon(qta.icon("fa5s.edit", color=COLOR_TEXT_DARK))
        self.btn_editar.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_editar.setEnabled(False)
        self.btn_editar.clicked.connect(self.editar_banco)

        self.btn_cambiar_estado = QPushButton("Cambiar estado")
        self.btn_cambiar_estado.setIcon(qta.icon("fa5s.sync-alt", color=COLOR_TEXT_DARK))
        self.btn_cambiar_estado.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_cambiar_estado.setEnabled(False)
        self.btn_cambiar_estado.clicked.connect(self.cambiar_estado_banco)

        h.addWidget(self.lbl_paginacion)
        h.addWidget(self.btn_anterior)
        h.addWidget(self.btn_siguiente)
        h.addStretch()
        h.addWidget(self.btn_editar)
        h.addWidget(self.btn_cambiar_estado)
        return w

    # ── Carga de datos ─────────────────────────────────────────────────────

    def cargar_bancos(self):
        """Carga la lista de bancos via BancoService (antes hacia session.query(Banco)
        directo, sin pasar por require_permiso -- cualquier usuario autenticado podia
        ver/crear/editar/"eliminar" bancos sin importar su rol; hallazgo de auditoria,
        2026-09-02). Bancos es un catalogo chico (a diferencia de clientes/vendedores),
        asi que se sigue filtrando/paginando del lado de Python sobre la lista completa
        en vez de sumarle paginacion al servicio."""
        session = self.session_factory()
        try:
            bancos = BancoService.listar_bancos(session, id_usuario=self.usuario.id_usuario)

            estado_filtro = self.estado_combo.currentData()
            if estado_filtro:
                bancos = [b for b in bancos if b.estado_banco == estado_filtro]

            busqueda = self.buscar_input.text().strip().lower()
            if busqueda:
                bancos = [
                    b
                    for b in bancos
                    if busqueda in (b.codigo_banco or "").lower()
                    or busqueda in (b.nombre_banco or "").lower()
                    or busqueda in (b.identificacion_banco or "").lower()
                    or busqueda in (b.numero_telefono_banco or "").lower()
                ]

            self.bancos = bancos
            self._actualizar_tabla()
            self._actualizar_paginacion()
        except PermisoDenegadoError:
            self.bancos = []
            self._actualizar_tabla()
            self._actualizar_paginacion()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar bancos.")
        except Exception:
            logger.exception("Fallo al cargar la lista de bancos")
            self.bancos = []
            self._actualizar_tabla()
            self._actualizar_paginacion()
            MessageBox.critical(self, "Error de conexión", "No se pudo cargar la lista de bancos.")
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
            estado = banco.estado_banco or "ACTIVO"
            color_estado = COLORES_ESTADO_BANCO.get(estado, COLOR_TEXT_MUTED)
            estado_widget = EstadoBadge(estado.capitalize(), color_estado)
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
                BancoService.crear_banco(session, **data, creado_por=self.usuario.id_usuario)
                self.cargar_bancos()
        except IntegrityError:
            session.rollback()
            MessageBox.warning(self, "Dato duplicado", "Ya existe un banco con esa identificación (RIF).")
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para crear bancos.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al crear banco")
            MessageBox.critical(self, "Error", "No se pudo crear el banco.")
        finally:
            session.close()

    def editar_banco(self):
        """Abre el diálogo para editar el banco seleccionado."""
        banco_id = self._id_seleccionado()
        if banco_id is None:
            return

        session = self.session_factory()
        try:
            banco = session.get(Banco, banco_id)
            if banco is None:
                return
            dialog = BancoFormDialog(session, banco, parent=self)
            if dialog.exec():
                data = dialog.get_data()
                BancoService.actualizar_banco(session, banco_id, id_usuario=self.usuario.id_usuario, **data)
                self.cargar_bancos()
        except IntegrityError:
            session.rollback()
            MessageBox.warning(self, "Dato duplicado", "Ya existe un banco con esa identificación (RIF).")
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para editar bancos.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al editar banco")
            MessageBox.critical(self, "Error", "No se pudo guardar los cambios del banco.")
        finally:
            session.close()

    def cambiar_estado_banco(self):
        """Cambia el estado del banco seleccionado (ACTIVO <-> INACTIVO)."""
        banco_id = self._id_seleccionado()
        if banco_id is None:
            return

        session = self.session_factory()
        try:
            banco = session.get(Banco, banco_id)
            if banco is None:
                return
            nuevo_estado = "INACTIVO" if banco.estado_banco == "ACTIVO" else "ACTIVO"
            respuesta = MessageBox.question(
                self, "Confirmar", f"¿Cambiar el estado del banco '{banco.nombre_banco}' a {nuevo_estado}?"
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return

            BancoService.cambiar_estado_banco(session, banco_id, nuevo_estado, id_usuario=self.usuario.id_usuario)
            self.cargar_bancos()
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para cambiar el estado de bancos.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al cambiar el estado del banco %s", banco_id)
            MessageBox.critical(self, "Error", "No se pudo cambiar el estado del banco.")
        finally:
            session.close()

    def _id_seleccionado(self) -> int | None:
        row = self.tabla.currentRow()
        if row < 0:
            MessageBox.information(self, "Selección requerida", "Selecciona un banco de la lista.")
            return None
        item = self.tabla.item(row, COL_ID_INTERNO)
        return int(item.text()) if item is not None else None

    def _on_selection_changed(self):
        """Habilita/deshabilita los botones de editar y cambiar estado según la selección."""
        has_selection = self.tabla.currentRow() >= 0
        self.btn_editar.setEnabled(has_selection)
        self.btn_cambiar_estado.setEnabled(has_selection)
