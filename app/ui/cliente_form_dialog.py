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

from app.db.models import CategoriaCliente, Cliente, Vendedor
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


class ClienteFormDialog(QDialog):
    """
    Diálogo moderno, horizontal y centrado para la creación y edición de clientes.
    Utiliza Font Awesome para todos los íconos y cuenta con selector fiscal (J, G, V, E, P).
    """

    def __init__(self, session: Session, cliente: Cliente | None = None, parent=None):
        super().__init__(parent)
        self.session = session
        self.cliente = cliente
        self.setWindowTitle("Editar Cliente" if cliente else "Nuevo Cliente")
        self.setFixedSize(860, 480)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()

        if cliente:
            self._precargar(cliente)

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
        fa_icon_name = "fa5s.user-edit" if self.cliente else "fa5s.user-plus"
        icon_lbl.setPixmap(qta.icon(fa_icon_name, color=COLOR_PRIMARY).pixmap(QSize(22, 22)))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(38, 38)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titles_layout = QVBoxLayout()
        titles_layout.setSpacing(1)
        titles_layout.setContentsMargins(0, 0, 0, 0)

        titulo_text = "Editar Cliente" if self.cliente else "Nuevo Cliente"
        lbl_titulo = QLabel(titulo_text)
        lbl_titulo.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        lbl_subtitulo = QLabel("Complete los datos requeridos para registrar la ficha comercial del cliente.")
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
        self.codigo_input.setPlaceholderText("Ej: CLI-001")
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
        self.identificacion_input.setFixedHeight(32)

        id_hbox.addWidget(self.tipo_id_combo)
        id_hbox.addWidget(self.identificacion_input)
        grid1.addLayout(id_hbox, 1, 1)

        # Razón Social
        lbl_nom = QLabel("Razón Social o Nombre Completo <span style='color: #DC2626;'>*</span>")
        lbl_nom.setProperty("class", "FormLabel")
        self.nombre_input = QLineEdit()
        self.nombre_input.setPlaceholderText("Ej: Distribuidora Central, C.A.")
        self.nombre_input.setFixedHeight(32)
        grid1.addWidget(lbl_nom, 2, 0, 1, 2)
        grid1.addWidget(self.nombre_input, 3, 0, 1, 2)

        # Vendedor Asignado
        lbl_vend = QLabel("Vendedor Asignado")
        lbl_vend.setProperty("class", "FormLabel")
        self.vendedor_combo = QComboBox()
        self.vendedor_combo.setFixedHeight(32)
        self.vendedor_combo.addItem("Sin asignar", None)
        for vendedor in (
            self.session.query(Vendedor).filter(Vendedor.estado_vendedor == "ACTIVO").order_by(Vendedor.nombre_vendedor)
        ):
            self.vendedor_combo.addItem(vendedor.nombre_vendedor, vendedor.id_vendedor)

        grid1.addWidget(lbl_vend, 4, 0)
        grid1.addWidget(self.vendedor_combo, 5, 0)

        # Categoría
        lbl_cat = QLabel("Categoría de Cliente")
        lbl_cat.setProperty("class", "FormLabel")
        self.categoria_combo = QComboBox()
        self.categoria_combo.setFixedHeight(32)
        self.categoria_combo.addItem("Sin asignar", None)
        for categoria in self.session.query(CategoriaCliente).order_by(CategoriaCliente.nombre):
            self.categoria_combo.addItem(categoria.nombre, categoria.id_categoria_cliente)

        grid1.addWidget(lbl_cat, 4, 1)
        grid1.addWidget(self.categoria_combo, 5, 1)

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
        self.telefono_input.setFixedHeight(32)
        grid2.addWidget(lbl_tel, 0, 0)
        grid2.addWidget(self.telefono_input, 1, 0)

        # Email
        lbl_email = QLabel("Correo Electrónico")
        lbl_email.setProperty("class", "FormLabel")
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("Ej: contacto@cliente.com")
        self.email_input.setFixedHeight(32)
        grid2.addWidget(lbl_email, 0, 1)
        grid2.addWidget(self.email_input, 1, 1)

        # Dirección
        lbl_dir = QLabel("Dirección Fiscal / Entrega")
        lbl_dir.setProperty("class", "FormLabel")
        self.direccion_input = QLineEdit()
        self.direccion_input.setPlaceholderText("Ej: Av. Principal, Edificio Central, Piso 2")
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
        self.dias_credito_input.setToolTip("0 = cliente de contado, no podrá facturarse a crédito")
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

        self.btn_guardar = QPushButton("Guardar Cliente")
        self.btn_guardar.setIcon(qta.icon("fa5s.save", color="#FFFFFF"))
        self.btn_guardar.setObjectName("BtnPrimary")
        self.btn_guardar.setFixedHeight(36)
        self.btn_guardar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guardar.clicked.connect(self._validar_y_aceptar)

        footer_layout.addWidget(self.btn_cancelar)
        footer_layout.addWidget(self.btn_guardar)

        root.addLayout(footer_layout)

    def _precargar(self, cliente: Cliente):
        self.codigo_input.setText(cliente.codigo_cliente or "")

        # Extraer prefijo fiscal (J, G, V, E, P) y número
        ident = (cliente.identificacion_cliente or "").strip().upper()
        prefix = "V"
        numero = ident
        if ident:
            for p in ["J", "G", "V", "E", "P"]:
                if ident.startswith(f"{p}-"):
                    prefix = p
                    numero = ident[2:]
                    break
                elif ident.startswith(p) and len(ident) > 1 and (ident[1].isdigit() or ident[1] == "-"):
                    prefix = p
                    numero = ident[1:].lstrip("-")
                    break

        idx_pref = self.tipo_id_combo.findText(prefix)
        if idx_pref >= 0:
            self.tipo_id_combo.setCurrentIndex(idx_pref)
        self.identificacion_input.setText(numero)

        self.nombre_input.setText(cliente.nombre_razon_social or "")
        self.telefono_input.setText(cliente.telefono or "")
        self.email_input.setText(cliente.email or "")
        self.direccion_input.setText(cliente.direccion or "")
        self.limite_credito_input.setValue(float(cliente.limite_credito or 0))
        self.dias_credito_input.setValue(cliente.dias_credito or 0)

        idx_vendedor = self.vendedor_combo.findData(cliente.vendedor_cliente)
        self.vendedor_combo.setCurrentIndex(idx_vendedor if idx_vendedor >= 0 else 0)

        idx_categoria = self.categoria_combo.findData(cliente.id_categoria_cliente)
        self.categoria_combo.setCurrentIndex(idx_categoria if idx_categoria >= 0 else 0)

    def _validar_y_aceptar(self):
        if not self.codigo_input.text().strip():
            QMessageBox.warning(self, "Dato requerido", "El código del cliente es obligatorio.")
            self.codigo_input.setFocus()
            return
        if not self.identificacion_input.text().strip():
            QMessageBox.warning(self, "Dato requerido", "El número de ID Fiscal / Identificación es obligatorio.")
            self.identificacion_input.setFocus()
            return
        if not self.nombre_input.text().strip():
            QMessageBox.warning(self, "Dato requerido", "La razón social o nombre del cliente es obligatoria.")
            self.nombre_input.setFocus()
            return
        self.accept()

    def get_data(self) -> dict:
        tipo = self.tipo_id_combo.currentText().strip()
        num = self.identificacion_input.text().strip()

        if num:
            num_upper = num.upper()
            prefijos = ["J", "G", "V", "E", "P"]
            if any(num_upper.startswith(f"{p}-") for p in prefijos):
                ident_final = num_upper
            elif any(num_upper.startswith(p) and len(num_upper) > 1 and num_upper[1].isdigit() for p in prefijos):
                ident_final = f"{num_upper[0]}-{num_upper[1:]}"
            else:
                ident_final = f"{tipo}-{num}"
        else:
            ident_final = None

        return {
            "codigo_cliente": self.codigo_input.text().strip() or None,
            "identificacion_cliente": ident_final,
            "nombre_razon_social": self.nombre_input.text().strip(),
            "telefono": self.telefono_input.text().strip() or None,
            "email": self.email_input.text().strip() or None,
            "direccion": self.direccion_input.text().strip() or None,
            "limite_credito": self.limite_credito_input.value(),
            "dias_credito": self.dias_credito_input.value(),
            "vendedor_cliente": self.vendedor_combo.currentData(),
            "id_categoria_cliente": self.categoria_combo.currentData(),
        }
