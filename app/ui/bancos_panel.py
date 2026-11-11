"""
Panel completo del módulo Bancos.
Incluye barra de herramientas, tabla estilizada con datos reales y acciones CRUD.
Diseño moderno integrado en el MainWindow (no como ventana flotante).
"""

import logging

import qtawesome as qta
from PySide6.QtCore import Qt
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
from app.services.paginacion import paginar_lista
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import BancoService
from app.ui.banco_form_dialog import BancoFormDialog
from app.ui.carga_asincrona import CargaAsincronaMixin
from app.ui.message_box import MessageBox
from app.ui.paginacion import ControlPaginacion, MixinPaginacion
from app.ui.permisos_ui import MixinPermisos
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_SUCCESS,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MUTED,
    SEARCH_QSS,
    TABLE_QSS,
    EstadoBadge,
    alinear_encabezados,
    aplicar_fondo_panel,
    dar_ancho_a_texto,
    estilizar_tarjeta,
)
from app.ui.toolbar_popups import BotonFiltros

logger = logging.getLogger(__name__)

# Columnas visibles en la tabla (índice oculto 0 = ID interno)
COLS_VISIBLES = [
    "ID",
    "CÓDIGO",
    "NOMBRE",
    "TIPO",
    "RIF",
    "TELÉFONO",
    "CORREO",
    "ESTADO",
]
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


def _tarea_listar_bancos(session, **filtros):
    """Corre en un hilo aparte (ver carga_asincrona.py): solo consulta, sin tocar widgets."""
    return BancoService.listar_bancos(session, **filtros)


class BancosPanel(CargaAsincronaMixin, MixinPermisos, MixinPaginacion, QWidget):
    """
    Panel principal del módulo Bancos.
    Encapsula la barra de herramientas y la tabla de datos en un solo widget
    para ser insertado directamente en el área de contenido del MainWindow.
    """

    recurso_permisos = "bancos"

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.bancos = []
        self._search_timer = None
        # Doble-click en la tabla dispara editar_banco(), que consulta la base y abre un
        # QDialog modal -- entre el clic y que el modal capture el foco hay una ventana
        # breve en la que la tabla sigue interactiva; sin este guard, un segundo
        # doble-click en ese hueco reentra editar_banco() y abre dos dialogos apilados
        # (hallazgo 3.3, auditoria 2026-09-05).
        self._abriendo_dialogo = False
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

        aplicar_fondo_panel(self)

    def _make_header(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("Bancos")
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
        estilizar_tarjeta(w, padding=4, radio=8)
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)

        # Barra de búsqueda
        self.buscar_input = QLineEdit()
        self.buscar_input.setPlaceholderText("Buscar por código, nombre, RIF o teléfono…")
        self.buscar_input.addAction(
            qta.icon("fa5s.search", color=COLOR_TEXT_LIGHT),
            QLineEdit.ActionPosition.LeadingPosition,
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
        if self._puede("crear"):
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
        dar_ancho_a_texto(self.tabla)
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

        self.paginacion = ControlPaginacion()
        self.paginacion.pagina_cambiada.connect(lambda _pagina: self._actualizar_tabla())

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

        h.addWidget(self.paginacion)
        h.addStretch()
        if self._puede("editar"):
            h.addWidget(self.btn_editar)
        if self._puede("eliminar"):
            h.addWidget(self.btn_cambiar_estado)
        return w

    # ── Carga de datos ─────────────────────────────────────────────────────

    def cargar_bancos(self, silencioso: bool = False, sincrono: bool = False):
        """Pide la lista de bancos via BancoService en un hilo aparte (ver carga_asincrona.py). Bancos es un
        catalogo chico (a diferencia de clientes/vendedores), asi que se sigue filtrando/paginando del lado de
        Python sobre la lista completa en vez de sumarle paginacion al servicio."""
        self.cargar_async(
            "bancos",
            _tarea_listar_bancos,
            self._mostrar_bancos,
            texto_error="No se pudo cargar la lista de bancos.",
            texto_sin_permiso="No tienes permiso para consultar bancos.",
            silencioso=silencioso,
            sincrono=sincrono,
            id_usuario=self.usuario.id_usuario,
        )

    def _mostrar_bancos(self, bancos: list) -> None:
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

    def _actualizar_tabla(self):
        """Actualiza la tabla con los bancos cargados (respetando paginación)."""
        self.tabla.setRowCount(0)

        # Paginacion central (app/services/paginacion.py): normaliza y lleva la pagina a la ultima si sobra.
        resultado = paginar_lista(self.bancos, self.pagina_actual, POR_PAGINA)
        self.paginacion.actualizar_desde(resultado)
        bancos_pagina = resultado["items"]

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

    # ── Búsqueda y filtros ─────────────────────────────────────────────────

    def _buscar_desde_inicio(self):
        """Realiza búsqueda desde la página 1."""
        self.pagina_actual = 1
        self.cargar_bancos()

    def _busqueda_dinamica(self):
        """Búsqueda en tiempo real con pausa al teclear."""
        self.buscar_con_pausa(self._buscar_tecleando)

    def _buscar_tecleando(self):
        self.pagina_actual = 1
        self.cargar_bancos(silencioso=True)  # no enciende la barra de carga

    # ── CRUD ─────────────────────────────────────────────────────────────

    def nuevo_banco(self):
        """Abre el diálogo para crear un nuevo banco."""
        if not self._exigir_permiso("crear", "No tienes permiso para crear bancos."):
            return
        session = self.session_factory()
        try:
            dialog = BancoFormDialog(session, parent=self)
            if dialog.exec():
                data = dialog.get_data()
                BancoService.crear_banco(session, **data, creado_por=self.usuario.id_usuario)
                self.cargar_bancos()
        except IntegrityError:
            session.rollback()
            MessageBox.warning(
                self,
                "Dato duplicado",
                "Ya existe un banco con esa identificación (RIF).",
            )
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
        if not self._exigir_permiso("editar", "No tienes permiso para editar bancos."):
            return
        banco_id = self._id_seleccionado()
        if banco_id is None:
            return
        if self._abriendo_dialogo:
            return
        self._abriendo_dialogo = True

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
            MessageBox.warning(
                self,
                "Dato duplicado",
                "Ya existe un banco con esa identificación (RIF).",
            )
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
            self._abriendo_dialogo = False

    def cambiar_estado_banco(self):
        """Cambia el estado del banco seleccionado (ACTIVO <-> INACTIVO)."""
        if not self._exigir_permiso("eliminar", "No tienes permiso para cambiar el estado de bancos."):
            return
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
                self,
                "Confirmar",
                f"¿Cambiar el estado del banco '{banco.nombre_banco}' a {nuevo_estado}?",
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return

            BancoService.cambiar_estado_banco(session, banco_id, nuevo_estado, id_usuario=self.usuario.id_usuario)
            self.cargar_bancos()
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(
                self,
                "Sin permiso",
                "No tienes permiso para cambiar el estado de bancos.",
            )
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
