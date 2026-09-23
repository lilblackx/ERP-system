"""Panel del modulo Cajas: listado de cajas con su estado de turno (abierta/cerrada),
cierre de turno (arqueo + confirmacion, CajaCierreDialog) y movimiento manual de caja
(entrada/salida durante un turno abierto). CajaService.cerrar_caja()/abrir_caja() existen
desde antes sin ninguna pantalla que los use (ver docs/ESTADO_DEL_PROYECTO.md, hallazgo
"Sin UI para cerrar un turno de caja" -- diferido a proposito hasta ahora); la apertura
sigue viviendo en app/ui/caja_apertura_dialog.py (gate de entrada a Facturacion), este
panel no la duplica.

Abrir/cerrar turno esta restringido a ADMIN en el servicio (_require_admin en
tesoreria.py, no el RBAC generico de 'cajas'/'editar') -- un cajero sin ese rol ve el
listado (con 'cajas'/'ver') pero el boton de cierre le devuelve PermisoDenegadoError."""

import logging
from datetime import date, datetime
from decimal import Decimal

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.db.models import Caja, CajaMovimiento, Usuario
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import CajaService
from app.ui.caja_cierre_dialog import CajaCierreDialog
from app.ui.message_box import MessageBox
from app.ui.numeric_inputs import NumericFieldType, NumericLineEdit
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    COLOR_WHITE,
    FONT_FAMILY,
    TABLE_QSS,
    EstadoBadge,
    alinear_encabezados,
    aplicar_sombra,
)

logger = logging.getLogger(__name__)

COLS_VISIBLES = ["ID", "CAJA", "ESTADO", "CAJERO", "APERTURA", "SALDO APERTURA", "SALDO CIERRE", "MOVIMIENTOS"]

DIALOG_STYLE_MOVIMIENTO = f"""
QDialog {{
    background-color: {COLOR_CONTENT_BG};
    font-family: '{FONT_FAMILY}', Arial, sans-serif;
}}
QLineEdit, QComboBox {{
    background-color: {COLOR_WHITE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
    min-height: 20px;
}}
"""

DIALOG_STYLE_HISTORIAL = f"""
QDialog {{
    background-color: {COLOR_CONTENT_BG};
    font-family: '{FONT_FAMILY}', Arial, sans-serif;
}}
QWidget#SectionCard {{
    background-color: {COLOR_CARD_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
}}
"""


class CajaFormDialog(QDialog):
    """Formulario minimo para crear una caja nueva (turno todavia no abierto) --
    CajaService.crear_caja() existia sin ningun caller de UI: no habia forma de dar de
    alta una caja fisica desde la app, solo de abrir/cerrar el turno de una ya existente."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nueva Caja")
        self.setMinimumWidth(360)
        self.setStyleSheet(DIALOG_STYLE_MOVIMIENTO)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Nombre de la Caja"))
        self.nombre_input = QLineEdit()
        self.nombre_input.setPlaceholderText("Ej. Caja Principal")
        self.nombre_input.setMaxLength(50)
        layout.addWidget(self.nombre_input)

        botones = QHBoxLayout()
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_cancelar.clicked.connect(self.reject)
        btn_guardar = QPushButton("Crear")
        btn_guardar.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_guardar.clicked.connect(self.accept)
        botones.addStretch()
        botones.addWidget(btn_cancelar)
        botones.addWidget(btn_guardar)
        layout.addLayout(botones)

    def get_nombre(self) -> str:
        return self.nombre_input.text().strip()


class MovimientoManualDialog(QDialog):
    """Formulario minimo para registrar un ingreso/egreso manual de caja durante un turno
    abierto (ej. compra menor de insumos, un retiro parcial) -- CajaService.
    registrar_movimiento_manual() existia sin ningun caller de UI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Movimiento Manual de Caja")
        self.setMinimumWidth(360)
        self.setStyleSheet(DIALOG_STYLE_MOVIMIENTO)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Tipo de movimiento"))
        self.tipo_combo = QComboBox()
        self.tipo_combo.addItem("Entrada", "entrada")
        self.tipo_combo.addItem("Salida", "salida")
        layout.addWidget(self.tipo_combo)

        layout.addWidget(QLabel("Monto"))
        self.monto_input = NumericLineEdit(NumericFieldType.AMOUNT, min_value=Decimal("0.01"), prefix="$ ")
        layout.addWidget(self.monto_input)

        layout.addWidget(QLabel("Descripción"))
        self.descripcion_input = QLineEdit()
        self.descripcion_input.setPlaceholderText("Motivo del movimiento (opcional)")
        self.descripcion_input.setMaxLength(255)
        layout.addWidget(self.descripcion_input)

        botones = QHBoxLayout()
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_cancelar.clicked.connect(self.reject)
        btn_guardar = QPushButton("Registrar")
        btn_guardar.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_guardar.clicked.connect(self.accept)
        botones.addStretch()
        botones.addWidget(btn_cancelar)
        botones.addWidget(btn_guardar)
        layout.addLayout(botones)

    def get_data(self) -> dict:
        return {
            "tipo": self.tipo_combo.currentData(),
            "monto": self.monto_input.get_value(),
            "descripcion": self.descripcion_input.text().strip() or None,
        }


class HistorialMovimientosDialog(QDialog):
    """Dialogo para ver el historial de movimientos de una caja filtrado por fecha."""

    def __init__(self, session_factory, id_caja: int, nombre_caja: str, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.id_caja = id_caja
        self.nombre_caja = nombre_caja
        self.usuario = usuario

        self.setWindowTitle(f"Historial de Movimientos - {nombre_caja}")
        self.setMinimumWidth(700)
        self.resize(700, 500)
        self.setStyleSheet(DIALOG_STYLE_HISTORIAL)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()
        # Cargar historial directamente
        self._cargar_historial()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # Header con filtros de fecha
        header = QHBoxLayout()
        header.setSpacing(12)

        header.addWidget(QLabel("Desde:"))
        self.fecha_desde = QLineEdit()
        self.fecha_desde.setPlaceholderText("DD/MM/YYYY")
        self.fecha_desde.setFixedWidth(120)
        header.addWidget(self.fecha_desde)

        header.addWidget(QLabel("Hasta:"))
        self.fecha_hasta = QLineEdit()
        self.fecha_hasta.setPlaceholderText("DD/MM/YYYY")
        self.fecha_hasta.setFixedWidth(120)
        header.addWidget(self.fecha_hasta)

        btn_filtrar = QPushButton("Filtrar")
        btn_filtrar.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_filtrar.clicked.connect(self._cargar_historial)
        header.addWidget(btn_filtrar)

        btn_hoy = QPushButton("Hoy")
        btn_hoy.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_hoy.clicked.connect(self._filtrar_hoy)
        header.addWidget(btn_hoy)

        header.addStretch()
        root.addLayout(header)

        # Tabla de movimientos
        self.tabla = QTableWidget(0, 5)
        self.tabla.setHorizontalHeaderLabels(["Fecha", "Tipo", "Descripción", "Monto", "Origen"])
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setShowGrid(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(self.tabla)
        alinear_encabezados(
            self.tabla,
            {
                0: Qt.AlignmentFlag.AlignLeft,
                1: Qt.AlignmentFlag.AlignLeft,
                2: Qt.AlignmentFlag.AlignLeft,
                3: Qt.AlignmentFlag.AlignRight,
                4: Qt.AlignmentFlag.AlignLeft,
            },
        )
        root.addWidget(self.tabla, stretch=1)

        # Footer con resumen
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 8, 0, 0)
        footer.setSpacing(24)

        self.lbl_total_entradas = QLabel("Total Entradas: $0.00")
        self.lbl_total_entradas.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {COLOR_SUCCESS};")

        self.lbl_total_salidas = QLabel("Total Salidas: $0.00")
        self.lbl_total_salidas.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {COLOR_DANGER};")

        self.lbl_saldo = QLabel("Saldo Neto: $0.00")
        self.lbl_saldo.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {COLOR_PRIMARY};")

        footer.addWidget(self.lbl_total_entradas)
        footer.addWidget(self.lbl_total_salidas)
        footer.addStretch()
        footer.addWidget(self.lbl_saldo)

        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_cerrar.clicked.connect(self.accept)
        footer.addWidget(btn_cerrar)

        root.addLayout(footer)

    def _filtrar_hoy(self) -> None:
        hoy = date.today()
        self.fecha_desde.setText(hoy.strftime("%d/%m/%Y"))
        self.fecha_hasta.setText(hoy.strftime("%d/%m/%Y"))
        self._cargar_historial()

    def _cargar_historial(self) -> None:
        try:
            # Parsear fechas
            fecha_desde = None
            fecha_hasta = None

            if self.fecha_desde.text().strip():
                try:
                    fecha_desde = datetime.strptime(self.fecha_desde.text().strip(), "%d/%m/%Y").date()
                except ValueError:
                    MessageBox.warning(self, "Fecha inválida", "El formato de 'Desde' debe ser DD/MM/YYYY")
                    return

            if self.fecha_hasta.text().strip():
                try:
                    fecha_hasta = datetime.strptime(self.fecha_hasta.text().strip(), "%d/%m/%Y").date()
                except ValueError:
                    MessageBox.warning(self, "Fecha inválida", "El formato de 'Hasta' debe ser DD/MM/YYYY")
                    return

            # Si no hay fechas, mostrar movimientos de hoy
            if not fecha_desde and not fecha_hasta:
                hoy = date.today()
                fecha_desde = hoy
                fecha_hasta = hoy
                self.fecha_desde.setText(hoy.strftime("%d/%m/%Y"))
                self.fecha_hasta.setText(hoy.strftime("%d/%m/%Y"))

            session = self.session_factory()
            try:
                query = session.query(CajaMovimiento).filter(CajaMovimiento.id_caja == self.id_caja)

                if fecha_desde:
                    desde_dt = datetime.combine(fecha_desde, datetime.min.time())
                    query = query.filter(CajaMovimiento.fecha_registro >= desde_dt)

                if fecha_hasta:
                    hasta_dt = datetime.combine(fecha_hasta, datetime.max.time())
                    query = query.filter(CajaMovimiento.fecha_registro <= hasta_dt)

                movimientos = query.order_by(CajaMovimiento.fecha_registro.desc()).all()

                self.tabla.setRowCount(len(movimientos))
                total_entradas = Decimal("0.00")
                total_salidas = Decimal("0.00")

                for fila, mov in enumerate(movimientos):
                    fecha_str = mov.fecha_registro.strftime("%d/%m/%Y %H:%M")
                    self.tabla.setItem(fila, 0, QTableWidgetItem(fecha_str))

                    es_entrada = mov.tipo_movimiento == "entrada"
                    tipo_item = QTableWidgetItem("Entrada" if es_entrada else "Salida")
                    tipo_item.setForeground(Qt.GlobalColor.darkGreen if es_entrada else Qt.GlobalColor.red)
                    self.tabla.setItem(fila, 1, tipo_item)

                    self.tabla.setItem(fila, 2, QTableWidgetItem(mov.descripcion_movimiento or ""))

                    monto = mov.monto_movimiento or Decimal("0.00")
                    item_monto = QTableWidgetItem(f"$ {monto:,.2f}")
                    item_monto.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.tabla.setItem(fila, 3, item_monto)

                    # Determinar origen
                    origen = "Manual"
                    if mov.id_pago_cobro:
                        origen = "Cobro"
                    elif mov.id_pago_proveedor:
                        origen = "Pago Proveedor"
                    elif mov.id_pago_comision:
                        origen = "Pago Comisión"
                    self.tabla.setItem(fila, 4, QTableWidgetItem(origen))

                    if es_entrada:
                        total_entradas += monto
                    else:
                        total_salidas += monto

                self.lbl_total_entradas.setText(f"Total Entradas: ${total_entradas:,.2f}")
                self.lbl_total_salidas.setText(f"Total Salidas: ${total_salidas:,.2f}")
                saldo_neto = total_entradas - total_salidas
                self.lbl_saldo.setText(f"Saldo Neto: ${saldo_neto:,.2f}")

            finally:
                session.close()

        except Exception as e:
            logger.exception("Fallo al cargar historial de movimientos")
            MessageBox.critical(self, "Error", f"No se pudo cargar el historial: {str(e)}")


class CajasPanel(QWidget):
    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.setObjectName("ContentArea")
        self._setup_ui()
        QTimer.singleShot(100, self.cargar_cajas)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.cargar_cajas()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        root.addWidget(self._make_header())
        root.addWidget(self._make_table())
        root.addWidget(self._make_footer())

        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

    def _make_header(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("Cajas")
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

        btn_nueva_caja = QPushButton("Nueva Caja")
        btn_nueva_caja.setIcon(qta.icon("fa5s.plus", color="white"))
        btn_nueva_caja.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_nueva_caja.clicked.connect(self.crear_caja)
        h.addWidget(btn_nueva_caja)

        btn_refrescar = QPushButton("Actualizar")
        btn_refrescar.setIcon(qta.icon("fa5s.sync-alt", color="white"))
        btn_refrescar.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_refrescar.clicked.connect(self.cargar_cajas)
        h.addWidget(btn_refrescar)
        return w

    def _make_table(self) -> QTableWidget:
        self.tabla = QTableWidget(0, len(COLS_VISIBLES))
        self.tabla.setHorizontalHeaderLabels(COLS_VISIBLES)
        alinear_encabezados(
            self.tabla,
            {
                0: Qt.AlignmentFlag.AlignLeft,
                1: Qt.AlignmentFlag.AlignLeft,
                2: Qt.AlignmentFlag.AlignCenter,
                3: Qt.AlignmentFlag.AlignLeft,
                4: Qt.AlignmentFlag.AlignLeft,
                5: Qt.AlignmentFlag.AlignRight,
                6: Qt.AlignmentFlag.AlignRight,
                7: Qt.AlignmentFlag.AlignRight,
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
        self.tabla.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.tabla.setColumnWidth(2, 100)
        self.tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(self.tabla)
        self.tabla.verticalHeader().setDefaultSectionSize(45)
        return self.tabla

    def _make_footer(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addStretch()

        self.btn_movimiento = QPushButton("Movimiento Manual")
        self.btn_movimiento.setIcon(qta.icon("fa5s.exchange-alt", color=COLOR_TEXT_DARK))
        self.btn_movimiento.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_movimiento.clicked.connect(self.registrar_movimiento_manual)

        btn_historial = QPushButton("Ver Historial")
        btn_historial.setIcon(qta.icon("fa5s.history", color=COLOR_TEXT_DARK))
        btn_historial.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_historial.clicked.connect(self.ver_historial_movimientos)

        btn_cerrar = QPushButton("Cerrar Turno")
        btn_cerrar.setIcon(qta.icon("fa5s.lock", color="white"))
        btn_cerrar.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_cerrar.clicked.connect(self.cerrar_turno_seleccionado)

        h.addWidget(self.btn_movimiento)
        h.addWidget(btn_historial)
        h.addWidget(btn_cerrar)
        return w

    def crear_caja(self) -> None:
        dialogo = CajaFormDialog(parent=self)
        if not dialogo.exec():
            return
        nombre = dialogo.get_nombre()

        session = self.session_factory()
        try:
            caja = CajaService.crear_caja(session, nombre, id_usuario=self.usuario.id_usuario)
            self.cargar_cajas()
            MessageBox.information(self, "Caja creada", f"La caja '{caja.nombre_caja}' fue creada correctamente.")
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError as exc:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", str(exc))
        except Exception:
            session.rollback()
            logger.exception("Fallo al crear la caja")
            MessageBox.critical(self, "Error", "No se pudo crear la caja.")
        finally:
            session.close()

    def cargar_cajas(self) -> None:
        session = self.session_factory()
        try:
            estados = CajaService.obtener_estado_cajas(session, id_usuario=self.usuario.id_usuario)
            self._poblar_tabla(estados)
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar cajas.")
        except Exception:
            logger.exception("Fallo al cargar el estado de las cajas")
            MessageBox.critical(self, "Error de conexión", "No se pudo cargar el estado de las cajas.")
        finally:
            session.close()

    def _poblar_tabla(self, estados: list[dict]) -> None:
        self.tabla.setRowCount(len(estados))
        for fila, est in enumerate(estados):
            item_id = QTableWidgetItem(str(est["id_caja"]))
            item_id.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 0, item_id)

            item_nombre = QTableWidgetItem(est["nombre_caja"] or "")
            item_nombre.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 1, item_nombre)

            color = COLOR_SUCCESS if est["estado"] == "ABIERTA" else COLOR_DANGER
            badge = EstadoBadge(est["estado"].capitalize(), color)
            self.tabla.setCellWidget(fila, 2, badge)

            item_cajero = QTableWidgetItem(est["cajero"] or "—")
            item_cajero.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 3, item_cajero)

            apertura = est.get("fecha_apertura")
            item_apertura = QTableWidgetItem(apertura.strftime("%d/%m/%Y %H:%M") if apertura else "—")
            item_apertura.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 4, item_apertura)

            saldo_apertura = est["saldo_apertura"]
            item_saldo_apertura = QTableWidgetItem(f"$ {saldo_apertura:,.2f}" if saldo_apertura is not None else "—")
            item_saldo_apertura.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 5, item_saldo_apertura)

            saldo_cierre = est["saldo_cierre"]
            item_saldo_cierre = QTableWidgetItem(f"$ {saldo_cierre:,.2f}" if saldo_cierre is not None else "—")
            item_saldo_cierre.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 6, item_saldo_cierre)

            item_movimientos = QTableWidgetItem(str(est["cantidad_movimientos"]))
            item_movimientos.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 7, item_movimientos)

        self.lbl_total.setText(f"{len(estados)} caja{'s' if len(estados) != 1 else ''}")

    def _fila_seleccionada_id(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            MessageBox.information(self, "Selección requerida", "Selecciona una caja de la lista.")
            return None
        item = self.tabla.item(filas[0].row(), 0)
        if item is None:
            return None
        return int(item.text())

    def cerrar_turno_seleccionado(self) -> None:
        id_caja = self._fila_seleccionada_id()
        if id_caja is None:
            return

        session = self.session_factory()
        try:
            print(f"DEBUG: Cerrando turno para caja id={id_caja}")
            caja = session.get(Caja, id_caja)
            if caja is None:
                MessageBox.warning(self, "Error", "Caja no encontrada.")
                return
            if caja.fecha_apertura is None or caja.fecha_cierre is not None:
                MessageBox.information(
                    self, "Sin turno abierto", f"La caja '{caja.nombre_caja}' no tiene un turno abierto."
                )
                return

            print(f"DEBUG: Abriendo diálogo de cierre para caja {caja.nombre_caja}")
            dialogo = CajaCierreDialog(session, caja, self.usuario.id_usuario, parent=self)
            print(f"DEBUG: Diálogo ejecutado, cerrada={dialogo.cerrada}")
            if dialogo.exec() and dialogo.cerrada:
                MessageBox.information(
                    self, "Turno cerrado", f"El turno de '{caja.nombre_caja}' se cerró correctamente."
                )
                self.cargar_cajas()
        except PermisoDenegadoError as exc:
            print(f"DEBUG: PermisoDenegadoError: {str(exc)}")
            MessageBox.warning(self, "Sin permiso", str(exc))
        except Exception as exc:
            import traceback
            print(f"DEBUG: Exception al cerrar turno: {str(exc)}")
            print(traceback.format_exc())
            logger.exception("Fallo al cerrar el turno de la caja %s", id_caja)
            MessageBox.critical(self, "Error", f"No se pudo cerrar el turno de caja: {str(exc)}")
        finally:
            session.close()

    def registrar_movimiento_manual(self) -> None:
        id_caja = self._fila_seleccionada_id()
        if id_caja is None:
            return

        self.btn_movimiento.setEnabled(False)
        session = self.session_factory()
        try:
            caja = session.get(Caja, id_caja)
            if caja is None:
                MessageBox.warning(self, "Error", "Caja no encontrada.")
                return
            if caja.fecha_apertura is None or caja.fecha_cierre is not None:
                MessageBox.warning(
                    self, "Sin turno abierto", f"La caja '{caja.nombre_caja}' no tiene un turno abierto."
                )
                return

            dialogo = MovimientoManualDialog(parent=self)
            if not dialogo.exec():
                return
            datos = dialogo.get_data()

            CajaService.registrar_movimiento_manual(
                session,
                id_caja=id_caja,
                tipo=datos["tipo"],
                monto=datos["monto"],
                descripcion=datos["descripcion"],
                id_usuario=self.usuario.id_usuario,
            )
            self.cargar_cajas()
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para registrar movimientos de caja.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al registrar movimiento manual de caja %s", id_caja)
            MessageBox.critical(self, "Error", "No se pudo registrar el movimiento de caja.")
        finally:
            session.close()
            self.btn_movimiento.setEnabled(True)

    def ver_historial_movimientos(self) -> None:
        id_caja = self._fila_seleccionada_id()
        if id_caja is None:
            return

        try:
            session = self.session_factory()
            try:
                caja = session.get(Caja, id_caja)
                if caja is None:
                    MessageBox.warning(self, "Error", "Caja no encontrada.")
                    return

                nombre_caja = caja.nombre_caja or f"Caja {id_caja}"
                print(f"Abriendo historial para caja: {nombre_caja} (id: {id_caja})")
                dialogo = HistorialMovimientosDialog(
                    self.session_factory, id_caja, nombre_caja, self.usuario, parent=self
                )
                dialogo.exec()
            finally:
                session.close()
        except Exception as e:
            import traceback
            logger.exception("Fallo al abrir historial de movimientos para caja %s", id_caja)
            print(f"Error al abrir historial: {str(e)}")
            print(traceback.format_exc())
            MessageBox.critical(self, "Error", f"No se pudo abrir el historial de movimientos: {str(e)}")
