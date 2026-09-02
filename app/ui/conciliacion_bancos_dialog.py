import datetime

import qtawesome as qta
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCalendarWidget,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
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

from app.db.models import Banco, BancoMovimiento, CuentaBancaria, Usuario
from app.services.banco_movimientos import BancoMovimientoService
from app.ui.message_box import MessageBox
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_PRIMARY,
    COLOR_TEXT_DARK,
    TABLE_QSS,
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
        self.setFixedSize(1000, 700)
        self.setStyleSheet(TABLE_QSS)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()
        self._cargar_cuentas()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # ── Header ──
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.balance-scale", color=COLOR_PRIMARY).pixmap(28, 28))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 2px solid #BFDBFE; border-radius: 10px; padding: 8px;"
        )
        icon_lbl.setFixedSize(44, 44)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_titulo = QLabel("Conciliación de Bancos")
        lbl_titulo.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        header_layout.addWidget(icon_lbl)
        header_layout.addWidget(lbl_titulo)
        header_layout.addStretch()

        layout.addWidget(header)

        # ── Selección de fecha y cuenta ──
        selection_layout = QHBoxLayout()
        selection_layout.setSpacing(12)

        # Calendario
        calendar_layout = QVBoxLayout()
        calendar_layout.setSpacing(4)
        lbl_fecha = QLabel("Fecha de Conciliación:")
        lbl_fecha.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(True)
        self.calendar.setSelectedDate(self._fecha_conciliacion)
        self.calendar.selectionChanged.connect(self._on_fecha_cambiada)
        calendar_layout.addWidget(lbl_fecha)
        calendar_layout.addWidget(self.calendar)

        # Selección de cuenta
        cuenta_layout = QVBoxLayout()
        cuenta_layout.setSpacing(4)
        lbl_cuenta = QLabel("Cuenta Bancaria:")
        lbl_cuenta.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        self.cuenta_combo = QComboBox()
        self.cuenta_combo.setFixedHeight(36)
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
        resumen_layout.setContentsMargins(16, 12, 16, 12)
        resumen_layout.setSpacing(12)

        self.lbl_saldo_inicial = QLabel("Saldo Inicial: $0.00")
        self.lbl_saldo_inicial.setStyleSheet("font-size: 14px; font-weight: 600; color: #475569;")
        resumen_layout.addWidget(self.lbl_saldo_inicial, 0, 0)

        self.lbl_total_entradas = QLabel("Total Entradas: $0.00")
        self.lbl_total_entradas.setStyleSheet("font-size: 14px; font-weight: 600; color: #16A34A;")
        resumen_layout.addWidget(self.lbl_total_entradas, 0, 1)

        self.lbl_total_salidas = QLabel("Total Salidas: $0.00")
        self.lbl_total_salidas.setStyleSheet("font-size: 14px; font-weight: 600; color: #DC2626;")
        resumen_layout.addWidget(self.lbl_total_salidas, 0, 2)

        # Saldo final manual
        saldo_final_layout = QVBoxLayout()
        saldo_final_layout.setSpacing(4)
        lbl_saldo_final = QLabel("Saldo Final (Manual):")
        lbl_saldo_final.setStyleSheet("font-size: 13px; font-weight: 600; color: #475569;")
        self.saldo_final_input = QDoubleSpinBox()
        self.saldo_final_input.setRange(-999999999.99, 999999999.99)
        self.saldo_final_input.setDecimals(2)
        self.saldo_final_input.setPrefix("$ ")
        self.saldo_final_input.setFixedHeight(36)
        self.saldo_final_input.valueChanged.connect(self._calcular_conciliacion)
        saldo_final_layout.addWidget(lbl_saldo_final)
        saldo_final_layout.addWidget(self.saldo_final_input)
        resumen_layout.addLayout(saldo_final_layout, 1, 0)

        self.lbl_diferencia = QLabel("Diferencia: $0.00")
        self.lbl_diferencia.setStyleSheet("font-size: 14px; font-weight: 600; color: #475569;")
        resumen_layout.addWidget(self.lbl_diferencia, 1, 1)

        self.lbl_estado = QLabel("Estado: Pendiente")
        self.lbl_estado.setStyleSheet("font-size: 14px; font-weight: 600; color: #F59E0B;")
        resumen_layout.addWidget(self.lbl_estado, 1, 2)

        layout.addWidget(resumen_card)

        # ── Botones para agregar movimientos ──
        botones_layout = QHBoxLayout()
        botones_layout.setSpacing(12)

        btn_agregar_entrada = QPushButton("Agregar Entrada")
        btn_agregar_entrada.setIcon(qta.icon("fa5s.plus", color="#16A34A"))
        btn_agregar_entrada.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_agregar_entrada.clicked.connect(self._on_agregar_entrada)
        botones_layout.addWidget(btn_agregar_entrada)

        btn_agregar_salida = QPushButton("Agregar Salida")
        btn_agregar_salida.setIcon(qta.icon("fa5s.minus", color="#DC2626"))
        btn_agregar_salida.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_agregar_salida.clicked.connect(self._on_agregar_salida)
        botones_layout.addWidget(btn_agregar_salida)

        btn_marcar_conciliado = QPushButton("Marcar como Conciliado")
        btn_marcar_conciliado.setIcon(qta.icon("fa5s.check", color="#16A34A"))
        btn_marcar_conciliado.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_marcar_conciliado.clicked.connect(self._marcar_conciliado)
        botones_layout.addWidget(btn_marcar_conciliado)

        btn_calcular = QPushButton("Calcular Conciliación")
        btn_calcular.setIcon(qta.icon("fa5s.calculator", color=COLOR_PRIMARY))
        btn_calcular.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_calcular.clicked.connect(self._calcular_conciliacion)
        botones_layout.addWidget(btn_calcular)

        btn_guardar = QPushButton("Guardar Movimientos")
        btn_guardar.setIcon(qta.icon("fa5s.save", color="#16A34A"))
        btn_guardar.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_guardar.clicked.connect(self._guardar_movimientos)
        botones_layout.addWidget(btn_guardar)

        botones_layout.addStretch()

        layout.addLayout(botones_layout)

        # ── Tabla de movimientos del día ──
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Fecha", "Tipo", "Monto", "Origen", "Referencia", "Descripción"])
        self.table.setFixedHeight(250)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 140)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 120)
        layout.addWidget(self.table)

        # ── Footer ──
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 8, 0, 0)
        footer_layout.setSpacing(12)

        footer_layout.addStretch()

        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setIcon(qta.icon("fa5s.times", color=COLOR_TEXT_DARK))
        btn_cerrar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_cerrar.setFixedHeight(36)
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

        dialog = MovimientoManualDialog(tipo, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            datos = dialog.get_data()
            movimiento = {
                "tipo": tipo,
                "monto": datos["monto"],
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

        fecha = self._fecha_conciliacion.toPyDate()
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

            todos_movimientos.append(
                {
                    "tipo": mov.tipo_movimiento,
                    "monto": float(mov.monto_movimiento) if mov.monto_movimiento else 0.0,
                    "origen": origen,
                    "referencia": mov.referencia_movimiento or "N/A",
                    "descripcion": mov.descripcion_movimiento or "N/A",
                    "fecha": mov.fecha_movimiento,
                    "es_manual": False,
                }
            )

        for mov in self._movimientos_manuales:
            todos_movimientos.append(
                {
                    "tipo": mov["tipo"],
                    "monto": mov["monto"],
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
            self.table.setItem(row, 2, QTableWidgetItem(f"${movimiento['monto']:,.2f}"))

            # Origen
            self.table.setItem(row, 3, QTableWidgetItem(movimiento["origen"]))

            # Referencia
            self.table.setItem(row, 4, QTableWidgetItem(movimiento["referencia"]))

            # Descripción
            self.table.setItem(row, 5, QTableWidgetItem(movimiento["descripcion"]))

    def _eliminar_movimiento_manual(self, index: int):
        """Elimina un movimiento manual."""
        if 0 <= index < len(self._movimientos_manuales):
            del self._movimientos_manuales[index]
            self._actualizar_tabla_manuales()
            self._calcular_conciliacion()

    def _marcar_conciliado(self):
        """Marca el día como conciliado si la diferencia es 0."""
        id_cuenta = self.cuenta_combo.currentData()
        if id_cuenta is None:
            MessageBox.warning(self, "Selección requerida", "Seleccione una cuenta bancaria.")
            return

        # Verificar que la diferencia sea 0
        saldo_final_manual = self.saldo_final_input.value()
        id_cuenta = self.cuenta_combo.currentData()
        fecha = self._fecha_conciliacion.toPyDate()

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
        for mov in movimientos_anteriores:
            if mov.monto_movimiento:
                monto = float(mov.monto_movimiento)
                if mov.tipo_movimiento == "abono":
                    saldo_inicial += monto
                elif mov.tipo_movimiento == "cargo":
                    saldo_inicial -= monto

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

        for mov in movimientos_dia:
            if mov.monto_movimiento:
                monto = float(mov.monto_movimiento)
                if mov.tipo_movimiento == "abono":
                    total_entradas += monto
                elif mov.tipo_movimiento == "cargo":
                    total_salidas += monto

        for mov in self._movimientos_manuales:
            if mov["tipo"] == "abono":
                total_entradas += mov["monto"]
            else:
                total_salidas += mov["monto"]

        saldo_calculado = saldo_inicial + total_entradas - total_salidas
        diferencia = saldo_calculado - saldo_final_manual

        if abs(diferencia) > 0.01:
            MessageBox.warning(
                self,
                "No se puede conciliar",
                f"La conciliación presenta una diferencia de ${diferencia:,.2f}. "
                "Solo se puede marcar como conciliado cuando la diferencia sea 0.",
            )
            return

        # Aquí se podría guardar en una tabla de conciliaciones si existe
        # Por ahora, mostramos un mensaje de éxito
        MessageBox.information(
            self,
            "Conciliación Exitosa",
            f"El día {fecha.strftime('%d/%m/%Y')} ha sido marcado como conciliado.\n"
            f"Saldo Final: ${saldo_final_manual:,.2f}",
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

        fecha = self._fecha_conciliacion.toPyDate()
        fecha_movimiento = datetime.datetime.combine(fecha, datetime.datetime.now().time())

        try:
            for movimiento in self._movimientos_manuales:
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

        fecha = self._fecha_conciliacion.toPyDate()
        fecha_inicio = datetime.datetime.combine(fecha, datetime.time.min)
        fecha_fin = datetime.datetime.combine(fecha, datetime.time.max)

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
        for mov in movimientos_anteriores:
            if mov.monto_movimiento:
                monto = float(mov.monto_movimiento)
                if mov.tipo_movimiento == "abono":
                    saldo_inicial += monto
                elif mov.tipo_movimiento == "cargo":
                    saldo_inicial -= monto

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

        for mov in movimientos_dia:
            if mov.monto_movimiento:
                monto = float(mov.monto_movimiento)
                if mov.tipo_movimiento == "abono":
                    total_entradas += monto
                elif mov.tipo_movimiento == "cargo":
                    total_salidas += monto

        # Agregar movimientos manuales
        for mov in self._movimientos_manuales:
            if mov["tipo"] == "abono":
                total_entradas += mov["monto"]
            else:
                total_salidas += mov["monto"]

        # Saldo final manual ingresado por el usuario
        saldo_final_manual = self.saldo_final_input.value()

        # Cálculo: (Saldo Inicial + Entradas - Salidas) - Saldo Final Manual = Diferencia
        saldo_calculado = saldo_inicial + total_entradas - total_salidas
        diferencia = saldo_calculado - saldo_final_manual

        # Actualizar etiquetas
        self.lbl_saldo_inicial.setText(f"Saldo Inicial: ${saldo_inicial:,.2f}")
        self.lbl_total_entradas.setText(f"Total Entradas: ${total_entradas:,.2f}")
        self.lbl_total_salidas.setText(f"Total Salidas: ${total_salidas:,.2f}")
        self.lbl_diferencia.setText(f"Diferencia: ${diferencia:,.2f}")

        # Verificar si está cuadrado (diferencia debe ser 0)
        if abs(diferencia) < 0.01:
            self.lbl_estado.setText("Estado: Cuadrado ✓")
            self.lbl_estado.setStyleSheet("font-size: 14px; font-weight: 600; color: #16A34A;")
        else:
            self.lbl_estado.setText("Estado: Desbalanceado ✗")
            self.lbl_estado.setStyleSheet("font-size: 14px; font-weight: 600; color: #DC2626;")

        # Actualizar tabla de movimientos
        self._actualizar_tabla_manuales()


class MovimientoManualDialog(QDialog):
    """Diálogo para agregar un movimiento manual."""

    def __init__(self, tipo: str, parent=None):
        super().__init__(parent)
        self.tipo = tipo
        self.setWindowTitle(f"Agregar {'Entrada' if tipo == 'abono' else 'Salida'} Manual")
        self.setFixedSize(400, 300)
        self.setStyleSheet(TABLE_QSS)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()

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

        lbl_monto = QLabel("Monto:")
        lbl_monto.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        self.monto_input = QDoubleSpinBox()
        self.monto_input.setRange(0, 999999999.99)
        self.monto_input.setDecimals(2)
        self.monto_input.setPrefix("$ ")
        self.monto_input.setFixedHeight(36)
        form_layout.addWidget(lbl_monto, 0, 0)
        form_layout.addWidget(self.monto_input, 0, 1)

        lbl_referencia = QLabel("Referencia:")
        lbl_referencia.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        self.referencia_input = QLineEdit()
        self.referencia_input.setPlaceholderText("Ej: Cheque #12345")
        self.referencia_input.setFixedHeight(36)
        form_layout.addWidget(lbl_referencia, 1, 0)
        form_layout.addWidget(self.referencia_input, 1, 1)

        lbl_descripcion = QLabel("Descripción:")
        lbl_descripcion.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        self.descripcion_input = QLineEdit()
        self.descripcion_input.setPlaceholderText("Ej: Pago de servicios")
        self.descripcion_input.setFixedHeight(36)
        form_layout.addWidget(lbl_descripcion, 2, 0)
        form_layout.addWidget(self.descripcion_input, 2, 1)

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

    def _validar_y_aceptar(self):
        if self.monto_input.value() <= 0:
            MessageBox.warning(self, "Dato requerido", "El monto debe ser mayor a 0.")
            return
        if not self.referencia_input.text().strip():
            MessageBox.warning(self, "Dato requerido", "La referencia es obligatoria.")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "monto": self.monto_input.value(),
            "referencia": self.referencia_input.text().strip(),
            "descripcion": self.descripcion_input.text().strip(),
        }
