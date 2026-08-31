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
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from app.db.models import Banco, CuentaBancaria
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
QDoubleSpinBox {{
    background-color: #FFFFFF;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
    min-height: 20px;
}}
QDoubleSpinBox:focus {{
    border: 1.5px solid {COLOR_PRIMARY};
    background-color: #FFFFFF;
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


class CuentaBancariaFormDialog(QDialog):
    """Diálogo de creación/edición de cuentas bancarias."""

    def __init__(self, session: Session, cuenta: CuentaBancaria | None = None, parent=None):
        super().__init__(parent)
        self.session = session
        self.cuenta = cuenta
        self.setWindowTitle("Editar Cuenta Bancaria" if cuenta else "Nueva Cuenta Bancaria")
        self.setFixedWidth(800)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()
        self._cargar_bancos()

        if cuenta:
            self._precargar(cuenta)

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
        fa_icon_name = "fa5s.university" if self.cuenta else "fa5s.plus-circle"
        icon_lbl.setPixmap(qta.icon(fa_icon_name, color=COLOR_PRIMARY).pixmap(QSize(22, 22)))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(38, 38)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titles_layout = QVBoxLayout()
        titles_layout.setSpacing(1)
        titles_layout.setContentsMargins(0, 0, 0, 0)

        titulo_text = "Editar Cuenta Bancaria" if self.cuenta else "Nueva Cuenta Bancaria"
        lbl_titulo = QLabel(titulo_text)
        lbl_titulo.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        lbl_subtitulo = QLabel("Complete los datos requeridos para registrar la cuenta bancaria.")
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

        sec_title = QLabel("DATOS DE LA CUENTA BANCARIA")
        sec_title.setProperty("class", "SectionTitle")
        card_layout.addWidget(sec_title)

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # Banco
        lbl_banco = QLabel("Banco <span style='color: #DC2626;'>*</span>")
        lbl_banco.setProperty("class", "FormLabel")
        self.banco_combo = QComboBox()
        self.banco_combo.setFixedHeight(36)
        grid.addWidget(lbl_banco, 0, 0, 1, 2)
        grid.addWidget(self.banco_combo, 1, 0, 1, 2)

        # Número de Cuenta
        lbl_num = QLabel("Número de Cuenta <span style='color: #DC2626;'>*</span>")
        lbl_num.setProperty("class", "FormLabel")
        self.numero_input = QLineEdit()
        self.numero_input.setPlaceholderText("Ej: 0134-0001-123456789")
        self.numero_input.setMaxLength(30)
        self.numero_input.setFixedHeight(36)
        grid.addWidget(lbl_num, 2, 0, 1, 2)
        grid.addWidget(self.numero_input, 3, 0, 1, 2)

        # Tipo de Cuenta
        lbl_tipo = QLabel("Tipo de Cuenta")
        lbl_tipo.setProperty("class", "FormLabel")
        self.tipo_combo = QComboBox()
        self.tipo_combo.addItems(["AHORRO", "CORRIENTE"])
        self.tipo_combo.setFixedHeight(36)
        grid.addWidget(lbl_tipo, 4, 0)
        grid.addWidget(self.tipo_combo, 5, 0)

        # Saldo Inicial -- solo editable al CREAR la cuenta. En edicion se deshabilita
        # (ver _precargar): cambiarlo a mano ahi rompe la trazabilidad, porque no genera
        # ningun BancoMovimiento que explique el ajuste -- BancoMovimientoService.crear()
        # es el unico camino que debe modificar saldo_total_banco despues de la creacion.
        self.lbl_saldo = QLabel("Saldo Inicial")
        self.lbl_saldo.setProperty("class", "FormLabel")
        self.saldo_input = QDoubleSpinBox()
        self.saldo_input.setRange(0, 999999999.99)
        self.saldo_input.setDecimals(2)
        self.saldo_input.setPrefix("$ ")
        self.saldo_input.setFixedHeight(36)
        grid.addWidget(self.lbl_saldo, 4, 1)
        grid.addWidget(self.saldo_input, 5, 1)

        # Nombre del Titular
        lbl_nom = QLabel("Nombre del Titular <span style='color: #DC2626;'>*</span>")
        lbl_nom.setProperty("class", "FormLabel")
        self.nombre_input = QLineEdit()
        self.nombre_input.setPlaceholderText("Ej: Juan Pérez")
        self.nombre_input.setFixedHeight(36)
        grid.addWidget(lbl_nom, 6, 0, 1, 2)
        grid.addWidget(self.nombre_input, 7, 0, 1, 2)

        # Identificación del Titular
        lbl_rif = QLabel("Identificación del Titular <span style='color: #DC2626;'>*</span>")
        lbl_rif.setProperty("class", "FormLabel")
        self.identificacion_input = QLineEdit()
        self.identificacion_input.setPlaceholderText("Ej: V-12345678")
        self.identificacion_input.setMaxLength(20)
        self.identificacion_input.setFixedHeight(36)
        grid.addWidget(lbl_rif, 8, 0, 1, 2)
        grid.addWidget(self.identificacion_input, 9, 0, 1, 2)

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

        self.btn_guardar = QPushButton("Guardar Cuenta")
        self.btn_guardar.setIcon(qta.icon("fa5s.save", color="#FFFFFF"))
        self.btn_guardar.setObjectName("BtnPrimary")
        self.btn_guardar.setFixedHeight(36)
        self.btn_guardar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guardar.clicked.connect(self._validar_y_aceptar)

        footer_layout.addWidget(self.btn_cancelar)
        footer_layout.addWidget(self.btn_guardar)

        root.addLayout(footer_layout)

    def _cargar_bancos(self):
        """Carga la lista de bancos activos en el combo."""
        bancos = self.session.query(Banco).filter(Banco.estado_banco == "ACTIVO").order_by(Banco.nombre_banco).all()
        self.banco_combo.clear()
        for banco in bancos:
            self.banco_combo.addItem(f"{banco.nombre_banco} ({banco.codigo_banco})", banco.id_banco)

    def _precargar(self, cuenta: CuentaBancaria):
        self.numero_input.setText(cuenta.numero_cuenta or "")
        self.nombre_input.setText(cuenta.nombre_titular or "")
        self.identificacion_input.setText(cuenta.identificacion_titular or "")
        self.saldo_input.setValue(float(cuenta.saldo_total_banco or 0))
        self.saldo_input.setEnabled(False)
        self.saldo_input.setToolTip("El saldo se actualiza registrando movimientos bancarios, no editando este campo.")
        self.lbl_saldo.setText("Saldo Actual (solo lectura)")

        # Seleccionar banco
        idx_banco = self.banco_combo.findData(cuenta.id_banco)
        if idx_banco >= 0:
            self.banco_combo.setCurrentIndex(idx_banco)

        # Seleccionar tipo de cuenta
        idx_tipo = self.tipo_combo.findText(cuenta.tipo_cuenta_banco or "CORRIENTE")
        if idx_tipo >= 0:
            self.tipo_combo.setCurrentIndex(idx_tipo)

        # Mostrar información de auditoría solo en edición
        self.auditoria_widget.setVisible(True)
        if cuenta.fecha_creacion:
            fecha_str = cuenta.fecha_creacion.strftime("%d/%m/%Y %H:%M")
            self.fecha_creacion_label.setText(f"Fecha de creación: {fecha_str}")
        else:
            self.fecha_creacion_label.setText("Fecha de creación: N/A")

        if cuenta.creador:
            nombre_creador = cuenta.creador.nombre or cuenta.creador.nombre_usuario or f"ID {cuenta.creado_por}"
            self.creado_por_label.setText(f"Creado por: {nombre_creador}")
        else:
            self.creado_por_label.setText("Creado por: N/A")

    def _validar_y_aceptar(self):
        if self.banco_combo.currentData() is None:
            QMessageBox.warning(self, "Dato requerido", "Debe seleccionar un banco.")
            self.banco_combo.setFocus()
            return
        if not self.numero_input.text().strip():
            QMessageBox.warning(self, "Dato requerido", "El número de cuenta es obligatorio.")
            self.numero_input.setFocus()
            return
        if not self.nombre_input.text().strip():
            QMessageBox.warning(self, "Dato requerido", "El nombre del titular es obligatorio.")
            self.nombre_input.setFocus()
            return
        if not self.identificacion_input.text().strip():
            QMessageBox.warning(self, "Dato requerido", "La identificación del titular es obligatoria.")
            self.identificacion_input.setFocus()
            return
        self.accept()

    def get_data(self) -> dict:
        datos = {
            "id_banco": self.banco_combo.currentData(),
            "numero_cuenta": self.numero_input.text().strip(),
            "tipo_cuenta_banco": self.tipo_combo.currentText(),
            "nombre_titular": self.nombre_input.text().strip(),
            "identificacion_titular": self.identificacion_input.text().strip(),
        }
        # Solo se establece al CREAR -- en edicion el campo esta deshabilitado (ver
        # _precargar) y no debe viajar en el dict de actualizar(), para que
        # CuentaBancariaService.actualizar() nunca reciba un cambio de saldo sin el
        # BancoMovimiento que lo explique.
        if self.cuenta is None:
            datos["saldo_total_banco"] = self.saldo_input.value()
        return datos
