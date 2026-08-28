"""
Panel completo del módulo Tasas de Cambio.
Mismo patrón visual que app/ui/vendedores_panel.py/inventario_panel.py (paleta y
tipografía de app/ui/styles.py), pero sin edición/estado: TasaService no tiene
actualizar/eliminar -- cada registro es un snapshot histórico inmutable (ver
app/services/tasas.py), así que este panel es solo alta + listado + exportación.
"""

import logging
from decimal import Decimal

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.db.models import Usuario
from app.services.exportacion import exportar_excel, exportar_pdf
from app.services.permisos import PermisoDenegadoError
from app.services.tasas import TasaService
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    TABLE_QSS,
    ComboBoxSinScroll,
    alinear_encabezados,
    aplicar_sombra,
)
from app.ui.tasa_registro_dialog import TasaRegistroDialog
from app.ui.toolbar_popups import BotonExportar

logger = logging.getLogger(__name__)

COLS_VISIBLES = ["Fecha", "Tasa BCV", "Dólar Paralelo", "Brecha"]
OPCIONES_RANGO = [("Últimos 30 días", 30), ("Últimos 60 días", 60), ("Últimos 90 días", 90)]


class TasasPanel(QWidget):
    """Panel principal del módulo Tasas de Cambio: tasa vigente + registrar una nueva +
    histórico exportable."""

    # TasaTicker (franja superior del shell, app/ui/tasa_ticker.py) vive fuera de este
    # panel y tiene su propio timer de refresco cada 5 minutos -- sin esta señal, registrar
    # una tasa aca la dejaba mostrando la tasa VIEJA (y su "Actualizado hace X" desfasado)
    # hasta el proximo tick del timer. MainWindow conecta esto a ticker_tasas.cargar_tasa
    # al crear el panel (mismo patron que DashboardPanel.nueva_factura_solicitada).
    tasa_registrada = Signal()

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self._tasa_actual: dict | None = None
        self.setObjectName("ContentArea")
        self._setup_ui()
        QTimer.singleShot(100, self.cargar_datos)

    def showEvent(self, event: QShowEvent) -> None:
        # MainWindow cachea el panel y lo reutiliza via QStackedWidget -- sin esto,
        # volver a "Tasas de Cambio" desde otro modulo mostraba los datos viejos.
        super().showEvent(event)
        self.cargar_datos()

    # ── Construcción de la UI ─────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        root.addWidget(self._make_header())
        root.addWidget(self._make_card_actual())
        root.addWidget(self._make_toolbar())
        root.addWidget(self._make_table(), stretch=1)

        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

    def _make_header(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("Tasas de Cambio")
        lbl.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        h.addWidget(lbl)
        h.addStretch()
        return w

    def _make_bloque_tasa(self, titulo: str, icono: str) -> dict:
        """Devuelve el widget + labels internos (valor/delta) para poder actualizarlos
        despues en _mostrar_tasa_actual() -- mismo criterio visual que TasaTicker, mas
        grande porque aca tiene toda una tarjeta para si solo en vez de una franja."""
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        fila_titulo = QHBoxLayout()
        fila_titulo.setSpacing(6)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon(icono, color=COLOR_TEXT_MUTED).pixmap(14, 14))
        icon_lbl.setStyleSheet("background: transparent;")
        lbl_titulo = QLabel(titulo)
        lbl_titulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED}; background: transparent;")
        fila_titulo.addWidget(icon_lbl)
        fila_titulo.addWidget(lbl_titulo)
        fila_titulo.addStretch()

        lbl_valor = QLabel("—")
        lbl_valor.setStyleSheet(
            f"font-size: 22px; font-weight: bold; color: {COLOR_TEXT_DARK}; background: transparent;"
        )

        lbl_delta = QLabel("")
        lbl_delta.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {COLOR_TEXT_MUTED}; background: transparent;"
        )

        v.addLayout(fila_titulo)
        v.addWidget(lbl_valor)
        v.addWidget(lbl_delta)
        return {"widget": w, "valor": lbl_valor, "delta": lbl_delta}

    def _separador(self) -> QLabel:
        # QLabel con background-color, no QFrame (ver GUIA_ESTILO_UI.md 8.8), 1px con el
        # tono estandar de bordes -- mismo criterio que el separador de tasa_ticker.py.
        sep = QLabel()
        sep.setFixedWidth(1)
        sep.setFixedHeight(48)
        sep.setStyleSheet(f"background-color: {COLOR_BORDER};")
        return sep

    def _make_card_actual(self) -> QWidget:
        card = QWidget()
        card.setObjectName("SectionCard")
        card.setStyleSheet(
            f"#SectionCard {{ background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER};"
            " border-radius: 10px; }"
        )
        aplicar_sombra(card)
        h = QHBoxLayout(card)
        h.setContentsMargins(20, 16, 20, 16)
        h.setSpacing(24)

        self.bloque_bcv = self._make_bloque_tasa("Tasa BCV (Bs./USD)", "fa5s.university")
        self.bloque_paralelo = self._make_bloque_tasa("Dólar Paralelo (Bs./USD)", "fa5s.exchange-alt")
        self.bloque_cop = self._make_bloque_tasa("Peso Colombiano (COP/USD)", "fa5s.coins")

        h.addWidget(self.bloque_bcv["widget"])
        h.addWidget(self._separador())
        h.addWidget(self.bloque_paralelo["widget"])
        h.addWidget(self._separador())
        h.addWidget(self.bloque_cop["widget"])
        h.addStretch()

        self.lbl_actualizado = QLabel("Sin tasas registradas todavía")
        self.lbl_actualizado.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED}; background: transparent;")
        h.addWidget(self.lbl_actualizado)
        return card

    def _make_toolbar(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(
            f"background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 8px; padding: 4px;"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)

        lbl_rango = QLabel("Histórico:")
        lbl_rango.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 13px;")

        self.rango_combo = ComboBoxSinScroll()
        for etiqueta, valor in OPCIONES_RANGO:
            self.rango_combo.addItem(etiqueta, valor)
        self.rango_combo.currentIndexChanged.connect(self.cargar_datos)

        self.btn_registrar = QPushButton("Registrar tasa del día")
        self.btn_registrar.setIcon(qta.icon("fa5s.plus", color="white"))
        self.btn_registrar.setStyleSheet(BUTTON_PRIMARY_QSS)
        self.btn_registrar.clicked.connect(self.registrar_tasa)

        self.btn_exportar = BotonExportar(on_excel=self.exportar_excel_tasas, on_pdf=self.exportar_pdf_tasas)

        h.addWidget(lbl_rango)
        h.addWidget(self.rango_combo)
        h.addSpacerItem(QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        h.addWidget(self.btn_registrar)
        h.addWidget(self.btn_exportar)
        return w

    def _make_table(self) -> QTableWidget:
        self.tabla = QTableWidget(0, len(COLS_VISIBLES))
        self.tabla.setHorizontalHeaderLabels(COLS_VISIBLES)
        alinear_encabezados(
            self.tabla,
            {
                0: Qt.AlignmentFlag.AlignLeft,
                1: Qt.AlignmentFlag.AlignRight,
                2: Qt.AlignmentFlag.AlignRight,
                3: Qt.AlignmentFlag.AlignRight,
            },
        )
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setShowGrid(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(self.tabla)
        self.tabla.verticalHeader().setDefaultSectionSize(45)
        return self.tabla

    # ── Lógica de datos ───────────────────────────────────────────────────

    def cargar_datos(self) -> None:
        session = self.session_factory()
        try:
            actual = TasaService.obtener_tasa_actual(session, id_usuario=self.usuario.id_usuario)
            historico = TasaService.obtener_historico_tasas(
                session, limite=self.rango_combo.currentData(), id_usuario=self.usuario.id_usuario
            )
            self._tasa_actual = actual
            self._mostrar_tasa_actual(actual)
            self._poblar_tabla(historico)
        except PermisoDenegadoError:
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar tasas de cambio.")
        except Exception:
            logger.exception("Fallo al cargar las tasas de cambio")
            QMessageBox.critical(self, "Error de conexión", "No se pudieron cargar las tasas de cambio.")
        finally:
            session.close()

    def _set_delta(self, lbl: QLabel, porcentaje: float | None) -> None:
        if porcentaje is None:
            lbl.setText("")
            return
        if porcentaje > 0:
            color, icono = COLOR_SUCCESS, "▲"
        elif porcentaje < 0:
            color, icono = COLOR_DANGER, "▼"
        else:
            color, icono = COLOR_TEXT_MUTED, ""
        lbl.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {color}; background: transparent;")
        lbl.setText(f"{icono} {abs(porcentaje):.1f}% vs. ayer".strip())

    def _mostrar_tasa_actual(self, actual: dict | None) -> None:
        if actual is None:
            self.bloque_bcv["valor"].setText("—")
            self.bloque_paralelo["valor"].setText("—")
            self.bloque_cop["valor"].setText("—")
            self.lbl_actualizado.setText("Sin tasas registradas todavía")
            return

        self.bloque_bcv["valor"].setText(f"Bs. {float(actual['tasa_bcv']):,.2f}")
        self._set_delta(self.bloque_bcv["delta"], actual.get("porcentaje_vs_ayer_bcv"))

        if actual.get("tasa_paralelo") is not None:
            self.bloque_paralelo["valor"].setText(f"Bs. {float(actual['tasa_paralelo']):,.2f}")
            self._set_delta(self.bloque_paralelo["delta"], actual.get("porcentaje_vs_ayer_paralelo"))
        else:
            self.bloque_paralelo["valor"].setText("—")
            self.bloque_paralelo["delta"].setText("")

        if actual.get("tasa_cop") is not None:
            self.bloque_cop["valor"].setText(f"COP {float(actual['tasa_cop']):,.2f}")
        else:
            self.bloque_cop["valor"].setText("—")
        self.bloque_cop["delta"].setText("")

        fecha = actual["fecha_tasa"]
        self.lbl_actualizado.setText(f"Vigente desde el {fecha.strftime('%d/%m/%Y %H:%M')}")

    def _poblar_tabla(self, historico: list[dict]) -> None:
        filas = list(reversed(historico))  # el servicio devuelve ascendente; la tabla, mas reciente primero
        self.tabla.setRowCount(len(filas))
        for fila, t in enumerate(filas):
            self.tabla.setItem(fila, 0, QTableWidgetItem(t["fecha"].strftime("%d/%m/%Y %H:%M")))

            item_bcv = QTableWidgetItem(f"Bs. {float(t['tasa_bcv']):,.2f}")
            item_bcv.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 1, item_bcv)

            texto_paralelo = f"Bs. {float(t['tasa_paralelo']):,.2f}" if t["tasa_paralelo"] is not None else "—"
            item_paralelo = QTableWidgetItem(texto_paralelo)
            item_paralelo.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 2, item_paralelo)

            texto_brecha = f"{t['brecha_porcentual']:.1f}%" if t["brecha_porcentual"] is not None else "—"
            item_brecha = QTableWidgetItem(texto_brecha)
            item_brecha.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 3, item_brecha)

        self.tabla.setColumnWidth(0, 160)

    # ── Registrar ──────────────────────────────────────────────────────────

    UMBRAL_SALTO_PORCENTUAL = 30.0

    def _saltos_bruscos(self, datos: dict) -> list[str]:
        """Un tipeo (ej. "4.20" en vez de "42.00") afecta de inmediato toda conversion
        VES/COP de facturas/compras en curso, sin ningun paso intermedio que lo frene --
        esto no bloquea el guardado (una tasa SI puede saltar de verdad en una crisis
        cambiaria), solo junta que campos saltaron mucho para poder confirmar antes de
        guardar (auditoria de Tasas, 2026-08-27)."""
        if not self._tasa_actual:
            return []

        saltos = []
        for campo, etiqueta in (("tasa_bcv", "BCV"), ("tasa_paralelo", "Paralelo"), ("tasa_cop", "COP")):
            anterior = self._tasa_actual.get(campo)
            nuevo = datos.get(campo)
            if not anterior or nuevo is None:
                continue
            pct = abs(float((Decimal(str(nuevo)) - anterior) / anterior * 100))
            if pct > self.UMBRAL_SALTO_PORCENTUAL:
                saltos.append(f"{etiqueta}: {pct:.0f}%")
        return saltos

    def _confirmar_si_salto_brusco(self, datos: dict) -> bool:
        saltos = self._saltos_bruscos(datos)
        if not saltos:
            return True
        respuesta = QMessageBox.question(
            self,
            "Cambio brusco detectado",
            "La tasa nueva difiere mucho de la última registrada (" + ", ".join(saltos) + "). "
            "¿Revisaste que no sea un error de tipeo? Esto afecta de inmediato todas las "
            "conversiones de VES/COP en Facturación y Compras.",
        )
        return respuesta == QMessageBox.StandardButton.Yes

    def registrar_tasa(self) -> None:
        dialogo = TasaRegistroDialog(parent=self)
        if not dialogo.exec():
            return

        datos = dialogo.get_data()
        if not self._confirmar_si_salto_brusco(datos):
            return

        session = self.session_factory()
        try:
            TasaService.registrar_tasa(session, **datos, creado_por=self.usuario.id_usuario)
            self.cargar_datos()
            self.tasa_registrada.emit()
            QMessageBox.information(self, "Tasa registrada", "La tasa del día se registró con éxito.")
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "No se pudo registrar la tasa", str(exc))
        except PermisoDenegadoError:
            session.rollback()
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para registrar tasas de cambio.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al registrar la tasa de cambio")
            QMessageBox.critical(self, "Error", "No se pudo registrar la tasa de cambio.")
        finally:
            session.close()

    # ── Exportación ───────────────────────────────────────────────────────

    def _filas_para_exportar(self, session) -> list[list]:
        historico = TasaService.obtener_historico_tasas(
            session, limite=self.rango_combo.currentData(), id_usuario=self.usuario.id_usuario
        )
        return [
            [
                t["fecha"].strftime("%d/%m/%Y %H:%M"),
                float(t["tasa_bcv"]),
                float(t["tasa_paralelo"]) if t["tasa_paralelo"] is not None else None,
                t["brecha_porcentual"],
            ]
            for t in reversed(historico)
        ]

    def exportar_excel_tasas(self) -> None:
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar tasas", "tasas.xlsx", "Excel (*.xlsx)")
        if not ruta:
            return

        session = self.session_factory()
        try:
            filas = self._filas_para_exportar(session)
            exportar_excel(ruta, COLS_VISIBLES, filas)
            QMessageBox.information(self, "Exportación completa", f"Se exportaron {len(filas)} tasas a:\n{ruta}")
        except PermisoDenegadoError:
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar tasas de cambio.")
        except Exception:
            logger.exception("Fallo al exportar el histórico de tasas a Excel")
            QMessageBox.critical(self, "Error", "No se pudo exportar el histórico de tasas.")
        finally:
            session.close()

    def exportar_pdf_tasas(self) -> None:
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar tasas", "tasas.pdf", "PDF (*.pdf)")
        if not ruta:
            return

        session = self.session_factory()
        try:
            filas = self._filas_para_exportar(session)
            exportar_pdf(ruta, "Histórico de Tasas de Cambio", COLS_VISIBLES, filas)
            QMessageBox.information(self, "Exportación completa", f"Se exportaron {len(filas)} tasas a:\n{ruta}")
        except PermisoDenegadoError:
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar tasas de cambio.")
        except Exception:
            logger.exception("Fallo al exportar el histórico de tasas a PDF")
            QMessageBox.critical(self, "Error", "No se pudo exportar el histórico de tasas.")
        finally:
            session.close()
