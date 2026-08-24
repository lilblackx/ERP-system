"""Dialogo de emision de una nueva factura de venta (estilo carrito): cabecera
(cliente, vendedor, condicion de pago) + lineas de productos agregadas una a una.
Mismo patron visual que cliente_form_dialog.py/producto_form_dialog.py (paleta y
tipografia de app/ui/styles.py); a diferencia de esos dos, permite redimensionar
porque la tabla del carrito se beneficia de espacio vertical extra."""

import qtawesome as qta
from PySide6.QtCore import QDate, QSize, Qt
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
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from app.services.clientes import list_clientes
from app.services.inventario import PrecioService, ProductoService
from app.services.vendedores import VendedorService
from app.ui.styles import (
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_PRIMARY,
    COLOR_PRIMARY_DARK,
    COLOR_PRIMARY_LIGHT,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    FONT_FAMILY,
    TABLE_QSS,
)

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
    border: 1px solid #CBD5E1;
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
    border: 1px solid #CBD5E1;
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
    background-color: #F1F5F9;
    color: #475569;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#BtnSecondary:hover {{
    background-color: #E2E8F0;
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
"""


class FacturaFormDialog(QDialog):
    """Dialogo de nueva factura: cabecera + carrito de productos.

    A diferencia de ClienteFormDialog/ProductoFormDialog, las listas de
    cliente/producto se cargan una sola vez al abrir (catalogos de tamano
    moderado, no paginados todavia -- D-01 sigue pendiente para clientes) y se
    filtran del lado del cliente con una caja de busqueda, en vez de hacer un
    roundtrip a la base por cada tecla.
    """

    def __init__(self, session: Session, id_usuario: int | None, parent=None):
        super().__init__(parent)
        self.session = session
        self.id_usuario = id_usuario
        self.items: list[dict] = []

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

    # ── Construcción de la UI ─────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        root.addWidget(self._make_header())
        root.addWidget(self._make_card_cabecera())
        root.addWidget(self._make_card_carrito(), stretch=1)
        root.addLayout(self._make_footer())

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
        return w

    def _make_card_cabecera(self) -> QWidget:
        card = QWidget()
        card.setObjectName("SectionCard")
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
        lbl_vendedor = QLabel("Vendedor")
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
        self.observaciones_input.setFixedHeight(32)
        grid.addWidget(lbl_obs, 3, 2)
        grid.addWidget(self.observaciones_input, 4, 2)

        layout.addLayout(grid)
        return card

    def _make_card_carrito(self) -> QWidget:
        card = QWidget()
        card.setObjectName("SectionCard")
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
        self.precio_input.setRange(0, 999999999.99)
        self.precio_input.setDecimals(2)
        self.precio_input.setPrefix("$ ")
        self.precio_input.setFixedHeight(32)
        self.precio_input.setFixedWidth(130)

        btn_agregar = QPushButton(" Agregar")
        btn_agregar.setObjectName("BtnAgregar")
        btn_agregar.setIcon(qta.icon("fa5s.cart-plus", color=COLOR_PRIMARY))
        btn_agregar.setFixedHeight(32)
        btn_agregar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_agregar.clicked.connect(self._agregar_item)

        fila_agregar.addWidget(self.producto_buscar_input, stretch=1)
        fila_agregar.addWidget(self.producto_combo, stretch=2)
        fila_agregar.addWidget(self.cantidad_input)
        fila_agregar.addWidget(self.precio_input)
        fila_agregar.addWidget(btn_agregar)
        layout.addLayout(fila_agregar)

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
        layout.addWidget(self.tabla_items, stretch=1)

        fila_total = QHBoxLayout()
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
        self.btn_cancelar.clicked.connect(self.reject)

        self.btn_emitir = QPushButton("Emitir Factura")
        self.btn_emitir.setIcon(qta.icon("fa5s.check", color="#FFFFFF"))
        self.btn_emitir.setObjectName("BtnPrimary")
        self.btn_emitir.setFixedHeight(36)
        self.btn_emitir.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_emitir.clicked.connect(self._validar_y_aceptar)

        footer.addWidget(self.btn_cancelar)
        footer.addWidget(self.btn_emitir)
        return footer

    # ── Cliente: carga + filtro local ─────────────────────────────────────

    def _cargar_clientes(self) -> None:
        todos = list_clientes(self.session, None, id_usuario=self.id_usuario)
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
        self._on_cliente_cambiado()

    def _filtrar_clientes(self, texto: str) -> None:
        texto = texto.strip().lower()
        if not texto:
            self._poblar_combo_clientes(self._clientes)
            return
        filtrados = [
            c
            for c in self._clientes
            if texto in (c.nombre_razon_social or "").lower() or texto in (c.identificacion_cliente or "").lower()
        ]
        self._poblar_combo_clientes(filtrados)

    def _on_cliente_cambiado(self) -> None:
        if self.condicion_combo.currentData() != "credito":
            return
        id_cliente = self.cliente_combo.currentData()
        cliente = next((c for c in self._clientes if c.id_cliente == id_cliente), None)
        dias_credito = (cliente.dias_credito if cliente else None) or 30
        self.vencimiento_input.setDate(QDate.currentDate().addDays(dias_credito))

    # ── Vendedor ───────────────────────────────────────────────────────────

    def _cargar_vendedores(self) -> None:
        self.vendedor_combo.addItem("Sin vendedor", None)
        for vendedor in VendedorService.listar(self.session, id_usuario=self.id_usuario):
            if (vendedor.estado_vendedor or "ACTIVO") == "ACTIVO":
                self.vendedor_combo.addItem(vendedor.nombre_vendedor, vendedor.id_vendedor)

    # ── Condicion de pago ──────────────────────────────────────────────────

    def _toggle_credito(self) -> None:
        es_credito = self.condicion_combo.currentData() == "credito"
        self.vencimiento_input.setEnabled(es_credito)
        if es_credito:
            self._on_cliente_cambiado()

    # ── Producto: carga + filtro local ────────────────────────────────────

    def _cargar_productos(self) -> None:
        resultado = ProductoService.buscar(
            self.session, solo_con_stock=True, por_pagina=500, id_usuario=self.id_usuario
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
        self._on_producto_cambiado()

    def _filtrar_productos(self, texto: str) -> None:
        texto = texto.strip().lower()
        if not texto:
            self._poblar_combo_productos(self._productos)
            return
        filtrados = [
            p
            for p in self._productos
            if texto in (p.nombre_producto or "").lower() or texto in (p.cod_producto or "").lower()
        ]
        self._poblar_combo_productos(filtrados)

    def _on_producto_cambiado(self) -> None:
        id_producto = self.producto_combo.currentData()
        self.cantidad_input.setValue(1)
        if id_producto is None:
            self.precio_input.setValue(0)
            return
        precio = PrecioService.obtener_precio(self.session, id_producto, id_usuario=self.id_usuario)
        self.precio_input.setValue(float(precio.precio_venta) if precio else 0)

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
        self.items.append(
            {
                "id_producto": id_producto,
                "nombre_producto": nombre_producto,
                "cantidad": cantidad,
                "precio_unitario": precio,
            }
        )
        self._refrescar_tabla_items()
        self.producto_buscar_input.clear()

    def _quitar_item(self, indice: int) -> None:
        del self.items[indice]
        self._refrescar_tabla_items()

    def _refrescar_tabla_items(self) -> None:
        self.tabla_items.setRowCount(len(self.items))
        total = 0.0
        for fila, item in enumerate(self.items):
            subtotal = item["cantidad"] * item["precio_unitario"]
            total += subtotal

            self.tabla_items.setItem(fila, 0, QTableWidgetItem(item["nombre_producto"]))
            item_cant = QTableWidgetItem(f"{item['cantidad']:,.2f}")
            item_cant.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla_items.setItem(fila, 1, item_cant)
            item_precio = QTableWidgetItem(f"${item['precio_unitario']:,.2f}")
            item_precio.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
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

        self.lbl_total.setText(f"Total: ${total:,.2f}")

    # ── Validación / datos ────────────────────────────────────────────────

    def _validar_y_aceptar(self) -> None:
        if self.cliente_combo.currentData() is None:
            QMessageBox.warning(self, "Cliente requerido", "Seleccione un cliente para la factura.")
            return
        if not self.items:
            QMessageBox.warning(self, "Factura vacía", "Agregue al menos un producto a la factura.")
            return
        self.accept()

    def get_data(self) -> dict:
        es_credito = self.condicion_combo.currentData() == "credito"
        return {
            "id_cliente": self.cliente_combo.currentData(),
            "id_vendedor": self.vendedor_combo.currentData(),
            "condicion_pago": self.condicion_combo.currentData(),
            "fecha_vencimiento": self.vencimiento_input.date().toPython() if es_credito else None,
            "observaciones": self.observaciones_input.text().strip() or None,
            "items": [
                {"id_producto": it["id_producto"], "cantidad": it["cantidad"], "precio_unitario": it["precio_unitario"]}
                for it in self.items
            ],
        }
