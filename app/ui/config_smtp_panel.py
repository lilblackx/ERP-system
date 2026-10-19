"""
Pestaña "Correo" del módulo Configuración: cuenta con la que la app manda los códigos de
desbloqueo/recuperación de clave. Antes esto solo se podía cambiar editando el .env a mano;
ahora se guarda en la base (ver app/services/smtp_config.py) y vale para todas las estaciones.

El usuario solo elige su servicio de correo (Gmail, Outlook, ...) e ingresa su cuenta y
contraseña: servidor, puerto y TLS salen del catálogo `PROVEEDORES`. "Otro" despliega los
campos manuales para quien use un servidor propio. "Probar conexión" habla con la red, así
que corre en un QueryWorker para no congelar la ventana (ver app/ui/workers.py).
"""

import logging
from decimal import Decimal

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.db.models import Usuario
from app.services.email_service import AjustesSmtp
from app.services.permisos import PermisoDenegadoError
from app.services.smtp_config import (
    _SENTINEL,
    PROVEEDOR_OTRO,
    PROVEEDORES,
    SmtpConfigService,
    proveedor_de_servidor,
    proveedor_por_clave,
)
from app.ui.message_box import MessageBox
from app.ui.numeric_inputs import NumericFieldType, NumericLineEdit
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_PRIMARY,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    COLOR_WHITE,
    ICON_CHEVRON_DOWN_URL,
)
from app.ui.workers import QueryWorker

logger = logging.getLogger(__name__)

PUERTO_POR_DEFECTO = 587

_ESTILO_INPUT = f"""
    QLineEdit {{
        border: 1px solid {COLOR_BORDER};
        border-radius: 6px;
        padding: 0 12px;
        font-size: 14px;
    }}
    QLineEdit:focus {{
        border: 1px solid {COLOR_PRIMARY};
    }}
"""
# Estilo propio del combo (no heredar GLOBAL_QSS), mismo bloque que impresora_combo en
# config_empresa_panel.py.
_ESTILO_COMBO = f"""
    QComboBox {{
        background-color: {COLOR_WHITE};
        border: 1px solid {COLOR_BORDER};
        border-radius: 6px;
        padding: 6px 28px 6px 12px;
        font-size: 14px;
        color: {COLOR_TEXT_DARK};
    }}
    QComboBox:hover {{
        border-color: {COLOR_TEXT_MUTED};
    }}
    QComboBox:focus {{
        border-color: {COLOR_PRIMARY};
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 28px;
        border: none;
        background: transparent;
    }}
    QComboBox::down-arrow {{
        image: url({ICON_CHEVRON_DOWN_URL});
        width: 12px;
        height: 12px;
        margin-right: 8px;
    }}
"""
_ESTILO_LABEL = f"font-weight: bold; color: {COLOR_TEXT_DARK}; font-size: 14px; border: none; background: transparent;"
_ESTILO_NOTA = f"color: {COLOR_TEXT_MUTED}; font-size: 12px; border: none; background: transparent;"

_AYUDA_OTRO = (
    "Pida estos datos (servidor, puerto y si usa TLS) al soporte de su proveedor de correo o al encargado de sistemas."
)


class ConfigSmtpPanel(QWidget):
    """Formulario de la cuenta de correo. La contraseña nunca se vuelve a mostrar: si ya hay
    una guardada, dejar el campo vacío la conserva."""

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self._worker: QueryWorker | None = None
        self._tiene_password = False
        self.setObjectName("ContentArea")

        self._build_ui()
        self._on_proveedor_cambiado()
        self.cargar_datos()

    # ── UI ──────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(20)

        # Selector acotado a #SectionCard, mismo criterio que ConfigEmpresaPanel: un
        # "QWidget {...}" sin ID se aplicaba a cualquier hijo sin estilo propio.
        card = QWidget()
        card.setObjectName("SectionCard")
        card.setStyleSheet(f"""
            QWidget#SectionCard {{
                background-color: {COLOR_CARD_BG};
                border: 1px solid {COLOR_BORDER};
                border-radius: 12px;
            }}
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)

        titulo = QLabel("Correo")
        titulo.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {COLOR_TEXT_DARK}; border: none; background: transparent;"
        )
        layout.addWidget(titulo)

        descripcion = QLabel(
            "Cuenta de correo desde la que el sistema envía los códigos para desbloquear una cuenta o "
            "recuperar la clave. Elija su servicio de correo e ingrese su cuenta y contraseña."
        )
        descripcion.setWordWrap(True)
        descripcion.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 13px; border: none; background: transparent;")
        layout.addWidget(descripcion)

        form = QFormLayout()
        form.setSpacing(16)

        self.proveedor_combo = QComboBox()
        self.proveedor_combo.setStyleSheet(_ESTILO_COMBO)
        self.proveedor_combo.setMinimumHeight(38)
        self.proveedor_combo.addItem("Seleccione su servicio de correo…", None)
        for proveedor in PROVEEDORES:
            self.proveedor_combo.addItem(proveedor.nombre, proveedor.clave)
        self.proveedor_combo.addItem("Otro (configuración manual)", PROVEEDOR_OTRO)
        self.proveedor_combo.currentIndexChanged.connect(self._on_proveedor_cambiado)

        self.lbl_ayuda = QLabel()
        self.lbl_ayuda.setWordWrap(True)
        self.lbl_ayuda.setStyleSheet(_ESTILO_NOTA)

        self.usuario_input = self._crear_input("Ej: cuenta@gmail.com")
        self.usuario_input.setMaxLength(255)

        self.password_input = self._crear_input("")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setMaxLength(255)

        # Combo y ayuda en una sola celda: como fila propia, la ayuda (QLabel con wordWrap)
        # dejaba un hueco grande encima y debajo.
        celda_servicio = QWidget()
        celda_servicio.setStyleSheet("background: transparent;")
        v_servicio = QVBoxLayout(celda_servicio)
        v_servicio.setContentsMargins(0, 0, 0, 0)
        v_servicio.setSpacing(6)
        v_servicio.addWidget(self.proveedor_combo)
        v_servicio.addWidget(self.lbl_ayuda)

        form.addRow(self._crear_label("Servicio de correo:"), celda_servicio)
        form.addRow(self._crear_label("Correo electrónico:"), self.usuario_input)
        form.addRow(self._crear_label("Contraseña:"), self.password_input)
        layout.addLayout(form)

        # Datos manuales: solo se muestran con "Otro", para un servidor propio/de empresa.
        self.avanzado = QWidget()
        self.avanzado.setStyleSheet("background: transparent;")
        form_avanzado = QFormLayout(self.avanzado)
        form_avanzado.setContentsMargins(0, 0, 0, 0)
        form_avanzado.setSpacing(16)

        self.host_input = self._crear_input("Ej: mail.miempresa.com")
        self.host_input.setMaxLength(255)

        self.puerto_input = NumericLineEdit(NumericFieldType.COUNT, max_value=Decimal(65535))
        self.puerto_input.setMinimumHeight(38)
        self.puerto_input.setFixedWidth(110)
        self.puerto_input.setStyleSheet(_ESTILO_INPUT)
        self.puerto_input.set_value(PUERTO_POR_DEFECTO)

        self.remitente_input = self._crear_input("Opcional — por defecto, el mismo correo electrónico")
        self.remitente_input.setMaxLength(255)

        self.tls_check = QCheckBox("Usar TLS (STARTTLS)")
        self.tls_check.setChecked(True)
        self.tls_check.setStyleSheet(f"color: {COLOR_TEXT_DARK}; font-size: 14px; background: transparent;")
        self.tls_check.setToolTip(
            "Recomendado con el puerto 587. El puerto 465 usa SSL directo y no necesita esta opción."
        )

        form_avanzado.addRow(self._crear_label("Servidor:"), self.host_input)
        form_avanzado.addRow(self._crear_label("Puerto:"), self.puerto_input)
        form_avanzado.addRow(self._crear_label("Remitente:"), self.remitente_input)
        form_avanzado.addRow("", self.tls_check)
        layout.addWidget(self.avanzado)

        self.lbl_origen = QLabel()
        self.lbl_origen.setWordWrap(True)
        self.lbl_origen.setStyleSheet(_ESTILO_NOTA)
        layout.addWidget(self.lbl_origen)

        botones = QHBoxLayout()
        self.btn_probar = QPushButton("Probar conexión")
        self.btn_probar.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_probar.setMinimumHeight(44)
        self.btn_probar.clicked.connect(self.probar_conexion)
        self.btn_guardar = QPushButton("Guardar Cambios")
        self.btn_guardar.setStyleSheet(BUTTON_PRIMARY_QSS)
        self.btn_guardar.setMinimumHeight(44)
        self.btn_guardar.setMinimumWidth(200)
        self.btn_guardar.clicked.connect(self.guardar_cambios)
        botones.addStretch()
        botones.addWidget(self.btn_probar)
        botones.addWidget(self.btn_guardar)
        layout.addLayout(botones)
        layout.addStretch()

        # Scroll por el mismo motivo que en ConfigEmpresaPanel: en una ventana baja el
        # layout no tiene donde recortar y comprime las filas.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.setWidget(card)
        root.addWidget(scroll, stretch=1)

        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

    @staticmethod
    def _crear_input(placeholder: str) -> QLineEdit:
        campo = QLineEdit()
        campo.setPlaceholderText(placeholder)
        campo.setMinimumHeight(38)
        campo.setStyleSheet(_ESTILO_INPUT)
        return campo

    @staticmethod
    def _crear_label(texto: str) -> QLabel:
        lbl = QLabel(texto)
        lbl.setStyleSheet(_ESTILO_LABEL)
        return lbl

    # ── Proveedor ───────────────────────────────────────────────────────────

    def _on_proveedor_cambiado(self, _indice: int = 0) -> None:
        clave = self.proveedor_combo.currentData()
        proveedor = proveedor_por_clave(clave)
        if proveedor is not None:
            self.lbl_ayuda.setText(proveedor.ayuda)
        elif clave == PROVEEDOR_OTRO:
            self.lbl_ayuda.setText(_AYUDA_OTRO)
        else:
            self.lbl_ayuda.setText("")
        self.lbl_ayuda.setVisible(bool(self.lbl_ayuda.text()))
        self.avanzado.setVisible(clave == PROVEEDOR_OTRO)

    def _conexion_elegida(self) -> tuple[str, int, bool, str] | None:
        """(host, puerto, usar_tls, remitente) segun lo elegido, o None si todavia no se
        eligio ningun servicio. Con un proveedor del catalogo todo sale de ahi; solo con
        "Otro" se leen los campos manuales."""
        clave = self.proveedor_combo.currentData()
        proveedor = proveedor_por_clave(clave)
        if proveedor is not None:
            return proveedor.host, proveedor.puerto, proveedor.usar_tls, ""
        if clave == PROVEEDOR_OTRO:
            return (
                self.host_input.text().strip(),
                self._puerto_manual(),
                self.tls_check.isChecked(),
                self.remitente_input.text().strip(),
            )
        return None

    def _puerto_manual(self) -> int:
        valor = self.puerto_input.get_value()
        return int(valor) if valor is not None else 0

    # ── Carga / guardado ────────────────────────────────────────────────────

    def cargar_datos(self) -> None:
        session = self.session_factory()
        try:
            fila = SmtpConfigService.obtener_configuracion(session, self.usuario.id_usuario)
            if fila is None:
                self.proveedor_combo.setCurrentIndex(0)
                self._tiene_password = False
                self.lbl_origen.setText(
                    "Todavía no se configuró aquí: mientras tanto el sistema usa las variables SMTP_* del "
                    "archivo .env, si existen."
                )
            else:
                clave = proveedor_de_servidor(fila.host, fila.puerto, bool(fila.usar_tls))
                self.proveedor_combo.setCurrentIndex(max(self.proveedor_combo.findData(clave), 0))
                self.usuario_input.setText(fila.usuario or "")
                self.host_input.setText(fila.host or "")
                self.puerto_input.set_value(fila.puerto)
                self.remitente_input.setText(fila.remitente or "")
                self.tls_check.setChecked(bool(fila.usar_tls))
                self._tiene_password = bool(fila.password)
                self.lbl_origen.setText("Esta configuración se comparte con todas las estaciones.")
            self._on_proveedor_cambiado()
            self.password_input.clear()
            self.password_input.setPlaceholderText(
                "Guardada — déjelo vacío para no cambiarla" if self._tiene_password else "Contraseña de la cuenta"
            )
        except PermisoDenegadoError:
            self._deshabilitar_por_permiso()
        except Exception:
            logger.exception("Fallo al cargar la configuración SMTP")
        finally:
            session.close()

    def _deshabilitar_por_permiso(self) -> None:
        for control in (
            self.proveedor_combo,
            self.usuario_input,
            self.password_input,
            self.avanzado,
            self.btn_probar,
            self.btn_guardar,
        ):
            control.setEnabled(False)
        self.lbl_origen.setText("No tiene permiso para ver esta configuración.")

    def guardar_cambios(self) -> None:
        conexion = self._conexion_elegida()
        if conexion is None:
            MessageBox.warning(self, "Dato requerido", "Seleccione su servicio de correo.")
            self.proveedor_combo.setFocus()
            return
        host, puerto, usar_tls, remitente = conexion

        usuario = self.usuario_input.text().strip()
        if not usuario:
            MessageBox.warning(self, "Dato requerido", "Ingrese su correo electrónico.")
            self.usuario_input.setFocus()
            return
        password = self.password_input.text()
        if not password and not self._tiene_password:
            MessageBox.warning(self, "Dato requerido", "Ingrese la contraseña de la cuenta de correo.")
            self.password_input.setFocus()
            return

        session = self.session_factory()
        try:
            SmtpConfigService.guardar_configuracion(
                session=session,
                host=host,
                puerto=puerto,
                usuario=usuario,
                # Vacío = conservar la guardada (el campo nunca la muestra).
                password=password if password else _SENTINEL,
                remitente=remitente,
                usar_tls=usar_tls,
                modificado_por=self.usuario.id_usuario,
            )
            MessageBox.information(self, "Éxito", "Configuración de correo guardada correctamente.")
            self.cargar_datos()
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para editar la configuración de correo.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al guardar la configuración SMTP")
            MessageBox.critical(self, "Error", "No se pudo guardar la configuración. Intente nuevamente.")
        finally:
            session.close()

    # ── Probar conexión (en segundo plano) ──────────────────────────────────

    def probar_conexion(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return

        conexion = self._conexion_elegida()
        if conexion is None:
            MessageBox.warning(self, "Dato requerido", "Seleccione su servicio de correo.")
            return
        host, puerto, usar_tls, remitente = conexion
        if not host:
            MessageBox.warning(self, "Dato requerido", "Ingrese el servidor SMTP.")
            return
        if not 1 <= puerto <= 65535:
            MessageBox.warning(self, "Dato inválido", "El puerto debe estar entre 1 y 65535.")
            return

        usuario = self.usuario_input.text().strip()
        password = self.password_input.text()
        id_usuario = self.usuario.id_usuario

        def _tarea(session):
            clave = password
            if not clave:
                # Campo vacío = "usar la guardada": se lee acá, en el hilo del worker.
                fila = SmtpConfigService.obtener_configuracion(session, id_usuario)
                clave = (fila.password if fila else None) or ""
            SmtpConfigService.probar_conexion(
                AjustesSmtp(
                    host=host,
                    puerto=puerto,
                    usuario=usuario,
                    password=clave,
                    remitente=remitente,
                    usar_tls=usar_tls,
                )
            )

        self._ocupado(True)
        self._worker = QueryWorker(self.session_factory, _tarea)
        self._worker.resultado.connect(self._on_prueba_ok)
        self._worker.error.connect(self._on_prueba_error)
        self._worker.start()

    def _ocupado(self, ocupado: bool) -> None:
        self.btn_probar.setEnabled(not ocupado)
        self.btn_probar.setText("Probando..." if ocupado else "Probar conexión")

    def _on_prueba_ok(self, _resultado) -> None:
        self._ocupado(False)
        MessageBox.information(self, "Conexión exitosa", "El servidor aceptó el usuario y la contraseña.")

    def _on_prueba_error(self, mensaje: str) -> None:
        # QueryWorker solo pasa str(excepcion): SmtpConfigService.probar_conexion ya
        # convierte las fallas de smtplib en mensajes pensados para el usuario.
        self._ocupado(False)
        MessageBox.warning(self, "No se pudo conectar", mensaje or "No se pudo completar la prueba.")
