"""
Panel del modulo Cuentas por Cobrar BCV: analogo a cuentas_por_cobrar_panel.py,
pero para las cuentas con precios incrementados por porcentaje BCV.
"""

import logging
from datetime import date
from decimal import Decimal

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
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import joinedload

from app.db.models import CuentaPorCobrarBCV, Usuario
from app.services.db_utils import reintentar_en_deadlock
from app.services.exportacion import exportar_excel, exportar_pdf
from app.services.pagos_bcv import PagoBCVService
from app.services.permisos import PermisoDenegadoError
from app.services.tasas import TasaService
from app.services.tesoreria import BancoService, CajaService
from app.ui.message_box import MessageBox
from app.ui.numeric_inputs import NumericFieldType, NumericLineEdit, _as_decimal
from app.ui.pago_linea_dialog import METODOS_PAGO, METODOS_QUE_REQUIEREN_CAJA
from app.ui.styles import (
    ASTERISCO_REQUERIDO,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_FIELD_BG,
    COLOR_PRIMARY,
    COLOR_PRIMARY_DARK,
    COLOR_PRIMARY_LIGHT,
    COLOR_SUCCESS,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_DARK_SLATE,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MEDIUM,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
    COLOR_WHITE,
    FONT_FAMILY,
    ICON_CHEVRON_DOWN_URL,
    SEARCH_QSS,
    TABLE_QSS,
    EstadoBadge,
    alinear_encabezados,
    aplicar_sombra,
)
from app.ui.toolbar_popups import BotonExportar, BotonFiltros

logger = logging.getLogger(__name__)

POR_PAGINA = 20

COLORES_ESTADO_CXC_BCV = {
    "pendiente": COLOR_WARNING,
    "parcial": COLOR_PRIMARY,
    "pagada": COLOR_SUCCESS,
    "vencida": COLOR_DANGER,
}

ESTADOS_FILTRO = [
    ("Todos los estados", None),
    ("Pendiente", "pendiente"),
    ("Parcial", "parcial"),
    ("Vencida", "vencida"),
    ("Pagada", "pagada"),
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


class PagoCobroBCVDialog(QDialog):
    """Un unico pago en USD contra el saldo_pendiente de una CuentaPorCobrarBCV."""

    def __init__(
        self,
        session_factory,
        id_usuario: int | None,
        cuenta: CuentaPorCobrarBCV,
        tasa_bcv: float | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.session_factory = session_factory
        self.id_usuario = id_usuario
        self.cuenta = cuenta
        self.tasa_bcv = tasa_bcv
        self.pago_creado = None
        self._cajas_abiertas: list = []
        self._cuentas_activas: list = []
        self._tasas_disponibles: list = []
        self._id_tasa_seleccionada: int | None = None

        self.setWindowTitle("Registrar Cobro BCV")
        self.setFixedSize(420, 550)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._build_ui()
        self._cargar_origenes()
        self._cargar_tasas()
        self._toggle_origen()
        self._toggle_campos_bolivares()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        cliente = self.cuenta.factura.cliente if self.cuenta.factura else None
        lbl_titulo = QLabel(f"Cobrar BCV a {cliente.nombre_razon_social if cliente else 'cliente'}")
        lbl_titulo.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        root.addWidget(lbl_titulo)

        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        numero_factura = self.cuenta.factura.numero_factura if self.cuenta.factura else ""
        porcentaje = f"{float(self.cuenta.porcentaje):.2f}%" if self.cuenta.porcentaje else "N/A"
        total_factura = self.cuenta.factura.total_venta if self.cuenta.factura else Decimal("0.00")
        total_text = f"Factura: {numero_factura} | Porcentaje BCV: {porcentaje} | Total: ${float(total_factura):,.2f}"
        lbl_factura = QLabel(total_text)
        lbl_factura.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        layout.addWidget(lbl_factura)

        saldo_pendiente = _as_decimal(self.cuenta.saldo_pendiente)
        texto_saldo = f"Saldo pendiente BCV: ${float(saldo_pendiente):,.2f}"
        if self.tasa_bcv:
            tasa_decimal = Decimal(str(self.tasa_bcv)) if not isinstance(self.tasa_bcv, Decimal) else self.tasa_bcv
            monto_bs = saldo_pendiente * tasa_decimal
            texto_saldo += f"  (Bs {float(monto_bs):,.2f})"
        lbl_saldo = QLabel(texto_saldo)
        lbl_saldo.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_MUTED};")
        layout.addWidget(lbl_saldo)

        lbl_metodo = QLabel(f"Método de Pago {ASTERISCO_REQUERIDO}")
        lbl_metodo.setProperty("class", "FormLabel")
        self.metodo_combo = QComboBox()
        for etiqueta, valor in METODOS_PAGO:
            self.metodo_combo.addItem(etiqueta, valor)
        self.metodo_combo.setFixedHeight(32)
        self.metodo_combo.currentIndexChanged.connect(self._on_metodo_cambiado)
        layout.addWidget(lbl_metodo)
        layout.addWidget(self.metodo_combo)

        lbl_monto = QLabel(f"Monto (USD) {ASTERISCO_REQUERIDO}")
        lbl_monto.setProperty("class", "FormLabel")
        self.monto_input = NumericLineEdit(NumericFieldType.AMOUNT, min_value=Decimal("0.01"), prefix="$ ")
        self.monto_input.set_value(saldo_pendiente)
        self.monto_input.setFixedHeight(32)
        self.monto_input.valueChanged.connect(self._calcular_bolivares_desde_usd)
        layout.addWidget(lbl_monto)
        layout.addWidget(self.monto_input)

        # Campos para cálculo en bolivares (visible para todos los pagos bancarios)
        self.campos_bolivares_widget = QWidget()
        self.campos_bolivares_widget.setVisible(False)
        campos_bolivares_layout = QVBoxLayout(self.campos_bolivares_widget)
        campos_bolivares_layout.setContentsMargins(0, 0, 0, 0)
        campos_bolivares_layout.setSpacing(8)

        fila_bolivares = QHBoxLayout()
        fila_bolivares.setSpacing(8)

        col_bolivares = QVBoxLayout()
        lbl_bolivares = QLabel("Monto (Bs)")
        lbl_bolivares.setProperty("class", "FormLabel")
        self.bolivares_input = NumericLineEdit(NumericFieldType.AMOUNT, max_value=Decimal("999999999999"))
        self.bolivares_input.setFixedHeight(32)
        self.bolivares_input.valueChanged.connect(self._calcular_monto_usd)
        col_bolivares.addWidget(lbl_bolivares)
        col_bolivares.addWidget(self.bolivares_input)

        col_tasa = QVBoxLayout()
        lbl_tasa = QLabel("Tasa del día (Bs/USD)")
        lbl_tasa.setProperty("class", "FormLabel")
        self.tasa_input = NumericLineEdit(NumericFieldType.RATE)
        self.tasa_input.setFixedHeight(32)
        self.tasa_input.valueChanged.connect(self._calcular_monto_usd)
        col_tasa.addWidget(lbl_tasa)
        col_tasa.addWidget(self.tasa_input)

        fila_bolivares.addLayout(col_bolivares, stretch=1)
        fila_bolivares.addLayout(col_tasa, stretch=1)
        campos_bolivares_layout.addLayout(fila_bolivares)

        # Selector de tasas disponibles
        fila_tasa_selector = QHBoxLayout()
        fila_tasa_selector.setSpacing(8)
        lbl_usar_tasa = QLabel("Usar tasa:")
        lbl_usar_tasa.setStyleSheet("font-size: 12px; color: #64748B;")
        self.tasa_combo = QComboBox()
        self.tasa_combo.setFixedHeight(32)
        self.tasa_combo.addItem("-- Seleccionar --")
        self.tasa_combo.currentIndexChanged.connect(self._on_tasa_seleccionada)
        fila_tasa_selector.addWidget(lbl_usar_tasa)
        fila_tasa_selector.addWidget(self.tasa_combo)
        fila_tasa_selector.addStretch()
        campos_bolivares_layout.addLayout(fila_tasa_selector)

        layout.addWidget(self.campos_bolivares_widget)

        lbl_origen = QLabel(f"Origen {ASTERISCO_REQUERIDO}")
        lbl_origen.setProperty("class", "FormLabel")
        self.origen_combo = QComboBox()
        self.origen_combo.setFixedHeight(32)
        self.origen_combo.currentIndexChanged.connect(self._toggle_campos_bolivares)
        layout.addWidget(lbl_origen)
        layout.addWidget(self.origen_combo)

        lbl_ref = QLabel("Referencia")
        lbl_ref.setProperty("class", "FormLabel")
        self.referencia_input = QLineEdit()
        self.referencia_input.setPlaceholderText("Opcional")
        self.referencia_input.setFixedHeight(32)
        self.referencia_input.setMaxLength(100)
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
        self.btn_cobrar = QPushButton("Registrar Cobro BCV")
        self.btn_cobrar.setObjectName("BtnPrimary")
        self.btn_cobrar.setFixedHeight(34)
        self.btn_cobrar.setAutoDefault(False)
        self.btn_cobrar.clicked.connect(self._validar_y_aceptar)
        footer.addWidget(btn_cancelar)
        footer.addWidget(self.btn_cobrar)
        root.addLayout(footer)

    def _cargar_origenes(self) -> None:
        try:
            session = self.session_factory()
            try:
                cajas = CajaService.listar_cajas(session, id_usuario=self.id_usuario)
            finally:
                session.close()
        except PermisoDenegadoError:
            cajas = []
        self._cajas_abiertas = [c for c in cajas if c.fecha_apertura is not None and c.fecha_cierre is None]
        try:
            session = self.session_factory()
            try:
                cuentas = BancoService.listar_cuentas(session, id_usuario=self.id_usuario)
            finally:
                session.close()
        except PermisoDenegadoError:
            cuentas = []
        self._cuentas_activas = [c for c in cuentas if (c.estado_cuenta or "ACTIVO") == "ACTIVO"]

    def _cargar_tasas(self) -> None:
        """Carga las tasas actuales (BCV, paralelo y COP) en el combo."""
        try:
            session = self.session_factory()
            try:
                from app.db.models import ControlDeTasa

                # Obtener la tasa más reciente
                tasa_registro = (
                    session.query(ControlDeTasa)
                    .order_by(ControlDeTasa.fecha_tasa.desc(), ControlDeTasa.id_tasa.desc())
                    .first()
                )
            finally:
                session.close()
        except Exception:
            tasa_registro = None

        self.tasa_combo.blockSignals(True)
        self.tasa_combo.clear()
        self.tasa_combo.addItem("-- Seleccionar --")

        if tasa_registro:
            # Agregar tasa BCV
            if tasa_registro.tasa_dolar_bcv:
                tasa_bcv = _as_decimal(tasa_registro.tasa_dolar_bcv)
                etiqueta_bcv = f"BCV: {float(tasa_bcv):,.2f}"
                self.tasa_combo.addItem(etiqueta_bcv, (tasa_registro.id_tasa, float(tasa_bcv)))
            # Agregar tasa paralelo
            if tasa_registro.tasa_dolar_paralelo:
                tasa_paralelo = _as_decimal(tasa_registro.tasa_dolar_paralelo)
                etiqueta_paralelo = f"Paralelo: {float(tasa_paralelo):,.2f}"
                self.tasa_combo.addItem(
                    etiqueta_paralelo,
                    (tasa_registro.id_tasa, float(tasa_paralelo)),
                )
            # Agregar tasa COP
            if tasa_registro.tasa_cop:
                tasa_cop = _as_decimal(tasa_registro.tasa_cop)
                etiqueta_cop = f"COP: {float(tasa_cop):,.2f}"
                self.tasa_combo.addItem(etiqueta_cop, (tasa_registro.id_tasa, float(tasa_cop)))

        self.tasa_combo.blockSignals(False)

        # Pre-seleccionar la tasa BCV si está disponible
        if self.tasa_bcv:
            self.tasa_input.set_value(self.tasa_bcv)

    def _on_metodo_cambiado(self) -> None:
        self._toggle_origen()
        self._toggle_campos_bolivares()

    def _toggle_origen(self) -> None:
        metodo = self.metodo_combo.currentData()
        requiere_caja = metodo in METODOS_QUE_REQUIEREN_CAJA
        self.origen_combo.blockSignals(True)
        self.origen_combo.clear()
        if requiere_caja:
            if not self._cajas_abiertas:
                self.origen_combo.addItem("Sin cajas abiertas")
                self.origen_combo.setEnabled(False)
            else:
                self.origen_combo.setEnabled(True)
                for caja in self._cajas_abiertas:
                    self.origen_combo.addItem(
                        caja.nombre_caja or f"Caja {caja.id_caja}",
                        ("caja", caja.id_caja),
                    )
        else:
            if not self._cuentas_activas:
                self.origen_combo.addItem("Sin cuentas bancarias activas")
                self.origen_combo.setEnabled(False)
            else:
                self.origen_combo.setEnabled(True)
                for cuenta in self._cuentas_activas:
                    nombre_banco = cuenta.banco.nombre_banco if cuenta.banco else "Banco"
                    self.origen_combo.addItem(
                        f"{nombre_banco} - ...{cuenta.numero_cuenta[-4:]}",
                        ("banco", cuenta.id_cuenta),
                    )
        self.origen_combo.blockSignals(False)
        # Actualizar campos de bolivares cuando cambia el origen
        self._toggle_campos_bolivares()

    def _toggle_campos_bolivares(self) -> None:
        """Muestra/oculta los campos de bolivares según el método de pago y origen."""
        metodo = self.metodo_combo.currentData()
        origen = self.origen_combo.currentData()

        # Mostrar campos de bolivares para todos los métodos bancarios (no efectivo)
        # Esto incluye: transferencia, zelle, binance, punto_de_venta
        es_banco = origen is not None and origen[0] == "banco"
        es_efectivo = metodo == "efectivo"

        mostrar_bolivares = es_banco and not es_efectivo
        self.campos_bolivares_widget.setVisible(bool(mostrar_bolivares))

        if mostrar_bolivares:
            # Habilitar cálculo automático
            self.monto_input.setReadOnly(True)
            self.monto_input.setStyleSheet("background-color: #F1F5F9;")
            # Si no hay tasa seleccionada, seleccionar automáticamente la primera disponible (BCV)
            if self._id_tasa_seleccionada is None and self.tasa_combo.count() > 1:
                self.tasa_combo.setCurrentIndex(1)  # El índice 0 es "-- Seleccionar --"
        else:
            # Restaurar campo de monto manual
            self.monto_input.setReadOnly(False)
            self.monto_input.setStyleSheet("")

    def _on_tasa_seleccionada(self) -> None:
        """Carga la tasa seleccionada del combo al campo de tasa y calcula bolivares."""
        tasa_data = self.tasa_combo.currentData()
        if tasa_data is not None:
            id_tasa, valor_tasa = tasa_data
            self._id_tasa_seleccionada = id_tasa
            self.tasa_input.set_value(valor_tasa)
            # Calcular automáticamente el monto en bolivares
            monto_usd = self.monto_input.get_value() or Decimal("0")
            if valor_tasa > 0 and monto_usd > 0:
                bolivares = monto_usd * Decimal(str(valor_tasa))
                self.bolivares_input.set_value(bolivares)
            self._calcular_monto_usd()

    def _calcular_monto_usd(self) -> None:
        """Calcula el monto USD automáticamente: bolivares / tasa."""
        metodo = self.metodo_combo.currentData()
        origen = self.origen_combo.currentData()
        # Solo calcular para métodos bancarios (no efectivo)
        if metodo == "efectivo" or not origen or origen[0] != "banco":
            return

        bolivares = self.bolivares_input.get_value() or Decimal("0")
        tasa = self.tasa_input.get_value() or Decimal("0")

        if tasa > 0:
            monto_usd = bolivares / tasa
            self.monto_input.set_value(monto_usd)
            # set_value() reformatea con el estilo base del widget -- reaplicar el
            # resaltado de solo-lectura para que no desaparezca en cada recalculo
            # mientras el metodo de pago siga siendo bancario.
            if self.monto_input.isReadOnly():
                self.monto_input.setStyleSheet("background-color: #F1F5F9;")

    def _calcular_bolivares_desde_usd(self) -> None:
        """Calcula el monto en bolivares automáticamente: USD * tasa."""
        metodo = self.metodo_combo.currentData()
        origen = self.origen_combo.currentData()
        # Solo calcular para métodos bancarios (no efectivo)
        if metodo == "efectivo" or not origen or origen[0] != "banco":
            return

        monto_usd = self.monto_input.get_value() or Decimal("0")
        tasa = self.tasa_input.get_value() or Decimal("0")

        if tasa > 0 and monto_usd > 0:
            bolivares = monto_usd * tasa
            self.bolivares_input.set_value(bolivares)

    def _validar_y_aceptar(self) -> None:
        origen = self.origen_combo.currentData()
        if origen is None:
            MessageBox.warning(self, "Campo requerido", "Seleccione el origen del pago.")
            return

        monto = self.monto_input.get_value()
        if monto is None or monto <= 0:
            MessageBox.warning(self, "Monto inválido", "El monto debe ser mayor a cero.")
            return

        tipo_origen, id_origen = origen
        id_cuenta_bancaria = id_origen if tipo_origen == "banco" else None
        id_caja = id_origen if tipo_origen == "caja" else None

        metodo_pago = self.metodo_combo.currentData()
        referencia = self.referencia_input.text().strip() or None

        # Variables para guardar datos de conversión
        monto_moneda_origen = None
        monto_bolivares = None
        tasa_cambio = None
        id_tasa = None

        # Si es pago bancario (no efectivo), guardar bolivares y tasa seleccionada
        # Esto incluye: transferencia, zelle, binance, punto_de_venta
        if metodo_pago != "efectivo" and tipo_origen == "banco":
            bolivares = self.bolivares_input.get_value() or Decimal("0")
            tasa = self.tasa_input.get_value() or Decimal("0")

            # Si no hay tasa manual, usar la tasa seleccionada del combo
            if tasa == 0 and self._id_tasa_seleccionada:
                tasa_data = self.tasa_combo.currentData()
                if tasa_data:
                    _, valor_tasa = tasa_data
                    tasa = Decimal(str(valor_tasa))

            # Calcular bolivares si no se ingresaron pero hay tasa
            if bolivares == 0 and tasa > 0:
                bolivares = (self.monto_input.get_value() or Decimal("0")) * tasa

            # Siempre guardar los valores para pagos bancarios
            # Esto asegura que el trigger tenga los datos para crear el movimiento bancario
            if bolivares > 0:
                monto_moneda_origen = bolivares
                monto_bolivares = bolivares
            if tasa > 0:
                tasa_cambio = tasa
            # Siempre guardar el ID de la tasa si está seleccionada
            id_tasa = self._id_tasa_seleccionada

        try:
            session = self.session_factory()
            try:
                reintentar_en_deadlock(
                    lambda: PagoBCVService.registrar_pago_cobro_bcv(
                        session=session,
                        id_cuenta_por_cobrar=self.cuenta.id_cuenta_por_cobrar,
                        monto=monto,
                        metodo_pago=metodo_pago,
                        moneda="USD",
                        monto_moneda_origen=monto_moneda_origen,
                        monto_bolivares=monto_bolivares,
                        tasa_cambio=tasa_cambio,
                        id_cuenta_bancaria=id_cuenta_bancaria,
                        id_caja=id_caja,
                        id_tasa=id_tasa,
                        referencia=referencia,
                        id_usuario=self.id_usuario,
                    )
                )
                self.pago_creado = True
                MessageBox.information(self, "Éxito", "Cobro BCV registrado correctamente.")
                self.accept()
            finally:
                session.close()
        except ValueError as e:
            MessageBox.warning(self, "Error", str(e))
        except Exception as e:
            logger.exception("Error al registrar cobro BCV")
            MessageBox.critical(self, "Error", f"No se pudo registrar el cobro: {str(e)}")


class SeleccionarCuentaBCVDialog(QDialog):
    """Diálogo para seleccionar una cuenta individual de un cliente."""

    def __init__(self, cuentas: list, tasa_bcv: float | None = None, parent=None):
        super().__init__(parent)
        self.cuentas = cuentas
        self.tasa_bcv = tasa_bcv
        self.cuenta_seleccionada = None

        self.setWindowTitle("Seleccionar Cuenta BCV")
        self.setFixedSize(700, 500)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        lbl_titulo = QLabel("Seleccione una cuenta para cobrar")
        lbl_titulo.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        root.addWidget(lbl_titulo)

        # Tabla de cuentas
        self.tabla = QTableWidget(0, 6)
        headers = [
            "Factura",
            "Porcentaje BCV",
            "Saldo Pendiente",
            "Saldo a Favor",
            "Días",
            "Fecha Emisión",
        ]
        self.tabla.setHorizontalHeaderLabels(headers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setShowGrid(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.setStyleSheet(TABLE_QSS)
        self.tabla.verticalHeader().setDefaultSectionSize(40)

        for cuenta in self.cuentas:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)

            factura = cuenta.factura

            # Factura
            self.tabla.setItem(fila, 0, QTableWidgetItem(factura.numero_factura if factura else "N/A"))

            # Porcentaje BCV
            porcentaje_text = f"{float(cuenta.porcentaje):.2f}%" if cuenta.porcentaje else "N/A"
            self.tabla.setItem(fila, 1, QTableWidgetItem(porcentaje_text))

            # Saldo Pendiente
            saldo = _as_decimal(cuenta.saldo_pendiente)
            saldo_text = f"${float(saldo):,.2f}"
            if self.tasa_bcv:
                tasa_bcv = float(self.tasa_bcv) if not isinstance(self.tasa_bcv, float) else self.tasa_bcv
                saldo_text = f"${float(saldo):,.2f} / Bs {float(saldo * Decimal(str(tasa_bcv))):,.2f}"
            self.tabla.setItem(fila, 2, QTableWidgetItem(saldo_text))

            # Saldo a Favor
            saldo_favor = _as_decimal(cuenta.saldo_favor) if cuenta.saldo_favor else Decimal("0.00")
            saldo_favor_text = f"${float(saldo_favor):,.2f}"
            if self.tasa_bcv:
                tasa_bcv = float(self.tasa_bcv) if not isinstance(self.tasa_bcv, float) else self.tasa_bcv
                saldo_favor_text = f"${float(saldo_favor):,.2f} / Bs {float(saldo_favor * Decimal(str(tasa_bcv))):,.2f}"
            self.tabla.setItem(fila, 3, QTableWidgetItem(saldo_favor_text))

            # Días de crédito
            dias_text = str(cuenta.dias_credito) if cuenta.dias_credito is not None else "N/A"
            self.tabla.setItem(fila, 4, QTableWidgetItem(dias_text))

            # Fecha de Emisión
            fecha_emision_text = cuenta.fecha_emision.strftime("%d/%m/%Y") if cuenta.fecha_emision else "N/A"
            self.tabla.setItem(fila, 5, QTableWidgetItem(fecha_emision_text))

        root.addWidget(self.tabla, stretch=1)

        footer = QHBoxLayout()
        footer.addStretch()
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setObjectName("BtnSecondary")
        btn_cancelar.setFixedHeight(34)
        btn_cancelar.setAutoDefault(False)
        btn_cancelar.clicked.connect(self.reject)
        btn_seleccionar = QPushButton("Seleccionar")
        btn_seleccionar.setObjectName("BtnPrimary")
        btn_seleccionar.setFixedHeight(34)
        btn_seleccionar.setAutoDefault(False)
        btn_seleccionar.clicked.connect(self._seleccionar)
        footer.addWidget(btn_cancelar)
        footer.addWidget(btn_seleccionar)
        root.addLayout(footer)

    def _seleccionar(self) -> None:
        fila_actual = self.tabla.currentRow()
        if fila_actual < 0 or fila_actual >= len(self.cuentas):
            MessageBox.warning(self, "Selección requerida", "Seleccione una cuenta de la lista.")
            return

        self.cuenta_seleccionada = self.cuentas[fila_actual]
        self.accept()


class AbonoGeneralBCVDialog(QDialog):
    """Diálogo para aplicar un abono general a un cliente usando el método FIFO para cuentas BCV."""

    def __init__(
        self,
        session_factory,
        cliente,
        id_usuario: int | None,
        tasa_bcv: float | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.session_factory = session_factory
        self.cliente = cliente
        self.id_usuario = id_usuario
        self.tasa_bcv = tasa_bcv
        self.abono_aplicado = None
        self._cajas_abiertas: list = []
        self._cuentas_activas: list = []
        self._id_tasa_seleccionada: int | None = None

        self.setWindowTitle("Abono General BCV")
        self.setFixedSize(450, 500)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._build_ui()
        self._cargar_origenes()
        self._cargar_tasas()
        self._toggle_origen()
        self._toggle_campos_bolivares()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        lbl_titulo = QLabel(f"Abono General BCV - {self.cliente.nombre_razon_social if self.cliente else 'Cliente'}")
        lbl_titulo.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        root.addWidget(lbl_titulo)

        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        # Calcular deuda total del cliente BCV
        try:
            session = self.session_factory()
            try:
                resultado = PagoBCVService.listar_cuentas_por_cobrar_bcv(
                    session,
                    id_cliente=self.cliente.id_cliente if self.cliente else None,
                    id_usuario=self.id_usuario,
                )
                deuda_total = sum(cuenta.saldo_pendiente for cuenta in resultado["items"])
            finally:
                session.close()
        except Exception:
            deuda_total = Decimal("0.00")

        lbl_deuda = QLabel(f"Deuda total BCV: ${float(deuda_total):,.2f}")
        if self.tasa_bcv:
            tasa_bcv = float(self.tasa_bcv) if not isinstance(self.tasa_bcv, float) else self.tasa_bcv
            lbl_deuda.setText(
                f"Deuda total BCV: ${float(deuda_total):,.2f} (Bs {float(deuda_total * Decimal(str(tasa_bcv))):,.2f})"
            )
        lbl_deuda.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_MUTED};")
        layout.addWidget(lbl_deuda)

        # Calcular saldo a favor del cliente (desde la primera cuenta BCV del cliente)
        saldo_favor = Decimal("0.00")
        if self.cliente:
            try:
                session = self.session_factory()
                try:
                    from app.db.models import CuentaPorCobrarBCV, FacturaVenta

                    primera_cuenta = (
                        session.query(CuentaPorCobrarBCV)
                        .join(
                            FacturaVenta,
                            FacturaVenta.id_factura == CuentaPorCobrarBCV.id_factura,
                        )
                        .filter(FacturaVenta.id_cliente_factura == self.cliente.id_cliente)
                        .first()
                    )
                    if primera_cuenta:
                        saldo_favor = primera_cuenta.saldo_favor if primera_cuenta.saldo_favor else Decimal("0.00")
                        if saldo_favor is None:
                            saldo_favor = Decimal("0.00")
                finally:
                    session.close()
            except Exception as e:
                logger.warning(f"Error al obtener saldo a favor BCV: {e}")
                saldo_favor = Decimal("0.00")

        if saldo_favor > 0:
            lbl_saldo_favor = QLabel(f"Saldo a favor: ${float(saldo_favor):,.2f}")
            lbl_saldo_favor.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_SUCCESS};")
            layout.addWidget(lbl_saldo_favor)

        lbl_info = QLabel("El abono se aplicará automáticamente a las facturas más antiguas (FIFO)")
        lbl_info.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_MUTED}; font-style: italic;")
        layout.addWidget(lbl_info)

        lbl_metodo = QLabel(f"Método de Pago {ASTERISCO_REQUERIDO}")
        lbl_metodo.setProperty("class", "FormLabel")
        self.metodo_combo = QComboBox()
        for etiqueta, valor in METODOS_PAGO:
            self.metodo_combo.addItem(etiqueta, valor)
        self.metodo_combo.setFixedHeight(32)
        self.metodo_combo.currentIndexChanged.connect(self._on_metodo_cambiado)
        layout.addWidget(lbl_metodo)
        layout.addWidget(self.metodo_combo)

        lbl_monto = QLabel(f"Monto del Abono (USD) {ASTERISCO_REQUERIDO}")
        lbl_monto.setProperty("class", "FormLabel")
        self.monto_input = NumericLineEdit(NumericFieldType.AMOUNT, min_value=Decimal("0.01"), prefix="$ ")
        self.monto_input.set_value(deuda_total)  # Sugerir deuda total
        self.monto_input.setFixedHeight(32)
        self.monto_input.valueChanged.connect(self._calcular_bolivares_desde_usd)
        layout.addWidget(lbl_monto)
        layout.addWidget(self.monto_input)

        # Campos para cálculo en bolivares
        self.campos_bolivares_widget = QWidget()
        self.campos_bolivares_widget.setVisible(False)
        campos_bolivares_layout = QVBoxLayout(self.campos_bolivares_widget)
        campos_bolivares_layout.setContentsMargins(0, 0, 0, 0)
        campos_bolivares_layout.setSpacing(8)

        fila_bolivares = QHBoxLayout()
        fila_bolivares.setSpacing(8)

        col_bolivares = QVBoxLayout()
        lbl_bolivares = QLabel("Monto (Bs)")
        lbl_bolivares.setProperty("class", "FormLabel")
        self.bolivares_input = NumericLineEdit(NumericFieldType.AMOUNT, max_value=Decimal("999999999999"))
        self.bolivares_input.setFixedHeight(32)
        self.bolivares_input.valueChanged.connect(self._calcular_monto_usd)
        col_bolivares.addWidget(lbl_bolivares)
        col_bolivares.addWidget(self.bolivares_input)

        col_tasa = QVBoxLayout()
        lbl_tasa = QLabel("Tasa del día (Bs/USD)")
        lbl_tasa.setProperty("class", "FormLabel")
        self.tasa_input = NumericLineEdit(NumericFieldType.RATE)
        self.tasa_input.setFixedHeight(32)
        self.tasa_input.valueChanged.connect(self._calcular_monto_usd)
        col_tasa.addWidget(lbl_tasa)
        col_tasa.addWidget(self.tasa_input)

        fila_bolivares.addLayout(col_bolivares, stretch=1)
        fila_bolivares.addLayout(col_tasa, stretch=1)
        campos_bolivares_layout.addLayout(fila_bolivares)

        # Selector de tasas disponibles
        fila_tasa_selector = QHBoxLayout()
        fila_tasa_selector.setSpacing(8)
        lbl_usar_tasa = QLabel("Usar tasa:")
        lbl_usar_tasa.setStyleSheet("font-size: 12px; color: #64748B;")
        self.tasa_combo = QComboBox()
        self.tasa_combo.setFixedHeight(32)
        self.tasa_combo.addItem("-- Seleccionar --")
        self.tasa_combo.currentIndexChanged.connect(self._on_tasa_seleccionada)
        fila_tasa_selector.addWidget(lbl_usar_tasa)
        fila_tasa_selector.addWidget(self.tasa_combo)
        fila_tasa_selector.addStretch()
        campos_bolivares_layout.addLayout(fila_tasa_selector)

        layout.addWidget(self.campos_bolivares_widget)

        lbl_origen = QLabel(f"Origen {ASTERISCO_REQUERIDO}")
        lbl_origen.setProperty("class", "FormLabel")
        self.origen_combo = QComboBox()
        self.origen_combo.setFixedHeight(32)
        self.origen_combo.currentIndexChanged.connect(self._toggle_campos_bolivares)
        layout.addWidget(lbl_origen)
        layout.addWidget(self.origen_combo)

        lbl_ref = QLabel("Referencia")
        lbl_ref.setProperty("class", "FormLabel")
        self.referencia_input = QLineEdit()
        self.referencia_input.setPlaceholderText("Opcional")
        self.referencia_input.setFixedHeight(32)
        self.referencia_input.setMaxLength(100)
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
        self.btn_abonar = QPushButton("Aplicar Abono BCV")
        self.btn_abonar.setObjectName("BtnPrimary")
        self.btn_abonar.setFixedHeight(34)
        self.btn_abonar.setAutoDefault(False)
        self.btn_abonar.clicked.connect(self._validar_y_aceptar)
        footer.addWidget(btn_cancelar)
        footer.addWidget(self.btn_abonar)
        root.addLayout(footer)

    def _cargar_origenes(self) -> None:
        try:
            session = self.session_factory()
            try:
                cajas = CajaService.listar_cajas(session, id_usuario=self.id_usuario)
            finally:
                session.close()
        except PermisoDenegadoError:
            cajas = []
        self._cajas_abiertas = [c for c in cajas if c.fecha_apertura is not None and c.fecha_cierre is None]
        try:
            session = self.session_factory()
            try:
                cuentas = BancoService.listar_cuentas(session, id_usuario=self.id_usuario)
            finally:
                session.close()
        except PermisoDenegadoError:
            cuentas = []
        self._cuentas_activas = [c for c in cuentas if (c.estado_cuenta or "ACTIVO") == "ACTIVO"]

    def _cargar_tasas(self) -> None:
        """Carga las tasas actuales (BCV, paralelo y COP) en el combo."""
        try:
            session = self.session_factory()
            try:
                from app.db.models import ControlDeTasa

                tasa_registro = (
                    session.query(ControlDeTasa)
                    .order_by(ControlDeTasa.fecha_tasa.desc(), ControlDeTasa.id_tasa.desc())
                    .first()
                )
            finally:
                session.close()
        except Exception:
            tasa_registro = None

        self.tasa_combo.blockSignals(True)
        self.tasa_combo.clear()
        self.tasa_combo.addItem("-- Seleccionar --")

        if tasa_registro:
            if tasa_registro.tasa_dolar_bcv:
                tasa_bcv = _as_decimal(tasa_registro.tasa_dolar_bcv)
                etiqueta_bcv = f"BCV: {float(tasa_bcv):,.2f}"
                self.tasa_combo.addItem(etiqueta_bcv, (tasa_registro.id_tasa, float(tasa_bcv)))
            if tasa_registro.tasa_dolar_paralelo:
                tasa_paralelo = _as_decimal(tasa_registro.tasa_dolar_paralelo)
                etiqueta_paralelo = f"Paralelo: {float(tasa_paralelo):,.2f}"
                self.tasa_combo.addItem(
                    etiqueta_paralelo,
                    (tasa_registro.id_tasa, float(tasa_paralelo)),
                )
            if tasa_registro.tasa_cop:
                tasa_cop = _as_decimal(tasa_registro.tasa_cop)
                etiqueta_cop = f"COP: {float(tasa_cop):,.2f}"
                self.tasa_combo.addItem(etiqueta_cop, (tasa_registro.id_tasa, float(tasa_cop)))

        self.tasa_combo.blockSignals(False)

        if self.tasa_bcv:
            self.tasa_input.set_value(self.tasa_bcv)

    def _on_metodo_cambiado(self) -> None:
        self._toggle_origen()
        self._toggle_campos_bolivares()

    def _toggle_origen(self) -> None:
        metodo = self.metodo_combo.currentData()
        requiere_caja = metodo in METODOS_QUE_REQUIEREN_CAJA
        self.origen_combo.blockSignals(True)
        self.origen_combo.clear()
        if requiere_caja:
            if not self._cajas_abiertas:
                self.origen_combo.addItem("Sin cajas abiertas")
                self.origen_combo.setEnabled(False)
            else:
                self.origen_combo.setEnabled(True)
                for caja in self._cajas_abiertas:
                    self.origen_combo.addItem(
                        caja.nombre_caja or f"Caja {caja.id_caja}",
                        ("caja", caja.id_caja),
                    )
        else:
            if not self._cuentas_activas:
                self.origen_combo.addItem("Sin cuentas bancarias activas")
                self.origen_combo.setEnabled(False)
            else:
                self.origen_combo.setEnabled(True)
                for cuenta in self._cuentas_activas:
                    nombre_banco = cuenta.banco.nombre_banco if cuenta.banco else "Banco"
                    self.origen_combo.addItem(
                        f"{nombre_banco} - ...{cuenta.numero_cuenta[-4:]}",
                        ("banco", cuenta.id_cuenta),
                    )
        self.origen_combo.blockSignals(False)
        self._toggle_campos_bolivares()

    def _toggle_campos_bolivares(self) -> None:
        """Muestra/oculta los campos de bolivares según el método de pago y origen."""
        metodo = self.metodo_combo.currentData()
        origen = self.origen_combo.currentData()
        es_banco = origen is not None and origen[0] == "banco"
        es_efectivo = metodo == "efectivo"

        # Mostrar campos de bolivares solo para pagos bancarios (no efectivo)
        mostrar_bolivares = es_banco and not es_efectivo
        self.campos_bolivares_widget.setVisible(bool(mostrar_bolivares))

        if mostrar_bolivares:
            self.monto_input.setReadOnly(True)
            self.monto_input.setStyleSheet("background-color: #F1F5F9;")
            if self._id_tasa_seleccionada is None and self.tasa_combo.count() > 1:
                self.tasa_combo.setCurrentIndex(1)
        else:
            self.monto_input.setReadOnly(False)
            self.monto_input.setStyleSheet("")

        # Para efectivo, ocultar completamente el campo de tasa ya que no se usa
        if es_efectivo:
            self.tasa_input.set_value(Decimal("0.00"))
            self.tasa_input.setEnabled(False)

    def _on_tasa_seleccionada(self) -> None:
        """Carga la tasa seleccionada del combo al campo de tasa y calcula bolivares."""
        tasa_data = self.tasa_combo.currentData()
        if tasa_data is not None:
            id_tasa, valor_tasa = tasa_data
            self._id_tasa_seleccionada = id_tasa
            self.tasa_input.set_value(valor_tasa)
            monto_usd = self.monto_input.get_value() or Decimal("0")
            if valor_tasa > 0 and monto_usd > 0:
                bolivares = monto_usd * Decimal(str(valor_tasa))
                self.bolivares_input.set_value(bolivares)
            self._calcular_monto_usd()

    def _calcular_monto_usd(self) -> None:
        """Calcula el monto USD automáticamente: bolivares / tasa."""
        metodo = self.metodo_combo.currentData()
        origen = self.origen_combo.currentData()
        if metodo == "efectivo" or not origen or origen[0] != "banco":
            return

        bolivares = self.bolivares_input.get_value() or Decimal("0")
        tasa = self.tasa_input.get_value() or Decimal("0")

        if tasa > 0:
            monto_usd = bolivares / tasa
            self.monto_input.set_value(monto_usd)
            if self.monto_input.isReadOnly():
                self.monto_input.setStyleSheet("background-color: #F1F5F9;")

    def _calcular_bolivares_desde_usd(self) -> None:
        """Calcula el monto en bolivares automáticamente: USD * tasa."""
        metodo = self.metodo_combo.currentData()
        origen = self.origen_combo.currentData()
        if metodo == "efectivo" or not origen or origen[0] != "banco":
            return

        monto_usd = self.monto_input.get_value() or Decimal("0")
        tasa = self.tasa_input.get_value() or Decimal("0")

        if tasa > 0 and monto_usd > 0:
            bolivares = monto_usd * tasa
            self.bolivares_input.set_value(bolivares)

    def _validar_y_aceptar(self) -> None:
        origen = self.origen_combo.currentData()
        if origen is None:
            MessageBox.warning(
                self,
                "Origen requerido",
                "No hay ninguna caja/cuenta disponible para este método.",
            )
            return
        tipo_origen, id_origen = origen

        self.btn_abonar.setEnabled(False)
        try:
            metodo = self.metodo_combo.currentData()
            tasa_cambio = None
            id_tasa = None

            # Obtener monto del abono primero
            monto_abono = self.monto_input.get_value()
            if not monto_abono or monto_abono <= 0:
                MessageBox.warning(self, "Monto requerido", "El monto del abono debe ser mayor a cero.")
                return

            # Obtener tasa de cambio según el método de pago
            if metodo != "efectivo" and tipo_origen == "banco":
                # Para pagos bancarios, usar la tasa ingresada o seleccionada
                tasa = self.tasa_input.get_value() or Decimal("0")
                if tasa == 0 and self._id_tasa_seleccionada:
                    tasa_data = self.tasa_combo.currentData()
                    if tasa_data:
                        _, valor_tasa = tasa_data
                        tasa = Decimal(str(valor_tasa))

                if tasa > 0:
                    tasa_cambio = tasa
                id_tasa = self._id_tasa_seleccionada

                if not tasa_cambio or tasa_cambio <= 0:
                    MessageBox.warning(
                        self,
                        "Tasa requerida",
                        "Para pagos bancarios debe indicar una tasa de cambio válida.",
                    )
                    return
            else:
                # Para efectivo, usar tasa BCV solo para cálculos internos (no se muestra al usuario)
                if self.tasa_bcv and self.tasa_bcv > 0:
                    tasa_cambio = Decimal(str(self.tasa_bcv))
                else:
                    # Si no hay tasa BCV, usar 1.0 como tasa por defecto para efectivo
                    tasa_cambio = Decimal("1.00")

            # Aplicar abono general usando el servicio BCV
            session = self.session_factory()
            try:
                self.abono_aplicado = reintentar_en_deadlock(
                    lambda: PagoBCVService.aplicar_abono_general_cliente_bcv(
                        session=session,
                        id_cliente=self.cliente.id_cliente if self.cliente else None,
                        monto_abono=monto_abono,
                        tasa_cambio=tasa_cambio,
                        metodo_pago=metodo,
                        id_cuenta_bancaria=(id_origen if tipo_origen == "banco" else None),
                        id_caja=id_origen if tipo_origen == "caja" else None,
                        id_tasa=id_tasa,
                        referencia=self.referencia_input.text().strip() or None,
                        id_usuario=self.id_usuario,
                    )
                )
                MessageBox.information(
                    self,
                    "Abono aplicado",
                    "Abono general BCV aplicado exitosamente.\n"
                    f"Monto aplicado: ${float(self.abono_aplicado['monto_total_aplicado']):,.2f}",
                )
                self.accept()
            finally:
                session.close()
        except ValueError as exc:
            MessageBox.warning(self, "No se pudo aplicar el abono", str(exc))
            return
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para aplicar abonos.")
            return
        except Exception as e:
            logger.exception(f"Fallo al aplicar abono general BCV: {e}")
            MessageBox.critical(self, "Error", f"No se pudo aplicar el abono: {str(e)}")
            return
        finally:
            self.btn_abonar.setEnabled(True)


class DetalleCuentasBCVDialog(QDialog):
    """Diálogo para mostrar las cuentas individuales BCV de un cliente."""

    def __init__(
        self,
        session_factory,
        cliente,
        cuentas: list,
        tasa_bcv: float | None,
        id_usuario: int | None,
        parent=None,
    ):
        super().__init__(parent)
        self.session_factory = session_factory
        self.cliente = cliente
        self.cuentas = cuentas
        self.tasa_bcv = tasa_bcv
        self.id_usuario = id_usuario
        self.se_realizo_cobro = False

        self.setWindowTitle(f"Detalle de Cuentas BCV - {cliente.nombre_razon_social if cliente else 'Cliente'}")
        self.setFixedSize(900, 600)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._build_ui()
        self._poblar_tabla_detalle()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # Header con información del cliente
        header = QWidget()
        header.setStyleSheet("background: transparent;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)

        lbl_titulo = QLabel("Facturas Pendientes BCV")
        lbl_titulo.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        header_layout.addWidget(lbl_titulo)
        header_layout.addStretch()

        lbl_cliente = QLabel(self.cliente.nombre_razon_social if self.cliente else "Cliente")
        lbl_cliente.setStyleSheet(f"font-size: 14px; color: {COLOR_TEXT_MEDIUM};")
        header_layout.addWidget(lbl_cliente)

        # Saldo a favor del cliente
        self.lbl_saldo_favor = QLabel("")
        self.lbl_saldo_favor.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_SUCCESS};")
        header_layout.addWidget(self.lbl_saldo_favor)

        # Monto total a cobrar
        self.lbl_monto_total = QLabel("")
        self.lbl_monto_total.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_PRIMARY};")
        header_layout.addWidget(self.lbl_monto_total)

        root.addWidget(header)

        # Tabla de facturas
        self.tabla = self._crear_tabla_detalle()
        root.addWidget(self.tabla)

        # Footer con botones
        footer = QHBoxLayout()
        footer.addStretch()

        btn_abono_general = QPushButton("Abono General BCV")
        btn_abono_general.setIcon(qta.icon("fa5s.money-bill-wave", color=COLOR_TEXT_DARK))
        btn_abono_general.setObjectName("BtnPrimary")
        btn_abono_general.setFixedHeight(34)
        btn_abono_general.setAutoDefault(False)
        btn_abono_general.clicked.connect(self._aplicar_abono_general)

        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setObjectName("BtnSecondary")
        btn_cerrar.setFixedHeight(34)
        btn_cerrar.setAutoDefault(False)
        btn_cerrar.clicked.connect(self.accept)

        footer.addWidget(btn_abono_general)
        footer.addWidget(btn_cerrar)

        root.addLayout(footer)

    def _crear_tabla_detalle(self) -> QTableWidget:
        columnas = [
            "ID",
            "Factura",
            "Porcentaje BCV",
            "Saldo Pendiente",
            "Días",
            "Fecha Factura",
            "Estado",
        ]
        tabla = QTableWidget(0, len(columnas))
        tabla.setHorizontalHeaderLabels(columnas)
        tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabla.setAlternatingRowColors(True)
        tabla.setShowGrid(False)
        tabla.verticalHeader().setVisible(False)
        tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Ajustar columnas para que los datos sean visibles
        tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # ID (oculto)
        tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Factura
        tabla.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Porcentaje BCV
        tabla.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Saldo Pendiente
        tabla.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Días
        tabla.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Fecha Factura
        tabla.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)  # Estado
        tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(tabla)
        tabla.setColumnHidden(0, True)
        tabla.verticalHeader().setDefaultSectionSize(40)
        tabla.doubleClicked.connect(self._on_double_click_cuenta)
        # Establecer anchos mínimos para columnas que muestran datos largos
        tabla.setColumnWidth(2, 100)  # Porcentaje BCV - mínimo 100px
        tabla.setColumnWidth(3, 150)  # Saldo Pendiente - mínimo 150px
        tabla.setColumnWidth(6, 100)  # Estado - mínimo 100px

        alinear_encabezados(
            tabla,
            {
                1: Qt.AlignmentFlag.AlignLeft,
                2: Qt.AlignmentFlag.AlignCenter,
                3: Qt.AlignmentFlag.AlignRight,
                4: Qt.AlignmentFlag.AlignRight,
                5: Qt.AlignmentFlag.AlignLeft,
                6: Qt.AlignmentFlag.AlignCenter,
            },
        )

        return tabla

    def _poblar_tabla_detalle(self) -> None:
        self.tabla.setRowCount(len(self.cuentas))

        hoy = date.today()
        monto_total = Decimal("0.00")
        for fila, cuenta in enumerate(self.cuentas):
            factura = cuenta.factura
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(cuenta.id_cuenta_por_cobrar)))
            self.tabla.setItem(fila, 1, QTableWidgetItem(factura.numero_factura if factura else ""))

            # Porcentaje BCV
            porcentaje_text = f"{float(cuenta.porcentaje):.2f}%" if cuenta.porcentaje else "N/A"
            item_porcentaje = QTableWidgetItem(porcentaje_text)
            item_porcentaje.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 2, item_porcentaje)

            saldo_pendiente = _as_decimal(cuenta.saldo_pendiente)
            monto_total += saldo_pendiente
            item_saldo = QTableWidgetItem(f"${float(saldo_pendiente):,.2f}")
            item_saldo.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 3, item_saldo)

            # Calcular días transcurridos desde la emisión de la factura
            dias_transcurridos = 0
            if cuenta.fecha_emision:
                dias_transcurridos = (hoy - cuenta.fecha_emision).days
            item_dias = QTableWidgetItem(str(dias_transcurridos))
            item_dias.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 4, item_dias)

            fecha_emision = cuenta.fecha_emision.strftime("%d/%m/%Y") if cuenta.fecha_emision else "Sin definir"
            self.tabla.setItem(fila, 5, QTableWidgetItem(fecha_emision))

            # Calcular estado visual
            estado_visual = (
                "vencida"
                if cuenta.estado in ("pendiente", "parcial")
                and cuenta.fecha_vencimiento is not None
                and cuenta.fecha_vencimiento < hoy
                else cuenta.estado
            )

            estado_widget = EstadoBadge(
                estado_visual,
                COLORES_ESTADO_CXC_BCV.get(estado_visual, COLOR_TEXT_MUTED),
            )
            self.tabla.setCellWidget(fila, 6, estado_widget)

        # Calcular y mostrar saldo a favor
        saldo_favor_total = sum(_as_decimal(c.saldo_favor) if c.saldo_favor else Decimal("0.00") for c in self.cuentas)
        if saldo_favor_total > 0:
            self.lbl_saldo_favor.setText(f"Saldo a favor: ${float(saldo_favor_total):,.2f}")
        else:
            self.lbl_saldo_favor.setText("")

        # Mostrar monto total a cobrar
        if self.tasa_bcv:
            tasa_bcv = float(self.tasa_bcv) if not isinstance(self.tasa_bcv, float) else self.tasa_bcv
            self.lbl_monto_total.setText(
                f"Total a cobrar: ${float(monto_total):,.2f} (Bs {float(monto_total * Decimal(str(tasa_bcv))):,.2f})"
            )
        else:
            self.lbl_monto_total.setText(f"Total a cobrar: ${float(monto_total):,.2f}")

    def _on_double_click_cuenta(self) -> None:
        """Maneja el doble clic en una cuenta para abrir el diálogo de cobro."""
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            return

        row = filas[0].row()
        item = self.tabla.item(row, 0)
        if item is None:
            return

        id_cuenta = int(item.text())
        self._cobrar_cuenta(id_cuenta)

    def _cobrar_cuenta(self, id_cuenta: int) -> None:
        """Abre el diálogo de cobro para una cuenta específica."""
        try:
            session = self.session_factory()
            try:
                cuenta = session.get(CuentaPorCobrarBCV, id_cuenta)
                if cuenta is None:
                    return
                if cuenta.estado == "pagada":
                    MessageBox.information(self, "Ya pagada", "Esta cuenta por cobrar BCV ya está saldada.")
                    return

                dialogo = PagoCobroBCVDialog(self.session_factory, self.id_usuario, cuenta, self.tasa_bcv, self)
                if dialogo.exec() and dialogo.pago_creado is not None:
                    self.se_realizo_cobro = True
                    MessageBox.information(self, "Cobro registrado", "El cobro BCV se registró con éxito.")
                    # Recargar la tabla de detalle
                    self._recargar_cuentas()
            finally:
                session.close()
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para aplicar cobros.")
        except Exception:
            logger.exception("Fallo al registrar cobro BCV de cliente")
            MessageBox.critical(self, "Error", "No se pudo registrar el cobro.")

    def _recargar_cuentas(self) -> None:
        """Recarga las cuentas del cliente después de un cobro."""
        try:
            session = self.session_factory()
            try:
                resultado = PagoBCVService.listar_cuentas_por_cobrar_bcv(
                    session,
                    id_cliente=self.cliente.id_cliente if self.cliente else None,
                    id_usuario=self.id_usuario,
                )
                self.cuentas = resultado["items"]
                self._poblar_tabla_detalle()
            finally:
                session.close()
        except Exception:
            logger.exception("Fallo al recargar cuentas BCV del cliente")

    def _aplicar_abono_general(self) -> None:
        """Abre el diálogo de abono general BCV para el cliente."""
        try:
            dialogo = AbonoGeneralBCVDialog(
                self.session_factory,
                self.cliente,
                self.id_usuario,
                tasa_bcv=self.tasa_bcv,
                parent=self,
            )
            if dialogo.exec() and dialogo.abono_aplicado is not None:
                self.se_realizo_cobro = True
                MessageBox.information(self, "Abono aplicado", "El abono general BCV se aplicó con éxito.")
                # Recargar la tabla de detalle
                self._recargar_cuentas()
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para aplicar abonos.")
        except Exception:
            logger.exception("Fallo al aplicar abono general BCV")
            MessageBox.critical(self, "Error", "No se pudo aplicar el abono general BCV.")


class CuentasPorCobrarBCVPanel(QWidget):
    """Panel principal del modulo Cuentas por Cobrar BCV."""

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.id_usuario = usuario.id_usuario
        self.pagina_actual = 1
        self.total_paginas = 1
        self.texto_busqueda = ""
        self._estado_filtro = None
        self._tasa_bcv = None
        self._cuentas_cargadas = []
        self._total_pendiente = Decimal("0.00")
        self._total_favor = Decimal("0.00")
        self._total_registros = 0
        self.setObjectName("ContentArea")
        self._setup_ui()
        self._cargar_tasa_bcv()
        QTimer.singleShot(100, self.cargar_cuentas)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.cargar_cuentas()

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

        lbl = QLabel("Cuentas por Cobrar BCV")
        lbl.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        self.lbl_total = QLabel("Cargando…")
        self.lbl_total.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 13px;"
            f" background-color: {COLOR_TABLE_HEADER}; border-radius: 10px;"
            " padding: 3px 10px;"
        )

        self.lbl_saldo_total = QLabel("$0.00")
        self.lbl_saldo_total.setStyleSheet(
            f"color: {COLOR_SUCCESS}; font-size: 13px; font-weight: bold;"
            f" background-color: {COLOR_TABLE_HEADER}; border-radius: 10px;"
            " padding: 3px 10px;"
        )

        # Tasa BCV vigente
        self.lbl_tasa = QLabel()
        self.lbl_tasa.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 13px;"
            f" background-color: {COLOR_TABLE_HEADER}; border-radius: 10px;"
            " padding: 3px 10px;"
        )
        self.lbl_tasa.setVisible(False)

        h.addWidget(lbl)
        h.addWidget(self.lbl_total)
        h.addWidget(self.lbl_saldo_total)
        h.addWidget(self.lbl_tasa)
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

        # Barra de búsqueda
        self.buscar_input = QLineEdit()
        self.buscar_input.setPlaceholderText("Buscar por cliente…")
        self.buscar_input.addAction(
            qta.icon("fa5s.search", color=COLOR_TEXT_LIGHT),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.buscar_input.setObjectName("SearchInput")
        self.buscar_input.setStyleSheet(SEARCH_QSS)
        self.buscar_input.setFixedWidth(320)
        self.buscar_input.textChanged.connect(self._busqueda_dinamica)

        self.estado_combo = QComboBox()
        for etiqueta, valor in ESTADOS_FILTRO:
            self.estado_combo.addItem(etiqueta, valor)
        self.estado_combo.currentIndexChanged.connect(self._buscar_desde_inicio)

        self.btn_filtrar = BotonFiltros([("Estado", self.estado_combo)])

        self.btn_exportar = BotonExportar(
            on_excel=self._exportar_excel_cuentas_bcv,
            on_pdf=self._exportar_pdf_cuentas_bcv,
        )

        h.addWidget(self.buscar_input)
        h.addStretch()
        h.addWidget(self.btn_filtrar)
        h.addWidget(self.btn_exportar)
        return w

    def _make_table(self) -> QWidget:
        headers = [
            "ID Cliente",
            "CLIENTE",
            "SALDO PENDIENTE",
            "SALDO A FAVOR",
            "DÍAS",
            "FECHA FACTURA",
            "ESTADO",
        ]
        self.tabla = self._crear_tabla(headers)
        alinear_encabezados(
            self.tabla,
            {
                1: Qt.AlignmentFlag.AlignLeft,  # CLIENTE
                2: Qt.AlignmentFlag.AlignRight,  # SALDO PENDIENTE
                3: Qt.AlignmentFlag.AlignRight,  # SALDO A FAVOR
                4: Qt.AlignmentFlag.AlignCenter,  # DÍAS
                5: Qt.AlignmentFlag.AlignCenter,  # FECHA FACTURA
                6: Qt.AlignmentFlag.AlignCenter,  # ESTADO
            },
        )
        return self.tabla

    def _crear_tabla(self, columnas: list[str]):
        tabla = QTableWidget(0, len(columnas))
        tabla.setHorizontalHeaderLabels(columnas)
        tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabla.setAlternatingRowColors(True)
        tabla.setShowGrid(False)
        tabla.verticalHeader().setVisible(False)
        tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Ajustar columnas para que los datos sean visibles
        tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # ID Cliente (oculto)
        tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # CLIENTE
        tabla.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # SALDO PENDIENTE
        tabla.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # SALDO A FAVOR
        tabla.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # DÍAS
        tabla.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # FECHA FACTURA
        tabla.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)  # ESTADO
        tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(tabla)
        tabla.setColumnHidden(0, True)
        tabla.verticalHeader().setDefaultSectionSize(45)
        tabla.doubleClicked.connect(self._on_fila_doble_click)
        # Establecer anchos mínimos para columnas que muestran datos largos
        tabla.setColumnWidth(2, 150)  # SALDO PENDIENTE - mínimo 150px
        tabla.setColumnWidth(3, 150)  # SALDO A FAVOR - mínimo 150px
        tabla.setColumnWidth(6, 100)  # ESTADO - mínimo 100px
        return tabla

    def _make_footer(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        self.lbl_paginacion = QLabel("Página 1 de 1")
        self.lbl_paginacion.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 13px;")
        h.addWidget(self.lbl_paginacion)
        h.addStretch()

        btn_ver_detalle = QPushButton("Ver Detalle")
        btn_ver_detalle.setIcon(qta.icon("fa5s.list", color=COLOR_TEXT_DARK))
        btn_ver_detalle.setObjectName("BtnSecondary")
        btn_ver_detalle.setFixedHeight(32)
        btn_ver_detalle.clicked.connect(self._ver_detalle_factura)
        h.addWidget(btn_ver_detalle)

        return w

    def _cargar_tasa_bcv(self) -> None:
        try:
            session = self.session_factory()
            try:
                tasa = TasaService.obtener_tasa_actual(session, id_usuario=self.id_usuario)
                if tasa:
                    self._tasa_bcv = float(tasa.get("tasa_bcv")) if tasa.get("tasa_bcv") else None
                    self.lbl_tasa.setText(f"Tasa BCV: {float(self._tasa_bcv):,.2f} Bs/USD")
                    self.lbl_tasa.setVisible(True)
            finally:
                session.close()
        except (PermisoDenegadoError, Exception):
            self._tasa_bcv = None
            self.lbl_tasa.setVisible(False)

    def _cargar_resumen(self) -> None:
        """Carga el resumen de cuentas por cobrar BCV (total pendiente, saldo a favor y cantidad de clientes)."""
        try:
            session = self.session_factory()
            try:
                from sqlalchemy import func

                from app.db.models import Cliente, CuentaPorCobrarBCV, FacturaVenta

                # Calcular total pendiente y saldo a favor agrupado por cliente
                subquery = (
                    session.query(
                        Cliente.id_cliente,
                        func.sum(CuentaPorCobrarBCV.saldo_pendiente).label("saldo_cliente"),
                        func.sum(CuentaPorCobrarBCV.saldo_favor).label("saldo_favor_cliente"),
                    )
                    .join(
                        FacturaVenta,
                        FacturaVenta.id_factura == CuentaPorCobrarBCV.id_factura,
                    )
                    .join(Cliente, Cliente.id_cliente == FacturaVenta.id_cliente_factura)
                    .filter(CuentaPorCobrarBCV.estado.in_(("pendiente", "parcial")))
                    .group_by(Cliente.id_cliente)
                    .having(func.sum(CuentaPorCobrarBCV.saldo_pendiente) > 0)
                    .subquery()
                )

                total_pendiente = session.query(func.coalesce(func.sum(subquery.c.saldo_cliente), 0)).scalar()

                total_favor = session.query(func.coalesce(func.sum(subquery.c.saldo_favor_cliente), 0)).scalar()

                total_clientes = session.query(func.count(subquery.c.id_cliente)).scalar()

                self._total_pendiente = Decimal(str(total_pendiente)) if total_pendiente else Decimal("0.00")
                self._total_favor = Decimal(str(total_favor)) if total_favor else Decimal("0.00")
                self._total_registros = total_clientes if total_clientes else 0

                # Actualizar UI
                self.lbl_total.setText(f"{self._total_registros} clientes con saldo pendiente")
                self.lbl_saldo_total.setText(f"${float(self._total_pendiente):,.2f}")

                logger.info(
                    f"BCV - Resumen cargado: Total pendiente={self._total_pendiente}, "
                    f"Total favor={self._total_favor}, Clientes={self._total_registros}"
                )
            finally:
                session.close()
        except PermisoDenegadoError:
            MessageBox.warning(
                self,
                "Sin permiso",
                "No tienes permiso para ver el resumen de cuentas BCV.",
            )
        except Exception:
            logger.exception("Error al cargar resumen de cuentas BCV")
            self.lbl_total.setText("0 clientes con saldo pendiente")
            self.lbl_saldo_total.setText("$0.00")

    def cargar_cuentas(self) -> None:
        try:
            session = self.session_factory()
            try:
                resultado = reintentar_en_deadlock(
                    lambda: PagoBCVService.listar_cuentas_por_cobrar_bcv_agrupadas(
                        session=session,
                        estado=self._estado_filtro,
                        pagina=self.pagina_actual,
                        por_pagina=POR_PAGINA,
                        id_usuario=self.id_usuario,
                        busqueda=self.texto_busqueda if self.texto_busqueda else None,
                    )
                )
                self._mostrar_datos(resultado)
                self._cargar_resumen()
            finally:
                session.close()
        except PermisoDenegadoError:
            MessageBox.warning(
                self,
                "Sin permiso",
                "No tienes permiso para ver cuentas por cobrar BCV.",
            )
        except Exception as e:
            logger.exception("Error al cargar cuentas por cobrar BCV")
            MessageBox.critical(self, "Error", f"No se pudieron cargar las cuentas: {str(e)}")

    def _mostrar_datos(self, resultado: dict) -> None:
        self.tabla.setRowCount(0)
        items = resultado.get("items", [])
        self._cuentas_cargadas = items
        total = resultado.get("total", 0)
        pagina = resultado.get("pagina", 1)
        por_pagina = resultado.get("por_pagina", POR_PAGINA)

        for item in items:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)

            # ID Cliente (oculto)
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(item.id_cliente)))

            # CLIENTE
            self.tabla.setItem(fila, 1, QTableWidgetItem(item.nombre_cliente))

            # SALDO PENDIENTE (acumulado)
            saldo = _as_decimal(item.saldo_pendiente)
            saldo_text = f"${float(saldo):,.2f}"
            if self._tasa_bcv:
                tasa_bcv = float(self._tasa_bcv) if not isinstance(self._tasa_bcv, float) else self._tasa_bcv
                saldo_text = f"${float(saldo):,.2f} / Bs {float(saldo * Decimal(str(tasa_bcv))):,.2f}"
            self.tabla.setItem(fila, 2, QTableWidgetItem(saldo_text))

            # SALDO A FAVOR (acumulado)
            saldo_favor = _as_decimal(item.saldo_favor)
            saldo_favor_text = f"${float(saldo_favor):,.2f}"
            if self._tasa_bcv:
                tasa_bcv = float(self._tasa_bcv) if not isinstance(self._tasa_bcv, float) else self._tasa_bcv
                saldo_favor_text = f"${float(saldo_favor):,.2f} / Bs {float(saldo_favor * Decimal(str(tasa_bcv))):,.2f}"
            self.tabla.setItem(fila, 3, QTableWidgetItem(saldo_favor_text))

            # DÍAS (días de crédito)
            dias_text = str(item.dias_credito) if item.dias_credito is not None else "N/A"
            self.tabla.setItem(fila, 4, QTableWidgetItem(dias_text))

            # FECHA FACTURA (fecha de emisión más antigua)
            fecha_factura_text = item.fecha_emision.strftime("%d/%m/%Y") if item.fecha_emision else "N/A"
            self.tabla.setItem(fila, 5, QTableWidgetItem(fecha_factura_text))

            # ESTADO
            estado = getattr(item, "estado_visual", item.estado)
            badge = EstadoBadge(estado, COLORES_ESTADO_CXC_BCV.get(estado, COLOR_TEXT_MEDIUM))
            self.tabla.setCellWidget(fila, 6, badge)

        # Actualizar paginación
        self.total_paginas = (total + por_pagina - 1) // por_pagina if total > 0 else 1
        self.lbl_paginacion.setText(f"Página {pagina} de {self.total_paginas}")

        logger.info(f"Mostrando {len(items)} clientes agrupados de {total} total, página {pagina}")

    def _on_filtro_cambiado(self) -> None:
        self._estado_filtro = self.estado_combo.currentData()
        self.pagina_actual = 1
        self.cargar_cuentas()

    def _busqueda_dinamica(self) -> None:
        self.texto_busqueda = self.buscar_input.text().strip()
        self.pagina_actual = 1
        self.cargar_cuentas()

    def _buscar_desde_inicio(self) -> None:
        self._on_filtro_cambiado()

    def _pagina_anterior(self) -> None:
        if self.pagina_actual > 1:
            self.pagina_actual -= 1
            self.cargar_cuentas()

    def _pagina_siguiente(self) -> None:
        if self.pagina_actual < self.total_paginas:
            self.pagina_actual += 1
            self.cargar_cuentas()

    def _on_fila_doble_click(self) -> None:
        """Maneja el doble clic en una fila para mostrar las cuentas individuales del cliente."""
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            return

        row = filas[0].row()
        if row >= 0 and row < self.tabla.rowCount() and row < len(self._cuentas_cargadas):
            item = self._cuentas_cargadas[row]
            self._mostrar_cuentas_cliente(item)

    def _mostrar_cuentas_cliente(self, item) -> None:
        """Muestra las cuentas individuales de un cliente en un diálogo."""
        try:
            session = self.session_factory()
            try:
                from app.db.models import FacturaVenta

                # Obtener todas las cuentas del cliente
                cuentas = (
                    session.query(CuentaPorCobrarBCV)
                    .join(
                        FacturaVenta,
                        FacturaVenta.id_factura == CuentaPorCobrarBCV.id_factura,
                    )
                    .filter(
                        FacturaVenta.id_cliente_factura == item.id_cliente,
                        CuentaPorCobrarBCV.estado.in_(("pendiente", "parcial")),
                        CuentaPorCobrarBCV.saldo_pendiente > 0,
                    )
                    .options(joinedload(CuentaPorCobrarBCV.factura).joinedload(FacturaVenta.cliente))
                    .order_by(CuentaPorCobrarBCV.fecha_vencimiento.desc())
                    .all()
                )

                if not cuentas:
                    mensaje = f"El cliente {item.nombre_cliente} no tiene cuentas pendientes."
                    MessageBox.information(self, "Sin cuentas", mensaje)
                    return

                # Crear diálogo de detalle con abono general
                from app.db.models import Cliente

                cliente = session.get(Cliente, item.id_cliente)
                tasa_bcv_float = float(self._tasa_bcv) if self._tasa_bcv else None
                dialog = DetalleCuentasBCVDialog(
                    self.session_factory,
                    cliente,
                    cuentas,
                    tasa_bcv_float,
                    self.id_usuario,
                    self,
                )
                if dialog.exec() == QDialog.DialogCode.Accepted and dialog.se_realizo_cobro:
                    self.cargar_cuentas()
            finally:
                session.close()
        except Exception as e:
            logger.exception("Error al mostrar cuentas del cliente")
            MessageBox.critical(self, "Error", f"No se pudieron cargar las cuentas: {str(e)}")

    def _cobrar(self, cuenta: CuentaPorCobrarBCV) -> None:
        tasa_bcv_float = float(self._tasa_bcv) if self._tasa_bcv else None
        dialog = PagoCobroBCVDialog(self.session_factory, self.id_usuario, cuenta, tasa_bcv_float, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.pago_creado:
            self.cargar_cuentas()

    def _ver_detalle_factura(self) -> None:
        """Muestra las cuentas individuales del cliente seleccionado."""
        fila_actual = self.tabla.currentRow()
        if fila_actual < 0 or fila_actual >= len(self._cuentas_cargadas):
            MessageBox.warning(
                self,
                "Selección requerida",
                "Seleccione un cliente para ver sus cuentas por cobrar BCV.",
            )
            return

        item = self._cuentas_cargadas[fila_actual]
        self._mostrar_cuentas_cliente(item)

    def _exportar_excel_cuentas_bcv(self) -> None:
        try:
            session = self.session_factory()
            try:
                resultado = reintentar_en_deadlock(
                    lambda: PagoBCVService.listar_cuentas_por_cobrar_bcv_agrupadas(
                        session=session,
                        estado=self._estado_filtro,
                        pagina=1,
                        por_pagina=10000,  # Exportar todo
                        id_usuario=self.id_usuario,
                    )
                )
                items = resultado.get("items", [])
                encabezados = [
                    "CLIENTE",
                    "SALDO PENDIENTE",
                    "SALDO A FAVOR",
                    "DÍAS",
                    "FECHA FACTURA",
                    "ESTADO",
                ]
                filas = []
                for item in items:
                    fila = [
                        item.nombre_cliente,
                        float(item.saldo_pendiente),
                        float(item.saldo_favor),
                        (str(item.dias_credito) if item.dias_credito is not None else "N/A"),
                        (item.fecha_emision.strftime("%d/%m/%Y") if item.fecha_emision else "N/A"),
                        item.estado,
                    ]
                    filas.append(fila)

                ruta, _ = QFileDialog.getSaveFileName(
                    self,
                    "Exportar cuentas por cobrar BCV",
                    "cuentas_por_cobrar_bcv.xlsx",
                    "Excel (*.xlsx)",
                )
                if ruta:
                    exportar_excel(
                        ruta,
                        encabezados,
                        filas,
                        titulo="Cuentas por Cobrar BCV (Agrupadas por Cliente)",
                    )
            finally:
                session.close()
        except Exception as e:
            logger.exception("Error al exportar cuentas por cobrar BCV a Excel")
            MessageBox.critical(self, "Error", f"No se pudo exportar a Excel: {str(e)}")

    def _exportar_pdf_cuentas_bcv(self) -> None:
        try:
            session = self.session_factory()
            try:
                resultado = reintentar_en_deadlock(
                    lambda: PagoBCVService.listar_cuentas_por_cobrar_bcv_agrupadas(
                        session=session,
                        estado=self._estado_filtro,
                        pagina=1,
                        por_pagina=10000,  # Exportar todo
                        id_usuario=self.id_usuario,
                    )
                )
                items = resultado.get("items", [])
                encabezados = [
                    "CLIENTE",
                    "SALDO PENDIENTE",
                    "SALDO A FAVOR",
                    "DÍAS",
                    "FECHA FACTURA",
                    "ESTADO",
                ]
                filas = []
                for item in items:
                    fila = [
                        item.nombre_cliente,
                        float(item.saldo_pendiente),
                        float(item.saldo_favor),
                        (str(item.dias_credito) if item.dias_credito is not None else "N/A"),
                        (item.fecha_emision.strftime("%d/%m/%Y") if item.fecha_emision else "N/A"),
                        item.estado,
                    ]
                    filas.append(fila)

                ruta, _ = QFileDialog.getSaveFileName(
                    self,
                    "Exportar cuentas por cobrar BCV",
                    "cuentas_por_cobrar_bcv.pdf",
                    "PDF (*.pdf)",
                )
                if ruta:
                    exportar_pdf(
                        ruta,
                        "Cuentas por Cobrar BCV (Agrupadas por Cliente)",
                        encabezados,
                        filas,
                    )
            finally:
                session.close()
        except Exception as e:
            logger.exception("Error al exportar cuentas por cobrar BCV a PDF")
            MessageBox.critical(self, "Error", f"No se pudo exportar a PDF: {str(e)}")
