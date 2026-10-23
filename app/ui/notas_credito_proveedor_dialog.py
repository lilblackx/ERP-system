"""Notas de credito de proveedor (saldo a favor de la empresa al anular una compra ya
pagada) y sus dos formas de consumirlas, desde Cuentas por Pagar:

- Aplicar a una deuda: descuenta de otra cuenta por pagar abierta del mismo proveedor
  (NotaCreditoService.aplicar_nota_credito_proveedor) -- compensacion, no mueve dinero.
- Registrar reembolso: el proveedor devolvio el dinero, entra a una caja o cuenta bancaria
  (NotaCreditoService.reembolsar_nota_credito_proveedor).

Mismo patron que AplicarNotaCreditoDialog/DevolverNotaCreditoDialog del lado cliente."""

import logging
from decimal import Decimal

from PySide6.QtCore import Qt
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
from sqlalchemy.orm import Session

from app.db.models import NotaCreditoProveedor
from app.services.notas_credito import NotaCreditoService
from app.services.pagos import PagoService
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import BancoService, CajaService
from app.ui.animaciones import liberar_boton, ocupar_boton
from app.ui.message_box import MessageBox
from app.ui.numeric_inputs import NumericFieldType, NumericLineEdit, _as_decimal
from app.ui.pantalla import ajustar_tamano, hacer_desplazable
from app.ui.styles import (
    ASTERISCO_REQUERIDO,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_FIELD_BG,
    COLOR_PRIMARY,
    COLOR_PRIMARY_DARK,
    COLOR_PRIMARY_LIGHT,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_DARK_SLATE,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MEDIUM,
    COLOR_TEXT_MUTED,
    COLOR_WHITE,
    FONT_FAMILY,
    ICON_CHEVRON_DOWN_URL,
    TABLE_QSS,
    aplicar_sombra,
)

logger = logging.getLogger(__name__)

METODOS_REEMBOLSO = [
    ("Efectivo", "efectivo"),
    ("Pago Móvil", "pago_movil"),
    ("Transferencia", "transferencia"),
]

DIALOG_STYLE = f"""
QDialog {{
    background-color: {COLOR_CONTENT_BG};
    font-family: '{FONT_FAMILY}', Arial, sans-serif;
}}
QWidget#SectionCard {{
    background-color: {COLOR_CARD_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
}}
QLabel.FormLabel {{
    font-size: 12px;
    font-weight: 600;
    color: {COLOR_TEXT_DARK_SLATE};
    margin-bottom: 2px;
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
QLineEdit:focus, QComboBox:focus {{
    border: 1.5px solid {COLOR_PRIMARY};
}}
QLineEdit:disabled, QComboBox:disabled {{
    background-color: {COLOR_CONTENT_BG};
    color: {COLOR_TEXT_LIGHT};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox::down-arrow {{
    image: url({ICON_CHEVRON_DOWN_URL});
    width: 12px;
    height: 12px;
    margin-right: 6px;
}}
QPushButton#BtnPrimary {{
    background-color: {COLOR_PRIMARY};
    color: {COLOR_WHITE};
    border: none;
    border-radius: 6px;
    padding: 8px 22px;
    font-size: 13px;
    font-weight: bold;
}}
QPushButton#BtnPrimary:hover {{
    background-color: {COLOR_PRIMARY_LIGHT};
}}
QPushButton#BtnPrimary:pressed {{
    background-color: {COLOR_PRIMARY_DARK};
}}
QPushButton#BtnPrimary:disabled {{
    background-color: {COLOR_BORDER};
    color: {COLOR_TEXT_LIGHT};
}}
QPushButton#BtnSecondary {{
    background-color: {COLOR_FIELD_BG};
    color: {COLOR_TEXT_MEDIUM};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#BtnSecondary:hover {{
    background-color: {COLOR_TABLE_HEADER};
    color: {COLOR_TEXT_DARK};
}}
"""


def _nombre_proveedor(nota: NotaCreditoProveedor) -> str:
    return nota.proveedor.nombre_razon_social if nota.proveedor else "—"


def _numero_compra(nota: NotaCreditoProveedor) -> str:
    return nota.compra_origen.numero_compra if nota.compra_origen else "—"


def _footer(dialogo: QDialog, texto_aceptar: str, on_aceptar) -> tuple[QHBoxLayout, QPushButton]:
    footer = QHBoxLayout()
    footer.addStretch()
    btn_cancelar = QPushButton("Cancelar")
    btn_cancelar.setObjectName("BtnSecondary")
    btn_cancelar.setFixedHeight(34)
    btn_cancelar.setAutoDefault(False)
    btn_cancelar.clicked.connect(dialogo.reject)
    btn_aceptar = QPushButton(texto_aceptar)
    btn_aceptar.setObjectName("BtnPrimary")
    btn_aceptar.setFixedHeight(34)
    btn_aceptar.setAutoDefault(False)
    btn_aceptar.clicked.connect(on_aceptar)
    footer.addWidget(btn_cancelar)
    footer.addWidget(btn_aceptar)
    return footer, btn_aceptar


def _card_nota(nota: NotaCreditoProveedor) -> QLabel:
    saldo = _as_decimal(nota.saldo_disponible)
    lbl = QLabel(
        f"{_nombre_proveedor(nota)} · compra anulada {_numero_compra(nota)}\nSaldo a favor: ${float(saldo):,.2f}"
    )
    lbl.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_MUTED};")
    return lbl


class AplicarNotaCreditoProveedorDialog(QDialog):
    """Descuenta el saldo de la nota de una cuenta por pagar abierta del mismo proveedor."""

    def __init__(self, session: Session, id_usuario: int | None, nota: NotaCreditoProveedor, parent=None):
        super().__init__(parent)
        self.session = session
        self.id_usuario = id_usuario
        self.nota = nota
        self.aplicada = False
        resultado = PagoService.listar_cuentas_por_pagar(
            session, id_proveedor=nota.id_proveedor, por_pagina=10_000, id_usuario=id_usuario
        )
        self.cuentas = [c for c in resultado["items"] if c.estado in ("pendiente", "parcial", "vencida")]

        self.setWindowTitle("Aplicar nota de crédito a una deuda")
        ajustar_tamano(self, 460, 360)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._build_ui()
        hacer_desplazable(self)
        self._on_cuenta_cambiada()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(_card_nota(self.nota))

        lbl_cuenta = QLabel(f"Cuenta por pagar {ASTERISCO_REQUERIDO}")
        lbl_cuenta.setProperty("class", "FormLabel")
        self.cuenta_combo = QComboBox()
        self.cuenta_combo.setFixedHeight(32)
        if not self.cuentas:
            self.cuenta_combo.addItem("Este proveedor no tiene deudas abiertas")
            self.cuenta_combo.setEnabled(False)
        for cuenta in self.cuentas:
            numero = cuenta.compra.numero_compra if cuenta.compra else f"Cuenta {cuenta.id_cuenta}"
            saldo = _as_decimal(cuenta.saldo_pendiente)
            self.cuenta_combo.addItem(f"{numero} — saldo ${float(saldo):,.2f}", cuenta)
        self.cuenta_combo.currentIndexChanged.connect(self._on_cuenta_cambiada)
        layout.addWidget(lbl_cuenta)
        layout.addWidget(self.cuenta_combo)

        lbl_monto = QLabel(f"Monto a aplicar (USD) {ASTERISCO_REQUERIDO}")
        lbl_monto.setProperty("class", "FormLabel")
        self.monto_input = NumericLineEdit(NumericFieldType.AMOUNT, min_value=Decimal("0.01"), prefix="$ ")
        self.monto_input.setFixedHeight(32)
        layout.addWidget(lbl_monto)
        layout.addWidget(self.monto_input)
        root.addWidget(card, stretch=1)

        footer, self.btn_aplicar = _footer(self, "Aplicar", self._validar_y_aceptar)
        self.btn_aplicar.setEnabled(bool(self.cuentas))
        root.addLayout(footer)

    def _on_cuenta_cambiada(self) -> None:
        cuenta = self.cuenta_combo.currentData()
        if cuenta is None:
            return
        tope = min(_as_decimal(self.nota.saldo_disponible), _as_decimal(cuenta.saldo_pendiente))
        self.monto_input.max_value = tope
        self.monto_input.set_value(tope)

    def _validar_y_aceptar(self) -> None:
        cuenta = self.cuenta_combo.currentData()
        if cuenta is None:
            return
        ocupar_boton(self.btn_aplicar)
        try:
            NotaCreditoService.aplicar_nota_credito_proveedor(
                self.session,
                id_nota_credito=self.nota.id_nota_credito,
                id_cuenta_por_pagar=cuenta.id_cuenta,
                monto=self.monto_input.get_value(),
                id_usuario=self.id_usuario,
            )
        except ValueError as exc:
            self.session.rollback()
            MessageBox.warning(self, "No se pudo aplicar la nota", str(exc))
            return
        except PermisoDenegadoError:
            self.session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para aplicar notas de crédito.")
            return
        except Exception:
            self.session.rollback()
            logger.exception("Fallo al aplicar nota de credito de proveedor")
            MessageBox.critical(self, "Error", "No se pudo aplicar la nota de crédito.")
            return
        finally:
            liberar_boton(self.btn_aplicar)
        self.aplicada = True
        self.accept()


class ReembolsoNotaCreditoProveedorDialog(QDialog):
    """Registra el dinero que el proveedor devolvio: ingreso a una caja o cuenta bancaria."""

    def __init__(self, session: Session, id_usuario: int | None, nota: NotaCreditoProveedor, parent=None):
        super().__init__(parent)
        self.session = session
        self.id_usuario = id_usuario
        self.nota = nota
        self.registrado = False
        try:
            cajas = CajaService.listar_cajas(session, id_usuario=id_usuario)
        except PermisoDenegadoError:
            cajas = []
        self._cajas_abiertas = [c for c in cajas if c.fecha_apertura is not None and c.fecha_cierre is None]
        try:
            cuentas = BancoService.listar_cuentas(session, id_usuario=id_usuario)
        except PermisoDenegadoError:
            cuentas = []
        self._cuentas_activas = [c for c in cuentas if (c.estado_cuenta or "ACTIVO") == "ACTIVO"]

        self.setWindowTitle("Registrar reembolso del proveedor")
        ajustar_tamano(self, 460, 440)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._build_ui()
        hacer_desplazable(self)
        self._on_metodo_cambiado()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(_card_nota(self.nota))

        lbl_metodo = QLabel(f"Cómo devolvió el dinero {ASTERISCO_REQUERIDO}")
        lbl_metodo.setProperty("class", "FormLabel")
        self.metodo_combo = QComboBox()
        for etiqueta, valor in METODOS_REEMBOLSO:
            self.metodo_combo.addItem(etiqueta, valor)
        self.metodo_combo.setFixedHeight(32)
        self.metodo_combo.currentIndexChanged.connect(self._on_metodo_cambiado)
        layout.addWidget(lbl_metodo)
        layout.addWidget(self.metodo_combo)

        lbl_destino = QLabel(f"Destino {ASTERISCO_REQUERIDO}")
        lbl_destino.setProperty("class", "FormLabel")
        self.destino_combo = QComboBox()
        self.destino_combo.setFixedHeight(32)
        layout.addWidget(lbl_destino)
        layout.addWidget(self.destino_combo)

        lbl_monto = QLabel(f"Monto recibido (USD) {ASTERISCO_REQUERIDO}")
        lbl_monto.setProperty("class", "FormLabel")
        saldo = _as_decimal(self.nota.saldo_disponible)
        self.monto_input = NumericLineEdit(
            NumericFieldType.AMOUNT, min_value=Decimal("0.01"), max_value=saldo, prefix="$ "
        )
        self.monto_input.set_value(saldo)
        self.monto_input.setFixedHeight(32)
        layout.addWidget(lbl_monto)
        layout.addWidget(self.monto_input)

        self.lbl_referencia = QLabel(f"Referencia bancaria {ASTERISCO_REQUERIDO}")
        self.lbl_referencia.setProperty("class", "FormLabel")
        self.referencia_input = QLineEdit()
        self.referencia_input.setPlaceholderText("Mínimo 4 caracteres")
        self.referencia_input.setMaxLength(50)
        self.referencia_input.setFixedHeight(32)
        layout.addWidget(self.lbl_referencia)
        layout.addWidget(self.referencia_input)
        root.addWidget(card, stretch=1)

        footer, self.btn_registrar = _footer(self, "Registrar reembolso", self._validar_y_aceptar)
        root.addLayout(footer)

    def _on_metodo_cambiado(self) -> None:
        es_efectivo = self.metodo_combo.currentData() == "efectivo"
        self.lbl_referencia.setVisible(not es_efectivo)
        self.referencia_input.setVisible(not es_efectivo)
        self.destino_combo.clear()
        if es_efectivo:
            for caja in self._cajas_abiertas:
                self.destino_combo.addItem(caja.nombre_caja or f"Caja {caja.id_caja}", ("caja", caja.id_caja))
            vacio = "Sin cajas con turno abierto"
        else:
            for cuenta in self._cuentas_activas:
                nombre_banco = cuenta.banco.nombre_banco if cuenta.banco else "Banco"
                self.destino_combo.addItem(
                    f"{nombre_banco} - ...{cuenta.numero_cuenta[-4:]}", ("banco", cuenta.id_cuenta)
                )
            vacio = "Sin cuentas bancarias activas"
        hay_destino = self.destino_combo.count() > 0
        if not hay_destino:
            self.destino_combo.addItem(vacio)
        self.destino_combo.setEnabled(hay_destino)
        self.btn_registrar.setEnabled(hay_destino)

    def _validar_y_aceptar(self) -> None:
        destino = self.destino_combo.currentData()
        if destino is None:
            return
        tipo_destino, id_destino = destino
        ocupar_boton(self.btn_registrar)
        try:
            NotaCreditoService.reembolsar_nota_credito_proveedor(
                self.session,
                id_nota_credito=self.nota.id_nota_credito,
                monto=self.monto_input.get_value(),
                metodo_reembolso=self.metodo_combo.currentData(),
                id_usuario=self.id_usuario,
                id_caja=id_destino if tipo_destino == "caja" else None,
                id_cuenta_bancaria=id_destino if tipo_destino == "banco" else None,
                referencia=self.referencia_input.text().strip() or None,
            )
        except ValueError as exc:
            self.session.rollback()
            MessageBox.warning(self, "No se pudo registrar el reembolso", str(exc))
            return
        except PermisoDenegadoError:
            self.session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para registrar reembolsos.")
            return
        except Exception:
            self.session.rollback()
            logger.exception("Fallo al registrar reembolso de nota de credito de proveedor")
            MessageBox.critical(self, "Error", "No se pudo registrar el reembolso.")
            return
        finally:
            liberar_boton(self.btn_registrar)
        self.registrado = True
        self.accept()


class NotasCreditoProveedorDialog(QDialog):
    """Listado de notas de credito de proveedor con saldo a favor, con las dos acciones."""

    def __init__(self, session_factory, id_usuario: int | None, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.id_usuario = id_usuario
        self.hubo_cambios = False
        self._notas: list[NotaCreditoProveedor] = []

        self.setWindowTitle("Notas de crédito de proveedores")
        ajustar_tamano(self, 760, 460)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._build_ui()
        self.cargar()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        lbl_titulo = QLabel("Saldo a favor con proveedores")
        lbl_titulo.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        root.addWidget(lbl_titulo)
        lbl_ayuda = QLabel(
            "Se generan al anular una compra que ya estaba pagada. Aplícalas a otra deuda del mismo "
            "proveedor, o registra el reembolso cuando el proveedor devuelva el dinero."
        )
        lbl_ayuda.setWordWrap(True)
        lbl_ayuda.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        root.addWidget(lbl_ayuda)

        self.tabla = QTableWidget(0, 6)
        self.tabla.setHorizontalHeaderLabels(["ID", "Proveedor", "Compra anulada", "Fecha", "Monto", "Disponible"])
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.setColumnHidden(0, True)
        self.tabla.setStyleSheet(TABLE_QSS)
        root.addWidget(self.tabla, stretch=1)

        footer = QHBoxLayout()
        self.lbl_total = QLabel("")
        self.lbl_total.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        footer.addWidget(self.lbl_total)
        footer.addStretch()
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setObjectName("BtnSecondary")
        btn_cerrar.setAutoDefault(False)
        btn_cerrar.clicked.connect(self.accept)
        self.btn_aplicar = QPushButton("Aplicar a una deuda")
        self.btn_aplicar.setObjectName("BtnSecondary")
        self.btn_aplicar.setAutoDefault(False)
        self.btn_aplicar.clicked.connect(self.aplicar_seleccionada)
        self.btn_reembolso = QPushButton("Registrar reembolso")
        self.btn_reembolso.setObjectName("BtnPrimary")
        self.btn_reembolso.setAutoDefault(False)
        self.btn_reembolso.clicked.connect(self.reembolsar_seleccionada)
        footer.addWidget(btn_cerrar)
        footer.addWidget(self.btn_aplicar)
        footer.addWidget(self.btn_reembolso)
        root.addLayout(footer)

    def cargar(self) -> None:
        session = self.session_factory()
        try:
            self._notas = NotaCreditoService.listar_notas_credito_proveedor_disponibles(
                session, id_usuario=self.id_usuario
            )
            filas = [
                (
                    nota.id_nota_credito,
                    _nombre_proveedor(nota),
                    _numero_compra(nota),
                    nota.fecha_creacion.strftime("%d/%m/%Y") if nota.fecha_creacion else "",
                    _as_decimal(nota.monto),
                    _as_decimal(nota.saldo_disponible),
                )
                for nota in self._notas
            ]
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para ver notas de crédito.")
            filas = []
        except Exception:
            logger.exception("Fallo al cargar notas de credito de proveedor")
            MessageBox.critical(self, "Error", "No se pudieron cargar las notas de crédito.")
            filas = []
        finally:
            session.close()

        self.tabla.setRowCount(len(filas))
        total = Decimal("0")
        for fila, (id_nota, proveedor, compra, fecha, monto, disponible) in enumerate(filas):
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(id_nota)))
            self.tabla.setItem(fila, 1, QTableWidgetItem(proveedor))
            self.tabla.setItem(fila, 2, QTableWidgetItem(compra))
            self.tabla.setItem(fila, 3, QTableWidgetItem(fecha))
            for columna, valor in ((4, monto), (5, disponible)):
                item = QTableWidgetItem(f"${float(valor):,.2f}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.tabla.setItem(fila, columna, item)
            total += disponible
        self.lbl_total.setText(f"Total a favor: ${float(total):,.2f}")
        hay_notas = bool(filas)
        self.btn_aplicar.setEnabled(hay_notas)
        self.btn_reembolso.setEnabled(hay_notas)

    def _id_seleccionado(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            MessageBox.information(self, "Selección requerida", "Selecciona una nota de crédito de la lista.")
            return None
        return int(self.tabla.item(filas[0].row(), 0).text())

    def _abrir(self, clase_dialogo) -> None:
        id_nota = self._id_seleccionado()
        if id_nota is None:
            return
        session = self.session_factory()
        try:
            nota = session.get(NotaCreditoProveedor, id_nota)
            if nota is None or nota.estado != "disponible":
                MessageBox.information(self, "No disponible", "Esta nota de crédito ya no tiene saldo disponible.")
                self.cargar()
                return
            dialogo = clase_dialogo(session, self.id_usuario, nota, parent=self)
            if dialogo.exec():
                self.hubo_cambios = True
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para usar notas de crédito.")
        finally:
            session.close()
        self.cargar()

    def aplicar_seleccionada(self) -> None:
        self._abrir(AplicarNotaCreditoProveedorDialog)

    def reembolsar_seleccionada(self) -> None:
        self._abrir(ReembolsoNotaCreditoProveedorDialog)
