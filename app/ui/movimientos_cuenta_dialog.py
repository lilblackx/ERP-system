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
from app.ui.paginacion import ControlPaginacion
from app.ui.pantalla import ajustar_tamano, hacer_desplazable
from app.ui.styles import (
    BUTTON_SECONDARY_QSS,
    COLOR_BLUE_LIGHTER,
    COLOR_INFO_BG,
    COLOR_PRIMARY,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    TABLE_QSS,
    alinear_encabezados,
)

POR_PAGINA = 50


class MovimientosCuentaDialog(QDialog):
    """Diálogo para ver los movimientos de una cuenta bancaria."""

    def __init__(self, session: Session, cuenta: CuentaBancaria, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session = session
        self.cuenta = cuenta
        self.usuario = usuario
        # El monto "local" de cada movimiento es en pesos para una cuenta COP y en bolivares para las demas.
        self._moneda_local = "COP" if getattr(cuenta, "moneda", None) == "COP" else "BS"
        self._movimientos = []
        self.paginacion = ControlPaginacion()
        self.paginacion.pagina_cambiada.connect(lambda _pagina: self._cargar_movimientos())

        self.setWindowTitle(f"Movimientos - {cuenta.numero_cuenta}")
        ajustar_tamano(self, 900, 600)
        self.setStyleSheet(TABLE_QSS)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()
        hacer_desplazable(self)
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
            f"background-color: {COLOR_INFO_BG}; border: 2px solid "
            f"{COLOR_BLUE_LIGHTER}; border-radius: 10px; padding: 8px;"
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
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)  # solo lectura
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels(
            [
                "Fecha",
                "Tipo",
                "Monto",
                f"Monto {self._moneda_local}",
                "Tasa",
                "Origen",
                "Referencia",
                "Descripción",
                "Usuario",
                "Pago Relacionado",
            ]
        )
        self.table.setFixedHeight(450)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 140)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 80)
        self.table.setColumnWidth(5, 100)
        self.table.setColumnWidth(6, 120)
        self.table.setColumnWidth(7, 150)
        self.table.setColumnWidth(8, 100)
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
                8: Qt.AlignmentFlag.AlignLeft,
                9: Qt.AlignmentFlag.AlignLeft,
            },
        )
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

        self.lbl_total_entradas_bs = QLabel(f"Total Entradas {self._moneda_local}: 0.00")
        self.lbl_total_entradas_bs.setStyleSheet("color: #16A34A; font-size: 13px; font-weight: 600;")
        footer_layout.addWidget(self.lbl_total_entradas_bs)

        self.lbl_total_salidas_bs = QLabel(f"Total Salidas {self._moneda_local}: 0.00")
        self.lbl_total_salidas_bs.setStyleSheet("color: #DC2626; font-size: 13px; font-weight: 600;")
        footer_layout.addWidget(self.lbl_total_salidas_bs)

        footer_layout.addStretch()
        footer_layout.addWidget(self.paginacion)

        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setIcon(qta.icon("fa5s.times", color=COLOR_TEXT_DARK))
        btn_cerrar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_cerrar.setFixedHeight(36)
        btn_cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cerrar.clicked.connect(self.accept)
        footer_layout.addWidget(btn_cerrar)

        layout.addLayout(footer_layout)

    def _cargar_movimientos(self):
        """Carga una pagina de movimientos de la cuenta bancaria (y los totales de toda la cuenta)."""
        resultado = BancoMovimientoService.listar_paginado(
            self.session,
            id_cuenta=self.cuenta.id_cuenta,
            pagina=self.paginacion.pagina,
            por_pagina=POR_PAGINA,
            id_usuario=self.usuario.id_usuario,
        )
        self._movimientos = resultado["items"]
        self.paginacion.actualizar_desde(resultado, mostrar_total=True)
        self._actualizar_tabla()
        self._mostrar_totales(resultado["totales"])

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
            item_monto = QTableWidgetItem(monto_str)
            item_monto.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 2, item_monto)

            # Monto BS
            monto_bs = 0.0
            if movimiento.monto_bolivares:
                monto_bs = float(movimiento.monto_bolivares)
            elif movimiento.monto_movimiento and movimiento.tasa_cambio and movimiento.tasa_cambio > 0:
                monto_bs = float(movimiento.monto_movimiento) * float(movimiento.tasa_cambio)

            monto_bs_str = f"{monto_bs:,.2f}" if monto_bs > 0 else "0.00"
            item_monto_bs = QTableWidgetItem(monto_bs_str)
            item_monto_bs.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 3, item_monto_bs)

            # Tasa
            if movimiento.tasa_cambio and movimiento.tasa_cambio > 0:
                tasa_str = f"{float(movimiento.tasa_cambio):,.2f}"
            else:
                tasa_str = "N/A"
            item_tasa = QTableWidgetItem(tasa_str)
            item_tasa.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 4, item_tasa)

            # Origen (Cliente, Proveedor, Comisión, Manual, Otro)
            origen = "Manual"
            if movimiento.id_pago_cobro or movimiento.id_pago_cobro_bcv:
                origen = "Cliente"
            elif movimiento.id_pago_proveedor:
                origen = "Proveedor"
            elif movimiento.id_pago_comision:
                origen = "Comisión"
            self.table.setItem(row, 5, QTableWidgetItem(origen))

            # Referencia
            self.table.setItem(row, 6, QTableWidgetItem(movimiento.referencia_movimiento or "N/A"))

            # Descripción
            self.table.setItem(row, 7, QTableWidgetItem(movimiento.descripcion_movimiento or "N/A"))

            # Usuario
            nombre_usuario = movimiento.creador.nombre if movimiento.creador else "N/A"
            self.table.setItem(row, 8, QTableWidgetItem(nombre_usuario))

            # Pago Relacionado
            pago_rel = "N/A"
            if movimiento.id_pago_cobro:
                pago_rel = f"Cobro #{movimiento.id_pago_cobro}"
            elif movimiento.id_pago_cobro_bcv:
                pago_rel = f"Cobro BCV #{movimiento.id_pago_cobro_bcv}"
            elif movimiento.id_pago_proveedor:
                pago_rel = f"Prov. #{movimiento.id_pago_proveedor}"
            elif movimiento.id_pago_comision:
                pago_rel = f"Comisión #{movimiento.id_pago_comision}"
            self.table.setItem(row, 9, QTableWidgetItem(pago_rel))

    def _mostrar_totales(self, totales: dict):
        """Muestra los totales de entradas y salidas de toda la cuenta (calculados en la base)."""
        self.lbl_total_entradas.setText(f"Total Entradas: ${totales['entradas']:,.2f}")
        self.lbl_total_salidas.setText(f"Total Salidas: ${totales['salidas']:,.2f}")
        self.lbl_total_entradas_bs.setText(f"Total Entradas {self._moneda_local}: {totales['entradas_bs']:,.2f}")
        self.lbl_total_salidas_bs.setText(f"Total Salidas {self._moneda_local}: {totales['salidas_bs']:,.2f}")
