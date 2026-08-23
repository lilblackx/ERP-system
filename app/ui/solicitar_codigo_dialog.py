"""
SolicitarCodigoDialog — dialogo de 2 pasos (pedir codigo -> verificarlo) reusado para
los dos flujos de recuperacion de acceso: desbloqueo de cuenta (C7) y clave olvidada
(C6/C7). Un solo archivo parametrizado por `tipo` en vez de dos dialogos casi
identicos -- solo el paso de verificacion difiere (RECUPERAR_CLAVE agrega los campos de
clave nueva).
"""

import logging

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
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

logger = logging.getLogger(__name__)

_TITULOS = {
    TIPO_DESBLOQUEO: "Desbloquear cuenta",
    TIPO_RECUPERAR_CLAVE: "Recuperar clave",
}


class SolicitarCodigoDialog(QDialog):
    def __init__(self, session_factory, tipo: str, nombre_usuario: str = "", parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.tipo = tipo
        self._nombre_usuario_confirmado: str | None = None

        self.setWindowTitle(_TITULOS[tipo])
        self.setMinimumWidth(360)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_paso_solicitar(nombre_usuario))
        self.stack.addWidget(self._build_paso_verificar())

        layout = QVBoxLayout(self)
        layout.addWidget(self.stack)

    # ── Paso 1: pedir el codigo ────────────────────────────────────────────

    def _build_paso_solicitar(self, nombre_usuario: str) -> QWidget:
        pagina = QWidget()
        form = QFormLayout(pagina)

        self.usuario_input = QLineEdit(nombre_usuario)
        self.usuario_input.setPlaceholderText("Nombre de usuario")
        form.addRow("Usuario:", self.usuario_input)

        btn_enviar = QPushButton("Enviar codigo al correo")
        btn_enviar.clicked.connect(self._enviar_codigo)
        form.addRow(btn_enviar)

        return pagina

    def _enviar_codigo(self) -> None:
        nombre_usuario = self.usuario_input.text().strip()
        if not nombre_usuario:
            QMessageBox.warning(self, "Dato requerido", "Ingrese el nombre de usuario.")
            return

        session = self.session_factory()
        try:
            if self.tipo == TIPO_DESBLOQUEO:
                mensaje = RecuperacionAccesoService.solicitar_codigo_desbloqueo(session, nombre_usuario)
            else:
                mensaje = RecuperacionAccesoService.solicitar_codigo_recuperacion(session, nombre_usuario)
        except Exception:
            logger.exception("Fallo al solicitar codigo (%s) para '%s'", self.tipo, nombre_usuario)
            QMessageBox.critical(self, "Error", "No se pudo enviar el codigo. Intente nuevamente mas tarde.")
            return
        finally:
            session.close()

        self._nombre_usuario_confirmado = nombre_usuario
        QMessageBox.information(self, "Codigo enviado", mensaje)
        self.stack.setCurrentIndex(1)

    # ── Paso 2: verificar el codigo ────────────────────────────────────────

    def _build_paso_verificar(self) -> QWidget:
        pagina = QWidget()
        form = QFormLayout(pagina)

        self.codigo_input = QLineEdit()
        self.codigo_input.setPlaceholderText("123456")
        self.codigo_input.setMaxLength(6)
        form.addRow("Codigo recibido:", self.codigo_input)

        if self.tipo == TIPO_RECUPERAR_CLAVE:
            lbl_politica = QLabel(
                "La clave nueva debe tener minimo 8 caracteres, con al menos una "
                "mayuscula, una minuscula, un numero y un caracter especial."
            )
            lbl_politica.setWordWrap(True)
            form.addRow(lbl_politica)

            self.nueva_clave_input = QLineEdit()
            self.nueva_clave_input.setEchoMode(QLineEdit.EchoMode.Password)
            form.addRow("Clave nueva:", self.nueva_clave_input)

            self.confirmar_clave_input = QLineEdit()
            self.confirmar_clave_input.setEchoMode(QLineEdit.EchoMode.Password)
            form.addRow("Confirmar clave:", self.confirmar_clave_input)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._verificar_codigo)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        return pagina

    def _verificar_codigo(self) -> None:
        codigo = self.codigo_input.text().strip()
        if not codigo:
            QMessageBox.warning(self, "Dato requerido", "Ingrese el codigo recibido.")
            return

        if self.tipo == TIPO_RECUPERAR_CLAVE:
            nueva_clave = self.nueva_clave_input.text()
            if nueva_clave != self.confirmar_clave_input.text():
                QMessageBox.warning(self, "Error", "Las claves no coinciden.")
                return

        session = self.session_factory()
        try:
            if self.tipo == TIPO_DESBLOQUEO:
                RecuperacionAccesoService.verificar_codigo_desbloqueo(session, self._nombre_usuario_confirmado, codigo)
                QMessageBox.information(self, "Listo", "Cuenta desbloqueada. Ya puede iniciar sesion.")
            else:
                RecuperacionAccesoService.verificar_codigo_y_cambiar_clave(
                    session, self._nombre_usuario_confirmado, codigo, nueva_clave
                )
                QMessageBox.information(self, "Listo", "Clave actualizada. Ya puede iniciar sesion.")
        except ValueError as exc:
            # Mensajes ya pensados para el usuario final (codigo invalido/vencido,
            # politica de clave) -- no son un str(exc) tecnico, mismo criterio que C3.
            QMessageBox.warning(self, "Error", str(exc))
            return
        except Exception:
            logger.exception("Fallo al verificar codigo (%s) para '%s'", self.tipo, self._nombre_usuario_confirmado)
            QMessageBox.critical(self, "Error", "Ocurrio un error inesperado. Intente nuevamente.")
            return
        finally:
            session.close()

        self.accept()
