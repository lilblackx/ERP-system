"""
LoginWindow — Pantalla de inicio de sesión moderna del ERP.
Diseño: Split-screen (izquierda azul con bienvenida, derecha blanca con formulario).
"""

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
import qtawesome as qta

from app.db.models import ConfiguracionEmpresa
from app.db.session import SessionLocal
from app.services.auth import CuentaBloqueadaError, authenticate
from app.services.recuperacion_acceso import TIPO_DESBLOQUEO, TIPO_RECUPERAR_CLAVE
from app.ui.solicitar_codigo_dialog import SolicitarCodigoDialog
from app.ui.styles import (
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_DANGER,
    COLOR_PRIMARY,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    FONT_FAMILY,
)

logger = logging.getLogger(__name__)

# Color azul claro similar al de la imagen de referencia
COLOR_LEFT_BG = "#7A96EA"


class LoginWindow(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ERP — Iniciar Sesión")
        self.setFixedSize(850, 500)
        self.usuario_autenticado = None

        # Obtener nombre de empresa
        empresa = "Mi Empresa"
        session = SessionLocal()
        try:
            config = session.query(ConfiguracionEmpresa).first()
            if config and config.razon_social_empresa:
                empresa = config.razon_social_empresa
        except Exception:
            logger.exception("No se pudo cargar el nombre de la empresa para la pantalla de login")
        finally:
            session.close()

        # Eliminar márgenes del QDialog base
        self.setStyleSheet(f"QDialog {{ background-color: {COLOR_CARD_BG}; font-family: '{FONT_FAMILY}', Arial; }}")

        self._build_ui(empresa)

    # ── Construcción de la UI ─────────────────────────────────────────────

    def _build_ui(self, empresa_nombre: str) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Panel Izquierdo (Azul) ──
        left_panel = QWidget()
        left_panel.setObjectName("LeftPanel")
        left_panel.setFixedWidth(400)
        left_panel.setStyleSheet(f"""
            QWidget#LeftPanel {{
                background-color: {COLOR_LEFT_BG};
                border-top-right-radius: 60px;
                border-bottom-right-radius: 60px;
            }}
        """)

        left_layout = QVBoxLayout(left_panel)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.setSpacing(16)
        left_layout.setContentsMargins(40, 40, 40, 40)

        lbl_hola = QLabel("Hola, Bienvenido")
        lbl_hola.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_hola.setStyleSheet("color: white; font-size: 32px; font-weight: bold; background: transparent;")

        lbl_empresa = QLabel(empresa_nombre)
        lbl_empresa.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_empresa.setStyleSheet("color: white; font-size: 24px; font-weight: normal; background: transparent;")
        lbl_empresa.setWordWrap(True)

        left_layout.addStretch()
        left_layout.addWidget(lbl_hola)
        left_layout.addWidget(lbl_empresa)
        left_layout.addStretch()

        # ── Panel Derecho (Blanco) ──
        right_panel = QWidget()
        right_panel.setObjectName("RightPanel")
        right_panel.setStyleSheet(f"""
            QWidget#RightPanel {{
                background-color: {COLOR_CARD_BG};
            }}
        """)

        right_layout = QVBoxLayout(right_panel)
        right_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.setSpacing(20)
        right_layout.setContentsMargins(80, 40, 80, 40)

        lbl_titulo = QLabel("Iniciar Sesion")
        lbl_titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_titulo.setStyleSheet(f"color: {COLOR_TEXT_DARK}; font-size: 36px; font-weight: bold;")
        right_layout.addWidget(lbl_titulo)
        right_layout.addSpacing(20)

        # Input Usuario
        self.usuario_input = QLineEdit()
        self.usuario_input.setPlaceholderText("Usuario")
        self.usuario_input.setStyleSheet(self._campo_qss())
        self.usuario_input.setFixedHeight(40)

        user_layout = QHBoxLayout()
        user_layout.addWidget(self.usuario_input)
        lbl_user_icon = QLabel()
        lbl_user_icon.setPixmap(qta.icon("fa5s.user", color=COLOR_TEXT_MUTED).pixmap(18, 18))
        lbl_user_icon.setStyleSheet("background: transparent;")
        user_layout.addWidget(lbl_user_icon)
        right_layout.addLayout(user_layout)

        # Input Password
        self.clave_input = QLineEdit()
        self.clave_input.setPlaceholderText("Password")
        self.clave_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.clave_input.setStyleSheet(self._campo_qss())
        self.clave_input.setFixedHeight(40)
        self.clave_input.returnPressed.connect(self.intentar_login)

        pass_layout = QHBoxLayout()
        pass_layout.addWidget(self.clave_input)
        lbl_pass_icon = QLabel()
        lbl_pass_icon.setPixmap(qta.icon("fa5s.lock", color=COLOR_TEXT_MUTED).pixmap(18, 18))
        lbl_pass_icon.setStyleSheet("background: transparent;")
        pass_layout.addWidget(lbl_pass_icon)
        right_layout.addLayout(pass_layout)

        # Olvidaste tu contraseña
        lbl_olvidaste = QLabel("¿Olvidaste tu contraseña?")
        lbl_olvidaste.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_olvidaste.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        lbl_olvidaste.setStyleSheet(f"color: {COLOR_PRIMARY}; font-size: 13px; text-decoration: underline;")
        lbl_olvidaste.mousePressEvent = lambda event: self._abrir_recuperar_clave()
        right_layout.addWidget(lbl_olvidaste)

        # Mensaje de error (oculto por defecto)
        self.mensaje = QLabel("")
        self.mensaje.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mensaje.setFixedHeight(20)
        self.mensaje.setStyleSheet(f"color: {COLOR_DANGER}; font-size: 12px;")
        right_layout.addWidget(self.mensaje)

        # Botón Iniciar Sesion
        self.btn_login = QPushButton("Iniciar Sesion")
        self.btn_login.setFixedHeight(46)
        self.btn_login.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_login.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_LEFT_BG};
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #6382DA;
            }}
        """)
        self.btn_login.clicked.connect(self.intentar_login)
        right_layout.addWidget(self.btn_login)

        # Redes sociales (eliminadas a petición)
        right_layout.addStretch()

        # Ensamblar
        root.addWidget(left_panel)
        root.addWidget(right_panel)

    def _campo_qss(self) -> str:
        return f"""
            QLineEdit {{
                background-color: transparent;
                border: none;
                border-bottom: 2px solid {COLOR_BORDER};
                padding: 0 4px;
                font-size: 14px;
                color: {COLOR_TEXT_DARK};
            }}
            QLineEdit:focus {{
                border-bottom: 2px solid {COLOR_LEFT_BG};
            }}
        """

    # ── Lógica de autenticación ───────────────────────────────────────────

    def intentar_login(self) -> None:
        nombre_usuario = self.usuario_input.text().strip()
        clave = self.clave_input.text()
        self.mensaje.setText("")

        if not nombre_usuario or not clave:
            self.mensaje.setText("⚠ Ingrese usuario y contraseña")
            return

        self.btn_login.setText("Verificando…")
        self.btn_login.setEnabled(False)

        session = SessionLocal()
        try:
            usuario = authenticate(session, nombre_usuario, clave)
        except CuentaBloqueadaError:
            self.mensaje.setText("⚠ Cuenta bloqueada por intentos fallidos")
            self.clave_input.clear()
            self.clave_input.setFocus()
            dialogo = SolicitarCodigoDialog(SessionLocal, TIPO_DESBLOQUEO, nombre_usuario, parent=self)
            dialogo.exec()
            return
        except Exception:
            logger.exception("Fallo al autenticar al usuario '%s'", nombre_usuario)
            QMessageBox.critical(self, "Error de conexión", "No se pudo conectar con el servidor. Intente nuevamente.")
            return
        finally:
            session.close()
            self.btn_login.setText("Iniciar Sesion")
            self.btn_login.setEnabled(True)

        if usuario is None:
            self.mensaje.setText("✖ Usuario o contraseña incorrectos")
            self.clave_input.clear()
            self.clave_input.setFocus()
            return

        self.usuario_autenticado = usuario
        self.accept()

    def _abrir_recuperar_clave(self) -> None:
        nombre_usuario = self.usuario_input.text().strip()
        dialogo = SolicitarCodigoDialog(SessionLocal, TIPO_RECUPERAR_CLAVE, nombre_usuario, parent=self)
        dialogo.exec()
