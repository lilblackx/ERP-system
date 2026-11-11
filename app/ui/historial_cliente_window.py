"""Ventana para mostrar el historial de facturas y pagos de un cliente. Misma paleta y
plantilla que app/ui/factura_form_dialog.py (DIALOG_STYLE, tarjetas SectionCard,
encabezado con icono + titulo/subtitulo) -- antes tenia su propio fondo azul solido que
no combinaba con el resto de dialogos de la app."""

import logging
from datetime import date, datetime
from decimal import Decimal

import qtawesome as qta
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.db.models import Cliente
from app.services.exportacion import exportar_excel, exportar_pdf
from app.services.historial_cliente import (
    ETIQUETAS_VISTA,
    VISTA_FACTURAS,
    VISTA_PAGOS,
    VISTA_TODOS,
    filtrar_historial,
    monto_para_vista,
    obtener_historial_cliente,
    obtener_saldo_total_pendiente,
    obtener_saldo_total_positivo,
    total_pagado,
)
from app.services.notas_credito import NotaCreditoService
from app.services.permisos import PermisoDenegadoError
from app.ui.animaciones import liberar_boton, ocupar_boton
from app.ui.aplicar_nota_credito_dialog import AplicarNotaCreditoDialog
from app.ui.carga_asincrona import CargaAsincronaMixin
from app.ui.devolver_nota_credito_dialog import DevolverNotaCreditoDialog
from app.ui.factura_detalle_dialog import FacturaDetalleDialog, tarea_cargar_factura
from app.ui.message_box import MessageBox
from app.ui.pantalla import ajustar_tamano
from app.ui.permisos_ui import MixinPermisos
from app.ui.styles import (
    COLOR_BLUE_LIGHTER,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_FIELD_BG,
    COLOR_INFO_BG,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MEDIUM,
    COLOR_TEXT_MUTED,
    FONT_FAMILY,
    TABLE_QSS,
    alinear_encabezados,
    aplicar_sombra,
    dar_ancho_a_texto,
)
from app.ui.workers import QueryWorker

logger = logging.getLogger(__name__)


def _etiqueta_metodo_pago(valor: str | None) -> str:
    """ "mixto" es el sentinel que obtener_historial_cliente() usa cuando una factura tuvo
    mas de una forma de pago con metodo distinto -- se traduce aca para no mostrar el
    valor crudo en la tabla/exportacion (mismo criterio que facturacion_panel.py)."""
    return "Mixto" if valor == "mixto" else (valor or "—")


# Metodo de VUELTO (cambio), catalogo distinto de metodo de pago -- ver METODOS_VUELTO en
# factura_form_dialog.py y _ETIQUETAS_METODO_VUELTO en factura_detalle_dialog.py.
# Duplicado aca a proposito (3 valores fijos).
_ETIQUETAS_METODO_VUELTO = {
    "efectivo": "Efectivo",
    "pago_movil": "Pago Móvil",
    "transferencia": "Transferencia",
}


def _texto_vuelto(item: dict) -> str:
    if not item["monto_vuelto"] or float(item["monto_vuelto"]) <= 0:
        return "—"
    etiqueta = _ETIQUETAS_METODO_VUELTO.get(item["metodo_vuelto"], item["metodo_vuelto"])
    return f"${float(item['monto_vuelto']):,.2f} ({etiqueta})"


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
QPushButton#BtnSecondary {{
    background-color: {COLOR_FIELD_BG};
    color: {COLOR_TEXT_MEDIUM};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#BtnSecondary:hover {{
    background-color: {COLOR_TABLE_HEADER};
    color: {COLOR_TEXT_DARK};
}}
"""

# Columnas de la tabla de historial
COLS_HISTORIAL = [
    "Tipo",
    "N° Factura/Nota",
    "Fecha",
    "Estado",
    "Condición Pago",
    "Método Pago",
    "Días",
    "Observaciones",
    "Monto",
    "Pagado",
    "Saldo Factura",
    "Saldo Corrido",
]

# Etiqueta de cada tipo de fila (misma en la tabla y en la exportacion).
ETIQUETAS_TIPO = {
    "factura": "Factura",
    "pago": "Abono",
    "nota_credito": "Nota Crédito",
    "devolucion_nota_credito": "Devolución NC",
}

# Anchos relativos de las columnas en el PDF (12 columnas: Observaciones es la mas ancha).
COL_WIDTHS_PDF = [0.9, 1.2, 1.3, 0.9, 0.9, 0.9, 0.5, 2.0, 1.0, 1.0, 1.0, 1.0]


def _filas_historial_para_exportar(session, id_cliente: int, vista: str = VISTA_TODOS) -> list[list]:
    """Filas del historial para Excel/PDF, SOLO las de `vista` (la misma que el usuario ve en pantalla).
    Los montos van como Decimal (numeros), no como texto."""
    historial = filtrar_historial(obtener_historial_cliente(session, id_cliente), vista)
    filas = []
    for item in historial:
        tipo = item["tipo_transaccion"]
        es_factura = tipo == "factura"

        # Dias transcurridos desde la fecha de emision (solo facturas)
        dias_transcurridos = "—"
        if es_factura and item["fecha"]:
            try:
                fecha_emision = datetime.strptime(item["fecha"], "%Y-%m-%d %H:%M").date()
                dias_transcurridos = str((date.today() - fecha_emision).days)
            except Exception:
                dias_transcurridos = "—"

        estado = item["estado_factura"] if tipo in ("factura", "nota_credito", "devolucion_nota_credito") else "—"

        filas.append(
            [
                ETIQUETAS_TIPO.get(tipo, tipo),
                item["numero_factura"],
                item["fecha"],
                estado,
                item["condicion_pago"] if es_factura else "—",
                _etiqueta_metodo_pago(item["metodo_pago"]) if tipo in ("factura", "pago") else "—",
                dias_transcurridos,
                item["observaciones"] or "",
                # Numeros reales (Decimal), NO str(): con texto, los abonos ("-100.00") llegaban a Excel como
                # texto y el escritor los alteraba; asi conservan su signo y se pueden sumar.
                monto_para_vista(item, vista),
                item["monto_pagado"] if es_factura else None,
                item["saldo_factura"] if es_factura else None,
                None if tipo == "pago" else item["saldo_corrido"],
            ]
        )
    return filas


def _titulo_excel_historial(cliente_nombre: str | None, vista: str) -> str:
    cliente = ": " + cliente_nombre if cliente_nombre else ""
    return "Historial del Cliente" + cliente + " - " + ETIQUETAS_VISTA[vista]


def _tarea_exportar_historial_excel(session, ruta: str, id_cliente: int, vista: str, cliente_nombre: str | None) -> str:
    """Corre en un QThread aparte (QueryWorker) -- consultar y volcar el historial
    completo del cliente a un archivo (openpyxl) es lo bastante lento como para
    congelar la ventana si se hace en el hilo de GUI."""
    filas = _filas_historial_para_exportar(session, id_cliente, vista)
    exportar_excel(ruta, COLS_HISTORIAL, filas, titulo=_titulo_excel_historial(cliente_nombre, vista))
    return ruta


def _tarea_exportar_historial_pdf(session, ruta: str, id_cliente: int, vista: str, cliente_nombre: str | None) -> str:
    filas = _filas_historial_para_exportar(session, id_cliente, vista)
    exportar_pdf(
        ruta,
        "Historial del Cliente",
        COLS_HISTORIAL,
        filas,
        cliente_nombre=cliente_nombre,
        filtros={"Vista": ETIQUETAS_VISTA[vista]},
        col_widths=COL_WIDTHS_PDF,
    )
    return ruta


def _tarea_historial_cliente(session, id_cliente: int, id_usuario: int | None) -> dict:
    """Corre en un hilo aparte (ver carga_asincrona.py): historial, saldos y notas de credito del cliente en una sola
    pasada. Sin 'notas_credito'/'ver' simplemente no hay notas (no es un error)."""
    historial = obtener_historial_cliente(session, id_cliente)
    saldo_total = obtener_saldo_total_pendiente(session, id_cliente)
    saldo_positivo = obtener_saldo_total_positivo(session, id_cliente)
    try:
        notas = NotaCreditoService.listar_notas_credito_cliente(session, id_cliente, id_usuario=id_usuario)
    except PermisoDenegadoError:
        notas = []
    return {"historial": historial, "saldo_total": saldo_total, "saldo_positivo": saldo_positivo, "notas": notas}


class HistorialClienteWindow(CargaAsincronaMixin, MixinPermisos, QDialog):
    """Ventana que muestra el historial de facturas y pagos de un cliente."""

    recurso_permisos = "notas_credito"

    def __init__(
        self,
        session_factory,
        id_cliente: int,
        cliente: Cliente,
        id_usuario: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.session_factory = session_factory
        self.id_cliente = id_cliente
        self.cliente = cliente
        self.id_usuario = id_usuario
        # Notas de credito disponibles del cliente y facturas con saldo pendiente --
        # pobladas en cargar_historial(), usadas para habilitar los botones de aplicar/
        # devolver y para armar las listas de AplicarNotaCreditoDialog/
        # DevolverNotaCreditoDialog (ver NotaCreditoService).
        self._notas_disponibles: list = []
        self._facturas_pendientes: list[dict] = []
        # Historial completo cargado + vista activa. Por defecto se ocultan los abonos (los pagos se ven en
        # "Solo pagos" o "Todos los movimientos"); la tabla y las exportaciones muestran solo la vista activa.
        self._historial: list = []
        self._vista: str = VISTA_FACTURAS
        # Guard anti-reentrancia para ver_detalle_factura() -- ver bancos_panel.py para
        # el motivo (hallazgo 3.3, auditoria 2026-09-05).
        self._abriendo_dialogo = False
        self.setWindowTitle(f"Historial - {cliente.nombre_razon_social}")
        ajustar_tamano(self, 1400, 700, 1400, 700)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.WindowCloseButtonHint & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self._setup_ui()
        self.cargar_historial()

    def showEvent(self, event: QShowEvent) -> None:
        # Mismo artefacto de primer pintado (Windows/DWM) que factura_form_dialog.py --
        # ver su showEvent para el detalle. Esta ventana tiene la misma combinacion de
        # tarjetas con sombra + tabla que lo dispara.
        super().showEvent(event)
        QTimer.singleShot(0, self.update)

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # Header con información del cliente
        root.addWidget(self._make_header())

        # Resumen de saldo pendiente
        root.addWidget(self._make_saldo_pendiente())

        # Tabla de historial
        root.addWidget(self._make_table())

        # Footer con botón cerrar
        root.addLayout(self._make_footer())

    def _make_header(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.history", color=COLOR_PRIMARY).pixmap(QSize(22, 22)))
        icon_lbl.setStyleSheet(
            f"background-color: {COLOR_INFO_BG}; border: 1.5px solid "
            f"{COLOR_BLUE_LIGHTER}; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(38, 38)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titulos = QVBoxLayout()
        titulos.setSpacing(1)
        titulos.setContentsMargins(0, 0, 0, 0)
        lbl_titulo = QLabel("Historial del Cliente")
        lbl_titulo.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        lbl_subtitulo = QLabel(self.cliente.nombre_razon_social or "")
        lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        titulos.addWidget(lbl_titulo)
        titulos.addWidget(lbl_subtitulo)

        lbl_vista = QLabel("Ver:")
        lbl_vista.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_MEDIUM};")
        self.vista_combo = QComboBox()
        for clave in (VISTA_FACTURAS, VISTA_TODOS, VISTA_PAGOS):
            self.vista_combo.addItem(ETIQUETAS_VISTA[clave], clave)
        self.vista_combo.setFixedHeight(34)
        self.vista_combo.setMinimumWidth(230)
        self.vista_combo.setToolTip("Qué movimientos mostrar. La exportación (Excel/PDF) sigue la vista elegida.")
        self.vista_combo.currentIndexChanged.connect(self._on_vista_cambiada)

        h.addWidget(icon_lbl)
        h.addLayout(titulos)
        h.addStretch()
        h.addWidget(lbl_vista)
        h.addWidget(self.vista_combo)
        return w

    def _make_saldo_pendiente(self) -> QWidget:
        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        h = QHBoxLayout(card)
        h.setContentsMargins(16, 14, 16, 14)
        h.setSpacing(10)

        lbl_icono = QLabel()
        lbl_icono.setPixmap(qta.icon("fa5s.wallet", color=COLOR_PRIMARY).pixmap(20, 20))
        lbl_icono.setStyleSheet("background: transparent;")

        self.lbl_saldo_pendiente = QLabel("Cargando saldo...")
        self.lbl_saldo_pendiente.setStyleSheet(f"color: {COLOR_TEXT_DARK}; font-size: 15px; font-weight: bold;")

        # Saldo positivo (notas de crédito disponibles)
        self.lbl_saldo_positivo = QLabel()
        self.lbl_saldo_positivo.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: 14px; font-weight: 600;")
        self.lbl_saldo_positivo.hide()

        # Notas de credito disponibles -- solo visible si el cliente tiene alguna (ver
        # cargar_historial). Antes no habia ningun indicio en la app de que un cliente
        # tuviera saldo a favor sin consumir.
        self.lbl_notas_credito = QLabel()
        self.lbl_notas_credito.setStyleSheet(f"color: {COLOR_PRIMARY}; font-size: 12px; font-weight: 600;")
        self.lbl_notas_credito.hide()

        # Total de abonos -- solo visible en la vista "Solo pagos".
        self.lbl_total_pagado = QLabel()
        self.lbl_total_pagado.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: 14px; font-weight: 600;")
        self.lbl_total_pagado.hide()

        h.addWidget(lbl_icono)
        h.addWidget(self.lbl_saldo_pendiente)
        h.addSpacing(16)
        h.addWidget(self.lbl_saldo_positivo)
        h.addWidget(self.lbl_notas_credito)
        h.addWidget(self.lbl_total_pagado)
        h.addStretch()
        return card

    def _make_table(self) -> QTableWidget:
        self.tabla = QTableWidget(0, len(COLS_HISTORIAL))
        self.tabla.setHorizontalHeaderLabels(COLS_HISTORIAL)
        alinear_encabezados(
            self.tabla,
            {
                0: Qt.AlignmentFlag.AlignCenter,
                1: Qt.AlignmentFlag.AlignCenter,
                2: Qt.AlignmentFlag.AlignCenter,
                3: Qt.AlignmentFlag.AlignCenter,
                4: Qt.AlignmentFlag.AlignCenter,
                5: Qt.AlignmentFlag.AlignCenter,
                6: Qt.AlignmentFlag.AlignCenter,
                7: Qt.AlignmentFlag.AlignLeft,
                8: Qt.AlignmentFlag.AlignRight,
                9: Qt.AlignmentFlag.AlignRight,
                10: Qt.AlignmentFlag.AlignRight,
                11: Qt.AlignmentFlag.AlignRight,
            },
        )
        self.tabla.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setShowGrid(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabla.doubleClicked.connect(self.ver_detalle_factura)
        # Todas se ajustan a su contenido salvo Observaciones, que absorbe el ancho que sobra.
        dar_ancho_a_texto(self.tabla, 7)
        self.tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(self.tabla)
        self.tabla.verticalHeader().setDefaultSectionSize(45)
        return self.tabla

    def _make_footer(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setContentsMargins(0, 4, 0, 0)
        h.setSpacing(10)
        h.addStretch()

        btn_detalle = QPushButton("Ver detalle")
        btn_detalle.setIcon(qta.icon("fa5s.eye", color=COLOR_TEXT_DARK))
        btn_detalle.setObjectName("BtnSecondary")
        btn_detalle.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_detalle.setAutoDefault(False)
        btn_detalle.clicked.connect(self.ver_detalle_factura)

        self.btn_exportar_excel = QPushButton("Exportar Excel")
        self.btn_exportar_excel.setIcon(qta.icon("fa5s.file-excel", color=COLOR_SUCCESS))
        self.btn_exportar_excel.setObjectName("BtnSecondary")
        self.btn_exportar_excel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_exportar_excel.setAutoDefault(False)
        self.btn_exportar_excel.clicked.connect(self.exportar_excel)

        self.btn_exportar_pdf = QPushButton("Exportar PDF")
        self.btn_exportar_pdf.setIcon(qta.icon("fa5s.file-pdf", color=COLOR_DANGER))
        self.btn_exportar_pdf.setObjectName("BtnSecondary")
        self.btn_exportar_pdf.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_exportar_pdf.setAutoDefault(False)
        self.btn_exportar_pdf.clicked.connect(self.exportar_pdf)

        # Deshabilitados hasta que cargar_historial() confirme que hay notas
        # disponibles/facturas con saldo pendiente (ver _actualizar_notas_credito) -- sin
        # eso no hay nada que aplicar ni devolver.
        self.btn_aplicar_nota = QPushButton("Aplicar Nota de Crédito")
        self.btn_aplicar_nota.setIcon(qta.icon("fa5s.exchange-alt", color=COLOR_PRIMARY))
        self.btn_aplicar_nota.setObjectName("BtnSecondary")
        self.btn_aplicar_nota.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_aplicar_nota.setAutoDefault(False)
        self.btn_aplicar_nota.setEnabled(False)
        self.btn_aplicar_nota.clicked.connect(self.aplicar_nota_credito)

        self.btn_devolver_nota = QPushButton("Devolver Nota de Crédito")
        self.btn_devolver_nota.setIcon(qta.icon("fa5s.hand-holding-usd", color=COLOR_PRIMARY))
        self.btn_devolver_nota.setObjectName("BtnSecondary")
        self.btn_devolver_nota.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_devolver_nota.setAutoDefault(False)
        self.btn_devolver_nota.setEnabled(False)
        self.btn_devolver_nota.clicked.connect(self.devolver_nota_credito)

        # Estilo propio (no #BtnPrimary del DIALOG_STYLE de la ventana): con el boton
        # dentro de un QHBoxLayout agregado directo al layout raiz (sin envolverlo en un
        # QWidget contenedor), la regla en cascada #BtnPrimary no pintaba su
        # background-color en Windows (aunque el borde y el texto si se veian) -- fijar
        # el QSS completo en el propio boton evita depender de esa cascada.
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setIcon(qta.icon("fa5s.times", color=COLOR_PRIMARY))
        btn_cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cerrar.setAutoDefault(False)
        btn_cerrar.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_CARD_BG};
                color: {COLOR_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: 6px;
                padding: 8px 18px;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {COLOR_TABLE_HEADER};
            }}
        """)
        btn_cerrar.clicked.connect(self.accept)

        h.addWidget(btn_detalle)
        if self._puede("crear"):
            h.addWidget(self.btn_aplicar_nota)
        if self._puede("crear"):
            h.addWidget(self.btn_devolver_nota)
        h.addWidget(self.btn_exportar_excel)
        h.addWidget(self.btn_exportar_pdf)
        h.addWidget(btn_cerrar)
        return h

    def cargar_historial(self, silencioso: bool = False, sincrono: bool = False) -> None:
        # Un fallo ya no deja la tabla vacia y "Cargando saldo..." congelado en silencio: carga_asincrona avisa
        # con "Error de conexion" (un error de conexion no debe verse igual que "sin facturas").
        self.cargar_async(
            "historial",
            _tarea_historial_cliente,
            self._mostrar_historial,
            texto_error="No se pudo cargar el historial del cliente.",
            silencioso=silencioso,
            sincrono=sincrono,
            id_cliente=self.id_cliente,
            id_usuario=self.id_usuario,
        )

    def _mostrar_historial(self, datos: dict) -> None:
        historial = datos["historial"]
        self._historial = historial
        self._aplicar_vista()

        saldo_total = datos["saldo_total"]
        self.lbl_saldo_pendiente.setText(f"SALDO PENDIENTE : $ {float(saldo_total):,.2f}")

        # Color del saldo según si está vencido o no
        if saldo_total > 0:
            self.lbl_saldo_pendiente.setStyleSheet(f"color: {COLOR_DANGER}; font-size: 16px; font-weight: bold;")
        else:
            self.lbl_saldo_pendiente.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: 16px; font-weight: bold;")

        # Saldo total positivo (notas de crédito disponibles)
        saldo_positivo = datos["saldo_positivo"]
        if saldo_positivo > 0:
            self.lbl_saldo_positivo.setText(f"SALDO A FAVOR : $ {float(saldo_positivo):,.2f}")
            self.lbl_saldo_positivo.show()
        else:
            self.lbl_saldo_positivo.hide()

        self._actualizar_notas_credito(datos["notas"], historial)

    def _on_vista_cambiada(self) -> None:
        self._vista = self.vista_combo.currentData() or VISTA_FACTURAS
        self._aplicar_vista()

    def _aplicar_vista(self) -> None:
        """Pinta en la tabla solo las filas de la vista activa. El historial completo (`self._historial`) no se
        toca: los saldos, las notas de credito y el boton de aplicar se calculan siempre con todo."""
        self._poblar_tabla(filtrar_historial(self._historial, self._vista))
        if self._vista == VISTA_PAGOS:
            self.lbl_total_pagado.setText(f"TOTAL PAGADO : $ {float(total_pagado(self._historial)):,.2f}")
            self.lbl_total_pagado.show()
        else:
            self.lbl_total_pagado.hide()

    def _actualizar_notas_credito(self, notas: list, historial: list) -> None:
        """Notas de credito disponibles del cliente + facturas del historial con saldo
        pendiente -- habilita los botones de aplicar/devolver y arma las listas que
        consumen AplicarNotaCreditoDialog/DevolverNotaCreditoDialog. `notas` ya viene vacia
        si el usuario no tiene 'notas_credito'/'ver' (no ve la funcionalidad, no un error)."""
        self._notas_disponibles = [n for n in notas if n.estado == "disponible" and n.saldo_disponible > 0]

        self._facturas_pendientes = [
            {
                "id_factura": item["id_factura"],
                "numero_factura": item["numero_factura"],
                "saldo_pendiente": (item["saldo_corrido"] if item["saldo_corrido"] > 0 else Decimal("0.00")),
            }
            for item in historial
            if (
                item["tipo_transaccion"] == "factura"
                and item["saldo_corrido"] > 0
                and item["estado_factura"] != "ANULADA"
            )
        ]

        hay_notas = bool(self._notas_disponibles)
        self.btn_devolver_nota.setEnabled(hay_notas)
        self.btn_aplicar_nota.setEnabled(hay_notas and bool(self._facturas_pendientes))

        if hay_notas:
            total_disponible = sum(float(n.saldo_disponible) for n in self._notas_disponibles)
            self.lbl_notas_credito.setText(f"Notas de crédito disponibles: ${total_disponible:,.2f}")
            self.lbl_notas_credito.show()
        else:
            self.lbl_notas_credito.hide()

    def aplicar_nota_credito(self) -> None:
        if not self._exigir_permiso("crear", "No tienes permiso para aplicar notas de crédito."):
            return
        session = self.session_factory()
        try:
            dialogo = AplicarNotaCreditoDialog(
                session,
                self.id_usuario,
                self._notas_disponibles,
                self._facturas_pendientes,
                parent=self,
            )
            if dialogo.exec() == QDialog.DialogCode.Accepted:
                MessageBox.information(
                    self,
                    "Nota de crédito aplicada",
                    "La nota de crédito se aplicó con éxito.",
                )
                self.cargar_historial()
        finally:
            session.close()

    def devolver_nota_credito(self) -> None:
        if not self._exigir_permiso("crear", "No tienes permiso para devolver notas de crédito."):
            return
        session = self.session_factory()
        try:
            dialogo = DevolverNotaCreditoDialog(session, self.id_usuario, self._notas_disponibles, parent=self)
            if dialogo.exec() == QDialog.DialogCode.Accepted:
                MessageBox.information(
                    self,
                    "Nota de crédito devuelta",
                    "La devolución se registró con éxito.",
                )
                self.cargar_historial()
        finally:
            session.close()

    def _poblar_tabla(self, historial: list) -> None:
        self.tabla.setRowCount(len(historial))

        for fila, item in enumerate(historial):
            # Tipo de transacción (Factura, Pago, Nota Crédito o Devolución)
            tipo = item["tipo_transaccion"]
            if tipo == "factura":
                color = QColor(COLOR_DANGER)
            elif tipo == "pago":
                color = QColor(COLOR_SUCCESS)
            elif tipo == "nota_credito":
                color = QColor(COLOR_PRIMARY)
            elif tipo == "devolucion_nota_credito":
                color = QColor("#FF9800")  # Naranja para devoluciones
            else:
                color = QColor(COLOR_TEXT_DARK)
            tipo_label = ETIQUETAS_TIPO.get(tipo, tipo)

            item_tipo = QTableWidgetItem(tipo_label)
            item_tipo.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            item_tipo.setData(Qt.ItemDataRole.ForegroundRole, color)
            # Datos de la fila: con filas ocultas por la vista, el numero de fila de la tabla ya no coincide con
            # el indice del historial, asi que el detalle de factura sale de aqui y no de la posicion.
            item_tipo.setData(Qt.ItemDataRole.UserRole, {"tipo": tipo, "id_factura": item["id_factura"]})
            self.tabla.setItem(fila, 0, item_tipo)

            # N° Factura/Nota
            item_factura = QTableWidgetItem(item["numero_factura"])
            item_factura.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 1, item_factura)

            # Fecha
            item_fecha = QTableWidgetItem(item["fecha"])
            item_fecha.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 2, item_fecha)

            # Estado
            if tipo == "factura":
                estado = item["estado_factura"] or ""
            elif tipo in ("nota_credito", "devolucion_nota_credito"):
                estado = item["estado_factura"] or ""
            else:
                estado = ""
            item_estado = QTableWidgetItem(estado)
            item_estado.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 3, item_estado)

            # Condición Pago (solo para facturas)
            if tipo == "factura":
                item_condicion = QTableWidgetItem(item["condicion_pago"] or "")
            else:
                item_condicion = QTableWidgetItem("—")
            item_condicion.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 4, item_condicion)

            # Método Pago (solo para facturas y pagos)
            if tipo in ("factura", "pago"):
                metodo_pago = _etiqueta_metodo_pago(item["metodo_pago"])
            elif tipo in ("nota_credito", "devolucion_nota_credito"):
                metodo_pago = "—"
            else:
                metodo_pago = "—"
            item_metodo = QTableWidgetItem(metodo_pago)
            item_metodo.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 5, item_metodo)

            # Días transcurridos desde la fecha de emisión
            dias_transcurridos = "—"
            if tipo == "factura" and item["fecha"]:
                try:
                    fecha_emision = datetime.strptime(item["fecha"], "%Y-%m-%d %H:%M").date()
                    fecha_actual = date.today()
                    dias_calc = (fecha_actual - fecha_emision).days
                    dias_transcurridos = str(dias_calc)
                except Exception as e:
                    logger.exception("Error calculando días transcurridos: %s", e)
                    dias_transcurridos = "—"
            elif tipo in ("pago", "nota_credito", "devolucion_nota_credito"):
                dias_transcurridos = "—"

            item_dias = QTableWidgetItem(dias_transcurridos)
            item_dias.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 6, item_dias)

            # Observaciones
            item_observaciones = QTableWidgetItem(item["observaciones"] or "")
            item_observaciones.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 7, item_observaciones)

            # Monto: positivo para facturas; los abonos van en negativo (restan del saldo) salvo en la vista
            # "Solo pagos", donde son pagos y se muestran en positivo.
            monto_visible = monto_para_vista(item, self._vista)
            monto = f"${float(monto_visible):,.2f}"
            item_monto = QTableWidgetItem(monto)
            item_monto.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if tipo == "pago" or item["monto"] < 0:
                item_monto.setData(Qt.ItemDataRole.ForegroundRole, QColor(COLOR_SUCCESS))
            else:
                item_monto.setData(Qt.ItemDataRole.ForegroundRole, QColor(COLOR_DANGER))
            font = item_monto.font()
            font.setBold(True)
            item_monto.setFont(font)
            self.tabla.setItem(fila, 8, item_monto)

            # Pagado / Saldo Factura (solo facturas): al ocultar los abonos sigue viendose cuanto se pago de
            # cada factura y cuanto falta.
            es_factura = tipo == "factura"
            item_pagado = QTableWidgetItem(f"${float(item['monto_pagado']):,.2f}" if es_factura else "—")
            item_pagado.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if es_factura and item["monto_pagado"] > 0:
                item_pagado.setData(Qt.ItemDataRole.ForegroundRole, QColor(COLOR_SUCCESS))
            self.tabla.setItem(fila, 9, item_pagado)

            item_saldo_factura = QTableWidgetItem(f"${float(item['saldo_factura']):,.2f}" if es_factura else "—")
            item_saldo_factura.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if es_factura:
                item_saldo_factura.setData(
                    Qt.ItemDataRole.ForegroundRole,
                    QColor(COLOR_DANGER if item["saldo_factura"] > 0 else COLOR_SUCCESS),
                )
            self.tabla.setItem(fila, 10, item_saldo_factura)

            # Saldo Corrido (no aplica a un abono suelto)
            saldo_corrido = "—" if tipo == "pago" else f"${float(item['saldo_corrido']):,.2f}"
            item_corrido = QTableWidgetItem(saldo_corrido)
            item_corrido.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if item["saldo_corrido"] > 0:
                item_corrido.setData(Qt.ItemDataRole.ForegroundRole, QColor(COLOR_DANGER))
            else:
                item_corrido.setData(Qt.ItemDataRole.ForegroundRole, QColor(COLOR_SUCCESS))
            font_corrido = item_corrido.font()
            font_corrido.setBold(True)
            item_corrido.setFont(font_corrido)
            self.tabla.setItem(fila, 11, item_corrido)

    def exportar_excel(self) -> None:
        session = self.session_factory()
        try:
            nombre_archivo = f"historial_{self.cliente.nombre_razon_social or 'cliente'}_{self._vista}"
            ruta, _ = QFileDialog.getSaveFileName(
                self,
                "Exportar Historial a Excel",
                f"{nombre_archivo}.xlsx",
                "Excel (*.xlsx)",
            )
            if not ruta:
                return

            ocupar_boton(self.btn_exportar_excel)
            self._worker_export_excel = QueryWorker(
                self.session_factory,
                _tarea_exportar_historial_excel,
                ruta=ruta,
                id_cliente=self.id_cliente,
                vista=self._vista,
                cliente_nombre=self.cliente.nombre_razon_social,
            )
            self._worker_export_excel.resultado.connect(self._on_exportar_excel_ok)
            self._worker_export_excel.error.connect(self._on_exportar_excel_error)
            self._worker_export_excel.start()
        finally:
            session.close()

    def exportar_pdf(self) -> None:
        session = self.session_factory()
        try:
            nombre_archivo = f"historial_{self.cliente.nombre_razon_social or 'cliente'}_{self._vista}"
            ruta, _ = QFileDialog.getSaveFileName(
                self, "Exportar Historial a PDF", f"{nombre_archivo}.pdf", "PDF (*.pdf)"
            )
            if not ruta:
                return

            ocupar_boton(self.btn_exportar_pdf)
            self._worker_export_pdf = QueryWorker(
                self.session_factory,
                _tarea_exportar_historial_pdf,
                ruta=ruta,
                id_cliente=self.id_cliente,
                vista=self._vista,
                cliente_nombre=self.cliente.nombre_razon_social,
            )
            self._worker_export_pdf.resultado.connect(self._on_exportar_pdf_ok)
            self._worker_export_pdf.error.connect(self._on_exportar_pdf_error)
            self._worker_export_pdf.start()
        finally:
            session.close()

    def _on_exportar_excel_ok(self, ruta: str) -> None:
        liberar_boton(self.btn_exportar_excel)
        MessageBox.information(self, "Exportación completa", f"Se exportó el historial a:\n{ruta}")

    def _on_exportar_excel_error(self, mensaje: str) -> None:
        liberar_boton(self.btn_exportar_excel)
        logger.error("Fallo al exportar historial a Excel: %s", mensaje)
        MessageBox.critical(self, "Error", "No se pudo exportar el historial a Excel.")

    def _on_exportar_pdf_ok(self, ruta: str) -> None:
        liberar_boton(self.btn_exportar_pdf)
        MessageBox.information(self, "Exportación completa", f"Se exportó el historial a:\n{ruta}")

    def _on_exportar_pdf_error(self, mensaje: str) -> None:
        liberar_boton(self.btn_exportar_pdf)
        logger.error("Fallo al exportar historial a PDF: %s", mensaje)
        MessageBox.critical(self, "Error", "No se pudo exportar el historial a PDF.")

    def _fila_seleccionada_id_factura(self) -> int | None:
        """Id de la factura de la fila seleccionada: la propia factura o la factura a la que se abono (en la
        vista "Solo pagos" no hay facturas, y abrir la del pago es lo natural). Sale de los datos guardados en
        la fila, no de su posicion: con filas ocultas por la vista el indice de la tabla no coincide con el
        del historial."""
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            MessageBox.information(self, "Selección requerida", "Selecciona una factura o un pago de la lista.")
            return None
        celda = self.tabla.item(filas[0].row(), 0)
        datos = celda.data(Qt.ItemDataRole.UserRole) if celda is not None else None
        if not datos:
            logger.warning("Fila seleccionada sin datos de factura (fila %d)", filas[0].row())
            return None
        if datos["tipo"] in ("factura", "pago") and datos["id_factura"]:
            return datos["id_factura"]
        MessageBox.information(self, "Selección inválida", "Selecciona una factura o un pago, no una nota de crédito.")
        return None

    def ver_detalle_factura(self) -> None:
        id_factura = self._fila_seleccionada_id_factura()
        if id_factura is None:
            return
        if self._abriendo_dialogo:
            return
        self._abriendo_dialogo = True
        # La factura se consulta en un hilo aparte (ver carga_asincrona.py); el dialogo se abre al llegar.
        self.cargar_async(
            "detalle_factura",
            tarea_cargar_factura,
            self._abrir_detalle_factura,
            texto_error="No se pudo cargar el detalle de la factura.",
            session_factory=self.session_factory,
            id_factura=id_factura,
            id_usuario=self.id_usuario,
        )

    def _abrir_detalle_factura(self, cargado: dict) -> None:
        session = cargado.get("session")
        error = cargado.get("error")
        try:
            if isinstance(error, PermisoDenegadoError):
                MessageBox.warning(self, "Sin permiso", "No tienes permiso para ver el detalle de facturas.")
            elif isinstance(error, ValueError):
                MessageBox.warning(self, "No se pudo abrir la factura", str(error))
            elif error is not None:
                logger.error("Fallo al cargar el detalle de la factura", exc_info=error)
                MessageBox.critical(self, "Error", "No se pudo cargar el detalle de la factura.")
            else:
                FacturaDetalleDialog(cargado["datos"], session, self.id_usuario, parent=self).exec()
        except Exception:
            logger.exception("Fallo al abrir el detalle de la factura")
            MessageBox.critical(self, "Error", "No se pudo cargar el detalle de la factura.")
        finally:
            if session is not None:
                session.close()
            self._abriendo_dialogo = False
