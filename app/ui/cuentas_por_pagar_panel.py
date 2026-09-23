"""
Panel del modulo Cuentas por Pagar (CxP): modulo aparte, no vive dentro de Compras
(app/ui/compras.py) -- pedido explicito del usuario de no mezclar "pagar" con "comprar"
en la misma pantalla. Mismo patron visual que app/ui/proveedores_panel.py (paleta y
tipografia de app/ui/styles.py): barra de herramientas, tabla estilizada, paginacion.

Las cuentas por pagar se generan solas (trigger trg_compras_cxp al facturar una compra a
credito, tanto por el flujo directo -- CompraService.registrar_compra -- como por el
flujo OC -- CompraService.crear_compra_desde_oc); este panel es puramente de consulta +
pago, no crea/edita cuentas por pagar directamente.
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
from sqlalchemy.orm import Session

from app.db.models import ConfiguracionEmpresa, CuentaPorPagar, Usuario
from app.services.db_utils import reintentar_en_deadlock
from app.services.empresa import EmpresaService
from app.services.exportacion import exportar_excel, exportar_pdf
from app.services.pagos import PagoService
from app.services.permisos import PermisoDenegadoError
from app.services.tasas import TasaService
from app.services.tesoreria import BancoService, CajaService
from app.ui.message_box import MessageBox
from app.ui.numeric_inputs import NumericFieldType, NumericLineEdit, _as_decimal
from app.ui.pago_linea_dialog import METODOS_PAGO, METODOS_QUE_REQUIEREN_CAJA
from app.ui.styles import (
    ASTERISCO_REQUERIDO,
    BUTTON_SECONDARY_QSS,
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

COLORES_ESTADO_CXP = {
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


class PagoProveedorDialog(QDialog):
    """Un unico pago (sin conversion de moneda -- PagoService.registrar_pago_proveedor no
    la maneja, a diferencia de PagoLineaDialog/pagos_cobros) contra el saldo_pendiente de
    una CuentaPorPagar. Mismo patron de origen caja/cuenta que PagoLineaDialog."""

    def __init__(
        self,
        session: Session,
        id_usuario: int | None,
        cuenta: CuentaPorPagar,
        tasa_bcv: float | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.session = session
        self.id_usuario = id_usuario
        self.cuenta = cuenta
        self.tasa_bcv = tasa_bcv
        self.pago_creado = None
        self._cajas_abiertas: list = []
        self._cuentas_activas: list = []

        self.setWindowTitle("Pagar a Proveedor")
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

        proveedor = self.cuenta.compra.proveedor if self.cuenta.compra else None
        lbl_titulo = QLabel(f"Pagar a {proveedor.nombre_razon_social if proveedor else 'proveedor'}")
        lbl_titulo.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        root.addWidget(lbl_titulo)

        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        saldo_pendiente = _as_decimal(self.cuenta.saldo_pendiente)
        texto_saldo = f"Saldo pendiente: ${float(saldo_pendiente):,.2f}"
        if self.tasa_bcv:
            texto_saldo += f"  (Bs {float(saldo_pendiente) * self.tasa_bcv:,.2f})"
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
        self.monto_input = NumericLineEdit(
            NumericFieldType.AMOUNT, min_value=Decimal("0.01"), max_value=saldo_pendiente, prefix="$ "
        )
        self.monto_input.set_value(saldo_pendiente)
        self.monto_input.setFixedHeight(32)
        self.monto_input.valueChanged.connect(self._on_monto_usd_cambiado)
        layout.addWidget(lbl_monto)
        layout.addWidget(self.monto_input)

        # Campos para cálculo en bolivares (visible solo para transferencia)
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

        # Espacio antes del selector de tasas
        campos_bolivares_layout.addSpacing(10)

        # Selector de tasas disponibles
        fila_tasa_selector = QHBoxLayout()
        fila_tasa_selector.setSpacing(8)
        lbl_usar_tasa = QLabel("Usar tasa:")
        lbl_usar_tasa.setStyleSheet("font-size: 12px; color: #64748B;")
        self.tasa_combo = QComboBox()
        self.tasa_combo.setFixedHeight(16)
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
        layout.addWidget(lbl_origen)
        layout.addWidget(self.origen_combo)

        lbl_ref = QLabel("Referencia")
        lbl_ref.setProperty("class", "FormLabel")
        self.referencia_input = QLineEdit()
        self.referencia_input.setPlaceholderText("Opcional")
        self.referencia_input.setFixedHeight(32)
        self.referencia_input.setMaxLength(100)  # columna referencia VARCHAR(100)
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
        self.btn_pagar = QPushButton("Registrar Pago")
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

    def _cargar_tasas(self) -> None:
        """Carga las tasas actuales (BCV, paralelo y COP) en el combo."""
        try:
            from app.db.models import ControlDeTasa

            # Obtener la tasa más reciente
            tasa_registro = (
                self.session.query(ControlDeTasa)
                .order_by(ControlDeTasa.fecha_tasa.desc(), ControlDeTasa.id_tasa.desc())
                .first()
            )
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

    def _on_metodo_cambiado(self) -> None:
        """Cuando cambia el método de pago, actualiza origen y campos de bolívares."""
        self._toggle_origen()
        self._toggle_campos_bolivares()
        # Un pago en efectivo no tiene "referencia" que registrar
        es_efectivo = self.metodo_combo.currentData() == "efectivo"
        self.referencia_input.setEnabled(not es_efectivo)
        if es_efectivo:
            self.referencia_input.clear()

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
                    self.origen_combo.addItem(caja.nombre_caja or f"Caja {caja.id_caja}", ("caja", caja.id_caja))
        else:
            if not self._cuentas_activas:
                self.origen_combo.addItem("Sin cuentas bancarias activas")
                self.origen_combo.setEnabled(False)
            else:
                self.origen_combo.setEnabled(True)
                for cuenta in self._cuentas_activas:
                    nombre_banco = cuenta.banco.nombre_banco if cuenta.banco else "Banco"
                    self.origen_combo.addItem(
                        f"{nombre_banco} - ...{cuenta.numero_cuenta[-4:]}", ("banco", cuenta.id_cuenta)
                    )
        self.origen_combo.blockSignals(False)

    def _toggle_campos_bolivares(self) -> None:
        """Muestra/oculta los campos de cálculo en bolivares según el método de pago."""
        metodo = self.metodo_combo.currentData()
        # Solo mostrar para transferencia
        mostrar_bolivares = metodo == "transferencia"
        self.campos_bolivares_widget.setVisible(mostrar_bolivares)

    def _on_tasa_seleccionada(self) -> None:
        """Cuando se selecciona una tasa del combo, actualiza el campo de tasa."""
        datos_tasa = self.tasa_combo.currentData()
        if datos_tasa:
            _, tasa_valor = datos_tasa
            self.tasa_input.set_value(Decimal(str(tasa_valor)))
            self._calcular_monto_usd()

    def _on_monto_usd_cambiado(self) -> None:
        """Cuando el monto en USD cambia, calcula el equivalente en Bs si aplica."""
        metodo = self.metodo_combo.currentData()
        if metodo == "transferencia":
            self._calcular_bolivares_desde_usd()

    def _calcular_monto_usd(self) -> None:
        """Calcula el monto en USD a partir del monto en Bs y la tasa."""
        monto_bs = self.bolivares_input.get_value()
        tasa = self.tasa_input.get_value()
        if monto_bs > 0 and tasa > 0:
            monto_usd = monto_bs / tasa
            self.monto_input.set_value(monto_usd)

    def _calcular_bolivares_desde_usd(self) -> None:
        """Calcula el monto en Bs a partir del monto en USD y la tasa."""
        monto_usd = self.monto_input.get_value()
        tasa = self.tasa_input.get_value()
        if monto_usd > 0 and tasa > 0:
            monto_bs = monto_usd * tasa
            self.bolivares_input.set_value(monto_bs)

    def _validar_y_aceptar(self) -> None:
        origen = self.origen_combo.currentData()
        if origen is None:
            MessageBox.warning(self, "Origen requerido", "No hay ninguna caja/cuenta disponible para este método.")
            return
        tipo_origen, id_origen = origen

        self.btn_pagar.setEnabled(False)
        try:
            metodo = self.metodo_combo.currentData()
            monto_bolivares = None
            tasa_cambio = None
            id_tasa = None

            # Para transferencia, incluir monto en bolívares y tasa
            if metodo == "transferencia":
                monto_bolivares = self.bolivares_input.get_value()
                tasa_cambio = self.tasa_input.get_value()
                datos_tasa = self.tasa_combo.currentData()
                if datos_tasa:
                    id_tasa, _ = datos_tasa

            self.pago_creado = reintentar_en_deadlock(
                lambda: PagoService.registrar_pago_proveedor(
                    self.session,
                    id_cuenta_por_pagar=self.cuenta.id_cuenta,
                    monto=self.monto_input.get_value(),
                    metodo_pago=metodo,
                    id_caja=id_origen if tipo_origen == "caja" else None,
                    id_cuenta_bancaria=id_origen if tipo_origen == "banco" else None,
                    id_tasa=id_tasa,
                    referencia=self.referencia_input.text().strip() or None,
                    id_usuario=self.id_usuario,
                    monto_bolivares=monto_bolivares,
                    tasa_cambio=tasa_cambio,
                )
            )
        except ValueError as exc:
            self.session.rollback()
            MessageBox.warning(self, "No se pudo registrar el pago", str(exc))
            return
        except PermisoDenegadoError:
            self.session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para aplicar pagos.")
            return
        except Exception:
            self.session.rollback()
            logger.exception("Fallo al registrar pago a proveedor")
            MessageBox.critical(self, "Error", "No se pudo registrar el pago.")
            return
        finally:
            self.btn_pagar.setEnabled(True)

        self.accept()


class CuentasPorPagarPanel(QWidget):
    """Panel principal del modulo Cuentas por Pagar: listado con filtro por estado,
    paginacion y pago contra PagoService.registrar_pago_proveedor."""

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.pagina_actual = 1
        self.total_paginas = 1
        self._tasa_bcv: float | None = None
        self.texto_busqueda = ""
        self.setObjectName("ContentArea")
        self._setup_ui()
        QTimer.singleShot(100, self.cargar_cuentas)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.cargar_cuentas()

    # ── Construccion de la UI ─────────────────────────────────────────────

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

        lbl = QLabel("Cuentas por Pagar")
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

        # Tasa BCV vigente -- mismo patron informativo que factura_form_dialog.py/
        # cuentas_por_cobrar_panel.py: se oculta si el usuario no tiene 'tasas'/'ver' o no
        # hay ninguna tasa registrada, nunca bloquea el panel.
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
        self.buscar_input.setPlaceholderText("Buscar por proveedor o RIF…")
        self.buscar_input.addAction(
            qta.icon("fa5s.search", color=COLOR_TEXT_LIGHT), QLineEdit.ActionPosition.LeadingPosition
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

        self.btn_exportar = BotonExportar(on_excel=self._exportar_excel, on_pdf=self._exportar_pdf)

        h.addWidget(self.buscar_input)
        h.addStretch()
        h.addWidget(self.btn_filtrar)
        h.addWidget(self.btn_exportar)
        return w

    def _make_table(self) -> QWidget:
        self.tabla = self._crear_tabla(
            [
                "ID",
                "Compra",
                "Proveedor",
                "Saldo Pendiente",
                "Fecha Factura",
                "Días",
                "Vencimiento",
                "Estado",
                "Acciones",
            ]
        )
        alinear_encabezados(
            self.tabla,
            {
                1: Qt.AlignmentFlag.AlignLeft,
                2: Qt.AlignmentFlag.AlignLeft,
                3: Qt.AlignmentFlag.AlignRight,
                4: Qt.AlignmentFlag.AlignCenter,
                5: Qt.AlignmentFlag.AlignCenter,
                6: Qt.AlignmentFlag.AlignLeft,
                7: Qt.AlignmentFlag.AlignCenter,
                8: Qt.AlignmentFlag.AlignCenter,
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
        tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(tabla)
        tabla.setColumnHidden(0, True)
        tabla.verticalHeader().setDefaultSectionSize(45)
        return tabla

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

        btn_pagar = QPushButton("Pagar")
        btn_pagar.setIcon(qta.icon("fa5s.money-bill-wave", color=COLOR_TEXT_DARK))
        btn_pagar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_pagar.clicked.connect(self.pagar_seleccionada)

        h.addWidget(self.lbl_pagina)
        h.addWidget(self.btn_anterior)
        h.addWidget(self.btn_siguiente)
        h.addStretch()
        h.addWidget(btn_pagar)
        return w

    # ── Paginacion ───────────────────────────────────────────────────────

    def _buscar_desde_inicio(self) -> None:
        self.pagina_actual = 1
        self.cargar_cuentas()

    def _busqueda_dinamica(self) -> None:
        """Búsqueda dinámica por nombre o RIF del proveedor."""
        self.texto_busqueda = self.buscar_input.text().strip()
        self.pagina_actual = 1
        self.cargar_cuentas()

    def _pagina_anterior(self) -> None:
        if self.pagina_actual > 1:
            self.pagina_actual -= 1
            self.cargar_cuentas()

    def _pagina_siguiente(self) -> None:
        if self.pagina_actual < self.total_paginas:
            self.pagina_actual += 1
            self.cargar_cuentas()

    # ── Logica de datos ────────────────────────────────────────────────────

    def _cargar_tasa_actual(self, session) -> float | None:
        """Tasa BCV vigente, solo para mostrar el equivalente en Bs -- nunca bloquea el
        panel. Mismo patron que factura_form_dialog.py::_cargar_tasa_vigente()."""
        try:
            tasa = TasaService.obtener_tasa_actual(session, id_usuario=self.usuario.id_usuario)
        except PermisoDenegadoError:
            self.lbl_tasa.setVisible(False)
            return None
        if tasa is None:
            self.lbl_tasa.setVisible(False)
            return None
        fecha = tasa["fecha_tasa"].strftime("%d/%m/%Y")
        tasa_bcv = _as_decimal(tasa["tasa_bcv"])
        self.lbl_tasa.setText(f"Tasa BCV: {float(tasa_bcv):,.2f} Bs/USD ({fecha})")
        self.lbl_tasa.setVisible(True)
        return float(tasa_bcv)

    def cargar_cuentas(self) -> None:
        session = self.session_factory()
        try:
            self.texto_busqueda = self.buscar_input.text().strip()
            self._tasa_bcv = self._cargar_tasa_actual(session)
            resultado = PagoService.listar_cuentas_por_pagar(
                session,
                estado=self.estado_combo.currentData(),
                pagina=self.pagina_actual,
                por_pagina=POR_PAGINA,
                id_usuario=self.usuario.id_usuario,
            )

            # Aplicar filtros de búsqueda manualmente (nombre o RIF del proveedor)
            cuentas_filtradas = []
            for cuenta in resultado["items"]:
                try:
                    proveedor = cuenta.compra.proveedor if cuenta.compra else None

                    # Filtro de búsqueda (nombre o RIF del proveedor)
                    if self.texto_busqueda:
                        nombre = proveedor.nombre_razon_social if proveedor else ""
                        # Construir RIF completo desde id_legal e identificacion_proveedor
                        if proveedor and proveedor.id_legal and proveedor.identificacion_proveedor:
                            rif = f"{proveedor.id_legal}-{proveedor.identificacion_proveedor}"
                        else:
                            rif = proveedor.identificacion_proveedor if proveedor else ""
                        # Buscar en nombre, RIF completo, identificación sola, o id_legal
                        if (
                            self.texto_busqueda.lower() not in nombre.lower()
                            and self.texto_busqueda.lower() not in rif.lower()
                            and self.texto_busqueda.lower() not in (proveedor.identificacion_proveedor or "").lower()
                            and self.texto_busqueda.lower() not in (proveedor.id_legal or "").lower()
                        ):
                            continue

                    cuentas_filtradas.append(cuenta)
                except (AttributeError, TypeError):
                    # Si hay error al acceder a atributos, saltar esta cuenta
                    continue

            # Actualizar resultado con cuentas filtradas
            resultado["items"] = cuentas_filtradas
            resultado["total"] = len(cuentas_filtradas)

            self._poblar_tabla(resultado)
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar cuentas por pagar.")
        except Exception:
            logger.exception("Fallo al cargar el listado de cuentas por pagar")
            MessageBox.critical(self, "Error de conexión", "No se pudo cargar el listado de cuentas por pagar.")
        finally:
            session.close()

    def _poblar_tabla(self, resultado: dict) -> None:
        cuentas: list[CuentaPorPagar] = resultado["items"]
        self.tabla.setRowCount(len(cuentas))

        saldo_total = 0.0
        for fila, cuenta in enumerate(cuentas):
            compra = cuenta.compra
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(cuenta.id_cuenta)))
            self.tabla.setItem(fila, 1, QTableWidgetItem(compra.numero_compra if compra else ""))
            self.tabla.setItem(
                fila, 2, QTableWidgetItem(compra.proveedor.nombre_razon_social if compra and compra.proveedor else "")
            )
            saldo_pendiente = _as_decimal(cuenta.saldo_pendiente)
            item_saldo = QTableWidgetItem(f"${float(saldo_pendiente):,.2f}")
            item_saldo.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 3, item_saldo)

            # Fecha de factura (fecha_emision)
            fecha_factura = cuenta.fecha_emision.strftime("%d/%m/%Y") if cuenta.fecha_emision else "Sin definir"
            item_fecha_factura = QTableWidgetItem(fecha_factura)
            item_fecha_factura.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 4, item_fecha_factura)

            # Días transcurridos desde la fecha de factura
            dias_transcurridos = ""
            if cuenta.fecha_emision:
                dias_hoy = (date.today() - cuenta.fecha_emision).days
                dias_transcurridos = str(dias_hoy)
            item_dias = QTableWidgetItem(dias_transcurridos)
            item_dias.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 5, item_dias)

            vencimiento = cuenta.fecha_vencimiento.strftime("%d/%m/%Y") if cuenta.fecha_vencimiento else "Sin definir"
            self.tabla.setItem(fila, 6, QTableWidgetItem(vencimiento))
            color = COLORES_ESTADO_CXP.get(cuenta.estado, COLOR_TEXT_MUTED)
            self.tabla.setCellWidget(fila, 7, EstadoBadge(cuenta.estado.capitalize(), color))

            # Botón de imprimir factura
            btn_imprimir = QPushButton("Imprimir")
            btn_imprimir.setFixedHeight(28)
            btn_imprimir.setStyleSheet(BUTTON_SECONDARY_QSS)
            btn_imprimir.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_imprimir.clicked.connect(
                lambda checked, id_compra=compra.id_compra if compra else None: self._imprimir_factura_compra(id_compra)
            )
            widget_acciones = QWidget()
            layout_acciones = QHBoxLayout(widget_acciones)
            layout_acciones.setContentsMargins(5, 2, 5, 2)
            layout_acciones.addWidget(btn_imprimir)
            layout_acciones.addStretch()
            self.tabla.setCellWidget(fila, 8, widget_acciones)

            saldo_total += float(saldo_pendiente)

        total = resultado["total"]
        self.total_paginas = max(1, -(-total // POR_PAGINA))
        self.pagina_actual = min(self.pagina_actual, self.total_paginas)

        self.lbl_total.setText(f"{total} cuenta{'s' if total != 1 else ''} por pagar")
        self.lbl_saldo_total.setText(f"${_as_decimal(saldo_total):,.2f}")
        self.lbl_pagina.setText(f"Página {self.pagina_actual} de {self.total_paginas}")
        self.btn_anterior.setEnabled(self.pagina_actual > 1)
        self.btn_siguiente.setEnabled(self.pagina_actual < self.total_paginas)

    def _fila_seleccionada_id(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            MessageBox.information(self, "Selección requerida", "Selecciona una cuenta por pagar de la lista.")
            return None
        item = self.tabla.item(filas[0].row(), 0)
        return int(item.text()) if item is not None else None

    def pagar_seleccionada(self) -> None:
        id_cuenta = self._fila_seleccionada_id()
        if id_cuenta is None:
            return
        session = self.session_factory()
        try:
            cuenta = session.get(CuentaPorPagar, id_cuenta)
            if cuenta is None:
                return
            if cuenta.estado == "pagada":
                MessageBox.information(self, "Ya pagada", "Esta cuenta por pagar ya está saldada.")
                return
            dialogo = PagoProveedorDialog(
                session, self.usuario.id_usuario, cuenta, tasa_bcv=self._tasa_bcv, parent=self
            )
            if dialogo.exec() and dialogo.pago_creado is not None:
                self.cargar_cuentas()
                MessageBox.information(self, "Pago registrado", "El pago se registró con éxito.")
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para aplicar pagos.")
        finally:
            session.close()

    # ── Exportación ───────────────────────────────────────────────────────

    def _exportar_excel(self) -> None:
        """Exporta la tabla actual a un archivo Excel."""
        filas = self._obtener_filas_para_exportar()
        if not filas:
            MessageBox.information(self, "Sin datos", "No hay datos para exportar.")
            return

        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar a Excel", "cuentas_por_pagar.xlsx", "Excel (*.xlsx)")
        if not ruta:
            return

        try:
            config_empresa = self._obtener_config_empresa()
            encabezados = ["Compra", "Proveedor", "Saldo Pendiente", "Fecha Factura", "Días", "Vencimiento", "Estado"]
            exportar_excel(ruta, encabezados, filas, titulo="Cuentas por Pagar", config_empresa=config_empresa)
            MessageBox.information(self, "Exportación exitosa", f"El archivo se guardó en:\n{ruta}")
        except Exception:
            logger.exception("Fallo al exportar a Excel")
            MessageBox.critical(self, "Error", "No se pudo exportar a Excel.")

    def _exportar_pdf(self) -> None:
        """Exporta la tabla actual a un archivo PDF."""
        filas = self._obtener_filas_para_exportar()
        if not filas:
            MessageBox.information(self, "Sin datos", "No hay datos para exportar.")
            return

        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar a PDF", "cuentas_por_pagar.pdf", "PDF (*.pdf)")
        if not ruta:
            return

        try:
            config_empresa = self._obtener_config_empresa()
            encabezados = ["Compra", "Proveedor", "Saldo Pendiente", "Fecha Factura", "Días", "Vencimiento", "Estado"]
            filtros = self._obtener_filtros_para_exportar()
            col_widths = [1.5, 2.5, 1.5, 1.2, 0.8, 1.2, 1.0]
            exportar_pdf(
                ruta,
                "Cuentas por Pagar",
                encabezados,
                filas,
                filtros=filtros,
                col_widths=col_widths,
                config_empresa=config_empresa,
            )
            MessageBox.information(self, "Exportación exitosa", f"El archivo se guardó en:\n{ruta}")
        except Exception:
            logger.exception("Fallo al exportar a PDF")
            MessageBox.critical(self, "Error", "No se pudo exportar a PDF.")

    def _obtener_filas_para_exportar(self) -> list[list]:
        """Obtiene las filas de la tabla actual para exportación."""
        filas = []
        for row in range(self.tabla.rowCount()):
            fila = []
            for col in range(1, self.tabla.columnCount()):  # Saltar columna ID (0)
                item = self.tabla.item(row, col)
                if item:
                    fila.append(item.text())
                else:
                    # Para widgets como EstadoBadge
                    widget = self.tabla.cellWidget(row, col)
                    if widget:
                        # EstadoBadge es un QWidget que contiene un QLabel
                        # Buscamos el QLabel dentro del layout
                        if hasattr(widget, "layout"):
                            layout = widget.layout()
                            if layout:
                                for i in range(layout.count()):
                                    layout_item = layout.itemAt(i)
                                    if layout_item:
                                        item_widget = layout_item.widget()
                                        if isinstance(item_widget, QLabel):
                                            fila.append(item_widget.text())
                                            break
                                else:
                                    fila.append("")
                            else:
                                fila.append("")
                        else:
                            fila.append("")
                    else:
                        fila.append("")
            filas.append(fila)
        return filas

    def _obtener_filtros_para_exportar(self) -> dict[str, str]:
        """Genera un diccionario con los filtros aplicados para el PDF."""
        filtros = {}
        if self.texto_busqueda:
            filtros["Proveedor"] = self.texto_busqueda
        if self.estado_combo.currentData():
            filtros["Estado"] = self.estado_combo.currentText()
        return filtros

    def _obtener_config_empresa(self) -> ConfiguracionEmpresa | None:
        """Obtiene la configuración de la empresa para la exportación."""
        session = self.session_factory()
        try:
            return EmpresaService.obtener_datos_documento(session)
        finally:
            session.close()
