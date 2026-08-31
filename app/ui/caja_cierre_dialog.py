"""Dialogo de cierre de turno de caja: arqueo (movimientos del turno + saldo calculado)
seguido de la confirmacion que dispara CajaService.cerrar_caja(). Simetrico a
CajaAperturaDialog (app/ui/caja_apertura_dialog.py) pero sin el paso de reautenticacion --
CajasPanel ya exige estar logueado como ADMIN para llegar aqui (_require_admin en el
servicio es la barrera real, esto es solo UX)."""

import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from app.db.models import Caja
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import CajaService
from app.ui.styles import (
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    FONT_FAMILY,
    TABLE_QSS,
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
QPushButton#BtnPrimary {{
    background-color: {COLOR_DANGER};
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 8px 22px;
    font-size: 13px;
    font-weight: bold;
}}
QPushButton#BtnPrimary:hover {{
    background-color: #B91C1C;
}}
QPushButton#BtnSecondary {{
    background-color: {COLOR_TABLE_HEADER};
    color: #475569;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#BtnSecondary:hover {{
    background-color: {COLOR_BORDER};
    color: {COLOR_TEXT_DARK};
}}
"""


class CajaCierreDialog(QDialog):
    """Muestra el arqueo (movimientos del turno + saldo calculado) de una caja abierta y,
    tras confirmar, cierra el turno. `cerrada` queda True si exec() == Accepted."""

    def __init__(self, session: Session, caja: Caja, id_usuario_actor: int, parent=None):
        super().__init__(parent)
        self.session = session
        self.caja = caja
        self.id_usuario_actor = id_usuario_actor
        self.cerrada = False

        self.setWindowTitle("Cerrar Turno de Caja")
        self.setMinimumWidth(560)
        self.resize(560, 520)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()
        self._cargar_arqueo()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.cash-register", color=COLOR_DANGER).pixmap(QSize(20, 20)))
        icon_lbl.setStyleSheet(
            "background-color: #FEF2F2; border: 1.5px solid #FECACA; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(34, 34)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        titulos = QVBoxLayout()
        titulos.setSpacing(1)
        lbl_titulo = QLabel(f"Cerrar turno — {self.caja.nombre_caja or f'Caja {self.caja.id_caja}'}")
        lbl_titulo.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        cajero = self.caja.usuario.nombre_usuario if self.caja.usuario else "—"
        self.lbl_subtitulo = QLabel(f"Cajero: {cajero} · Apertura: {self._fmt_fecha(self.caja.fecha_apertura)}")
        self.lbl_subtitulo.setWordWrap(True)
        self.lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        titulos.addWidget(lbl_titulo)
        titulos.addWidget(self.lbl_subtitulo)
        header.addWidget(icon_lbl)
        header.addLayout(titulos, stretch=1)
        root.addLayout(header)

        root.addWidget(self._make_card_resumen())
        root.addWidget(self._make_tabla_movimientos(), stretch=1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 4, 0, 0)
        footer.setSpacing(10)
        footer.addStretch()

        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.setIcon(qta.icon("fa5s.times", color="#475569"))
        self.btn_cancelar.setObjectName("BtnSecondary")
        self.btn_cancelar.setFixedHeight(34)
        self.btn_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancelar.setAutoDefault(False)
        self.btn_cancelar.clicked.connect(self.reject)

        self.btn_cerrar = QPushButton("Confirmar Cierre de Turno")
        self.btn_cerrar.setIcon(qta.icon("fa5s.lock", color="#FFFFFF"))
        self.btn_cerrar.setObjectName("BtnPrimary")
        self.btn_cerrar.setFixedHeight(34)
        self.btn_cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cerrar.setAutoDefault(False)
        self.btn_cerrar.clicked.connect(self._confirmar_cierre)

        footer.addWidget(self.btn_cancelar)
        footer.addWidget(self.btn_cerrar)
        root.addLayout(footer)

    def _make_card_resumen(self) -> QWidget:
        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(24)

        self.lbl_apertura = self._make_stat("Saldo de apertura", "—")
        self.lbl_entradas = self._make_stat("Entradas", "—", COLOR_SUCCESS)
        self.lbl_salidas = self._make_stat("Salidas", "—", COLOR_DANGER)
        self.lbl_saldo_calculado = self._make_stat("Saldo calculado (a cerrar)", "—", COLOR_PRIMARY)

        layout.addLayout(self.lbl_apertura[0])
        layout.addLayout(self.lbl_entradas[0])
        layout.addLayout(self.lbl_salidas[0])
        layout.addStretch()
        layout.addLayout(self.lbl_saldo_calculado[0])
        return card

    def _make_stat(self, titulo: str, valor_inicial: str, color: str = COLOR_TEXT_DARK):
        col = QVBoxLayout()
        col.setSpacing(2)
        lbl_titulo = QLabel(titulo)
        lbl_titulo.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_MUTED}; font-weight: 600;")
        lbl_valor = QLabel(valor_inicial)
        lbl_valor.setStyleSheet(f"font-size: 16px; color: {color}; font-weight: bold;")
        col.addWidget(lbl_titulo)
        col.addWidget(lbl_valor)
        return col, lbl_valor

    def _make_tabla_movimientos(self) -> QTableWidget:
        self.tabla = QTableWidget(0, 4)
        self.tabla.setHorizontalHeaderLabels(["Fecha", "Tipo", "Descripción", "Monto"])
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setShowGrid(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(self.tabla)
        return self.tabla

    @staticmethod
    def _fmt_fecha(fecha) -> str:
        return fecha.strftime("%d/%m/%Y %H:%M") if fecha else "—"

    def _cargar_arqueo(self) -> None:
        try:
            movimientos = CajaService.listar_movimientos_turno(
                self.session, self.caja.id_caja, id_usuario=self.id_usuario_actor
            )
            saldo_calculado = CajaService.calcular_saldo_actual(self.session, self.caja.id_caja)
        except (ValueError, PermisoDenegadoError) as exc:
            QMessageBox.critical(self, "No se pudo cargar el arqueo", str(exc))
            self.reject()
            return

        total_entradas = sum((m.monto_movimiento or 0) for m in movimientos if m.tipo_movimiento == "entrada")
        total_salidas = sum((m.monto_movimiento or 0) for m in movimientos if m.tipo_movimiento == "salida")

        self.lbl_apertura[1].setText(f"$ {self.caja.saldo_apertura or 0:,.2f}")
        self.lbl_entradas[1].setText(f"+$ {total_entradas:,.2f}")
        self.lbl_salidas[1].setText(f"-$ {total_salidas:,.2f}")
        self.lbl_saldo_calculado[1].setText(f"$ {saldo_calculado:,.2f}")

        self.tabla.setRowCount(len(movimientos))
        for fila, mov in enumerate(movimientos):
            self.tabla.setItem(fila, 0, QTableWidgetItem(self._fmt_fecha(mov.fecha_registro)))
            es_entrada = mov.tipo_movimiento == "entrada"
            tipo_item = QTableWidgetItem("Entrada" if es_entrada else "Salida")
            tipo_item.setForeground(Qt.GlobalColor.darkGreen if es_entrada else Qt.GlobalColor.red)
            self.tabla.setItem(fila, 1, tipo_item)
            self.tabla.setItem(fila, 2, QTableWidgetItem(mov.descripcion_movimiento or ""))
            self.tabla.setItem(fila, 3, QTableWidgetItem(f"$ {mov.monto_movimiento or 0:,.2f}"))

        if not movimientos:
            self.btn_cerrar.setText("Confirmar Cierre de Turno (sin movimientos)")

    def _confirmar_cierre(self) -> None:
        respuesta = QMessageBox.question(
            self,
            "Confirmar cierre de turno",
            "Esta acción cierra el turno y fija el saldo de cierre mostrado arriba.\n"
            "No se puede deshacer desde la aplicación. ¿Confirma el cierre?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if respuesta != QMessageBox.StandardButton.Yes:
            return

        try:
            CajaService.cerrar_caja(self.session, self.caja.id_caja, self.id_usuario_actor)
        except (ValueError, PermisoDenegadoError) as exc:
            QMessageBox.warning(self, "No se pudo cerrar la caja", str(exc))
            return

        self.cerrada = True
        self.accept()
