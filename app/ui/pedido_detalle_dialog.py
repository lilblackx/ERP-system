"""Detalle de un pedido de venta: quien lo pidio, en que estado esta y sus lineas.

Recibe los datos ya armados (`PedidoService.detalle_pedido`: diccionarios y numeros, nada ligado a una sesion), asi
que se abre sin tocar la base y no depende de que ninguna sesion siga abierta.
"""

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.ui.pantalla import ajustar_tamano
from app.ui.styles import (
    BUTTON_SECONDARY_QSS,
    COLOR_CARD_BG,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    COLORES_ESTADO_PEDIDO,
    TABLE_QSS,
    EstadoBadge,
    alinear_encabezados,
    dar_ancho_a_texto,
)

COLS = ["PRODUCTO", "CANTIDAD", "PRECIO", "SUBTOTAL"]


def _fecha(valor) -> str:
    return valor.strftime("%d/%m/%Y %H:%M") if valor else "—"


def _tipo(tipo_venta: str) -> str:
    return "caja" if tipo_venta == "bulto" else "und"


class PedidoDetalleDialog(QDialog):
    def __init__(self, datos: dict, parent=None):
        super().__init__(parent)
        self.datos = datos
        self.setWindowTitle(f"Pedido {datos['numero_pedido']}")
        ajustar_tamano(self, 760, 560, 640, 440)
        self.setStyleSheet(f"QDialog {{ background-color: {COLOR_CARD_BG}; }}")

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(20, 16, 20, 16)
        raiz.setSpacing(12)
        raiz.addLayout(self._cabecera())
        raiz.addLayout(self._datos_generales())
        raiz.addWidget(self._tabla_lineas(), stretch=1)
        raiz.addLayout(self._pie())

    def _cabecera(self) -> QHBoxLayout:
        fila = QHBoxLayout()
        titulo = QLabel(f"Pedido {self.datos['numero_pedido']}")
        titulo.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        estado = self.datos["estado"]
        self.badge = EstadoBadge(estado.capitalize(), COLORES_ESTADO_PEDIDO.get(estado, COLOR_TEXT_MUTED))
        fila.addWidget(titulo)
        fila.addWidget(self.badge)
        fila.addStretch()
        return fila

    def _datos_generales(self) -> QGridLayout:
        d = self.datos
        condicion = "Contado" if d["condicion_pago"] == "contado" else "Crédito"
        campos = [
            ("Cliente", d["cliente"]),
            ("Vendedor", d["vendedor"]),
            ("Fecha", _fecha(d["fecha_creacion"])),
            ("Condición de pago", condicion),
        ]
        if d["estado"] == "ENVIADO":
            campos.append(("Reserva hasta", _fecha(d["fecha_vencimiento_reserva"])))
        if d["observaciones"]:
            campos.append(("Observaciones", d["observaciones"]))
        if d["motivo"]:
            campos.append(("Motivo", d["motivo"]))

        rejilla = QGridLayout()
        rejilla.setHorizontalSpacing(24)
        rejilla.setVerticalSpacing(6)
        for i, (etiqueta, valor) in enumerate(campos):
            lbl = QLabel(etiqueta)
            lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")
            val = QLabel(str(valor))
            val.setWordWrap(True)
            val.setStyleSheet(f"color: {COLOR_TEXT_DARK}; font-size: 13px;")
            rejilla.addWidget(lbl, i // 2 * 2, i % 2)
            rejilla.addWidget(val, i // 2 * 2 + 1, i % 2)
        return rejilla

    def _tabla_lineas(self) -> QTableWidget:
        lineas = self.datos["lineas"]
        self.tabla = QTableWidget(len(lineas), len(COLS))
        self.tabla.setHorizontalHeaderLabels(COLS)
        alinear_encabezados(
            self.tabla,
            {
                0: Qt.AlignmentFlag.AlignLeft,
                1: Qt.AlignmentFlag.AlignRight,
                2: Qt.AlignmentFlag.AlignRight,
                3: Qt.AlignmentFlag.AlignRight,
            },
        )
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setShowGrid(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        dar_ancho_a_texto(self.tabla)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tabla.setStyleSheet(TABLE_QSS)
        derecha = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        for fila, linea in enumerate(lineas):
            nombre = f"{linea['codigo']} - {linea['nombre']}" if linea["codigo"] else linea["nombre"]
            item_nombre = QTableWidgetItem(nombre)
            if linea["descripcion"]:
                item_nombre.setToolTip(linea["descripcion"])
            self.tabla.setItem(fila, 0, item_nombre)
            valores = (
                f"{linea['cantidad']:,.2f} {_tipo(linea['tipo_venta'])}",
                f"${linea['precio_unitario']:,.2f}",
                f"${linea['subtotal']:,.2f}",
            )
            for columna, texto in enumerate(valores, start=1):
                item = QTableWidgetItem(texto)
                item.setTextAlignment(derecha)
                self.tabla.setItem(fila, columna, item)
        return self.tabla

    def _pie(self) -> QHBoxLayout:
        fila = QHBoxLayout()
        self.lbl_total = QLabel(f"Total: ${self.datos['total']:,.2f}")
        self.lbl_total.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        cerrar = QPushButton("Cerrar")
        cerrar.setIcon(qta.icon("fa5s.times", color=COLOR_TEXT_DARK))
        cerrar.setStyleSheet(BUTTON_SECONDARY_QSS)
        cerrar.clicked.connect(self.accept)
        fila.addWidget(self.lbl_total)
        fila.addStretch()
        fila.addWidget(cerrar)
        return fila
