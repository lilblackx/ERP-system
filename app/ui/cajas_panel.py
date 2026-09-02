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

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
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

from app.db.models import Caja, Usuario
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import CajaService
from app.ui.caja_cierre_dialog import CajaCierreDialog
from app.ui.message_box import MessageBox
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    FONT_FAMILY,
    TABLE_QSS,
    EstadoBadge,
    alinear_encabezados,
    aplicar_sombra,
)

logger = logging.getLogger(__name__)

COLS_VISIBLES = ["ID", "Caja", "Estado", "Cajero", "Apertura", "Saldo Apertura", "Saldo Cierre", "Movimientos"]

DIALOG_STYLE_MOVIMIENTO = f"""
QDialog {{
    background-color: {COLOR_CONTENT_BG};
    font-family: '{FONT_FAMILY}', Arial, sans-serif;
}}
QLineEdit, QComboBox, QDoubleSpinBox {{
    background-color: #FFFFFF;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
    min-height: 20px;
}}
"""


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
        self.monto_input = QDoubleSpinBox()
        self.monto_input.setRange(0.01, 999999999.99)
        self.monto_input.setDecimals(2)
        self.monto_input.setPrefix("$ ")
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
            "monto": self.monto_input.value(),
            "descripcion": self.descripcion_input.text().strip() or None,
        }


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

        lbl = QLabel("CAJAS")
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
                1: Qt.AlignmentFlag.AlignLeft,
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

        btn_movimiento = QPushButton("Movimiento Manual")
        btn_movimiento.setIcon(qta.icon("fa5s.exchange-alt", color=COLOR_TEXT_DARK))
        btn_movimiento.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_movimiento.clicked.connect(self.registrar_movimiento_manual)

        btn_cerrar = QPushButton("Cerrar Turno")
        btn_cerrar.setIcon(qta.icon("fa5s.lock", color="white"))
        btn_cerrar.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_cerrar.clicked.connect(self.cerrar_turno_seleccionado)

        h.addWidget(btn_movimiento)
        h.addWidget(btn_cerrar)
        return w

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
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(est["id_caja"])))
            self.tabla.setItem(fila, 1, QTableWidgetItem(est["nombre_caja"] or ""))

            color = COLOR_SUCCESS if est["estado"] == "ABIERTA" else COLOR_DANGER
            badge = EstadoBadge(est["estado"].capitalize(), color)
            self.tabla.setCellWidget(fila, 2, badge)

            self.tabla.setItem(fila, 3, QTableWidgetItem(est["cajero"] or "—"))
            apertura = est.get("fecha_apertura")
            self.tabla.setItem(fila, 4, QTableWidgetItem(apertura.strftime("%d/%m/%Y %H:%M") if apertura else "—"))
            saldo_apertura = est["saldo_apertura"]
            self.tabla.setItem(
                fila, 5, QTableWidgetItem(f"$ {saldo_apertura:,.2f}" if saldo_apertura is not None else "—")
            )
            saldo_cierre = est["saldo_cierre"]
            self.tabla.setItem(fila, 6, QTableWidgetItem(f"$ {saldo_cierre:,.2f}" if saldo_cierre is not None else "—"))
            self.tabla.setItem(fila, 7, QTableWidgetItem(str(est["cantidad_movimientos"])))

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
            caja = session.get(Caja, id_caja)
            if caja is None:
                MessageBox.warning(self, "Error", "Caja no encontrada.")
                return
            if caja.fecha_apertura is None or caja.fecha_cierre is not None:
                MessageBox.information(
                    self, "Sin turno abierto", f"La caja '{caja.nombre_caja}' no tiene un turno abierto."
                )
                return

            dialogo = CajaCierreDialog(session, caja, self.usuario.id_usuario, parent=self)
            if dialogo.exec() and dialogo.cerrada:
                MessageBox.information(
                    self, "Turno cerrado", f"El turno de '{caja.nombre_caja}' se cerró correctamente."
                )
                self.cargar_cajas()
        except PermisoDenegadoError as exc:
            MessageBox.warning(self, "Sin permiso", str(exc))
        except Exception:
            logger.exception("Fallo al cerrar el turno de la caja %s", id_caja)
            MessageBox.critical(self, "Error", "No se pudo cerrar el turno de caja.")
        finally:
            session.close()

    def registrar_movimiento_manual(self) -> None:
        id_caja = self._fila_seleccionada_id()
        if id_caja is None:
            return

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
