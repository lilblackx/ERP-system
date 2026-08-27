"""Dialogo de alta/edicion de usuarios -- mismo patron visual que
VendedorFormDialog (app/ui/vendedor_form_dialog.py), pero necesita sesion/actor porque
puebla los combos de rol (RolService.listar_roles) y vendedor vinculado
(VendedorService.listar) desde la base, a diferencia de un form sin dependencias
externas."""

import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
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

from app.db.models import Usuario
from app.services.auth import PASSWORD_MAX_BYTES
from app.services.permisos import PermisoDenegadoError, RolService
from app.services.usuarios import APELLIDO_MAX, EMAIL_MAX, NOMBRE_MAX, NOMBRE_USUARIO_MAX
from app.services.vendedores import VendedorService
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
    ComboBoxSinScroll,
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
QLabel.Hint {{
    font-size: 11px;
    color: {COLOR_TEXT_MUTED};
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


class UsuarioFormDialog(QDialog):
    """Alta/edicion de un usuario. `get_data()` devuelve los campos planos (sin clave,
    para poder pasarlos tal cual a UsuarioService.editar_usuario(datos=...)) y
    `get_clave()` devuelve la clave por separado -- obligatoria al crear, opcional
    ("dejar en blanco para no cambiarla") al editar, mismo contrato que
    UsuarioService.editar_usuario(nueva_clave=...)."""

    def __init__(self, session: Session, id_usuario_actor: int | None, usuario: Usuario | None = None, parent=None):
        super().__init__(parent)
        self.session = session
        self.id_usuario_actor = id_usuario_actor
        self.usuario = usuario
        self.setWindowTitle("Editar Usuario" if usuario else "Nuevo Usuario")
        self.setFixedSize(480, 545)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._roles = []
        self._vendedores = []

        self._build_ui()
        self._cargar_combos()

        if usuario:
            self._precargar(usuario)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        icon_lbl = QLabel()
        fa_icon_name = "fa5s.user-edit" if self.usuario else "fa5s.user-plus"
        icon_lbl.setPixmap(qta.icon(fa_icon_name, color=COLOR_PRIMARY).pixmap(QSize(22, 22)))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(38, 38)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titles_layout = QVBoxLayout()
        titles_layout.setSpacing(1)
        titles_layout.setContentsMargins(0, 0, 0, 0)

        titulo_text = "Editar Usuario" if self.usuario else "Nuevo Usuario"
        lbl_titulo = QLabel(titulo_text)
        lbl_titulo.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        lbl_subtitulo = QLabel("Cuenta de acceso al sistema y el rol que determina sus permisos.")
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

        titulo_card = QLabel("DATOS DEL USUARIO")
        titulo_card.setProperty("class", "SectionTitle")
        card_layout.addWidget(titulo_card)

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        lbl_usuario = QLabel("Nombre de usuario <span style='color: #DC2626;'>*</span>")
        lbl_usuario.setProperty("class", "FormLabel")
        self.nombre_usuario_input = QLineEdit()
        self.nombre_usuario_input.setPlaceholderText("Ej: jperez")
        self.nombre_usuario_input.setFixedHeight(32)
        self.nombre_usuario_input.setMaxLength(NOMBRE_USUARIO_MAX)
        grid.addWidget(lbl_usuario, 0, 0, 1, 2)
        grid.addWidget(self.nombre_usuario_input, 1, 0, 1, 2)

        lbl_nombre = QLabel("Nombre")
        lbl_nombre.setProperty("class", "FormLabel")
        self.nombre_input = QLineEdit()
        self.nombre_input.setFixedHeight(32)
        self.nombre_input.setMaxLength(NOMBRE_MAX)
        grid.addWidget(lbl_nombre, 2, 0)
        grid.addWidget(self.nombre_input, 3, 0)

        lbl_apellido = QLabel("Apellido")
        lbl_apellido.setProperty("class", "FormLabel")
        self.apellido_input = QLineEdit()
        self.apellido_input.setFixedHeight(32)
        self.apellido_input.setMaxLength(APELLIDO_MAX)
        grid.addWidget(lbl_apellido, 2, 1)
        grid.addWidget(self.apellido_input, 3, 1)

        lbl_email = QLabel("Correo electrónico <span style='color: #DC2626;'>*</span>")
        lbl_email.setProperty("class", "FormLabel")
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("Ej: usuario@empresa.com")
        self.email_input.setFixedHeight(32)
        self.email_input.setMaxLength(EMAIL_MAX)
        grid.addWidget(lbl_email, 4, 0, 1, 2)
        grid.addWidget(self.email_input, 5, 0, 1, 2)

        lbl_hint_email = QLabel("A este correo se envían los códigos de desbloqueo y recuperación de clave.")
        lbl_hint_email.setProperty("class", "Hint")
        lbl_hint_email.setWordWrap(True)
        grid.addWidget(lbl_hint_email, 6, 0, 1, 2)

        lbl_clave = QLabel(
            "Clave <span style='color: #DC2626;'>*</span>" if not self.usuario else "Nueva clave (opcional)"
        )
        lbl_clave.setProperty("class", "FormLabel")
        self.clave_input = QLineEdit()
        self.clave_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.clave_input.setPlaceholderText("Dejar en blanco para no cambiarla" if self.usuario else "")
        self.clave_input.setFixedHeight(32)
        # Tope por caracteres, no bytes -- bcrypt exige <=72 BYTES utf-8 (validar_password_
        # policy() en auth.py es la version exacta por bytes); esto es solo un techo
        # razonable en la UI, la validacion real sigue siendo server-side.
        self.clave_input.setMaxLength(PASSWORD_MAX_BYTES)
        grid.addWidget(lbl_clave, 7, 0, 1, 2)
        grid.addWidget(self.clave_input, 8, 0, 1, 2)

        lbl_hint_clave = QLabel("Mínimo 8 caracteres, con mayúscula, minúscula, número y carácter especial.")
        lbl_hint_clave.setProperty("class", "Hint")
        lbl_hint_clave.setWordWrap(True)
        grid.addWidget(lbl_hint_clave, 9, 0, 1, 2)

        lbl_rol = QLabel("Rol <span style='color: #DC2626;'>*</span>")
        lbl_rol.setProperty("class", "FormLabel")
        self.rol_combo = ComboBoxSinScroll()
        self.rol_combo.setFixedHeight(32)
        self.rol_combo.currentIndexChanged.connect(self._toggle_vendedor)
        grid.addWidget(lbl_rol, 10, 0, 1, 2)
        grid.addWidget(self.rol_combo, 11, 0, 1, 2)

        self.lbl_vendedor = QLabel("Vendedor vinculado")
        self.lbl_vendedor.setProperty("class", "FormLabel")
        self.vendedor_combo = ComboBoxSinScroll()
        self.vendedor_combo.setFixedHeight(32)
        grid.addWidget(self.lbl_vendedor, 12, 0, 1, 2)
        grid.addWidget(self.vendedor_combo, 13, 0, 1, 2)

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

        self.btn_guardar = QPushButton("Guardar Usuario")
        self.btn_guardar.setIcon(qta.icon("fa5s.save", color="#FFFFFF"))
        self.btn_guardar.setObjectName("BtnPrimary")
        self.btn_guardar.setFixedHeight(36)
        self.btn_guardar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guardar.setAutoDefault(False)
        self.btn_guardar.clicked.connect(self._validar_y_aceptar)

        footer_layout.addWidget(self.btn_cancelar)
        footer_layout.addWidget(self.btn_guardar)
        root.addLayout(footer_layout)

    def _cargar_combos(self) -> None:
        try:
            self._roles = RolService.listar_roles(self.session, id_usuario=self.id_usuario_actor)
        except PermisoDenegadoError:
            self._roles = []
        for rol in self._roles:
            self.rol_combo.addItem(rol.nombre, rol.id_rol)

        try:
            vendedores = VendedorService.listar(self.session, id_usuario=self.id_usuario_actor)
        except PermisoDenegadoError:
            vendedores = []
        self._vendedores = [v for v in vendedores if (v.estado_vendedor or "ACTIVO") == "ACTIVO"]
        self.vendedor_combo.addItem("Sin vincular", None)
        for vendedor in self._vendedores:
            self.vendedor_combo.addItem(vendedor.nombre_vendedor, vendedor.id_vendedor)

        self._toggle_vendedor()

    def _toggle_vendedor(self) -> None:
        rol_id = self.rol_combo.currentData()
        rol = next((r for r in self._roles if r.id_rol == rol_id), None)
        es_vendedor = rol is not None and rol.nombre == "VENDEDOR"
        self.lbl_vendedor.setVisible(es_vendedor)
        self.vendedor_combo.setVisible(es_vendedor)
        if not es_vendedor:
            self.vendedor_combo.setCurrentIndex(0)

    def _precargar(self, usuario: Usuario) -> None:
        self.nombre_usuario_input.setText(usuario.nombre_usuario or "")
        self.nombre_input.setText(usuario.nombre or "")
        self.apellido_input.setText(usuario.apellido or "")
        self.email_input.setText(usuario.email or "")
        if usuario.id_rol is not None:
            idx = self.rol_combo.findData(usuario.id_rol)
            if idx >= 0:
                self.rol_combo.setCurrentIndex(idx)
        if usuario.id_vendedor_usuario is not None:
            idx = self.vendedor_combo.findData(usuario.id_vendedor_usuario)
            if idx >= 0:
                self.vendedor_combo.setCurrentIndex(idx)

    def _validar_y_aceptar(self) -> None:
        if not self.nombre_usuario_input.text().strip():
            QMessageBox.warning(self, "Dato requerido", "El nombre de usuario es obligatorio.")
            self.nombre_usuario_input.setFocus()
            return
        if not self.email_input.text().strip():
            QMessageBox.warning(
                self,
                "Dato requerido",
                "El correo electrónico es obligatorio: es a donde se envían los códigos de "
                "desbloqueo y recuperación de clave.",
            )
            self.email_input.setFocus()
            return
        if self.rol_combo.currentData() is None:
            QMessageBox.warning(self, "Dato requerido", "Selecciona un rol.")
            return
        if not self.usuario and not self.clave_input.text():
            QMessageBox.warning(self, "Dato requerido", "La clave es obligatoria para un usuario nuevo.")
            self.clave_input.setFocus()
            return
        self.accept()

    def get_data(self) -> dict:
        rol_id = self.rol_combo.currentData()
        rol = next((r for r in self._roles if r.id_rol == rol_id), None)
        es_vendedor = rol is not None and rol.nombre == "VENDEDOR"
        return {
            "nombre_usuario": self.nombre_usuario_input.text().strip(),
            "nombre": self.nombre_input.text().strip() or None,
            "apellido": self.apellido_input.text().strip() or None,
            "email": self.email_input.text().strip() or None,
            "id_rol": rol_id,
            "id_vendedor_usuario": self.vendedor_combo.currentData() if es_vendedor else None,
        }

    def get_clave(self) -> str | None:
        return self.clave_input.text() or None
