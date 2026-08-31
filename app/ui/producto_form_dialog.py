"""Dialogo de creacion/edicion de productos de inventario. Mismo patron visual que
app/ui/cliente_form_dialog.py (paleta y tipografia de app/ui/styles.py, layout de 2
columnas con tarjetas, Font Awesome via qtawesome) para mantener consistencia entre
modulos."""

import qtawesome as qta
from PySide6.QtCore import QDate, QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from app.db.models import Inventario
from app.services.categorias import CategoriaService
from app.services.inventario import PrecioService
from app.services.permisos import PermisoDenegadoError
from app.ui.styles import (
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_FIELD_BG,
    COLOR_PRIMARY,
    COLOR_PRIMARY_DARK,
    COLOR_PRIMARY_LIGHT,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MUTED,
    FONT_FAMILY,
    ICON_CHECK_URL,
    ICON_CHEVRON_DOWN_URL,
    ICON_CHEVRON_UP_URL,
    aplicar_sombra,
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
QLineEdit:disabled, QComboBox:disabled, QDoubleSpinBox:disabled, QDateEdit:disabled {{
    background-color: {COLOR_CONTENT_BG};
    color: {COLOR_TEXT_LIGHT};
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
QCheckBox {{
    font-size: 12px;
    color: {COLOR_TEXT_DARK};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    background-color: #FFFFFF;
}}
QCheckBox::indicator:hover {{
    border-color: {COLOR_PRIMARY};
}}
QCheckBox::indicator:checked {{
    background-color: {COLOR_PRIMARY};
    border-color: {COLOR_PRIMARY};
    image: url({ICON_CHECK_URL});
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
QPushButton#BtnAddCategoria {{
    background-color: #EFF6FF;
    color: {COLOR_PRIMARY};
    border: 1px solid #BFDBFE;
    border-radius: 6px;
    font-weight: bold;
}}
QPushButton#BtnAddCategoria:hover {{
    background-color: #DBEAFE;
}}
"""


class ProductoFormDialog(QDialog):
    """Dialogo horizontal para creacion/edicion de productos, con precio de venta
    (ProductoPrecio) integrado en el mismo formulario -- un producto sin precio no se
    puede vender, tiene sentido capturarlo en el mismo paso que el alta."""

    def __init__(self, session: Session, id_usuario: int | None, producto: Inventario | None = None, parent=None):
        super().__init__(parent)
        self.session = session
        self.id_usuario = id_usuario
        self.producto = producto
        self.setWindowTitle("Editar Producto" if producto else "Nuevo Producto")
        self.setFixedSize(860, 520)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()

        if producto:
            self._precargar(producto)

    # ── Construccion de la UI ─────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # ── Encabezado ──
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        icon_lbl = QLabel()
        fa_icon_name = "fa5s.box-open" if self.producto else "fa5s.box"
        icon_lbl.setPixmap(qta.icon(fa_icon_name, color=COLOR_PRIMARY).pixmap(QSize(22, 22)))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(38, 38)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titles_layout = QVBoxLayout()
        titles_layout.setSpacing(1)
        titles_layout.setContentsMargins(0, 0, 0, 0)

        titulo_text = "Editar Producto" if self.producto else "Nuevo Producto"
        lbl_titulo = QLabel(titulo_text)
        lbl_titulo.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        lbl_subtitulo = QLabel("Complete los datos del producto y su precio de venta.")
        lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")

        titles_layout.addWidget(lbl_titulo)
        titles_layout.addWidget(lbl_subtitulo)

        header_layout.addWidget(icon_lbl)
        header_layout.addLayout(titles_layout)
        header_layout.addStretch()

        root.addWidget(header_widget)

        # ── Contenido: 2 columnas ──
        content_layout = QHBoxLayout()
        content_layout.setSpacing(14)
        content_layout.setContentsMargins(0, 0, 0, 0)

        content_layout.addWidget(self._make_columna_datos_generales(), 1)
        content_layout.addWidget(self._make_columna_inventario_precio(), 1)

        root.addLayout(content_layout)
        root.addLayout(self._make_footer())

    def _make_columna_datos_generales(self) -> QWidget:
        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        titulo = QLabel("DATOS GENERALES")
        titulo.setProperty("class", "SectionTitle")
        layout.addWidget(titulo)

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # Código
        lbl_cod = QLabel("Código <span style='color: #DC2626;'>*</span>")
        lbl_cod.setProperty("class", "FormLabel")
        self.codigo_input = QLineEdit()
        self.codigo_input.setPlaceholderText("Ej: PROD-001")
        self.codigo_input.setFixedHeight(32)
        grid.addWidget(lbl_cod, 0, 0)
        grid.addWidget(self.codigo_input, 1, 0)

        # Categoría (+ boton de alta rapida)
        lbl_cat = QLabel("Categoría <span style='color: #DC2626;'>*</span>")
        lbl_cat.setProperty("class", "FormLabel")
        grid.addWidget(lbl_cat, 0, 1)

        cat_hbox = QHBoxLayout()
        cat_hbox.setSpacing(4)
        cat_hbox.setContentsMargins(0, 0, 0, 0)
        self.categoria_combo = QComboBox()
        self.categoria_combo.setFixedHeight(32)
        self._cargar_categorias()

        btn_nueva_categoria = QPushButton()
        btn_nueva_categoria.setObjectName("BtnAddCategoria")
        btn_nueva_categoria.setIcon(qta.icon("fa5s.plus", color=COLOR_PRIMARY))
        btn_nueva_categoria.setFixedSize(32, 32)
        btn_nueva_categoria.setToolTip("Crear categoría nueva")
        btn_nueva_categoria.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_nueva_categoria.clicked.connect(self._crear_categoria_rapida)

        cat_hbox.addWidget(self.categoria_combo)
        cat_hbox.addWidget(btn_nueva_categoria)
        grid.addLayout(cat_hbox, 1, 1)

        # Nombre
        lbl_nom = QLabel("Nombre del Producto <span style='color: #DC2626;'>*</span>")
        lbl_nom.setProperty("class", "FormLabel")
        self.nombre_input = QLineEdit()
        self.nombre_input.setPlaceholderText("Ej: Refresco Cola 2L")
        self.nombre_input.setFixedHeight(32)
        grid.addWidget(lbl_nom, 2, 0, 1, 2)
        grid.addWidget(self.nombre_input, 3, 0, 1, 2)

        # Descripción
        lbl_desc = QLabel("Descripción")
        lbl_desc.setProperty("class", "FormLabel")
        self.descripcion_input = QLineEdit()
        self.descripcion_input.setPlaceholderText("Detalle adicional del producto (opcional)")
        self.descripcion_input.setFixedHeight(32)
        grid.addWidget(lbl_desc, 4, 0, 1, 2)
        grid.addWidget(self.descripcion_input, 5, 0, 1, 2)

        # Fecha de vencimiento
        self.tiene_vencimiento_check = QCheckBox("Tiene fecha de vencimiento")
        self.tiene_vencimiento_check.toggled.connect(self._toggle_vencimiento)
        grid.addWidget(self.tiene_vencimiento_check, 6, 0, 1, 2)

        self.vencimiento_input = QDateEdit()
        self.vencimiento_input.setCalendarPopup(True)
        self.vencimiento_input.setDisplayFormat("dd/MM/yyyy")
        self.vencimiento_input.setDate(QDate.currentDate().addDays(30))
        self.vencimiento_input.setFixedHeight(32)
        self.vencimiento_input.setEnabled(False)
        grid.addWidget(self.vencimiento_input, 7, 0, 1, 2)

        layout.addLayout(grid)
        layout.addStretch()
        return card

    def _make_columna_inventario_precio(self) -> QWidget:
        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        titulo = QLabel("INVENTARIO Y PRECIO")
        titulo.setProperty("class", "SectionTitle")
        layout.addWidget(titulo)

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # Costo
        lbl_costo = QLabel("Costo ($) <span style='color: #DC2626;'>*</span>")
        lbl_costo.setProperty("class", "FormLabel")
        self.costo_input = QDoubleSpinBox()
        self.costo_input.setRange(0, 999999999.99)
        self.costo_input.setDecimals(2)
        self.costo_input.setPrefix("$ ")
        self.costo_input.setFixedHeight(32)
        self.costo_input.valueChanged.connect(self._actualizar_margen)
        grid.addWidget(lbl_costo, 0, 0)
        grid.addWidget(self.costo_input, 1, 0)

        # Precio de venta
        lbl_precio = QLabel("Precio de Venta ($)")
        lbl_precio.setProperty("class", "FormLabel")
        self.precio_venta_input = QDoubleSpinBox()
        self.precio_venta_input.setRange(0, 999999999.99)
        self.precio_venta_input.setDecimals(2)
        self.precio_venta_input.setPrefix("$ ")
        self.precio_venta_input.setFixedHeight(32)
        self.precio_venta_input.valueChanged.connect(self._actualizar_margen)
        grid.addWidget(lbl_precio, 0, 1)
        grid.addWidget(self.precio_venta_input, 1, 1)

        self.lbl_margen = QLabel("Margen: 0.00%")
        self.lbl_margen.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_MUTED}; margin-top: -4px;")
        grid.addWidget(self.lbl_margen, 2, 0, 1, 2)

        # Cantidad en stock -- "Cantidad por Caja" se saco del formulario (auditoria de
        # Productos 2026-08-28): se capturaba y guardaba, pero ningun flujo de ventas/
        # compras/alertas la usaba, solo cantidad_unidad cuenta para el stock real. La
        # columna sigue existiendo en inventario (no se toco el schema), por si se retoma
        # con una conversion caja->unidad real mas adelante.
        lbl_unidad = QLabel("Cantidad en Stock")
        lbl_unidad.setProperty("class", "FormLabel")
        self.cantidad_unidad_input = QDoubleSpinBox()
        self.cantidad_unidad_input.setRange(0, 999999.99)
        self.cantidad_unidad_input.setDecimals(2)
        self.cantidad_unidad_input.setFixedHeight(32)
        grid.addWidget(lbl_unidad, 3, 0, 1, 2)
        grid.addWidget(self.cantidad_unidad_input, 4, 0, 1, 2)

        # Umbral para el reporte "Stock bajo minimo" (migrations/0037). 0 = sin minimo
        # configurado, el producto no aparece en ese reporte.
        lbl_minima = QLabel("Stock Mínimo (alerta)")
        lbl_minima.setProperty("class", "FormLabel")
        self.cantidad_minima_input = QDoubleSpinBox()
        self.cantidad_minima_input.setRange(0, 999999.99)
        self.cantidad_minima_input.setDecimals(2)
        self.cantidad_minima_input.setFixedHeight(32)
        grid.addWidget(lbl_minima, 5, 0, 1, 2)
        grid.addWidget(self.cantidad_minima_input, 6, 0, 1, 2)

        layout.addLayout(grid)
        layout.addStretch()
        return card

    def _make_footer(self) -> QHBoxLayout:
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 4, 0, 0)
        footer_layout.setSpacing(10)
        footer_layout.addStretch()

        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.setIcon(qta.icon("fa5s.times", color="#475569"))
        self.btn_cancelar.setObjectName("BtnSecondary")
        self.btn_cancelar.setFixedHeight(36)
        self.btn_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancelar.clicked.connect(self.reject)

        self.btn_guardar = QPushButton("Guardar Producto")
        self.btn_guardar.setIcon(qta.icon("fa5s.save", color="#FFFFFF"))
        self.btn_guardar.setObjectName("BtnPrimary")
        self.btn_guardar.setFixedHeight(36)
        self.btn_guardar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guardar.clicked.connect(self._validar_y_aceptar)

        footer_layout.addWidget(self.btn_cancelar)
        footer_layout.addWidget(self.btn_guardar)
        return footer_layout

    # ── Categorías ─────────────────────────────────────────────────────────

    def _cargar_categorias(self, seleccionar_id: int | None = None) -> None:
        self.categoria_combo.clear()
        try:
            categorias = CategoriaService.listar(self.session, id_usuario=self.id_usuario)
        except PermisoDenegadoError:
            # 'inventario'/'crear' o 'editar' no implican 'categorias'/'ver' en el catalogo
            # de permisos -- son recursos independientes (auditoria de Productos
            # 2026-08-28). Si un rol custom armado desde roles_permisos_panel.py tiene el
            # primero sin el segundo, sin este catch el PermisoDenegadoError explotaba en
            # medio de la construccion del dialogo (antes de que el usuario llegara a ver
            # nada) en vez de dar un mensaje que apunte al recurso real que falta.
            QMessageBox.warning(
                self,
                "Sin permiso",
                "No tienes permiso para consultar categorías ('categorias'/'ver'), "
                "necesario para poder asignarle una al producto.",
            )
            self.categoria_combo.setEnabled(False)
            return
        for categoria in categorias:
            self.categoria_combo.addItem(categoria.nombre, categoria.id_categoria)
        if seleccionar_id is not None:
            idx = self.categoria_combo.findData(seleccionar_id)
            if idx >= 0:
                self.categoria_combo.setCurrentIndex(idx)

    def _crear_categoria_rapida(self) -> None:
        nombre, ok = QInputDialog.getText(self, "Nueva categoría", "Nombre de la categoría:")
        nombre = nombre.strip()
        if not ok or not nombre:
            return
        try:
            categoria = CategoriaService.crear(self.session, nombre=nombre, creado_por=self.id_usuario)
        except Exception as exc:
            QMessageBox.warning(self, "No se pudo crear la categoría", str(exc))
            return
        self._cargar_categorias(seleccionar_id=categoria.id_categoria)

    # ── Vencimiento / margen ──────────────────────────────────────────────

    def _toggle_vencimiento(self, activo: bool) -> None:
        self.vencimiento_input.setEnabled(activo)

    def _actualizar_margen(self) -> None:
        costo = self.costo_input.value()
        precio = self.precio_venta_input.value()
        margen = ((precio - costo) / costo * 100) if costo else 0.0
        self.lbl_margen.setText(f"Margen: {margen:.2f}%")

    # ── Precarga (edición) ────────────────────────────────────────────────

    def _precargar(self, producto: Inventario) -> None:
        self.codigo_input.setText(producto.cod_producto or "")
        self.nombre_input.setText(producto.nombre_producto or "")
        self.descripcion_input.setText(producto.descripcion_producto or "")
        self.costo_input.setValue(float(producto.costo_producto or 0))
        self.cantidad_unidad_input.setValue(float(producto.cantidad_unidad or 0))
        self.cantidad_minima_input.setValue(float(producto.cantidad_minima or 0))

        idx_categoria = self.categoria_combo.findData(producto.id_categoria)
        if idx_categoria >= 0:
            self.categoria_combo.setCurrentIndex(idx_categoria)

        if producto.fecha_vencimiento:
            self.tiene_vencimiento_check.setChecked(True)
            self.vencimiento_input.setDate(QDate(producto.fecha_vencimiento))

        precio = PrecioService.obtener_precio(self.session, producto.id_producto, id_usuario=self.id_usuario)
        if precio:
            self.precio_venta_input.setValue(float(precio.precio_venta or 0))
        self._actualizar_margen()

    # ── Validación / datos ────────────────────────────────────────────────

    def _validar_y_aceptar(self) -> None:
        if not self.codigo_input.text().strip():
            QMessageBox.warning(self, "Dato requerido", "El código del producto es obligatorio.")
            self.codigo_input.setFocus()
            return
        if not self.nombre_input.text().strip():
            QMessageBox.warning(self, "Dato requerido", "El nombre del producto es obligatorio.")
            self.nombre_input.setFocus()
            return
        if self.categoria_combo.currentData() is None:
            QMessageBox.warning(self, "Dato requerido", "Seleccione o cree una categoría para el producto.")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "cod_producto": self.codigo_input.text().strip(),
            "nombre_producto": self.nombre_input.text().strip(),
            "descripcion_producto": self.descripcion_input.text().strip() or None,
            "id_categoria": self.categoria_combo.currentData(),
            "costo_producto": self.costo_input.value(),
            "cantidad_unidad": self.cantidad_unidad_input.value(),
            "cantidad_minima": self.cantidad_minima_input.value(),
            "fecha_vencimiento": (
                self.vencimiento_input.date().toPython() if self.tiene_vencimiento_check.isChecked() else None
            ),
        }

    def get_precio_venta(self) -> float:
        return self.precio_venta_input.value()
