from decimal import Decimal

import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from app.db.models import Banco, BancoMovimiento, ControlDeTasa, CuentaBancaria
from app.services.moneda_cuentas import MONEDAS_CUENTA, etiqueta_moneda
from app.ui.message_box import MessageBox
from app.ui.numeric_inputs import NumericFieldType, NumericLineEdit
from app.ui.styles import (
    ASTERISCO_REQUERIDO,
    COLOR_BLUE_LIGHT,
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
    COLOR_TEXT_LIGHT,
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
    margin-bottom: 6px;
}}
QLabel.SectionTitle {{
    font-size: 11px;
    font-weight: bold;
    color: {COLOR_PRIMARY};
    letter-spacing: 0.8px;
    padding-bottom: 2px;
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
    background-color: {COLOR_WHITE};
}}
QLineEdit::placeholder {{
    color: {COLOR_TEXT_LIGHT};
    font-size: 12px;
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
QComboBox QAbstractItemView {{
    background-color: {COLOR_WHITE};
    border: 1px solid {COLOR_BORDER};
    selection-background-color: {COLOR_BLUE_LIGHT};
    selection-color: {COLOR_TEXT_DARK};
    padding: 4px;
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


class CuentaBancariaFormDialog(QDialog):
    """Diálogo de creación/edición de cuentas bancarias."""

    def __init__(
        self, session: Session, cuenta: CuentaBancaria | None = None, parent=None, precargado: dict | None = None
    ):
        super().__init__(parent)
        self.session = session
        self.cuenta = cuenta
        # Bancos y (al editar) si la cuenta tiene movimientos, ya consultados por el panel en un hilo aparte
        # ({"bancos": [...], "tiene_movimientos": bool}); sin ellos el dialogo los consulta el mismo.
        self._precargado = precargado
        self.setWindowTitle("Editar Cuenta Bancaria" if cuenta else "Nueva Cuenta Bancaria")
        self.setFixedWidth(800)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()
        self._cargar_bancos()
        self._precargar_tasa_cambio()

        if cuenta:
            self._precargar(cuenta)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # ── Encabezado Corporativo ──
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        icon_lbl = QLabel()
        fa_icon_name = "fa5s.university" if self.cuenta else "fa5s.plus-circle"
        icon_lbl.setPixmap(qta.icon(fa_icon_name, color=COLOR_PRIMARY).pixmap(QSize(22, 22)))
        icon_lbl.setStyleSheet(
            f"background-color: {COLOR_INFO_BG}; border: 1.5px solid "
            f"{COLOR_BLUE_LIGHTER}; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(38, 38)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titles_layout = QVBoxLayout()
        titles_layout.setSpacing(1)
        titles_layout.setContentsMargins(0, 0, 0, 0)

        titulo_text = "Editar Cuenta Bancaria" if self.cuenta else "Nueva Cuenta Bancaria"
        lbl_titulo = QLabel(titulo_text)
        lbl_titulo.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        lbl_subtitulo = QLabel("Complete los datos requeridos para registrar la cuenta bancaria.")
        lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")

        titles_layout.addWidget(lbl_titulo)
        titles_layout.addWidget(lbl_subtitulo)

        header_layout.addWidget(icon_lbl)
        header_layout.addLayout(titles_layout)
        header_layout.addStretch()

        root.addWidget(header_widget)

        # ── Contenido: Tarjeta Única ──
        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(12)

        sec_title = QLabel("DATOS DE LA CUENTA BANCARIA")
        sec_title.setProperty("class", "SectionTitle")
        card_layout.addWidget(sec_title)

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # Banco
        lbl_banco = QLabel(f"Banco {ASTERISCO_REQUERIDO}")
        lbl_banco.setProperty("class", "FormLabel")
        self.banco_combo = QComboBox()
        self.banco_combo.setFixedHeight(36)
        grid.addWidget(lbl_banco, 0, 0, 1, 2)
        grid.addWidget(self.banco_combo, 1, 0, 1, 2)

        # Número de Cuenta
        lbl_num = QLabel(f"Número de Cuenta {ASTERISCO_REQUERIDO}")
        lbl_num.setProperty("class", "FormLabel")
        self.numero_input = QLineEdit()
        self.numero_input.setPlaceholderText("Ej: 0134-0001-123456789")
        self.numero_input.setMaxLength(30)
        self.numero_input.setFixedHeight(36)
        grid.addWidget(lbl_num, 2, 0, 1, 2)
        grid.addWidget(self.numero_input, 3, 0, 1, 2)

        # Tipo de Cuenta
        lbl_tipo = QLabel("Tipo de Cuenta")
        lbl_tipo.setProperty("class", "FormLabel")
        self.tipo_combo = QComboBox()
        self.tipo_combo.addItems(["AHORRO", "CORRIENTE"])
        self.tipo_combo.setFixedHeight(36)
        grid.addWidget(lbl_tipo, 4, 0)
        grid.addWidget(self.tipo_combo, 5, 0)

        # Moneda de la cuenta: decide que pagos puede recibir (Zelle/Binance a USD, pagos en pesos a COP, el resto de
        # los metodos bancarios a VES) y que saldo se muestra (ver _aplicar_moneda_a_los_saldos). Se puede cambiar
        # mientras la cuenta no tenga movimientos.
        self.lbl_moneda = QLabel(f"Moneda de la Cuenta {ASTERISCO_REQUERIDO}")
        self.lbl_moneda.setProperty("class", "FormLabel")
        self.moneda_combo = QComboBox()
        for moneda in MONEDAS_CUENTA:
            self.moneda_combo.addItem(etiqueta_moneda(moneda), moneda)
        self.moneda_combo.setFixedHeight(36)
        grid.addWidget(self.lbl_moneda, 4, 1)
        grid.addWidget(self.moneda_combo, 5, 1)

        # Solo al editar una cuenta con historial (ver _precargar).
        self.lbl_aviso_moneda = QLabel(
            "Esta cuenta ya tiene movimientos: cambiarle la moneda pide confirmación, solo la hace un "
            "administrador y queda en la auditoría. El historial no cambia."
        )
        self.lbl_aviso_moneda.setWordWrap(True)
        self.lbl_aviso_moneda.setStyleSheet("font-size: 11px; font-style: italic; color: #64748B;")
        self.lbl_aviso_moneda.hide()
        grid.addWidget(self.lbl_aviso_moneda, 6, 0, 1, 2)

        # Saldos. Solo se muestra el de la moneda de la cuenta (Bs, USD o COP): los otros se ocultan y quedan en 0.
        self.saldos_widget = QWidget()
        saldos_layout = QHBoxLayout(self.saldos_widget)
        saldos_layout.setContentsMargins(0, 0, 0, 0)
        saldos_layout.setSpacing(16)

        # Saldo Inicial USD -- solo editable al CREAR la cuenta. En edicion se deshabilita
        # (ver _precargar): cambiarlo a mano ahi rompe la trazabilidad, porque no genera
        # ningun BancoMovimiento que explique el ajuste -- BancoMovimientoService.crear()
        # es el unico camino que debe modificar saldo_total_banco despues de la creacion.
        self.saldo_usd_widget = QWidget()
        col_usd = QVBoxLayout(self.saldo_usd_widget)
        col_usd.setContentsMargins(0, 0, 0, 0)
        col_usd.setSpacing(6)
        self.lbl_saldo = QLabel("Saldo Inicial USD")
        self.lbl_saldo.setProperty("class", "FormLabel")
        self.saldo_input = NumericLineEdit(NumericFieldType.AMOUNT, prefix="$ ")
        self.saldo_input.setFixedHeight(36)
        col_usd.addWidget(self.lbl_saldo)
        col_usd.addWidget(self.saldo_input)

        # Saldo Inicial BS -- solo editable al CREAR la cuenta. En edicion se deshabilita
        # por la misma razón que el saldo USD.
        self.saldo_bs_widget = QWidget()
        col_bs = QVBoxLayout(self.saldo_bs_widget)
        col_bs.setContentsMargins(0, 0, 0, 0)
        col_bs.setSpacing(6)
        self.lbl_saldo_bs = QLabel("Saldo Inicial BS")
        self.lbl_saldo_bs.setProperty("class", "FormLabel")
        self.saldo_bs_input = NumericLineEdit(NumericFieldType.AMOUNT, allow_negative=False, decimals=2)
        self.saldo_bs_input.setFixedHeight(36)
        col_bs.addWidget(self.lbl_saldo_bs)
        col_bs.addWidget(self.saldo_bs_input)

        # Saldo Inicial COP (pesos colombianos) -- mismo criterio que los otros dos saldos.
        self.saldo_cop_widget = QWidget()
        col_cop = QVBoxLayout(self.saldo_cop_widget)
        col_cop.setContentsMargins(0, 0, 0, 0)
        col_cop.setSpacing(6)
        self.lbl_saldo_cop = QLabel("Saldo Inicial COP")
        self.lbl_saldo_cop.setProperty("class", "FormLabel")
        self.saldo_cop_input = NumericLineEdit(NumericFieldType.AMOUNT, allow_negative=False, decimals=2)
        self.saldo_cop_input.setFixedHeight(36)
        col_cop.addWidget(self.lbl_saldo_cop)
        col_cop.addWidget(self.saldo_cop_input)

        self.saldo_bs_input.valueChanged.connect(self._calcular_equivalente_usd)

        saldos_layout.addWidget(self.saldo_usd_widget, stretch=1)
        saldos_layout.addWidget(self.saldo_bs_widget, stretch=1)
        saldos_layout.addWidget(self.saldo_cop_widget, stretch=1)
        grid.addWidget(self.saldos_widget, 7, 0, 1, 2)

        # Tasa y equivalente en USD del saldo inicial en bolivares: el equivalente (Bs / tasa) es el saldo
        # en dolares con que nace la cuenta (ver get_data). Se muestra cuando la moneda es VES.
        self.conversion_widget = QWidget()
        conv_layout = QHBoxLayout(self.conversion_widget)
        conv_layout.setContentsMargins(0, 0, 0, 0)
        conv_layout.setSpacing(24)

        self.tasa_widget = QWidget()
        col_tasa = QVBoxLayout(self.tasa_widget)
        col_tasa.setContentsMargins(0, 0, 0, 0)
        col_tasa.setSpacing(6)
        self.lbl_tasa_cambio = QLabel("Tasa de Cambio (Bs/USD)")
        self.lbl_tasa_cambio.setProperty("class", "FormLabel")
        self.tasa_cambio_input = NumericLineEdit(NumericFieldType.RATE)
        self.tasa_cambio_input.setFixedHeight(36)
        self.tasa_cambio_input.valueChanged.connect(self._calcular_equivalente_usd)
        col_tasa.addWidget(self.lbl_tasa_cambio)
        col_tasa.addWidget(self.tasa_cambio_input)

        self.equivalente_widget = QWidget()
        col_equiv = QVBoxLayout(self.equivalente_widget)
        col_equiv.setContentsMargins(0, 0, 0, 0)
        col_equiv.setSpacing(6)
        self.lbl_equivalente = QLabel("Equivalente USD (se guarda como saldo):")
        self.lbl_equivalente.setProperty("class", "FormLabel")
        self.equivalente_usd_input = NumericLineEdit(NumericFieldType.AMOUNT, prefix="$ ")
        self.equivalente_usd_input.setFixedHeight(36)
        self.equivalente_usd_input.setReadOnly(True)
        self.equivalente_usd_input.setStyleSheet("background-color: #F1F5F9;")
        col_equiv.addWidget(self.lbl_equivalente)
        col_equiv.addWidget(self.equivalente_usd_input)

        conv_layout.addWidget(self.tasa_widget, stretch=1)
        conv_layout.addWidget(self.equivalente_widget, stretch=1)
        grid.addWidget(self.conversion_widget, 12, 0, 1, 2)

        self.moneda_combo.currentIndexChanged.connect(self._aplicar_moneda_a_los_saldos)
        self._aplicar_moneda_a_los_saldos()

        # Nombre del Titular
        lbl_nom = QLabel(f"Nombre del Titular {ASTERISCO_REQUERIDO}")
        lbl_nom.setProperty("class", "FormLabel")
        self.nombre_input = QLineEdit()
        self.nombre_input.setPlaceholderText("Ej: Juan Pérez")
        self.nombre_input.setFixedHeight(36)
        grid.addWidget(lbl_nom, 8, 0, 1, 2)
        grid.addWidget(self.nombre_input, 9, 0, 1, 2)

        # Identificación del Titular
        lbl_rif = QLabel(f"Identificación del Titular {ASTERISCO_REQUERIDO}")
        lbl_rif.setProperty("class", "FormLabel")
        self.identificacion_input = QLineEdit()
        self.identificacion_input.setPlaceholderText("Ej: V-12345678")
        self.identificacion_input.setMaxLength(20)
        self.identificacion_input.setFixedHeight(36)
        grid.addWidget(lbl_rif, 10, 0, 1, 2)
        grid.addWidget(self.identificacion_input, 11, 0, 1, 2)

        # Campos de auditoría (solo visibles en edición)
        self.auditoria_widget = QWidget()
        self.auditoria_widget.setVisible(False)
        auditoria_layout = QVBoxLayout(self.auditoria_widget)
        auditoria_layout.setContentsMargins(0, 0, 0, 0)
        auditoria_layout.setSpacing(4)

        lbl_auditoria = QLabel("INFORMACIÓN DE AUDITORÍA")
        lbl_auditoria.setProperty("class", "SectionTitle")
        auditoria_layout.addWidget(lbl_auditoria)

        self.fecha_creacion_label = QLabel()
        self.fecha_creacion_label.setStyleSheet("font-size: 11px; color: #64748B;")
        auditoria_layout.addWidget(self.fecha_creacion_label)

        self.creado_por_label = QLabel()
        self.creado_por_label.setStyleSheet("font-size: 11px; color: #64748B;")
        auditoria_layout.addWidget(self.creado_por_label)

        card_layout.addLayout(grid)
        card_layout.addWidget(self.auditoria_widget)
        card_layout.addStretch()

        root.addWidget(card)

        # ── Footer con Botones de Acción ──
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 4, 0, 0)
        footer_layout.setSpacing(10)

        footer_layout.addStretch()

        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.setIcon(qta.icon("fa5s.times", color="#475569"))
        self.btn_cancelar.setObjectName("BtnSecondary")
        self.btn_cancelar.setFixedHeight(36)
        self.btn_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancelar.clicked.connect(self.reject)

        self.btn_guardar = QPushButton("Guardar Cuenta")
        self.btn_guardar.setIcon(qta.icon("fa5s.save", color="#FFFFFF"))
        self.btn_guardar.setObjectName("BtnPrimary")
        self.btn_guardar.setFixedHeight(36)
        self.btn_guardar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guardar.clicked.connect(self._validar_y_aceptar)

        footer_layout.addWidget(self.btn_cancelar)
        footer_layout.addWidget(self.btn_guardar)

        root.addLayout(footer_layout)

    def _cargar_bancos(self):
        """Carga la lista de bancos activos en el combo."""
        if self._precargado is not None:
            bancos = self._precargado["bancos"]
        else:
            bancos = self.session.query(Banco).filter(Banco.estado_banco == "ACTIVO").order_by(Banco.nombre_banco).all()
        self.banco_combo.clear()
        for banco in bancos:
            self.banco_combo.addItem(f"{banco.nombre_banco} ({banco.codigo_banco})", banco.id_banco)

    def _aplicar_moneda_a_los_saldos(self) -> None:
        """Muestra solo el saldo de la moneda de la cuenta: bolivares, dolares o pesos. Los saldos que se ocultan al
        CREAR la cuenta se limpian para no guardar un monto en la moneda equivocada."""
        moneda = self.moneda_combo.currentData()
        visibles = {
            self.saldo_usd_widget: moneda == "USD",
            self.saldo_bs_widget: moneda == "VES",
            self.saldo_cop_widget: moneda == "COP",
        }
        for widget, mostrar in visibles.items():
            widget.setVisible(mostrar)
        self.conversion_widget.setVisible(moneda == "VES")
        self._calcular_equivalente_usd()
        if self.cuenta is None:
            if moneda != "USD":
                self.saldo_input.set_value(0)
            if moneda != "VES":
                self.saldo_bs_input.set_value(0)
            if moneda != "COP":
                self.saldo_cop_input.set_value(0)

    def _precargar_tasa_cambio(self) -> None:
        """Tasa BCV mas reciente como sugerencia para el calculo del equivalente en USD. Viene precargada
        del panel (se consulta en el hilo aparte, ver _tarea_form_cuenta); sin `precargado` el dialogo la
        consulta el mismo, como el resto de sus datos."""
        if self._precargado is not None:
            tasa = self._precargado.get("tasa")
        else:
            registro = self.session.query(ControlDeTasa).order_by(ControlDeTasa.fecha_tasa.desc()).first()
            tasa = registro.tasa_dolar_bcv if registro is not None else None
        if isinstance(tasa, (int, float, Decimal)) and tasa > 0:
            self.tasa_cambio_input.set_value(tasa)

    def _calcular_equivalente_usd(self) -> None:
        """Saldo inicial en Bs / tasa -> equivalente en USD. En una cuenta VES es el saldo en dolares con
        que nace la cuenta (ver get_data)."""
        saldo_bs = self.saldo_bs_input.get_value()
        tasa = self.tasa_cambio_input.get_value()
        if saldo_bs is None or tasa is None or tasa <= 0:
            self.equivalente_usd_input.set_value(None)
        else:
            self.equivalente_usd_input.set_value(saldo_bs / tasa)
        # set_value() reaplica el estilo base del widget
        self.equivalente_usd_input.setStyleSheet("background-color: #F1F5F9;")

    def _precargar(self, cuenta: CuentaBancaria):
        self.numero_input.setText(cuenta.numero_cuenta or "")
        self.nombre_input.setText(cuenta.nombre_titular or "")
        self.identificacion_input.setText(cuenta.identificacion_titular or "")
        self.saldo_input.set_value(cuenta.saldo_total_banco or 0)
        self.saldo_input.setEnabled(False)
        self.saldo_input.setToolTip("El saldo se actualiza registrando movimientos bancarios, no editando este campo.")
        self.lbl_saldo.setText("Saldo Actual USD (solo lectura)")

        self.saldo_bs_input.set_value(cuenta.saldo_total_banco_bs or 0)
        self.saldo_bs_input.setEnabled(False)
        self.saldo_bs_input.setToolTip(
            "El saldo en BS se actualiza registrando movimientos bancarios, no editando este campo."
        )
        self.lbl_saldo_bs.setText("Saldo Actual BS (solo lectura)")

        self.saldo_cop_input.set_value(cuenta.saldo_total_banco_cop or 0)
        self.saldo_cop_input.setEnabled(False)
        self.saldo_cop_input.setToolTip(
            "El saldo en COP se actualiza registrando movimientos bancarios, no editando este campo."
        )
        self.lbl_saldo_cop.setText("Saldo Actual COP (solo lectura)")

        # Seleccionar banco
        idx_banco = self.banco_combo.findData(cuenta.id_banco)
        if idx_banco >= 0:
            self.banco_combo.setCurrentIndex(idx_banco)

        # Seleccionar tipo de cuenta
        idx_tipo = self.tipo_combo.findText(cuenta.tipo_cuenta_banco or "CORRIENTE")
        if idx_tipo >= 0:
            self.tipo_combo.setCurrentIndex(idx_tipo)

        idx_moneda = self.moneda_combo.findData(cuenta.moneda or "VES")
        if idx_moneda >= 0:
            self.moneda_combo.setCurrentIndex(idx_moneda)
        self._aplicar_moneda_a_los_saldos()
        if self._precargado is not None and "tiene_movimientos" in self._precargado:
            tiene_movimientos = self._precargado["tiene_movimientos"]
        else:
            tiene_movimientos = (
                self.session.query(BancoMovimiento.id_movimiento)
                .filter(BancoMovimiento.id_cuenta == cuenta.id_cuenta)
                .first()
                is not None
            )
        self.tiene_movimientos = tiene_movimientos
        self.lbl_aviso_moneda.setVisible(tiene_movimientos)

        # Mostrar información de auditoría solo en edición
        self.auditoria_widget.setVisible(True)
        if cuenta.fecha_creacion:
            fecha_str = cuenta.fecha_creacion.strftime("%d/%m/%Y %H:%M")
            self.fecha_creacion_label.setText(f"Fecha de creación: {fecha_str}")
        else:
            self.fecha_creacion_label.setText("Fecha de creación: N/A")

        if cuenta.creador:
            nombre_creador = cuenta.creador.nombre or cuenta.creador.nombre_usuario or f"ID {cuenta.creado_por}"
            self.creado_por_label.setText(f"Creado por: {nombre_creador}")
        else:
            self.creado_por_label.setText("Creado por: N/A")

    def _validar_y_aceptar(self):
        if self.banco_combo.currentData() is None:
            MessageBox.warning(self, "Dato requerido", "Debe seleccionar un banco.")
            self.banco_combo.setFocus()
            return
        if not self.numero_input.text().strip():
            MessageBox.warning(self, "Dato requerido", "El número de cuenta es obligatorio.")
            self.numero_input.setFocus()
            return
        if not self.nombre_input.text().strip():
            MessageBox.warning(self, "Dato requerido", "El nombre del titular es obligatorio.")
            self.nombre_input.setFocus()
            return
        if not self.identificacion_input.text().strip():
            MessageBox.warning(self, "Dato requerido", "La identificación del titular es obligatoria.")
            self.identificacion_input.setFocus()
            return
        self.accept()

    def get_data(self) -> dict:
        datos = {
            "id_banco": self.banco_combo.currentData(),
            "numero_cuenta": self.numero_input.text().strip(),
            "tipo_cuenta_banco": self.tipo_combo.currentText(),
            "moneda": self.moneda_combo.currentData(),
            "nombre_titular": self.nombre_input.text().strip(),
            "identificacion_titular": self.identificacion_input.text().strip(),
        }
        # Solo se establece al CREAR -- en edicion el campo esta deshabilitado (ver
        # _precargar) y no debe viajar en el dict de actualizar(), para que
        # CuentaBancariaService.actualizar() nunca reciba un cambio de saldo sin el
        # BancoMovimiento que lo explique.
        if self.cuenta is None:
            datos["saldo_total_banco"] = self.saldo_input.get_value()
            datos["saldo_total_banco_bs"] = self.saldo_bs_input.get_value()
            datos["saldo_total_banco_cop"] = self.saldo_cop_input.get_value()
            # Cuenta en Bs: el saldo en dolares es el equivalente calculado (Bs / tasa), no un campo aparte.
            if self.moneda_combo.currentData() == "VES":
                datos["saldo_total_banco"] = self.equivalente_usd_input.get_value() or self.saldo_input.get_value()
        return datos
