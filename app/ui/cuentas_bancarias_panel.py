import qtawesome as qta
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.db.models import Banco, Usuario
from app.services.cuentas_bancarias import CuentaBancariaService
from app.ui.cuenta_bancaria_form_dialog import CuentaBancariaFormDialog
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    SEARCH_QSS,
    TABLE_QSS,
)

ESTADOS_VALIDOS = {"ACTIVO", "INACTIVO"}


class CuentasBancariasPanel(QWidget):
    """Panel de gestión de cuentas bancarias."""

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self._cuentas = []
        self._pagina_actual = 1
        self._por_pagina = 20
        self._total_registros = 0
        self._filtro_estado = "TODOS"
        self._filtro_banco = None
        self._texto_busqueda = ""

        self._setup_ui()
        self._cargar_bancos()
        self._cargar_datos()

        # Timer para auto-refresh de saldos (cada 30 segundos)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._cargar_datos)
        self._refresh_timer.start(30000)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # ── Header ──
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.university", color=COLOR_PRIMARY).pixmap(32, 32))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 2px solid #BFDBFE; border-radius: 12px; padding: 8px;"
        )
        icon_lbl.setFixedSize(48, 48)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titles_layout = QVBoxLayout()
        titles_layout.setSpacing(2)

        lbl_titulo = QLabel("Cuentas Bancarias")
        lbl_titulo.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        self.lbl_subtitulo = QLabel("Gestión de cuentas bancarias")
        self.lbl_subtitulo.setStyleSheet(f"font-size: 13px; color: {COLOR_TEXT_MUTED};")

        titles_layout.addWidget(lbl_titulo)
        titles_layout.addWidget(self.lbl_subtitulo)

        header_layout.addWidget(icon_lbl)
        header_layout.addLayout(titles_layout)
        header_layout.addStretch()

        layout.addWidget(header)

        # ── Toolbar ──
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(12)

        # Buscador
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar por número, titular o identificación...")
        self.search_input.setStyleSheet(SEARCH_QSS)
        self.search_input.setFixedHeight(40)
        self.search_input.textChanged.connect(self._on_busqueda_cambiada)
        toolbar_layout.addWidget(self.search_input, 1)

        # Filtro por banco
        self.banco_combo = QComboBox()
        self.banco_combo.setPlaceholderText("Todos los bancos")
        self.banco_combo.setStyleSheet(SEARCH_QSS)
        self.banco_combo.setFixedHeight(40)
        self.banco_combo.setFixedWidth(200)
        self.banco_combo.currentIndexChanged.connect(self._on_banco_cambiado)
        toolbar_layout.addWidget(self.banco_combo)

        # Filtro por estado
        self.estado_combo = QComboBox()
        self.estado_combo.addItems(["TODOS", "ACTIVO", "INACTIVO"])
        self.estado_combo.setStyleSheet(SEARCH_QSS)
        self.estado_combo.setFixedHeight(40)
        self.estado_combo.setFixedWidth(120)
        self.estado_combo.currentIndexChanged.connect(self._on_estado_cambiado)
        toolbar_layout.addWidget(self.estado_combo)

        # Botón Nueva Cuenta
        btn_nuevo = QPushButton("Nueva Cuenta")
        btn_nuevo.setIcon(qta.icon("fa5s.plus", color="#FFFFFF"))
        btn_nuevo.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_nuevo.setFixedHeight(40)
        btn_nuevo.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_nuevo.clicked.connect(self._on_nueva_cuenta)
        toolbar_layout.addWidget(btn_nuevo)

        # Botón Exportar
        btn_exportar = QPushButton("Exportar")
        btn_exportar.setIcon(qta.icon("fa5s.file-excel", color=COLOR_PRIMARY))
        btn_exportar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_exportar.setFixedHeight(40)
        btn_exportar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_exportar.clicked.connect(self._on_exportar)
        toolbar_layout.addWidget(btn_exportar)

        layout.addWidget(toolbar)

        # ── Tabla ──
        self.table = QTableWidget()
        self.table.setStyleSheet(TABLE_QSS)
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Banco", "Número de Cuenta", "Tipo", "Titular", "Identificación", "Saldo", "Estado"]
        )
        self.table.setFixedHeight(400)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 60)
        self.table.setColumnWidth(1, 180)
        self.table.setColumnWidth(2, 150)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 150)
        self.table.setColumnWidth(5, 120)
        self.table.setColumnWidth(6, 100)
        layout.addWidget(self.table)

        # ── Footer ──
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(12)

        self.lbl_paginacion = QLabel("Mostrando 0 de 0 registros")
        self.lbl_paginacion.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 13px;")
        footer_layout.addWidget(self.lbl_paginacion)
        footer_layout.addStretch()

        btn_anterior = QPushButton("Anterior")
        btn_anterior.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_anterior.setFixedHeight(36)
        btn_anterior.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_anterior.clicked.connect(self._on_pagina_anterior)
        footer_layout.addWidget(btn_anterior)

        self.lbl_pagina_actual = QLabel("Página 1")
        self.lbl_pagina_actual.setStyleSheet(f"color: {COLOR_TEXT_DARK}; font-size: 13px; font-weight: 600;")
        footer_layout.addWidget(self.lbl_pagina_actual)

        btn_siguiente = QPushButton("Siguiente")
        btn_siguiente.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_siguiente.setFixedHeight(36)
        btn_siguiente.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_siguiente.clicked.connect(self._on_pagina_siguiente)
        footer_layout.addWidget(btn_siguiente)

        # Botones de acción
        btn_editar = QPushButton("Editar")
        btn_editar.setIcon(qta.icon("fa5s.edit", color=COLOR_PRIMARY))
        btn_editar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_editar.setFixedHeight(36)
        btn_editar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_editar.clicked.connect(self._on_editar)
        footer_layout.addWidget(btn_editar)

        btn_cambiar_estado = QPushButton("Cambiar Estado")
        btn_cambiar_estado.setIcon(qta.icon("fa5s.toggle-on", color=COLOR_SUCCESS))
        btn_cambiar_estado.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_cambiar_estado.setFixedHeight(36)
        btn_cambiar_estado.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cambiar_estado.clicked.connect(self._on_cambiar_estado)
        footer_layout.addWidget(btn_cambiar_estado)

        layout.addWidget(footer)

    def _cargar_bancos(self):
        """Carga la lista de bancos en el combo de filtro."""
        session = self.session_factory()
        try:
            bancos = session.query(Banco).filter(Banco.estado_banco == "ACTIVO").order_by(Banco.nombre_banco).all()
            self.banco_combo.clear()
            self.banco_combo.addItem("Todos los bancos", None)
            for banco in bancos:
                self.banco_combo.addItem(f"{banco.nombre_banco} ({banco.codigo_banco})", banco.id_banco)
        finally:
            session.close()

    def _cargar_datos(self):
        """Carga las cuentas bancarias según los filtros actuales."""
        session = self.session_factory()
        try:
            estado_filtro = None if self._filtro_estado == "TODOS" else self._filtro_estado
            resultado = CuentaBancariaService.listar(
                session,
                texto_busqueda=self._texto_busqueda or None,
                estado_cuenta=estado_filtro,
                id_banco=self._filtro_banco,
                id_usuario=self.usuario.id_usuario,
                pagina=self._pagina_actual,
                por_pagina=self._por_pagina,
            )
            self._cuentas = resultado["items"]
            self._total_registros = resultado["total"]
            self._actualizar_tabla()
            self._actualizar_paginacion()
        finally:
            session.close()

    def _actualizar_tabla(self):
        """Actualiza la tabla con las cuentas cargadas."""
        self.table.setRowCount(0)
        for row, cuenta in enumerate(self._cuentas):
            self.table.insertRow(row)

            self.table.setItem(row, 0, QTableWidgetItem(str(cuenta.id_cuenta)))
            self.table.setItem(row, 1, QTableWidgetItem(cuenta.banco.nombre_banco if cuenta.banco else "N/A"))
            self.table.setItem(row, 2, QTableWidgetItem(cuenta.numero_cuenta or "N/A"))
            self.table.setItem(row, 3, QTableWidgetItem(cuenta.tipo_cuenta_banco or "N/A"))
            self.table.setItem(row, 4, QTableWidgetItem(cuenta.nombre_titular or "N/A"))
            self.table.setItem(row, 5, QTableWidgetItem(cuenta.identificacion_titular or "N/A"))
            self.table.setItem(row, 6, QTableWidgetItem(f"${float(cuenta.saldo_total_banco):,.2f}"))

            estado_item = QTableWidgetItem(cuenta.estado_cuenta)
            if cuenta.estado_cuenta == "ACTIVO":
                estado_item.setForeground(Qt.GlobalColor.darkGreen)
            else:
                estado_item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, 7, estado_item)

    def _actualizar_paginacion(self):
        """Actualiza los controles de paginación."""
        inicio = (self._pagina_actual - 1) * self._por_pagina + 1
        fin = min(inicio + self._por_pagina - 1, self._total_registros)
        self.lbl_paginacion.setText(f"Mostrando {inicio}-{fin} de {self._total_registros} registros")
        self.lbl_pagina_actual.setText(f"Página {self._pagina_actual}")

    def _on_busqueda_cambiada(self, texto: str):
        """Maneja el cambio en el texto de búsqueda."""
        self._texto_busqueda = texto.strip()
        self._pagina_actual = 1
        self._cargar_datos()

    def _on_banco_cambiado(self, index: int):
        """Maneja el cambio en el filtro de banco."""
        self._filtro_banco = self.banco_combo.currentData()
        self._pagina_actual = 1
        self._cargar_datos()

    def _on_estado_cambiado(self, index: int):
        """Maneja el cambio en el filtro de estado."""
        self._filtro_estado = self.estado_combo.currentText()
        self._pagina_actual = 1
        self._cargar_datos()

    def _on_nueva_cuenta(self):
        """Abre el diálogo para crear una nueva cuenta bancaria."""
        session = self.session_factory()
        try:
            dialog = CuentaBancariaFormDialog(session, parent=self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                datos = dialog.get_data()
                datos["creado_por"] = self.usuario.id_usuario
                CuentaBancariaService.crear(session, **datos)
                self._cargar_datos()
        finally:
            session.close()

    def _on_editar(self):
        """Abre el diálogo para editar la cuenta seleccionada."""
        row = self.table.currentRow()
        if row < 0:
            return

        cuenta = self._cuentas[row]
        session = self.session_factory()
        try:
            dialog = CuentaBancariaFormDialog(session, cuenta, parent=self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                datos = dialog.get_data()
                CuentaBancariaService.actualizar(session, cuenta.id_cuenta, id_usuario=self.usuario.id_usuario, **datos)
                self._cargar_datos()
        finally:
            session.close()

    def _on_cambiar_estado(self):
        """Cambia el estado de la cuenta seleccionada."""
        row = self.table.currentRow()
        if row < 0:
            return

        cuenta = self._cuentas[row]
        nuevo_estado = "INACTIVO" if cuenta.estado_cuenta == "ACTIVO" else "ACTIVO"
        session = self.session_factory()
        try:
            CuentaBancariaService.cambiar_estado(
                session, cuenta.id_cuenta, nuevo_estado, id_usuario=self.usuario.id_usuario
            )
            self._cargar_datos()
        finally:
            session.close()

    def _on_pagina_anterior(self):
        """Retrocede a la página anterior."""
        if self._pagina_actual > 1:
            self._pagina_actual -= 1
            self._cargar_datos()

    def _on_pagina_siguiente(self):
        """Avanza a la página siguiente."""
        total_paginas = (self._total_registros + self._por_pagina - 1) // self._por_pagina
        if self._pagina_actual < total_paginas:
            self._pagina_actual += 1
            self._cargar_datos()

    def _on_exportar(self):
        """Exporta los datos actuales a Excel (placeholder)."""
        # TODO: Implementar exportación a Excel
        pass

    def closeEvent(self, event):
        """Detiene el timer de auto-refresh cuando se cierra el panel."""
        self._refresh_timer.stop()
        super().closeEvent(event)
