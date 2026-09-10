"""Dialogo de apertura de turno de caja: gate de entrada al modulo de Facturacion (ver
FacturacionPanel._verificar_caja_abierta). Pide usuario+clave de quien va a operar la
caja -- no asume que es el mismo usuario logueado en la app, mismo patron que
AutorizacionDescuentoDialog (app/ui/autorizacion_dialog.py) -- y solo despues de
verificar esas credenciales muestra la caja a abrir y el saldo de apertura, ya que
listar las cajas disponibles (CajaService.listar_cajas) requiere un actor autenticado
para el chequeo de permisos (RBAC: id_usuario=None se trata como no autorizado, ver
require_permiso en app/services/permisos.py)."""

import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from app.db.models import Caja, Usuario
from app.services.auth import CuentaBloqueadaError, authenticate
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import CajaService
from app.ui.message_box import MessageBox
from app.ui.numeric_inputs import NumericFieldType, NumericLineEdit
from app.ui.styles import (
    ASTERISCO_REQUERIDO,
    COLOR_BLUE_LIGHTER,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_FIELD_BG,
    COLOR_INFO_BG,
    COLOR_PRIMARY,
    COLOR_PRIMARY_DARK,
    COLOR_PRIMARY_LIGHT,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_DARK_SLATE,
    COLOR_TEXT_MEDIUM,
    COLOR_TEXT_MUTED,
    COLOR_WHITE,
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
    color: {COLOR_TEXT_DARK_SLATE};
    margin-bottom: 2px;
}}
QLineEdit, QComboBox {{
    background-color: {COLOR_WHITE};
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
QComboBox {{
    padding-right: 24px;
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
QLineEdit:disabled {{
    background-color: {COLOR_FIELD_BG};
    color: {COLOR_TEXT_MUTED};
}}
QPushButton#BtnPrimary {{
    background-color: {COLOR_PRIMARY};
    color: {COLOR_WHITE};
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
    color: {COLOR_TEXT_MEDIUM};
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


class CajaAperturaDialog(QDialog):
    """Gate de dos pasos: primero verifica usuario+clave (authenticate(), sin cerrar la
    sesion de quien tenga la app abierta) y solo despues deja elegir la caja y el saldo
    de apertura, con ese usuario como dueño del turno. Tras exec() == Accepted,
    `caja_abierta` y `usuario_autenticado` quedan poblados."""

    def __init__(self, session: Session, parent=None):
        super().__init__(parent)
        self.session = session
        self.caja_abierta: Caja | None = None
        self.usuario_autenticado: Usuario | None = None
        self._verificado = False

        self.setWindowTitle("Abrir Turno de Caja")
        self.setFixedWidth(420)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.cash-register", color=COLOR_PRIMARY).pixmap(QSize(20, 20)))
        icon_lbl.setStyleSheet(
            f"background-color: {COLOR_INFO_BG}; border: 1.5px solid "
            f"{COLOR_BLUE_LIGHTER}; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(34, 34)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        titulos = QVBoxLayout()
        titulos.setSpacing(1)
        lbl_titulo = QLabel("Abrir Turno de Caja")
        lbl_titulo.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        self.lbl_subtitulo = QLabel("Identifíquese para poder facturar.")
        self.lbl_subtitulo.setWordWrap(True)
        self.lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        titulos.addWidget(lbl_titulo)
        titulos.addWidget(self.lbl_subtitulo)
        header.addWidget(icon_lbl)
        header.addLayout(titulos, stretch=1)
        root.addLayout(header)

        root.addWidget(self._make_card_identificacion())
        self.card_apertura = self._make_card_apertura()
        self.card_apertura.hide()
        root.addWidget(self.card_apertura)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 4, 0, 0)
        footer.setSpacing(10)
        footer.addStretch()

        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.setIcon(qta.icon("fa5s.times", color="#475569"))
        self.btn_cancelar.setObjectName("BtnSecondary")
        self.btn_cancelar.setFixedHeight(34)
        self.btn_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancelar.setAutoDefault(False)
        self.btn_cancelar.clicked.connect(self.reject)

        self.btn_principal = QPushButton("Verificar identidad")
        self.btn_principal.setIcon(qta.icon("fa5s.user-check", color="#FFFFFF"))
        self.btn_principal.setObjectName("BtnPrimary")
        self.btn_principal.setFixedHeight(34)
        self.btn_principal.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_principal.setAutoDefault(False)
        self.btn_principal.clicked.connect(self._on_click_boton_principal)

        footer.addWidget(self.btn_cancelar)
        footer.addWidget(self.btn_principal)
        root.addLayout(footer)

    def _make_card_identificacion(self) -> QWidget:
        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        lbl_usuario = QLabel(f"Usuario {ASTERISCO_REQUERIDO}")
        lbl_usuario.setProperty("class", "FormLabel")
        self.usuario_input = QLineEdit()
        layout.addWidget(lbl_usuario)
        layout.addWidget(self.usuario_input)

        lbl_clave = QLabel(f"Clave {ASTERISCO_REQUERIDO}")
        lbl_clave.setProperty("class", "FormLabel")
        self.clave_input = QLineEdit()
        self.clave_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(lbl_clave)
        layout.addWidget(self.clave_input)

        return card

    def _make_card_apertura(self) -> QWidget:
        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        lbl_caja = QLabel(f"Caja {ASTERISCO_REQUERIDO}")
        lbl_caja.setProperty("class", "FormLabel")
        self.caja_combo = QComboBox()
        self.caja_combo.setFixedHeight(32)
        layout.addWidget(lbl_caja)
        layout.addWidget(self.caja_combo)

        lbl_saldo = QLabel("Saldo de Apertura")
        lbl_saldo.setProperty("class", "FormLabel")
        self.saldo_input = NumericLineEdit(NumericFieldType.AMOUNT, prefix="$ ")
        self.saldo_input.setFixedHeight(32)
        layout.addWidget(lbl_saldo)
        layout.addWidget(self.saldo_input)

        return card

    # ── Paso 1: identidad ──────────────────────────────────────────────────

    def _on_click_boton_principal(self) -> None:
        if not self._verificado:
            self._verificar_identidad()
        else:
            self._abrir()

    def _verificar_identidad(self) -> None:
        nombre_usuario = self.usuario_input.text().strip()
        clave = self.clave_input.text()
        if not nombre_usuario or not clave:
            MessageBox.warning(self, "Credenciales requeridas", "Ingrese usuario y clave.")
            return

        try:
            usuario = authenticate(
                self.session,
                nombre_usuario,
                clave,
                accion_exito="APERTURA_TURNO_CAJA",
                accion_fallo="APERTURA_TURNO_CAJA_FALLIDA",
            )
        except CuentaBloqueadaError as exc:
            MessageBox.critical(self, "Cuenta bloqueada", str(exc))
            return

        if usuario is None:
            MessageBox.warning(self, "Credenciales inválidas", "Usuario o clave incorrectos.")
            return

        try:
            cajas = CajaService.listar_cajas(self.session, id_usuario=usuario.id_usuario)
        except PermisoDenegadoError:
            MessageBox.warning(
                self, "Sin permiso", f"'{usuario.nombre_usuario}' no tiene permiso para abrir turnos de caja."
            )
            return

        cajas_cerradas = [c for c in cajas if c.fecha_apertura is None or c.fecha_cierre is not None]
        if not cajas_cerradas:
            MessageBox.warning(self, "Sin cajas disponibles", "No hay ninguna caja disponible para abrir.")
            return

        self.usuario_autenticado = usuario
        self._verificado = True
        self.usuario_input.setEnabled(False)
        self.clave_input.setEnabled(False)
        self.lbl_subtitulo.setText(f"Identificado como {usuario.nombre_usuario}. Elija la caja a abrir.")
        self.caja_combo.clear()
        for caja in cajas_cerradas:
            self.caja_combo.addItem(caja.nombre_caja or f"Caja {caja.id_caja}", caja.id_caja)
        self.card_apertura.show()
        self.btn_principal.setText("Abrir Turno")
        self.btn_principal.setIcon(qta.icon("fa5s.unlock", color="#FFFFFF"))
        # Sin fixed size, el dialogo se dimensiona segun su contenido al mostrarse por
        # primera vez, pero no vuelve a recalcular su alto solo porque una card oculta
        # se hace visible despues -- adjustSize() lo fuerza a crecer para la card de
        # apertura recien revelada.
        self.adjustSize()

    # ── Paso 2: apertura ───────────────────────────────────────────────────

    def _abrir(self) -> None:
        id_caja = self.caja_combo.currentData()
        if id_caja is None:
            MessageBox.warning(self, "Caja requerida", "Seleccione una caja para abrir su turno.")
            return
        try:
            self.caja_abierta = CajaService.abrir_caja(
                self.session,
                id_caja,
                id_usuario=self.usuario_autenticado.id_usuario,
                saldo_apertura=self.saldo_input.get_value(),
            )
        except (ValueError, PermisoDenegadoError) as exc:
            MessageBox.warning(self, "No se pudo abrir la caja", str(exc))
            return
        self.accept()
