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
from app.services.bloqueo import esta_bloqueado
from app.services.permisos import PermisoDenegadoError, RolService
from app.services.usuarios import UsuarioService
from app.services.vendedores import VendedorService
from app.ui.carga_asincrona import CargaAsincronaMixin, sesion_para_dialogo
from app.ui.message_box import MessageBox
from app.ui.permisos_ui import MixinPermisos
from app.ui.roles_permisos_panel import RolesPermisosPanel
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
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
    aplicar_fondo_panel,
    aplicar_sombra,
    dar_ancho_a_texto,
    estilizar_tarjeta,
)
from app.ui.usuario_form_dialog import UsuarioFormDialog

logger = logging.getLogger(__name__)

COLS_VISIBLES = ["ID", "USUARIO", "NOMBRE", "ROL", "ESTADO"]
COL_ID_INTERNO = 0  # oculto


def _tarea_listar_usuarios(session, **filtros):
    """Corre en un hilo aparte (ver carga_asincrona.py): solo consulta, sin tocar widgets."""
    return UsuarioService.listar_usuarios(session, **filtros)


def _tarea_form_usuario(session, session_factory, id_actor: int | None, id_usuario: int | None = None) -> dict:
    """Corre en un hilo aparte (ver carga_asincrona.py): roles y vendedores activos (y, al editar, el usuario) para
    el formulario. Devuelve la sesion usada, que el panel usa para guardar y cierra al terminar."""
    sesion = sesion_para_dialogo(session_factory)
    try:
        try:
            roles = RolService.listar_roles(sesion, id_usuario=id_actor)
        except PermisoDenegadoError:
            roles = []
        try:
            # por_pagina alto: el combo necesita TODOS los vendedores activos, no un recorte de pagina.
            vendedores = VendedorService.listar(sesion, id_usuario=id_actor, estado_vendedor="ACTIVO", por_pagina=1000)[
                "items"
            ]
        except PermisoDenegadoError:
            vendedores = []
        usuario = sesion.get(Usuario, id_usuario) if id_usuario is not None else None
        return {
            "session": sesion,
            "usuario": usuario,
            "precargado": {"roles": roles, "vendedores": vendedores},
        }
    except BaseException:
        sesion.close()
        raise


class UsuariosPanel(CargaAsincronaMixin, MixinPermisos, QWidget):
    """Panel principal del módulo Usuarios."""

    recurso_permisos = "usuarios"

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

        aplicar_fondo_panel(self)

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
        estilizar_tarjeta(w, padding=4, radio=8)
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)

        self.buscar_input = QLineEdit()
        self.buscar_input.setPlaceholderText("Buscar por usuario o nombre…")
        self.buscar_input.addAction(
            qta.icon("fa5s.search", color=COLOR_TEXT_LIGHT),
            QLineEdit.ActionPosition.LeadingPosition,
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
        dar_ancho_a_texto(self.tabla)
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
        if self._puede("editar"):
            h.addWidget(btn_editar)
        if self._puede("editar"):
            h.addWidget(btn_estado)
        if self._puede("editar"):
            h.addWidget(btn_desbloquear)
        return w

    # ── Timer para búsqueda dinámica (300 ms debounce) ────────────────────

    def _busqueda_dinamica(self) -> None:
        self.buscar_con_pausa(self._buscar_tecleando)

    def _buscar_tecleando(self) -> None:
        self.cargar_usuarios(silencioso=True)  # no enciende la barra de carga

    # ── Lógica de datos ───────────────────────────────────────────────────

    def cargar_usuarios(self, silencioso: bool = False, sincrono: bool = False) -> None:
        self.cargar_async(
            "usuarios",
            _tarea_listar_usuarios,
            self._poblar_tabla,
            texto_error="No se pudo cargar la lista de usuarios.",
            texto_sin_permiso="No tienes permiso para consultar usuarios.",
            silencioso=silencioso,
            sincrono=sincrono,
            texto_busqueda=self.buscar_input.text().strip() or None,
            id_usuario=self.usuario.id_usuario,
        )

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
            MessageBox.information(self, "Selección requerida", "Selecciona un usuario de la lista.")
            return None
        return int(self.tabla.item(filas[0].row(), 0).text())

    def nuevo_usuario(self) -> None:
        if not self._exigir_permiso("crear", "No tienes permiso para crear usuarios."):
            return
        self.cargar_async(
            "form_usuario",
            _tarea_form_usuario,
            self._abrir_nuevo_usuario,
            texto_error="No se pudo abrir el formulario de usuario.",
            texto_sin_permiso="No tienes permiso para crear usuarios.",
            session_factory=self.session_factory,
            id_actor=self.usuario.id_usuario,
        )

    def _abrir_nuevo_usuario(self, datos_previos: dict) -> None:
        session = datos_previos["session"]
        try:
            dialogo = UsuarioFormDialog(
                session, self.usuario.id_usuario, parent=self, precargado=datos_previos["precargado"]
            )
            if dialogo.exec():
                datos = dialogo.get_data()
                UsuarioService.crear_usuario(
                    session,
                    **datos,
                    clave=dialogo.get_clave(),
                    realizado_por=self.usuario.id_usuario,
                )
                self.cargar_usuarios()
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para crear usuarios.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al crear usuario")
            MessageBox.critical(self, "Error", "No se pudo crear el usuario.")
        finally:
            session.close()

    def editar_usuario(self) -> None:
        if not self._exigir_permiso("editar", "No tienes permiso para editar usuarios."):
            return
        id_usuario = self._fila_seleccionada_id()
        if id_usuario is None:
            return

        self.cargar_async(
            "form_usuario",
            _tarea_form_usuario,
            self._abrir_editar_usuario,
            texto_error="No se pudo abrir el formulario de usuario.",
            texto_sin_permiso="No tienes permiso para editar usuarios.",
            session_factory=self.session_factory,
            id_actor=self.usuario.id_usuario,
            id_usuario=id_usuario,
        )

    def _abrir_editar_usuario(self, datos_previos: dict) -> None:
        session = datos_previos["session"]
        usuario = datos_previos["usuario"]
        try:
            if usuario is None:
                MessageBox.warning(self, "No encontrado", "El usuario seleccionado ya no existe.")
                return
            id_usuario = usuario.id_usuario
            dialogo = UsuarioFormDialog(
                session, self.usuario.id_usuario, usuario, parent=self, precargado=datos_previos["precargado"]
            )
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
            MessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para editar usuarios.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al editar usuario %s", id_usuario)
            MessageBox.critical(self, "Error", "No se pudo guardar los cambios del usuario.")
        finally:
            session.close()

    def cambiar_estado_usuario_seleccionado(self) -> None:
        if not self._exigir_permiso("editar", "No tienes permiso para cambiar el estado de usuarios."):
            return
        id_usuario = self._fila_seleccionada_id()
        if id_usuario is None:
            return
        if id_usuario == self.usuario.id_usuario:
            MessageBox.warning(
                self,
                "Acción no permitida",
                "No puedes cambiar el estado de tu propio usuario.",
            )
            return

        session = self.session_factory()
        try:
            usuario = session.get(Usuario, id_usuario)
            if usuario is None:
                MessageBox.warning(self, "No encontrado", "El usuario seleccionado ya no existe.")
                return
            estado_actual = usuario.estado or "ACTIVO"
            nuevo_estado = "INACTIVO" if estado_actual == "ACTIVO" else "ACTIVO"

            respuesta = MessageBox.question(
                self,
                "Confirmar",
                f"¿Cambiar el estado de '{usuario.nombre_usuario}' a {nuevo_estado}?",
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return

            UsuarioService.cambiar_estado(session, id_usuario, nuevo_estado, realizado_por=self.usuario.id_usuario)
            self.cargar_usuarios()
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, "No se pudo cambiar el estado", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(
                self,
                "Sin permiso",
                "No tienes permiso para cambiar el estado de usuarios.",
            )
        except Exception:
            session.rollback()
            logger.exception("Fallo al cambiar el estado del usuario %s", id_usuario)
            MessageBox.critical(self, "Error", "No se pudo cambiar el estado del usuario.")
        finally:
            session.close()

    def desbloquear_usuario_seleccionado(self) -> None:
        if not self._exigir_permiso("editar", "No tienes permiso para desbloquear usuarios."):
            return
        id_usuario = self._fila_seleccionada_id()
        if id_usuario is None:
            return

        session = self.session_factory()
        try:
            usuario = session.get(Usuario, id_usuario)
            if usuario is None:
                MessageBox.warning(self, "No encontrado", "El usuario seleccionado ya no existe.")
                return
            if not esta_bloqueado(usuario):
                MessageBox.information(
                    self,
                    "Sin bloqueo",
                    f"'{usuario.nombre_usuario}' no está bloqueado.",
                )
                return

            UsuarioService.desbloquear_usuario(session, id_usuario, realizado_por=self.usuario.id_usuario)
            MessageBox.information(
                self,
                "Usuario desbloqueado",
                f"Se desbloqueó a '{usuario.nombre_usuario}'.",
            )
            self.cargar_usuarios()
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para desbloquear usuarios.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al desbloquear el usuario %s", id_usuario)
            MessageBox.critical(self, "Error", "No se pudo desbloquear el usuario.")
        finally:
            session.close()
