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

from app.db.models import Vendedor
from app.services.permisos import PermisoDenegadoError
from app.services.rutas import RutaService
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


class VendedorFormDialog(QDialog):
    """Dialogo de alta/edicion de vendedores -- mismo patron visual que
    ClienteFormDialog (app/ui/cliente_form_dialog.py), pero con una sola tarjeta
    porque el vendedor tiene muchos menos campos que un cliente."""

    def __init__(self, session: Session, vendedor: Vendedor | None = None, id_usuario: int | None = None, parent=None):
        super().__init__(parent)
        self.session = session
        self.vendedor = vendedor
        self.id_usuario = id_usuario
        self.setWindowTitle("Editar Vendedor" if vendedor else "Nuevo Vendedor")
        self.setFixedSize(480, 470)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()

        if vendedor:
            self._precargar(vendedor)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        icon_lbl = QLabel()
        fa_icon_name = "fa5s.user-edit" if self.vendedor else "fa5s.user-tie"
        icon_lbl.setPixmap(qta.icon(fa_icon_name, color=COLOR_PRIMARY).pixmap(QSize(22, 22)))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(38, 38)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titles_layout = QVBoxLayout()
        titles_layout.setSpacing(1)
        titles_layout.setContentsMargins(0, 0, 0, 0)

        titulo_text = "Editar Vendedor" if self.vendedor else "Nuevo Vendedor"
        lbl_titulo = QLabel(titulo_text)
        lbl_titulo.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        lbl_subtitulo = QLabel("Datos de la fuerza de venta para asignarla a clientes y facturas.")
        lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")

        titles_layout.addWidget(lbl_titulo)
        titles_layout.addWidget(lbl_subtitulo)

        header_layout.addWidget(icon_lbl)
        header_layout.addLayout(titles_layout)
        header_layout.addStretch()

        root.addWidget(header_widget)

        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 14)
        card_layout.setSpacing(8)

        titulo_card = QLabel("DATOS DEL VENDEDOR")
        titulo_card.setProperty("class", "SectionTitle")
        card_layout.addWidget(titulo_card)

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        lbl_nombre = QLabel("Nombre Completo <span style='color: #DC2626;'>*</span>")
        lbl_nombre.setProperty("class", "FormLabel")
        self.nombre_input = QLineEdit()
        self.nombre_input.setPlaceholderText("Ej: Juan Pérez")
        self.nombre_input.setFixedHeight(32)
        grid.addWidget(lbl_nombre, 0, 0, 1, 2)
        grid.addWidget(self.nombre_input, 1, 0, 1, 2)

        lbl_codigo = QLabel("Código <span style='color: #DC2626;'>*</span>")
        lbl_codigo.setProperty("class", "FormLabel")
        self.codigo_input = QLineEdit()
        self.codigo_input.setPlaceholderText("Ej: VEN-001")
        self.codigo_input.setMaxLength(20)
        self.codigo_input.setFixedHeight(32)
        grid.addWidget(lbl_codigo, 2, 0)
        grid.addWidget(self.codigo_input, 3, 0)

        lbl_id = QLabel("Identificación <span style='color: #DC2626;'>*</span>")
        lbl_id.setProperty("class", "FormLabel")
        self.identificacion_input = QLineEdit()
        self.identificacion_input.setPlaceholderText("Ej: V-12345678")
        self.identificacion_input.setMaxLength(20)
        self.identificacion_input.setFixedHeight(32)
        grid.addWidget(lbl_id, 2, 1)
        grid.addWidget(self.identificacion_input, 3, 1)

        lbl_tel = QLabel("Teléfono")
        lbl_tel.setProperty("class", "FormLabel")
        self.telefono_input = QLineEdit()
        self.telefono_input.setPlaceholderText("Ej: 0414-1234567")
        self.telefono_input.setFixedHeight(32)
        grid.addWidget(lbl_tel, 4, 0)
        grid.addWidget(self.telefono_input, 5, 0)

        lbl_email = QLabel("Correo Electrónico")
        lbl_email.setProperty("class", "FormLabel")
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("Ej: vendedor@empresa.com")
        self.email_input.setFixedHeight(32)
        grid.addWidget(lbl_email, 4, 1)
        grid.addWidget(self.email_input, 5, 1)

        lbl_ruta = QLabel("Ruta <span style='color: #DC2626;'>*</span>")
        lbl_ruta.setProperty("class", "FormLabel")
        self.ruta_combo = QComboBox()
        self.ruta_combo.setFixedHeight(32)
        # Via RutaService.listar() (no una query directa a la tabla) para que respete
        # require_permiso('rutas', 'ver') igual que el resto de la app -- una consulta
        # cruda aca dejaba ver el catalogo de rutas a cualquiera con permiso de
        # vendedores/crear-editar aunque no tuviera permiso propio sobre rutas (hallazgo
        # de auditoria, 2026-09-02). Sin ese permiso el combo queda vacio -- el usuario ya
        # no podra guardar (la ruta es obligatoria), consistente con negarle el acceso.
        try:
            rutas = RutaService.listar(
                self.session, estado_ruta="ACTIVO", id_usuario=self.id_usuario, por_pagina=1_000_000
            )["items"]
        except PermisoDenegadoError:
            rutas = []
        if self.vendedor is not None and self.vendedor.ruta is not None and self.vendedor.ruta.estado_ruta != "ACTIVO":
            # La ruta ya asignada puede haber sido desactivada despues -- se conserva en la
            # lista al editar para no perder el valor actual sin que el usuario lo pida.
            rutas = [*rutas, self.vendedor.ruta]
        for ruta in rutas:
            self.ruta_combo.addItem(ruta.nombre_ruta, ruta.id_ruta)
        grid.addWidget(lbl_ruta, 6, 0, 1, 2)
        grid.addWidget(self.ruta_combo, 7, 0, 1, 2)

        lbl_dir = QLabel("Dirección")
        lbl_dir.setProperty("class", "FormLabel")
        self.direccion_input = QLineEdit()
        self.direccion_input.setPlaceholderText("Opcional")
        self.direccion_input.setFixedHeight(32)
        grid.addWidget(lbl_dir, 8, 0, 1, 2)
        grid.addWidget(self.direccion_input, 9, 0, 1, 2)

        card_layout.addLayout(grid)
        card_layout.addStretch()
        root.addWidget(card, stretch=1)

        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 4, 0, 0)
        footer_layout.setSpacing(10)
        footer_layout.addStretch()

        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.setIcon(qta.icon("fa5s.times", color="#475569"))
        self.btn_cancelar.setObjectName("BtnSecondary")
        self.btn_cancelar.setFixedHeight(36)
        self.btn_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancelar.setAutoDefault(False)
        self.btn_cancelar.clicked.connect(self.reject)

        self.btn_guardar = QPushButton("Guardar Vendedor")
        self.btn_guardar.setIcon(qta.icon("fa5s.save", color="#FFFFFF"))
        self.btn_guardar.setObjectName("BtnPrimary")
        self.btn_guardar.setFixedHeight(36)
        self.btn_guardar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guardar.setAutoDefault(False)
        self.btn_guardar.clicked.connect(self._validar_y_aceptar)

        footer_layout.addWidget(self.btn_cancelar)
        footer_layout.addWidget(self.btn_guardar)
        root.addLayout(footer_layout)

    def _precargar(self, vendedor: Vendedor) -> None:
        self.nombre_input.setText(vendedor.nombre_vendedor or "")
        self.codigo_input.setText(vendedor.codigo_vendedor or "")
        self.identificacion_input.setText(vendedor.identificacion_vendedor or "")
        self.telefono_input.setText(vendedor.telefono_vendedor or "")
        self.email_input.setText(vendedor.email_vendedor or "")
        self.direccion_input.setText(vendedor.direccion_vendedor or "")
        idx_ruta = self.ruta_combo.findData(vendedor.id_ruta)
        if idx_ruta >= 0:
            self.ruta_combo.setCurrentIndex(idx_ruta)

    def _validar_y_aceptar(self) -> None:
        if not self.nombre_input.text().strip():
            QMessageBox.warning(self, "Dato requerido", "El nombre del vendedor es obligatorio.")
            self.nombre_input.setFocus()
            return
        if not self.codigo_input.text().strip():
            QMessageBox.warning(self, "Dato requerido", "El código del vendedor es obligatorio.")
            self.codigo_input.setFocus()
            return
        if not self.identificacion_input.text().strip():
            QMessageBox.warning(self, "Dato requerido", "La identificación del vendedor es obligatoria.")
            self.identificacion_input.setFocus()
            return
        if self.ruta_combo.currentData() is None:
            QMessageBox.warning(
                self,
                "Dato requerido",
                "La ruta es obligatoria. Cree una ruta primero desde la pestaña 'Rutas'.",
            )
            self.ruta_combo.setFocus()
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "nombre_vendedor": self.nombre_input.text().strip(),
            "codigo_vendedor": self.codigo_input.text().strip() or None,
            "identificacion_vendedor": self.identificacion_input.text().strip() or None,
            "telefono_vendedor": self.telefono_input.text().strip() or None,
            "email_vendedor": self.email_input.text().strip() or None,
            "direccion_vendedor": self.direccion_input.text().strip() or None,
            "id_ruta": self.ruta_combo.currentData(),
        }
