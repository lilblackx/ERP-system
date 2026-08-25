"""
Panel completo del módulo Facturación / Ventas.
Mismo patrón visual y de interacción que app/ui/clientes_panel.py e
app/ui/inventario_panel.py (paleta y tipografía de app/ui/styles.py): barra de
herramientas, tabla estilizada, paginación (ya provista por
VentaService.listar_facturas()) y exportación a Excel/PDF (R-10).
"""

import logging

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
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

from app.db.models import Caja, FacturaVenta, Usuario
from app.services.clientes import list_clientes
from app.services.empresa import EmpresaService
from app.services.exportacion import exportar_excel, exportar_pdf
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import CajaService
from app.services.ventas import VentaService
from app.ui.caja_apertura_dialog import CajaAperturaDialog
from app.ui.factura_detalle_dialog import FacturaDetalleDialog
from app.ui.factura_form_dialog import FacturaFormDialog
from app.ui.factura_pdf import imprimir_factura
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
    COLORES_ESTADO_FACTURA,
    SEARCH_QSS,
    TABLE_QSS,
    aplicar_sombra,
    color_con_alpha,
)
from app.ui.toolbar_popups import BotonExportar, BotonFiltros
from app.ui.workers import QueryWorker

logger = logging.getLogger(__name__)

COLS_VISIBLES = ["ID", "N° Factura", "Cliente", "Fecha", "Condición", "Total", "Estado"]
COL_ID_INTERNO = 0  # oculto
POR_PAGINA = 20


def _tarea_imprimir_factura(session, id_factura: int, id_usuario: int | None) -> str | None:
    """Corre en un QThread aparte (QueryWorker), no en el hilo de GUI: enviar un
    trabajo a un driver de impresora real via QPrinter.print_() puede tardar varios
    cientos de ms (a veces mas en el primer trabajo de la sesion, mientras el driver
    inicializa), y hacerlo de forma sincrona justo despues de "Facturar" era lo que
    hacia sentir lento todo el flujo -- la ventana quedaba bloqueada hasta que el
    spooler aceptaba el documento. Devuelve el nombre de la impresora usada, o None si
    no hay ninguna configurada (no es un error, ver FacturacionPanel._disparar_impresion_automatica)."""
    config_empresa = EmpresaService.obtener_configuracion(session, id_usuario=id_usuario)
    if not config_empresa or not config_empresa.impresora_predeterminada:
        return None
    datos_factura = VentaService.obtener_factura(session, id_factura, id_usuario=id_usuario)
    imprimir_factura(datos_factura, config_empresa, config_empresa.impresora_predeterminada)
    return config_empresa.impresora_predeterminada


ESTADOS_FILTRO = [
    ("Todos los estados", None),
    ("Emitida", "EMITIDA"),
    ("Pagada", "PAGADA"),
    ("Parcial", "PARCIAL"),
    ("Vencida", "VENCIDA"),
    ("Anulada", "ANULADA"),
]
CONDICIONES_FILTRO = [
    ("Contado y crédito", None),
    ("Contado", "contado"),
    ("Crédito", "credito"),
]


class EstadoFacturaBadge(QWidget):
    """Badge de color por estado de factura (EMITIDA/PAGADA/PARCIAL/VENCIDA/ANULADA),
    mismo criterio visual que BadgeItem en clientes_panel.py/inventario_panel.py pero
    con mas de 2 estados posibles -- ver COLORES_ESTADO_FACTURA en app/ui/styles.py."""

    def __init__(self, estado: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        color = COLORES_ESTADO_FACTURA.get(estado, COLOR_TEXT_MUTED)
        lbl = QLabel(estado.capitalize())
        lbl.setStyleSheet(
            f"background-color: {color_con_alpha(color)}; color: {color}; border-radius: 10px;"
            " padding: 2px 10px; font-size: 11px; font-weight: bold;"
        )
        layout.addWidget(lbl)


class FacturacionPanel(QWidget):
    """Panel principal del módulo Facturación: listado de facturas con búsqueda por
    número, filtro por estado/condición de pago, paginación, emisión de nuevas
    facturas (carrito), ver detalle y anulación."""

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.pagina_actual = 1
        self.total_paginas = 1
        self._verificando_caja = False
        self.setObjectName("ContentArea")
        self._setup_ui()
        QTimer.singleShot(100, self.cargar_facturas)

    def showEvent(self, event: QShowEvent) -> None:
        # Mismo problema que DashboardPanel (ver su showEvent): MainWindow
        # cachea el panel y lo reutiliza via QStackedWidget, asi que sin esto
        # volver a "Facturacion" desde otro modulo mostraba el listado viejo.
        super().showEvent(event)
        self.cargar_facturas()
        # Gate de entrada: sin ninguna caja con turno abierto no se puede emitir
        # facturas (aunque si se pueden seguir viendo las ya emitidas) -- se ofrece
        # abrir un turno cada vez que se entra al modulo mientras siga sin haber
        # ninguna abierta. self._verificando_caja evita reentrancia si showEvent se
        # dispara mas de una vez mientras el dialogo modal ya esta abierto (el
        # exec() de un QDialog corre un event loop anidado que si procesa timers).
        self._verificar_caja_abierta(ofrecer_apertura=True)

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

        lbl = QLabel("Facturación de Ventas")
        lbl.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        self.lbl_total = QLabel("Cargando…")
        self.lbl_total.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 13px;"
            f" background-color: {COLOR_TABLE_HEADER}; border-radius: 10px;"
            " padding: 3px 10px;"
        )

        self.lbl_caja_estado = QLabel()
        self._actualizar_estado_caja(None)

        h.addWidget(lbl)
        h.addWidget(self.lbl_total)
        h.addWidget(self.lbl_caja_estado)
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
        self.buscar_input.setPlaceholderText("Buscar por N° de factura…")
        self.buscar_input.addAction(qta.icon("fa5s.search", color="#94A3B8"), QLineEdit.ActionPosition.LeadingPosition)
        self.buscar_input.setObjectName("SearchInput")
        self.buscar_input.setStyleSheet(SEARCH_QSS)
        self.buscar_input.setFixedWidth(200)
        self.buscar_input.returnPressed.connect(self._buscar_desde_inicio)
        self.buscar_input.textChanged.connect(self._busqueda_dinamica)

        self.estado_combo = QComboBox()
        for etiqueta, valor in ESTADOS_FILTRO:
            self.estado_combo.addItem(etiqueta, valor)
        self.estado_combo.currentIndexChanged.connect(self._buscar_desde_inicio)

        self.condicion_combo = QComboBox()
        for etiqueta, valor in CONDICIONES_FILTRO:
            self.condicion_combo.addItem(etiqueta, valor)
        self.condicion_combo.currentIndexChanged.connect(self._buscar_desde_inicio)

        self.cliente_combo = QComboBox()
        self.cliente_combo.addItem("Todos los clientes", None)
        self.cliente_combo.currentIndexChanged.connect(self._buscar_desde_inicio)
        self._cargar_clientes_filtro()

        self.btn_filtrar = BotonFiltros(
            [
                ("Estado", self.estado_combo),
                ("Condición de pago", self.condicion_combo),
                ("Cliente", self.cliente_combo),
            ]
        )

        self.btn_nueva_factura = QPushButton("Nueva Factura")
        self.btn_nueva_factura.setIcon(qta.icon("fa5s.plus", color="white"))
        self.btn_nueva_factura.setStyleSheet(BUTTON_PRIMARY_QSS)
        self.btn_nueva_factura.clicked.connect(self.nueva_factura)

        self.btn_exportar = BotonExportar(on_excel=self.exportar_excel_facturas, on_pdf=self.exportar_pdf_facturas)

        h.addWidget(self.buscar_input)
        h.addSpacerItem(QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        h.addWidget(self.btn_nueva_factura)
        h.addWidget(self.btn_filtrar)
        h.addWidget(self.btn_exportar)
        return w

    def _cargar_clientes_filtro(self) -> None:
        session = self.session_factory()
        try:
            for cliente in list_clientes(session, None, id_usuario=self.usuario.id_usuario):
                self.cliente_combo.addItem(cliente.nombre_razon_social, cliente.id_cliente)
        except Exception:
            logger.exception("Fallo al cargar clientes para el filtro de facturacion")
        finally:
            session.close()

    def _make_table(self) -> QTableWidget:
        self.tabla = QTableWidget(0, len(COLS_VISIBLES))
        self.tabla.setHorizontalHeaderLabels(COLS_VISIBLES)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setShowGrid(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.tabla.setColumnWidth(6, 110)
        self.tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(self.tabla)
        self.tabla.setColumnHidden(COL_ID_INTERNO, True)
        self.tabla.verticalHeader().setDefaultSectionSize(48)
        self.tabla.doubleClicked.connect(self.ver_detalle_factura)
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

        btn_detalle = QPushButton("Ver detalle")
        btn_detalle.setIcon(qta.icon("fa5s.eye", color=COLOR_TEXT_DARK))
        btn_detalle.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_detalle.clicked.connect(self.ver_detalle_factura)

        btn_anular = QPushButton("Anular factura")
        btn_anular.setIcon(qta.icon("fa5s.ban", color=COLOR_TEXT_DARK))
        btn_anular.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_anular.clicked.connect(self.anular_factura_seleccionada)

        h.addWidget(self.lbl_pagina)
        h.addWidget(self.btn_anterior)
        h.addWidget(self.btn_siguiente)
        h.addStretch()
        h.addWidget(btn_detalle)
        h.addWidget(btn_anular)
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
        self.cargar_facturas()

    def _pagina_anterior(self) -> None:
        if self.pagina_actual > 1:
            self.pagina_actual -= 1
            self.cargar_facturas()

    def _pagina_siguiente(self) -> None:
        if self.pagina_actual < self.total_paginas:
            self.pagina_actual += 1
            self.cargar_facturas()

    # ── Lógica de datos ───────────────────────────────────────────────────

    def cargar_facturas(self) -> None:
        session = self.session_factory()
        try:
            resultado = VentaService.listar_facturas(
                session,
                numero_factura=self.buscar_input.text().strip() or None,
                estado=self.estado_combo.currentData(),
                condicion_pago=self.condicion_combo.currentData(),
                id_cliente=self.cliente_combo.currentData(),
                pagina=self.pagina_actual,
                por_pagina=POR_PAGINA,
                id_usuario=self.usuario.id_usuario,
            )
            self._poblar_tabla(resultado)
        except Exception:
            logger.exception("Fallo al cargar el listado de facturas")
            QMessageBox.critical(self, "Error de conexión", "No se pudo cargar el listado de facturas.")
        finally:
            session.close()

    def _poblar_tabla(self, resultado: dict) -> None:
        facturas: list[FacturaVenta] = resultado["items"]
        self.tabla.setRowCount(len(facturas))
        for fila, f in enumerate(facturas):
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(f.id_factura)))
            self.tabla.setItem(fila, 1, QTableWidgetItem(f.numero_factura))
            self.tabla.setItem(fila, 2, QTableWidgetItem(f.cliente.nombre_razon_social if f.cliente else ""))

            fecha = f.fecha_emision.strftime("%d/%m/%Y") if f.fecha_emision else ""
            self.tabla.setItem(fila, 3, QTableWidgetItem(fecha))

            condicion = "Contado" if f.condicion_pago == "contado" else "Crédito"
            self.tabla.setItem(fila, 4, QTableWidgetItem(condicion))

            item_total = QTableWidgetItem(f"${float(f.total_venta):,.2f}")
            item_total.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 5, item_total)

            badge = EstadoFacturaBadge(f.estado_factura or "EMITIDA")
            self.tabla.setCellWidget(fila, 6, badge)

        total = resultado["total"]
        self.total_paginas = max(1, -(-total // POR_PAGINA))  # ceil sin importar math
        self.pagina_actual = min(self.pagina_actual, self.total_paginas)

        self.lbl_total.setText(f"{total} factura{'s' if total != 1 else ''}")
        self.lbl_pagina.setText(f"Página {self.pagina_actual} de {self.total_paginas}")
        self.btn_anterior.setEnabled(self.pagina_actual > 1)
        self.btn_siguiente.setEnabled(self.pagina_actual < self.total_paginas)

    def _fila_seleccionada_id(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            QMessageBox.information(self, "Selección requerida", "Selecciona una factura de la lista.")
            return None
        return int(self.tabla.item(filas[0].row(), 0).text())

    # ── Gate de caja (sin turno abierto no se puede facturar) ─────────────

    def _cajas_con_turno_abierto(self) -> list[Caja]:
        session = self.session_factory()
        try:
            cajas = CajaService.listar_cajas(session, id_usuario=self.usuario.id_usuario)
        except PermisoDenegadoError:
            cajas = []
        finally:
            session.close()
        return [c for c in cajas if c.fecha_apertura is not None and c.fecha_cierre is None]

    def _actualizar_estado_caja(self, caja: Caja | None) -> None:
        if caja is not None:
            self.lbl_caja_estado.setText(f"Caja abierta: {caja.nombre_caja or caja.id_caja}")
            self.lbl_caja_estado.setStyleSheet(
                f"color: {COLOR_SUCCESS}; font-size: 13px; background-color: #DCFCE7;"
                " border-radius: 10px; padding: 3px 10px;"
            )
        else:
            self.lbl_caja_estado.setText("Sin caja abierta")
            self.lbl_caja_estado.setStyleSheet(
                f"color: {COLOR_DANGER}; font-size: 13px; background-color: #FEE2E2;"
                " border-radius: 10px; padding: 3px 10px;"
            )

    def _verificar_caja_abierta(self, ofrecer_apertura: bool = False) -> bool:
        """Sin ninguna caja con turno abierto no se puede facturar -- solo se puede
        seguir viendo el listado de facturas ya emitidas. Si ofrecer_apertura=True y no
        hay ninguna abierta, se lanza el gate de identificacion + apertura de turno
        (CajaAperturaDialog); si el usuario lo completa, se vuelve a verificar."""
        if self._verificando_caja:
            return bool(self._cajas_con_turno_abierto())
        self._verificando_caja = True
        try:
            abiertas = self._cajas_con_turno_abierto()
            if not abiertas and ofrecer_apertura:
                session = self.session_factory()
                try:
                    dialogo = CajaAperturaDialog(session, parent=self)
                    if dialogo.exec() == QDialog.DialogCode.Accepted and dialogo.caja_abierta is not None:
                        abiertas = self._cajas_con_turno_abierto()
                finally:
                    session.close()
            self._actualizar_estado_caja(abiertas[0] if abiertas else None)
            return bool(abiertas)
        finally:
            self._verificando_caja = False

    def nueva_factura(self) -> None:
        if not self._verificar_caja_abierta(ofrecer_apertura=True):
            QMessageBox.information(
                self, "Caja requerida", "Debe abrir el turno de una caja para poder emitir facturas."
            )
            return

        session = self.session_factory()
        try:
            dialogo = FacturaFormDialog(session, self.usuario.id_usuario, parent=self)
            if dialogo.exec():
                datos = dialogo.get_data()
                factura = VentaService.emitir_factura(session, id_usuario=self.usuario.id_usuario, **datos)
                self.cargar_facturas()
                # La impresion se dispara en segundo plano (no bloquea este mensaje ni
                # el resto de la UI) -- ver _disparar_impresion_automatica.
                self._disparar_impresion_automatica(factura.id_factura)
                QMessageBox.information(self, "Factura emitida", f"Factura {factura.numero_factura} emitida con éxito.")
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "No se pudo emitir la factura", str(exc))
        except Exception:
            session.rollback()
            logger.exception("Fallo al emitir factura")
            QMessageBox.critical(self, "Error", "No se pudo emitir la factura.")
        finally:
            session.close()

    def _disparar_impresion_automatica(self, id_factura: int) -> None:
        """Lanza _tarea_imprimir_factura en un QueryWorker (QThread) para que enviar el
        trabajo al driver de la impresora no bloquee la ventana -- ver el docstring de
        _tarea_imprimir_factura para el por que. Si ya hay una impresion en curso, esta
        se omite en vez de pisar el QThread anterior mientras sigue corriendo (mismo
        riesgo que DashboardPanel/TasaTicker, ver app/ui/workers.py); la factura ya
        quedo guardada y se puede exportar/imprimir manualmente desde el detalle."""
        if getattr(self, "_worker", None) is not None and self._worker.isRunning():
            logger.warning("Se omitio la impresion automatica de la factura %s: ya hay otra en curso", id_factura)
            return
        self._worker = QueryWorker(
            self.session_factory, _tarea_imprimir_factura, id_factura=id_factura, id_usuario=self.usuario.id_usuario
        )
        self._worker.resultado.connect(self._on_impresion_automatica_ok)
        self._worker.error.connect(self._on_impresion_automatica_error)
        self._worker.start()

    def _on_impresion_automatica_ok(self, nombre_impresora: str | None) -> None:
        if nombre_impresora:
            logger.info("Factura enviada automaticamente a la impresora '%s'", nombre_impresora)

    def _on_impresion_automatica_error(self, mensaje: str) -> None:
        logger.warning("Fallo la impresion automatica de la factura: %s", mensaje)
        QMessageBox.warning(
            self,
            "No se pudo imprimir",
            "La factura se emitió correctamente, pero no se pudo enviar a la impresora "
            "predeterminada configurada. Puede exportarla a PDF manualmente desde el detalle.",
        )

    def ver_detalle_factura(self) -> None:
        id_factura = self._fila_seleccionada_id()
        if id_factura is None:
            return

        session = self.session_factory()
        try:
            datos = VentaService.obtener_factura(session, id_factura, id_usuario=self.usuario.id_usuario)
            dialogo = FacturaDetalleDialog(datos, session, self.usuario.id_usuario, parent=self)
            dialogo.exec()
        except ValueError as exc:
            QMessageBox.warning(self, "No se pudo abrir la factura", str(exc))
        except Exception:
            logger.exception("Fallo al cargar el detalle de la factura %s", id_factura)
            QMessageBox.critical(self, "Error", "No se pudo cargar el detalle de la factura.")
        finally:
            session.close()

    def anular_factura_seleccionada(self) -> None:
        id_factura = self._fila_seleccionada_id()
        if id_factura is None:
            return

        motivo, ok = QInputDialog.getText(self, "Anular factura", "Motivo de la anulación:")
        motivo = motivo.strip()
        if not ok or not motivo:
            return

        respuesta = QMessageBox.question(
            self, "Confirmar", "¿Anular esta factura? Se repondrá el stock vendido y no se puede deshacer."
        )
        if respuesta != QMessageBox.StandardButton.Yes:
            return

        session = self.session_factory()
        try:
            VentaService.anular_factura(session, id_factura, id_usuario=self.usuario.id_usuario, motivo=motivo)
            self.cargar_facturas()
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "No se pudo anular la factura", str(exc))
        except Exception:
            session.rollback()
            logger.exception("Fallo al anular la factura %s", id_factura)
            QMessageBox.critical(self, "Error", "No se pudo anular la factura.")
        finally:
            session.close()

    def _filas_para_exportar(self, session) -> list[list]:
        resultado = VentaService.listar_facturas(
            session,
            numero_factura=self.buscar_input.text().strip() or None,
            estado=self.estado_combo.currentData(),
            condicion_pago=self.condicion_combo.currentData(),
            id_cliente=self.cliente_combo.currentData(),
            pagina=1,
            por_pagina=1_000_000,
            id_usuario=self.usuario.id_usuario,
        )
        return [
            [
                f.id_factura,
                f.numero_factura,
                f.cliente.nombre_razon_social if f.cliente else None,
                f.fecha_emision.strftime("%d/%m/%Y") if f.fecha_emision else None,
                "Contado" if f.condicion_pago == "contado" else "Crédito",
                float(f.total_venta),
                f.estado_factura,
            ]
            for f in resultado["items"]
        ]

    def exportar_excel_facturas(self) -> None:
        # R-09: se pide el destino ANTES de generar el archivo -- se escribe directo ahi,
        # nunca a un temporal.
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar facturas", "facturas.xlsx", "Excel (*.xlsx)")
        if not ruta:
            return

        session = self.session_factory()
        try:
            filas = self._filas_para_exportar(session)
            exportar_excel(ruta, COLS_VISIBLES, filas)
            QMessageBox.information(self, "Exportación completa", f"Se exportaron {len(filas)} facturas a:\n{ruta}")
        except Exception:
            logger.exception("Fallo al exportar el listado de facturas a Excel")
            QMessageBox.critical(self, "Error", "No se pudo exportar el listado de facturas.")
        finally:
            session.close()

    def exportar_pdf_facturas(self) -> None:
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar facturas", "facturas.pdf", "PDF (*.pdf)")
        if not ruta:
            return

        session = self.session_factory()
        try:
            filas = self._filas_para_exportar(session)
            exportar_pdf(ruta, "Facturas de Venta", COLS_VISIBLES, filas)
            QMessageBox.information(self, "Exportación completa", f"Se exportaron {len(filas)} facturas a:\n{ruta}")
        except Exception:
            logger.exception("Fallo al exportar el listado de facturas a PDF")
            QMessageBox.critical(self, "Error", "No se pudo exportar el listado de facturas.")
        finally:
            session.close()
