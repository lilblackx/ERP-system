"""Dialogo de emision de una nueva factura de venta (estilo carrito): cabecera
(cliente, vendedor, condicion de pago) + lineas de productos agregadas una a una.
Mismo patron visual que cliente_form_dialog.py/producto_form_dialog.py (paleta y
tipografia de app/ui/styles.py); a diferencia de esos dos, permite redimensionar
porque la tabla del carrito se beneficia de espacio vertical extra."""

import qtawesome as qta
from PySide6.QtCore import QDate, QSize, Qt, QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from app.services.clientes import list_clientes
from app.services.inventario import PrecioService, ProductoService
from app.services.permisos import PermisoDenegadoError
from app.services.tasas import TasaService
from app.services.vendedores import VendedorService
from app.services.ventas import VentaService
from app.ui.autorizacion_dialog import AutorizacionDescuentoDialog
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
    TABLE_QSS,
    aplicar_sombra,
)

_ETIQUETAS_METODO = {valor: etiqueta for etiqueta, valor in METODOS_PAGO}
_ETIQUETAS_MONEDA = {valor: etiqueta for etiqueta, valor in MONEDAS}

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
QLineEdit, QComboBox, QDoubleSpinBox, QDateEdit {{
    background-color: #FFFFFF;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
    min-height: 20px;
}}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QDateEdit:focus {{
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
QTabWidget::pane {{
    border: none;
    top: -1px;
}}
QTabBar::tab {{
    background-color: transparent;
    color: {COLOR_TEXT_MUTED};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 4px;
    margin-right: 22px;
    font-size: 13px;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    color: {COLOR_PRIMARY};
    border-bottom: 2px solid {COLOR_PRIMARY};
}}
QTabBar::tab:disabled {{
    color: #CBD5E1;
}}
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
        self._precio_lista_actual: float | None = None
        self._id_autorizador_descuento: int | None = None
        self._motivo_descuento: str | None = None
        self._tasa_vigente: dict | None = None

        self.setWindowTitle("Nueva Factura")
        self.resize(920, 700)
        self.setMinimumSize(820, 600)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._clientes: list = []
        self._productos: list = []

        self._build_ui()
        self._cargar_clientes()
        self._cargar_vendedores()
        self._cargar_productos()
        self._cargar_tasa_vigente()
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
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._make_card_cabecera())
        layout.addWidget(self._make_card_carrito(), stretch=1)
        return page

    def _make_tab_pagos(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
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

        return self.card_pagos

    def _agregar_pago(self) -> None:
        dialogo = PagoLineaDialog(self.session, self.id_usuario, parent=self)
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
        self._actualizar_alerta_credito()

    def _total_factura_actual(self) -> float:
        total = sum(it["cantidad"] * it["precio_unitario"] for it in self.items)
        return max(total - self.descuento_input.value(), 0.0)

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

        self.precio_input = QDoubleSpinBox()
        self.precio_input.setRange(0.01, 999999999.99)
        self.precio_input.setDecimals(2)
        self.precio_input.setPrefix("$ ")
        self.precio_input.setFixedHeight(32)
        self.precio_input.setFixedWidth(130)

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
        layout.addWidget(self.nota_item_input)

        self.tabla_items = QTableWidget(0, 5)
        self.tabla_items.setHorizontalHeaderLabels(["Producto", "Cantidad", "Precio Unit.", "Subtotal", ""])
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
        todos = list_clientes(self.session, texto, id_usuario=self.id_usuario, limite=LIMITE_CATALOGO)
        self._clientes = [c for c in todos if (c.estado_cliente or "ACTIVO") == "ACTIVO"]
        self._poblar_combo_clientes(self._clientes)

    def _poblar_combo_clientes(self, clientes: list) -> None:
        self.cliente_combo.blockSignals(True)
        self.cliente_combo.clear()
        if not clientes:
            self.cliente_combo.addItem("Sin resultados", None)
        for cliente in clientes:
            etiqueta = f"{cliente.nombre_razon_social} ({cliente.identificacion_cliente or 's/i'})"
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

    def _on_cliente_cambiado(self) -> None:
        if self.condicion_combo.currentData() == "credito":
            id_cliente = self.cliente_combo.currentData()
            cliente = next((c for c in self._clientes if c.id_cliente == id_cliente), None)
            dias_credito = (cliente.dias_credito if cliente else None) or 30
            self.vencimiento_input.setDate(QDate.currentDate().addDays(dias_credito))
        self._actualizar_alerta_credito()

    def _actualizar_alerta_credito(self) -> None:
        """Bloqueo visual proactivo (hallazgo #12 del audit de facturacion): antes de que
        el usuario arme todo el carrito y recien se entere del limite de credito al dar
        "Emitir", se avisa apenas el total supera lo disponible. Solo informativo -- el
        backend (VentaService.emitir_factura) vuelve a validar todo, IVA incluido, que
        aca no se conoce sin llamar al servicio de nuevo.

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

        try:
            info = VentaService.consultar_limite_disponible(self.session, id_cliente, id_usuario=self.id_usuario)
        except (ValueError, PermisoDenegadoError):
            self.lbl_alerta_credito.hide()
            self.btn_emitir.setEnabled(True)
            return

        total_carrito = sum(it["cantidad"] * it["precio_unitario"] for it in self.items)
        total_carrito -= self.descuento_input.value()
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
        vendedores = [
            v
            for v in VendedorService.listar(self.session, id_usuario=self.id_usuario)
            if (v.estado_vendedor or "ACTIVO") == "ACTIVO"
        ]
        if not vendedores:
            self.vendedor_combo.addItem("Sin vendedores activos", None)
        for vendedor in vendedores:
            self.vendedor_combo.addItem(vendedor.nombre_vendedor, vendedor.id_vendedor)

    # ── Condicion de pago ──────────────────────────────────────────────────

    def _toggle_credito(self) -> None:
        es_credito = self.condicion_combo.currentData() == "credito"
        self.vencimiento_input.setEnabled(es_credito)
        if es_credito and self.pagos:
            # credito no admite pagos al emitir (VentaService.emitir_factura los rechaza) --
            # se descartan las formas de pago que se hayan cargado mientras era contado.
            self.pagos = []
        self.tabs.setTabEnabled(self._idx_tab_pagos, not es_credito)
        if es_credito and self.tabs.currentIndex() == self._idx_tab_pagos:
            self.tabs.setCurrentIndex(0)  # dispara _on_tab_cambiada, que ya actualiza el boton
        else:
            self._actualizar_boton_footer()
        self._refrescar_tabla_pagos()  # tambien deja btn_emitir en el estado correcto
        if es_credito:
            self._on_cliente_cambiado()

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
        if descuento > 0:
            self.lbl_total.setText(f"Total: ${total:,.2f} − ${descuento:,.2f} = ${max(total - descuento, 0):,.2f}")
        else:
            self.lbl_total.setText(f"Total: ${total:,.2f}")

        # El total de la factura (carrito - descuento) es justo lo que la pestana de
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
            dialogo = AutorizacionDescuentoDialog(self.session, mensaje, parent=self)
            if dialogo.exec() != QDialog.DialogCode.Accepted or dialogo.usuario_autorizador is None:
                return
            self._id_autorizador_descuento = dialogo.usuario_autorizador.id_usuario
            self._motivo_descuento = dialogo.motivo

        self.accept()

    def get_data(self) -> dict:
        es_credito = self.condicion_combo.currentData() == "credito"
        return {
            "id_cliente": self.cliente_combo.currentData(),
            "id_vendedor": self.vendedor_combo.currentData(),
            "condicion_pago": self.condicion_combo.currentData(),
            "fecha_vencimiento": self.vencimiento_input.date().toPython() if es_credito else None,
            "observaciones": self.observaciones_input.text().strip() or None,
            "monto_descuento": self.descuento_input.value(),
            "motivo_descuento": self._motivo_descuento,
            "id_autorizador_descuento": self._id_autorizador_descuento,
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
