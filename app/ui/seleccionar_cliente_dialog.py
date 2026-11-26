"""Dialogo para elegir cualquier cliente activo (busqueda server-side con pausa al
teclear, mismo patron que el combo de cliente de factura_form_dialog.py).

Lo usan los modulos de Cuentas por Cobrar y Cuentas por Cobrar BCV para registrar un
abono a un cliente que no aparece en el listado (p. ej. no tiene facturas pendientes:
su pago queda como saldo a favor via nota de credito).
"""

import logging

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from app.services.clientes import list_clientes
from app.ui.message_box import MessageBox
from app.ui.pantalla import ajustar_tamano, hacer_desplazable
from app.ui.styles import (
    COLOR_CONTENT_BG,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    FONT_FAMILY,
    SEARCH_QSS,
    TABLE_QSS,
)
from app.utils.rif import formatear_identificacion

logger = logging.getLogger(__name__)

LIMITE_RESULTADOS = 50

DIALOG_STYLE = f"""
QDialog {{
    background-color: {COLOR_CONTENT_BG};
    font-family: '{FONT_FAMILY}', Arial, sans-serif;
}}
"""


class SeleccionarClienteDialog(QDialog):
    """Devuelve `cliente_seleccionado` (Cliente) o None si se cancela."""

    def __init__(self, session_factory, id_usuario: int | None, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.id_usuario = id_usuario
        self.cliente_seleccionado = None
        self._timer_busqueda = QTimer(self)
        self._timer_busqueda.setSingleShot(True)
        self._timer_busqueda.setInterval(300)
        self._timer_busqueda.timeout.connect(self._buscar)

        self.setWindowTitle("Seleccionar Cliente")
        ajustar_tamano(self, 480, 520)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._build_ui()
        hacer_desplazable(self)
        self._buscar()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        lbl_titulo = QLabel("Seleccione el cliente que va a realizar el pago")
        lbl_titulo.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        lbl_titulo.setWordWrap(True)
        root.addWidget(lbl_titulo)

        self.buscar_input = QLineEdit()
        self.buscar_input.setPlaceholderText("Buscar por nombre, identificación, teléfono…")
        self.buscar_input.addAction(
            qta.icon("fa5s.search", color=COLOR_TEXT_MUTED),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.buscar_input.setStyleSheet(SEARCH_QSS)
        self.buscar_input.setFixedHeight(34)
        self.buscar_input.textChanged.connect(lambda _t: self._timer_busqueda.start())
        root.addWidget(self.buscar_input)

        self.lista = QListWidget()
        self.lista.setStyleSheet(TABLE_QSS)
        self.lista.itemDoubleClicked.connect(lambda _item: self._aceptar())
        root.addWidget(self.lista, 1)

        lbl_vacio = QLabel("Escriba para buscar clientes.")
        lbl_vacio.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")
        root.addWidget(lbl_vacio)

        footer = QHBoxLayout()
        footer.addStretch()
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setObjectName("BtnSecondary")
        btn_cancelar.setFixedHeight(32)
        btn_cancelar.setAutoDefault(False)
        btn_cancelar.clicked.connect(self.reject)
        btn_aceptar = QPushButton("Seleccionar")
        btn_aceptar.setObjectName("BtnPrimary")
        btn_aceptar.setFixedHeight(32)
        btn_aceptar.setAutoDefault(False)
        btn_aceptar.clicked.connect(self._aceptar)
        footer.addWidget(btn_cancelar)
        footer.addWidget(btn_aceptar)
        root.addLayout(footer)

    def _buscar(self) -> None:
        texto = self.buscar_input.text().strip() or None
        session = self.session_factory()
        try:
            resultado = list_clientes(
                session,
                texto,
                id_usuario=self.id_usuario,
                estado_cliente="ACTIVO",
                por_pagina=LIMITE_RESULTADOS,
            )
            clientes = resultado["items"]
        except Exception as exc:
            logger.exception("Fallo al buscar clientes para el abono")
            MessageBox.critical(self, "Error", f"No se pudo buscar clientes: {exc}")
            return
        finally:
            session.close()

        self.lista.clear()
        for cliente in clientes:
            identificacion = formatear_identificacion(cliente.id_legal, cliente.identificacion_cliente) or "s/i"
            item = QListWidgetItem(f"{cliente.nombre_razon_social}  —  {identificacion}")
            item.setData(Qt.ItemDataRole.UserRole, cliente)
            self.lista.addItem(item)
        if clientes:
            self.lista.setCurrentRow(0)

    def _aceptar(self) -> None:
        item = self.lista.currentItem()
        if item is None:
            MessageBox.warning(self, "Cliente requerido", "Seleccione un cliente de la lista.")
            return
        self.cliente_seleccionado = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
