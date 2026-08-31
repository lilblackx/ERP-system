"""
Panel completo del módulo Usuarios: dos pestañas -- "Usuarios" (listado, alta/edición,
activar/desactivar, desbloqueo manual) y "Roles y Permisos" (RolesPermisosPanel). Mismo
patrón visual que app/ui/clientes_panel.py/vendedores_panel.py (paleta y tipografía de
app/ui/styles.py), pero con QTabWidget porque el modulo cubre dos conceptos distintos
(cuentas + la matriz de permisos que las gobierna) bajo una sola entrada de sidebar.
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.db.models import Usuario
from app.services.permisos import PermisoDenegadoError
from app.services.usuarios import UsuarioService
from app.ui.roles_permisos_panel import RolesPermisosPanel
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
from app.ui.usuario_form_dialog import UsuarioFormDialog

logger = logging.getLogger(__name__)

COLS_VISIBLES = ["ID", "Usuario", "Nombre", "Rol", "Estado"]
COL_ID_INTERNO = 0  # oculto


class UsuariosPanel(QWidget):
    """Panel principal del módulo Usuarios."""

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.setObjectName("ContentArea")
        self._setup_ui()
        QTimer.singleShot(100, self.cargar_usuarios)

    def showEvent(self, event: QShowEvent) -> None:
        # Mismo motivo que en el resto de los paneles (ver DashboardPanel.showEvent):
        # MainWindow cachea el panel via QStackedWidget, asi que sin esto volver a
        # "Usuarios" desde otro modulo mostraba el listado viejo.
        super().showEvent(event)
        self.cargar_usuarios()
        if self.tabs.currentWidget() is self.tab_roles:
            self.tab_roles.cargar()

    # ── Construcción de la UI ─────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        root.addWidget(self._make_header())

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(TABS_QSS)
        self.tab_usuarios = self._make_tab_usuarios()
        self.tab_roles = RolesPermisosPanel(self.session_factory, self.usuario)
        self.tabs.addTab(self.tab_usuarios, "Usuarios")
        self.tabs.addTab(self.tab_roles, "Roles y Permisos")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, stretch=1)

        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

    def _on_tab_changed(self, indice: int) -> None:
        if self.tabs.widget(indice) is self.tab_roles:
            self.tab_roles.cargar()

    def _make_header(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("Usuarios")
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

    def _make_tab_usuarios(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        # Margen chico pero no-cero: con 0 la tabla (con aplicar_sombra) quedaba pegada
        # al borde de la pestana, sin lugar para pintar su sombra -- ver el mismo fix en
        # RolesPermisosPanel._setup_ui() (reportado por el usuario, 2026-08-27).
        v.setContentsMargins(4, 12, 4, 4)
        v.setSpacing(16)

        v.addWidget(self._make_toolbar())
        v.addWidget(self._make_table(), stretch=1)
        v.addWidget(self._make_footer())
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
        self.buscar_input.setPlaceholderText("Buscar por usuario o nombre…")
        self.buscar_input.addAction(
            qta.icon("fa5s.search", color=COLOR_TEXT_LIGHT), QLineEdit.ActionPosition.LeadingPosition
        )
        self.buscar_input.setObjectName("SearchInput")
        self.buscar_input.setStyleSheet(SEARCH_QSS)
        self.buscar_input.setFixedWidth(280)
        self.buscar_input.returnPressed.connect(self.cargar_usuarios)
        self.buscar_input.textChanged.connect(self._busqueda_dinamica)

        self.btn_nuevo = QPushButton("Nuevo Usuario")
        self.btn_nuevo.setIcon(qta.icon("fa5s.user-plus", color="white"))
        self.btn_nuevo.setStyleSheet(BUTTON_PRIMARY_QSS)
        self.btn_nuevo.clicked.connect(self.nuevo_usuario)

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
                4: Qt.AlignmentFlag.AlignCenter,
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
        self.tabla.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.tabla.setColumnWidth(4, 110)
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
        btn_editar.clicked.connect(self.editar_usuario)

        btn_estado = QPushButton("Cambiar estado")
        btn_estado.setIcon(qta.icon("fa5s.sync-alt", color=COLOR_TEXT_DARK))
        btn_estado.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_estado.clicked.connect(self.cambiar_estado_usuario_seleccionado)

        btn_desbloquear = QPushButton("Desbloquear")
        btn_desbloquear.setIcon(qta.icon("fa5s.unlock", color=COLOR_TEXT_DARK))
        btn_desbloquear.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_desbloquear.clicked.connect(self.desbloquear_usuario_seleccionado)

        h.addWidget(self.lbl_pagina)
        h.addStretch()
        h.addWidget(btn_editar)
        h.addWidget(btn_estado)
        h.addWidget(btn_desbloquear)
        return w

    # ── Timer para búsqueda dinámica (300 ms debounce) ────────────────────

    def _busqueda_dinamica(self) -> None:
        if not hasattr(self, "_timer_busqueda"):
            self._timer_busqueda = QTimer()
            self._timer_busqueda.setSingleShot(True)
            self._timer_busqueda.timeout.connect(self.cargar_usuarios)
        self._timer_busqueda.start(300)

    # ── Lógica de datos ───────────────────────────────────────────────────

    def cargar_usuarios(self) -> None:
        session = self.session_factory()
        try:
            usuarios = UsuarioService.listar_usuarios(
                session,
                texto_busqueda=self.buscar_input.text().strip() or None,
                id_usuario=self.usuario.id_usuario,
            )
            self._poblar_tabla(usuarios)
        except PermisoDenegadoError:
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar usuarios.")
        except Exception:
            logger.exception("Fallo al cargar la lista de usuarios")
            QMessageBox.critical(self, "Error de conexión", "No se pudo cargar la lista de usuarios.")
        finally:
            session.close()

    def _poblar_tabla(self, usuarios: list[dict]) -> None:
        self.tabla.setRowCount(len(usuarios))
        for fila, u in enumerate(usuarios):
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(u["id_usuario"])))
            self.tabla.setItem(fila, 1, QTableWidgetItem(u["nombre_usuario"]))
            self.tabla.setItem(fila, 2, QTableWidgetItem(u["nombre_completo"] or "—"))
            self.tabla.setItem(fila, 3, QTableWidgetItem(u["rol"] or "Sin rol"))

            estado = u["estado"] or "ACTIVO"
            color_estado = COLOR_SUCCESS if estado.upper() == "ACTIVO" else COLOR_DANGER
            badge = EstadoBadge(estado.capitalize(), color_estado)
            self.tabla.setCellWidget(fila, 4, badge)

        total = len(usuarios)
        self.lbl_total.setText(f"{total} usuario{'s' if total != 1 else ''}")
        self.lbl_pagina.setText(f"Mostrando {total} registro{'s' if total != 1 else ''}")

    def _fila_seleccionada_id(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            QMessageBox.information(self, "Selección requerida", "Selecciona un usuario de la lista.")
            return None
        return int(self.tabla.item(filas[0].row(), 0).text())

    def nuevo_usuario(self) -> None:
        session = self.session_factory()
        try:
            dialogo = UsuarioFormDialog(session, self.usuario.id_usuario, parent=self)
            if dialogo.exec():
                datos = dialogo.get_data()
                UsuarioService.crear_usuario(
                    session, **datos, clave=dialogo.get_clave(), realizado_por=self.usuario.id_usuario
                )
                self.cargar_usuarios()
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para crear usuarios.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al crear usuario")
            QMessageBox.critical(self, "Error", "No se pudo crear el usuario.")
        finally:
            session.close()

    def editar_usuario(self) -> None:
        id_usuario = self._fila_seleccionada_id()
        if id_usuario is None:
            return

        session = self.session_factory()
        try:
            usuario = session.get(Usuario, id_usuario)
            if usuario is None:
                QMessageBox.warning(self, "No encontrado", "El usuario seleccionado ya no existe.")
                return
            dialogo = UsuarioFormDialog(session, self.usuario.id_usuario, usuario, parent=self)
            if dialogo.exec():
                UsuarioService.editar_usuario(
                    session,
                    id_usuario,
                    datos=dialogo.get_data(),
                    nueva_clave=dialogo.get_clave(),
                    realizado_por=self.usuario.id_usuario,
                )
                self.cargar_usuarios()
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para editar usuarios.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al editar usuario %s", id_usuario)
            QMessageBox.critical(self, "Error", "No se pudo guardar los cambios del usuario.")
        finally:
            session.close()

    def cambiar_estado_usuario_seleccionado(self) -> None:
        id_usuario = self._fila_seleccionada_id()
        if id_usuario is None:
            return
        if id_usuario == self.usuario.id_usuario:
            QMessageBox.warning(self, "Acción no permitida", "No puedes cambiar el estado de tu propio usuario.")
            return

        session = self.session_factory()
        try:
            usuario = session.get(Usuario, id_usuario)
            if usuario is None:
                QMessageBox.warning(self, "No encontrado", "El usuario seleccionado ya no existe.")
                return
            estado_actual = usuario.estado or "ACTIVO"
            nuevo_estado = "INACTIVO" if estado_actual == "ACTIVO" else "ACTIVO"

            respuesta = QMessageBox.question(
                self, "Confirmar", f"¿Cambiar el estado de '{usuario.nombre_usuario}' a {nuevo_estado}?"
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return

            UsuarioService.cambiar_estado(session, id_usuario, nuevo_estado, realizado_por=self.usuario.id_usuario)
            self.cargar_usuarios()
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "No se pudo cambiar el estado", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para cambiar el estado de usuarios.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al cambiar el estado del usuario %s", id_usuario)
            QMessageBox.critical(self, "Error", "No se pudo cambiar el estado del usuario.")
        finally:
            session.close()

    def desbloquear_usuario_seleccionado(self) -> None:
        id_usuario = self._fila_seleccionada_id()
        if id_usuario is None:
            return

        session = self.session_factory()
        try:
            usuario = session.get(Usuario, id_usuario)
            if usuario is None:
                QMessageBox.warning(self, "No encontrado", "El usuario seleccionado ya no existe.")
                return
            if usuario.bloqueado_desde is None:
                QMessageBox.information(self, "Sin bloqueo", f"'{usuario.nombre_usuario}' no está bloqueado.")
                return

            UsuarioService.desbloquear_usuario(session, id_usuario, realizado_por=self.usuario.id_usuario)
            QMessageBox.information(self, "Usuario desbloqueado", f"Se desbloqueó a '{usuario.nombre_usuario}'.")
            self.cargar_usuarios()
        except PermisoDenegadoError:
            session.rollback()
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para desbloquear usuarios.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al desbloquear el usuario %s", id_usuario)
            QMessageBox.critical(self, "Error", "No se pudo desbloquear el usuario.")
        finally:
            session.close()
