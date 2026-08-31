"""
Panel del modulo Comisiones: gestion de comisiones de vendedores (listar, pagar).
Dos modos en el mismo panel:
  - Modo gestion (comisiones:ver/crear): ADMIN/CAJERO elige un vendedor y paga comisiones.
  - Modo "Mis Comisiones" (reportes_comisiones:ver): VENDEDOR ve solo sus propias comisiones.
Mismo patron visual que app/ui/cuentas_por_pagar_panel.py.
"""

import logging
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
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from app.db.models import ComisionFactura, Usuario
from app.services.comisiones import ComisionService, PagoComisionService
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import BancoService, CajaService
from app.services.usuarios import UsuarioService
from app.services.vendedores import VendedorService
from app.ui.pago_linea_dialog import METODOS_PAGO, METODOS_QUE_REQUIEREN_CAJA
from app.ui.styles import (
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_FIELD_BG,
    COLOR_PRIMARY,
    COLOR_PRIMARY_DARK,
    COLOR_PRIMARY_LIGHT,
    COLOR_SUCCESS,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MUTED,
    FONT_FAMILY,
    ICON_CHEVRON_DOWN_URL,
    TABLE_QSS,
    EstadoBadge,
    aplicar_sombra,
)
from app.ui.toolbar_popups import BotonFiltros

logger = logging.getLogger(__name__)

COLORES_ESTADO_COMISION = {
    "pendiente": COLOR_PRIMARY,
    "pagada": COLOR_SUCCESS,
}

ESTADOS_FILTRO = [
    ("Todos los estados", None),
    ("Pendiente", "pendiente"),
    ("Pagada", "pagada"),
]

LIMITE_CATALOGO = 50

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
    color: #334155;
    margin-bottom: 2px;
}}
QLineEdit, QComboBox {{
    background-color: #FFFFFF;
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
    color: #FFFFFF;
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
QPushButton#BtnSecondary {{
    background-color: {COLOR_FIELD_BG};
    color: #475569;
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


class PagarComisionesDialog(QDialog):
    """Dialogo para pagar todas las comisiones pendientes de un vendedor en un batch."""

    def __init__(
        self,
        session: Session,
        id_usuario: int | None,
        id_vendedor: int,
        monto_pendiente: Decimal,
        nombre_vendedor: str,
        parent=None,
    ):
        super().__init__(parent)
        self.session = session
        self.id_usuario = id_usuario
        self.id_vendedor = id_vendedor
        self.monto_pendiente = monto_pendiente
        self.nombre_vendedor = nombre_vendedor
        self.pago_creado = None
        self._cajas_abiertas: list = []
        self._cuentas_activas: list = []

        self.setWindowTitle("Pagar Comisiones")
        self.setFixedSize(420, 380)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._build_ui()
        self._cargar_origenes()
        self._toggle_origen()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        lbl_titulo = QLabel(f"Pagar comisiones a {self.nombre_vendedor}")
        lbl_titulo.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        root.addWidget(lbl_titulo)

        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        lbl_monto = QLabel(f"Total pendiente: ${float(self.monto_pendiente):,.2f}")
        lbl_monto.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_MUTED};")
        layout.addWidget(lbl_monto)

        lbl_metodo = QLabel("Método de Pago <span style='color: #DC2626;'>*</span>")
        lbl_metodo.setProperty("class", "FormLabel")
        self.metodo_combo = QComboBox()
        for etiqueta, valor in METODOS_PAGO:
            self.metodo_combo.addItem(etiqueta, valor)
        self.metodo_combo.setFixedHeight(32)
        self.metodo_combo.currentIndexChanged.connect(self._toggle_origen)
        layout.addWidget(lbl_metodo)
        layout.addWidget(self.metodo_combo)

        lbl_origen = QLabel("Origen <span style='color: #DC2626;'>*</span>")
        lbl_origen.setProperty("class", "FormLabel")
        self.origen_combo = QComboBox()
        self.origen_combo.setFixedHeight(32)
        layout.addWidget(lbl_origen)
        layout.addWidget(self.origen_combo)

        lbl_ref = QLabel("Referencia")
        lbl_ref.setProperty("class", "FormLabel")
        self.referencia_input = QLineEdit()
        self.referencia_input.setPlaceholderText("Opcional")
        self.referencia_input.setFixedHeight(32)
        layout.addWidget(lbl_ref)
        layout.addWidget(self.referencia_input)

        root.addWidget(card, stretch=1)

        footer = QHBoxLayout()
        footer.addStretch()
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setObjectName("BtnSecondary")
        btn_cancelar.setFixedHeight(34)
        btn_cancelar.setAutoDefault(False)
        btn_cancelar.clicked.connect(self.reject)
        self.btn_pagar = QPushButton("Pagar")
        self.btn_pagar.setObjectName("BtnPrimary")
        self.btn_pagar.setFixedHeight(34)
        self.btn_pagar.setAutoDefault(False)
        self.btn_pagar.clicked.connect(self._validar_y_aceptar)
        footer.addWidget(btn_cancelar)
        footer.addWidget(self.btn_pagar)
        root.addLayout(footer)

    def _cargar_origenes(self) -> None:
        try:
            cajas = CajaService.listar_cajas(self.session, id_usuario=self.id_usuario)
        except PermisoDenegadoError:
            cajas = []
        self._cajas_abiertas = [c for c in cajas if c.fecha_apertura is not None and c.fecha_cierre is None]
        try:
            cuentas = BancoService.listar_cuentas(self.session, id_usuario=self.id_usuario)
        except PermisoDenegadoError:
            cuentas = []
        self._cuentas_activas = [c for c in cuentas if (c.estado_cuenta or "ACTIVO") == "ACTIVO"]

    def _toggle_origen(self) -> None:
        metodo = self.metodo_combo.currentData()
        requiere_caja = metodo in METODOS_QUE_REQUIEREN_CAJA
        self.origen_combo.blockSignals(True)
        self.origen_combo.clear()
        if requiere_caja:
            if not self._cajas_abiertas:
                self.origen_combo.addItem("Sin cajas abiertas", None)
                self.origen_combo.setEnabled(False)
            else:
                self.origen_combo.setEnabled(True)
                for caja in self._cajas_abiertas:
                    self.origen_combo.addItem(caja.nombre_caja or f"Caja {caja.id_caja}", ("caja", caja.id_caja))
        else:
            if not self._cuentas_activas:
                self.origen_combo.addItem("Sin cuentas bancarias activas", None)
                self.origen_combo.setEnabled(False)
            else:
                self.origen_combo.setEnabled(True)
                for cuenta in self._cuentas_activas:
                    nombre_banco = cuenta.banco.nombre_banco if cuenta.banco else "Banco"
                    self.origen_combo.addItem(
                        f"{nombre_banco} - ...{cuenta.numero_cuenta[-4:]}", ("banco", cuenta.id_cuenta)
                    )
        self.origen_combo.blockSignals(False)

    def _validar_y_aceptar(self) -> None:
        origen = self.origen_combo.currentData()
        if origen is None:
            QMessageBox.warning(self, "Origen requerido", "No hay ninguna caja/cuenta disponible para este método.")
            return
        tipo_origen, id_origen = origen

        respuesta = QMessageBox.question(
            self,
            "Confirmar pago",
            f"¿Confirma el pago de ${float(self.monto_pendiente):,.2f} a {self.nombre_vendedor}?\n"
            "Esta acción no se puede deshacer.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if respuesta != QMessageBox.StandardButton.Yes:
            return

        try:
            self.pago_creado = PagoComisionService.pagar_comisiones_vendedor(
                self.session,
                id_vendedor=self.id_vendedor,
                metodo_pago=self.metodo_combo.currentData(),
                id_caja=id_origen if tipo_origen == "caja" else None,
                id_cuenta_bancaria=id_origen if tipo_origen == "banco" else None,
                referencia=self.referencia_input.text().strip() or None,
                id_usuario=self.id_usuario,
            )
        except ValueError as exc:
            self.session.rollback()
            QMessageBox.warning(self, "No se pudo registrar el pago", str(exc))
            return
        except PermisoDenegadoError:
            self.session.rollback()
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para pagar comisiones.")
            return
        except Exception:
            self.session.rollback()
            logger.exception("Fallo al pagar comisiones")
            QMessageBox.critical(self, "Error", "No se pudo registrar el pago.")
            return

        self.accept()


class ComisionesPanel(QWidget):
    """Panel del modulo Comisiones: dos modos segun el permiso del usuario.
    - Modo gestion (comisiones:ver): selector de vendedor + tabla + pagar.
    - Modo "Mis Comisiones" (reportes_comisiones:ver): solo lectura de propias."""

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.setObjectName("ContentArea")

        session = session_factory()
        try:
            self.modo_gestion = UsuarioService.verificar_permiso(session, usuario.id_usuario, "comisiones", "ver")
        except Exception:
            self.modo_gestion = False
        finally:
            session.close()

        self.id_vendedor_actual: int | None = None
        self.comisiones_cargadas: list[ComisionFactura] = []

        self._setup_ui()
        QTimer.singleShot(100, self.cargar_datos)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.cargar_datos()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        root.addWidget(self._make_header())
        if self.modo_gestion:
            root.addWidget(self._make_toolbar())
        root.addWidget(self._make_table())
        if self.modo_gestion:
            root.addWidget(self._make_footer())

        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

    def _make_header(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        titulo = "Comisiones" if self.modo_gestion else "Mis Comisiones"
        lbl = QLabel(titulo)
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
        w.setStyleSheet(
            f"background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 8px; padding: 4px;"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)

        lbl_vendedor = QLabel("Vendedor:")
        lbl_vendedor.setStyleSheet(f"color: {COLOR_TEXT_DARK}; font-weight: 600;")
        self.vendedor_combo = QComboBox()
        self.vendedor_combo.setFixedWidth(250)
        self.vendedor_combo.currentIndexChanged.connect(self._on_vendedor_cambiado)

        self.estado_combo = QComboBox()
        for etiqueta, valor in ESTADOS_FILTRO:
            self.estado_combo.addItem(etiqueta, valor)
        self.estado_combo.currentIndexChanged.connect(self._aplicar_filtro_estado)
        self.btn_filtrar = BotonFiltros([("Estado", self.estado_combo)])

        h.addWidget(lbl_vendedor)
        h.addWidget(self.vendedor_combo)
        h.addStretch()
        h.addWidget(self.btn_filtrar)
        return w

    def _make_table(self) -> QTableWidget:
        self.tabla = QTableWidget(0, 7)
        self.tabla.setHorizontalHeaderLabels(
            ["ID", "Factura", "Fecha Cálculo", "Monto Base", "Monto Venta", "Comisión", "Estado"]
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
        self.tabla.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.tabla.setColumnWidth(6, 110)
        self.tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(self.tabla)
        self.tabla.setColumnHidden(0, True)
        self.tabla.verticalHeader().setDefaultSectionSize(45)
        return self.tabla

    def _make_footer(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        h.addStretch()
        self.btn_pagar = QPushButton("Pagar Comisiones")
        self.btn_pagar.setIcon(qta.icon("fa5s.money-bill-wave", color=COLOR_TEXT_DARK))
        self.btn_pagar.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_pagar.clicked.connect(self.pagar_comisiones)
        self.btn_pagar.setEnabled(False)
        h.addWidget(self.btn_pagar)
        return w

    def cargar_datos(self) -> None:
        session = self.session_factory()
        try:
            if self.modo_gestion:
                self._cargar_vendedores(session)
            else:
                self._cargar_comisiones_propias(session)
        except PermisoDenegadoError:
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar comisiones.")
        except ValueError as exc:
            QMessageBox.warning(self, "Error", str(exc))
        except Exception:
            logger.exception("Fallo al cargar comisiones")
            QMessageBox.critical(self, "Error de conexión", "No se pudo cargar las comisiones.")
        finally:
            session.close()

    def _cargar_vendedores(self, session: Session) -> None:
        resultado = VendedorService.listar(
            session, id_usuario=self.usuario.id_usuario, estado_vendedor="ACTIVO", por_pagina=LIMITE_CATALOGO
        )
        vendedores = resultado["items"]
        self.vendedor_combo.blockSignals(True)
        self.vendedor_combo.clear()
        if not vendedores:
            self.vendedor_combo.addItem("Sin vendedores activos", None)
        for vendedor in vendedores:
            self.vendedor_combo.addItem(
                vendedor.nombre_vendedor or f"Vendedor {vendedor.id_vendedor}", vendedor.id_vendedor
            )
        self.vendedor_combo.blockSignals(False)
        if vendedores:
            self.vendedor_combo.setCurrentIndex(0)
            self._on_vendedor_cambiado()

    def _cargar_comisiones_propias(self, session: Session) -> None:
        try:
            comisiones = ComisionService.listar_mis_comisiones(session, self.usuario.id_usuario)
            self.comisiones_cargadas = comisiones
            self._poblar_tabla(comisiones)
        except ValueError:
            self.tabla.setRowCount(0)
            self.lbl_total.setText("Sin datos")
            raise

    def _on_vendedor_cambiado(self) -> None:
        self.id_vendedor_actual = self.vendedor_combo.currentData()
        if self.id_vendedor_actual is not None:
            session = self.session_factory()
            try:
                comisiones = ComisionService.listar_comisiones_vendedor(
                    session, self.id_vendedor_actual, id_usuario=self.usuario.id_usuario
                )
                self.comisiones_cargadas = comisiones
                self._aplicar_filtro_estado()
            except Exception:
                logger.exception("Fallo al cargar comisiones del vendedor")
                self.tabla.setRowCount(0)
            finally:
                session.close()

    def _aplicar_filtro_estado(self) -> None:
        estado_filtro = self.estado_combo.currentData()
        if estado_filtro:
            filtradas = [c for c in self.comisiones_cargadas if c.estado_pago == estado_filtro]
        else:
            filtradas = self.comisiones_cargadas
        self._poblar_tabla(filtradas)

    def _poblar_tabla(self, comisiones: list[ComisionFactura]) -> None:
        self.tabla.setRowCount(len(comisiones))
        total_pendiente = Decimal("0.00")

        for fila, comision in enumerate(comisiones):
            factura_num = ""
            try:
                if comision.detalle and comision.detalle.factura:
                    factura_num = comision.detalle.factura.numero_factura or ""
            except Exception:
                pass

            self.tabla.setItem(fila, 0, QTableWidgetItem(str(comision.id_comision)))
            self.tabla.setItem(fila, 1, QTableWidgetItem(factura_num))
            fecha_str = comision.fecha_calculo.strftime("%d/%m/%Y") if comision.fecha_calculo else ""
            self.tabla.setItem(fila, 2, QTableWidgetItem(fecha_str))
            self.tabla.setItem(fila, 3, QTableWidgetItem(f"${float(comision.monto_base_comision or 0):,.2f}"))
            self.tabla.setItem(fila, 4, QTableWidgetItem(f"${float(comision.monto_venta_comision or 0):,.2f}"))
            self.tabla.setItem(fila, 5, QTableWidgetItem(f"${float(comision.monto_comision):,.2f}"))

            estado = comision.estado_pago or "pendiente"
            color = COLORES_ESTADO_COMISION.get(estado, COLOR_TEXT_MUTED)
            self.tabla.setCellWidget(fila, 6, EstadoBadge(estado.capitalize(), color))

            if estado == "pendiente":
                total_pendiente += comision.monto_comision

        self.lbl_total.setText(f"Pendiente: ${float(total_pendiente):,.2f}")
        if self.modo_gestion:
            self.btn_pagar.setEnabled(self.id_vendedor_actual is not None and total_pendiente > 0)

    def pagar_comisiones(self) -> None:
        if self.id_vendedor_actual is None:
            QMessageBox.information(self, "Selección requerida", "Selecciona un vendedor.")
            return

        total_pendiente = sum(
            (c.monto_comision for c in self.comisiones_cargadas if c.estado_pago == "pendiente"),
            Decimal("0.00"),
        )
        if total_pendiente <= 0:
            QMessageBox.information(self, "Sin comisiones", "No hay comisiones pendientes para este vendedor.")
            return

        nombre_vendedor = self.vendedor_combo.currentText()
        session = self.session_factory()
        try:
            dialogo = PagarComisionesDialog(
                session, self.usuario.id_usuario, self.id_vendedor_actual, total_pendiente, nombre_vendedor, parent=self
            )
            if dialogo.exec() and dialogo.pago_creado is not None:
                self._on_vendedor_cambiado()
                QMessageBox.information(self, "Pago registrado", "El pago se registró con éxito.")
        except Exception:
            logger.exception("Fallo al abrir dialogo de pago")
        finally:
            session.close()
