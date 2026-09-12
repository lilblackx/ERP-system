import datetime

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
from sqlalchemy.orm import Session

from app.db.models import Banco, BancoMovimiento, ControlDeTasa, CuentaBancaria, Usuario
from app.services.banco_movimientos import BancoMovimientoService
from app.ui.message_box import MessageBox
from app.ui.numeric_inputs import NumericFieldType, NumericLineEdit
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
)


class ConciliacionBancosDialog(QDialog):
    """Diálogo para conciliación de bancos."""

    def __init__(self, session: Session, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session = session
        self.usuario = usuario
        self._cuentas = []
        self._movimientos_manuales = []
        self._fecha_conciliacion = QDate.currentDate()

        self.setWindowTitle("Conciliación de Bancos")
        self.setStyleSheet(TABLE_QSS)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        # Aumentar el tamaño para asegurar que todos los campos sean visibles
        self.resize(1050, 700)

        # Centrar la ventana en la pantalla
        self._centrar_ventana()

        self._build_ui()
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
        icon_lbl.setFixedSize(38, 38)
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
        self.calendar.setFixedSize(200, 160)
        calendar_layout.addWidget(lbl_fecha)
        calendar_layout.addWidget(self.calendar)

        # Selección de cuenta
        cuenta_layout = QVBoxLayout()
        cuenta_layout.setSpacing(4)
        lbl_cuenta = QLabel("Cuenta Bancaria:")
        lbl_cuenta.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        self.cuenta_combo = QComboBox()
        self.cuenta_combo.setFixedHeight(32)
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

        self.lbl_saldo_inicial = QLabel("Saldo Inicial: $0.00")
        self.lbl_saldo_inicial.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {COLOR_TEXT_MEDIUM};")
        resumen_layout.addWidget(self.lbl_saldo_inicial, 0, 0)

        self.lbl_total_entradas = QLabel("Total Entradas: $0.00")
        self.lbl_total_entradas.setStyleSheet("font-size: 12px; font-weight: 600; color: #16A34A;")
        resumen_layout.addWidget(self.lbl_total_entradas, 0, 1)

        self.lbl_total_salidas = QLabel("Total Salidas: $0.00")
        self.lbl_total_salidas.setStyleSheet("font-size: 12px; font-weight: 600; color: #DC2626;")
        resumen_layout.addWidget(self.lbl_total_salidas, 0, 2)

        # Sección de bolívares
        self.lbl_saldo_inicial_bs = QLabel("Saldo Inicial BS: 0.00")
        self.lbl_saldo_inicial_bs.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {COLOR_TEXT_MEDIUM};")
        resumen_layout.addWidget(self.lbl_saldo_inicial_bs, 1, 0)

        self.lbl_total_entradas_bs = QLabel("Total Entradas BS: 0.00")
        self.lbl_total_entradas_bs.setStyleSheet("font-size: 12px; font-weight: 600; color: #16A34A;")
        resumen_layout.addWidget(self.lbl_total_entradas_bs, 1, 1)

        self.lbl_total_salidas_bs = QLabel("Total Salidas BS: 0.00")
        self.lbl_total_salidas_bs.setStyleSheet("font-size: 12px; font-weight: 600; color: #DC2626;")
        resumen_layout.addWidget(self.lbl_total_salidas_bs, 1, 2)

        # Saldo final en bolívares
        saldo_final_bs_layout = QVBoxLayout()
        saldo_final_bs_layout.setSpacing(4)
        lbl_saldo_final_bs = QLabel("Saldo Final BS:")
        lbl_saldo_final_bs.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {COLOR_TEXT_MEDIUM};")
        self.saldo_final_bs_input = NumericLineEdit(NumericFieldType.AMOUNT, allow_negative=True, decimals=2)
        self.saldo_final_bs_input.setFixedHeight(32)
        self.saldo_final_bs_input.valueChanged.connect(self._calcular_saldo_final_usd)
        saldo_final_bs_layout.addWidget(lbl_saldo_final_bs)
        saldo_final_bs_layout.addWidget(self.saldo_final_bs_input)
        resumen_layout.addLayout(saldo_final_bs_layout, 2, 0)

        # Tasa de cambio
        tasa_layout = QVBoxLayout()
        tasa_layout.setSpacing(4)
        lbl_tasa = QLabel("Tasa de Cambio:")
        lbl_tasa.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {COLOR_TEXT_MEDIUM};")
        self.tasa_input = NumericLineEdit(NumericFieldType.AMOUNT, allow_negative=False, decimals=2)
        self.tasa_input.setFixedHeight(32)
        self.tasa_input.valueChanged.connect(self._calcular_saldo_final_usd)
        tasa_layout.addWidget(lbl_tasa)
        tasa_layout.addWidget(self.tasa_input)
        resumen_layout.addLayout(tasa_layout, 2, 1)

        # Saldo final en USD (calculado)
        saldo_final_layout = QVBoxLayout()
        saldo_final_layout.setSpacing(4)
        lbl_saldo_final = QLabel("Saldo Final USD (Calc):")
        lbl_saldo_final.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {COLOR_TEXT_MEDIUM};")
        self.saldo_final_input = NumericLineEdit(NumericFieldType.AMOUNT, allow_negative=True, prefix="$ ")
        self.saldo_final_input.setFixedHeight(32)
        self.saldo_final_input.setEnabled(False)  # Solo lectura, calculado automáticamente
        saldo_final_layout.addWidget(lbl_saldo_final)
        saldo_final_layout.addWidget(self.saldo_final_input)
        resumen_layout.addLayout(saldo_final_layout, 2, 2)

        self.lbl_diferencia = QLabel("Diferencia: $0.00")
        self.lbl_diferencia.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {COLOR_TEXT_MEDIUM};")
        resumen_layout.addWidget(self.lbl_diferencia, 3, 0)

        self.lbl_diferencia_bs = QLabel("Diferencia BS: 0.00")
        self.lbl_diferencia_bs.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {COLOR_TEXT_MEDIUM};")
        resumen_layout.addWidget(self.lbl_diferencia_bs, 3, 1)

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
        resumen_layout.addWidget(self.lbl_estado, 3, 2)

        layout.addWidget(resumen_card)

        # ── Botones para agregar movimientos ──
        botones_layout = QHBoxLayout()
        botones_layout.setSpacing(10)

        btn_agregar_entrada = QPushButton("Agregar Entrada")
        btn_agregar_entrada.setIcon(qta.icon("fa5s.plus", color="#16A34A"))
        btn_agregar_entrada.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_agregar_entrada.setFixedHeight(32)
        btn_agregar_entrada.clicked.connect(self._on_agregar_entrada)
        botones_layout.addWidget(btn_agregar_entrada)

        btn_agregar_salida = QPushButton("Agregar Salida")
        btn_agregar_salida.setIcon(qta.icon("fa5s.minus", color="#DC2626"))
        btn_agregar_salida.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_agregar_salida.setFixedHeight(32)
        btn_agregar_salida.clicked.connect(self._on_agregar_salida)
        botones_layout.addWidget(btn_agregar_salida)

        btn_marcar_conciliado = QPushButton("Marcar como Conciliado")
        btn_marcar_conciliado.setIcon(qta.icon("fa5s.check", color="#16A34A"))
        btn_marcar_conciliado.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_marcar_conciliado.setFixedHeight(32)
        btn_marcar_conciliado.clicked.connect(self._marcar_conciliado)
        botones_layout.addWidget(btn_marcar_conciliado)

        btn_calcular = QPushButton("Calcular Conciliación")
        btn_calcular.setIcon(qta.icon("fa5s.calculator", color=COLOR_PRIMARY))
        btn_calcular.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_calcular.setFixedHeight(32)
        btn_calcular.clicked.connect(self._calcular_conciliacion)
        botones_layout.addWidget(btn_calcular)

        btn_guardar = QPushButton("Guardar Movimientos")
        btn_guardar.setIcon(qta.icon("fa5s.save", color="#16A34A"))
        btn_guardar.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_guardar.setFixedHeight(32)
        btn_guardar.clicked.connect(self._guardar_movimientos)
        botones_layout.addWidget(btn_guardar)

        botones_layout.addStretch()

        layout.addLayout(botones_layout)

        # ── Tabla de movimientos del día ──
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            ["Fecha", "Tipo", "Monto", "Tasa", "Monto BS", "Origen", "Referencia", "Descripción"]
        )
        self.table.setMinimumHeight(240)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 95)
        self.table.setColumnWidth(1, 55)
        self.table.setColumnWidth(2, 75)
        self.table.setColumnWidth(3, 55)
        self.table.setColumnWidth(4, 75)
        self.table.setColumnWidth(5, 65)
        self.table.setColumnWidth(6, 80)
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
        layout.addWidget(self.table)

        # ── Footer ──
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 5, 0, 0)
        footer_layout.setSpacing(10)

        footer_layout.addStretch()

        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setIcon(qta.icon("fa5s.times", color=COLOR_TEXT_DARK))
        btn_cerrar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_cerrar.setFixedHeight(32)
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
        self.cuenta_combo.clear()
        for cuenta in cuentas:
            banco_nombre = cuenta.banco.nombre_banco if cuenta.banco else "N/A"
            self.cuenta_combo.addItem(f"{banco_nombre} - {cuenta.numero_cuenta}", cuenta.id_cuenta)

    def _on_fecha_cambiada(self):
        """Maneja el cambio de fecha."""
        self._fecha_conciliacion = self.calendar.selectedDate()
        self._calcular_conciliacion()

    def _on_cuenta_cambiada(self, index: int):
        """Maneja el cambio de cuenta."""
        self._calcular_conciliacion()

    def _calcular_saldo_final_usd(self):
        """Calcula el saldo final USD basado en el saldo final BS y la tasa."""
        saldo_final_bs = self.saldo_final_bs_input.get_value()
        tasa = self.tasa_input.get_value()

        if saldo_final_bs is not None and tasa is not None and tasa > 0:
            saldo_final_usd = saldo_final_bs / tasa
            self.saldo_final_input.set_value(saldo_final_usd)
        else:
            self.saldo_final_input.set_value(0)

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

        # Obtener tasa actual del diálogo principal
        tasa_value = self.tasa_input.get_value()
        tasa_actual = float(tasa_value) if tasa_value is not None and tasa_value > 0 else 0.0

        dialog = MovimientoManualDialog(tipo, parent=self, tasa_inicial=tasa_actual)

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
            if mov.id_pago_cobro:
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
                    "monto": float(mov.monto_movimiento) if mov.monto_movimiento else 0.0,
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

            # Monto
            item_monto = QTableWidgetItem(f"${movimiento['monto']:,.2f}")
            item_monto.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 2, item_monto)

            # Tasa
            tasa_texto = (
                f"{movimiento['tasa']:,.2f}" if movimiento["tasa"] is not None and movimiento["tasa"] > 0 else "N/A"
            )
            item_tasa = QTableWidgetItem(tasa_texto)
            item_tasa.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 3, item_tasa)

            # Monto BS
            item_monto_bs = QTableWidgetItem(f"{movimiento['monto_bs']:,.2f}" if movimiento["monto_bs"] > 0 else "0.00")
            item_monto_bs.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 4, item_monto_bs)

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
        """Marca el día como conciliado si la diferencia en bolívares es 0."""
        id_cuenta = self.cuenta_combo.currentData()
        if id_cuenta is None:
            MessageBox.warning(self, "Selección requerida", "Seleccione una cuenta bancaria.")
            return

        # Verificar que la diferencia en bolívares sea 0
        saldo_final_bs_value = self.saldo_final_bs_input.get_value()
        saldo_final_manual_bs = float(saldo_final_bs_value) if saldo_final_bs_value is not None else 0.0
        tasa_value = self.tasa_input.get_value()
        tasa_cambio = float(tasa_value) if tasa_value is not None and tasa_value > 0 else 0.0

        # Calcular saldo final en USD
        saldo_final_manual = 0.0
        if tasa_cambio > 0:
            saldo_final_manual = saldo_final_manual_bs / tasa_cambio

        if tasa_cambio == 0:
            MessageBox.warning(self, "Tasa requerida", "Debe ingresar una tasa de cambio para conciliar.")
            return

        id_cuenta = self.cuenta_combo.currentData()
        fecha = self._fecha_conciliacion.toPython()

        # Recalcular para verificar
        fecha_inicio = datetime.datetime.combine(fecha, datetime.time.min)
        fecha_fin = datetime.datetime.combine(fecha, datetime.time.max)

        fecha_anterior = fecha - datetime.timedelta(days=1)
        fecha_anterior_fin = datetime.datetime.combine(fecha_anterior, datetime.time.max)

        movimientos_anteriores = (
            self.session.query(BancoMovimiento)
            .filter(
                BancoMovimiento.id_cuenta == id_cuenta,
                BancoMovimiento.fecha_movimiento <= fecha_anterior_fin,
            )
            .all()
        )

        saldo_inicial = 0.0
        saldo_inicial_bs = 0.0
        for mov in movimientos_anteriores:
            if mov.monto_movimiento:
                monto = float(mov.monto_movimiento)
                if mov.tipo_movimiento == "abono":
                    saldo_inicial += monto
                elif mov.tipo_movimiento == "cargo":
                    saldo_inicial -= monto

                # Calcular en bolívares
                if mov.monto_bolivares:
                    monto_bs = float(mov.monto_bolivares)
                elif mov.tasa_cambio and mov.tasa_cambio > 0:
                    monto_bs = monto * float(mov.tasa_cambio)
                else:
                    monto_bs = 0.0

                if mov.tipo_movimiento == "abono":
                    saldo_inicial_bs += monto_bs
                elif mov.tipo_movimiento == "cargo":
                    saldo_inicial_bs -= monto_bs

        movimientos_dia = (
            self.session.query(BancoMovimiento)
            .filter(
                BancoMovimiento.id_cuenta == id_cuenta,
                BancoMovimiento.fecha_movimiento >= fecha_inicio,
                BancoMovimiento.fecha_movimiento <= fecha_fin,
            )
            .all()
        )

        total_entradas = 0.0
        total_salidas = 0.0
        total_entradas_bs = 0.0
        total_salidas_bs = 0.0

        for mov in movimientos_dia:
            if mov.monto_movimiento:
                monto = float(mov.monto_movimiento)
                if mov.tipo_movimiento == "abono":
                    total_entradas += monto
                elif mov.tipo_movimiento == "cargo":
                    total_salidas += monto

                # Calcular en bolívares
                if mov.monto_bolivares:
                    monto_bs = float(mov.monto_bolivares)
                elif mov.tasa_cambio and mov.tasa_cambio > 0:
                    monto_bs = monto * float(mov.tasa_cambio)
                else:
                    monto_bs = 0.0

                if mov.tipo_movimiento == "abono":
                    total_entradas_bs += monto_bs
                elif mov.tipo_movimiento == "cargo":
                    total_salidas_bs += monto_bs

        for mov in self._movimientos_manuales:
            if mov["tipo"] == "abono":
                total_entradas += mov["monto"]
            else:
                total_salidas += mov["monto"]

            # Calcular en bolívares para movimientos manuales
            monto_bs = mov.get("monto_bs", 0.0)
            tasa_mov = mov.get("tasa", tasa_cambio)

            # Si no se proporcionó monto_bs, calcularlo
            if monto_bs == 0.0 and tasa_mov > 0:
                monto_bs = mov["monto"] * tasa_mov

            if mov["tipo"] == "abono":
                total_entradas_bs += monto_bs
            else:
                total_salidas_bs += monto_bs

        saldo_calculado_bs = saldo_inicial_bs + total_entradas_bs - total_salidas_bs

        saldo_final_manual_bs = saldo_final_manual * tasa_cambio
        diferencia_bs = saldo_calculado_bs - saldo_final_manual_bs

        if abs(diferencia_bs) > 0.01:
            MessageBox.warning(
                self,
                "No se puede conciliar",
                f"La conciliación presenta una diferencia de {diferencia_bs:,.2f} BS. "
                "Solo se puede marcar como conciliado cuando la diferencia en bolívares sea 0.",
            )
            return

        # Aquí se podría guardar en una tabla de conciliaciones si existe
        # Por ahora, mostramos un mensaje de éxito
        MessageBox.information(
            self,
            "Conciliación Exitosa",
            f"El día {fecha.strftime('%d/%m/%Y')} ha sido marcado como conciliado.\n"
            f"Saldo Final BS: {saldo_final_manual_bs:,.2f} (${saldo_final_manual:,.2f} USD)\n"
            f"Tasa: {tasa_cambio:,.2f}",
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
        tasa_value = self.tasa_input.get_value()
        tasa_cambio = float(tasa_value) if tasa_value is not None and tasa_value > 0 else 0.0

        # Obtener la tasa actual de control_de_tasas si existe
        tasa_registro = None
        if tasa_cambio > 0:
            tasa_registro = self.session.query(ControlDeTasa).order_by(ControlDeTasa.fecha_tasa.desc()).first()

        try:
            for movimiento in self._movimientos_manuales:
                # El monto en USD se calcula como monto_bs / tasa
                monto = movimiento["monto"]
                monto_bs = movimiento.get("monto_bs", 0.0)
                tasa_mov = movimiento.get("tasa", tasa_cambio)

                # Si no se proporcionó monto_bs, calcularlo
                if monto_bs == 0.0 and tasa_mov is not None and tasa_mov > 0:
                    monto_bs = monto * tasa_mov

                BancoMovimientoService.crear(
                    self.session,
                    id_cuenta=id_cuenta,
                    tipo_movimiento=movimiento["tipo"],
                    monto=movimiento["monto"],
                    referencia=movimiento["referencia"],
                    descripcion=movimiento["descripcion"],
                    id_usuario=self.usuario.id_usuario,
                )
                # Actualizar la fecha del movimiento a la fecha de conciliación
                movimientos = (
                    self.session.query(BancoMovimiento).order_by(BancoMovimiento.id_movimiento.desc()).limit(1).all()
                )
                if movimientos:
                    movimientos[0].fecha_movimiento = fecha_movimiento
                    movimientos[0].monto_bolivares = monto_bs
                    movimientos[0].tasa_cambio = tasa_mov
                    if tasa_registro:
                        movimientos[0].id_tasa = tasa_registro.id_tasa
                    self.session.commit()

            self._movimientos_manuales.clear()
            self._actualizar_tabla_manuales()
            self._calcular_conciliacion()
            MessageBox.information(
                self, "Movimientos Guardados", "Los movimientos manuales han sido guardados exitosamente."
            )
        except Exception as e:
            self.session.rollback()
            MessageBox.critical(self, "Error", f"Error al guardar movimientos: {str(e)}")

    def _calcular_conciliacion(self):
        """Calcula la conciliación bancaria."""
        id_cuenta = self.cuenta_combo.currentData()
        if id_cuenta is None:
            return

        fecha = self._fecha_conciliacion.toPython()
        fecha_inicio = datetime.datetime.combine(fecha, datetime.time.min)
        fecha_fin = datetime.datetime.combine(fecha, datetime.time.max)

        # Obtener tasa de cambio actual
        tasa_value = self.tasa_input.get_value()
        tasa_cambio = float(tasa_value) if tasa_value is not None and tasa_value > 0 else 0.0

        # Obtener saldo inicial (saldo al final del día anterior)
        fecha_anterior = fecha - datetime.timedelta(days=1)
        fecha_anterior_fin = datetime.datetime.combine(fecha_anterior, datetime.time.max)

        movimientos_anteriores = (
            self.session.query(BancoMovimiento)
            .filter(
                BancoMovimiento.id_cuenta == id_cuenta,
                BancoMovimiento.fecha_movimiento <= fecha_anterior_fin,
            )
            .all()
        )

        saldo_inicial = 0.0
        saldo_inicial_bs = 0.0
        for mov in movimientos_anteriores:
            if mov.monto_movimiento:
                monto = float(mov.monto_movimiento)
                if mov.tipo_movimiento == "abono":
                    saldo_inicial += monto
                elif mov.tipo_movimiento == "cargo":
                    saldo_inicial -= monto

                # Calcular en bolívares
                if mov.monto_bolivares:
                    monto_bs = float(mov.monto_bolivares)
                elif mov.tasa_cambio and mov.tasa_cambio > 0:
                    monto_bs = monto * float(mov.tasa_cambio)
                else:
                    monto_bs = 0.0

                if mov.tipo_movimiento == "abono":
                    saldo_inicial_bs += monto_bs
                elif mov.tipo_movimiento == "cargo":
                    saldo_inicial_bs -= monto_bs

        # Obtener movimientos del día
        movimientos_dia = (
            self.session.query(BancoMovimiento)
            .filter(
                BancoMovimiento.id_cuenta == id_cuenta,
                BancoMovimiento.fecha_movimiento >= fecha_inicio,
                BancoMovimiento.fecha_movimiento <= fecha_fin,
            )
            .all()
        )

        total_entradas = 0.0
        total_salidas = 0.0
        total_entradas_bs = 0.0
        total_salidas_bs = 0.0

        for mov in movimientos_dia:
            if mov.monto_movimiento:
                monto = float(mov.monto_movimiento)
                if mov.tipo_movimiento == "abono":
                    total_entradas += monto
                elif mov.tipo_movimiento == "cargo":
                    total_salidas += monto

                # Calcular en bolívares
                if mov.monto_bolivares:
                    monto_bs = float(mov.monto_bolivares)
                elif mov.tasa_cambio and mov.tasa_cambio > 0:
                    monto_bs = monto * float(mov.tasa_cambio)
                else:
                    monto_bs = 0.0

                if mov.tipo_movimiento == "abono":
                    total_entradas_bs += monto_bs
                elif mov.tipo_movimiento == "cargo":
                    total_salidas_bs += monto_bs

        # Agregar movimientos manuales
        for mov in self._movimientos_manuales:
            if mov["tipo"] == "abono":
                total_entradas += mov["monto"]
            else:
                total_salidas += mov["monto"]

            # Calcular en bolívares para movimientos manuales
            monto_bs = mov.get("monto_bs", 0.0)
            tasa_mov = mov.get("tasa", tasa_cambio)

            # Si no se proporcionó monto_bs, calcularlo
            if monto_bs == 0.0 and tasa_mov > 0:
                monto_bs = mov["monto"] * tasa_mov

            if mov["tipo"] == "abono":
                total_entradas_bs += monto_bs
            else:
                total_salidas_bs += monto_bs

        # Saldo final en bolívares ingresado por el usuario
        saldo_final_bs_value = self.saldo_final_bs_input.get_value()
        saldo_final_manual_bs = float(saldo_final_bs_value) if saldo_final_bs_value is not None else 0.0

        # Calcular saldo final en USD (monto BS / tasa)
        saldo_final_manual = 0.0
        if tasa_cambio > 0:
            saldo_final_manual = saldo_final_manual_bs / tasa_cambio
            self.saldo_final_input.set_value(saldo_final_manual)

        # Cálculo en USD: (Saldo Inicial + Entradas - Salidas) - Saldo Final Manual = Diferencia
        saldo_calculado = saldo_inicial + total_entradas - total_salidas
        diferencia = saldo_calculado - saldo_final_manual

        # Cálculo en BS: (Saldo Inicial BS + Entradas BS - Salidas BS) - Saldo Final Manual BS = Diferencia BS
        saldo_calculado_bs = saldo_inicial_bs + total_entradas_bs - total_salidas_bs
        diferencia_bs = saldo_calculado_bs - saldo_final_manual_bs

        # Actualizar etiquetas
        self.lbl_saldo_inicial.setText(f"Saldo Inicial: ${saldo_inicial:,.2f}")
        self.lbl_total_entradas.setText(f"Total Entradas: ${total_entradas:,.2f}")
        self.lbl_total_salidas.setText(f"Total Salidas: ${total_salidas:,.2f}")
        self.lbl_saldo_inicial_bs.setText(f"Saldo Inicial BS: {saldo_inicial_bs:,.2f}")
        self.lbl_total_entradas_bs.setText(f"Total Entradas BS: {total_entradas_bs:,.2f}")
        self.lbl_total_salidas_bs.setText(f"Total Salidas BS: {total_salidas_bs:,.2f}")
        self.lbl_diferencia.setText(f"Diferencia: ${diferencia:,.2f}")
        self.lbl_diferencia_bs.setText(f"Diferencia BS: {diferencia_bs:,.2f}")

        # Verificar si está cuadrado (diferencia debe ser 0 en BS)
        if abs(diferencia_bs) < 0.01:
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
    """Diálogo para agregar un movimiento manual."""

    def __init__(self, tipo: str, parent=None, tasa_inicial: float = 0.0):
        super().__init__(parent)
        self.tipo = tipo
        self.tasa_inicial = tasa_inicial
        self.setWindowTitle(f"Agregar {'Entrada' if tipo == 'abono' else 'Salida'} Manual")
        self.setFixedSize(450, 400)
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

        lbl_monto_bs = QLabel("Monto BS:")
        lbl_monto_bs.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        self.monto_bs_input = NumericLineEdit(NumericFieldType.AMOUNT, decimals=2)
        self.monto_bs_input.setFixedHeight(36)
        self.monto_bs_input.valueChanged.connect(self._calcular_monto)
        form_layout.addWidget(lbl_monto_bs, 0, 0)
        form_layout.addWidget(self.monto_bs_input, 0, 1)

        lbl_tasa = QLabel("Tasa de Cambio:")
        lbl_tasa.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        self.tasa_input = NumericLineEdit(NumericFieldType.AMOUNT, decimals=2)
        self.tasa_input.setFixedHeight(36)
        self.tasa_input.valueChanged.connect(self._calcular_monto)
        form_layout.addWidget(lbl_tasa, 1, 0)
        form_layout.addWidget(self.tasa_input, 1, 1)

        lbl_monto = QLabel("Monto USD (Calc):")
        lbl_monto.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_MEDIUM};")
        self.monto_input = NumericLineEdit(NumericFieldType.AMOUNT, prefix="$ ")
        self.monto_input.setFixedHeight(36)
        self.monto_input.setEnabled(False)  # Solo lectura, calculado automáticamente
        form_layout.addWidget(lbl_monto, 2, 0)
        form_layout.addWidget(self.monto_input, 2, 1)

        lbl_referencia = QLabel("Referencia:")
        lbl_referencia.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        self.referencia_input = QLineEdit()
        self.referencia_input.setPlaceholderText("Ej: Cheque #12345")
        self.referencia_input.setFixedHeight(36)
        self.referencia_input.setMaxLength(100)  # columna referencia_bancaria VARCHAR(100)
        form_layout.addWidget(lbl_referencia, 3, 0)
        form_layout.addWidget(self.referencia_input, 3, 1)

        lbl_descripcion = QLabel("Descripción:")
        lbl_descripcion.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        self.descripcion_input = QLineEdit()
        self.descripcion_input.setPlaceholderText("Ej: Pago de servicios")
        self.descripcion_input.setFixedHeight(36)
        form_layout.addWidget(lbl_descripcion, 4, 0)
        form_layout.addWidget(self.descripcion_input, 4, 1)

        layout.addLayout(form_layout)
        layout.addStretch()

        # Botones
        botones_layout = QHBoxLayout()
        botones_layout.setSpacing(12)

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_cancelar.clicked.connect(self.reject)
        botones_layout.addWidget(btn_cancelar)

        btn_aceptar = QPushButton("Aceptar")
        btn_aceptar.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_aceptar.clicked.connect(self._validar_y_aceptar)
        botones_layout.addWidget(btn_aceptar)

        layout.addLayout(botones_layout)

    def _calcular_monto(self):
        """Calcula el monto en USD basado en el monto BS y la tasa."""
        monto_bs = self.monto_bs_input.get_value()
        tasa = self.tasa_input.get_value()

        if monto_bs is not None and tasa is not None and monto_bs > 0 and tasa > 0:
            monto = monto_bs / tasa
            self.monto_input.set_value(monto)
        else:
            self.monto_input.set_value(0)

    def _validar_y_aceptar(self):
        monto_bs = self.monto_bs_input.get_value()
        tasa = self.tasa_input.get_value()

        if monto_bs is None or monto_bs <= 0:
            MessageBox.warning(self, "Dato requerido", "El monto BS debe ser mayor a 0.")
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
            "monto_bs": float(monto_bs) if monto_bs is not None else 0.0,
            "tasa": float(tasa) if tasa is not None else 0.0,
            "referencia": self.referencia_input.text().strip(),
            "descripcion": self.descripcion_input.text().strip(),
        }
