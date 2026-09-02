"""Reemplazo con estilo propio de los QMessageBox nativos de Qt/Windows (botones en
inglés, esquinas cuadradas, sin relación visual con el resto del ERP). `MessageBox`
expone los mismos 4 metodos estaticos que `QMessageBox` (`question`/`information`/
`warning`/`critical`) con la misma firma `(parent, titulo, texto)` y, en el caso de
`question`, el mismo tipo de retorno (`QMessageBox.StandardButton.Yes`/`.No`) -- para que
migrar un call site sea un cambio mecanico de `QMessageBox.` a `MessageBox.` (mas el
import) sin tocar la logica que ya compara el resultado, en vez de reescribir cada sitio
a mano. Auditoria de 2026-09-02: 473 call sites en 43 archivos, todos con esta misma
forma de 3 argumentos (o, en 2 casos, 5 argumentos con los mismos botones Si/No que ya
son el default aca) -- ver docs/GUIA_ESTILO_UI.md antes de tocar este archivo, todo el
QSS/iconografia de abajo sigue esas convenciones (paleta de app/ui/styles.py, patron de
dialogo de la seccion 7, botones de la seccion 3).

Un solo caso en toda la app (`app/ui/auditoria_panel.py`) instancia `QMessageBox`
directo en vez de usar los estaticos, para forzar `textFormat=PlainText` en un detalle
que puede traer texto libre del usuario (mitigacion de HTML/link-spoofing) -- ese sitio
sigue usando `QMessageBox` nativo a proposito, no se migra a esta clase."""

import qtawesome as qta
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.styles import (
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_FIELD_BG,
    COLOR_PRIMARY,
    COLOR_PRIMARY_DARK,
    COLOR_PRIMARY_LIGHT,
    COLOR_SUCCESS,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_WARNING,
    FONT_FAMILY,
    aplicar_sombra,
    color_con_alpha,
)

# icono + color semantico por tipo -- "information" en esta app siempre se usa para
# confirmar una operacion ya completada ("Exportación completa", "Cliente creado"), never
# un aviso neutro, asi que usa el icono/color de exito (COLOR_SUCCESS) en vez de
# COLOR_INFO (reservado para "ni exito ni error", sin un caso de uso real en los 473
# call sites auditados).
_CONFIGURACION = {
    "question": {"icono": "fa5s.question-circle", "color": COLOR_PRIMARY},
    "information": {"icono": "fa5s.check-circle", "color": COLOR_SUCCESS},
    "warning": {"icono": "fa5s.exclamation-triangle", "color": COLOR_WARNING},
    "critical": {"icono": "fa5s.times-circle", "color": COLOR_DANGER},
}

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
QLabel#MensajeTexto {{
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
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


class MessageBox(QDialog):
    """Dialogo de mensaje/confirmacion con la identidad visual del ERP -- ver el
    docstring del modulo para la API de migracion. No instanciar directo salvo caso de
    uso nuevo que no encaje en los 4 estaticos; usar `MessageBox.question/information/
    warning/critical(parent, titulo, texto)`."""

    def __init__(self, parent, titulo: str, texto: str, tipo: str, confirmacion: bool = False):
        super().__init__(parent)
        self._aceptado = False
        config = _CONFIGURACION[tipo]

        self.setWindowTitle(titulo)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setModal(True)
        self.setMinimumWidth(380)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(16)

        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(14)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon(config["icono"], color=config["color"]).pixmap(QSize(22, 22)))
        icon_lbl.setStyleSheet(
            f"background-color: {color_con_alpha(config['color'], 26)};"
            f" border: 1.5px solid {color_con_alpha(config['color'], 90)};"
            " border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(38, 38)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_texto = QLabel(texto)
        lbl_texto.setObjectName("MensajeTexto")
        lbl_texto.setWordWrap(True)
        lbl_texto.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        lbl_texto.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        card_layout.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignTop)
        card_layout.addWidget(lbl_texto, 1)
        root.addWidget(card)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(10)
        footer.addStretch()

        if confirmacion:
            btn_cancelar = QPushButton("Cancelar")
            btn_cancelar.setObjectName("BtnSecondary")
            btn_cancelar.setFixedHeight(34)
            btn_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_cancelar.setAutoDefault(False)
            btn_cancelar.clicked.connect(self.reject)
            footer.addWidget(btn_cancelar)

            btn_confirmar = QPushButton("Confirmar")
            btn_confirmar.setObjectName("BtnPrimary")
            btn_confirmar.setFixedHeight(34)
            btn_confirmar.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_confirmar.setAutoDefault(False)
            btn_confirmar.setDefault(True)
            btn_confirmar.clicked.connect(self.accept)
            footer.addWidget(btn_confirmar)
        else:
            btn_aceptar = QPushButton("Aceptar")
            btn_aceptar.setObjectName("BtnPrimary")
            btn_aceptar.setFixedHeight(34)
            btn_aceptar.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_aceptar.setAutoDefault(False)
            btn_aceptar.setDefault(True)
            btn_aceptar.clicked.connect(self.accept)
            footer.addWidget(btn_aceptar)

        root.addLayout(footer)

    def showEvent(self, event) -> None:  # noqa: N802 (override de Qt)
        # Artefacto de primer pintado (Windows/DWM) con tarjetas con sombra -- ver
        # GUIA_ESTILO_UI.md §8.1. Se autocorrige con cualquier repintado.
        super().showEvent(event)
        QTimer.singleShot(0, self.update)

    def accept(self) -> None:  # noqa: N802 (override de Qt)
        self._aceptado = True
        super().accept()

    # ── API de migracion (misma firma y valor de retorno que QMessageBox) ──────────

    @staticmethod
    def question(parent, titulo: str, texto: str) -> QMessageBox.StandardButton:
        dialogo = MessageBox(parent, titulo, texto, tipo="question", confirmacion=True)
        dialogo.exec()
        return QMessageBox.StandardButton.Yes if dialogo._aceptado else QMessageBox.StandardButton.No

    @staticmethod
    def information(parent, titulo: str, texto: str) -> None:
        MessageBox(parent, titulo, texto, tipo="information").exec()

    @staticmethod
    def warning(parent, titulo: str, texto: str) -> None:
        MessageBox(parent, titulo, texto, tipo="warning").exec()

    @staticmethod
    def critical(parent, titulo: str, texto: str) -> None:
        MessageBox(parent, titulo, texto, tipo="critical").exec()
