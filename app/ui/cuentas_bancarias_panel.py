import logging

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import IntegrityError

from app.db.models import Usuario
from app.services.cuentas_bancarias import CuentaBancariaService
from app.services.exportacion import exportar_excel, exportar_pdf
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import BancoService, _enmascarar_numero_cuenta
from app.ui.conciliacion_bancos_dialog import ConciliacionBancosDialog
from app.ui.cuenta_bancaria_form_dialog import CuentaBancariaFormDialog
from app.ui.message_box import MessageBox
from app.ui.movimientos_cuenta_dialog import MovimientosCuentaDialog
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_TEXT_DARK,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MUTED,
    SEARCH_QSS,
    TABLE_QSS,
    EstadoBadge,
    aplicar_sombra,
)
from app.ui.toolbar_popups import BotonExportar, BotonFiltros

logger = logging.getLogger(__name__)

ESTADOS_VALIDOS = {"ACTIVO", "INACTIVO"}
COLS_VISIBLES = ["ID", "Banco", "Número de Cuenta", "Tipo", "Titular", "Identificación", "Saldo", "Estado"]

COLORES_ESTADO_CUENTA = {
    "ACTIVO": COLOR_SUCCESS,
    "INACTIVO": "#dc3545",  # Rojo para estado inactivo
}


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
        self._filtro_estado = None
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
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # ── Header ── (mismo patrón que bancos_panel.py/vendedores_panel.py: título +
        # badge de conteo -- el encabezado con ícono en caja azul es el patrón de
        # DIALOG_STYLE de un QDialog, ver GUIA_ESTILO_UI.md §7, no el de un panel).
        header = QWidget()
        header.setStyleSheet("background: transparent;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)

        lbl_titulo = QLabel("Cuentas Bancarias")
        lbl_titulo.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        self.lbl_total = QLabel("Cargando…")
        self.lbl_total.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 13px;"
            f" background-color: {COLOR_TABLE_HEADER}; border-radius: 10px;"
            " padding: 3px 10px;"
        )

        header_layout.addWidget(lbl_titulo)
        header_layout.addWidget(self.lbl_total)
        header_layout.addStretch()
        layout.addWidget(header)

        # ── Toolbar ── (GUIA_ESTILO_UI.md §3.4: Buscar — stretch — Nuevo X — Filtrar —
        # Exportar; banco+estado agrupados en un solo BotonFiltros, no dropdowns sueltos)
        toolbar = QWidget()
        toolbar.setStyleSheet(
            f"background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 8px; padding: 4px;"
        )
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 8, 12, 8)
        toolbar_layout.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar por número, titular o identificación…")
        self.search_input.addAction(
            qta.icon("fa5s.search", color=COLOR_TEXT_LIGHT), QLineEdit.ActionPosition.LeadingPosition
        )
        self.search_input.setObjectName("SearchInput")
        self.search_input.setStyleSheet(SEARCH_QSS)
        self.search_input.setFixedWidth(280)
        self.search_input.textChanged.connect(self._on_busqueda_cambiada)
        toolbar_layout.addWidget(self.search_input)
        toolbar_layout.addStretch()

        btn_nuevo = QPushButton("Nueva cuenta")
        btn_nuevo.setIcon(qta.icon("fa5s.plus", color="#FFFFFF"))
        btn_nuevo.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_nuevo.clicked.connect(self._on_nueva_cuenta)
        toolbar_layout.addWidget(btn_nuevo)

        # Filtros (banco + estado) agrupados detras de "Filtrar" -- GUIA_ESTILO_UI.md §3.3,
        # ningun dropdown suelto en la barra, ni siquiera uno solo.
        self.banco_combo = QComboBox()
        self.banco_combo.addItem("Todos los bancos", None)
        self.banco_combo.currentIndexChanged.connect(self._on_banco_cambiado)

        self.estado_combo = QComboBox()
        for etiqueta, valor in ESTADOS_FILTRO:
            self.estado_combo.addItem(etiqueta, valor)
        self.estado_combo.currentIndexChanged.connect(self._on_estado_cambiado)

        self.btn_filtrar = BotonFiltros([("Banco", self.banco_combo), ("Estado", self.estado_combo)])
        toolbar_layout.addWidget(self.btn_filtrar)

        self.btn_exportar = BotonExportar(on_excel=self._exportar_excel, on_pdf=self._exportar_pdf)
        toolbar_layout.addWidget(self.btn_exportar)

        layout.addWidget(toolbar)

        # ── Tabla ── (GUIA_ESTILO_UI.md §5: setup estandar)
        self.table = QTableWidget(0, len(COLS_VISIBLES))
        self.table.setHorizontalHeaderLabels(COLS_VISIBLES)
        alinear_encabezados(
            self.table,
            {
                1: Qt.AlignmentFlag.AlignLeft,
                2: Qt.AlignmentFlag.AlignLeft,
                3: Qt.AlignmentFlag.AlignLeft,
                4: Qt.AlignmentFlag.AlignLeft,
                5: Qt.AlignmentFlag.AlignLeft,
                6: Qt.AlignmentFlag.AlignLeft,
                7: Qt.AlignmentFlag.AlignCenter,
            },
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setStyleSheet(TABLE_QSS)
        aplicar_sombra(self.table)
        self.table.verticalHeader().setDefaultSectionSize(45)
        layout.addWidget(self.table, stretch=1)

        # ── Footer ──
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(12)

        self.lbl_paginacion = QLabel("Mostrando 0 de 0 registros")
        self.lbl_paginacion.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 13px;")
        footer_layout.addWidget(self.lbl_paginacion)

        btn_anterior = QPushButton()
        btn_anterior.setIcon(qta.icon("fa5s.chevron-left", color=COLOR_TEXT_DARK))
        btn_anterior.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_anterior.setFixedWidth(40)
        btn_anterior.clicked.connect(self._on_pagina_anterior)
        footer_layout.addWidget(btn_anterior)

        self.lbl_pagina_actual = QLabel("Página 1")
        self.lbl_pagina_actual.setStyleSheet(f"color: {COLOR_TEXT_DARK}; font-size: 13px; font-weight: 600;")
        footer_layout.addWidget(self.lbl_pagina_actual)

        btn_siguiente = QPushButton()
        btn_siguiente.setIcon(qta.icon("fa5s.chevron-right", color=COLOR_TEXT_DARK))
        btn_siguiente.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_siguiente.setFixedWidth(40)
        btn_siguiente.clicked.connect(self._on_pagina_siguiente)
        footer_layout.addWidget(btn_siguiente)

        footer_layout.addStretch()

        # Botones de acción
        btn_conciliacion = QPushButton("Conciliación de bancos")
        btn_conciliacion.setIcon(qta.icon("fa5s.balance-scale", color=COLOR_TEXT_DARK))
        btn_conciliacion.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_conciliacion.clicked.connect(self._on_conciliacion)
        footer_layout.addWidget(btn_conciliacion)

        btn_ver_movimientos = QPushButton("Ver movimientos")
        btn_ver_movimientos.setIcon(qta.icon("fa5s.exchange-alt", color=COLOR_TEXT_DARK))
        btn_ver_movimientos.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_ver_movimientos.clicked.connect(self._on_ver_movimientos)
        footer_layout.addWidget(btn_ver_movimientos)

        btn_editar = QPushButton("Editar seleccionado")
        btn_editar.setIcon(qta.icon("fa5s.edit", color=COLOR_TEXT_DARK))
        btn_editar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_editar.clicked.connect(self._on_editar)
        footer_layout.addWidget(btn_editar)

        btn_cambiar_estado = QPushButton("Cambiar estado")
        btn_cambiar_estado.setIcon(qta.icon("fa5s.sync-alt", color=COLOR_TEXT_DARK))
        btn_cambiar_estado.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_cambiar_estado.clicked.connect(self._on_cambiar_estado)
        footer_layout.addWidget(btn_cambiar_estado)

        layout.addWidget(footer)

        # Sin esto el panel no fija su propio fondo y hereda el negro por defecto de Qt
        # en los pixeles que TABLE_QSS deja fuera del border-radius de la tabla (las
        # "esquinas negras" reportadas por el usuario, 2026-09-02) -- todos los demas
        # paneles del sistema (bancos_panel.py, vendedores_panel.py, etc.) ya lo hacen.
        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

    def _cargar_bancos(self):
        """Carga la lista de bancos en el combo de filtro via BancoService (antes hacia
        session.query(Banco) directo, sin pasar por require_permiso -- mismo hallazgo de
        auditoria que bancos_panel.py, 2026-09-02)."""
        session = self.session_factory()
        try:
            bancos = BancoService.listar_bancos(session, id_usuario=self.usuario.id_usuario)
            self.banco_combo.clear()
            self.banco_combo.addItem("Todos los bancos", None)
            for banco in bancos:
                if banco.estado_banco == "ACTIVO":
                    self.banco_combo.addItem(f"{banco.nombre_banco} ({banco.codigo_banco})", banco.id_banco)
        except PermisoDenegadoError:
            pass
        finally:
            session.close()

    def _cargar_datos(self):
        """Carga las cuentas bancarias según los filtros actuales."""
        session = self.session_factory()
        try:
            resultado = CuentaBancariaService.listar(
                session,
                texto_busqueda=self._texto_busqueda or None,
                estado_cuenta=self._filtro_estado,
                id_banco=self._filtro_banco,
                id_usuario=self.usuario.id_usuario,
                pagina=self._pagina_actual,
                por_pagina=self._por_pagina,
            )
            self._cuentas = resultado["items"]
            self._total_registros = resultado["total"]
            self._actualizar_tabla()
            self._actualizar_paginacion()
        except PermisoDenegadoError:
            self._cuentas = []
            self._total_registros = 0
            self._actualizar_tabla()
            self._actualizar_paginacion()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar cuentas bancarias.")
        except Exception:
            logger.exception("Fallo al cargar la lista de cuentas bancarias")
            self._cuentas = []
            self._total_registros = 0
            self._actualizar_tabla()
            self._actualizar_paginacion()
            MessageBox.critical(self, "Error de conexión", "No se pudo cargar la lista de cuentas bancarias.")
        finally:
            session.close()

    def _actualizar_tabla(self):
        """Actualiza la tabla con las cuentas cargadas."""
        self.table.setRowCount(0)
        for row, cuenta in enumerate(self._cuentas):
            self.table.insertRow(row)

            self.table.setItem(row, 0, QTableWidgetItem(str(cuenta.id_cuenta)))
            self.table.setItem(row, 1, QTableWidgetItem(cuenta.banco.nombre_banco if cuenta.banco else "N/A"))
            self.table.setItem(row, 2, QTableWidgetItem(_enmascarar_numero_cuenta(cuenta.numero_cuenta) or "N/A"))
            self.table.setItem(row, 3, QTableWidgetItem(cuenta.tipo_cuenta_banco or "N/A"))
            self.table.setItem(row, 4, QTableWidgetItem(cuenta.nombre_titular or "N/A"))
            self.table.setItem(row, 5, QTableWidgetItem(cuenta.identificacion_titular or "N/A"))
            self.table.setItem(row, 6, QTableWidgetItem(f"${float(cuenta.saldo_total_banco):,.2f}"))

            estado = cuenta.estado_cuenta or "N/A"
            color_estado = COLORES_ESTADO_CUENTA.get(estado, COLOR_TEXT_MUTED)
            estado_widget = EstadoBadge(estado, color_estado)
            self.table.setCellWidget(row, 7, estado_widget)

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
        self._filtro_estado = self.estado_combo.currentData()
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
        except IntegrityError:
            session.rollback()
            MessageBox.warning(
                self, "Dato inválido", "No se pudo guardar la cuenta bancaria: verifica el banco seleccionado."
            )
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para crear cuentas bancarias.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al crear cuenta bancaria")
            MessageBox.critical(self, "Error", "No se pudo crear la cuenta bancaria.")
        finally:
            session.close()

    def _on_editar(self):
        """Abre el diálogo para editar la cuenta seleccionada."""
        row = self.table.currentRow()
        if row < 0:
            MessageBox.information(self, "Selección requerida", "Selecciona una cuenta de la lista.")
            return

        cuenta = self._cuentas[row]
        session = self.session_factory()
        try:
            dialog = CuentaBancariaFormDialog(session, cuenta, parent=self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                datos = dialog.get_data()
                CuentaBancariaService.actualizar(session, cuenta.id_cuenta, id_usuario=self.usuario.id_usuario, **datos)
                self._cargar_datos()
        except IntegrityError:
            session.rollback()
            MessageBox.warning(
                self, "Dato inválido", "No se pudo guardar la cuenta bancaria: verifica el banco seleccionado."
            )
        except ValueError as exc:
            session.rollback()
            MessageBox.warning(self, "Dato inválido", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para editar cuentas bancarias.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al editar cuenta bancaria")
            MessageBox.critical(self, "Error", "No se pudo guardar los cambios de la cuenta bancaria.")
        finally:
            session.close()

    def _on_cambiar_estado(self):
        """Cambia el estado de la cuenta seleccionada."""
        row = self.table.currentRow()
        if row < 0:
            MessageBox.information(self, "Selección requerida", "Selecciona una cuenta de la lista.")
            return

        cuenta = self._cuentas[row]
        nuevo_estado = "INACTIVO" if cuenta.estado_cuenta == "ACTIVO" else "ACTIVO"
        respuesta = MessageBox.question(
            self, "Confirmar", f"¿Cambiar el estado de la cuenta '{cuenta.numero_cuenta}' a {nuevo_estado}?"
        )
        if respuesta != QMessageBox.StandardButton.Yes:
            return

        session = self.session_factory()
        try:
            CuentaBancariaService.cambiar_estado(
                session, cuenta.id_cuenta, nuevo_estado, id_usuario=self.usuario.id_usuario
            )
            self._cargar_datos()
        except PermisoDenegadoError:
            session.rollback()
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para cambiar el estado de cuentas bancarias.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al cambiar el estado de la cuenta bancaria %s", cuenta.id_cuenta)
            MessageBox.critical(self, "Error", "No se pudo cambiar el estado de la cuenta bancaria.")
        finally:
            session.close()

    def _on_ver_movimientos(self):
        """Abre el diálogo para ver los movimientos de la cuenta seleccionada."""
        row = self.table.currentRow()
        if row < 0:
            MessageBox.information(
                self, "Selección requerida", "Selecciona una cuenta bancaria para ver sus movimientos."
            )
            return

        cuenta = self._cuentas[row]
        session = self.session_factory()
        try:
            dialog = MovimientosCuentaDialog(session, cuenta, self.usuario, parent=self)
            dialog.exec()
            self._cargar_datos()
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar movimientos bancarios.")
        except Exception:
            logger.exception("Fallo al abrir los movimientos de la cuenta bancaria %s", cuenta.id_cuenta)
            MessageBox.critical(self, "Error", "No se pudo abrir los movimientos de la cuenta.")
        finally:
            session.close()

    def _on_conciliacion(self):
        """Abre el diálogo de conciliación de bancos."""
        session = self.session_factory()
        try:
            dialog = ConciliacionBancosDialog(session, self.usuario, parent=self)
            dialog.exec()
            self._cargar_datos()
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para conciliar bancos.")
        except Exception:
            logger.exception("Fallo al abrir la conciliación de bancos")
            MessageBox.critical(self, "Error", "No se pudo abrir la conciliación de bancos.")
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

    def _filas_para_exportar(self, session) -> list[list]:
        resultado = CuentaBancariaService.listar(
            session,
            texto_busqueda=self._texto_busqueda or None,
            estado_cuenta=self._filtro_estado,
            id_banco=self._filtro_banco,
            id_usuario=self.usuario.id_usuario,
            pagina=1,
            por_pagina=1_000_000,
        )
        cuentas = resultado["items"]
        return [
            [
                cuenta.id_cuenta,
                cuenta.banco.nombre_banco if cuenta.banco else None,
                _enmascarar_numero_cuenta(cuenta.numero_cuenta),
                cuenta.tipo_cuenta_banco,
                cuenta.nombre_titular,
                cuenta.identificacion_titular,
                float(cuenta.saldo_total_banco or 0),
                cuenta.estado_cuenta,
            ]
            for cuenta in cuentas
        ]

    def _exportar_excel(self):
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Exportar cuentas bancarias", "cuentas_bancarias.xlsx", "Excel (*.xlsx)"
        )
        if not ruta:
            return

        session = self.session_factory()
        try:
            filas = self._filas_para_exportar(session)
            exportar_excel(ruta, COLS_VISIBLES, filas)
            MessageBox.information(
                self, "Exportación completa", f"Se exportaron {len(filas)} cuentas bancarias a:\n{ruta}"
            )
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar cuentas bancarias.")
        except Exception:
            logger.exception("Fallo al exportar la lista de cuentas bancarias a Excel")
            MessageBox.critical(self, "Error", "No se pudo exportar la lista de cuentas bancarias.")
        finally:
            session.close()

    def _exportar_pdf(self):
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Exportar cuentas bancarias", "cuentas_bancarias.pdf", "PDF (*.pdf)"
        )
        if not ruta:
            return

        session = self.session_factory()
        try:
            filas = self._filas_para_exportar(session)

            filtros = {}
            texto_busqueda = self.search_input.text().strip()
            filtros["Búsqueda"] = texto_busqueda if texto_busqueda else "Todos"
            filtros["Banco"] = self.banco_combo.currentText()
            filtros["Estado"] = self.estado_combo.currentText()

            col_widths = [0.5, 1.5, 1.5, 1.0, 1.5, 1.3, 1.0, 1.0]

            exportar_pdf(
                ruta,
                "Reporte de Cuentas Bancarias",
                COLS_VISIBLES,
                filas,
                filtros=filtros,
                col_widths=col_widths,
            )
            MessageBox.information(
                self, "Exportación completa", f"Se exportaron {len(filas)} cuentas bancarias a:\n{ruta}"
            )
        except PermisoDenegadoError:
            MessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar cuentas bancarias.")
        except Exception:
            logger.exception("Fallo al exportar la lista de cuentas bancarias a PDF")
            MessageBox.critical(self, "Error", "No se pudo exportar la lista de cuentas bancarias.")
        finally:
            session.close()

    def closeEvent(self, event):
        """Detiene el timer de auto-refresh cuando se cierra el panel."""
        self._refresh_timer.stop()
        super().closeEvent(event)
