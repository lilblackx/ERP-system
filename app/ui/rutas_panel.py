"""Pestaña "Rutas" del módulo Vendedores: catálogo de rutas de reparto/cobranza que
luego se asignan a cada vendedor (VendedorFormDialog). Mismo patrón visual y de
interacción que app/ui/vendedores_panel.py, pero embebido como pestaña (mismo criterio
que RolesPermisosPanel dentro de UsuariosPanel, ver app/ui/usuarios_panel.py) y sin
exportación -- no hay pedido de reporte para este catálogo, solo alta/edición/estado."""

import logging

import qtawesome as qta
from PySide6.QtCore import Qt
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
from app.ui.carga_asincrona import CargaAsincronaMixin
from app.ui.message_box import MessageBox
from app.ui.paginacion import ControlPaginacion, MixinPaginacion
from app.ui.permisos_ui import MixinPermisos
from app.ui.ruta_form_dialog import RutaFormDialog
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_TEXT_DARK,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MUTED,
    SEARCH_QSS,
    TABLE_QSS,
    EstadoBadge,
    alinear_encabezados,
    aplicar_fondo_panel,
    aplicar_sombra,
    estilizar_tarjeta,
)

logger = logging.getLogger(__name__)

COLS_VISIBLES = ["ID", "NOMBRE", "DESCRIPCIÓN", "ESTADO"]
COL_ID_INTERNO = 0  # oculto
POR_PAGINA = 20

ESTADOS_FILTRO = [
    ("Todos los estados", None),
    ("Activas", "ACTIVO"),
    ("Inactivas", "INACTIVO"),
]


def _tarea_listar_rutas(session, **filtros):
    """Corre en un hilo aparte (ver carga_asincrona.py): solo consulta, sin tocar widgets."""
    return RutaService.listar(session, **filtros)


class RutasPanel(CargaAsincronaMixin, MixinPermisos, MixinPaginacion, QWidget):
    """Listado de rutas con búsqueda, alta/edición y activar/desactivar -- sin DELETE
    fisico, ver RutaService.eliminar()."""

    recurso_permisos = "rutas"

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        aplicar_fondo_panel(self)
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
        estilizar_tarjeta(w, padding=4, radio=8)
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)

        self.buscar_input = QLineEdit()
        self.buscar_input.setPlaceholderText("Buscar ruta…")
        self.buscar_input.addAction(
            qta.icon("fa5s.search", color=COLOR_TEXT_LIGHT),
            QLineEdit.ActionPosition.LeadingPosition,
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
        if self._puede("crear"):
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

        self.paginacion = ControlPaginacion()
        self.paginacion.pagina_cambiada.connect(lambda _pagina: self.cargar_rutas())

        btn_editar = QPushButton("Editar seleccionada")
        btn_editar.setIcon(qta.icon("fa5s.edit", color=COLOR_TEXT_DARK))
        btn_editar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_editar.clicked.connect(self.editar_ruta)

        btn_estado = QPushButton("Cambiar estado")
        btn_estado.setIcon(qta.icon("fa5s.sync-alt", color=COLOR_TEXT_DARK))
        btn_estado.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_estado.clicked.connect(self.cambiar_estado_ruta_seleccionada)

        h.addWidget(self.lbl_total)
        h.addWidget(self.paginacion)
        h.addStretch()
        if self._puede("editar"):
            h.addWidget(btn_editar)
        if self._puede("eliminar"):
            h.addWidget(btn_estado)
        return w

    # ── Timer para búsqueda dinámica (300 ms debounce) ────────────────────

    def _busqueda_dinamica(self) -> None:
        self.buscar_con_pausa(self._buscar_tecleando)

    def _buscar_tecleando(self) -> None:
        self.pagina_actual = 1
        self.cargar_rutas(silencioso=True)  # no enciende la barra de carga

    def _buscar_desde_inicio(self) -> None:
        self.pagina_actual = 1
        self.cargar_rutas()

    # ── Lógica de datos ───────────────────────────────────────────────────

    def cargar_rutas(self, silencioso: bool = False, sincrono: bool = False) -> None:
        self.cargar_async(
            "rutas",
            _tarea_listar_rutas,
            self._poblar_tabla,
            texto_error="No se pudo cargar la lista de rutas.",
            texto_sin_permiso="No tienes permiso para consultar rutas.",
            silencioso=silencioso,
            sincrono=sincrono,
            texto_busqueda=self.buscar_input.text().strip() or None,
            id_usuario=self.usuario.id_usuario,
            estado_ruta=self.estado_combo.currentData(),
            pagina=self.pagina_actual,
            por_pagina=POR_PAGINA,
        )

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
        # pagina y total_paginas vienen ya corregidos por el servicio (paginar()).
        self.paginacion.actualizar_desde(resultado)

        self.lbl_total.setText(f"{total} ruta{'s' if total != 1 else ''}")

    def _fila_seleccionada_id(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            MessageBox.information(self, "Selección requerida", "Selecciona una ruta de la lista.")
            return None
        return int(self.tabla.item(filas[0].row(), 0).text())

    def nueva_ruta(self) -> None:
        if not self._exigir_permiso("crear", "No tienes permiso para crear rutas."):
            return
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
            MessageBox.warning(self, "Dato duplicado", "Ya existe una ruta con ese nombre.")
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para crear rutas.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al crear ruta")
            MessageBox.critical(self, "Error", "No se pudo crear la ruta.")
        finally:
            session.close()

    def editar_ruta(self) -> None:
        if not self._exigir_permiso("editar", "No tienes permiso para editar rutas."):
            return
        id_ruta = self._fila_seleccionada_id()
        if id_ruta is None:
            return

        session = self.session_factory()
        try:
            ruta = RutaService.obtener(session, id_ruta, id_usuario=self.usuario.id_usuario)
            dialogo = RutaFormDialog(ruta, parent=self)
            if dialogo.exec():
                RutaService.actualizar(
                    session,
                    id_ruta,
                    id_usuario=self.usuario.id_usuario,
                    **dialogo.get_data(),
                )
                self.cargar_rutas()
        except IntegrityError:
            session.rollback()
            MessageBox.warning(self, "Dato duplicado", "Ya existe una ruta con ese nombre.")
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para editar rutas.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al editar ruta")
            MessageBox.critical(self, "Error", "No se pudo guardar los cambios de la ruta.")
        finally:
            session.close()

    def cambiar_estado_ruta_seleccionada(self) -> None:
        if not self._exigir_permiso("eliminar", "No tienes permiso para cambiar el estado de rutas."):
            return
        id_ruta = self._fila_seleccionada_id()
        if id_ruta is None:
            return

        session = self.session_factory()
        try:
            ruta = RutaService.obtener(session, id_ruta, id_usuario=self.usuario.id_usuario)
            estado_actual = ruta.estado_ruta or "ACTIVO"
            nuevo_estado = "INACTIVO" if estado_actual == "ACTIVO" else "ACTIVO"

            respuesta = MessageBox.question(
                self,
                "Confirmar",
                f"¿Cambiar el estado de la ruta '{ruta.nombre_ruta}' a {nuevo_estado}?",
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return

            RutaService.cambiar_estado(session, id_ruta, nuevo_estado, id_usuario=self.usuario.id_usuario)
            self.cargar_rutas()
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(
                self,
                "Sin permiso",
                "No tienes permiso para cambiar el estado de rutas.",
            )
        except Exception:
            session.rollback()
            logger.exception("Fallo al cambiar el estado de la ruta %s", id_ruta)
            MessageBox.critical(self, "Error", "No se pudo cambiar el estado de la ruta.")
        finally:
            session.close()
