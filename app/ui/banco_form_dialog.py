import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from app.db.models import Banco
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
    margin-bottom: 6px;
}}
QLabel.SectionTitle {{
    font-size: 11px;
    font-weight: bold;
    color: {COLOR_PRIMARY};
    letter-spacing: 0.8px;
    padding-bottom: 2px;
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


class BancoFormDialog(QDialog):
    """Diálogo de creación/edición de bancos."""

    def __init__(self, session: Session, banco: Banco | None = None, parent=None):
        super().__init__(parent)
        self.session = session
        self.banco = banco
        self.setWindowTitle("Editar Banco" if banco else "Nuevo Banco")
        self.setFixedSize(800, 520)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()

        if banco:
            self._precargar(banco)

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
        fa_icon_name = "fa5s.university" if self.banco else "fa5s.plus-circle"
        icon_lbl.setPixmap(qta.icon(fa_icon_name, color=COLOR_PRIMARY).pixmap(QSize(22, 22)))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(38, 38)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titles_layout = QVBoxLayout()
        titles_layout.setSpacing(1)
        titles_layout.setContentsMargins(0, 0, 0, 0)

        titulo_text = "Editar Banco" if self.banco else "Nuevo Banco"
        lbl_titulo = QLabel(titulo_text)
        lbl_titulo.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        lbl_subtitulo = QLabel("Complete los datos requeridos para registrar el banco.")
        lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")

        titles_layout.addWidget(lbl_titulo)
        titles_layout.addWidget(lbl_subtitulo)

        header_layout.addWidget(icon_lbl)
        header_layout.addLayout(titles_layout)
        header_layout.addStretch()

        root.addWidget(header_widget)

        # ── Contenido: Tarjeta Única ──
        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(12)

        sec_title = QLabel("DATOS DEL BANCO")
        sec_title.setProperty("class", "SectionTitle")
        card_layout.addWidget(sec_title)

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # Código del Banco
        lbl_cod = QLabel("Código del Banco <span style='color: #DC2626;'>*</span>")
        lbl_cod.setProperty("class", "FormLabel")
        self.codigo_input = QLineEdit()
        self.codigo_input.setPlaceholderText("Ej: 0102")
        self.codigo_input.setMaxLength(4)
        self.codigo_input.setFixedHeight(36)
        grid.addWidget(lbl_cod, 0, 0)
        grid.addWidget(self.codigo_input, 1, 0)

        # Tipo de Banco
        lbl_tipo = QLabel("Tipo de Banco <span style='color: #DC2626;'>*</span>")
        lbl_tipo.setProperty("class", "FormLabel")
        self.tipo_combo = QComboBox()
        self.tipo_combo.addItems(["AHORRO", "CORRIENTE"])
        self.tipo_combo.setFixedHeight(36)
        grid.addWidget(lbl_tipo, 0, 1)
        grid.addWidget(self.tipo_combo, 1, 1)

        # Nombre del Banco
        lbl_nom = QLabel("Nombre del Banco <span style='color: #DC2626;'>*</span>")
        lbl_nom.setProperty("class", "FormLabel")
        self.nombre_input = QLineEdit()
        self.nombre_input.setPlaceholderText("Ej: Banco de Venezuela")
        self.nombre_input.setFixedHeight(36)
        grid.addWidget(lbl_nom, 2, 0, 1, 2)
        grid.addWidget(self.nombre_input, 3, 0, 1, 2)

        # Identificación (RIF)
        lbl_rif = QLabel("Identificación (RIF) <span style='color: #DC2626;'>*</span>")
        lbl_rif.setProperty("class", "FormLabel")
        self.identificacion_input = QLineEdit()
        self.identificacion_input.setPlaceholderText("Ej: J-12345678-9")
        self.identificacion_input.setMaxLength(20)
        self.identificacion_input.setFixedHeight(36)
        grid.addWidget(lbl_rif, 4, 0)
        grid.addWidget(self.identificacion_input, 5, 0)

        # Correo Electrónico
        lbl_email = QLabel("Correo Electrónico")
        lbl_email.setProperty("class", "FormLabel")
        self.correo_input = QLineEdit()
        self.correo_input.setPlaceholderText("Ej: contacto@banco.com")
        self.correo_input.setFixedHeight(36)
        grid.addWidget(lbl_email, 4, 1)
        grid.addWidget(self.correo_input, 5, 1)

        # Teléfono
        lbl_tel = QLabel("Teléfono")
        lbl_tel.setProperty("class", "FormLabel")
        self.telefono_input = QLineEdit()
        self.telefono_input.setPlaceholderText("Ej: 0212-1234567")
        self.telefono_input.setMaxLength(20)
        self.telefono_input.setFixedHeight(36)
        grid.addWidget(lbl_tel, 6, 0, 1, 2)
        grid.addWidget(self.telefono_input, 7, 0, 1, 2)

        # Campos de auditoría (solo visibles en edición)
        self.auditoria_widget = QWidget()
        self.auditoria_widget.setVisible(False)
        auditoria_layout = QVBoxLayout(self.auditoria_widget)
        auditoria_layout.setContentsMargins(0, 0, 0, 0)
        auditoria_layout.setSpacing(4)

        lbl_auditoria = QLabel("INFORMACIÓN DE AUDITORÍA")
        lbl_auditoria.setProperty("class", "SectionTitle")
        auditoria_layout.addWidget(lbl_auditoria)

        self.fecha_creacion_label = QLabel()
        self.fecha_creacion_label.setStyleSheet("font-size: 11px; color: #64748B;")
        auditoria_layout.addWidget(self.fecha_creacion_label)

        self.creado_por_label = QLabel()
        self.creado_por_label.setStyleSheet("font-size: 11px; color: #64748B;")
        auditoria_layout.addWidget(self.creado_por_label)

        self.modificado_por_label = QLabel()
        self.modificado_por_label.setStyleSheet("font-size: 11px; color: #64748B;")
        auditoria_layout.addWidget(self.modificado_por_label)

        card_layout.addLayout(grid)
        card_layout.addWidget(self.auditoria_widget)
        card_layout.addStretch()

        root.addWidget(card)

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

        self.btn_guardar = QPushButton("Guardar Banco")
        self.btn_guardar.setIcon(qta.icon("fa5s.save", color="#FFFFFF"))
        self.btn_guardar.setObjectName("BtnPrimary")
        self.btn_guardar.setFixedHeight(36)
        self.btn_guardar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guardar.clicked.connect(self._validar_y_aceptar)

        footer_layout.addWidget(self.btn_cancelar)
        footer_layout.addWidget(self.btn_guardar)

        root.addLayout(footer_layout)

    def _precargar(self, banco: Banco):
        self.codigo_input.setText(banco.codigo_banco or "")
        self.nombre_input.setText(banco.nombre_banco or "")
        self.identificacion_input.setText(banco.identificacion_banco or "")
        self.correo_input.setText(banco.correo_banco or "")
        self.telefono_input.setText(banco.numero_telefono_banco or "")

        idx_tipo = self.tipo_combo.findText(banco.tipo_banco or "CORRIENTE")
        if idx_tipo >= 0:
            self.tipo_combo.setCurrentIndex(idx_tipo)

        # Mostrar información de auditoría solo en edición
        self.auditoria_widget.setVisible(True)
        if banco.fecha_creacion:
            fecha_str = banco.fecha_creacion.strftime("%d/%m/%Y %H:%M")
            self.fecha_creacion_label.setText(f"Fecha de creación: {fecha_str}")
        else:
            self.fecha_creacion_label.setText("Fecha de creación: N/A")

        if banco.creador:
            nombre_creador = banco.creador.nombre or banco.creador.nombre_usuario or f"ID {banco.creado_por}"
            self.creado_por_label.setText(f"Creado por: {nombre_creador}")
        else:
            self.creado_por_label.setText("Creado por: N/A")

        if banco.modificador:
            nombre_modificador = (
                banco.modificador.nombre
                or banco.modificador.nombre_usuario
                or f"ID {banco.modificado_por}"
            )
            self.modificado_por_label.setText(f"Modificado por: {nombre_modificador}")
        else:
            self.modificado_por_label.setText("Modificado por: N/A")

    def _validar_y_aceptar(self):
        if not self.codigo_input.text().strip():
            QMessageBox.warning(self, "Dato requerido", "El código del banco es obligatorio.")
            self.codigo_input.setFocus()
            return
        if not self.nombre_input.text().strip():
            QMessageBox.warning(self, "Dato requerido", "El nombre del banco es obligatorio.")
            self.nombre_input.setFocus()
            return
        if not self.identificacion_input.text().strip():
            QMessageBox.warning(self, "Dato requerido", "La identificación (RIF) es obligatoria.")
            self.identificacion_input.setFocus()
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "codigo_banco": self.codigo_input.text().strip() or None,
            "nombre_banco": self.nombre_input.text().strip(),
            "tipo_banco": self.tipo_combo.currentText(),
            "identificacion_banco": self.identificacion_input.text().strip(),
            "correo_banco": self.correo_input.text().strip() or None,
            "numero_telefono_banco": self.telefono_input.text().strip() or None,
        }
