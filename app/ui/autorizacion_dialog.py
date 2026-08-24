"""Dialogo de autorizacion de descuentos: se abre cuando una factura tiene un item
vendido por debajo de su precio de lista y/o un descuento manual de factura. Pide
usuario+clave de un supervisor SIN cerrar la sesion de quien esta facturando -- valida
contra bcrypt (mismo mecanismo que el login, app/services/auth.py) y ademas que ese
usuario tenga el permiso 'descuentos'/'crear' (app/services/permisos.py).

No asume que quien abre este dialogo no tiene el permiso el mismo: FacturaFormDialog
solo lo abre cuando hace falta autorizacion, sin importar quien esta logueado -- si el
propio usuario logueado tiene el permiso, puede autorizarse a si mismo escribiendo sus
propias credenciales aca."""

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from sqlalchemy.orm import Session

from app.db.models import Usuario
from app.services.auth import CuentaBloqueadaError, authenticate
from app.services.permisos import PermisoDenegadoError, require_permiso
from app.ui.styles import (
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_PRIMARY,
    COLOR_PRIMARY_DARK,
    COLOR_PRIMARY_LIGHT,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    FONT_FAMILY,
)

DIALOG_STYLE = f"""
QDialog {{
    background-color: {COLOR_CONTENT_BG};
    font-family: '{FONT_FAMILY}', Arial, sans-serif;
}}
QLabel.FormLabel {{
    font-size: 12px;
    font-weight: 600;
    color: #334155;
    margin-bottom: 2px;
}}
QLineEdit {{
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
    min-height: 22px;
}}
QLineEdit:focus {{
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
}}
"""


class AutorizacionDescuentoDialog(QDialog):
    """Tras exec() == Accepted, `usuario_autorizador` y `motivo` quedan poblados."""

    def __init__(self, session: Session, mensaje: str, parent=None):
        super().__init__(parent)
        self.session = session
        self.usuario_autorizador: Usuario | None = None
        self.motivo: str = ""

        self.setWindowTitle("Autorizacion de descuento requerida")
        self.setFixedSize(420, 320)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui(mensaje)

    def _build_ui(self, mensaje: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.user-shield", color=COLOR_DANGER).pixmap(22, 22))
        titulos = QVBoxLayout()
        titulos.setSpacing(1)
        lbl_titulo = QLabel("Autorizacion requerida")
        lbl_titulo.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        lbl_subtitulo = QLabel(mensaje)
        lbl_subtitulo.setWordWrap(True)
        lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        titulos.addWidget(lbl_titulo)
        titulos.addWidget(lbl_subtitulo)
        header.addWidget(icon_lbl)
        header.addLayout(titulos, stretch=1)
        root.addLayout(header)

        lbl_motivo = QLabel("Motivo del descuento <span style='color: #DC2626;'>*</span>")
        lbl_motivo.setProperty("class", "FormLabel")
        self.motivo_input = QLineEdit()
        self.motivo_input.setPlaceholderText("Ej. cliente frecuente, mercancia con detalle…")
        root.addWidget(lbl_motivo)
        root.addWidget(self.motivo_input)

        lbl_usuario = QLabel("Usuario del supervisor <span style='color: #DC2626;'>*</span>")
        lbl_usuario.setProperty("class", "FormLabel")
        self.usuario_input = QLineEdit()
        root.addWidget(lbl_usuario)
        root.addWidget(self.usuario_input)

        lbl_clave = QLabel("Clave <span style='color: #DC2626;'>*</span>")
        lbl_clave.setProperty("class", "FormLabel")
        self.clave_input = QLineEdit()
        self.clave_input.setEchoMode(QLineEdit.EchoMode.Password)
        root.addWidget(lbl_clave)
        root.addWidget(self.clave_input)

        root.addStretch()

        footer = QHBoxLayout()
        footer.addStretch()
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setObjectName("BtnSecondary")
        btn_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancelar.clicked.connect(self.reject)
        btn_autorizar = QPushButton("Autorizar")
        btn_autorizar.setIcon(qta.icon("fa5s.check", color="#FFFFFF"))
        btn_autorizar.setObjectName("BtnPrimary")
        btn_autorizar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_autorizar.clicked.connect(self._autorizar)
        footer.addWidget(btn_cancelar)
        footer.addWidget(btn_autorizar)
        root.addLayout(footer)

    def _autorizar(self) -> None:
        motivo = self.motivo_input.text().strip()
        nombre_usuario = self.usuario_input.text().strip()
        clave = self.clave_input.text()

        if not motivo:
            QMessageBox.warning(self, "Motivo requerido", "Ingrese el motivo del descuento.")
            return
        if not nombre_usuario or not clave:
            QMessageBox.warning(self, "Credenciales requeridas", "Ingrese usuario y clave del supervisor.")
            return

        try:
            usuario = authenticate(
                self.session,
                nombre_usuario,
                clave,
                accion_exito="AUTORIZACION_DESCUENTO",
                accion_fallo="AUTORIZACION_DESCUENTO_FALLIDA",
            )
        except CuentaBloqueadaError as exc:
            QMessageBox.critical(self, "Cuenta bloqueada", str(exc))
            return

        if usuario is None:
            QMessageBox.warning(self, "Credenciales invalidas", "Usuario o clave incorrectos.")
            return

        try:
            require_permiso(self.session, usuario.id_usuario, "descuentos", "crear")
        except PermisoDenegadoError:
            QMessageBox.warning(
                self, "Sin permiso", f"'{usuario.nombre_usuario}' no tiene permiso para autorizar descuentos."
            )
            return

        self.usuario_autorizador = usuario
        self.motivo = motivo
        self.accept()
