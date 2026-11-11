import datetime
from decimal import Decimal

import qtawesome as qta
from PySide6.QtCore import QDate, QSize, Qt
from PySide6.QtWidgets import (
    QCalendarWidget,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.db.models import Banco, BancoMovimiento, ControlDeTasa, CuentaBancaria, Usuario
from app.services.banco_movimientos import BancoMovimientoService
from app.services.moneda_cuentas import MONEDA_BS, MONEDA_COP, MONEDA_USD
from app.ui.message_box import MessageBox
from app.ui.numeric_inputs import NumericFieldType, NumericLineEdit
from app.ui.pantalla import ajustar_tamano, hacer_desplazable
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_BLUE_LIGHTER,
    COLOR_INFO_BG,
    COLOR_PRIMARY,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MEDIUM,
    TABLE_QSS,
    alinear_encabezados,
    dar_ancho_a_texto,
)

# Columnas de la tabla de movimientos del dia.
COL_MONTO_USD = 2
COL_TASA = 3
COL_MONTO_LOCAL = 4


class ConciliacionBancosDialog(QDialog):
    """Diálogo para conciliación de bancos."""

    def __init__(self, session: Session, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session = session
        self.usuario = usuario
        self._cuentas = []
        self._movimientos_manuales = []
        self._fecha_conciliacion = QDate.currentDate()
        # Moneda de cada cuenta del combo y de la seleccionada: manda sobre que montos se muestran (ver
        # _aplicar_modo_moneda). Sin cuentas se muestra el lado en dolares.
        self._monedas: dict[int, str] = {}
        self._moneda = MONEDA_USD
        # Tasa que el usuario escribio en el resumen, por moneda de la cuenta: cambiar de cuenta no la pisa con la
        # del dia (una tasa en Bs no sirve para una cuenta en pesos, por eso es una por moneda).
        self._tasas_editadas: dict[str, float] = {}

        self.setWindowTitle("Conciliación de Bancos")
        self.setStyleSheet(TABLE_QSS)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        # Tamaño mínimo adaptativo y permitir redimensionamiento
        ajustar_tamano(self, 1200, 800, 1100, 750)

        # Centrar la ventana en la pantalla
        self._centrar_ventana()

        self._build_ui()
        hacer_desplazable(self)
        self._cargar_cuentas()

    def _centrar_ventana(self):
        """Centra la ventana en la pantalla."""
        screen = self.screen()
        if screen:
            screen_geometry = screen.availableGeometry()
            window_geometry = self.frameGeometry()
            center_point = screen_geometry.center()
            window_geometry.moveCenter(center_point)
            self.move(window_geometry.topLeft())

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ── Header ──
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.balance-scale", color=COLOR_PRIMARY).pixmap(24, 24))
        icon_lbl.setStyleSheet(
            f"background-color: {COLOR_INFO_BG}; border: 2px solid "
            f"{COLOR_BLUE_LIGHTER}; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setMinimumSize(38, 38)  # Tamaño mínimo en lugar de fijo
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_titulo = QLabel("Conciliación de Bancos")
        lbl_titulo.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        header_layout.addWidget(icon_lbl)
        header_layout.addWidget(lbl_titulo)
        header_layout.addStretch()

        layout.addWidget(header)

        # ── Selección de fecha y cuenta ──
        selection_layout = QHBoxLayout()
        selection_layout.setSpacing(12)

        # Calendario
        calendar_layout = QVBoxLayout()
        calendar_layout.setSpacing(3)
        lbl_fecha = QLabel("Fecha de Conciliación:")
        lbl_fecha.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(True)
        self.calendar.setSelectedDate(self._fecha_conciliacion)
        self.calendar.selectionChanged.connect(self._on_fecha_cambiada)
        self.calendar.setMinimumSize(220, 180)  # Tamaño mínimo en lugar de fijo
        calendar_layout.addWidget(lbl_fecha)
        calendar_layout.addWidget(self.calendar)

        # Selección de cuenta
        cuenta_layout = QVBoxLayout()
        cuenta_layout.setSpacing(4)
        lbl_cuenta = QLabel("Cuenta Bancaria:")
        lbl_cuenta.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        self.cuenta_combo = QComboBox()
        self.cuenta_combo.setMinimumHeight(32)  # Altura mínima en lugar de fija
        self.cuenta_combo.currentIndexChanged.connect(self._on_cuenta_cambiada)
        cuenta_layout.addWidget(lbl_cuenta)
        cuenta_layout.addWidget(self.cuenta_combo)

        selection_layout.addLayout(calendar_layout)
        selection_layout.addLayout(cuenta_layout)
        selection_layout.addStretch()

        layout.addLayout(selection_layout)

        # ── Resumen de saldos ──
        resumen_card = QWidget()
        resumen_card.setStyleSheet("background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px;")
        resumen_layout = QGridLayout(resumen_card)
        resumen_layout.setContentsMargins(12, 10, 12, 10)
        resumen_layout.setSpacing(10)
        resumen_layout.setColumnStretch(0, 1)  # Columnas flexibles
        resumen_layout.setColumnStretch(1, 1)
        resumen_layout.setColumnStretch(2, 1)

        # Todo el resumen va en la moneda de la cuenta (dolares, o bolivares/pesos): ver _aplicar_modo_moneda.
        self.lbl_saldo_inicial = QLabel("Saldo Inicial: $0.00")
        self.lbl_saldo_inicial.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {COLOR_TEXT_MEDIUM};")
        resumen_layout.addWidget(self.lbl_saldo_inicial, 0, 0)

        self.lbl_total_entradas = QLabel("Total Entradas: $0.00")
        self.lbl_total_entradas.setStyleSheet("font-size: 12px; font-weight: 600; color: #16A34A;")
        resumen_layout.addWidget(self.lbl_total_entradas, 0, 1)

        self.lbl_total_salidas = QLabel("Total Salidas: $0.00")
        self.lbl_total_salidas.setStyleSheet("font-size: 12px; font-weight: 600; color: #DC2626;")
        resumen_layout.addWidget(self.lbl_total_salidas, 0, 2)

        # Saldo final que dice el estado de cuenta del banco. Hay un campo por moneda y solo se muestra el de la
        # moneda de la cuenta.
        saldo_final_layout = QVBoxLayout()
        saldo_final_layout.setSpacing(4)
        estilo_saldo_final = f"font-size: 12px; font-weight: 600; color: {COLOR_TEXT_MEDIUM};"
        self.lbl_saldo_final = QLabel("Saldo Final USD:")
        self.lbl_saldo_final.setStyleSheet(estilo_saldo_final)
        self.saldo_final_input = NumericLineEdit(NumericFieldType.AMOUNT, allow_negative=True, prefix="$ ")
        self.saldo_final_input.setMinimumHeight(32)  # Altura mínima en lugar de fija
        self.saldo_final_input.valueChanged.connect(self._calcular_conciliacion)
        self.lbl_saldo_final_bs = QLabel("Saldo Final BS:")
        self.lbl_saldo_final_bs.setStyleSheet(estilo_saldo_final)
        self.saldo_final_bs_input = NumericLineEdit(NumericFieldType.AMOUNT, allow_negative=True, decimals=2)
        self.saldo_final_bs_input.setMinimumHeight(32)  # Altura mínima en lugar de fija
        self.saldo_final_bs_input.valueChanged.connect(self._calcular_conciliacion)
        self.saldo_final_bs_input.valueChanged.connect(self._actualizar_equivalente_usd)
        self.saldo_final_input.valueChanged.connect(self._actualizar_equivalente_usd)
        for widget in (
            self.lbl_saldo_final,
            self.saldo_final_input,
            self.lbl_saldo_final_bs,
            self.saldo_final_bs_input,
        ):
            saldo_final_layout.addWidget(widget)
        resumen_layout.addLayout(saldo_final_layout, 1, 0)

        self.lbl_diferencia = QLabel("Diferencia: $0.00")
        self.lbl_diferencia.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {COLOR_TEXT_MEDIUM};")
        resumen_layout.addWidget(self.lbl_diferencia, 1, 1)

        # Icono real (qtawesome) en vez de "✓"/"✗" sueltos en el texto -- ver
        # GUIA_ESTILO_UI.md 3.1.
        self.lbl_estado = QWidget()
        estado_layout = QHBoxLayout(self.lbl_estado)
        estado_layout.setContentsMargins(0, 0, 0, 0)
        estado_layout.setSpacing(4)
        self.icon_estado = QLabel()
        self.lbl_estado_texto = QLabel("Estado: Pendiente")
        self.lbl_estado_texto.setStyleSheet("font-size: 12px; font-weight: 600; color: #F59E0B;")
        estado_layout.addWidget(self.icon_estado)
        estado_layout.addWidget(self.lbl_estado_texto)
        estado_layout.addStretch()
        resumen_layout.addWidget(self.lbl_estado, 1, 2)

        # Tasa y equivalente en USD del saldo final del banco: solo para cuentas que no son en dolares
        # (VES/COP). La tasa se puede editar; el equivalente (saldo final / tasa) es solo vista.
        self.tasa_equiv_widget = QWidget()
        tasa_equiv_layout = QHBoxLayout(self.tasa_equiv_widget)
        tasa_equiv_layout.setContentsMargins(0, 0, 0, 0)
        tasa_equiv_layout.setSpacing(10)

        estilo_tasa = f"font-size: 12px; font-weight: 600; color: {COLOR_TEXT_MEDIUM};"
        self.lbl_tasa_conciliacion = QLabel("Tasa (BS/USD):")
        self.lbl_tasa_conciliacion.setStyleSheet(estilo_tasa)
        self.tasa_conciliacion_input = NumericLineEdit(NumericFieldType.RATE)
        self.tasa_conciliacion_input.setMinimumHeight(32)
        self.tasa_conciliacion_input.setMaximumWidth(140)
        self.tasa_conciliacion_input.valueChanged.connect(self._guardar_tasa_editada)
        self.tasa_conciliacion_input.valueChanged.connect(self._actualizar_equivalente_usd)

        self.lbl_equiv_usd = QLabel("Equiv. USD (solo vista):")
        self.lbl_equiv_usd.setStyleSheet(estilo_tasa)
        self.equiv_usd_input = NumericLineEdit(NumericFieldType.AMOUNT, prefix="$ ")
        self.equiv_usd_input.setMinimumHeight(32)
        self.equiv_usd_input.setMaximumWidth(160)
        self.equiv_usd_input.setReadOnly(True)
        self.equiv_usd_input.setStyleSheet("background-color: #F1F5F9;")

        tasa_equiv_layout.addWidget(self.lbl_tasa_conciliacion)
        tasa_equiv_layout.addWidget(self.tasa_conciliacion_input)
        tasa_equiv_layout.addSpacing(16)
        tasa_equiv_layout.addWidget(self.lbl_equiv_usd)
        tasa_equiv_layout.addWidget(self.equiv_usd_input)
        tasa_equiv_layout.addStretch()
        resumen_layout.addWidget(self.tasa_equiv_widget, 2, 0, 1, 3)
        self.tasa_equiv_widget.setVisible(False)

        layout.addWidget(resumen_card)

        # ── Botones para agregar movimientos ──
        botones_layout = QHBoxLayout()
        botones_layout.setSpacing(10)

        btn_agregar_entrada = QPushButton("Agregar Entrada")
        btn_agregar_entrada.setIcon(qta.icon("fa5s.plus", color="#16A34A"))
        btn_agregar_entrada.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_agregar_entrada.setMinimumHeight(32)  # Altura mínima en lugar de fija
        btn_agregar_entrada.clicked.connect(self._on_agregar_entrada)
        botones_layout.addWidget(btn_agregar_entrada)

        btn_agregar_salida = QPushButton("Agregar Salida")
        btn_agregar_salida.setIcon(qta.icon("fa5s.minus", color="#DC2626"))
        btn_agregar_salida.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_agregar_salida.setMinimumHeight(32)  # Altura mínima en lugar de fija
        btn_agregar_salida.clicked.connect(self._on_agregar_salida)
        botones_layout.addWidget(btn_agregar_salida)

        btn_marcar_conciliado = QPushButton("Marcar como Conciliado")
        btn_marcar_conciliado.setIcon(qta.icon("fa5s.check", color="#16A34A"))
        btn_marcar_conciliado.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_marcar_conciliado.setMinimumHeight(32)  # Altura mínima en lugar de fija
        btn_marcar_conciliado.clicked.connect(self._marcar_conciliado)
        botones_layout.addWidget(btn_marcar_conciliado)

        btn_calcular = QPushButton("Calcular Conciliación")
        btn_calcular.setIcon(qta.icon("fa5s.calculator", color=COLOR_PRIMARY))
        btn_calcular.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_calcular.setMinimumHeight(32)  # Altura mínima en lugar de fija
        btn_calcular.clicked.connect(self._calcular_conciliacion)
        botones_layout.addWidget(btn_calcular)

        btn_guardar = QPushButton("Guardar Movimientos")
        btn_guardar.setIcon(qta.icon("fa5s.save", color="#16A34A"))
        btn_guardar.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_guardar.setMinimumHeight(32)  # Altura mínima en lugar de fija
        btn_guardar.clicked.connect(self._guardar_movimientos)
        botones_layout.addWidget(btn_guardar)

        botones_layout.addStretch()

        layout.addLayout(botones_layout)

        # ── Tabla de movimientos del día ──
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)  # solo lectura
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            [
                "Fecha",
                "Tipo",
                "Monto",
                "Tasa",
                "Monto BS",
                "Origen",
                "Referencia",
                "Descripción",
            ]
        )
        self.table.setMinimumHeight(280)  # Altura mínima aumentada
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        dar_ancho_a_texto(self.table)
        # Usar tamaños mínimos y permitir estiramiento en lugar de anchos fijos
        self.table.horizontalHeader().setMinimumSectionSize(60)
        self.table.setColumnWidth(0, 100)
        self.table.setColumnWidth(1, 60)
        self.table.setColumnWidth(2, 80)
        self.table.setColumnWidth(3, 60)
        self.table.setColumnWidth(4, 80)
        self.table.setColumnWidth(5, 70)
        self.table.setColumnWidth(6, 90)
        alinear_encabezados(
            self.table,
            {
                0: Qt.AlignmentFlag.AlignLeft,
                1: Qt.AlignmentFlag.AlignLeft,
                2: Qt.AlignmentFlag.AlignRight,
                3: Qt.AlignmentFlag.AlignRight,
                4: Qt.AlignmentFlag.AlignRight,
                5: Qt.AlignmentFlag.AlignLeft,
                6: Qt.AlignmentFlag.AlignLeft,
                7: Qt.AlignmentFlag.AlignLeft,
            },
        )
        layout.addWidget(self.table, stretch=1)  # Tabla ocupa espacio disponible

        # ── Footer ──
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 5, 0, 0)
        footer_layout.setSpacing(10)

        footer_layout.addStretch()

        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setIcon(qta.icon("fa5s.times", color=COLOR_TEXT_DARK))
        btn_cerrar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_cerrar.setMinimumHeight(32)  # Altura mínima en lugar de fija
        btn_cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cerrar.clicked.connect(self.accept)
        footer_layout.addWidget(btn_cerrar)

        layout.addLayout(footer_layout)

    def _cargar_cuentas(self):
        """Carga la lista de cuentas bancarias activas."""
        cuentas = (
            self.session.query(CuentaBancaria)
            .join(Banco)
            .filter(CuentaBancaria.estado_cuenta == "ACTIVO", Banco.estado_banco == "ACTIVO")
            .order_by(Banco.nombre_banco, CuentaBancaria.numero_cuenta)
            .all()
        )
        self._monedas = {c.id_cuenta: (c.moneda or MONEDA_BS) for c in cuentas}
        self.cuenta_combo.blockSignals(True)
        self.cuenta_combo.clear()
        for cuenta in cuentas:
            banco_nombre = cuenta.banco.nombre_banco if cuenta.banco else "N/A"
            self.cuenta_combo.addItem(f"{banco_nombre} - {cuenta.numero_cuenta}", cuenta.id_cuenta)
        self.cuenta_combo.blockSignals(False)
        self._aplicar_modo_moneda()
        self._calcular_conciliacion()

    @property
    def _es_usd(self) -> bool:
        return self._moneda == MONEDA_USD

    @property
    def _etiqueta_local(self) -> str:
        """Como se llama la moneda local de la cuenta en pantalla: BS, o COP para una cuenta en pesos."""
        return "COP" if self._moneda == MONEDA_COP else "BS"

    def _formato_monto(self, monto: float) -> str:
        return f"${monto:,.2f}" if self._es_usd else f"{self._etiqueta_local} {monto:,.2f}"

    def _aplicar_modo_moneda(self) -> None:
        """Una cuenta en USD solo muestra dolares; una en bolivares (o pesos), solo su moneda: ni saldos, ni tasa, ni
        columnas de la otra moneda."""
        self._moneda = self._monedas.get(self.cuenta_combo.currentData(), MONEDA_USD)
        es_usd = self._es_usd
        etiqueta = self._etiqueta_local
        self.lbl_saldo_final.setVisible(es_usd)
        self.saldo_final_input.setVisible(es_usd)
        self.lbl_saldo_final_bs.setVisible(not es_usd)
        self.saldo_final_bs_input.setVisible(not es_usd)
        self.lbl_saldo_final_bs.setText(f"Saldo Final {etiqueta}:")
        # Columnas de la tabla: Monto $ siempre visible (en cuentas que no son USD es el equivalente
        # calculado Monto BS / Tasa de cada fila); Tasa y Monto en la moneda local solo en las demas.
        self.table.setColumnHidden(COL_MONTO_USD, False)
        self.table.setColumnHidden(COL_TASA, es_usd)
        self.table.setColumnHidden(COL_MONTO_LOCAL, es_usd)
        encabezado = self.table.horizontalHeaderItem(COL_MONTO_LOCAL)
        if encabezado is not None:
            encabezado.setText(f"Monto {etiqueta}")
        encabezado_usd = self.table.horizontalHeaderItem(COL_MONTO_USD)
        if encabezado_usd is not None:
            encabezado_usd.setText("Monto" if es_usd else "Monto $")
        # Con las columnas de monto visibles hay espacio para que el encabezado y la cifra entren completos.
        self.table.setColumnWidth(COL_MONTO_USD, 110)
        self.table.setColumnWidth(COL_TASA, 80)
        self.table.setColumnWidth(COL_MONTO_LOCAL, 130)
        # Tasa y equivalente en USD: solo cuando la cuenta no es en dolares.
        self.tasa_equiv_widget.setVisible(not es_usd)
        if not es_usd:
            self.lbl_tasa_conciliacion.setText(f"Tasa ({etiqueta}/USD):")
            self._precargar_tasa_conciliacion()
        self._actualizar_equivalente_usd()

    def _precargar_tasa_conciliacion(self) -> None:
        """Tasa para el equivalente en USD: la que el usuario escribio para esta moneda si la hay; si no, la del dia
        (BCV o COP segun la moneda de la cuenta)."""
        tasa = self._tasas_editadas.get(self._moneda) or self._tasa_sugerida()
        if tasa > 0:
            self.tasa_conciliacion_input.set_value(tasa)

    def _guardar_tasa_editada(self) -> None:
        """El usuario cambio la tasa a mano: se recuerda para esta moneda (ver `_tasas_editadas`)."""
        valor = self.tasa_conciliacion_input.get_value()
        if valor is not None and valor > 0:
            self._tasas_editadas[self._moneda] = float(valor)

    def _actualizar_equivalente_usd(self) -> None:
        """Saldo final del banco (en la moneda de la cuenta) / tasa -> equivalente en USD. Solo vista."""
        tasa = self.tasa_conciliacion_input.get_value()
        saldo = Decimal(str(self._saldo_final_manual()))
        if tasa is None or tasa <= 0 or saldo == 0:
            self.equiv_usd_input.set_value(None)
        else:
            self.equiv_usd_input.set_value(saldo / tasa)
        # set_value() reaplica el estilo base del widget
        self.equiv_usd_input.setStyleSheet("background-color: #F1F5F9;")

    def _on_fecha_cambiada(self):
        """Maneja el cambio de fecha."""
        self._fecha_conciliacion = self.calendar.selectedDate()
        self._calcular_conciliacion()

    def _on_cuenta_cambiada(self, index: int):
        """Maneja el cambio de cuenta: los movimientos manuales sin guardar eran de la otra cuenta y de otra moneda."""
        self._movimientos_manuales.clear()
        self._aplicar_modo_moneda()
        self._calcular_conciliacion()

    def _saldo_final_manual(self) -> float:
        """Saldo final que dice el estado de cuenta del banco, en la moneda de la cuenta."""
        campo = self.saldo_final_input if self._es_usd else self.saldo_final_bs_input
        valor = campo.get_value()
        return float(valor) if valor is not None else 0.0

    def _tasa_sugerida(self) -> float:
        """Tasa del dia para precargar el movimiento manual de una cuenta en bolivares (o en pesos)."""
        registro = self.session.query(ControlDeTasa).order_by(ControlDeTasa.fecha_tasa.desc()).first()
        if registro is None:
            return 0.0
        tasa = registro.tasa_cop if self._moneda == MONEDA_COP else registro.tasa_dolar_bcv
        return float(tasa) if tasa else 0.0

    def _columna_monto(self):
        """Columna de `banco_movimientos` con el monto en la moneda de la cuenta."""
        return BancoMovimiento.monto_movimiento if self._es_usd else BancoMovimiento.monto_bolivares

    def _suma_por_tipo(self, id_cuenta: int, desde, hasta) -> tuple[float, float]:
        """(entradas, salidas) de la cuenta entre dos fechas, en la moneda de la cuenta, sumadas en la base."""
        monto = func.coalesce(self._columna_monto(), 0)
        filtros = [BancoMovimiento.id_cuenta == id_cuenta, BancoMovimiento.fecha_movimiento <= hasta]
        if desde is not None:
            filtros.append(BancoMovimiento.fecha_movimiento >= desde)
        entradas, salidas = (
            self.session.query(
                func.coalesce(func.sum(case((BancoMovimiento.tipo_movimiento == "abono", monto), else_=0)), 0),
                func.coalesce(func.sum(case((BancoMovimiento.tipo_movimiento == "cargo", monto), else_=0)), 0),
            )
            .filter(*filtros)
            .one()
        )
        return float(entradas), float(salidas)

    def _totales_conciliacion(self, id_cuenta: int, fecha) -> dict:
        """Saldo inicial (al cierre del dia anterior), entradas y salidas del dia, y el saldo calculado, todo en la
        moneda de la cuenta. Incluye los movimientos manuales aun sin guardar."""
        inicio = datetime.datetime.combine(fecha, datetime.time.min)
        fin = datetime.datetime.combine(fecha, datetime.time.max)
        fin_anterior = datetime.datetime.combine(fecha - datetime.timedelta(days=1), datetime.time.max)
        previas, previas_salidas = self._suma_por_tipo(id_cuenta, None, fin_anterior)
        entradas, salidas = self._suma_por_tipo(id_cuenta, inicio, fin)
        clave_manual = "monto" if self._es_usd else "monto_bs"
        for mov in self._movimientos_manuales:
            if mov["tipo"] == "abono":
                entradas += mov.get(clave_manual, 0.0)
            else:
                salidas += mov.get(clave_manual, 0.0)
        saldo_inicial = previas - previas_salidas
        return {
            "saldo_inicial": saldo_inicial,
            "entradas": entradas,
            "salidas": salidas,
            "saldo_calculado": saldo_inicial + entradas - salidas,
        }

    def _on_agregar_entrada(self):
        """Abre diálogo para agregar una entrada manual."""
        self._agregar_movimiento_manual("abono")

    def _on_agregar_salida(self):
        """Abre diálogo para agregar una salida manual."""
        self._agregar_movimiento_manual("cargo")

    def _agregar_movimiento_manual(self, tipo: str):
        """Agrega un movimiento manual."""
        id_cuenta = self.cuenta_combo.currentData()
        if id_cuenta is None:
            MessageBox.warning(self, "Selección requerida", "Seleccione una cuenta bancaria.")
            return

        # Una cuenta en USD registra el monto en dolares y nada mas; una en bolivares (o pesos) registra el monto en
        # su moneda con la tasa del dia (precargada), de donde sale el equivalente en dolares que lleva el saldo.
        # La tasa precargada es la del campo Tasa del resumen si el usuario la escribio; si no, la del dia.
        if self._es_usd:
            tasa_actual = 0.0
        else:
            tasa_resumen = self.tasa_conciliacion_input.get_value()
            tasa_actual = float(tasa_resumen) if tasa_resumen else self._tasa_sugerida()
        dialog = MovimientoManualDialog(tipo, parent=self, tasa_inicial=tasa_actual, moneda=self._moneda)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            datos = dialog.get_data()
            movimiento = {
                "tipo": tipo,
                "monto": datos["monto"],
                "monto_bs": datos["monto_bs"],
                "tasa": datos["tasa"],
                "referencia": datos["referencia"],
                "descripcion": datos["descripcion"],
                "id_cuenta": id_cuenta,
            }
            self._movimientos_manuales.append(movimiento)
            self._actualizar_tabla_manuales()
            self._calcular_conciliacion()

    def _actualizar_tabla_manuales(self):
        """Actualiza la tabla de movimientos manuales."""
        # Esta tabla ahora muestra todos los movimientos del día
        self.table.setRowCount(0)

        # Cargar movimientos del día de la base de datos
        id_cuenta = self.cuenta_combo.currentData()
        if id_cuenta is None:
            return

        fecha = self._fecha_conciliacion.toPython()
        fecha_inicio = datetime.datetime.combine(fecha, datetime.time.min)
        fecha_fin = datetime.datetime.combine(fecha, datetime.time.max)

        movimientos_db = (
            self.session.query(BancoMovimiento)
            .filter(
                BancoMovimiento.id_cuenta == id_cuenta,
                BancoMovimiento.fecha_movimiento >= fecha_inicio,
                BancoMovimiento.fecha_movimiento <= fecha_fin,
            )
            .order_by(BancoMovimiento.fecha_movimiento.asc())
            .all()
        )

        # Combinar movimientos de DB con movimientos manuales
        todos_movimientos = []
        for mov in movimientos_db:
            origen = "Otro"
            if mov.id_pago_cobro or mov.id_pago_cobro_bcv:
                origen = "Cliente"
            elif mov.id_pago_proveedor:
                origen = "Proveedor"
            elif mov.id_pago_comision:
                origen = "Comisión"

            # Calcular monto en bolívares si existe tasa
            monto_bs = 0.0
            tasa = 0.0
            if mov.monto_bolivares:
                monto_bs = float(mov.monto_bolivares)
            elif mov.monto_movimiento and mov.tasa_cambio and mov.tasa_cambio > 0:
                monto_bs = float(mov.monto_movimiento) * float(mov.tasa_cambio)

            if mov.tasa_cambio:
                tasa = float(mov.tasa_cambio)

            todos_movimientos.append(
                {
                    "tipo": mov.tipo_movimiento,
                    "monto": (float(mov.monto_movimiento) if mov.monto_movimiento else 0.0),
                    "tasa": tasa,
                    "monto_bs": monto_bs,
                    "origen": origen,
                    "referencia": mov.referencia_movimiento or "N/A",
                    "descripcion": mov.descripcion_movimiento or "N/A",
                    "fecha": mov.fecha_movimiento,
                    "es_manual": False,
                }
            )

        for mov in self._movimientos_manuales:
            # Para movimientos manuales, usar el monto_bs proporcionado
            monto = mov["monto"]
            monto_bs = mov.get("monto_bs", 0.0)
            tasa = mov.get("tasa", 0.0)

            # Si no se proporcionó monto_bs, calcularlo como monto * tasa
            if monto_bs == 0.0 and tasa > 0:
                monto_bs = monto * tasa

            todos_movimientos.append(
                {
                    "tipo": mov["tipo"],
                    "monto": monto,
                    "tasa": tasa,
                    "monto_bs": monto_bs,
                    "origen": "Manual",
                    "referencia": mov["referencia"],
                    "descripcion": mov["descripcion"],
                    "fecha": None,
                    "es_manual": True,
                }
            )

        # Mostrar en tabla
        for row, movimiento in enumerate(todos_movimientos):
            self.table.insertRow(row)

            # Fecha
            fecha_str = movimiento["fecha"].strftime("%d/%m/%Y %H:%M") if movimiento["fecha"] else "Pendiente"
            self.table.setItem(row, 0, QTableWidgetItem(fecha_str))

            # Tipo
            tipo_item = QTableWidgetItem(movimiento["tipo"] or "N/A")
            if movimiento["tipo"] == "abono":
                tipo_item.setForeground(Qt.GlobalColor.darkGreen)
            elif movimiento["tipo"] == "cargo":
                tipo_item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, 1, tipo_item)

            # Monto $: en una cuenta USD es el monto directo; en las demas es el equivalente calculado de
            # la fila (Monto BS / Tasa), solo lectura.
            if self._es_usd:
                monto_usd = movimiento["monto"]
            elif movimiento["tasa"] and movimiento["tasa"] > 0 and movimiento["monto_bs"]:
                monto_usd = movimiento["monto_bs"] / movimiento["tasa"]
            else:
                monto_usd = movimiento["monto"]
            item_monto = QTableWidgetItem(f"${monto_usd:,.2f}")
            item_monto.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, COL_MONTO_USD, item_monto)

            # Tasa
            tasa_texto = (
                f"{movimiento['tasa']:,.2f}" if movimiento["tasa"] is not None and movimiento["tasa"] > 0 else "N/A"
            )
            item_tasa = QTableWidgetItem(tasa_texto)
            item_tasa.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, COL_TASA, item_tasa)

            # Monto BS
            item_monto_bs = QTableWidgetItem(f"{movimiento['monto_bs']:,.2f}" if movimiento["monto_bs"] > 0 else "0.00")
            item_monto_bs.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, COL_MONTO_LOCAL, item_monto_bs)

            # Origen
            self.table.setItem(row, 5, QTableWidgetItem(movimiento["origen"]))

            # Referencia
            self.table.setItem(row, 6, QTableWidgetItem(movimiento["referencia"]))

            # Descripción
            self.table.setItem(row, 7, QTableWidgetItem(movimiento["descripcion"]))

    def _eliminar_movimiento_manual(self, index: int):
        """Elimina un movimiento manual."""
        if 0 <= index < len(self._movimientos_manuales):
            del self._movimientos_manuales[index]
            self._actualizar_tabla_manuales()
            self._calcular_conciliacion()

    def _marcar_conciliado(self):
        """Marca el día como conciliado si la diferencia (en la moneda de la cuenta) es 0."""
        id_cuenta = self.cuenta_combo.currentData()
        if id_cuenta is None:
            MessageBox.warning(self, "Selección requerida", "Seleccione una cuenta bancaria.")
            return

        fecha = self._fecha_conciliacion.toPython()
        totales = self._totales_conciliacion(id_cuenta, fecha)
        saldo_final = self._saldo_final_manual()
        diferencia = totales["saldo_calculado"] - saldo_final
        moneda = "USD" if self._es_usd else self._etiqueta_local

        if abs(diferencia) > 0.01:
            MessageBox.warning(
                self,
                "No se puede conciliar",
                f"La conciliación presenta una diferencia de {diferencia:,.2f} {moneda}. "
                f"Solo se puede marcar como conciliado cuando la diferencia en {moneda} sea 0.",
            )
            return

        # Aquí se podría guardar en una tabla de conciliaciones si existe
        # Por ahora, mostramos un mensaje de éxito
        MessageBox.information(
            self,
            "Conciliación Exitosa",
            f"El día {fecha.strftime('%d/%m/%Y')} ha sido marcado como conciliado.\n"
            f"Saldo Final {moneda}: {saldo_final:,.2f}",
        )

    def _guardar_movimientos(self):
        """Guarda los movimientos manuales en la base de datos."""
        if not self._movimientos_manuales:
            MessageBox.information(self, "Sin movimientos", "No hay movimientos manuales para guardar.")
            return

        id_cuenta = self.cuenta_combo.currentData()
        if id_cuenta is None:
            MessageBox.warning(self, "Selección requerida", "Seleccione una cuenta bancaria.")
            return

        fecha = self._fecha_conciliacion.toPython()
        fecha_movimiento = datetime.datetime.combine(fecha, datetime.datetime.now().time())
        tasa_registro = None
        if not self._es_usd:
            tasa_registro = self.session.query(ControlDeTasa).order_by(ControlDeTasa.fecha_tasa.desc()).first()

        try:
            for movimiento in self._movimientos_manuales:
                # Cuenta en USD: solo el monto en dolares. Las demas: el monto en su moneda y la tasa con que se
                # calculo el equivalente en dolares.
                monto_bs = None if self._es_usd else movimiento.get("monto_bs", 0.0)
                tasa_mov = None if self._es_usd else movimiento.get("tasa", 0.0)

                creado = BancoMovimientoService.crear(
                    self.session,
                    id_cuenta=id_cuenta,
                    tipo_movimiento=movimiento["tipo"],
                    monto=movimiento["monto"],
                    referencia=movimiento["referencia"],
                    descripcion=movimiento["descripcion"],
                    id_usuario=self.usuario.id_usuario,
                    monto_bolivares=monto_bs,
                    tasa_cambio=tasa_mov,
                )
                # Actualizar la fecha del movimiento a la fecha de conciliación
                creado.fecha_movimiento = fecha_movimiento
                if tasa_registro is not None:
                    creado.id_tasa = tasa_registro.id_tasa
                self.session.commit()

            self._movimientos_manuales.clear()
            self._actualizar_tabla_manuales()
            self._calcular_conciliacion()
            MessageBox.information(
                self,
                "Movimientos Guardados",
                "Los movimientos manuales han sido guardados exitosamente.",
            )
        except Exception as e:
            self.session.rollback()
            MessageBox.critical(self, "Error", f"Error al guardar movimientos: {str(e)}")

    def _calcular_conciliacion(self):
        """Calcula la conciliación bancaria en la moneda de la cuenta."""
        id_cuenta = self.cuenta_combo.currentData()
        if id_cuenta is None:
            return

        totales = self._totales_conciliacion(id_cuenta, self._fecha_conciliacion.toPython())
        diferencia = totales["saldo_calculado"] - self._saldo_final_manual()

        # Un solo juego de etiquetas, en la moneda de la cuenta: (Saldo Inicial + Entradas - Salidas) - Saldo Final
        # que dice el banco = Diferencia.
        self.lbl_saldo_inicial.setText(f"Saldo Inicial: {self._formato_monto(totales['saldo_inicial'])}")
        self.lbl_total_entradas.setText(f"Total Entradas: {self._formato_monto(totales['entradas'])}")
        self.lbl_total_salidas.setText(f"Total Salidas: {self._formato_monto(totales['salidas'])}")
        self.lbl_diferencia.setText(f"Diferencia: {self._formato_monto(diferencia)}")

        # Está cuadrado si la diferencia es 0
        if abs(diferencia) < 0.01:
            self.icon_estado.setPixmap(qta.icon("fa5s.check-circle", color="#16A34A").pixmap(QSize(14, 14)))
            self.lbl_estado_texto.setText("Estado: Cuadrado")
            self.lbl_estado_texto.setStyleSheet("font-size: 12px; font-weight: 600; color: #16A34A;")
        else:
            self.icon_estado.setPixmap(qta.icon("fa5s.times-circle", color="#DC2626").pixmap(QSize(14, 14)))
            self.lbl_estado_texto.setText("Estado: Desbalanceado")
            self.lbl_estado_texto.setStyleSheet("font-size: 12px; font-weight: 600; color: #DC2626;")

        # Actualizar tabla de movimientos
        self._actualizar_tabla_manuales()


class MovimientoManualDialog(QDialog):
    """Diálogo para agregar un movimiento manual a una cuenta.

    Cuenta en USD (`moneda="USD"`): solo el monto en dolares. Cuenta en bolivares o pesos: el monto en esa moneda y la
    tasa (el equivalente en dolares que lleva el saldo se calcula, sin mostrarse)."""

    def __init__(self, tipo: str, parent=None, tasa_inicial: float = 0.0, moneda: str = MONEDA_BS):
        super().__init__(parent)
        self.tipo = tipo
        self.tasa_inicial = tasa_inicial
        self.moneda = moneda
        self._en_usd = moneda == MONEDA_USD
        self._etiqueta = "COP" if moneda == MONEDA_COP else "BS"
        self.setWindowTitle(f"Agregar {'Entrada' if tipo == 'abono' else 'Salida'} Manual")
        self.setMinimumSize(450, 400)  # Tamaño mínimo en lugar de fijo
        self.resize(500, 450)  # Tamaño inicial mayor
        self.setStyleSheet(TABLE_QSS)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()

        # Pre-llenar la tasa si se proporcionó
        if self.tasa_inicial > 0:
            self.tasa_input.set_value(self.tasa_inicial)
            self._calcular_monto()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Título
        titulo = QLabel(f"Agregar {'Entrada' if self.tipo == 'abono' else 'Salida'} Manual")
        titulo.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        layout.addWidget(titulo)

        # Formulario
        form_layout = QGridLayout()
        form_layout.setSpacing(12)
        form_layout.setColumnStretch(0, 1)  # Columnas flexibles
        form_layout.setColumnStretch(1, 2)

        lbl_monto_bs = QLabel(f"Monto {self._etiqueta}:")
        lbl_monto_bs.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        self.monto_bs_input = NumericLineEdit(NumericFieldType.AMOUNT, decimals=2)
        self.monto_bs_input.setMinimumHeight(36)  # Altura mínima en lugar de fija
        self.monto_bs_input.valueChanged.connect(self._calcular_monto)
        form_layout.addWidget(lbl_monto_bs, 0, 0)
        form_layout.addWidget(self.monto_bs_input, 0, 1)

        lbl_tasa = QLabel("Tasa de Cambio:")
        lbl_tasa.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        self.tasa_input = NumericLineEdit(NumericFieldType.AMOUNT, decimals=2)
        self.tasa_input.setMinimumHeight(36)  # Altura mínima en lugar de fija
        self.tasa_input.valueChanged.connect(self._calcular_monto)
        form_layout.addWidget(lbl_tasa, 1, 0)
        form_layout.addWidget(self.tasa_input, 1, 1)

        # Monto en dolares: lo escribe el usuario en una cuenta USD; en las demas se calcula (monto / tasa) y no se
        # muestra.
        lbl_monto = QLabel("Monto USD:" if self._en_usd else "Monto USD (Calc):")
        lbl_monto.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_MEDIUM};")
        self.monto_input = NumericLineEdit(NumericFieldType.AMOUNT, prefix="$ ")
        self.monto_input.setMinimumHeight(36)  # Altura mínima en lugar de fija
        self.monto_input.setEnabled(self._en_usd)
        form_layout.addWidget(lbl_monto, 2, 0)
        form_layout.addWidget(self.monto_input, 2, 1)
        # Cuenta en USD: no hay monto en otra moneda ni tasa. Las demas: no se muestra el equivalente en dolares.
        for widget in (lbl_monto_bs, self.monto_bs_input, lbl_tasa, self.tasa_input):
            widget.setVisible(not self._en_usd)
        for widget in (lbl_monto, self.monto_input):
            widget.setVisible(self._en_usd)

        lbl_referencia = QLabel("Referencia:")
        lbl_referencia.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        self.referencia_input = QLineEdit()
        self.referencia_input.setPlaceholderText("Ej: Cheque #12345")
        self.referencia_input.setMinimumHeight(36)  # Altura mínima en lugar de fija
        self.referencia_input.setMaxLength(100)  # columna referencia_bancaria VARCHAR(100)
        form_layout.addWidget(lbl_referencia, 3, 0)
        form_layout.addWidget(self.referencia_input, 3, 1)

        lbl_descripcion = QLabel("Descripción:")
        lbl_descripcion.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        self.descripcion_input = QLineEdit()
        self.descripcion_input.setPlaceholderText("Ej: Pago de servicios")
        self.descripcion_input.setMinimumHeight(36)  # Altura mínima en lugar de fija
        form_layout.addWidget(lbl_descripcion, 4, 0)
        form_layout.addWidget(self.descripcion_input, 4, 1)

        layout.addLayout(form_layout)
        layout.addStretch()

        # Botones
        botones_layout = QHBoxLayout()
        botones_layout.setSpacing(12)

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_cancelar.setMinimumHeight(32)  # Altura mínima en lugar de fija
        btn_cancelar.clicked.connect(self.reject)
        botones_layout.addWidget(btn_cancelar)

        btn_aceptar = QPushButton("Aceptar")
        btn_aceptar.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_aceptar.setMinimumHeight(32)  # Altura mínima en lugar de fija
        btn_aceptar.clicked.connect(self._validar_y_aceptar)
        botones_layout.addWidget(btn_aceptar)

        layout.addLayout(botones_layout)

    def _calcular_monto(self):
        """Calcula el monto en USD basado en el monto BS y la tasa (no aplica a una cuenta en USD)."""
        if self._en_usd:
            return
        monto_bs = self.monto_bs_input.get_value()
        tasa = self.tasa_input.get_value()

        if monto_bs is not None and tasa is not None and monto_bs > 0 and tasa > 0:
            monto = monto_bs / tasa
            self.monto_input.set_value(monto)
        else:
            self.monto_input.set_value(0)

    def _validar_y_aceptar(self):
        if self._en_usd:
            monto = self.monto_input.get_value()
            if monto is None or monto <= 0:
                MessageBox.warning(self, "Dato requerido", "El monto USD debe ser mayor a 0.")
                return
        else:
            monto_bs = self.monto_bs_input.get_value()
            tasa = self.tasa_input.get_value()
            if monto_bs is None or monto_bs <= 0:
                MessageBox.warning(self, "Dato requerido", f"El monto {self._etiqueta} debe ser mayor a 0.")
                return
            if tasa is None or tasa <= 0:
                MessageBox.warning(self, "Dato requerido", "La tasa de cambio debe ser mayor a 0.")
                return
        if not self.referencia_input.text().strip():
            MessageBox.warning(self, "Dato requerido", "La referencia es obligatoria.")
            return
        self.accept()

    def get_data(self) -> dict:
        monto_bs = self.monto_bs_input.get_value()
        tasa = self.tasa_input.get_value()
        monto = self.monto_input.get_value()
        return {
            "monto": float(monto) if monto is not None else 0.0,
            # Cuenta en USD: no hay monto en otra moneda ni tasa.
            "monto_bs": 0.0 if self._en_usd else (float(monto_bs) if monto_bs is not None else 0.0),
            "tasa": 0.0 if self._en_usd else (float(tasa) if tasa is not None else 0.0),
            "referencia": self.referencia_input.text().strip(),
            "descripcion": self.descripcion_input.text().strip(),
        }
