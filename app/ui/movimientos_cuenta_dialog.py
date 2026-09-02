import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from app.db.models import CuentaBancaria, Usuario
from app.services.banco_movimientos import BancoMovimientoService
from app.ui.styles import (
    BUTTON_SECONDARY_QSS,
    COLOR_PRIMARY,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    TABLE_QSS,
)


class MovimientosCuentaDialog(QDialog):
    """Diálogo para ver los movimientos de una cuenta bancaria."""

    def __init__(self, session: Session, cuenta: CuentaBancaria, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session = session
        self.cuenta = cuenta
        self.usuario = usuario
        self._movimientos = []

        self.setWindowTitle(f"Movimientos - {cuenta.numero_cuenta}")
        self.setFixedSize(900, 600)
        self.setStyleSheet(TABLE_QSS)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()
        self._cargar_movimientos()

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
        icon_lbl.setPixmap(qta.icon("fa5s.exchange-alt", color=COLOR_PRIMARY).pixmap(28, 28))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 2px solid #BFDBFE; border-radius: 10px; padding: 8px;"
        )
        icon_lbl.setFixedSize(44, 44)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titles_layout = QVBoxLayout()
        titles_layout.setSpacing(2)

        banco_nombre = self.cuenta.banco.nombre_banco if self.cuenta.banco else "N/A"
        lbl_titulo = QLabel(f"Movimientos - {self.cuenta.numero_cuenta}")
        lbl_titulo.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        lbl_subtitulo = QLabel(f"Banco: {banco_nombre} | Saldo Actual: ${float(self.cuenta.saldo_total_banco):,.2f}")
        lbl_subtitulo.setStyleSheet(f"font-size: 13px; color: {COLOR_TEXT_MUTED};")

        titles_layout.addWidget(lbl_titulo)
        titles_layout.addWidget(lbl_subtitulo)

        header_layout.addWidget(icon_lbl)
        header_layout.addLayout(titles_layout)
        header_layout.addStretch()

        layout.addWidget(header)

        # ── Tabla de Movimientos ──
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            ["Fecha", "Tipo", "Monto", "Origen", "Referencia", "Descripción", "Usuario", "Pago Relacionado"]
        )
        self.table.setFixedHeight(450)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 140)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 120)
        self.table.setColumnWidth(5, 150)
        self.table.setColumnWidth(6, 100)
        layout.addWidget(self.table)

        # ── Footer ──
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 8, 0, 0)
        footer_layout.setSpacing(12)

        self.lbl_total_entradas = QLabel("Total Entradas: $0.00")
        self.lbl_total_entradas.setStyleSheet("color: #16A34A; font-size: 13px; font-weight: 600;")
        footer_layout.addWidget(self.lbl_total_entradas)

        self.lbl_total_salidas = QLabel("Total Salidas: $0.00")
        self.lbl_total_salidas.setStyleSheet("color: #DC2626; font-size: 13px; font-weight: 600;")
        footer_layout.addWidget(self.lbl_total_salidas)

        footer_layout.addStretch()

        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setIcon(qta.icon("fa5s.times", color=COLOR_TEXT_DARK))
        btn_cerrar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_cerrar.setFixedHeight(36)
        btn_cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cerrar.clicked.connect(self.accept)
        footer_layout.addWidget(btn_cerrar)

        layout.addLayout(footer_layout)

    def _cargar_movimientos(self):
        """Carga los movimientos de la cuenta bancaria."""
        self._movimientos = BancoMovimientoService.listar(
            self.session, id_cuenta=self.cuenta.id_cuenta, id_usuario=self.usuario.id_usuario
        )
        self._actualizar_tabla()
        self._calcular_totales()

    def _actualizar_tabla(self):
        """Actualiza la tabla con los movimientos cargados."""
        self.table.setRowCount(0)
        for row, movimiento in enumerate(self._movimientos):
            self.table.insertRow(row)

            # Fecha
            fecha_str = movimiento.fecha_movimiento.strftime("%d/%m/%Y %H:%M") if movimiento.fecha_movimiento else "N/A"
            self.table.setItem(row, 0, QTableWidgetItem(fecha_str))

            # Tipo
            tipo_item = QTableWidgetItem(movimiento.tipo_movimiento or "N/A")
            if movimiento.tipo_movimiento == "abono":
                tipo_item.setForeground(Qt.GlobalColor.darkGreen)
            elif movimiento.tipo_movimiento == "cargo":
                tipo_item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, 1, tipo_item)

            # Monto
            monto_str = f"${float(movimiento.monto_movimiento):,.2f}" if movimiento.monto_movimiento else "$0.00"
            self.table.setItem(row, 2, QTableWidgetItem(monto_str))

            # Origen (Cliente, Proveedor, Comisión, Manual, Otro)
            origen = "Manual"
            if movimiento.id_pago_cobro:
                origen = "Cliente"
            elif movimiento.id_pago_proveedor:
                origen = "Proveedor"
            elif movimiento.id_pago_comision:
                origen = "Comisión"
            self.table.setItem(row, 3, QTableWidgetItem(origen))

            # Referencia
            self.table.setItem(row, 4, QTableWidgetItem(movimiento.referencia_movimiento or "N/A"))

            # Descripción
            self.table.setItem(row, 5, QTableWidgetItem(movimiento.descripcion_movimiento or "N/A"))

            # Usuario
            nombre_usuario = movimiento.creador.nombre if movimiento.creador else "N/A"
            self.table.setItem(row, 6, QTableWidgetItem(nombre_usuario))

            # Pago Relacionado
            pago_rel = "N/A"
            if movimiento.id_pago_cobro:
                pago_rel = f"Cobro #{movimiento.id_pago_cobro}"
            elif movimiento.id_pago_proveedor:
                pago_rel = f"Prov. #{movimiento.id_pago_proveedor}"
            elif movimiento.id_pago_comision:
                pago_rel = f"Comisión #{movimiento.id_pago_comision}"
            self.table.setItem(row, 7, QTableWidgetItem(pago_rel))

    def _calcular_totales(self):
        """Calcula y muestra los totales de entradas y salidas."""
        total_entradas = 0.0
        total_salidas = 0.0

        for movimiento in self._movimientos:
            if movimiento.monto_movimiento:
                monto = float(movimiento.monto_movimiento)
                if movimiento.tipo_movimiento == "abono":
                    total_entradas += monto
                elif movimiento.tipo_movimiento == "cargo":
                    total_salidas += monto

        self.lbl_total_entradas.setText(f"Total Entradas: ${total_entradas:,.2f}")
        self.lbl_total_salidas.setText(f"Total Salidas: ${total_salidas:,.2f}")
