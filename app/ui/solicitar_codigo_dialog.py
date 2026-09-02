"""
SolicitarCodigoDialog — dialogo de 2 pasos (pedir codigo -> verificarlo) reusado para
los dos flujos de recuperacion de acceso: desbloqueo de cuenta (C7) y clave olvidada
(C6/C7). Un solo archivo parametrizado por `tipo` en vez de dos dialogos casi
identicos -- solo el paso de verificacion difiere (RECUPERAR_CLAVE agrega los campos de
clave nueva).
"""

import logging

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.recuperacion_acceso import (
    TIPO_DESBLOQUEO,
    TIPO_RECUPERAR_CLAVE,
    RecuperacionAccesoService,
)
from app.ui.message_box import MessageBox
from app.ui.styles import (
    COLOR_BORDER,
    COLOR_CONTENT_BG,
    COLOR_FIELD_BG,
    COLOR_PRIMARY,
    COLOR_PRIMARY_DARK,
    COLOR_PRIMARY_LIGHT,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    FONT_FAMILY,
)

logger = logging.getLogger(__name__)

_TITULOS = {
    TIPO_DESBLOQUEO: "Desbloquear cuenta",
    TIPO_RECUPERAR_CLAVE: "Recuperar clave",
}
_ICONOS = {
    TIPO_DESBLOQUEO: "fa5s.unlock-alt",
    TIPO_RECUPERAR_CLAVE: "fa5s.key",
}
_SUBTITULOS = {
    TIPO_DESBLOQUEO: "Ingresa tu usuario y te enviaremos un código a tu correo registrado para desbloquear tu cuenta.",
    TIPO_RECUPERAR_CLAVE: "Ingresa tu usuario y te enviaremos un código a tu correo registrado "
    "para restablecer tu clave.",
}

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


class SolicitarCodigoDialog(QDialog):
    def __init__(self, session_factory, tipo: str, nombre_usuario: str = "", parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.tipo = tipo
        self._nombre_usuario_confirmado: str | None = None

        self.setWindowTitle(_TITULOS[tipo])
        self.setMinimumWidth(420)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)
        root.addLayout(self._build_header(tipo))

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_paso_solicitar(nombre_usuario))
        self.stack.addWidget(self._build_paso_verificar())
        root.addWidget(self.stack)

    # ── Header ──────────────────────────────────────────────────────────────

    def _build_header(self, tipo: str) -> QHBoxLayout:
        header = QHBoxLayout()
        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon(_ICONOS[tipo], color=COLOR_PRIMARY).pixmap(22, 22))
        titulos = QVBoxLayout()
        titulos.setSpacing(1)
        lbl_titulo = QLabel(self.windowTitle())
        lbl_titulo.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        lbl_subtitulo = QLabel(_SUBTITULOS[tipo])
        lbl_subtitulo.setWordWrap(True)
        lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        titulos.addWidget(lbl_titulo)
        titulos.addWidget(lbl_subtitulo)
        header.addWidget(icon_lbl)
        header.addLayout(titulos, stretch=1)
        return header

    # ── Paso 1: pedir el codigo ────────────────────────────────────────────

    def _build_paso_solicitar(self, nombre_usuario: str) -> QWidget:
        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)

        lbl_usuario = QLabel("Usuario")
        lbl_usuario.setProperty("class", "FormLabel")
        self.usuario_input = QLineEdit(nombre_usuario)
        self.usuario_input.setPlaceholderText("Nombre de usuario")
        self.usuario_input.returnPressed.connect(self._enviar_codigo)
        layout.addWidget(lbl_usuario)
        layout.addWidget(self.usuario_input)
        layout.addStretch()

        footer = QHBoxLayout()
        footer.addStretch()
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setObjectName("BtnSecondary")
        btn_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancelar.clicked.connect(self.reject)
        btn_enviar = QPushButton("Enviar código al correo")
        btn_enviar.setIcon(qta.icon("fa5s.paper-plane", color="#FFFFFF"))
        btn_enviar.setObjectName("BtnPrimary")
        btn_enviar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_enviar.clicked.connect(self._enviar_codigo)
        footer.addWidget(btn_cancelar)
        footer.addWidget(btn_enviar)
        layout.addLayout(footer)

        return pagina

    def _enviar_codigo(self) -> None:
        nombre_usuario = self.usuario_input.text().strip()
        if not nombre_usuario:
            MessageBox.warning(self, "Dato requerido", "Ingrese el nombre de usuario.")
            return

        session = self.session_factory()
        try:
            if self.tipo == TIPO_DESBLOQUEO:
                mensaje = RecuperacionAccesoService.solicitar_codigo_desbloqueo(session, nombre_usuario)
            else:
                mensaje = RecuperacionAccesoService.solicitar_codigo_recuperacion(session, nombre_usuario)
        except Exception:
            logger.exception("Fallo al solicitar codigo (%s) para '%s'", self.tipo, nombre_usuario)
            MessageBox.critical(self, "Error", "No se pudo enviar el codigo. Intente nuevamente mas tarde.")
            return
        finally:
            session.close()

        self._nombre_usuario_confirmado = nombre_usuario
        MessageBox.information(self, "Codigo enviado", mensaje)
        self.stack.setCurrentIndex(1)
        self.codigo_input.setFocus()

    # ── Paso 2: verificar el codigo ────────────────────────────────────────

    def _build_paso_verificar(self) -> QWidget:
        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)

        lbl_codigo = QLabel("Código recibido")
        lbl_codigo.setProperty("class", "FormLabel")
        self.codigo_input = QLineEdit()
        self.codigo_input.setPlaceholderText("123456")
        self.codigo_input.setMaxLength(6)
        layout.addWidget(lbl_codigo)
        layout.addWidget(self.codigo_input)

        if self.tipo == TIPO_RECUPERAR_CLAVE:
            layout.addSpacing(6)
            lbl_politica = QLabel(
                "La clave nueva debe tener mínimo 8 caracteres, con al menos una "
                "mayúscula, una minúscula, un número y un carácter especial."
            )
            lbl_politica.setWordWrap(True)
            lbl_politica.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_MUTED};")
            layout.addWidget(lbl_politica)
            layout.addSpacing(4)

            lbl_clave_nueva = QLabel("Clave nueva")
            lbl_clave_nueva.setProperty("class", "FormLabel")
            self.nueva_clave_input = QLineEdit()
            self.nueva_clave_input.setEchoMode(QLineEdit.EchoMode.Password)
            layout.addWidget(lbl_clave_nueva)
            layout.addWidget(self.nueva_clave_input)

            lbl_confirmar = QLabel("Confirmar clave")
            lbl_confirmar.setProperty("class", "FormLabel")
            self.confirmar_clave_input = QLineEdit()
            self.confirmar_clave_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.confirmar_clave_input.returnPressed.connect(self._verificar_codigo)
            layout.addWidget(lbl_confirmar)
            layout.addWidget(self.confirmar_clave_input)
        else:
            self.codigo_input.returnPressed.connect(self._verificar_codigo)

        layout.addSpacing(8)

        footer = QHBoxLayout()
        footer.addStretch()
        btn_atras = QPushButton("Atrás")
        btn_atras.setObjectName("BtnSecondary")
        btn_atras.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_atras.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        etiqueta_confirmar = "Cambiar clave" if self.tipo == TIPO_RECUPERAR_CLAVE else "Desbloquear"
        btn_verificar = QPushButton(etiqueta_confirmar)
        btn_verificar.setIcon(qta.icon("fa5s.check", color="#FFFFFF"))
        btn_verificar.setObjectName("BtnPrimary")
        btn_verificar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_verificar.clicked.connect(self._verificar_codigo)
        footer.addWidget(btn_atras)
        footer.addWidget(btn_verificar)
        layout.addLayout(footer)

        return pagina

    def _verificar_codigo(self) -> None:
        codigo = self.codigo_input.text().strip()
        if not codigo:
            MessageBox.warning(self, "Dato requerido", "Ingrese el codigo recibido.")
            return

        if self.tipo == TIPO_RECUPERAR_CLAVE:
            nueva_clave = self.nueva_clave_input.text()
            if nueva_clave != self.confirmar_clave_input.text():
                MessageBox.warning(self, "Error", "Las claves no coinciden.")
                return

        session = self.session_factory()
        try:
            if self.tipo == TIPO_DESBLOQUEO:
                RecuperacionAccesoService.verificar_codigo_desbloqueo(session, self._nombre_usuario_confirmado, codigo)
                MessageBox.information(self, "Listo", "Cuenta desbloqueada. Ya puede iniciar sesion.")
            else:
                RecuperacionAccesoService.verificar_codigo_y_cambiar_clave(
                    session, self._nombre_usuario_confirmado, codigo, nueva_clave
                )
                MessageBox.information(self, "Listo", "Clave actualizada. Ya puede iniciar sesion.")
        except ValueError as exc:
            # Mensajes ya pensados para el usuario final (codigo invalido/vencido,
            # politica de clave) -- no son un str(exc) tecnico, mismo criterio que C3.
            MessageBox.warning(self, "Error", str(exc))
            return
        except Exception:
            logger.exception("Fallo al verificar codigo (%s) para '%s'", self.tipo, self._nombre_usuario_confirmado)
            MessageBox.critical(self, "Error", "Ocurrio un error inesperado. Intente nuevamente.")
            return
        finally:
            session.close()

        self.accept()
