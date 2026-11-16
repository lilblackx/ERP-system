"""Panel del modulo Pedidos: caja/admin revisan los pedidos que toman los vendedores (futura app movil), los
aprueban o rechazan y los convierten en factura.

Un pedido no es una factura: mientras espera, solo aparta stock (ver app/services/reservas_stock.py). Facturarlo abre
el mismo formulario de siempre (FacturaFormDialog) ya con el cliente, vendedor y productos del pedido; la factura
cierra el pedido en su misma transaccion. Mismo patron que app/ui/rutas_panel.py (carga en un hilo aparte, paginacion,
permisos en los botones); la barrera real de seguridad sigue siendo PedidoService.
"""

import logging
from collections.abc import Callable

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.db.models import Pedido, Usuario
from app.services.pedidos import PedidoService
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import CajaService
from app.ui.auto_refresco import AutoRefresco
from app.ui.caja_apertura_dialog import CajaAperturaDialog
from app.ui.carga_asincrona import CargaAsincronaMixin
from app.ui.factura_form_dialog import FacturaFormDialog
from app.ui.filtros_catalogo import llenar_combo_vendedores, tarea_vendedores_para_filtro
from app.ui.message_box import MessageBox
from app.ui.paginacion import ControlPaginacion, MixinPaginacion
from app.ui.pedido_detalle_dialog import PedidoDetalleDialog
from app.ui.permisos_ui import MixinPermisos
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    COLORES_ESTADO_PEDIDO,
    TABLE_QSS,
    EstadoBadge,
    alinear_encabezados,
    aplicar_fondo_panel,
    aplicar_sombra,
    dar_ancho_a_texto,
    estilizar_tarjeta,
)
from app.ui.toolbar_popups import BotonFiltros
from app.utils.caja_local import cajas_de_esta_estacion

logger = logging.getLogger(__name__)

COLS_VISIBLES = ["ID", "N° PEDIDO", "CLIENTE", "VENDEDOR", "FECHA", "CONDICIÓN", "TOTAL", "RESERVA HASTA", "ESTADO"]
COL_ID_INTERNO = 0  # oculto; lleva el estado del pedido en Qt.UserRole
COL_ESTADO = 8
POR_PAGINA = 20

ESTADOS_FILTRO = [
    ("Todos los estados", None),
    ("Por revisar", "ENVIADO"),
    ("Aprobados", "APROBADO"),
    ("Facturados", "FACTURADO"),
    ("Rechazados", "RECHAZADO"),
    ("Anulados", "ANULADO"),
    ("Vencidos", "VENCIDO"),
]


def _tarea_listar_pedidos(session, **filtros):
    """Corre en un hilo aparte (ver carga_asincrona.py): solo consulta, sin tocar widgets."""
    return PedidoService.listar_pedidos(session, **filtros)


def _tarea_detalle_pedido(session, id_pedido: int, id_usuario: int | None) -> dict:
    return PedidoService.detalle_pedido(session, id_pedido, id_usuario)


class PedidosPanel(CargaAsincronaMixin, MixinPermisos, MixinPaginacion, QWidget):
    """Listado de pedidos con filtro por estado y vendedor, y las acciones de revision de caja/admin."""

    recurso_permisos = "pedidos"

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self._abriendo_dialogo = False  # guard anti-reentrancia del detalle (ver bancos_panel.py)
        self.setObjectName("ContentArea")
        self._setup_ui()
        self._cargar_vendedores()
        QTimer.singleShot(100, self.cargar_pedidos)
        # Pedidos que entran desde la app movil o que otra estacion aprueba, sin salir y volver al modulo.
        self._auto_refresco = AutoRefresco(
            self, self._refresco_periodico, lambda: self.tabla, COL_ID_INTERNO, asincrono=True
        )

    def showEvent(self, event: QShowEvent) -> None:
        # MainWindow cachea el panel: sin esto, volver al modulo mostraria el listado viejo.
        super().showEvent(event)
        self.cargar_pedidos()

    def _refresco_periodico(self, al_terminar: Callable[[], None]) -> None:
        self.cargar_pedidos(silencioso=True, al_terminar=al_terminar)

    def _cargar_vendedores(self) -> None:
        self.cargar_async(
            "vendedores",
            tarea_vendedores_para_filtro,
            lambda vendedores: llenar_combo_vendedores(self.vendedor_combo, vendedores, self.usuario),
            texto_error="No se pudo cargar la lista de vendedores.",
            silencioso=True,
        )

    # ── Construcción de la UI ─────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        root.addWidget(self._make_header())
        root.addWidget(self._make_toolbar())
        root.addWidget(self._make_table(), stretch=1)
        root.addWidget(self._make_footer())
        aplicar_fondo_panel(self)

    def _make_header(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        titulo = QLabel("Pedidos de Venta")
        titulo.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        self.lbl_total = QLabel("Cargando…")
        self.lbl_total.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 13px;"
            f" background-color: {COLOR_TABLE_HEADER}; border-radius: 10px;"
            " padding: 3px 10px;"
        )
        h.addWidget(titulo)
        h.addWidget(self.lbl_total)
        h.addStretch()
        return w

    def _make_toolbar(self) -> QWidget:
        w = QWidget()
        estilizar_tarjeta(w, padding=4, radio=8)
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)

        self.estado_combo = QComboBox()
        for etiqueta, valor in ESTADOS_FILTRO:
            self.estado_combo.addItem(etiqueta, valor)
        self.estado_combo.currentIndexChanged.connect(self._buscar_desde_inicio)

        self.vendedor_combo = QComboBox()
        self.vendedor_combo.addItem("Todos los vendedores")
        self.vendedor_combo.currentIndexChanged.connect(self._buscar_desde_inicio)

        self.btn_filtrar = BotonFiltros([("Estado", self.estado_combo), ("Vendedor", self.vendedor_combo)])

        h.addSpacerItem(QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
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
                5: Qt.AlignmentFlag.AlignCenter,
                6: Qt.AlignmentFlag.AlignRight,
                7: Qt.AlignmentFlag.AlignCenter,
                COL_ESTADO: Qt.AlignmentFlag.AlignCenter,
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
        encabezado = self.tabla.horizontalHeader()
        encabezado.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        encabezado.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        encabezado.setSectionResizeMode(COL_ESTADO, QHeaderView.ResizeMode.Fixed)
        self.tabla.setColumnWidth(COL_ESTADO, 110)
        self.tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(self.tabla)
        self.tabla.setColumnHidden(COL_ID_INTERNO, True)
        self.tabla.verticalHeader().setDefaultSectionSize(48)
        self.tabla.doubleClicked.connect(self.ver_detalle_pedido)
        return self.tabla

    def _boton(self, texto: str, icono: str, handler, primario: bool = False) -> QPushButton:
        boton = QPushButton(texto)
        boton.setIcon(qta.icon(icono, color="white" if primario else COLOR_TEXT_DARK))
        boton.setStyleSheet(BUTTON_PRIMARY_QSS if primario else BUTTON_SECONDARY_QSS)
        boton.clicked.connect(handler)
        return boton

    def _make_footer(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        self.paginacion = ControlPaginacion()
        self.paginacion.pagina_cambiada.connect(lambda _pagina: self.cargar_pedidos())

        self.btn_detalle = self._boton("Ver detalle", "fa5s.eye", self.ver_detalle_pedido)
        self.btn_aprobar = self._boton("Aprobar", "fa5s.check", self.aprobar_pedido_seleccionado)
        self.btn_rechazar = self._boton("Rechazar", "fa5s.times", self.rechazar_pedido_seleccionado)
        self.btn_anular = self._boton("Anular", "fa5s.ban", self.anular_pedido_seleccionado)
        self.btn_facturar = self._boton(
            "Facturar", "fa5s.file-invoice-dollar", self.facturar_pedido_seleccionado, primario=True
        )

        h.addWidget(self.paginacion)
        h.addStretch()
        h.addWidget(self.btn_detalle)
        # Revisar (aprobar / rechazar / facturar) es 'editar'; anular tambien lo puede su propio vendedor ('crear').
        if self._puede("editar"):
            h.addWidget(self.btn_aprobar)
            h.addWidget(self.btn_rechazar)
        if self._puede("editar") or self._puede("crear"):
            h.addWidget(self.btn_anular)
        if self._puede("editar"):
            h.addWidget(self.btn_facturar)
        return w

    # ── Lógica de datos ───────────────────────────────────────────────────

    def _buscar_desde_inicio(self) -> None:
        self.pagina_actual = 1
        self.cargar_pedidos(silencioso=True)

    def cargar_pedidos(
        self, silencioso: bool = False, sincrono: bool = False, al_terminar: Callable[[], None] | None = None
    ) -> None:
        self.cargar_async(
            "pedidos",
            _tarea_listar_pedidos,
            self._poblar_tabla,
            texto_error="No se pudo cargar la lista de pedidos.",
            texto_sin_permiso="No tienes permiso para consultar pedidos.",
            silencioso=silencioso,
            sincrono=sincrono,
            al_terminar=al_terminar,
            id_usuario=self.usuario.id_usuario,
            estado=self.estado_combo.currentData(),
            id_vendedor=self.vendedor_combo.currentData(),
            pagina=self.pagina_actual,
            por_pagina=POR_PAGINA,
        )

    def _poblar_tabla(self, resultado: dict) -> None:
        pedidos: list[Pedido] = resultado["items"]
        self.tabla.setRowCount(len(pedidos))
        derecha = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        centro = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        for fila, p in enumerate(pedidos):
            item_id = QTableWidgetItem(str(p.id_pedido))
            item_id.setData(Qt.ItemDataRole.UserRole, p.estado)
            self.tabla.setItem(fila, 0, item_id)
            self.tabla.setItem(fila, 1, QTableWidgetItem(p.numero_pedido))
            self.tabla.setItem(fila, 2, QTableWidgetItem(p.cliente.nombre_razon_social if p.cliente else ""))
            self.tabla.setItem(fila, 3, QTableWidgetItem(p.vendedor.nombre_vendedor if p.vendedor else ""))
            self.tabla.setItem(
                fila, 4, QTableWidgetItem(p.fecha_creacion.strftime("%d/%m/%Y %H:%M") if p.fecha_creacion else "")
            )
            condicion = QTableWidgetItem("Contado" if p.condicion_pago == "contado" else "Crédito")
            condicion.setTextAlignment(centro)
            self.tabla.setItem(fila, 5, condicion)
            total = QTableWidgetItem(f"${float(p.total):,.2f}")
            total.setTextAlignment(derecha)
            self.tabla.setItem(fila, 6, total)
            # Solo un pedido por revisar vence: aprobado aparta hasta que se factura o se anula.
            vence = p.fecha_vencimiento_reserva.strftime("%d/%m %H:%M") if p.fecha_vencimiento_reserva else "—"
            item_vence = QTableWidgetItem(vence)
            item_vence.setTextAlignment(centro)
            self.tabla.setItem(fila, 7, item_vence)
            self.tabla.setCellWidget(
                fila,
                COL_ESTADO,
                EstadoBadge(p.estado.capitalize(), COLORES_ESTADO_PEDIDO.get(p.estado, COLOR_TEXT_MUTED)),
            )

        total = resultado["total"]
        self.paginacion.actualizar_desde(resultado)  # pagina y total_paginas ya vienen corregidos por paginar()
        self.lbl_total.setText(f"{total} pedido{'s' if total != 1 else ''}")

    def _pedido_seleccionado(self) -> tuple[int, str] | None:
        """(id, estado) del pedido elegido en la tabla, o None tras avisar que falta elegir uno."""
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            MessageBox.information(self, "Selección requerida", "Selecciona un pedido de la lista.")
            return None
        item = self.tabla.item(filas[0].row(), 0)
        return int(item.text()), item.data(Qt.ItemDataRole.UserRole)

    # ── Detalle ───────────────────────────────────────────────────────────

    def ver_detalle_pedido(self) -> None:
        elegido = self._pedido_seleccionado()
        if elegido is None or self._abriendo_dialogo:
            return
        self._abriendo_dialogo = True
        self.cargar_async(
            "detalle_pedido",
            _tarea_detalle_pedido,
            self._abrir_detalle,
            texto_error="No se pudo cargar el detalle del pedido.",
            texto_sin_permiso="No tienes permiso para ver pedidos.",
            id_pedido=elegido[0],
            id_usuario=self.usuario.id_usuario,
        )

    def _abrir_detalle(self, datos: dict) -> None:
        try:
            PedidoDetalleDialog(datos, parent=self).exec()
        finally:
            self._abriendo_dialogo = False

    # ── Acciones de revisión ──────────────────────────────────────────────

    def _correr_accion(
        self, accion: Callable, *, titulo_error: str, error_generico: str, titulo_ok: str, mensaje_ok: str
    ) -> bool:
        """Corre `accion(session)` (una operacion de PedidoService que devuelve el pedido) con una sesion propia y
        avisa el resultado. `mensaje_ok` lleva `{numero}`. Devuelve True si se hizo."""
        session = self.session_factory()
        try:
            numero = accion(session).numero_pedido
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, titulo_error, str(exc))
            return False
        except PermisoDenegadoError as exc:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", str(exc))
            return False
        except Exception:
            session.rollback()
            logger.exception("Fallo en una accion sobre un pedido")
            MessageBox.critical(self, "Error", error_generico)
            return False
        finally:
            session.close()
        self.cargar_pedidos()
        MessageBox.information(self, titulo_ok, mensaje_ok.format(numero=numero))
        return True

    def aprobar_pedido_seleccionado(self) -> None:
        if not self._exigir_permiso("editar", "No tienes permiso para aprobar pedidos."):
            return
        elegido = self._pedido_seleccionado()
        if elegido is None:
            return
        id_pedido = elegido[0]
        self._correr_accion(
            lambda s: PedidoService.aprobar_pedido(s, id_pedido, self.usuario.id_usuario),
            titulo_error="No se pudo aprobar el pedido",
            error_generico="No se pudo aprobar el pedido.",
            titulo_ok="Pedido aprobado",
            mensaje_ok="El pedido {numero} quedó aprobado. Su stock sigue apartado hasta que se facture o se anule.",
        )

    def rechazar_pedido_seleccionado(self) -> None:
        if not self._exigir_permiso("editar", "No tienes permiso para rechazar pedidos."):
            return
        elegido = self._pedido_seleccionado()
        if elegido is None:
            return
        id_pedido = elegido[0]
        motivo, ok = QInputDialog.getText(self, "Rechazar pedido", "Motivo del rechazo (lo verá el vendedor):")
        if not ok or not motivo.strip():
            return
        self._correr_accion(
            lambda s: PedidoService.rechazar_pedido(s, id_pedido, motivo, self.usuario.id_usuario),
            titulo_error="No se pudo rechazar el pedido",
            error_generico="No se pudo rechazar el pedido.",
            titulo_ok="Pedido rechazado",
            mensaje_ok="El pedido {numero} fue rechazado y su stock quedó libre.",
        )

    def anular_pedido_seleccionado(self) -> None:
        if not (self._puede("editar") or self._puede("crear")):
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para anular pedidos.")
            return
        elegido = self._pedido_seleccionado()
        if elegido is None:
            return
        id_pedido = elegido[0]
        motivo, ok = QInputDialog.getText(self, "Anular pedido", "Motivo de la anulación:")
        if not ok or not motivo.strip():
            return
        self._correr_accion(
            lambda s: PedidoService.anular_pedido(s, id_pedido, self.usuario.id_usuario, motivo.strip()),
            titulo_error="No se pudo anular el pedido",
            error_generico="No se pudo anular el pedido.",
            titulo_ok="Pedido anulado",
            mensaje_ok="El pedido {numero} fue anulado y su stock quedó libre.",
        )

    # ── Facturar ──────────────────────────────────────────────────────────

    def _hay_caja_abierta(self, session) -> bool:
        """Una factura de contado se cobra en una caja: la de ESTA estacion debe tener turno abierto (las que abrieron
        otras estaciones no cuentan). Si no hay, se ofrece abrir el turno, igual que al facturar desde Facturacion."""

        def abiertas() -> list:
            try:
                cajas = CajaService.listar_cajas(session, id_usuario=self.usuario.id_usuario)
            except PermisoDenegadoError:
                cajas = []
            return cajas_de_esta_estacion([c for c in cajas if c.fecha_apertura is not None and c.fecha_cierre is None])

        if abiertas():
            return True
        dialogo = CajaAperturaDialog(session, parent=self)
        return dialogo.exec() == QDialog.DialogCode.Accepted and dialogo.caja_abierta is not None and bool(abiertas())

    def facturar_pedido_seleccionado(self) -> None:
        if not self._exigir_permiso("editar", "No tienes permiso para facturar pedidos."):
            return
        if not self._exigir_permiso("crear", "No tienes permiso para emitir facturas.", recurso="ventas"):
            return
        elegido = self._pedido_seleccionado()
        if elegido is None:
            return
        id_pedido, estado = elegido
        if estado != "APROBADO":
            MessageBox.information(self, "Pedido no aprobado", "Solo se factura un pedido aprobado: apruébalo primero.")
            return

        session = self.session_factory()
        try:
            datos = PedidoService.datos_para_facturar(session, id_pedido, self.usuario.id_usuario)
            if datos["condicion_pago"] == "contado" and not self._hay_caja_abierta(session):
                MessageBox.information(
                    self, "Caja requerida", "Debe abrir el turno de una caja para facturar un pedido de contado."
                )
                return
            # El formulario emite la factura el mismo y, al hacerlo, cierra el pedido (id_pedido): si falla, se queda
            # abierto con el error y el pedido sigue aprobado.
            dialogo = FacturaFormDialog(
                session, self.usuario.id_usuario, parent=self, session_factory=self.session_factory, pedido=datos
            )
            if dialogo.exec() and dialogo.factura_emitida is not None:
                numero_factura = dialogo.numero_factura_emitida
                self.cargar_pedidos()
                MessageBox.information(
                    self,
                    "Pedido facturado",
                    f"El pedido {datos['numero_pedido']} se facturó: factura {numero_factura}.",
                )
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, "No se pudo facturar el pedido", str(exc))
        except PermisoDenegadoError as exc:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", str(exc))
        except Exception:
            session.rollback()
            logger.exception("Fallo al facturar el pedido %s", id_pedido)
            MessageBox.critical(self, "Error", "No se pudo abrir la factura del pedido.")
        finally:
            session.close()
