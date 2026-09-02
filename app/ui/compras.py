"""Modulo unico de Compras: flujo OC -> NR -> Compra (el Pago vive aparte, ver mas abajo).
El modulo anterior de "compra directa" (compras_panel.py/compra_form_dialog.py/
compra_detalle_dialog.py) se elimino para no tener dos entradas de Compras en el menu --
el backend que usaba (CompraService.registrar_compra/anular_compra/obtener_compra/
listar_compras) sigue existiendo intacto en app/services/compras.py (con sus tests), solo
que hoy ninguna UI lo llama; CompraService.crear_compra_desde_oc (usado aca) es una
funcion aparte.

ComprasView agrupa 3 pestanas (Ordenes de Compra, Recepciones, Facturas) que cubren el
ciclo de compra: crear OC -> recibir mercancia (parcial, con rechazo) -> facturar contra
lo recibido. La pestana de CxP/pago (que vivio aca en un momento) se movio a su propio
modulo -- ver app/ui/cuentas_por_pagar_panel.py (CuentasPorPagarPanel), pedido explicito
del usuario de no mezclar "pagar" con "comprar" en la misma pantalla. Mismo patron visual
que el resto de la app (paleta/tipografia de app/ui/styles.py), heredando de QWidget igual
que todos los paneles existentes -- no hay una clase base propia en este proyecto (ver
ClientesPanel/FacturacionPanel, todos QWidget directo)."""

import logging
from decimal import Decimal

import qtawesome as qta
from PySide6.QtCore import QDate, QSize, Qt, QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from app.db.models import CompraOC, NotaDevolucionDetalle, NotaRecepcion, Usuario
from app.services.compra_oc import CompraOCService
from app.services.compras import CompraService
from app.services.inventario import ProductoService
from app.services.nota_recepcion import NotaRecepcionService
from app.services.permisos import PermisoDenegadoError
from app.services.proveedores import ProveedorService
from app.services.usuarios import UsuarioService
from app.ui.message_box import MessageBox
from app.ui.orden_compra_detalle_dialog import OrdenCompraDetalleDialog
from app.ui.pago_linea_dialog import METODOS_PAGO, PagoLineaDialog
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
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
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
    FONT_FAMILY,
    ICON_CHEVRON_DOWN_URL,
    ICON_CHEVRON_UP_URL,
    SEARCH_QSS,
    TABLE_QSS,
    TABS_QSS,
    EstadoBadge,
    aplicar_sombra,
)
from app.ui.toolbar_popups import BotonFiltros

logger = logging.getLogger(__name__)

_ETIQUETAS_METODO = {valor: etiqueta for etiqueta, valor in METODOS_PAGO}
LIMITE_CATALOGO = 50  # mismo criterio D-01 que factura_form_dialog.py
DEBOUNCE_BUSQUEDA_MS = 300
POR_PAGINA = 20

MOTIVOS_DEVOLUCION = [
    "Unidades Defectuosas",
    "No Cumple Especificación",
    "Daño en Tránsito",
]

COLORES_ESTADO_OC = {
    "PENDIENTE": COLOR_WARNING,
    "PARCIAL": COLOR_PRIMARY,
    "COMPLETA": COLOR_SUCCESS,
    "ANULADA": COLOR_DANGER,
}
COLORES_ESTADO_NR = {
    "RECIBIDA": COLOR_SUCCESS,
    "PARCIAL": COLOR_PRIMARY,
    "FACTURADA": COLOR_TEXT_MUTED,
    "ANULADA": COLOR_DANGER,
}
COLORES_ESTADO_COMPRA = {"EMITIDA": COLOR_SUCCESS, "ANULADA": COLOR_DANGER}

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
QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    border: none;
    border-left: 1px solid {COLOR_BORDER};
}}
QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    border: none;
    border-left: 1px solid {COLOR_BORDER};
}}
QDoubleSpinBox::up-arrow {{
    image: url({ICON_CHEVRON_UP_URL});
    width: 10px;
    height: 10px;
}}
QDoubleSpinBox::down-arrow {{
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
"""


def _tabla_lecturas(columnas: list[str]) -> QTableWidget:
    """Tabla de solo lectura (no editable, sin seleccion multiple) -- helper compartido
    por los dialogos de esta pantalla que muestran lineas de una OC/NR con una celda
    editable (spinbox) por fila, mismo estilo que TABLE_QSS del resto de la app."""
    tabla = QTableWidget(0, len(columnas))
    tabla.setHorizontalHeaderLabels(columnas)
    tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tabla.setAlternatingRowColors(True)
    tabla.setShowGrid(False)
    tabla.verticalHeader().setVisible(False)
    tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    tabla.setStyleSheet(TABLE_QSS)
    aplicar_sombra(tabla)
    return tabla


# =============================================================================
# Dialogo: Nueva Orden de Compra
# =============================================================================


class OrdenCompraFormDialog(QDialog):
    """Cabecera (proveedor + fecha estimada) + carrito de productos, mismo patron que
    FacturaFormDialog (factura_form_dialog.py) pero sin pago -- una OC es solo la
    solicitud, el pago llega recien en el paso Compra."""

    def __init__(self, session: Session, id_usuario: int | None, parent=None):
        super().__init__(parent)
        self.session = session
        self.id_usuario = id_usuario
        self.items: list[dict] = []
        self.oc_creada: CompraOC | None = None
        self._proveedores: list = []
        self._productos: list = []

        self.setWindowTitle("Nueva Orden de Compra")
        self.resize(820, 620)
        self.setMinimumSize(760, 560)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()
        self._cargar_proveedores()
        self._cargar_productos()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.file-signature", color=COLOR_PRIMARY).pixmap(QSize(22, 22)))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(38, 38)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        titulos = QVBoxLayout()
        titulos.setSpacing(1)
        lbl_titulo = QLabel("Nueva Orden de Compra")
        lbl_titulo.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        lbl_subtitulo = QLabel("Seleccione el proveedor y agregue los productos solicitados.")
        lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        titulos.addWidget(lbl_titulo)
        titulos.addWidget(lbl_subtitulo)
        header.addWidget(icon_lbl)
        header.addLayout(titulos)
        header.addStretch()
        root.addLayout(header)

        root.addWidget(self._make_card_cabecera())
        root.addWidget(self._make_card_carrito(), stretch=1)
        root.addLayout(self._make_footer())

    def _make_card_cabecera(self) -> QWidget:
        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        titulo = QLabel("DATOS DE LA ORDEN")
        titulo.setProperty("class", "SectionTitle")
        layout.addWidget(titulo)

        grid = QGridLayout()
        grid.setSpacing(8)
        for col in range(2):
            grid.setColumnStretch(col, 1)

        lbl_proveedor = QLabel("Proveedor <span style='color: #DC2626;'>*</span>")
        lbl_proveedor.setProperty("class", "FormLabel")
        self.proveedor_buscar_input = QLineEdit()
        self.proveedor_buscar_input.setPlaceholderText("Buscar proveedor…")
        self.proveedor_buscar_input.setFixedHeight(30)
        self.proveedor_buscar_input.textChanged.connect(self._filtrar_proveedores)
        self.proveedor_combo = QComboBox()
        self.proveedor_combo.setFixedHeight(32)
        grid.addWidget(lbl_proveedor, 0, 0, 1, 2)
        grid.addWidget(self.proveedor_buscar_input, 1, 0, 1, 2)
        grid.addWidget(self.proveedor_combo, 2, 0, 1, 2)

        lbl_fecha = QLabel("Fecha Estimada de Entrega")
        lbl_fecha.setProperty("class", "FormLabel")
        self.fecha_entrega_input = QDateEdit()
        self.fecha_entrega_input.setCalendarPopup(True)
        self.fecha_entrega_input.setDisplayFormat("dd/MM/yyyy")
        self.fecha_entrega_input.setMinimumDate(QDate.currentDate())
        self.fecha_entrega_input.setDate(QDate.currentDate().addDays(7))
        self.fecha_entrega_input.setFixedHeight(32)
        grid.addWidget(lbl_fecha, 3, 0)
        grid.addWidget(self.fecha_entrega_input, 4, 0)

        lbl_obs = QLabel("Observaciones")
        lbl_obs.setProperty("class", "FormLabel")
        self.observaciones_input = QLineEdit()
        self.observaciones_input.setPlaceholderText("Opcional")
        self.observaciones_input.setMaxLength(255)
        self.observaciones_input.setFixedHeight(32)
        grid.addWidget(lbl_obs, 3, 1)
        grid.addWidget(self.observaciones_input, 4, 1)

        layout.addLayout(grid)
        return card

    def _make_card_carrito(self) -> QWidget:
        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        titulo = QLabel("PRODUCTOS SOLICITADOS")
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

        self.tabla_items = _tabla_lecturas(["Producto", "Cantidad", "Precio Unit.", "Subtotal", ""])
        self.tabla_items.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.tabla_items.setColumnWidth(4, 70)
        self.tabla_items.setMinimumHeight(140)
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
        footer.addStretch()
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setObjectName("BtnSecondary")
        btn_cancelar.setFixedHeight(36)
        btn_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancelar.setAutoDefault(False)
        btn_cancelar.clicked.connect(self.reject)
        self.btn_crear = QPushButton("Crear Orden de Compra")
        self.btn_crear.setIcon(qta.icon("fa5s.check", color="#FFFFFF"))
        self.btn_crear.setObjectName("BtnPrimary")
        self.btn_crear.setFixedHeight(36)
        self.btn_crear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_crear.setAutoDefault(False)
        self.btn_crear.clicked.connect(self._validar_y_aceptar)
        footer.addWidget(btn_cancelar)
        footer.addWidget(self.btn_crear)
        return footer

    # ── Proveedor / producto (busqueda server-side, D-01) ───────────────────

    def _cargar_proveedores(self) -> None:
        self._buscar_proveedores(None)

    def _buscar_proveedores(self, texto: str | None) -> None:
        try:
            resultado = ProveedorService.listar(
                self.session,
                texto_busqueda=texto,
                estado_proveedor="ACTIVO",
                id_usuario=self.id_usuario,
                por_pagina=LIMITE_CATALOGO,
            )
            self._proveedores = resultado["items"]
        except PermisoDenegadoError:
            self._proveedores = []
        self.proveedor_combo.blockSignals(True)
        self.proveedor_combo.clear()
        if not self._proveedores:
            self.proveedor_combo.addItem("Sin resultados", None)
        for p in self._proveedores:
            self.proveedor_combo.addItem(p.nombre_razon_social, p.id_proveedor)
        self.proveedor_combo.blockSignals(False)
        self.proveedor_combo.setEnabled(bool(self._proveedores))

    def _filtrar_proveedores(self, texto: str) -> None:
        if not hasattr(self, "_timer_prov"):
            self._timer_prov = QTimer(self)
            self._timer_prov.setSingleShot(True)
            self._timer_prov.timeout.connect(
                lambda: self._buscar_proveedores(self.proveedor_buscar_input.text().strip() or None)
            )
        self._timer_prov.start(DEBOUNCE_BUSQUEDA_MS)

    def _cargar_productos(self) -> None:
        self._buscar_productos(None)

    def _buscar_productos(self, texto: str | None) -> None:
        resultado = ProductoService.buscar(
            self.session, texto=texto, por_pagina=LIMITE_CATALOGO, id_usuario=self.id_usuario
        )
        self._productos = [p for p in resultado["items"] if (p.estado_producto or "ACTIVO") == "ACTIVO"]
        self.producto_combo.blockSignals(True)
        self.producto_combo.clear()
        if not self._productos:
            self.producto_combo.addItem("Sin resultados", None)
        for p in self._productos:
            self.producto_combo.addItem(f"{p.cod_producto} - {p.nombre_producto}", p.id_producto)
        self.producto_combo.blockSignals(False)
        self.producto_combo.setEnabled(bool(self._productos))
        self._on_producto_cambiado()

    def _filtrar_productos(self, texto: str) -> None:
        if not hasattr(self, "_timer_prod"):
            self._timer_prod = QTimer(self)
            self._timer_prod.setSingleShot(True)
            self._timer_prod.timeout.connect(
                lambda: self._buscar_productos(self.producto_buscar_input.text().strip() or None)
            )
        self._timer_prod.start(DEBOUNCE_BUSQUEDA_MS)

    def _on_producto_cambiado(self) -> None:
        id_producto = self.producto_combo.currentData()
        self.cantidad_input.setValue(1)
        if id_producto is None:
            self.precio_input.setValue(0)
            return
        producto = next((p for p in self._productos if p.id_producto == id_producto), None)
        self.precio_input.setValue(float(producto.costo_producto) if producto and producto.costo_producto else 0)

    # ── Carrito ────────────────────────────────────────────────────────────

    def _agregar_item(self) -> None:
        id_producto = self.producto_combo.currentData()
        if id_producto is None:
            MessageBox.warning(self, "Producto requerido", "Seleccione un producto para agregar.")
            return
        cantidad = self.cantidad_input.value()
        precio = self.precio_input.value()
        if cantidad <= 0 or precio <= 0:
            MessageBox.warning(self, "Datos inválidos", "Cantidad y precio deben ser mayores a cero.")
            return
        nombre = self.producto_combo.currentText()
        existente = next((it for it in self.items if it["id_producto"] == id_producto), None)
        if existente is not None:
            existente["cantidad"] += cantidad
        else:
            self.items.append(
                {"id_producto": id_producto, "nombre_producto": nombre, "cantidad": cantidad, "precio": precio}
            )
        self._refrescar_tabla()
        self.producto_buscar_input.clear()

    def _quitar_item(self, indice: int) -> None:
        del self.items[indice]
        self._refrescar_tabla()

    def _refrescar_tabla(self) -> None:
        self.tabla_items.setRowCount(len(self.items))
        total = 0.0
        for fila, item in enumerate(self.items):
            subtotal = item["cantidad"] * item["precio"]
            total += subtotal
            self.tabla_items.setItem(fila, 0, QTableWidgetItem(item["nombre_producto"]))
            self.tabla_items.setItem(fila, 1, QTableWidgetItem(f"{item['cantidad']:,.2f}"))
            self.tabla_items.setItem(fila, 2, QTableWidgetItem(f"${item['precio']:,.2f}"))
            self.tabla_items.setItem(fila, 3, QTableWidgetItem(f"${subtotal:,.2f}"))
            btn_quitar = QPushButton()
            btn_quitar.setObjectName("BtnQuitar")
            btn_quitar.setIcon(qta.icon("fa5s.trash-alt", color=COLOR_DANGER))
            btn_quitar.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_quitar.clicked.connect(lambda checked, i=fila: self._quitar_item(i))
            self.tabla_items.setCellWidget(fila, 4, btn_quitar)
        self.lbl_total.setText(f"Total: ${total:,.2f}")

    # ── Validacion / datos ────────────────────────────────────────────────

    def _validar_y_aceptar(self) -> None:
        if self.proveedor_combo.currentData() is None:
            MessageBox.warning(self, "Proveedor requerido", "Seleccione un proveedor.")
            return
        if not self.items:
            MessageBox.warning(self, "Orden vacía", "Agregue al menos un producto.")
            return

        self.btn_crear.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.oc_creada = CompraOCService.crear_oc(
                self.session,
                id_proveedor=self.proveedor_combo.currentData(),
                items=[
                    {
                        "id_producto": it["id_producto"],
                        "cantidad_solicitada": it["cantidad"],
                        "precio_unitario": it["precio"],
                    }
                    for it in self.items
                ],
                fecha_estimada_entrega=self.fecha_entrega_input.date().toPython(),
                observaciones=self.observaciones_input.text().strip() or None,
                id_usuario=self.id_usuario,
            )
        except ValueError as exc:
            self.session.rollback()
            MessageBox.warning(self, "No se pudo crear la orden", str(exc))
            return
        except PermisoDenegadoError:
            self.session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para crear órdenes de compra.")
            return
        except Exception:
            self.session.rollback()
            logger.exception("Fallo al crear orden de compra")
            MessageBox.critical(self, "Error", "No se pudo crear la orden de compra.")
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_crear.setEnabled(True)

        self.accept()


# =============================================================================
# Dialogo: Enmienda a una OC
# =============================================================================


class EnmiendaOCDialog(QDialog):
    """Propone un cambio a una OC (crear_enmienda_oc) y, si quien esta logueado tiene
    'compras'/'autorizar_enmienda_oc' (solo ADMIN, ver migrations/0033), ofrece
    autorizarla en el momento -- mismo criterio que _ofrecer_devolver_nota_credito en
    facturacion_panel.py (seguimiento inmediato en vez de obligar a navegar aparte)."""

    def __init__(self, session: Session, id_usuario: int | None, oc: CompraOC, parent=None):
        super().__init__(parent)
        self.session = session
        self.id_usuario = id_usuario
        self.oc = oc
        self.enmienda_creada = None

        self.setWindowTitle(f"Enmendar ODC {oc.numero_oc}")
        self.setFixedSize(480, 480)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._build_ui()

    def _make_card_info_tipos(self) -> QWidget:
        """Documentacion fija de que efecto tiene autorizar cada tipo de enmienda -- ver
        trg_compra_oc_enmienda_autorizar (migrations/0032 y 0034). Se muestra siempre,
        no solo para el tipo seleccionado, para que quede claro antes de elegir uno."""
        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        titulo = QLabel("EFECTO DE CADA TIPO AL AUTORIZAR")
        titulo.setProperty("class", "SectionTitle")
        layout.addWidget(titulo)

        filas = [
            ("Cantidad:", "se aplica automáticamente al autorizar.", COLOR_SUCCESS),
            ("Fecha:", "se aplica automáticamente al autorizar.", COLOR_SUCCESS),
            (
                "Precio:",
                "se registra como historial (cambio manual requerido en la línea de la ODC).",
                COLOR_TEXT_MUTED,
            ),
        ]
        for etiqueta, texto, color in filas:
            fila = QHBoxLayout()
            fila.setSpacing(6)
            lbl_etiqueta = QLabel(etiqueta)
            lbl_etiqueta.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {color};")
            lbl_etiqueta.setFixedWidth(55)
            lbl_texto = QLabel(texto)
            lbl_texto.setWordWrap(True)
            lbl_texto.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_DARK};")
            fila.addWidget(lbl_etiqueta)
            fila.addWidget(lbl_texto, stretch=1)
            layout.addLayout(fila)

        lbl_razon = QLabel(
            "Razón técnica: una ODC puede tener varias líneas con precios distintos, no hay "
            "una sola linea a la cual aplicar el cambio de precio de forma automatica."
        )
        lbl_razon.setWordWrap(True)
        lbl_razon.setStyleSheet(f"font-size: 11px; font-style: italic; color: {COLOR_TEXT_MUTED}; padding-top: 2px;")
        layout.addWidget(lbl_razon)

        return card

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        lbl_titulo = QLabel(f"Enmendar ODC {self.oc.numero_oc}")
        lbl_titulo.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        root.addWidget(lbl_titulo)

        root.addWidget(self._make_card_info_tipos())

        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        lbl_tipo = QLabel("Tipo de Cambio <span style='color: #DC2626;'>*</span>")
        lbl_tipo.setProperty("class", "FormLabel")
        self.tipo_combo = QComboBox()
        self.tipo_combo.addItem("Cantidad", "CANTIDAD")
        self.tipo_combo.addItem("Precio", "PRECIO")
        self.tipo_combo.addItem("Fecha de entrega", "FECHA")
        self.tipo_combo.setFixedHeight(32)
        self.tipo_combo.currentIndexChanged.connect(self._toggle_campos)
        layout.addWidget(lbl_tipo)
        layout.addWidget(self.tipo_combo)

        self.lbl_cantidad = QLabel("Nueva Cantidad Solicitada (total de la ODC)")
        self.lbl_cantidad.setProperty("class", "FormLabel")
        self.cantidad_nueva_input = QDoubleSpinBox()
        self.cantidad_nueva_input.setRange(0.01, 999999.99)
        self.cantidad_nueva_input.setDecimals(2)
        self.cantidad_nueva_input.setValue(float(self.oc.cantidad_solicitada))
        self.cantidad_nueva_input.setFixedHeight(32)
        layout.addWidget(self.lbl_cantidad)
        layout.addWidget(self.cantidad_nueva_input)

        self.lbl_precio = QLabel("Nuevo Precio (referencial, no ajusta lineas)")
        self.lbl_precio.setProperty("class", "FormLabel")
        self.precio_nuevo_input = QDoubleSpinBox()
        self.precio_nuevo_input.setRange(0.01, 999999999.99)
        self.precio_nuevo_input.setDecimals(2)
        self.precio_nuevo_input.setPrefix("$ ")
        self.precio_nuevo_input.setFixedHeight(32)
        layout.addWidget(self.lbl_precio)
        layout.addWidget(self.precio_nuevo_input)

        self.lbl_fecha = QLabel("Nueva Fecha de Entrega")
        self.lbl_fecha.setProperty("class", "FormLabel")
        self.fecha_nueva_input = QDateEdit()
        self.fecha_nueva_input.setCalendarPopup(True)
        self.fecha_nueva_input.setDisplayFormat("dd/MM/yyyy")
        self.fecha_nueva_input.setMinimumDate(QDate.currentDate())
        self.fecha_nueva_input.setDate(QDate.currentDate().addDays(7))
        self.fecha_nueva_input.setFixedHeight(32)
        layout.addWidget(self.lbl_fecha)
        layout.addWidget(self.fecha_nueva_input)

        lbl_motivo = QLabel("Motivo <span style='color: #DC2626;'>*</span>")
        lbl_motivo.setProperty("class", "FormLabel")
        self.motivo_input = QLineEdit()
        self.motivo_input.setPlaceholderText("Ej: acuerdo con el proveedor por retraso de despacho")
        self.motivo_input.setFixedHeight(32)
        layout.addWidget(lbl_motivo)
        layout.addWidget(self.motivo_input)

        root.addWidget(card, stretch=1)

        footer = QHBoxLayout()
        footer.addStretch()
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setObjectName("BtnSecondary")
        btn_cancelar.setFixedHeight(34)
        btn_cancelar.setAutoDefault(False)
        btn_cancelar.clicked.connect(self.reject)
        self.btn_proponer = QPushButton("Proponer Enmienda")
        self.btn_proponer.setObjectName("BtnPrimary")
        self.btn_proponer.setFixedHeight(34)
        self.btn_proponer.setAutoDefault(False)
        self.btn_proponer.clicked.connect(self._validar_y_aceptar)
        footer.addWidget(btn_cancelar)
        footer.addWidget(self.btn_proponer)
        root.addLayout(footer)

        self._toggle_campos()

    def _toggle_campos(self) -> None:
        tipo = self.tipo_combo.currentData()
        self.lbl_cantidad.setVisible(tipo == "CANTIDAD")
        self.cantidad_nueva_input.setVisible(tipo == "CANTIDAD")
        self.lbl_precio.setVisible(tipo == "PRECIO")
        self.precio_nuevo_input.setVisible(tipo == "PRECIO")
        self.lbl_fecha.setVisible(tipo == "FECHA")
        self.fecha_nueva_input.setVisible(tipo == "FECHA")

    def _validar_y_aceptar(self) -> None:
        motivo = self.motivo_input.text().strip()
        if not motivo:
            MessageBox.warning(self, "Motivo requerido", "Indique el motivo de la enmienda.")
            return
        tipo = self.tipo_combo.currentData()

        self.btn_proponer.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.enmienda_creada = CompraOCService.crear_enmienda(
                self.session,
                id_oc=self.oc.id_oc,
                tipo_cambio=tipo,
                motivo=motivo,
                cantidad_nueva=self.cantidad_nueva_input.value() if tipo == "CANTIDAD" else None,
                precio_nuevo=self.precio_nuevo_input.value() if tipo == "PRECIO" else None,
                fecha_entrega_nueva=self.fecha_nueva_input.date().toPython() if tipo == "FECHA" else None,
                id_usuario=self.id_usuario,
            )
        except ValueError as exc:
            self.session.rollback()
            MessageBox.warning(self, "No se pudo crear la enmienda", str(exc))
            return
        except PermisoDenegadoError:
            self.session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para proponer enmiendas.")
            return
        except Exception:
            self.session.rollback()
            logger.exception("Fallo al crear enmienda de OC")
            MessageBox.critical(self, "Error", "No se pudo crear la enmienda.")
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_proponer.setEnabled(True)

        # Seguimiento inmediato: solo tiene sentido ofrecerlo si quien esta logueado
        # puede autorizar (hoy, solo ADMIN -- ver migrations/0033). Si no puede, el
        # PermisoDenegadoError de autorizar_enmienda() se evita consultando antes.
        puede_autorizar = UsuarioService.verificar_permiso(
            self.session, self.id_usuario, "compras", "autorizar_enmienda_oc"
        )
        if puede_autorizar:
            respuesta = MessageBox.question(self, "Enmienda propuesta", "¿Autorizar esta enmienda ahora mismo?")
            if respuesta == QMessageBox.StandardButton.Yes:
                try:
                    CompraOCService.autorizar_enmienda(
                        self.session,
                        id_enmienda=self.enmienda_creada.id_enmienda,
                        aprobar=True,
                        id_usuario=self.id_usuario,
                    )
                except Exception:
                    self.session.rollback()
                    logger.exception("Fallo al autorizar enmienda recien creada")
                    MessageBox.warning(self, "No se pudo autorizar", "La enmienda quedó pendiente, autorícela luego.")

        self.accept()


# =============================================================================
# Dialogo: Nueva Recepcion (NR) contra una OC
# =============================================================================


class NotaRecepcionFormDialog(QDialog):
    """Tabla FIJA de las lineas pendientes de la OC (no un carrito de busqueda libre --
    solo se puede recibir lo que la OC realmente solicito). Cada fila tiene dos spinbox:
    cantidad a recibir (tope: lo pendiente) y cantidad rechazada (tope: lo que se va a
    recibir en esta misma linea)."""

    def __init__(self, session: Session, id_usuario: int | None, oc: CompraOC, parent=None):
        super().__init__(parent)
        self.session = session
        self.id_usuario = id_usuario
        self.oc = oc
        self.nota_creada = None
        datos = CompraOCService.obtener_oc(session, oc.id_oc, id_usuario=id_usuario)
        self.detalles_pendientes = [d for d in datos["detalles"] if d.cantidad_pendiente > 0]

        self.setWindowTitle(f"Nueva Recepción — ODC {oc.numero_oc}")
        self.resize(720, 560)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        lbl_titulo = QLabel(f"Nueva Recepción — ODC {self.oc.numero_oc}")
        lbl_titulo.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        root.addWidget(lbl_titulo)

        if not self.detalles_pendientes:
            root.addWidget(QLabel("Esta orden de compra no tiene lineas pendientes de recibir."))
        else:
            self.tabla = _tabla_lecturas(["Producto", "Pendiente", "Cant. a Recibir", "Cant. Rechazada"])
            self.tabla.setRowCount(len(self.detalles_pendientes))
            self._spins_recibida: list[QDoubleSpinBox] = []
            self._spins_rechazada: list[QDoubleSpinBox] = []
            for fila, detalle in enumerate(self.detalles_pendientes):
                nombre = detalle.producto.nombre_producto if detalle.producto else "—"
                self.tabla.setItem(fila, 0, QTableWidgetItem(nombre))
                self.tabla.setItem(fila, 1, QTableWidgetItem(f"{float(detalle.cantidad_pendiente):,.2f}"))

                spin_recibida = QDoubleSpinBox()
                spin_recibida.setRange(0, float(detalle.cantidad_pendiente))
                spin_recibida.setDecimals(2)
                spin_recibida.setValue(0)
                spin_recibida.valueChanged.connect(lambda v, i=fila: self._on_recibida_cambiada(i, v))
                self.tabla.setCellWidget(fila, 2, spin_recibida)
                self._spins_recibida.append(spin_recibida)

                spin_rechazada = QDoubleSpinBox()
                spin_rechazada.setRange(0, 0)
                spin_rechazada.setDecimals(2)
                self.tabla.setCellWidget(fila, 3, spin_rechazada)
                self._spins_rechazada.append(spin_rechazada)

            root.addWidget(self.tabla, stretch=1)

        lbl_obs = QLabel("Observaciones")
        lbl_obs.setProperty("class", "FormLabel")
        self.observaciones_input = QLineEdit()
        self.observaciones_input.setPlaceholderText("Opcional")
        self.observaciones_input.setFixedHeight(30)
        root.addWidget(lbl_obs)
        root.addWidget(self.observaciones_input)

        footer = QHBoxLayout()
        footer.addStretch()
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setObjectName("BtnSecondary")
        btn_cancelar.setFixedHeight(34)
        btn_cancelar.setAutoDefault(False)
        btn_cancelar.clicked.connect(self.reject)
        self.btn_registrar = QPushButton("Registrar Recepción")
        self.btn_registrar.setObjectName("BtnPrimary")
        self.btn_registrar.setFixedHeight(34)
        self.btn_registrar.setAutoDefault(False)
        self.btn_registrar.setEnabled(bool(self.detalles_pendientes))
        self.btn_registrar.clicked.connect(self._validar_y_aceptar)
        footer.addWidget(btn_cancelar)
        footer.addWidget(self.btn_registrar)
        root.addLayout(footer)

    def _on_recibida_cambiada(self, fila: int, valor: float) -> None:
        self._spins_rechazada[fila].setRange(0, valor)

    def _validar_y_aceptar(self) -> None:
        items = []
        for fila, detalle in enumerate(self.detalles_pendientes):
            cantidad_recibida = self._spins_recibida[fila].value()
            if cantidad_recibida <= 0:
                continue
            items.append(
                {
                    "id_oc_detalle": detalle.id_detalle,
                    "cantidad_recibida": cantidad_recibida,
                    "cantidad_rechazada": self._spins_rechazada[fila].value(),
                }
            )
        if not items:
            MessageBox.warning(self, "Nada que recibir", "Ingrese al menos una cantidad recibida mayor a cero.")
            return

        self.btn_registrar.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.nota_creada = NotaRecepcionService.crear_nota_recepcion(
                self.session,
                id_oc=self.oc.id_oc,
                items=items,
                observaciones=self.observaciones_input.text().strip() or None,
                id_usuario=self.id_usuario,
            )
        except ValueError as exc:
            self.session.rollback()
            MessageBox.warning(self, "No se pudo registrar la recepción", str(exc))
            return
        except PermisoDenegadoError:
            self.session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para recibir mercancía.")
            return
        except Exception:
            self.session.rollback()
            logger.exception("Fallo al crear nota de recepcion")
            MessageBox.critical(self, "Error", "No se pudo registrar la recepción.")
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_registrar.setEnabled(True)

        self.accept()


# =============================================================================
# Dialogo: Nota de Devolucion (rechazo) contra una NR
# =============================================================================


class NotaDevolucionFormDialog(QDialog):
    """Tabla fija de las lineas de la NR con saldo rechazado disponible para devolver
    (cantidad_rechazada de la linea, menos lo ya devuelto en notas anteriores de esa
    misma NR -- ver NotaRecepcionService.crear_nota_devolucion)."""

    def __init__(self, session: Session, id_usuario: int | None, nr, parent=None):
        super().__init__(parent)
        self.session = session
        self.id_usuario = id_usuario
        self.nr = nr
        self.devolucion_creada = None
        datos = NotaRecepcionService.obtener_nota_recepcion(session, nr.id_nr, id_usuario=id_usuario)
        self.lineas_disponibles = []
        for detalle in datos["detalles"]:
            ya_devuelto = (
                session.query(NotaDevolucionDetalle)
                .join(NotaDevolucionDetalle.devolucion)
                .filter(
                    NotaDevolucionDetalle.devolucion.has(id_nr=nr.id_nr),
                    NotaDevolucionDetalle.id_producto == detalle.id_producto,
                )
                .all()
            )
            devuelto = sum((d.cantidad_devuelta for d in ya_devuelto), Decimal("0"))
            disponible = detalle.cantidad_rechazada - devuelto
            if disponible > 0:
                self.lineas_disponibles.append((detalle, disponible))

        self.setWindowTitle(f"Nota de Devolución — NR {nr.numero_nr}")
        self.resize(680, 520)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        lbl_titulo = QLabel(f"Nota de Devolución — NR {self.nr.numero_nr}")
        lbl_titulo.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        root.addWidget(lbl_titulo)

        if not self.lineas_disponibles:
            root.addWidget(QLabel("Esta recepción no tiene unidades rechazadas pendientes de devolver."))
        else:
            self.tabla = _tabla_lecturas(["Producto", "Disponible para Devolver", "Cantidad a Devolver"])
            self.tabla.setRowCount(len(self.lineas_disponibles))
            self._spins: list[QDoubleSpinBox] = []
            for fila, (detalle, disponible) in enumerate(self.lineas_disponibles):
                nombre = detalle.producto.nombre_producto if detalle.producto else "—"
                self.tabla.setItem(fila, 0, QTableWidgetItem(nombre))
                self.tabla.setItem(fila, 1, QTableWidgetItem(f"{float(disponible):,.2f}"))
                spin = QDoubleSpinBox()
                spin.setRange(0, float(disponible))
                spin.setDecimals(2)
                self.tabla.setCellWidget(fila, 2, spin)
                self._spins.append(spin)
            root.addWidget(self.tabla, stretch=1)

        lbl_motivo = QLabel("Motivo <span style='color: #DC2626;'>*</span>")
        lbl_motivo.setProperty("class", "FormLabel")
        self.motivo_combo = QComboBox()
        for motivo in MOTIVOS_DEVOLUCION:
            self.motivo_combo.addItem(motivo)
        self.motivo_combo.setFixedHeight(32)
        root.addWidget(lbl_motivo)
        root.addWidget(self.motivo_combo)

        footer = QHBoxLayout()
        footer.addStretch()
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setObjectName("BtnSecondary")
        btn_cancelar.setFixedHeight(34)
        btn_cancelar.setAutoDefault(False)
        btn_cancelar.clicked.connect(self.reject)
        self.btn_registrar = QPushButton("Registrar Devolución")
        self.btn_registrar.setObjectName("BtnPrimary")
        self.btn_registrar.setFixedHeight(34)
        self.btn_registrar.setAutoDefault(False)
        self.btn_registrar.setEnabled(bool(self.lineas_disponibles))
        self.btn_registrar.clicked.connect(self._validar_y_aceptar)
        footer.addWidget(btn_cancelar)
        footer.addWidget(self.btn_registrar)
        root.addLayout(footer)

    def _validar_y_aceptar(self) -> None:
        items = []
        for fila, (detalle, _disponible) in enumerate(self.lineas_disponibles):
            cantidad = self._spins[fila].value()
            if cantidad <= 0:
                continue
            items.append({"id_producto": detalle.id_producto, "cantidad_devuelta": cantidad})
        if not items:
            MessageBox.warning(self, "Nada que devolver", "Ingrese al menos una cantidad a devolver mayor a cero.")
            return

        self.btn_registrar.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.devolucion_creada = NotaRecepcionService.crear_nota_devolucion(
                self.session,
                id_nr=self.nr.id_nr,
                items=items,
                motivo=self.motivo_combo.currentText(),
                id_usuario=self.id_usuario,
            )
        except ValueError as exc:
            self.session.rollback()
            MessageBox.warning(self, "No se pudo registrar la devolución", str(exc))
            return
        except PermisoDenegadoError:
            self.session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para registrar devoluciones.")
            return
        except Exception:
            self.session.rollback()
            logger.exception("Fallo al crear nota de devolucion")
            MessageBox.critical(self, "Error", "No se pudo registrar la devolución.")
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_registrar.setEnabled(True)

        self.accept()


# =============================================================================
# Dialogo: Facturar (crear Compra) contra una OC
# =============================================================================


class CompraDesdeOCFormDialog(QDialog):
    """Tabla fija de las lineas de la OC con saldo recibido y sin facturar (ver
    CompraService.crear_compra_desde_oc) + condicion de pago. Contado reusa
    PagoLineaDialog igual que CompraService.registrar_compra (compras.py): un unico pago
    que debe cubrir el total exacto, sin vuelto."""

    def __init__(self, session: Session, id_usuario: int | None, oc: CompraOC, parent=None):
        super().__init__(parent)
        self.session = session
        self.id_usuario = id_usuario
        self.oc = oc
        self.pago: dict | None = None
        self.compra_creada = None
        datos = CompraOCService.obtener_oc(session, oc.id_oc, id_usuario=id_usuario)
        self.lineas_disponibles = [
            (d, d.cantidad_recibida - d.cantidad_facturada)
            for d in datos["detalles"]
            if d.cantidad_recibida - d.cantidad_facturada > 0
        ]

        self.setWindowTitle(f"Nueva Factura — ODC {oc.numero_oc}")
        self.resize(720, 640)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        lbl_titulo = QLabel(f"Nueva Factura — ODC {self.oc.numero_oc}")
        lbl_titulo.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        root.addWidget(lbl_titulo)

        if not self.lineas_disponibles:
            root.addWidget(QLabel("Esta orden de compra no tiene mercancía recibida pendiente de facturar."))
        else:
            self.tabla = _tabla_lecturas(["Producto", "Disponible", "Costo Unit.", "Cant. a Facturar"])
            self.tabla.setRowCount(len(self.lineas_disponibles))
            self._spins: list[QDoubleSpinBox] = []
            for fila, (detalle, disponible) in enumerate(self.lineas_disponibles):
                nombre = detalle.producto.nombre_producto if detalle.producto else "—"
                self.tabla.setItem(fila, 0, QTableWidgetItem(nombre))
                self.tabla.setItem(fila, 1, QTableWidgetItem(f"{float(disponible):,.2f}"))
                self.tabla.setItem(fila, 2, QTableWidgetItem(f"${float(detalle.precio_unitario):,.2f}"))
                spin = QDoubleSpinBox()
                spin.setRange(0, float(disponible))
                spin.setDecimals(2)
                spin.setValue(float(disponible))
                spin.valueChanged.connect(self._refrescar_total)
                self.tabla.setCellWidget(fila, 3, spin)
                self._spins.append(spin)
            root.addWidget(self.tabla, stretch=1)

        fila_condicion = QHBoxLayout()
        col_condicion = QVBoxLayout()
        lbl_condicion = QLabel("Condición de Pago")
        lbl_condicion.setProperty("class", "FormLabel")
        self.condicion_combo = QComboBox()
        self.condicion_combo.addItem("Contado", "contado")
        self.condicion_combo.addItem("Crédito", "credito")
        self.condicion_combo.setFixedHeight(32)
        self.condicion_combo.currentIndexChanged.connect(self._toggle_credito)
        col_condicion.addWidget(lbl_condicion)
        col_condicion.addWidget(self.condicion_combo)
        fila_condicion.addLayout(col_condicion, stretch=1)

        col_total = QVBoxLayout()
        col_total.addWidget(QLabel(""))
        self.lbl_total = QLabel("Total: $0.00")
        self.lbl_total.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        col_total.addWidget(self.lbl_total)
        fila_condicion.addLayout(col_total, stretch=1)
        root.addLayout(fila_condicion)

        self.card_pago = QWidget()
        self.card_pago.setObjectName("SectionCard")
        aplicar_sombra(self.card_pago)
        pago_layout = QHBoxLayout(self.card_pago)
        pago_layout.setContentsMargins(16, 12, 16, 12)
        self.lbl_pago_resumen = QLabel("Sin pago configurado.")
        self.lbl_pago_resumen.setStyleSheet(f"font-size: 13px; color: {COLOR_TEXT_MUTED};")
        pago_layout.addWidget(self.lbl_pago_resumen, stretch=1)
        btn_configurar_pago = QPushButton("Configurar pago")
        btn_configurar_pago.setObjectName("BtnAgregar")
        btn_configurar_pago.setAutoDefault(False)
        btn_configurar_pago.clicked.connect(self._configurar_pago)
        pago_layout.addWidget(btn_configurar_pago)
        root.addWidget(self.card_pago)

        footer = QHBoxLayout()
        footer.addStretch()
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setObjectName("BtnSecondary")
        btn_cancelar.setFixedHeight(34)
        btn_cancelar.setAutoDefault(False)
        btn_cancelar.clicked.connect(self.reject)
        self.btn_registrar = QPushButton("Registrar Factura")
        self.btn_registrar.setObjectName("BtnPrimary")
        self.btn_registrar.setFixedHeight(34)
        self.btn_registrar.setAutoDefault(False)
        self.btn_registrar.setEnabled(bool(self.lineas_disponibles))
        self.btn_registrar.clicked.connect(self._validar_y_aceptar)
        footer.addWidget(btn_cancelar)
        footer.addWidget(self.btn_registrar)
        root.addLayout(footer)

        self._refrescar_total()
        self._toggle_credito()

    def _total_actual(self) -> float:
        if not self.lineas_disponibles:
            return 0.0
        return sum(
            spin.value() * float(detalle.precio_unitario)
            for spin, (detalle, _) in zip(self._spins, self.lineas_disponibles, strict=True)
        )

    def _refrescar_total(self) -> None:
        self.lbl_total.setText(f"Total: ${self._total_actual():,.2f}")

    def _toggle_credito(self) -> None:
        es_credito = self.condicion_combo.currentData() == "credito"
        self.card_pago.setVisible(not es_credito)
        if es_credito:
            self.pago = None
            self.lbl_pago_resumen.setText("Sin pago configurado.")

    def _configurar_pago(self) -> None:
        dialogo = PagoLineaDialog(self.session, self.id_usuario, monto_sugerido=self._total_actual(), parent=self)
        if dialogo.exec() == QDialog.DialogCode.Accepted:
            self.pago = dialogo.get_data()
            metodo = _ETIQUETAS_METODO.get(self.pago["metodo_pago"], self.pago["metodo_pago"])
            self.lbl_pago_resumen.setText(f"{metodo} · {self.pago['moneda']} {self.pago['monto_moneda_origen']:,.2f}")
            self.lbl_pago_resumen.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_SUCCESS};")

    def _validar_y_aceptar(self) -> None:
        items = []
        for spin, (detalle, _disponible) in zip(self._spins, self.lineas_disponibles, strict=True):
            if spin.value() <= 0:
                continue
            items.append({"id_oc_detalle": detalle.id_detalle, "cantidad": spin.value()})
        if not items:
            MessageBox.warning(self, "Nada que facturar", "Ingrese al menos una cantidad a facturar mayor a cero.")
            return
        es_contado = self.condicion_combo.currentData() == "contado"
        if es_contado and self.pago is None:
            MessageBox.warning(self, "Pago requerido", "Configure el pago de contado antes de registrar la factura.")
            return

        self.btn_registrar.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.compra_creada = CompraService.crear_compra_desde_oc(
                self.session,
                id_oc=self.oc.id_oc,
                id_usuario=self.id_usuario,
                items=items,
                condicion_pago=self.condicion_combo.currentData(),
                pago=self.pago if es_contado else None,
            )
        except ValueError as exc:
            self.session.rollback()
            MessageBox.warning(self, "No se pudo registrar la factura", str(exc))
            return
        except PermisoDenegadoError:
            self.session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para registrar compras.")
            return
        except Exception:
            self.session.rollback()
            logger.exception("Fallo al crear compra desde OC")
            MessageBox.critical(self, "Error", "No se pudo registrar la factura.")
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_registrar.setEnabled(True)

        self.accept()


# =============================================================================
# Vista principal: 3 pestanas (CxP se movio a app/ui/cuentas_por_pagar_panel.py,
# modulo aparte -- ver CuentasPorPagarPanel/PagoProveedorDialog en ese archivo)
# =============================================================================


class ComprasView(QWidget):
    """Modulo unico de Compras: cubre el flujo OC -> NR -> Compra -> Pago completo en 4
    pestanas. Cada pestana mantiene su propia paginacion, igual que un panel independiente
    -- son 4 listados distintos, no una sola tabla con filtros."""

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.paginas = {"oc": 1, "nr": 1, "compra": 1}
        self.total_paginas = {"oc": 1, "nr": 1, "compra": 1}
        self.setObjectName("ContentArea")
        self._setup_ui()
        QTimer.singleShot(100, self._cargar_tab_actual)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._cargar_tab_actual()

    # ── Construccion de la UI ────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        lbl = QLabel("Compras")
        lbl.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        root.addWidget(lbl)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(TABS_QSS)
        self.tabs.addTab(self._make_tab_oc(), "Órdenes de Compra")
        self.tabs.addTab(self._make_tab_nr(), "Recepciones")
        self.tabs.addTab(self._make_tab_compras(), "Facturas")
        self.tabs.currentChanged.connect(lambda _i: self._cargar_tab_actual())
        root.addWidget(self.tabs, stretch=1)

        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

    def _make_toolbar(self, estados: list[tuple], on_filtro_cambiado, on_nuevo=None, texto_nuevo="") -> tuple:
        w = QWidget()
        w.setStyleSheet(
            f"background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 8px; padding: 4px;"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)

        buscar_input = QLineEdit()
        buscar_input.setPlaceholderText("Buscar…")
        buscar_input.setObjectName("SearchInput")
        buscar_input.setStyleSheet(SEARCH_QSS)
        buscar_input.setFixedWidth(280)
        buscar_input.returnPressed.connect(on_filtro_cambiado)

        estado_combo = QComboBox()
        for etiqueta, valor in estados:
            estado_combo.addItem(etiqueta, valor)
        estado_combo.currentIndexChanged.connect(on_filtro_cambiado)
        btn_filtrar = BotonFiltros([("Estado", estado_combo)])

        h.addWidget(buscar_input)
        h.addSpacerItem(QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        btn_nuevo = None
        if on_nuevo is not None:
            btn_nuevo = QPushButton(texto_nuevo)
            btn_nuevo.setIcon(qta.icon("fa5s.plus", color="white"))
            btn_nuevo.setStyleSheet(BUTTON_PRIMARY_QSS)
            btn_nuevo.clicked.connect(on_nuevo)
            h.addWidget(btn_nuevo)
        h.addWidget(btn_filtrar)
        return w, buscar_input, estado_combo

    def _make_tabla(self, columnas: list[str]) -> QTableWidget:
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
        tabla.verticalHeader().setDefaultSectionSize(42)
        return tabla

    def _make_footer(self, on_anterior, on_siguiente, botones_secundarios: list[QPushButton]) -> tuple:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        lbl_pagina = QLabel("Página 1")
        lbl_pagina.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")
        btn_anterior = QPushButton()
        btn_anterior.setIcon(qta.icon("fa5s.chevron-left", color=COLOR_TEXT_DARK))
        btn_anterior.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_anterior.setFixedWidth(40)
        btn_anterior.clicked.connect(on_anterior)
        btn_siguiente = QPushButton()
        btn_siguiente.setIcon(qta.icon("fa5s.chevron-right", color=COLOR_TEXT_DARK))
        btn_siguiente.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_siguiente.setFixedWidth(40)
        btn_siguiente.clicked.connect(on_siguiente)
        h.addWidget(lbl_pagina)
        h.addWidget(btn_anterior)
        h.addWidget(btn_siguiente)
        h.addStretch()
        for btn in botones_secundarios:
            h.addWidget(btn)
        return w, lbl_pagina, btn_anterior, btn_siguiente

    def _fila_seleccionada_id(self, tabla: QTableWidget) -> int | None:
        filas = tabla.selectionModel().selectedRows()
        if not filas:
            MessageBox.information(self, "Selección requerida", "Selecciona una fila de la lista.")
            return None
        item = tabla.item(filas[0].row(), 0)
        return int(item.text()) if item is not None else None

    def _cargar_tab_actual(self) -> None:
        indice = self.tabs.currentIndex()
        [self.cargar_ocs, self.cargar_nrs, self.cargar_compras][indice]()

    # ── Pestana: Ordenes de Compra ───────────────────────────────────────

    def _make_tab_oc(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 12, 4, 4)
        layout.setSpacing(12)

        estados = [
            ("Todos los estados", None),
            ("Pendiente", "PENDIENTE"),
            ("Parcial", "PARCIAL"),
            ("Completa", "COMPLETA"),
            ("Anulada", "ANULADA"),
        ]
        toolbar, self.oc_buscar_input, self.oc_estado_combo = self._make_toolbar(
            estados, self._buscar_ocs_desde_inicio, self.nueva_oc, "Nueva ODC"
        )
        layout.addWidget(toolbar)

        self.tabla_oc = self._make_tabla(
            ["ID", "N° ODC", "Proveedor", "Fecha", "Total Productos", "Cant. Rec.", "Total", "Estado"]
        )
        self.tabla_oc.doubleClicked.connect(self.ver_detalle_oc)
        layout.addWidget(self.tabla_oc, stretch=1)

        btn_ver_detalle = QPushButton("Ver Detalle")
        btn_ver_detalle.setIcon(qta.icon("fa5s.eye", color=COLOR_TEXT_DARK))
        btn_ver_detalle.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_ver_detalle.clicked.connect(self.ver_detalle_oc_seleccionada)
        btn_enmendar = QPushButton("Enmendar")
        btn_enmendar.setIcon(qta.icon("fa5s.edit", color=COLOR_TEXT_DARK))
        btn_enmendar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_enmendar.clicked.connect(self.enmendar_oc_seleccionada)
        footer, self.lbl_pagina_oc, self.btn_oc_anterior, self.btn_oc_siguiente = self._make_footer(
            lambda: self._pagina_anterior("oc"), lambda: self._pagina_siguiente("oc"), [btn_ver_detalle, btn_enmendar]
        )
        layout.addWidget(footer)
        return page

    def _buscar_ocs_desde_inicio(self) -> None:
        self.paginas["oc"] = 1
        self.cargar_ocs()

    def cargar_ocs(self) -> None:
        session = self.session_factory()
        try:
            resultado = CompraOCService.listar_ocs(
                session,
                texto_busqueda=self.oc_buscar_input.text().strip() or None,
                estado=self.oc_estado_combo.currentData(),
                pagina=self.paginas["oc"],
                por_pagina=POR_PAGINA,
                id_usuario=self.usuario.id_usuario,
            )
            ocs = resultado["items"]
            self.tabla_oc.setRowCount(len(ocs))
            for fila, oc in enumerate(ocs):
                self.tabla_oc.setItem(fila, 0, QTableWidgetItem(str(oc.id_oc)))
                self.tabla_oc.setItem(fila, 1, QTableWidgetItem(oc.numero_oc))
                self.tabla_oc.setItem(
                    fila, 2, QTableWidgetItem(oc.proveedor.nombre_razon_social if oc.proveedor else "")
                )
                self.tabla_oc.setItem(
                    fila, 3, QTableWidgetItem(oc.fecha_oc.strftime("%d/%m/%Y") if oc.fecha_oc else "")
                )
                self.tabla_oc.setItem(fila, 4, QTableWidgetItem(f"{float(oc.cantidad_solicitada):,.2f}"))
                self.tabla_oc.setItem(fila, 5, QTableWidgetItem(f"{float(oc.cantidad_recibida):,.2f}"))
                self.tabla_oc.setItem(fila, 6, QTableWidgetItem(f"${float(oc.total_oc):,.2f}"))
                color = COLORES_ESTADO_OC.get(oc.estado, COLOR_TEXT_MUTED)
                self.tabla_oc.setCellWidget(fila, 7, EstadoBadge(oc.estado.capitalize(), color))
            self._actualizar_paginacion(
                "oc", resultado["total"], self.lbl_pagina_oc, self.btn_oc_anterior, self.btn_oc_siguiente
            )
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar órdenes de compra.")
        except Exception as exc:
            logger.exception("Fallo al cargar ordenes de compra")
            MessageBox.critical(self, "Error", f"No se pudo cargar el listado de órdenes de compra: {exc}")
        finally:
            session.close()

    def nueva_oc(self) -> None:
        session = self.session_factory()
        try:
            dialogo = OrdenCompraFormDialog(session, self.usuario.id_usuario, parent=self)
            if dialogo.exec() and dialogo.oc_creada is not None:
                self.cargar_ocs()
                MessageBox.information(self, "Orden creada", f"ODC {dialogo.oc_creada.numero_oc} creada con éxito.")
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para crear órdenes de compra.")
        finally:
            session.close()

    def enmendar_oc_seleccionada(self) -> None:
        id_oc = self._fila_seleccionada_id(self.tabla_oc)
        if id_oc is None:
            return
        session = self.session_factory()
        try:
            oc = session.get(CompraOC, id_oc)
            if oc is None:
                return
            dialogo = EnmiendaOCDialog(session, self.usuario.id_usuario, oc, parent=self)
            if dialogo.exec():
                self.cargar_ocs()
        finally:
            session.close()

    def ver_detalle_oc_seleccionada(self) -> None:
        id_oc = self._fila_seleccionada_id(self.tabla_oc)
        if id_oc is None:
            return
        self._abrir_detalle_oc(id_oc)

    def ver_detalle_oc(self) -> None:
        id_oc = self._fila_seleccionada_id(self.tabla_oc)
        if id_oc is not None:
            self._abrir_detalle_oc(id_oc)

    def _abrir_detalle_oc(self, id_oc: int) -> None:
        session = self.session_factory()
        try:
            datos = CompraOCService.obtener_oc(session, id_oc, id_usuario=self.usuario.id_usuario)
            dialogo = OrdenCompraDetalleDialog(datos, parent=self)
            dialogo.exec()
        except ValueError as exc:
            MessageBox.warning(self, "Orden no encontrada", str(exc))
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar esta orden de compra.")
        except Exception as exc:
            logger.exception("Fallo al abrir el detalle de la OC %s", id_oc)
            MessageBox.critical(self, "Error", f"No se pudo abrir el detalle de la orden de compra: {exc}")
        finally:
            session.close()

    # ── Pestana: Recepciones ─────────────────────────────────────────────

    def _make_tab_nr(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 12, 4, 4)
        layout.setSpacing(12)

        toolbar, self.nr_buscar_input, self.nr_estado_combo = self._make_toolbar(
            [
                ("Todos los estados", None),
                ("Recibida", "RECIBIDA"),
                ("Parcial", "PARCIAL"),
                ("Facturada", "FACTURADA"),
                ("Anulada", "ANULADA"),
            ],
            self._buscar_nrs_desde_inicio,
            self.nueva_recepcion,
            "Nueva Recepción",
        )
        self.nr_buscar_input.setVisible(False)  # sin busqueda por texto, ver docstring del footer
        layout.addWidget(toolbar)

        self.tabla_nr = self._make_tabla(["ID", "N° NR", "ODC", "Proveedor", "Fecha", "Estado"])
        layout.addWidget(self.tabla_nr, stretch=1)

        btn_rechazar = QPushButton("Rechazar (Devolución)")
        btn_rechazar.setIcon(qta.icon("fa5s.undo", color=COLOR_TEXT_DARK))
        btn_rechazar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_rechazar.clicked.connect(self.rechazar_nr_seleccionada)
        footer, self.lbl_pagina_nr, self.btn_nr_anterior, self.btn_nr_siguiente = self._make_footer(
            lambda: self._pagina_anterior("nr"), lambda: self._pagina_siguiente("nr"), [btn_rechazar]
        )
        layout.addWidget(footer)
        return page

    def _buscar_nrs_desde_inicio(self) -> None:
        self.paginas["nr"] = 1
        self.cargar_nrs()

    def cargar_nrs(self) -> None:
        session = self.session_factory()
        try:
            resultado = NotaRecepcionService.listar_notas_recepcion(
                session, pagina=self.paginas["nr"], por_pagina=POR_PAGINA, id_usuario=self.usuario.id_usuario
            )
            nrs = resultado["items"]
            estado_filtro = self.nr_estado_combo.currentData()
            if estado_filtro:
                nrs = [n for n in nrs if n.estado == estado_filtro]
            self.tabla_nr.setRowCount(len(nrs))
            for fila, nr in enumerate(nrs):
                oc = nr.oc
                self.tabla_nr.setItem(fila, 0, QTableWidgetItem(str(nr.id_nr)))
                self.tabla_nr.setItem(fila, 1, QTableWidgetItem(nr.numero_nr))
                self.tabla_nr.setItem(fila, 2, QTableWidgetItem(oc.numero_oc if oc else ""))
                self.tabla_nr.setItem(
                    fila, 3, QTableWidgetItem(oc.proveedor.nombre_razon_social if oc and oc.proveedor else "")
                )
                self.tabla_nr.setItem(
                    fila, 4, QTableWidgetItem(nr.fecha_recepcion.strftime("%d/%m/%Y") if nr.fecha_recepcion else "")
                )
                color = COLORES_ESTADO_NR.get(nr.estado, COLOR_TEXT_MUTED)
                self.tabla_nr.setCellWidget(fila, 5, EstadoBadge(nr.estado.capitalize(), color))
            self._actualizar_paginacion(
                "nr", resultado["total"], self.lbl_pagina_nr, self.btn_nr_anterior, self.btn_nr_siguiente
            )
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar recepciones.")
        except Exception:
            logger.exception("Fallo al cargar notas de recepcion")
            MessageBox.critical(self, "Error", "No se pudo cargar el listado de recepciones.")
        finally:
            session.close()

    def nueva_recepcion(self) -> None:
        session = self.session_factory()
        try:
            resultado = CompraOCService.listar_ocs(session, por_pagina=200, id_usuario=self.usuario.id_usuario)
            candidatas = [oc for oc in resultado["items"] if oc.estado in ("PENDIENTE", "PARCIAL")]
            if not candidatas:
                MessageBox.information(
                    self, "Sin órdenes pendientes", "No hay órdenes de compra con mercancía pendiente de recibir."
                )
                return
            etiquetas = [
                f"{oc.numero_oc} — {oc.proveedor.nombre_razon_social if oc.proveedor else ''}" for oc in candidatas
            ]
            etiqueta, ok = QInputDialog.getItem(
                self, "Nueva Recepción", "Seleccione la orden de compra:", etiquetas, editable=False
            )
            if not ok:
                return
            oc = candidatas[etiquetas.index(etiqueta)]

            dialogo = NotaRecepcionFormDialog(session, self.usuario.id_usuario, oc, parent=self)
            if dialogo.exec() and dialogo.nota_creada is not None:
                self.cargar_nrs()
                self.cargar_ocs()
                MessageBox.information(
                    self, "Recepción registrada", f"NR {dialogo.nota_creada.numero_nr} registrada con éxito."
                )
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para recibir mercancía.")
        finally:
            session.close()

    def rechazar_nr_seleccionada(self) -> None:
        id_nr = self._fila_seleccionada_id(self.tabla_nr)
        if id_nr is None:
            return
        session = self.session_factory()
        try:
            nr = session.get(NotaRecepcion, id_nr)
            if nr is None:
                return
            dialogo = NotaDevolucionFormDialog(session, self.usuario.id_usuario, nr, parent=self)
            if dialogo.exec() and dialogo.devolucion_creada is not None:
                MessageBox.information(
                    self,
                    "Devolución registrada",
                    f"Nota de devolución {dialogo.devolucion_creada.numero_nota_devolucion} registrada con éxito.",
                )
        finally:
            session.close()

    # ── Pestana: Facturas ────────────────────────────────────────────────

    def _make_tab_compras(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 12, 4, 4)
        layout.setSpacing(12)

        toolbar, self.compra_buscar_input, self.compra_estado_combo = self._make_toolbar(
            [("Todos los estados", None), ("Emitida", "EMITIDA"), ("Anulada", "ANULADA")],
            self._buscar_compras_desde_inicio,
            self.nueva_factura_desde_oc,
            "Nueva Factura",
        )
        self.compra_buscar_input.setVisible(False)
        layout.addWidget(toolbar)

        self.tabla_compra = self._make_tabla(
            ["ID", "N° Compra", "ODC", "Proveedor", "Fecha", "Condición", "Total", "Estado"]
        )
        layout.addWidget(self.tabla_compra, stretch=1)

        footer, self.lbl_pagina_compra, self.btn_compra_anterior, self.btn_compra_siguiente = self._make_footer(
            lambda: self._pagina_anterior("compra"), lambda: self._pagina_siguiente("compra"), []
        )
        layout.addWidget(footer)
        return page

    def _buscar_compras_desde_inicio(self) -> None:
        self.paginas["compra"] = 1
        self.cargar_compras()

    def cargar_compras(self) -> None:
        session = self.session_factory()
        try:
            resultado = CompraService.listar_compras(
                session,
                estado=self.compra_estado_combo.currentData(),
                solo_desde_oc=True,
                pagina=self.paginas["compra"],
                por_pagina=POR_PAGINA,
                id_usuario=self.usuario.id_usuario,
            )
            compras = resultado["items"]
            self.tabla_compra.setRowCount(len(compras))
            for fila, c in enumerate(compras):
                self.tabla_compra.setItem(fila, 0, QTableWidgetItem(str(c.id_compra)))
                self.tabla_compra.setItem(fila, 1, QTableWidgetItem(c.numero_compra))
                oc = session.get(CompraOC, c.id_oc) if c.id_oc else None
                self.tabla_compra.setItem(fila, 2, QTableWidgetItem(oc.numero_oc if oc else ""))
                self.tabla_compra.setItem(
                    fila, 3, QTableWidgetItem(c.proveedor.nombre_razon_social if c.proveedor else "")
                )
                self.tabla_compra.setItem(
                    fila, 4, QTableWidgetItem(c.fecha_emision.strftime("%d/%m/%Y") if c.fecha_emision else "")
                )
                self.tabla_compra.setItem(
                    fila, 5, QTableWidgetItem("Contado" if c.condicion_pago == "contado" else "Crédito")
                )
                self.tabla_compra.setItem(fila, 6, QTableWidgetItem(f"${float(c.total_compra):,.2f}"))
                estado = c.estado_compra or "EMITIDA"
                color = COLORES_ESTADO_COMPRA.get(estado, COLOR_TEXT_MUTED)
                self.tabla_compra.setCellWidget(fila, 7, EstadoBadge(estado.capitalize(), color))
            self._actualizar_paginacion(
                "compra",
                resultado["total"],
                self.lbl_pagina_compra,
                self.btn_compra_anterior,
                self.btn_compra_siguiente,
            )
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar compras.")
        except Exception:
            logger.exception("Fallo al cargar compras desde OC")
            MessageBox.critical(self, "Error", "No se pudo cargar el listado de facturas.")
        finally:
            session.close()

    def nueva_factura_desde_oc(self) -> None:
        session = self.session_factory()
        try:
            resultado = CompraOCService.listar_ocs(session, por_pagina=200, id_usuario=self.usuario.id_usuario)
            candidatas = [oc for oc in resultado["items"] if oc.cantidad_recibida > oc.cantidad_facturada]
            if not candidatas:
                MessageBox.information(
                    self, "Nada que facturar", "No hay órdenes de compra con mercancía recibida pendiente de facturar."
                )
                return
            etiquetas = [
                f"{oc.numero_oc} — {oc.proveedor.nombre_razon_social if oc.proveedor else ''}" for oc in candidatas
            ]
            etiqueta, ok = QInputDialog.getItem(
                self, "Nueva Factura", "Seleccione la orden de compra:", etiquetas, editable=False
            )
            if not ok:
                return
            oc = candidatas[etiquetas.index(etiqueta)]

            dialogo = CompraDesdeOCFormDialog(session, self.usuario.id_usuario, oc, parent=self)
            if dialogo.exec() and dialogo.compra_creada is not None:
                self.cargar_compras()
                self.cargar_ocs()
                MessageBox.information(
                    self, "Factura registrada", f"Compra {dialogo.compra_creada.numero_compra} registrada con éxito."
                )
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para registrar compras.")
        finally:
            session.close()

    # ── Paginacion compartida ────────────────────────────────────────────

    def _actualizar_paginacion(
        self, clave: str, total: int, lbl_pagina: QLabel, btn_anterior: QPushButton, btn_siguiente: QPushButton
    ) -> None:
        self.total_paginas[clave] = max(1, -(-total // POR_PAGINA))
        self.paginas[clave] = min(self.paginas[clave], self.total_paginas[clave])
        lbl_pagina.setText(f"Página {self.paginas[clave]} de {self.total_paginas[clave]} ({total})")
        btn_anterior.setEnabled(self.paginas[clave] > 1)
        btn_siguiente.setEnabled(self.paginas[clave] < self.total_paginas[clave])

    def _pagina_anterior(self, clave: str) -> None:
        if self.paginas[clave] > 1:
            self.paginas[clave] -= 1
            [self.cargar_ocs, self.cargar_nrs, self.cargar_compras][["oc", "nr", "compra"].index(clave)]()

    def _pagina_siguiente(self, clave: str) -> None:
        if self.paginas[clave] < self.total_paginas[clave]:
            self.paginas[clave] += 1
            [self.cargar_ocs, self.cargar_nrs, self.cargar_compras][["oc", "nr", "compra"].index(clave)]()
