"""Dialogo de autorizacion generico: se abre cuando una accion sensible dentro de una
factura (descuento manual/venta bajo precio de lista, o dias de credito distintos a los
configurados en el cliente) necesita el visto bueno de un supervisor. Pide usuario+clave
SIN cerrar la sesion de quien esta facturando -- valida contra bcrypt (mismo mecanismo
que el login, app/services/auth.py) y ademas que ese usuario tenga el permiso
`recurso`/`accion` indicado (app/services/permisos.py).

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
    QPushButton,
    QVBoxLayout,
)
from sqlalchemy.orm import Session

from app.db.models import Usuario
from app.services.auth import CuentaBloqueadaError, authenticate
from app.services.permisos import PermisoDenegadoError, require_permiso
from app.ui.message_box import MessageBox
from app.ui.styles import (
    COLOR_BORDER,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_FIELD_BG,
    COLOR_PRIMARY,
    COLOR_PRIMARY_DARK,
    COLOR_PRIMARY_LIGHT,
    COLOR_TABLE_HEADER,
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
    border: 1px solid {COLOR_BORDER};
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
}}
"""


class AutorizacionDialog(QDialog):
    """Tras exec() == Accepted, `usuario_autorizador` y `motivo` quedan poblados.

    `recurso`/`accion` son el permiso (app/services/permisos.py) que debe tener el
    supervisor que autoriza -- p. ej. ("descuentos", "crear") o ("creditos", "crear")."""

    def __init__(
        self,
        session: Session,
        recurso: str,
        accion: str,
        mensaje: str,
        titulo: str = "Autorización requerida",
        motivo_label: str = "Motivo",
        motivo_min_length: int = 1,
        motivo_max_length: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.session = session
        self.recurso = recurso
        self.accion = accion
        self.usuario_autorizador: Usuario | None = None
        self.motivo: str = ""
        # min/max por defecto (1, sin tope) cubren el uso original de este campo como
        # "motivo" libre (descuento, dias de credito) -- cuando se reutiliza como
        # referencia bancaria (vuelto/devolucion de nota de credito, ver
        # factura_form_dialog.py/devolver_nota_credito_dialog.py) el caller pasa el
        # mismo minimo/maximo que ya exige VentaService.emitir_factura()/
        # NotaCreditoService.devolver_nota_credito_cliente() server-side (>=4, <=50),
        # para no dejar que el supervisor se reautentique con clave para nada si la
        # referencia que tipeo es invalida y el servidor la va a rechazar igual.
        self.motivo_min_length = motivo_min_length

        self.setWindowTitle(titulo)
        self.setFixedSize(420, 320)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui(mensaje, motivo_label)
        if motivo_max_length is not None:
            self.motivo_input.setMaxLength(motivo_max_length)

    def _build_ui(self, mensaje: str, motivo_label: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.user-shield", color=COLOR_DANGER).pixmap(22, 22))
        titulos = QVBoxLayout()
        titulos.setSpacing(1)
        lbl_titulo = QLabel(self.windowTitle())
        lbl_titulo.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        lbl_subtitulo = QLabel(mensaje)
        lbl_subtitulo.setWordWrap(True)
        lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        titulos.addWidget(lbl_titulo)
        titulos.addWidget(lbl_subtitulo)
        header.addWidget(icon_lbl)
        header.addLayout(titulos, stretch=1)
        root.addLayout(header)

        lbl_motivo = QLabel(f"{motivo_label} <span style='color: #DC2626;'>*</span>")
        lbl_motivo.setProperty("class", "FormLabel")
        self.motivo_input = QLineEdit()
        self.motivo_input.setPlaceholderText("Ej. cliente frecuente…")
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
            MessageBox.warning(self, "Motivo requerido", "Ingrese el motivo.")
            return
        if len(motivo) < self.motivo_min_length:
            MessageBox.warning(
                self, "Motivo demasiado corto", f"Debe tener al menos {self.motivo_min_length} caracteres."
            )
            return
        if not nombre_usuario or not clave:
            MessageBox.warning(self, "Credenciales requeridas", "Ingrese usuario y clave del supervisor.")
            return

        try:
            usuario = authenticate(
                self.session,
                nombre_usuario,
                clave,
                accion_exito=f"AUTORIZACION_{self.recurso.upper()}",
                accion_fallo=f"AUTORIZACION_{self.recurso.upper()}_FALLIDA",
            )
        except CuentaBloqueadaError as exc:
            MessageBox.critical(self, "Cuenta bloqueada", str(exc))
            return

        if usuario is None:
            MessageBox.warning(self, "Credenciales invalidas", "Usuario o clave incorrectos.")
            return

        try:
            require_permiso(self.session, usuario.id_usuario, self.recurso, self.accion)
        except PermisoDenegadoError:
            MessageBox.warning(
                self, "Sin permiso", f"'{usuario.nombre_usuario}' no tiene permiso para autorizar esta acción."
            )
            return

        self.usuario_autorizador = usuario
        self.motivo = motivo
        self.accept()
