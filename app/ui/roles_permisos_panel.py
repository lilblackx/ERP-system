"""Segunda pestaña del módulo Usuarios: gestión de roles y su matriz de permisos.
Backend ya completo (RolService/PermisoService, app/services/permisos.py) desde antes de
esta pantalla -- obtener_matriz_rol()/establecer_permisos_rol() ya devuelven/reciben
exactamente lo que necesita un checkbox-grid, esto solo lo pinta.

ADMIN es un caso especial: bypassa la matriz de permisos por completo (ver
require_permiso() en permisos.py), así que tildar/destildar sus casillas acá no tendría
ningún efecto real -- se deshabilita la edición para ese rol en vez de dejar tildar algo
que después no hace nada."""

import logging
from collections import defaultdict

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from app.db.models import Usuario
from app.services.permisos import PermisoDenegadoError, PermisoService, RolService
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_PRIMARY,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    aplicar_sombra,
)

logger = logging.getLogger(__name__)


class RolesPermisosPanel(QWidget):
    """Lista de roles a la izquierda + checkbox-grid de permisos del rol seleccionado a
    la derecha, agrupado por recurso (una fila de checkboxes por recurso, una casilla por
    acción disponible de ese recurso)."""

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self._rol_seleccionado_id: int | None = None
        self._checkboxes: dict[int, QCheckBox] = {}  # id_permiso -> checkbox
        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")
        self._setup_ui()

    def cargar(self) -> None:
        self._cargar_roles()

    # ── Construcción de la UI ─────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QHBoxLayout(self)
        # Margen chico pero no-cero: con 0 las tarjetas quedaban pegadas al borde de la
        # pestana (y entre si) sin lugar para pintar su sombra/borde redondeado --
        # aplicar_sombra() no tiene margen propio para expandirse, lo recorta el
        # contenedor padre (reportado por el usuario, 2026-08-27).
        root.setContentsMargins(4, 12, 4, 4)
        root.setSpacing(16)

        root.addWidget(self._make_card_roles())
        root.addWidget(self._make_card_matriz(), stretch=1)

    def _make_card_roles(self) -> QWidget:
        card = QWidget()
        card.setFixedWidth(260)
        card.setStyleSheet(f"background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 10px;")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        titulo = QLabel("ROLES")
        titulo.setStyleSheet(
            f"font-size: 11px; font-weight: bold; color: {COLOR_PRIMARY}; letter-spacing: 0.8px; border: none;"
        )
        layout.addWidget(titulo)

        self.lista_roles = QListWidget()
        self.lista_roles.setStyleSheet(
            "QListWidget { border: none; font-size: 13px; }"
            "QListWidget::item { padding: 8px 6px; border-radius: 6px; }"
            f"QListWidget::item:selected {{ background-color: #EFF6FF; color: {COLOR_PRIMARY}; font-weight: 600; }}"
        )
        self.lista_roles.currentItemChanged.connect(self._on_rol_seleccionado)
        layout.addWidget(self.lista_roles, stretch=1)

        botones = QHBoxLayout()
        botones.setSpacing(6)
        self.btn_nuevo_rol = QPushButton()
        self.btn_nuevo_rol.setIcon(qta.icon("fa5s.plus", color=COLOR_TEXT_DARK))
        self.btn_nuevo_rol.setToolTip("Nuevo rol")
        self.btn_nuevo_rol.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_nuevo_rol.clicked.connect(self.nuevo_rol)

        self.btn_editar_rol = QPushButton()
        self.btn_editar_rol.setIcon(qta.icon("fa5s.edit", color=COLOR_TEXT_DARK))
        self.btn_editar_rol.setToolTip("Editar nombre/descripción")
        self.btn_editar_rol.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_editar_rol.clicked.connect(self.editar_rol)

        self.btn_eliminar_rol = QPushButton()
        self.btn_eliminar_rol.setIcon(qta.icon("fa5s.trash-alt", color=COLOR_TEXT_DARK))
        self.btn_eliminar_rol.setToolTip("Eliminar rol")
        self.btn_eliminar_rol.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_eliminar_rol.clicked.connect(self.eliminar_rol)

        botones.addWidget(self.btn_nuevo_rol)
        botones.addWidget(self.btn_editar_rol)
        botones.addWidget(self.btn_eliminar_rol)
        layout.addLayout(botones)
        return card

    def _make_card_matriz(self) -> QWidget:
        card = QWidget()
        card.setStyleSheet(f"background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 10px;")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self.lbl_titulo_matriz = QLabel("Seleccione un rol")
        self.lbl_titulo_matriz.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {COLOR_TEXT_DARK}; border: none;"
        )
        header.addWidget(self.lbl_titulo_matriz)
        header.addStretch()

        self.btn_guardar_matriz = QPushButton("Guardar permisos")
        self.btn_guardar_matriz.setIcon(qta.icon("fa5s.save", color="white"))
        self.btn_guardar_matriz.setStyleSheet(BUTTON_PRIMARY_QSS)
        self.btn_guardar_matriz.clicked.connect(self.guardar_matriz)
        self.btn_guardar_matriz.setEnabled(False)
        header.addWidget(self.btn_guardar_matriz)
        layout.addLayout(header)

        self.lbl_aviso_admin = QLabel(
            "ADMIN tiene acceso total al sistema y no usa esta matriz -- siempre bypassa "
            "cualquier chequeo de permisos, tildar/destildar acá no cambiaría nada."
        )
        self.lbl_aviso_admin.setWordWrap(True)
        self.lbl_aviso_admin.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED}; border: none;")
        self.lbl_aviso_admin.hide()
        layout.addWidget(self.lbl_aviso_admin)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")

        self._matriz_content = QWidget()
        self._matriz_content.setStyleSheet("background: transparent;")
        self._matriz_layout = QVBoxLayout(self._matriz_content)
        self._matriz_layout.setContentsMargins(0, 4, 0, 0)
        self._matriz_layout.setSpacing(10)
        self._matriz_layout.addSpacerItem(QSpacerItem(1, 1, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        scroll.setWidget(self._matriz_content)
        layout.addWidget(scroll, stretch=1)
        return card

    # ── Roles ──────────────────────────────────────────────────────────────

    def _cargar_roles(self) -> None:
        session = self.session_factory()
        try:
            roles = RolService.listar_roles(session, id_usuario=self.usuario.id_usuario)
            id_previo = self._rol_seleccionado_id
            self.lista_roles.blockSignals(True)
            self.lista_roles.clear()
            for rol in roles:
                item = QListWidgetItem(rol.nombre)
                item.setData(Qt.ItemDataRole.UserRole, rol.id_rol)
                self.lista_roles.addItem(item)
                if rol.id_rol == id_previo:
                    self.lista_roles.setCurrentItem(item)
            self.lista_roles.blockSignals(False)
            if self.lista_roles.currentItem() is None and self.lista_roles.count() > 0:
                self.lista_roles.setCurrentRow(0)
            elif self.lista_roles.count() == 0:
                self._rol_seleccionado_id = None
                self._render_matriz([], None)
        except PermisoDenegadoError:
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar roles y permisos.")
        except Exception:
            logger.exception("Fallo al cargar la lista de roles")
            QMessageBox.critical(self, "Error", "No se pudo cargar la lista de roles.")
        finally:
            session.close()

    def _on_rol_seleccionado(self, actual: QListWidgetItem | None, _anterior) -> None:
        if actual is None:
            self._rol_seleccionado_id = None
            self._render_matriz([], None)
            return
        id_rol = actual.data(Qt.ItemDataRole.UserRole)
        self._rol_seleccionado_id = id_rol
        self._cargar_matriz(id_rol, actual.text())

    def nuevo_rol(self) -> None:
        nombre, ok = QInputDialog.getText(self, "Nuevo rol", "Nombre del rol:")
        nombre = nombre.strip().upper()
        if not ok or not nombre:
            return
        descripcion, _ok_desc = QInputDialog.getText(self, "Nuevo rol", "Descripción (opcional):")

        session = self.session_factory()
        try:
            RolService.crear_rol(
                session, nombre=nombre, descripcion=descripcion.strip() or None, id_usuario=self.usuario.id_usuario
            )
            self._cargar_roles()
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "No se pudo crear el rol", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para crear roles.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al crear el rol")
            QMessageBox.critical(self, "Error", "No se pudo crear el rol.")
        finally:
            session.close()

    def editar_rol(self) -> None:
        item = self.lista_roles.currentItem()
        if item is None:
            QMessageBox.information(self, "Selección requerida", "Selecciona un rol de la lista.")
            return
        id_rol = item.data(Qt.ItemDataRole.UserRole)

        nombre, ok = QInputDialog.getText(self, "Editar rol", "Nombre del rol:", text=item.text())
        nombre = nombre.strip().upper()
        if not ok or not nombre:
            return

        session = self.session_factory()
        try:
            RolService.actualizar_rol(session, id_rol, id_usuario=self.usuario.id_usuario, nombre=nombre)
            self._cargar_roles()
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "No se pudo editar el rol", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para editar roles.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al editar el rol %s", id_rol)
            QMessageBox.critical(self, "Error", "No se pudo editar el rol.")
        finally:
            session.close()

    def eliminar_rol(self) -> None:
        item = self.lista_roles.currentItem()
        if item is None:
            QMessageBox.information(self, "Selección requerida", "Selecciona un rol de la lista.")
            return
        id_rol = item.data(Qt.ItemDataRole.UserRole)
        nombre = item.text()

        respuesta = QMessageBox.question(self, "Confirmar", f"¿Eliminar el rol '{nombre}'? No se puede deshacer.")
        if respuesta != QMessageBox.StandardButton.Yes:
            return

        session = self.session_factory()
        try:
            RolService.eliminar_rol(session, id_rol, id_usuario=self.usuario.id_usuario)
            self._rol_seleccionado_id = None
            self._cargar_roles()
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "No se pudo eliminar el rol", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para eliminar roles.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al eliminar el rol %s", id_rol)
            QMessageBox.critical(self, "Error", "No se pudo eliminar el rol.")
        finally:
            session.close()

    # ── Matriz de permisos ────────────────────────────────────────────────

    def _cargar_matriz(self, id_rol: int, nombre_rol: str) -> None:
        session = self.session_factory()
        try:
            matriz = PermisoService.obtener_matriz_rol(session, id_rol, id_usuario=self.usuario.id_usuario)
            self._render_matriz(matriz, nombre_rol)
        except PermisoDenegadoError:
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar la matriz de permisos.")
        except Exception:
            logger.exception("Fallo al cargar la matriz de permisos del rol %s", id_rol)
            QMessageBox.critical(self, "Error", "No se pudo cargar la matriz de permisos.")
        finally:
            session.close()

    def _limpiar_matriz(self) -> None:
        self._checkboxes.clear()
        while self._matriz_layout.count() > 1:  # el ultimo item es el spacer final
            item = self._matriz_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render_matriz(self, matriz: list[dict], nombre_rol: str | None) -> None:
        self._limpiar_matriz()
        es_admin = nombre_rol == "ADMIN"
        self.lbl_titulo_matriz.setText(f"Permisos de {nombre_rol}" if nombre_rol else "Seleccione un rol")
        self.lbl_aviso_admin.setVisible(es_admin)
        self.btn_guardar_matriz.setEnabled(bool(matriz) and not es_admin)

        por_recurso: dict[str, list[dict]] = defaultdict(list)
        for permiso in matriz:
            por_recurso[permiso["recurso"]].append(permiso)

        for recurso in sorted(por_recurso):
            fila = QWidget()
            fila.setStyleSheet("background: transparent;")
            grid = QGridLayout(fila)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(2)

            lbl_recurso = QLabel(recurso.replace("_", " ").capitalize())
            lbl_recurso.setFixedWidth(160)
            lbl_recurso.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_DARK}; border: none;")
            grid.addWidget(lbl_recurso, 0, 0)

            for columna, permiso in enumerate(sorted(por_recurso[recurso], key=lambda p: p["accion"]), start=1):
                chk = QCheckBox(permiso["accion"].capitalize())
                chk.setChecked(permiso["asignado"])
                chk.setEnabled(not es_admin)
                chk.setToolTip(permiso["descripcion"] or "")
                chk.setStyleSheet("font-size: 12px; border: none;")
                self._checkboxes[permiso["id_permiso"]] = chk
                grid.addWidget(chk, 0, columna)

            grid.setColumnStretch(len(por_recurso[recurso]) + 1, 1)
            self._matriz_layout.insertWidget(self._matriz_layout.count() - 1, fila)

    def guardar_matriz(self) -> None:
        if self._rol_seleccionado_id is None:
            return
        ids_marcados = [id_permiso for id_permiso, chk in self._checkboxes.items() if chk.isChecked()]

        session = self.session_factory()
        try:
            PermisoService.establecer_permisos_rol(
                session, self._rol_seleccionado_id, ids_marcados, id_usuario=self.usuario.id_usuario
            )
            QMessageBox.information(self, "Permisos guardados", "La matriz de permisos se actualizó correctamente.")
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "No se pudo guardar", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para editar la matriz de permisos.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al guardar la matriz de permisos del rol %s", self._rol_seleccionado_id)
            QMessageBox.critical(self, "Error", "No se pudo guardar la matriz de permisos.")
        finally:
            session.close()
