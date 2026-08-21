from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.db.session import SessionLocal
from app.services.auth import authenticate


class LoginWindow(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Distribuidora DJ — Iniciar sesion")
        self.setFixedSize(320, 160)
        self.usuario_autenticado = None

        self.usuario_input = QLineEdit()
        self.clave_input = QLineEdit()
        self.clave_input.setEchoMode(QLineEdit.EchoMode.Password)

        form = QFormLayout()
        form.addRow("Usuario:", self.usuario_input)
        form.addRow("Clave:", self.clave_input)

        self.mensaje = QLabel("")
        self.mensaje.setStyleSheet("color: red;")

        login_btn = QPushButton("Ingresar")
        login_btn.clicked.connect(self.intentar_login)
        self.clave_input.returnPressed.connect(self.intentar_login)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self.mensaje)
        layout.addWidget(login_btn)
        self.setLayout(layout)

    def intentar_login(self):
        nombre_usuario = self.usuario_input.text().strip()
        clave = self.clave_input.text()

        if not nombre_usuario or not clave:
            self.mensaje.setText("Ingrese usuario y clave")
            return

        session = SessionLocal()
        try:
            usuario = authenticate(session, nombre_usuario, clave)
        except Exception as exc:
            QMessageBox.critical(self, "Error de conexion", str(exc))
            return
        finally:
            session.close()

        if usuario is None:
            self.mensaje.setText("Usuario o clave incorrectos")
            return

        self.usuario_autenticado = usuario
        self.accept()
