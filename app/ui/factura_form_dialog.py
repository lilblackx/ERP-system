"""Dialogo de emision de una nueva factura de venta (estilo carrito): cabecera
(cliente, vendedor, condicion de pago) + lineas de productos agregadas una a una.
Mismo patron visual que cliente_form_dialog.py/producto_form_dialog.py (paleta y
tipografia de app/ui/styles.py); a diferencia de esos dos, permite redimensionar
porque la tabla del carrito se beneficia de espacio vertical extra."""

import logging
from decimal import Decimal

import qtawesome as qta
from PySide6.QtCore import QDate, QSize, Qt, QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from app.db.models import FacturaVenta, Usuario
from app.services.clientes import list_clientes
from app.services.empresa import EmpresaService
from app.services.inventario import PrecioService, ProductoService
from app.services.permisos import PermisoDenegadoError
from app.services.tasas import TasaService
from app.services.tesoreria import BancoService, CajaService
from app.services.vendedores import VendedorService
from app.services.ventas import VentaService
from app.ui.autorizacion_dialog import AutorizacionDialog
from app.ui.pago_linea_dialog import METODOS_PAGO, MONEDAS, PagoLineaDialog
from app.ui.styles import (
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
    COLOR_TEXT_MUTED,
    FONT_FAMILY,
    ICON_CHEVRON_DOWN_URL,
    ICON_CHEVRON_UP_URL,
    TABLE_QSS,
    TABS_QSS,
    ComboBoxSinScroll,
    alinear_encabezados,
    aplicar_sombra,
)

logger = logging.getLogger(__name__)

_ETIQUETAS_METODO = {valor: etiqueta for etiqueta, valor in METODOS_PAGO}
_ETIQUETAS_MONEDA = {valor: etiqueta for etiqueta, valor in MONEDAS}

# Metodo de vuelto (cambio) de una factura de contado: distinto de METODOS_PAGO (formas de
# pago del cliente) -- efectivo es libre, pago_movil/transferencia exigen referencia
# bancaria + autorizacion de supervisor (recurso 'vueltos_bancarios', ver
# VentaService.emitir_factura y migrations/0027_vuelto_factura.sql).
METODOS_VUELTO = [
    ("Efectivo", "efectivo"),
    ("Pago Móvil", "pago_movil"),
    ("Transferencia", "transferencia"),
]


def _enmascarar(numero: str | None) -> str:
    if not numero:
        return "s/n"
    visibles = numero[-4:]
    return "*" * max(len(numero) - len(visibles), 0) + visibles


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
QLabel.SectionTitle {{
    font-size: 11px;
    font-weight: bold;
    color: {COLOR_PRIMARY};
    letter-spacing: 0.8px;
    padding-bottom: 2px;
}}
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox, QDateEdit {{
    background-color: #FFFFFF;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
    min-height: 20px;
}}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus, QDateEdit:focus {{
    border: 1.5px solid {COLOR_PRIMARY};
    background-color: #FFFFFF;
}}
QLineEdit::placeholder {{
    color: #94A3B8;
    font-size: 12px;
}}
QComboBox::drop-down, QDateEdit::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox::down-arrow, QDateEdit::down-arrow {{
    image: url({ICON_CHEVRON_DOWN_URL});
    width: 12px;
    height: 12px;
    margin-right: 6px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    border: none;
    border-left: 1px solid {COLOR_BORDER};
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    border: none;
    border-left: 1px solid {COLOR_BORDER};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url({ICON_CHEVRON_UP_URL});
    width: 10px;
    height: 10px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url({ICON_CHEVRON_DOWN_URL});
    width: 10px;
    height: 10px;
}}
QComboBox QAbstractItemView {{
    background-color: #FFFFFF;
    border: 1px solid {COLOR_BORDER};
    selection-background-color: #DBEAFE;
    selection-color: {COLOR_TEXT_DARK};
    padding: 4px;
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
QPushButton#BtnAgregar {{
    background-color: #EFF6FF;
    color: {COLOR_PRIMARY};
    border: 1px solid #BFDBFE;
    border-radius: 6px;
    padding: 5px 14px;
    font-size: 13px;
    font-weight: bold;
}}
QPushButton#BtnAgregar:hover {{
    background-color: #DBEAFE;
}}
QPushButton#BtnQuitar {{
    background-color: #FEF2F2;
    color: {COLOR_DANGER};
    border: 1px solid #FECACA;
    border-radius: 5px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: bold;
}}
QPushButton#BtnQuitar:hover {{
    background-color: #FEE2E2;
}}
{TABS_QSS}
"""


LIMITE_CATALOGO = 50  # tope de resultados por busqueda (D-01): evita cargar el catalogo
# completo de clientes/productos a memoria en cada tecla.
DEBOUNCE_BUSQUEDA_MS = 300


class FacturaFormDialog(QDialog):
    """Dialogo de nueva factura: cabecera + carrito de productos.

    Cliente y producto se buscan contra la base con cada tecla (debounce de
    DEBOUNCE_BUSQUEDA_MS), acotado a LIMITE_CATALOGO resultados -- ya no se carga el
    catalogo completo a memoria (D-01, ver Cliente/Producto: carga + filtro server-side
    mas abajo).
    """

    def __init__(self, session: Session, id_usuario: int | None, parent=None):
        super().__init__(parent)
        self.session = session
        self.id_usuario = id_usuario
        self.items: list[dict] = []
        self.pagos: list[dict] = []
        # Poblado por _validar_y_aceptar() al emitir con exito -- VentaService.
        # emitir_factura() se llama desde ADENTRO del dialogo (no despues, en el
        # caller) justo para que un fallo server-side (stock que cambio, limite de
        # credito, etc.) pueda mostrar el error y dejar el dialogo abierto con el
        # carrito/formas de pago intactos, en vez de cerrarse y perder todo lo cargado
        # (hallazgo #3 de la auditoria de facturacion).
        self.factura_emitida: FacturaVenta | None = None
        self._precio_lista_actual: float | None = None
        self._id_autorizador_descuento: int | None = None
        self._motivo_descuento: str | None = None
        self._id_autorizador_dias_credito: int | None = None
        self._motivo_dias_credito: str | None = None
        self._id_autorizador_vuelto: int | None = None
        self._referencia_vuelto: str | None = None
        self._cajas_abiertas_vuelto: list = []
        self._cuentas_activas_vuelto: list = []
        self._tasa_vigente: dict | None = None
        self._iva_activo: bool = False
        self._iva_porcentaje: Decimal = Decimal("0")

        self.setWindowTitle("Nueva Factura")
        self.resize(920, 740)
        self.setMinimumSize(820, 640)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._clientes: list = []
        self._productos: list = []

        self._build_ui()
        self._cargar_clientes()
        self._cargar_vendedores()
        self._cargar_productos()
        self._cargar_tasa_vigente()
        self._cargar_iva_config()
        self._cargar_origenes_vuelto()
        self._toggle_origen_vuelto()
        # condicion_combo ya tiene sus items al construir el grid, antes de conectar la
        # senal (ver _make_card_cabecera) -- se llama una vez a mano para que el estado
        # inicial (Contado, la primera opcion) muestre la tarjeta de formas de pago.
        self._toggle_credito()

    def showEvent(self, event: QShowEvent) -> None:
        # El primer pintado de este dialogo (el mas denso de la app: 4 tarjetas con
        # sombra + 2 tablas) a veces queda con artefactos de tearing en Windows/DWM antes
        # de que QGraphicsDropShadowEffect termine de componer su cache -- se autocorrige
        # con cualquier repintado (mover/redimensionar la ventana), asi que se fuerza uno
        # diferido apenas se muestra, sin esperar a que el usuario lo note.
        super().showEvent(event)
        QTimer.singleShot(0, self.update)

    # ── Construcción de la UI ─────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        root.addWidget(self._make_header())

        self.tabs = QTabWidget()
        self.tabs.addTab(self._make_tab_factura(), "Factura")
        self._idx_tab_pagos = self.tabs.addTab(self._make_tab_pagos(), "Formas de Pago")
        self.tabs.currentChanged.connect(self._on_tab_cambiada)
        root.addWidget(self.tabs, stretch=1)

        root.addLayout(self._make_footer())

    def _make_tab_factura(self) -> QWidget:
        """Cliente/vendedor/condicion + carrito de productos -- se ve el total ANTES de
        pasar a la pestana de formas de pago, que solo tiene sentido conociendolo."""
        page = QWidget()
        layout = QVBoxLayout(page)
        # Margen chico pero no-cero: con 0 las tarjetas (con aplicar_sombra) quedaban
        # pegadas al borde de la pestana, sin lugar para pintar su sombra/borde redondeado
        # (mismo bug encontrado en RolesPermisosPanel, reportado por el usuario 2026-08-27).
        layout.setContentsMargins(4, 12, 4, 4)
        layout.setSpacing(12)
        layout.addWidget(self._make_card_cabecera())
        layout.addWidget(self._make_card_carrito(), stretch=1)
        return page

    def _make_tab_pagos(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 12, 4, 4)
        layout.setSpacing(12)
        layout.addWidget(self._make_card_pagos(), stretch=1)
        return page

    def _make_header(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.file-invoice-dollar", color=COLOR_PRIMARY).pixmap(QSize(22, 22)))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(38, 38)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titulos = QVBoxLayout()
        titulos.setSpacing(1)
        titulos.setContentsMargins(0, 0, 0, 0)
        lbl_titulo = QLabel("Nueva Factura")
        lbl_titulo.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        lbl_subtitulo = QLabel("Seleccione el cliente, agregue productos y emita la factura.")
        lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        titulos.addWidget(lbl_titulo)
        titulos.addWidget(lbl_subtitulo)

        h.addWidget(icon_lbl)
        h.addLayout(titulos)
        h.addStretch()

        self.lbl_tasa = QLabel()
        self.lbl_tasa.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 12px; background-color: {COLOR_FIELD_BG};"
            " border-radius: 10px; padding: 4px 12px;"
        )
        h.addWidget(self.lbl_tasa)
        return w

    def _cargar_tasa_vigente(self) -> None:
        # Meramente informativo (el snapshot real lo hace VentaService.emitir_factura al
        # emitir) -- si el usuario no tiene permiso 'tasas'/'ver' o no hay ninguna tasa
        # registrada, no bloquea el formulario, solo oculta el indicador.
        try:
            tasa = TasaService.obtener_tasa_actual(self.session, id_usuario=self.id_usuario)
        except PermisoDenegadoError:
            self.lbl_tasa.hide()
            return
        if tasa is None:
            # A diferencia de "sin permiso" (se oculta, no es asunto del usuario), esto si
            # es accionable: no hay ninguna tasa registrada en el sistema todavia. Se
            # muestra en vez de ocultar para que no parezca un glitch de la UI.
            self.lbl_tasa.setText("Tasa BCV: no configurada")
            self.lbl_tasa.show()
            return
        self._tasa_vigente = tasa
        fecha = tasa["fecha_tasa"].strftime("%d/%m/%Y")
        self.lbl_tasa.setText(f"Tasa BCV: {tasa['tasa_bcv']:,.2f} Bs/USD ({fecha})")

    def _cargar_iva_config(self) -> None:
        """El total que este dialogo muestra/valida (ver _total_factura_actual) debe
        coincidir con lo que VentaService.emitir_factura() realmente exige (subtotal -
        descuento + IVA) -- antes este dialogo no conocia el IVA en absoluto, el total
        mostrado quedaba por debajo del real, y una factura de contado con IVA activo
        podia parecer "Cubierta" en Formas de Pago y ser rechazada igual al Facturar
        (hallazgo #1 de la auditoria de facturacion).

        EmpresaService.obtener_iva_vigente() no exige permiso 'empresa'/'ver' a proposito
        (ver su docstring): el IVA es una regla de negocio global que necesita cualquier
        usuario que pueda facturar, no solo quien administra el resto de la configuracion
        de la empresa."""
        self._iva_activo, self._iva_porcentaje = EmpresaService.obtener_iva_vigente(self.session)

    def _calcular_iva(self, subtotal_con_descuento: float) -> float:
        """Misma formula que VentaService.emitir_factura(): IVA sobre el subtotal YA
        descontado, redondeado a 2 decimales."""
        if not self._iva_activo:
            return 0.0
        return round(subtotal_con_descuento * float(self._iva_porcentaje) / 100, 2)

    def _cargar_origenes_vuelto(self) -> None:
        """Mismo patron que PagoLineaDialog._cargar_origenes: cajas con turno abierto (para
        vuelto en efectivo) y cuentas bancarias activas (para vuelto por pago movil/
        transferencia) -- ver _make_card_pagos/_toggle_origen_vuelto."""
        try:
            cajas = CajaService.listar_cajas(self.session, id_usuario=self.id_usuario)
        except PermisoDenegadoError:
            cajas = []
        self._cajas_abiertas_vuelto = [c for c in cajas if c.fecha_apertura is not None and c.fecha_cierre is None]

        try:
            cuentas = BancoService.listar_cuentas(self.session, id_usuario=self.id_usuario)
        except PermisoDenegadoError:
            cuentas = []
        self._cuentas_activas_vuelto = [c for c in cuentas if (c.estado_cuenta or "ACTIVO") == "ACTIVO"]

    def _make_card_cabecera(self) -> QWidget:
        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        titulo = QLabel("DATOS DE LA FACTURA")
        titulo.setProperty("class", "SectionTitle")
        layout.addWidget(titulo)

        grid = QGridLayout()
        grid.setSpacing(8)
        for col in range(3):
            grid.setColumnStretch(col, 1)

        # Cliente (busqueda + combo)
        lbl_cliente = QLabel("Cliente <span style='color: #DC2626;'>*</span>")
        lbl_cliente.setProperty("class", "FormLabel")
        self.cliente_buscar_input = QLineEdit()
        self.cliente_buscar_input.setPlaceholderText("Buscar cliente por nombre o identificación…")
        self.cliente_buscar_input.setFixedHeight(30)
        self.cliente_buscar_input.textChanged.connect(self._filtrar_clientes)
        # Mismo criterio que producto_buscar_input: Enter fuerza la busqueda (sin
        # esperar el debounce) y salta a Buscar producto para seguir sin mouse
        # (auditoria UX de facturacion, cajero).
        self.cliente_buscar_input.returnPressed.connect(self._on_cliente_buscar_return_pressed)

        self.cliente_combo = QComboBox()
        self.cliente_combo.setFixedHeight(32)
        self.cliente_combo.currentIndexChanged.connect(self._on_cliente_cambiado)

        grid.addWidget(lbl_cliente, 0, 0, 1, 2)
        grid.addWidget(self.cliente_buscar_input, 1, 0, 1, 2)
        grid.addWidget(self.cliente_combo, 2, 0, 1, 2)

        # Vendedor
        lbl_vendedor = QLabel("Vendedor <span style='color: #DC2626;'>*</span>")
        lbl_vendedor.setProperty("class", "FormLabel")
        self.vendedor_combo = QComboBox()
        self.vendedor_combo.setFixedHeight(32)
        grid.addWidget(lbl_vendedor, 0, 2)
        grid.addWidget(self.vendedor_combo, 1, 2, 2, 1)

        # Condicion de pago
        lbl_condicion = QLabel("Condición de Pago <span style='color: #DC2626;'>*</span>")
        lbl_condicion.setProperty("class", "FormLabel")
        self.condicion_combo = QComboBox()
        self.condicion_combo.setFixedHeight(32)
        self.condicion_combo.addItem("Contado", "contado")
        self.condicion_combo.addItem("Crédito", "credito")
        self.condicion_combo.currentIndexChanged.connect(self._toggle_credito)
        grid.addWidget(lbl_condicion, 3, 0)
        grid.addWidget(self.condicion_combo, 4, 0)

        # Fecha de vencimiento (solo credito)
        lbl_vencimiento = QLabel("Fecha de Vencimiento")
        lbl_vencimiento.setProperty("class", "FormLabel")
        self.vencimiento_input = QDateEdit()
        self.vencimiento_input.setCalendarPopup(True)
        self.vencimiento_input.setDisplayFormat("dd/MM/yyyy")
        self.vencimiento_input.setMinimumDate(QDate.currentDate())
        self.vencimiento_input.setDate(QDate.currentDate().addDays(30))
        self.vencimiento_input.setFixedHeight(32)
        self.vencimiento_input.setEnabled(False)
        grid.addWidget(lbl_vencimiento, 3, 1)
        grid.addWidget(self.vencimiento_input, 4, 1)

        # Observaciones
        lbl_obs = QLabel("Observaciones")
        lbl_obs.setProperty("class", "FormLabel")
        self.observaciones_input = QLineEdit()
        self.observaciones_input.setPlaceholderText("Opcional")
        self.observaciones_input.setMaxLength(255)
        self.observaciones_input.setFixedHeight(32)
        grid.addWidget(lbl_obs, 3, 2)
        grid.addWidget(self.observaciones_input, 4, 2)

        # Dias de credito (solo credito): por defecto usa los configurados en el cliente
        # (self.chk_dias_configurados marcado); desmarcarlo revela un spinbox para dar
        # otros dias a esta factura puntual, lo que exige autorizacion de un supervisor
        # al aceptar (ver _validar_y_aceptar) -- vencimiento_input es siempre un valor
        # derivado de esto, nunca editado a mano.
        self.dias_credito_widget = QWidget()
        fila_dias = QHBoxLayout(self.dias_credito_widget)
        fila_dias.setContentsMargins(0, 4, 0, 0)
        fila_dias.setSpacing(8)
        self.chk_dias_configurados = QCheckBox("Usar días de crédito configurados del cliente")
        # Estilo inline explicito -- el texto no pintaba (aunque .text()/.isVisible()
        # eran correctos) al depender del cascade de DIALOG_STYLE, mismo sintoma que el
        # boton "Cerrar" de historial_cliente_window.py resuelto antes en esta sesion.
        self.chk_dias_configurados.setStyleSheet(f"color: {COLOR_TEXT_DARK}; font-size: 13px;")
        self.chk_dias_configurados.setChecked(True)
        self.chk_dias_configurados.toggled.connect(self._on_toggle_dias_configurados)
        self.lbl_dias_configurados = QLabel()
        self.lbl_dias_configurados.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")
        self.dias_credito_custom_input = QSpinBox()
        self.dias_credito_custom_input.setRange(1, 365)
        self.dias_credito_custom_input.setSuffix(" días")
        self.dias_credito_custom_input.setFixedHeight(32)
        self.dias_credito_custom_input.valueChanged.connect(self._actualizar_vencimiento_calculado)
        self.dias_credito_custom_input.hide()
        self.lbl_autorizacion_dias = QLabel("Requiere autorización de un supervisor")
        self.lbl_autorizacion_dias.setStyleSheet(f"color: {COLOR_DANGER}; font-size: 11px; font-style: italic;")
        self.lbl_autorizacion_dias.hide()
        fila_dias.addWidget(self.chk_dias_configurados)
        fila_dias.addWidget(self.lbl_dias_configurados)
        fila_dias.addWidget(self.dias_credito_custom_input)
        fila_dias.addWidget(self.lbl_autorizacion_dias)
        fila_dias.addStretch()
        self.dias_credito_widget.hide()
        grid.addWidget(self.dias_credito_widget, 5, 0, 1, 3)

        layout.addLayout(grid)

        self.lbl_alerta_credito = QLabel()
        self.lbl_alerta_credito.setWordWrap(True)
        self.lbl_alerta_credito.setStyleSheet(
            "background-color: #FEF2F2; color: #DC2626; border: 1px solid #FECACA;"
            " border-radius: 6px; padding: 6px 10px; font-size: 12px; font-weight: 600;"
        )
        self.lbl_alerta_credito.hide()
        layout.addWidget(self.lbl_alerta_credito)

        return card

    def _make_card_pagos(self) -> QWidget:
        """Contenido de la pestana "Formas de Pago" -- solo interactuable cuando la
        condicion es 'contado' (ver _toggle_credito, que deshabilita la pestana entera
        para credito). Una factura de contado exige registrar aca la(s) forma(s) de pago
        ANTES de poder emitirla (VentaService.emitir_factura(pagos=[...])); por eso esta
        pestana va DESPUES de "Factura" en el orden de tabs -- recien ahi se conoce el
        total contra el cual tienen que alcanzar los pagos."""
        self.card_pagos = QWidget()
        self.card_pagos.setObjectName("SectionCard")
        aplicar_sombra(self.card_pagos)
        layout = QVBoxLayout(self.card_pagos)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        fila_titulo = QHBoxLayout()
        lbl_ayuda = QLabel("Registre una o más formas de pago que cubran el total de la factura.")
        lbl_ayuda.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        fila_titulo.addWidget(lbl_ayuda)
        fila_titulo.addStretch()

        btn_agregar_pago = QPushButton(" Agregar forma de pago")
        btn_agregar_pago.setObjectName("BtnAgregar")
        btn_agregar_pago.setIcon(qta.icon("fa5s.plus-circle", color=COLOR_PRIMARY))
        btn_agregar_pago.setFixedHeight(30)
        btn_agregar_pago.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_agregar_pago.setAutoDefault(False)
        btn_agregar_pago.clicked.connect(self._agregar_pago)
        fila_titulo.addWidget(btn_agregar_pago)
        layout.addLayout(fila_titulo)

        self.tabla_pagos = QTableWidget(0, 5)
        self.tabla_pagos.setHorizontalHeaderLabels(["Método", "Moneda", "Monto", "Origen / Referencia", ""])
        alinear_encabezados(
            self.tabla_pagos,
            {
                0: Qt.AlignmentFlag.AlignLeft,
                1: Qt.AlignmentFlag.AlignLeft,
                2: Qt.AlignmentFlag.AlignRight,
                3: Qt.AlignmentFlag.AlignLeft,
            },
        )
        self.tabla_pagos.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tabla_pagos.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla_pagos.setAlternatingRowColors(True)
        self.tabla_pagos.setShowGrid(False)
        self.tabla_pagos.verticalHeader().setVisible(False)
        self.tabla_pagos.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabla_pagos.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla_pagos.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.tabla_pagos.setColumnWidth(4, 70)
        self.tabla_pagos.setStyleSheet(TABLE_QSS)
        aplicar_sombra(self.tabla_pagos)
        layout.addWidget(self.tabla_pagos, stretch=1)

        self.lbl_total_pagos = QLabel()
        self.lbl_total_pagos.setStyleSheet("font-size: 13px; font-weight: 600;")
        layout.addWidget(self.lbl_total_pagos)

        # Vuelto (cambio): solo visible cuando las formas de pago cargadas exceden el
        # total (ver _refrescar_tabla_pagos) -- efectivo es libre, pago movil/
        # transferencia exigen referencia bancaria + autorizacion de supervisor al
        # aceptar (ver _validar_y_aceptar, reusa AutorizacionDialog).
        self.vuelto_widget = QWidget()
        vuelto_layout = QVBoxLayout(self.vuelto_widget)
        vuelto_layout.setContentsMargins(0, 8, 0, 0)
        vuelto_layout.setSpacing(6)

        self.lbl_vuelto_monto = QLabel()
        self.lbl_vuelto_monto.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_PRIMARY};")
        vuelto_layout.addWidget(self.lbl_vuelto_monto)

        fila_vuelto = QHBoxLayout()
        fila_vuelto.setSpacing(8)

        col_metodo_vuelto = QVBoxLayout()
        lbl_metodo_vuelto = QLabel("Método de vuelto")
        lbl_metodo_vuelto.setProperty("class", "FormLabel")
        self.metodo_vuelto_combo = ComboBoxSinScroll()
        self.metodo_vuelto_combo.setFixedHeight(32)
        for etiqueta, valor in METODOS_VUELTO:
            self.metodo_vuelto_combo.addItem(etiqueta, valor)
        self.metodo_vuelto_combo.currentIndexChanged.connect(self._toggle_origen_vuelto)
        col_metodo_vuelto.addWidget(lbl_metodo_vuelto)
        col_metodo_vuelto.addWidget(self.metodo_vuelto_combo)

        col_origen_vuelto = QVBoxLayout()
        lbl_origen_vuelto = QLabel("Origen del vuelto")
        lbl_origen_vuelto.setProperty("class", "FormLabel")
        self.origen_vuelto_combo = ComboBoxSinScroll()
        self.origen_vuelto_combo.setFixedHeight(32)
        col_origen_vuelto.addWidget(lbl_origen_vuelto)
        col_origen_vuelto.addWidget(self.origen_vuelto_combo)

        fila_vuelto.addLayout(col_metodo_vuelto, stretch=1)
        fila_vuelto.addLayout(col_origen_vuelto, stretch=1)
        vuelto_layout.addLayout(fila_vuelto)

        self.lbl_aviso_vuelto_bancario = QLabel(
            "Requiere referencia bancaria y autorización de un supervisor al facturar"
        )
        self.lbl_aviso_vuelto_bancario.setStyleSheet(f"color: {COLOR_DANGER}; font-size: 11px; font-style: italic;")
        self.lbl_aviso_vuelto_bancario.hide()
        vuelto_layout.addWidget(self.lbl_aviso_vuelto_bancario)

        self.vuelto_widget.hide()
        layout.addWidget(self.vuelto_widget)

        return self.card_pagos

    def _toggle_origen_vuelto(self) -> None:
        metodo = self.metodo_vuelto_combo.currentData()
        es_efectivo = metodo == "efectivo"
        self.origen_vuelto_combo.blockSignals(True)
        self.origen_vuelto_combo.clear()
        if es_efectivo:
            if not self._cajas_abiertas_vuelto:
                self.origen_vuelto_combo.addItem("Sin cajas abiertas", None)
                self.origen_vuelto_combo.setEnabled(False)
            else:
                self.origen_vuelto_combo.setEnabled(True)
                for caja in self._cajas_abiertas_vuelto:
                    self.origen_vuelto_combo.addItem(caja.nombre_caja or f"Caja {caja.id_caja}", ("caja", caja.id_caja))
        else:
            if not self._cuentas_activas_vuelto:
                self.origen_vuelto_combo.addItem("Sin cuentas bancarias activas", None)
                self.origen_vuelto_combo.setEnabled(False)
            else:
                self.origen_vuelto_combo.setEnabled(True)
                for cuenta in self._cuentas_activas_vuelto:
                    nombre_banco = cuenta.banco.nombre_banco if cuenta.banco else "Banco"
                    etiqueta = f"{nombre_banco} - {_enmascarar(cuenta.numero_cuenta)}"
                    self.origen_vuelto_combo.addItem(etiqueta, ("banco", cuenta.id_cuenta))
        self.origen_vuelto_combo.blockSignals(False)
        self.lbl_aviso_vuelto_bancario.setVisible(not es_efectivo)

    def _agregar_pago(self) -> None:
        total_pagado = sum(self._convertir_pago_a_usd(pago) for pago in self.pagos)
        saldo_pendiente = max(self._total_factura_actual() - total_pagado, 0.0)
        dialogo = PagoLineaDialog(self.session, self.id_usuario, monto_sugerido=saldo_pendiente, parent=self)
        if dialogo.exec() == QDialog.DialogCode.Accepted:
            self.pagos.append(dialogo.get_data())
            self._refrescar_tabla_pagos()

    def _quitar_pago(self, indice: int) -> None:
        del self.pagos[indice]
        self._refrescar_tabla_pagos()

    def _convertir_pago_a_usd(self, pago: dict) -> float:
        moneda = pago["moneda"]
        monto = pago["monto_moneda_origen"]
        if moneda in ("USD", "USDT"):
            return monto
        if self._tasa_vigente is None:
            return 0.0
        if moneda == "VES":
            return monto / float(self._tasa_vigente["tasa_bcv"])
        if moneda == "COP":
            tasa_cop = self._tasa_vigente.get("tasa_cop")
            return monto / float(tasa_cop) if tasa_cop else 0.0
        return 0.0

    def _refrescar_tabla_pagos(self) -> None:
        self.tabla_pagos.setRowCount(len(self.pagos))
        total_usd = 0.0
        for fila, pago in enumerate(self.pagos):
            monto_usd = self._convertir_pago_a_usd(pago)
            total_usd += monto_usd

            item_metodo = QTableWidgetItem(_ETIQUETAS_METODO.get(pago["metodo_pago"], pago["metodo_pago"]))
            self.tabla_pagos.setItem(fila, 0, item_metodo)
            item_moneda = QTableWidgetItem(_ETIQUETAS_MONEDA.get(pago["moneda"], pago["moneda"]))
            self.tabla_pagos.setItem(fila, 1, item_moneda)
            texto_monto = f"{pago['monto_moneda_origen']:,.2f}"
            if pago["moneda"] not in ("USD", "USDT"):
                texto_monto += f" (${monto_usd:,.2f})"
            item_monto = QTableWidgetItem(texto_monto)
            item_monto.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla_pagos.setItem(fila, 2, item_monto)
            origen = pago.get("referencia") or ""
            item_origen = QTableWidgetItem(origen)
            self.tabla_pagos.setItem(fila, 3, item_origen)

            btn_quitar = QPushButton()
            btn_quitar.setObjectName("BtnQuitar")
            btn_quitar.setIcon(qta.icon("fa5s.trash-alt", color=COLOR_DANGER))
            btn_quitar.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_quitar.setToolTip("Quitar esta forma de pago")
            btn_quitar.clicked.connect(lambda checked, i=fila: self._quitar_pago(i))
            self.tabla_pagos.setCellWidget(fila, 4, btn_quitar)

        total_factura = self._total_factura_actual()
        falta = total_factura - total_usd
        if falta > 0.005:
            self.lbl_total_pagos.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {COLOR_DANGER};")
            self.lbl_total_pagos.setText(
                f"Total factura: ${total_factura:,.2f}  ·  Pagado: ${total_usd:,.2f}  ·  Falta: ${falta:,.2f}"
            )
        else:
            self.lbl_total_pagos.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {COLOR_SUCCESS};")
            self.lbl_total_pagos.setText(
                f"Total factura: ${total_factura:,.2f}  ·  Pagado: ${total_usd:,.2f}  ·  Cubierto"
            )

        monto_vuelto = max(total_usd - total_factura, 0.0)
        self.vuelto_widget.setVisible(monto_vuelto > 0.005)
        if monto_vuelto > 0.005:
            self.lbl_vuelto_monto.setText(f"Vuelto a entregar: ${monto_vuelto:,.2f}")

        self._actualizar_alerta_credito()

    def _total_factura_actual(self) -> float:
        total = sum(it["cantidad"] * it["precio_unitario"] for it in self.items)
        subtotal_con_descuento = max(total - self.descuento_input.value(), 0.0)
        return subtotal_con_descuento + self._calcular_iva(subtotal_con_descuento)

    def _make_card_carrito(self) -> QWidget:
        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        titulo = QLabel("PRODUCTOS")
        titulo.setProperty("class", "SectionTitle")
        layout.addWidget(titulo)

        fila_agregar = QHBoxLayout()
        fila_agregar.setSpacing(6)

        self.producto_buscar_input = QLineEdit()
        self.producto_buscar_input.setPlaceholderText("Buscar producto…")
        self.producto_buscar_input.setFixedHeight(32)
        self.producto_buscar_input.textChanged.connect(self._filtrar_productos)
        # Enter (ej. un lector de codigo de barras, que escanea + manda Enter solo) fuerza
        # la busqueda de una vez -- sin esto el Enter no hacia nada y quedaba a merced del
        # debounce -- y salta directo a Cantidad en vez de necesitar el mouse (auditoria
        # UX de facturacion, cajero).
        self.producto_buscar_input.returnPressed.connect(self._on_producto_buscar_return_pressed)

        self.producto_combo = QComboBox()
        self.producto_combo.setFixedHeight(32)
        self.producto_combo.setMinimumWidth(220)
        self.producto_combo.currentIndexChanged.connect(self._on_producto_cambiado)

        self.cantidad_input = QDoubleSpinBox()
        self.cantidad_input.setRange(0.01, 999999.99)
        self.cantidad_input.setDecimals(2)
        self.cantidad_input.setValue(1)
        self.cantidad_input.setFixedHeight(32)
        self.cantidad_input.setFixedWidth(100)
        # Enter en Cantidad o Precio agrega directo -- ya se vio/confirmo el producto en
        # el combo antes de llegar aca, cerrando el ciclo escaneo/tipeo -> agregar sin
        # tocar el mouse (auditoria UX de facturacion, cajero).
        self.cantidad_input.lineEdit().returnPressed.connect(self._agregar_item)

        self.precio_input = QDoubleSpinBox()
        self.precio_input.setRange(0.01, 999999999.99)
        self.precio_input.setDecimals(2)
        self.precio_input.setPrefix("$ ")
        self.precio_input.setFixedHeight(32)
        self.precio_input.setFixedWidth(130)
        self.precio_input.lineEdit().returnPressed.connect(self._agregar_item)

        btn_agregar = QPushButton(" Agregar")
        btn_agregar.setObjectName("BtnAgregar")
        btn_agregar.setIcon(qta.icon("fa5s.cart-plus", color=COLOR_PRIMARY))
        btn_agregar.setFixedHeight(32)
        btn_agregar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_agregar.setAutoDefault(False)
        btn_agregar.clicked.connect(self._agregar_item)

        fila_agregar.addWidget(self.producto_buscar_input, stretch=1)
        fila_agregar.addWidget(self.producto_combo, stretch=2)
        fila_agregar.addWidget(self.cantidad_input)
        fila_agregar.addWidget(self.precio_input)
        fila_agregar.addWidget(btn_agregar)
        layout.addLayout(fila_agregar)

        self.nota_item_input = QLineEdit()
        self.nota_item_input.setPlaceholderText("Nota para este item (opcional)…")
        self.nota_item_input.setMaxLength(255)
        self.nota_item_input.setFixedHeight(28)
        self.nota_item_input.returnPressed.connect(self._agregar_item)
        layout.addWidget(self.nota_item_input)

        self.tabla_items = QTableWidget(0, 5)
        self.tabla_items.setHorizontalHeaderLabels(["Producto", "Cantidad", "Precio Unit.", "Subtotal", ""])
        alinear_encabezados(
            self.tabla_items,
            {
                0: Qt.AlignmentFlag.AlignLeft,
                1: Qt.AlignmentFlag.AlignRight,
                2: Qt.AlignmentFlag.AlignRight,
                3: Qt.AlignmentFlag.AlignRight,
            },
        )
        self.tabla_items.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tabla_items.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla_items.setAlternatingRowColors(True)
        self.tabla_items.setShowGrid(False)
        self.tabla_items.verticalHeader().setVisible(False)
        self.tabla_items.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabla_items.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla_items.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.tabla_items.setColumnWidth(4, 70)
        self.tabla_items.setStyleSheet(TABLE_QSS)
        # La fila de dias de credito (card cabecera) puede aparecer/desaparecer segun el
        # cliente/condicion -- sin este minimo, esta tabla (stretch=1) es la que absorbe
        # esa diferencia de alto y sus filas quedan aplastadas/ilegibles cuando la fila de
        # arriba se muestra.
        self.tabla_items.setMinimumHeight(110)
        aplicar_sombra(self.tabla_items)
        layout.addWidget(self.tabla_items, stretch=1)

        fila_total = QHBoxLayout()
        fila_total.setSpacing(8)

        lbl_descuento = QLabel("Descuento de factura:")
        lbl_descuento.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        self.descuento_input = QDoubleSpinBox()
        self.descuento_input.setRange(0, 999999999.99)
        self.descuento_input.setDecimals(2)
        self.descuento_input.setPrefix("$ ")
        self.descuento_input.setFixedWidth(130)
        self.descuento_input.setFixedHeight(30)
        self.descuento_input.valueChanged.connect(self._refrescar_tabla_items)

        fila_total.addWidget(lbl_descuento)
        fila_total.addWidget(self.descuento_input)
        fila_total.addStretch()
        self.lbl_total = QLabel("Total: $0.00")
        self.lbl_total.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        fila_total.addWidget(self.lbl_total)
        layout.addLayout(fila_total)

        return card

    def _make_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 4, 0, 0)
        footer.setSpacing(10)
        footer.addStretch()

        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.setIcon(qta.icon("fa5s.times", color="#475569"))
        self.btn_cancelar.setObjectName("BtnSecondary")
        self.btn_cancelar.setFixedHeight(36)
        self.btn_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancelar.setAutoDefault(False)
        self.btn_cancelar.clicked.connect(self.reject)

        self.btn_emitir = QPushButton("Facturar")
        self.btn_emitir.setIcon(qta.icon("fa5s.check", color="#FFFFFF"))
        self.btn_emitir.setObjectName("BtnPrimary")
        self.btn_emitir.setFixedHeight(36)
        self.btn_emitir.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_emitir.setAutoDefault(False)
        self.btn_emitir.clicked.connect(self._on_click_boton_principal)

        footer.addWidget(self.btn_cancelar)
        footer.addWidget(self.btn_emitir)
        return footer

    # ── Cliente: busqueda server-side con debounce ──────────────────────────

    def _cargar_clientes(self) -> None:
        self._buscar_clientes(None)

    def _buscar_clientes(self, texto: str | None) -> None:
        resultado = list_clientes(self.session, texto, id_usuario=self.id_usuario, por_pagina=LIMITE_CATALOGO)
        self._clientes = [c for c in resultado["items"] if (c.estado_cliente or "ACTIVO") == "ACTIVO"]
        self._poblar_combo_clientes(self._clientes)

    def _poblar_combo_clientes(self, clientes: list) -> None:
        self.cliente_combo.blockSignals(True)
        self.cliente_combo.clear()
        if not clientes:
            self.cliente_combo.addItem("Sin resultados", None)
        for cliente in clientes:
            if cliente.id_legal and cliente.identificacion_cliente:
                identificacion = f"{cliente.id_legal}-{cliente.identificacion_cliente}"
            else:
                identificacion = cliente.id_legal or cliente.identificacion_cliente or "s/i"
            etiqueta = f"{cliente.nombre_razon_social} ({identificacion})"
            self.cliente_combo.addItem(etiqueta, cliente.id_cliente)
        self.cliente_combo.blockSignals(False)
        self.cliente_combo.setEnabled(bool(clientes))
        self._on_cliente_cambiado()

    def _filtrar_clientes(self, texto: str) -> None:
        if not hasattr(self, "_timer_busqueda_cliente"):
            self._timer_busqueda_cliente = QTimer(self)
            self._timer_busqueda_cliente.setSingleShot(True)
            self._timer_busqueda_cliente.timeout.connect(
                lambda: self._buscar_clientes(self.cliente_buscar_input.text().strip() or None)
            )
        self._timer_busqueda_cliente.start(DEBOUNCE_BUSQUEDA_MS)

    def _on_cliente_buscar_return_pressed(self) -> None:
        if hasattr(self, "_timer_busqueda_cliente"):
            self._timer_busqueda_cliente.stop()
        self._buscar_clientes(self.cliente_buscar_input.text().strip() or None)
        if self.cliente_combo.currentData() is not None:
            self.producto_buscar_input.setFocus()

    def _cliente_seleccionado(self):
        id_cliente = self.cliente_combo.currentData()
        return next((c for c in self._clientes if c.id_cliente == id_cliente), None)

    def _on_cliente_cambiado(self) -> None:
        es_credito = self.condicion_combo.currentData() == "credito"
        cliente = self._cliente_seleccionado()
        cliente_tiene_credito = cliente is not None and (cliente.dias_credito or 0) > 0
        self.dias_credito_widget.setVisible(es_credito and cliente_tiene_credito)
        if es_credito and cliente_tiene_credito:
            # Cada vez que cambia el cliente se vuelve a partir de "usar los
            # configurados" -- no se arrastra un override de un cliente anterior.
            self.lbl_dias_configurados.setText(f"({cliente.dias_credito} días)")
            self.chk_dias_configurados.blockSignals(True)
            self.chk_dias_configurados.setChecked(True)
            self.chk_dias_configurados.blockSignals(False)
            self.dias_credito_custom_input.hide()
            self.lbl_autorizacion_dias.hide()
            self._actualizar_vencimiento_calculado()
        self._actualizar_alerta_credito()

    def _on_toggle_dias_configurados(self, checked: bool) -> None:
        self.dias_credito_custom_input.setVisible(not checked)
        self.lbl_autorizacion_dias.setVisible(not checked)
        if not checked:
            cliente = self._cliente_seleccionado()
            self.dias_credito_custom_input.blockSignals(True)
            self.dias_credito_custom_input.setValue(cliente.dias_credito if cliente else 30)
            self.dias_credito_custom_input.blockSignals(False)
        self._actualizar_vencimiento_calculado()

    def _actualizar_vencimiento_calculado(self) -> None:
        """`vencimiento_input` es siempre un valor derivado (nunca editado a mano, ver
        `_make_card_cabecera`) -- refleja lo que `VentaService.emitir_factura` calculará
        server-side a partir de `cliente.dias_credito` o del override del spinbox."""
        if self.chk_dias_configurados.isChecked():
            cliente = self._cliente_seleccionado()
            dias = cliente.dias_credito if cliente else 0
        else:
            dias = self.dias_credito_custom_input.value()
        self.vencimiento_input.setDate(QDate.currentDate().addDays(dias))

    def _actualizar_alerta_credito(self) -> None:
        """Bloqueo visual proactivo (hallazgo #12 del audit de facturacion): antes de que
        el usuario arme todo el carrito y recien se entere del limite de credito al dar
        "Emitir", se avisa apenas el total supera lo disponible. Solo informativo -- el
        backend (VentaService.emitir_factura) vuelve a validar todo de nuevo, pero el
        total usado aca ya incluye IVA (via _total_factura_actual/_calcular_iva, ver
        _cargar_iva_config) para no subestimar cuanto le queda disponible al cliente.

        Tambien es el punto central que habilita/deshabilita btn_emitir: para contado, en
        la pestana "Formas de Pago" (paso final, boton "Facturar") se exige que las
        formas de pago cubran el total -- ver _refrescar_tabla_pagos, que llama esta
        misma funcion. En la pestana "Factura" (paso "Siguiente") no aplica: ese paso
        solo valida cliente/vendedor/items al hacer click, ver _ir_a_formas_de_pago."""
        es_credito = self.condicion_combo.currentData() == "credito"
        es_contado = self.condicion_combo.currentData() == "contado"
        id_cliente = self.cliente_combo.currentData()
        if not es_credito or id_cliente is None:
            self.lbl_alerta_credito.hide()
            if es_contado and self.tabs.currentIndex() == self._idx_tab_pagos:
                self.btn_emitir.setEnabled(self._pagos_cubren_total())
            else:
                self.btn_emitir.setEnabled(True)
            return

        cliente = self._cliente_seleccionado()
        if cliente is not None and (cliente.dias_credito or 0) <= 0:
            self.lbl_alerta_credito.setText(
                f"'{cliente.nombre_razon_social}' no tiene días de crédito configurados: "
                "solo puede facturarse de contado."
            )
            self.lbl_alerta_credito.show()
            self.btn_emitir.setEnabled(False)
            return

        try:
            info = VentaService.consultar_limite_disponible(self.session, id_cliente, id_usuario=self.id_usuario)
        except (ValueError, PermisoDenegadoError):
            self.lbl_alerta_credito.hide()
            self.btn_emitir.setEnabled(True)
            return

        total_carrito = self._total_factura_actual()
        if total_carrito > float(info["disponible"]):
            self.lbl_alerta_credito.setText(
                f"Este cliente tiene ${float(info['disponible']):,.2f} disponibles de credito y la "
                f"factura suma ${total_carrito:,.2f}. No se podra emitir a credito."
            )
            self.lbl_alerta_credito.show()
            self.btn_emitir.setEnabled(False)
        else:
            self.lbl_alerta_credito.hide()
            self.btn_emitir.setEnabled(True)

    def _pagos_cubren_total(self) -> bool:
        total_pagado = sum(self._convertir_pago_a_usd(pago) for pago in self.pagos)
        return total_pagado + 0.005 >= self._total_factura_actual()

    # ── Vendedor ───────────────────────────────────────────────────────────

    def _cargar_vendedores(self) -> None:
        vendedores = VendedorService.listar(
            self.session, id_usuario=self.id_usuario, estado_vendedor="ACTIVO", por_pagina=LIMITE_CATALOGO
        )["items"]
        if not vendedores:
            self.vendedor_combo.addItem("Sin vendedores activos", None)
        for vendedor in vendedores:
            self.vendedor_combo.addItem(vendedor.nombre_vendedor, vendedor.id_vendedor)

        # Precarga el vendedor si quien esta logueado tiene un vinculo directo con uno
        # (Usuario.id_vendedor_usuario, solo se asigna para usuarios con rol VENDEDOR --
        # ver UsuarioService._resolver_vinculo_vendedor): el caso mas comun es que quien
        # factura sea el propio vendedor, y antes tenia que elegirse a mano en cada
        # factura (auditoria UX de facturacion, cajero). No pisa la seleccion si ese
        # vendedor no esta en la lista (inactivo, o el usuario no tiene vinculo).
        usuario_actual = self.session.get(Usuario, self.id_usuario) if self.id_usuario is not None else None
        if usuario_actual is not None and usuario_actual.id_vendedor_usuario is not None:
            indice = self.vendedor_combo.findData(usuario_actual.id_vendedor_usuario)
            if indice >= 0:
                self.vendedor_combo.setCurrentIndex(indice)

    # ── Condicion de pago ──────────────────────────────────────────────────

    def _toggle_credito(self) -> None:
        es_credito = self.condicion_combo.currentData() == "credito"
        if es_credito and self.pagos:
            # credito no admite pagos al emitir (VentaService.emitir_factura los rechaza) --
            # se descartan las formas de pago que se hayan cargado mientras era contado.
            self.pagos = []
        if es_credito:
            self._id_autorizador_vuelto = None
            self._referencia_vuelto = None
            self.metodo_vuelto_combo.setCurrentIndex(0)
        self.tabs.setTabEnabled(self._idx_tab_pagos, not es_credito)
        if es_credito and self.tabs.currentIndex() == self._idx_tab_pagos:
            self.tabs.setCurrentIndex(0)  # dispara _on_tab_cambiada, que ya actualiza el boton
        else:
            self._actualizar_boton_footer()
        self._refrescar_tabla_pagos()  # tambien deja btn_emitir en el estado correcto
        self._on_cliente_cambiado()  # tambien recalcula vencimiento_input y la alerta

    # ── Producto: busqueda server-side con debounce ─────────────────────────

    def _cargar_productos(self) -> None:
        self._buscar_productos(None)

    def _buscar_productos(self, texto: str | None) -> None:
        resultado = ProductoService.buscar(
            self.session, texto=texto, solo_con_stock=True, por_pagina=LIMITE_CATALOGO, id_usuario=self.id_usuario
        )
        self._productos = [p for p in resultado["items"] if (p.estado_producto or "ACTIVO") == "ACTIVO"]
        self._poblar_combo_productos(self._productos)

    def _poblar_combo_productos(self, productos: list) -> None:
        self.producto_combo.blockSignals(True)
        self.producto_combo.clear()
        if not productos:
            self.producto_combo.addItem("Sin resultados", None)
        for producto in productos:
            etiqueta = f"{producto.cod_producto} - {producto.nombre_producto} (stock: {producto.cantidad_unidad:g})"
            self.producto_combo.addItem(etiqueta, producto.id_producto)
        self.producto_combo.blockSignals(False)
        self.producto_combo.setEnabled(bool(productos))
        self._on_producto_cambiado()

    def _filtrar_productos(self, texto: str) -> None:
        if not hasattr(self, "_timer_busqueda_producto"):
            self._timer_busqueda_producto = QTimer(self)
            self._timer_busqueda_producto.setSingleShot(True)
            self._timer_busqueda_producto.timeout.connect(
                lambda: self._buscar_productos(self.producto_buscar_input.text().strip() or None)
            )
        self._timer_busqueda_producto.start(DEBOUNCE_BUSQUEDA_MS)

    def _on_producto_buscar_return_pressed(self) -> None:
        if hasattr(self, "_timer_busqueda_producto"):
            self._timer_busqueda_producto.stop()
        self._buscar_productos(self.producto_buscar_input.text().strip() or None)
        if self.producto_combo.currentData() is not None:
            self.cantidad_input.setFocus()
            self.cantidad_input.selectAll()

    def _on_producto_cambiado(self) -> None:
        id_producto = self.producto_combo.currentData()
        self.cantidad_input.setValue(1)
        if id_producto is None:
            self.precio_input.setValue(0)
            self._precio_lista_actual = None
            return
        precio = PrecioService.obtener_precio(self.session, id_producto, id_usuario=self.id_usuario)
        self._precio_lista_actual = float(precio.precio_venta) if precio else None
        self.precio_input.setValue(self._precio_lista_actual or 0)

    # ── Carrito ────────────────────────────────────────────────────────────

    def _agregar_item(self) -> None:
        id_producto = self.producto_combo.currentData()
        if id_producto is None:
            QMessageBox.warning(self, "Producto requerido", "Seleccione un producto para agregar.")
            return
        cantidad = self.cantidad_input.value()
        precio = self.precio_input.value()
        if cantidad <= 0:
            QMessageBox.warning(self, "Cantidad inválida", "La cantidad debe ser mayor a cero.")
            return
        if precio <= 0:
            QMessageBox.warning(self, "Precio inválido", "El precio unitario debe ser mayor a cero.")
            return

        # Bloqueo proactivo de stock (hallazgo #5 de la auditoria de facturacion): el
        # stock ya se mostraba en el combo pero no se validaba hasta el submit final --
        # ahora se avisa apenas se intenta agregar mas de lo disponible, sumando lo que
        # ya este en el carrito para el mismo producto (varias lineas del mismo item
        # cuentan juntas). Solo informativo si el producto no esta en self._productos
        # (busqueda vieja/stale) -- el backend (VentaService.emitir_factura) vuelve a
        # validar todo con lock real, esto no lo reemplaza.
        producto_seleccionado = next((p for p in self._productos if p.id_producto == id_producto), None)
        if producto_seleccionado is not None:
            cantidad_en_carrito = sum(it["cantidad"] for it in self.items if it["id_producto"] == id_producto)
            stock_disponible = float(producto_seleccionado.cantidad_unidad)
            if cantidad_en_carrito + cantidad > stock_disponible:
                QMessageBox.warning(
                    self,
                    "Stock insuficiente",
                    f"Stock disponible de '{producto_seleccionado.nombre_producto}': {stock_disponible:,.2f}."
                    + (f" Ya tiene {cantidad_en_carrito:,.2f} en el carrito." if cantidad_en_carrito > 0 else ""),
                )
                return

        nombre_producto = self.producto_combo.currentText()
        nota = self.nota_item_input.text().strip() or None
        precio_lista = self._precio_lista_actual

        # Misma linea que una ya agregada (mismo producto, precio y nota): suma cantidad en
        # vez de crear una fila duplicada. Si el precio o la nota difieren, se agrega como
        # linea separada -- puede ser una venta legitima del mismo producto a dos precios
        # distintos en la misma factura (ej. promo + regular).
        existente = next(
            (
                it
                for it in self.items
                if it["id_producto"] == id_producto
                and abs(it["precio_unitario"] - precio) < 0.0001
                and it["observaciones_item"] == nota
            ),
            None,
        )
        if existente is not None:
            existente["cantidad"] += cantidad
        else:
            self.items.append(
                {
                    "id_producto": id_producto,
                    "nombre_producto": nombre_producto,
                    "cantidad": cantidad,
                    "precio_unitario": precio,
                    "observaciones_item": nota,
                    "precio_lista": precio_lista,
                }
            )
        self._refrescar_tabla_items()
        self.producto_buscar_input.clear()
        self.nota_item_input.clear()
        # Vuelve el foco a la busqueda para el siguiente item sin tocar el mouse --
        # cierra el ciclo escaneo/tipeo -> agregar -> escaneo/tipeo (auditoria UX de
        # facturacion, cajero).
        self.producto_buscar_input.setFocus()

    def _quitar_item(self, indice: int) -> None:
        del self.items[indice]
        self._refrescar_tabla_items()

    def _refrescar_tabla_items(self) -> None:
        self.tabla_items.setRowCount(len(self.items))
        total = 0.0
        for fila, item in enumerate(self.items):
            subtotal = item["cantidad"] * item["precio_unitario"]
            total += subtotal

            item_nombre = QTableWidgetItem(item["nombre_producto"])
            if item["observaciones_item"]:
                item_nombre.setToolTip(item["observaciones_item"])
            self.tabla_items.setItem(fila, 0, item_nombre)
            item_cant = QTableWidgetItem(f"{item['cantidad']:,.2f}")
            item_cant.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla_items.setItem(fila, 1, item_cant)
            item_precio = QTableWidgetItem(f"${item['precio_unitario']:,.2f}")
            item_precio.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            precio_lista = item.get("precio_lista")
            if precio_lista is not None and item["precio_unitario"] < precio_lista:
                item_precio.setForeground(Qt.GlobalColor.red)
                item_precio.setToolTip(f"Precio de lista: ${precio_lista:,.2f} -- requiere autorizacion")
            self.tabla_items.setItem(fila, 2, item_precio)
            item_subtotal = QTableWidgetItem(f"${subtotal:,.2f}")
            item_subtotal.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla_items.setItem(fila, 3, item_subtotal)

            btn_quitar = QPushButton()
            btn_quitar.setObjectName("BtnQuitar")
            btn_quitar.setIcon(qta.icon("fa5s.trash-alt", color=COLOR_DANGER))
            btn_quitar.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_quitar.setToolTip("Quitar de la factura")
            btn_quitar.clicked.connect(lambda checked, i=fila: self._quitar_item(i))
            self.tabla_items.setCellWidget(fila, 4, btn_quitar)

        descuento = self.descuento_input.value()
        subtotal_con_descuento = max(total - descuento, 0.0)
        monto_iva = self._calcular_iva(subtotal_con_descuento)
        if descuento > 0 or monto_iva > 0:
            partes = [f"Total: ${total:,.2f}"]
            if descuento > 0:
                partes.append(f"− ${descuento:,.2f}")
            if monto_iva > 0:
                partes.append(f"+ ${monto_iva:,.2f} IVA")
            self.lbl_total.setText(" ".join(partes) + f" = ${subtotal_con_descuento + monto_iva:,.2f}")
        else:
            self.lbl_total.setText(f"Total: ${total:,.2f}")

        # El total de la factura (carrito - descuento + IVA) es justo lo que la pestana de
        # Formas de Pago necesita mostrar como "Total factura" -- sin este refresco
        # quedaba congelado en $0.00 (el valor al construir el dialogo, antes de agregar
        # ningun producto).
        self._refrescar_tabla_pagos()

    # ── Validación / datos ────────────────────────────────────────────────

    def _requiere_autorizacion_descuento(self) -> bool:
        hay_precio_bajo_lista = any(
            it.get("precio_lista") is not None and it["precio_unitario"] < it["precio_lista"] for it in self.items
        )
        return hay_precio_bajo_lista or self.descuento_input.value() > 0

    def _validar_datos_basicos(self) -> bool:
        """Cliente/vendedor/carrito -- lo mismo que valida el paso "Siguiente" antes de
        pasar a formas de pago, y lo primero que vuelve a validar "Facturar" (el carrito
        pudo cambiar mientras el usuario estaba en la otra pestana)."""
        if self.cliente_combo.currentData() is None:
            QMessageBox.warning(self, "Cliente requerido", "Seleccione un cliente para la factura.")
            return False
        if self.vendedor_combo.currentData() is None:
            QMessageBox.warning(self, "Vendedor requerido", "Seleccione el vendedor de esta factura.")
            return False
        if not self.items:
            QMessageBox.warning(self, "Factura vacía", "Agregue al menos un producto a la factura.")
            return False
        return True

    def _en_paso_siguiente(self) -> bool:
        """Contado tiene dos pasos (Factura -> Formas de Pago); credito emite directo
        desde la unica pestana habilitada. Determina si el boton principal debe decir
        "Siguiente" (solo avanza de pestana) o "Facturar" (emite de verdad)."""
        es_contado = self.condicion_combo.currentData() == "contado"
        return es_contado and self.tabs.currentIndex() != self._idx_tab_pagos

    def _actualizar_boton_footer(self) -> None:
        if self._en_paso_siguiente():
            self.btn_emitir.setText("Siguiente")
            self.btn_emitir.setIcon(qta.icon("fa5s.arrow-right", color="#FFFFFF"))
        else:
            self.btn_emitir.setText("Facturar")
            self.btn_emitir.setIcon(qta.icon("fa5s.check", color="#FFFFFF"))

    def _on_tab_cambiada(self, _index: int) -> None:
        self._actualizar_boton_footer()
        self._actualizar_alerta_credito()

    def _on_click_boton_principal(self) -> None:
        if self._en_paso_siguiente():
            self._ir_a_formas_de_pago()
        else:
            self._validar_y_aceptar()

    def _ir_a_formas_de_pago(self) -> None:
        if not self._validar_datos_basicos():
            return
        self.tabs.setCurrentIndex(self._idx_tab_pagos)

    def _validar_y_aceptar(self) -> None:
        if not self._validar_datos_basicos():
            return
        es_contado = self.condicion_combo.currentData() == "contado"
        es_credito = self.condicion_combo.currentData() == "credito"
        if es_contado and not self.pagos:
            self.tabs.setCurrentIndex(self._idx_tab_pagos)
            QMessageBox.warning(
                self, "Forma de pago requerida", "Agregue al menos una forma de pago para facturar de contado."
            )
            return
        if es_contado and not self._pagos_cubren_total():
            self.tabs.setCurrentIndex(self._idx_tab_pagos)
            QMessageBox.warning(
                self, "Pago incompleto", "Las formas de pago agregadas no cubren el total de la factura."
            )
            return

        self._id_autorizador_descuento = None
        self._motivo_descuento = None
        if self._requiere_autorizacion_descuento():
            mensaje = (
                "Esta factura tiene un item por debajo del precio de lista y/o un "
                "descuento manual. Un supervisor debe autorizarla."
            )
            dialogo = AutorizacionDialog(
                self.session,
                recurso="descuentos",
                accion="crear",
                mensaje=mensaje,
                titulo="Autorización de descuento requerida",
                motivo_label="Motivo del descuento",
                parent=self,
            )
            if dialogo.exec() != QDialog.DialogCode.Accepted or dialogo.usuario_autorizador is None:
                return
            self._id_autorizador_descuento = dialogo.usuario_autorizador.id_usuario
            self._motivo_descuento = dialogo.motivo

        self._id_autorizador_dias_credito = None
        self._motivo_dias_credito = None
        if es_credito and not self.chk_dias_configurados.isChecked():
            mensaje = (
                "Esta factura usa días de crédito distintos a los configurados para el "
                "cliente. Un supervisor debe autorizarla."
            )
            dialogo = AutorizacionDialog(
                self.session,
                recurso="creditos",
                accion="crear",
                mensaje=mensaje,
                titulo="Autorización de días de crédito requerida",
                motivo_label="Motivo del cambio de días de crédito",
                parent=self,
            )
            if dialogo.exec() != QDialog.DialogCode.Accepted or dialogo.usuario_autorizador is None:
                return
            self._id_autorizador_dias_credito = dialogo.usuario_autorizador.id_usuario
            self._motivo_dias_credito = dialogo.motivo

        self._id_autorizador_vuelto = None
        self._referencia_vuelto = None
        if es_contado:
            monto_vuelto = max(
                sum(self._convertir_pago_a_usd(p) for p in self.pagos) - self._total_factura_actual(), 0.0
            )
            if monto_vuelto > 0.005:
                metodo_vuelto = self.metodo_vuelto_combo.currentData()
                origen_vuelto = self.origen_vuelto_combo.currentData()
                if origen_vuelto is None:
                    self.tabs.setCurrentIndex(self._idx_tab_pagos)
                    QMessageBox.warning(
                        self,
                        "Origen de vuelto requerido",
                        "No hay caja abierta ni cuenta bancaria activa disponible para el vuelto.",
                    )
                    return
                if metodo_vuelto != "efectivo":
                    mensaje = (
                        f"Esta factura tiene un vuelto de ${monto_vuelto:,.2f} por "
                        f"{'pago móvil' if metodo_vuelto == 'pago_movil' else 'transferencia'}. "
                        "Un supervisor debe autorizarlo e indicar la referencia bancaria."
                    )
                    dialogo = AutorizacionDialog(
                        self.session,
                        recurso="vueltos_bancarios",
                        accion="crear",
                        mensaje=mensaje,
                        titulo="Autorización de vuelto bancario requerida",
                        motivo_label="Número de referencia bancaria",
                        motivo_min_length=4,
                        motivo_max_length=50,
                        parent=self,
                    )
                    if dialogo.exec() != QDialog.DialogCode.Accepted or dialogo.usuario_autorizador is None:
                        return
                    self._id_autorizador_vuelto = dialogo.usuario_autorizador.id_usuario
                    self._referencia_vuelto = dialogo.motivo

        # Se emite ACA, no en el caller (ver self.factura_emitida) -- si emitir_factura
        # falla (una condicion cambio mientras se armaba la factura: stock consumido por
        # otra venta, limite de credito ya copado, etc.) el dialogo se queda abierto con
        # todo lo cargado intacto en vez de perderse. setEnabled(False) evita un segundo
        # click mientras la llamada esta en curso; setOverrideCursor dan feedback visual
        # de que algo esta pasando durante la llamada sincrona a la base de datos
        # (hallazgo #7 de la auditoria de facturacion) -- no reemplaza un QThread real
        # (el resto de la ventana sigue sin responder), pero evita que parezca colgada.
        self.btn_emitir.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.factura_emitida = VentaService.emitir_factura(
                self.session, id_usuario=self.id_usuario, **self.get_data()
            )
        except ValueError as exc:
            self.session.rollback()
            QMessageBox.warning(self, "No se pudo emitir la factura", str(exc))
            return
        except PermisoDenegadoError:
            self.session.rollback()
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para emitir facturas.")
            return
        except Exception:
            self.session.rollback()
            logger.exception("Fallo al emitir factura")
            QMessageBox.critical(self, "Error", "No se pudo emitir la factura.")
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_emitir.setEnabled(True)

        self.accept()

    def get_data(self) -> dict:
        es_credito = self.condicion_combo.currentData() == "credito"
        usar_dias_configurados = self.chk_dias_configurados.isChecked()
        # El vuelto solo aplica a contado y solo cuando efectivamente sobra algo --
        # VentaService.emitir_factura() rechaza metodo_vuelto si monto_vuelto es 0 (ver
        # migrations/0026_vuelto_factura.sql / _validar_y_aceptar), asi que estas claves
        # deben quedar todas en None para el caso comun (pago exacto, sin vuelto).
        monto_vuelto = (
            max(sum(self._convertir_pago_a_usd(p) for p in self.pagos) - self._total_factura_actual(), 0.0)
            if not es_credito
            else 0.0
        )
        hay_vuelto = monto_vuelto > 0.005
        metodo_vuelto = self.metodo_vuelto_combo.currentData() if hay_vuelto else None
        origen_vuelto = self.origen_vuelto_combo.currentData() if hay_vuelto else None
        return {
            "id_cliente": self.cliente_combo.currentData(),
            "id_vendedor": self.vendedor_combo.currentData(),
            "condicion_pago": self.condicion_combo.currentData(),
            # fecha_vencimiento queda en None: VentaService.emitir_factura() la calcula a
            # partir de dias_credito_personalizados/cliente.dias_credito -- es la unica
            # fuente de verdad, evita divergencias de fecha entre UI y servidor.
            "fecha_vencimiento": None,
            "observaciones": self.observaciones_input.text().strip() or None,
            "monto_descuento": self.descuento_input.value(),
            "motivo_descuento": self._motivo_descuento,
            "id_autorizador_descuento": self._id_autorizador_descuento,
            "dias_credito_personalizados": (
                self.dias_credito_custom_input.value() if es_credito and not usar_dias_configurados else None
            ),
            "motivo_dias_credito": self._motivo_dias_credito,
            "id_autorizador_dias_credito": self._id_autorizador_dias_credito,
            "metodo_vuelto": metodo_vuelto,
            "id_caja_vuelto": origen_vuelto[1] if origen_vuelto and metodo_vuelto == "efectivo" else None,
            "id_cuenta_bancaria_vuelto": origen_vuelto[1] if origen_vuelto and metodo_vuelto != "efectivo" else None,
            "referencia_vuelto": self._referencia_vuelto if hay_vuelto else None,
            "id_autorizador_vuelto": self._id_autorizador_vuelto if hay_vuelto else None,
            "pagos": self.pagos if not es_credito else [],
            "items": [
                {
                    "id_producto": it["id_producto"],
                    "cantidad": it["cantidad"],
                    "precio_unitario": it["precio_unitario"],
                    "observaciones": it["observaciones_item"],
                }
                for it in self.items
            ],
        }
