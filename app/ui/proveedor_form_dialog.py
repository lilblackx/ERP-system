import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from app.db.models import Proveedor
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
    COLOR_TEXT_MUTED,
    FONT_FAMILY,
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
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: #FFFFFF;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
    min-height: 20px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1.5px solid {COLOR_PRIMARY};
    background-color: #FFFFFF;
}}
QLineEdit::placeholder {{
    color: #94A3B8;
    font-size: 12px;
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
"""


class ProveedorFormDialog(QDialog):
    """
    Diálogo de creación/edición de proveedores -- mismo patrón visual que
    ClienteFormDialog (Proveedor es un subconjunto de los campos de Cliente: sin
    vendedor asignado ni categoría, que no aplican a un proveedor).
    """

    def __init__(self, session: Session, proveedor: Proveedor | None = None, parent=None):
        super().__init__(parent)
        self.session = session
        self.proveedor = proveedor
        self.setWindowTitle("Editar Proveedor" if proveedor else "Nuevo Proveedor")
        self.setFixedSize(860, 420)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()

        if proveedor:
            self._precargar(proveedor)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # ── Encabezado Corporativo ──
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        icon_lbl = QLabel()
        fa_icon_name = "fa5s.user-edit" if self.proveedor else "fa5s.truck-loading"
        icon_lbl.setPixmap(qta.icon(fa_icon_name, color=COLOR_PRIMARY).pixmap(QSize(22, 22)))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(38, 38)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titles_layout = QVBoxLayout()
        titles_layout.setSpacing(1)
        titles_layout.setContentsMargins(0, 0, 0, 0)

        titulo_text = "Editar Proveedor" if self.proveedor else "Nuevo Proveedor"
        lbl_titulo = QLabel(titulo_text)
        lbl_titulo.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        lbl_subtitulo = QLabel("Complete los datos requeridos para registrar la ficha del proveedor.")
        lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")

        titles_layout.addWidget(lbl_titulo)
        titles_layout.addWidget(lbl_subtitulo)

        header_layout.addWidget(icon_lbl)
        header_layout.addLayout(titles_layout)
        header_layout.addStretch()

        root.addWidget(header_widget)

        # ── Contenido Horizontal: 2 Columnas de Tarjetas ──
        content_layout = QHBoxLayout()
        content_layout.setSpacing(14)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # ── COLUMNA 1: Datos Generales y Fiscales ──
        card_col1 = QWidget()
        card_col1.setObjectName("SectionCard")
        aplicar_sombra(card_col1)
        col1_layout = QVBoxLayout(card_col1)
        col1_layout.setContentsMargins(16, 12, 16, 14)
        col1_layout.setSpacing(8)

        sec1_title = QLabel("DATOS GENERALES Y FISCALES")
        sec1_title.setProperty("class", "SectionTitle")
        col1_layout.addWidget(sec1_title)

        grid1 = QGridLayout()
        grid1.setSpacing(8)
        grid1.setColumnStretch(0, 1)
        grid1.setColumnStretch(1, 1)

        # Código
        lbl_cod = QLabel("Código <span style='color: #DC2626;'>*</span>")
        lbl_cod.setProperty("class", "FormLabel")
        self.codigo_input = QLineEdit()
        self.codigo_input.setPlaceholderText("Ej: PROV-001")
        self.codigo_input.setMaxLength(20)
        self.codigo_input.setFixedHeight(32)
        grid1.addWidget(lbl_cod, 0, 0)
        grid1.addWidget(self.codigo_input, 1, 0)

        # ID Fiscal
        lbl_id = QLabel("ID Fiscal / Identificación <span style='color: #DC2626;'>*</span>")
        lbl_id.setProperty("class", "FormLabel")
        grid1.addWidget(lbl_id, 0, 1)

        id_hbox = QHBoxLayout()
        id_hbox.setSpacing(4)
        id_hbox.setContentsMargins(0, 0, 0, 0)

        self.tipo_id_combo = QComboBox()
        self.tipo_id_combo.addItems(["J", "G", "V", "E", "P"])
        self.tipo_id_combo.setFixedWidth(52)
        self.tipo_id_combo.setFixedHeight(32)

        self.identificacion_input = QLineEdit()
        self.identificacion_input.setPlaceholderText("Ej: 30489713 / 12345678-0")
        self.identificacion_input.setMaxLength(20)
        self.identificacion_input.setFixedHeight(32)

        id_hbox.addWidget(self.tipo_id_combo)
        id_hbox.addWidget(self.identificacion_input)
        grid1.addLayout(id_hbox, 1, 1)

        # Razón Social
        lbl_nom = QLabel("Razón Social o Nombre Completo <span style='color: #DC2626;'>*</span>")
        lbl_nom.setProperty("class", "FormLabel")
        self.nombre_input = QLineEdit()
        self.nombre_input.setPlaceholderText("Ej: Suministros Industriales, C.A.")
        self.nombre_input.setMaxLength(200)
        self.nombre_input.setFixedHeight(32)
        grid1.addWidget(lbl_nom, 2, 0, 1, 2)
        grid1.addWidget(self.nombre_input, 3, 0, 1, 2)

        col1_layout.addLayout(grid1)
        col1_layout.addStretch()

        # ── COLUMNA 2: Contacto y Condiciones Comerciales ──
        card_col2 = QWidget()
        card_col2.setObjectName("SectionCard")
        aplicar_sombra(card_col2)
        col2_layout = QVBoxLayout(card_col2)
        col2_layout.setContentsMargins(16, 12, 16, 14)
        col2_layout.setSpacing(8)

        sec2_title = QLabel("CONTACTO Y CONDICIONES COMERCIALES")
        sec2_title.setProperty("class", "SectionTitle")
        col2_layout.addWidget(sec2_title)

        grid2 = QGridLayout()
        grid2.setSpacing(8)
        grid2.setColumnStretch(0, 1)
        grid2.setColumnStretch(1, 1)

        # Teléfono
        lbl_tel = QLabel("Teléfono")
        lbl_tel.setProperty("class", "FormLabel")
        self.telefono_input = QLineEdit()
        self.telefono_input.setPlaceholderText("Ej: 0414-1234567")
        self.telefono_input.setMaxLength(20)
        self.telefono_input.setFixedHeight(32)
        grid2.addWidget(lbl_tel, 0, 0)
        grid2.addWidget(self.telefono_input, 1, 0)

        # Email
        lbl_email = QLabel("Correo Electrónico")
        lbl_email.setProperty("class", "FormLabel")
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("Ej: contacto@proveedor.com")
        self.email_input.setMaxLength(150)
        self.email_input.setFixedHeight(32)
        grid2.addWidget(lbl_email, 0, 1)
        grid2.addWidget(self.email_input, 1, 1)

        # Dirección
        lbl_dir = QLabel("Dirección")
        lbl_dir.setProperty("class", "FormLabel")
        self.direccion_input = QLineEdit()
        self.direccion_input.setPlaceholderText("Ej: Av. Principal, Zona Industrial, Galpón 3")
        self.direccion_input.setMaxLength(255)
        self.direccion_input.setFixedHeight(32)
        grid2.addWidget(lbl_dir, 2, 0, 1, 2)
        grid2.addWidget(self.direccion_input, 3, 0, 1, 2)

        # Límite de Crédito
        lbl_limite = QLabel("Límite de Crédito ($)")
        lbl_limite.setProperty("class", "FormLabel")
        self.limite_credito_input = QDoubleSpinBox()
        self.limite_credito_input.setRange(0, 999999999.99)
        self.limite_credito_input.setDecimals(2)
        self.limite_credito_input.setPrefix("$ ")
        self.limite_credito_input.setFixedHeight(32)
        grid2.addWidget(lbl_limite, 4, 0)
        grid2.addWidget(self.limite_credito_input, 5, 0)

        # Días de Crédito
        lbl_dias = QLabel("Días de Crédito")
        lbl_dias.setProperty("class", "FormLabel")
        self.dias_credito_input = QSpinBox()
        self.dias_credito_input.setRange(0, 365)
        self.dias_credito_input.setSuffix(" días")
        self.dias_credito_input.setFixedHeight(32)
        self.dias_credito_input.setToolTip("0 = proveedor de contado, no se le podrá comprar a crédito")
        grid2.addWidget(lbl_dias, 4, 1)
        grid2.addWidget(self.dias_credito_input, 5, 1)

        col2_layout.addLayout(grid2)
        col2_layout.addStretch()

        content_layout.addWidget(card_col1, 1)
        content_layout.addWidget(card_col2, 1)

        root.addLayout(content_layout)

        # ── Footer con Botones de Acción ──
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

        self.btn_guardar = QPushButton("Guardar Proveedor")
        self.btn_guardar.setIcon(qta.icon("fa5s.save", color="#FFFFFF"))
        self.btn_guardar.setObjectName("BtnPrimary")
        self.btn_guardar.setFixedHeight(36)
        self.btn_guardar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guardar.clicked.connect(self._validar_y_aceptar)

        footer_layout.addWidget(self.btn_cancelar)
        footer_layout.addWidget(self.btn_guardar)

        root.addLayout(footer_layout)

    def _precargar(self, proveedor: Proveedor):
        self.codigo_input.setText(proveedor.codigo_proveedor or "")

        # id_legal contiene solo la letra (V, J, G, E, P)
        # identificacion_proveedor contiene solo el número
        prefix = (proveedor.id_legal or "").strip().upper() or "J"
        numero = proveedor.identificacion_proveedor or ""

        idx_pref = self.tipo_id_combo.findText(prefix)
        if idx_pref >= 0:
            self.tipo_id_combo.setCurrentIndex(idx_pref)
        self.identificacion_input.setText(numero)

        self.nombre_input.setText(proveedor.nombre_razon_social or "")
        self.telefono_input.setText(proveedor.telefono or "")
        self.email_input.setText(proveedor.email or "")
        self.direccion_input.setText(proveedor.direccion or "")
        self.limite_credito_input.setValue(float(proveedor.limite_credito or 0))
        self.dias_credito_input.setValue(proveedor.dias_credito or 0)

    def _validar_y_aceptar(self):
        if not self.codigo_input.text().strip():
            QMessageBox.warning(self, "Dato requerido", "El código del proveedor es obligatorio.")
            self.codigo_input.setFocus()
            return
        if not self.identificacion_input.text().strip():
            QMessageBox.warning(self, "Dato requerido", "El número de ID Fiscal / Identificación es obligatorio.")
            self.identificacion_input.setFocus()
            return
        if not self.nombre_input.text().strip():
            QMessageBox.warning(self, "Dato requerido", "La razón social o nombre del proveedor es obligatoria.")
            self.nombre_input.setFocus()
            return
        self.accept()

    def get_data(self) -> dict:
        tipo = self.tipo_id_combo.currentText().strip()
        num = self.identificacion_input.text().strip()

        return {
            "codigo_proveedor": self.codigo_input.text().strip() or None,
            "id_legal": tipo if tipo else None,
            "identificacion_proveedor": num if num else None,
            "nombre_razon_social": self.nombre_input.text().strip(),
            "telefono": self.telefono_input.text().strip() or None,
            "email": self.email_input.text().strip() or None,
            "direccion": self.direccion_input.text().strip() or None,
            "limite_credito": self.limite_credito_input.value(),
            "dias_credito": self.dias_credito_input.value(),
        }
