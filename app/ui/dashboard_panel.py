"""
Panel general (dashboard de inicio): KPIs consolidados, ventas de la semana,
cajas activas, facturas recientes e inventario en alerta.
Primera pantalla que ve el usuario tras iniciar sesión.
"""

import logging
import socket
from datetime import datetime

import qtawesome as qta
from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QShowEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from app.db.models import Usuario
from app.services.dashboard import DashboardService
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    CARD_QSS,
    COLOR_BORDER,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_INFO,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_TEXT_DARK,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
    COLORES_ESTADO_FACTURA,
    aplicar_sombra,
    color_con_alpha,
)
from app.ui.workers import QueryWorker

logger = logging.getLogger(__name__)

DIAS_SEMANA = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def _tarea_panel_general(session, id_usuario):
    return DashboardService.get_panel_general_data(session, id_usuario=id_usuario)


def _card(inner: QWidget) -> QWidget:
    """Envuelve `inner` en un contenedor con el mismo QSS de tarjeta usado en
    el resto del sistema (`CARD_QSS`, ver clientes/inventario)."""
    contenedor = QWidget()
    contenedor.setObjectName("Card")
    contenedor.setStyleSheet(CARD_QSS)
    aplicar_sombra(contenedor)
    layout = QVBoxLayout(contenedor)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(inner)
    return contenedor


class KpiCard(QWidget):
    """Tarjeta de indicador: título + ícono + valor grande + detalle/delta."""

    def __init__(self, titulo: str, icono: str, color: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setStyleSheet(CARD_QSS)
        aplicar_sombra(self)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(8)

        top = QHBoxLayout()
        lbl_titulo = QLabel(titulo)
        lbl_titulo.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 12px; font-weight: 600; background: transparent; border: none;"
        )

        lbl_icono = QLabel()
        lbl_icono.setPixmap(qta.icon(icono, color=color).pixmap(15, 15))
        lbl_icono.setFixedSize(30, 30)
        lbl_icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_icono.setStyleSheet(f"background-color: {color_con_alpha(color)}; border-radius: 15px; border: none;")

        top.addWidget(lbl_titulo)
        top.addStretch()
        top.addWidget(lbl_icono)

        self.lbl_valor = QLabel("—")
        self.lbl_valor.setStyleSheet(
            f"font-size: 23px; font-weight: bold; color: {COLOR_TEXT_DARK}; background: transparent; border: none;"
        )

        self.lbl_detalle = QLabel("")
        self.lbl_detalle.setStyleSheet(
            f"font-size: 11px; color: {COLOR_TEXT_MUTED}; background: transparent; border: none;"
        )

        v.addLayout(top)
        v.addWidget(self.lbl_valor)
        v.addWidget(self.lbl_detalle)

    def set_valor(self, texto: str) -> None:
        self.lbl_valor.setText(texto)

    def set_detalle(self, texto: str, color: str = COLOR_TEXT_MUTED) -> None:
        self.lbl_detalle.setStyleSheet(
            f"font-size: 11px; font-weight: bold; color: {color}; background: transparent; border: none;"
        )
        self.lbl_detalle.setText(texto)


class VentasSemanaChart(QWidget):
    """Gráfico de línea (sin dependencias externas, dibujado con QPainter) para
    el total vendido por día en los últimos 7 días."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._puntos: list[dict] = []
        self.setMinimumHeight(200)

    def set_datos(self, puntos: list[dict]) -> None:
        self._puntos = puntos
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (nombre impuesto por Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        if not self._puntos:
            painter.setPen(QColor(COLOR_TEXT_LIGHT))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Sin ventas registradas esta semana")
            painter.end()
            return

        margen_izq, margen_der, margen_arriba, margen_abajo = 16, 16, 12, 8
        plot = QRectF(
            rect.left() + margen_izq,
            rect.top() + margen_arriba,
            rect.width() - margen_izq - margen_der,
            rect.height() - margen_arriba - margen_abajo,
        )

        montos = [float(p["monto"]) for p in self._puntos]
        maximo = max(montos) or 1.0
        n = len(self._puntos)
        paso_x = plot.width() / (n - 1) if n > 1 else 0.0

        puntos_xy = []
        for i, monto in enumerate(montos):
            x = plot.left() + paso_x * i
            frac = monto / maximo
            y = plot.bottom() - frac * plot.height()
            puntos_xy.append((x, y))

        # Área bajo la curva
        area = QPainterPath()
        area.moveTo(puntos_xy[0][0], plot.bottom())
        for x, y in puntos_xy:
            area.lineTo(x, y)
        area.lineTo(puntos_xy[-1][0], plot.bottom())
        area.closeSubpath()

        gradiente = QLinearGradient(0, plot.top(), 0, plot.bottom())
        gradiente.setColorAt(0.0, QColor(13, 71, 161, 80))
        gradiente.setColorAt(1.0, QColor(13, 71, 161, 0))
        painter.fillPath(area, gradiente)

        # Línea
        linea = QPainterPath()
        linea.moveTo(*puntos_xy[0])
        for x, y in puntos_xy[1:]:
            linea.lineTo(x, y)
        pluma = QPen(QColor(COLOR_PRIMARY))
        pluma.setWidthF(2.4)
        painter.setPen(pluma)
        painter.drawPath(linea)

        # Puntos
        painter.setBrush(QColor(COLOR_PRIMARY))
        painter.setPen(Qt.PenStyle.NoPen)
        for x, y in puntos_xy:
            painter.drawEllipse(QRectF(x - 3.5, y - 3.5, 7, 7))

        painter.end()


class EtiquetasDiasSemana(QWidget):
    """Fila de "Lun".."Dom" bajo VentasSemanaChart, como QLabel reales en vez de texto
    pintado a mano dentro de paintEvent -- el intento anterior (drawText posicionado a
    mano relativo a plot.bottom()) seguia sin verse en pantalla despues de dos rondas de
    ajuste de margenes/manejo de excepciones, asi que se delega el renderizado del texto
    a QLabel, que lo resuelve solo de forma confiable.

    El posicionamiento NO usa un QHBoxLayout con stretch: eso centra cada etiqueta en 7
    columnas de igual ancho, mientras que los puntos del grafico van de borde a borde
    (el punto 0 pegado al margen izquierdo, el punto 6 pegado al derecho -- ver
    VentasSemanaChart.paintEvent, `x = plot.left() + paso_x * i`). Con columnas iguales
    las etiquetas de los extremos quedan corridas hacia adentro y ya no coinciden con el
    pico real del grafico. Por eso aqui se replica exactamente la misma formula via
    setGeometry en un resizeEvent propio, usando los mismos margenes (16, 16)."""

    MARGEN_IZQ = 16
    MARGEN_DER = 16
    _ANCHO_ETIQUETA = 36

    def __init__(self, parent=None):
        super().__init__(parent)
        self._labels: list[QLabel] = []
        self.setContentsMargins(0, 0, 0, 4)
        self.setFixedHeight(18)
        for _ in range(7):
            lbl = QLabel("", self)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"font-size: 10px; color: {COLOR_TEXT_MUTED}; background: transparent; border: none;")
            self._labels.append(lbl)
        self._reposicionar()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposicionar()

    def _reposicionar(self) -> None:
        n = len(self._labels)
        ancho_disponible = self.width() - self.MARGEN_IZQ - self.MARGEN_DER
        paso_x = ancho_disponible / (n - 1) if n > 1 and ancho_disponible > 0 else 0.0
        alto = max(self.height(), 1)
        for i, lbl in enumerate(self._labels):
            centro_x = self.MARGEN_IZQ + paso_x * i
            lbl.setGeometry(round(centro_x - self._ANCHO_ETIQUETA / 2), 0, self._ANCHO_ETIQUETA, alto)

    def set_datos(self, puntos: list[dict]) -> None:
        for i, lbl in enumerate(self._labels):
            texto = ""
            if i < len(puntos):
                try:
                    texto = DIAS_SEMANA[puntos[i]["fecha"].weekday()]
                except Exception:
                    logger.exception("No se pudo calcular la etiqueta de dia para el punto %s del grafico semanal", i)
            lbl.setText(texto)
        self._reposicionar()


class ListaVaciaLabel(QLabel):
    def __init__(self, texto: str, parent=None):
        super().__init__(texto, parent)
        self.setStyleSheet(f"color: {COLOR_TEXT_LIGHT}; font-size: 12px; background: transparent; border: none;")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class FilaCaja(QWidget):
    def __init__(self, caja: dict, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 6, 0, 6)
        h.setSpacing(8)

        info = QVBoxLayout()
        info.setSpacing(0)
        lbl_nombre = QLabel(caja["nombre_caja"])
        lbl_nombre.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {COLOR_TEXT_DARK}; background: transparent; border: none;"
        )
        lbl_cajero = QLabel(caja["cajero"] or "Sin cajero asignado")
        lbl_cajero.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_MUTED}; background: transparent; border: none;")
        info.addWidget(lbl_nombre)
        info.addWidget(lbl_cajero)

        badge = QLabel("ABIERTA")
        badge.setStyleSheet(
            f"background-color: #DCFCE7; color: {COLOR_SUCCESS}; border-radius: 4px;"
            " padding: 2px 8px; font-size: 10px; font-weight: bold;"
        )

        h.addLayout(info)
        h.addStretch()
        h.addWidget(badge)


class FilaInventarioAlerta(QWidget):
    def __init__(self, producto: dict, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 6, 0, 6)
        h.setSpacing(8)

        info = QVBoxLayout()
        info.setSpacing(0)
        lbl_nombre = QLabel(producto["nombre_producto"])
        lbl_nombre.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {COLOR_TEXT_DARK}; background: transparent; border: none;"
        )
        lbl_categoria = QLabel(producto["categoria"] or "Sin categoría")
        lbl_categoria.setStyleSheet(
            f"font-size: 11px; color: {COLOR_TEXT_MUTED}; background: transparent; border: none;"
        )
        info.addWidget(lbl_nombre)
        info.addWidget(lbl_categoria)

        lbl_cantidad = QLabel(f"{float(producto['cantidad_unidad']):,.0f} und.")
        lbl_cantidad.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {COLOR_DANGER}; background: transparent; border: none;"
        )

        h.addLayout(info)
        h.addStretch()
        h.addWidget(lbl_cantidad)


class FilaFactura(QWidget):
    def __init__(self, factura: dict, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: transparent; border-bottom: 1px solid {COLOR_BORDER};")
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 8, 0, 8)
        h.setSpacing(8)

        lbl_numero = QLabel(factura["numero_factura"])
        lbl_numero.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {COLOR_TEXT_DARK}; background: transparent; border: none;"
        )
        lbl_numero.setFixedWidth(90)

        lbl_cliente = QLabel(factura["cliente"] or "Consumidor final")
        lbl_cliente.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_DARK}; background: transparent; border: none;")

        lbl_total = QLabel(f"${float(factura['total_venta']):,.2f}")
        lbl_total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl_total.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_DARK}; background: transparent; border: none;")
        lbl_total.setFixedWidth(90)

        estado = factura["estado_factura"] or "EMITIDA"
        color_estado = COLORES_ESTADO_FACTURA.get(estado, COLOR_TEXT_MUTED)
        badge = QLabel(estado.capitalize())
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedWidth(70)
        badge.setStyleSheet(
            f"background-color: {color_con_alpha(color_estado)}; color: {color_estado}; border-radius: 4px;"
            " padding: 2px 6px; font-size: 10px; font-weight: bold;"
        )

        h.addWidget(lbl_numero)
        h.addWidget(lbl_cliente, stretch=1)
        h.addWidget(lbl_total)
        h.addWidget(badge)


class DashboardPanel(QWidget):
    """Panel general: primera pantalla tras iniciar sesión."""

    nueva_factura_solicitada = Signal()

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.setObjectName("ContentArea")
        self._build_ui()
        # self._setup_reloj()  -- desactivado junto con el bloque de equipo/fecha/hora
        # del header, ver _make_header().
        QTimer.singleShot(100, self.cargar_datos)

    def showEvent(self, event: QShowEvent) -> None:
        # El panel se crea una sola vez y MainWindow lo reutiliza via
        # QStackedWidget (_obtener_o_crear_panel) -- sin esto, volver a "Panel
        # General" despues de la carga inicial mostraba datos ya viejos hasta
        # cerrar y volver a abrir la app.
        super().showEvent(event)
        self.cargar_datos()

    # ── Construcción de la UI ─────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        root.addWidget(self._make_header())
        root.addWidget(self._make_fila_kpis())
        root.addWidget(self._make_fila_grafico_y_cajas(), stretch=1)
        root.addWidget(self._make_fila_facturas_e_inventario(), stretch=1)

        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

    def _make_header(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(28)

        info = QVBoxLayout()
        info.setSpacing(2)
        lbl_titulo = QLabel("Panel general")
        lbl_titulo.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        lbl_subtitulo = QLabel(f"Resumen de la operación · {self._nombre_empresa()}")
        lbl_subtitulo.setStyleSheet(f"font-size: 13px; color: {COLOR_TEXT_MUTED};")
        lbl_subtitulo.setWordWrap(False)
        info.addWidget(lbl_titulo)
        info.addWidget(lbl_subtitulo)

        # Bloque de equipo/fecha/hora desactivado a pedido del usuario (2026-08-27,
        # "no me gusta como se ve") -- comentado, no borrado, por si se quiere retomar
        # mas adelante con otro diseño. _setup_reloj()/_actualizar_fecha_hora() (mas
        # abajo) quedan intactos pero sin invocarse.
        # sistema_info = QVBoxLayout()
        # sistema_info.setSpacing(2)
        # self.lbl_hostname = QLabel()
        # self.lbl_hostname.setStyleSheet(
        #     f"font-size: 11px; font-weight: bold; color: {COLOR_TEXT_DARK}; background: transparent; border: none;"
        # )
        # self.lbl_fecha_hora = QLabel()
        # self.lbl_fecha_hora.setStyleSheet(
        #     f"font-size: 11px; font-weight: bold; color: {COLOR_TEXT_DARK}; background: transparent; border: none;"
        # )
        # sistema_info.addWidget(self.lbl_hostname)
        # sistema_info.addWidget(self.lbl_fecha_hora)

        btn_nueva_factura = QPushButton(" Nueva factura")
        btn_nueva_factura.setIcon(qta.icon("fa5s.plus", color="white"))
        btn_nueva_factura.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_nueva_factura.clicked.connect(self.nueva_factura_solicitada.emit)

        # h.setAlignment(layout, ...) en vez de dejar el default: sin esto, "info" (sin
        # alineacion propia) se estira para llenar el alto completo de la fila mientras
        # "sistema_info" (que SI tenia alignment seteado) se queda en su alto natural --
        # esa asimetria hacia que las dos columnas no quedaran alineadas verticalmente
        # entre si (reportado por el usuario: el bloque de equipo/fecha/hora aparecia
        # descolocado respecto al titulo/subtitulo). Ambas columnas ahora se comportan
        # igual: alto natural, centradas verticalmente en la fila.
        h.addLayout(info)
        h.setAlignment(info, Qt.AlignmentFlag.AlignVCenter)
        # h.addLayout(sistema_info)
        # h.setAlignment(sistema_info, Qt.AlignmentFlag.AlignVCenter)
        h.addSpacerItem(QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        h.addWidget(btn_nueva_factura)
        return w

    def _nombre_empresa(self) -> str:
        rol = self.usuario.rol.nombre if self.usuario.rol else "Usuario"
        nombre = self.usuario.nombre or self.usuario.nombre_usuario
        return f"{nombre} ({rol})"

    def _setup_reloj(self) -> None:
        """Configura el reloj que muestra hostname, fecha y hora del sistema."""
        try:
            hostname = socket.gethostname()
        except Exception:
            hostname = "Desconocido"
        self.lbl_hostname.setText(f"Equipo: {hostname}")

        self._actualizar_fecha_hora()
        self.timer_reloj = QTimer(self)
        self.timer_reloj.timeout.connect(self._actualizar_fecha_hora)
        self.timer_reloj.start(1000)  # Actualizar cada segundo

    def _actualizar_fecha_hora(self) -> None:
        """Actualiza la etiqueta de fecha y hora."""
        ahora = datetime.now()
        fecha = ahora.strftime("%d/%m/%Y")
        hora = ahora.strftime("%H:%M:%S")
        self.lbl_fecha_hora.setText(f"{fecha} · {hora}")

    def _make_fila_kpis(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(14)

        self.kpi_ventas_hoy = KpiCard("Ventas de hoy", "fa5s.chart-line", COLOR_PRIMARY)
        self.kpi_por_cobrar = KpiCard("Por cobrar", "fa5s.file-invoice-dollar", COLOR_INFO)
        self.kpi_por_pagar = KpiCard("Por pagar", "fa5s.hand-holding-usd", COLOR_WARNING)
        self.kpi_productos_alerta = KpiCard("Productos en alerta", "fa5s.exclamation-triangle", COLOR_DANGER)

        for card in (self.kpi_ventas_hoy, self.kpi_por_cobrar, self.kpi_por_pagar, self.kpi_productos_alerta):
            h.addWidget(card)
        return w

    def _make_fila_grafico_y_cajas(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(14)

        grafico_inner = QWidget()
        grafico_inner.setStyleSheet("background: transparent; border: none;")
        gv = QVBoxLayout(grafico_inner)
        gv.setContentsMargins(18, 16, 18, 16)
        gv.setSpacing(4)
        lbl_titulo = QLabel("Ventas de la semana")
        lbl_titulo.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {COLOR_TEXT_DARK}; border: none;")
        lbl_subtitulo = QLabel("Total facturado por día, últimos 7 días")
        lbl_subtitulo.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_MUTED}; border: none;")
        self.grafico_ventas = VentasSemanaChart()
        self.etiquetas_dias = EtiquetasDiasSemana()
        gv.addWidget(lbl_titulo)
        gv.addWidget(lbl_subtitulo)
        gv.addWidget(self.grafico_ventas, stretch=1)
        gv.addWidget(self.etiquetas_dias)

        cajas_inner = QWidget()
        cajas_inner.setStyleSheet("background: transparent; border: none;")
        cv = QVBoxLayout(cajas_inner)
        cv.setContentsMargins(18, 16, 18, 16)
        cv.setSpacing(4)
        lbl_titulo_cajas = QLabel("Cajas activas")
        lbl_titulo_cajas.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {COLOR_TEXT_DARK}; border: none;")
        lbl_subtitulo_cajas = QLabel("Estado de turnos abiertos hoy")
        lbl_subtitulo_cajas.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_MUTED}; border: none;")
        self.cajas_lista = QVBoxLayout()
        self.cajas_lista.setSpacing(0)
        cv.addWidget(lbl_titulo_cajas)
        cv.addWidget(lbl_subtitulo_cajas)
        cv.addLayout(self.cajas_lista)
        cv.addStretch()

        card_grafico = _card(grafico_inner)
        card_cajas = _card(cajas_inner)
        h.addWidget(card_grafico, stretch=2)
        h.addWidget(card_cajas, stretch=1)
        return w

    def _make_fila_facturas_e_inventario(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(14)

        facturas_inner = QWidget()
        facturas_inner.setStyleSheet("background: transparent; border: none;")
        fv = QVBoxLayout(facturas_inner)
        fv.setContentsMargins(18, 16, 18, 16)
        fv.setSpacing(4)
        lbl_titulo = QLabel("Facturas recientes")
        lbl_titulo.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {COLOR_TEXT_DARK}; border: none;")
        lbl_subtitulo = QLabel("Últimos movimientos de ventas")
        lbl_subtitulo.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_MUTED}; border: none;")
        self.facturas_lista = QVBoxLayout()
        self.facturas_lista.setSpacing(0)
        fv.addWidget(lbl_titulo)
        fv.addWidget(lbl_subtitulo)
        fv.addLayout(self.facturas_lista)
        fv.addStretch()

        inventario_inner = QWidget()
        inventario_inner.setStyleSheet("background: transparent; border: none;")
        iv = QVBoxLayout(inventario_inner)
        iv.setContentsMargins(18, 16, 18, 16)
        iv.setSpacing(4)
        lbl_titulo_inv = QLabel("Inventario en alerta")
        lbl_titulo_inv.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {COLOR_TEXT_DARK}; border: none;")
        lbl_subtitulo_inv = QLabel("Stock por debajo del mínimo")
        lbl_subtitulo_inv.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_MUTED}; border: none;")
        self.inventario_lista = QVBoxLayout()
        self.inventario_lista.setSpacing(0)
        iv.addWidget(lbl_titulo_inv)
        iv.addWidget(lbl_subtitulo_inv)
        iv.addLayout(self.inventario_lista)
        iv.addStretch()

        card_facturas = _card(facturas_inner)
        card_inventario = _card(inventario_inner)
        h.addWidget(card_facturas, stretch=2)
        h.addWidget(card_inventario, stretch=1)
        return w

    # ── Carga de datos ────────────────────────────────────────────────────

    def cargar_datos(self) -> None:
        # showEvent puede disparar esto antes de que una carga anterior termine
        # (navegacion rapida entre modulos) -- reasignar self._worker a un QThread
        # nuevo mientras el viejo sigue corriendo lo destruye a mitad de ejecucion
        # y Qt aborta el proceso ("QThread: Destroyed while thread is still running").
        if getattr(self, "_worker", None) is not None and self._worker.isRunning():
            return
        self._worker = QueryWorker(self.session_factory, _tarea_panel_general, id_usuario=self.usuario.id_usuario)
        self._worker.resultado.connect(self._mostrar_datos)
        self._worker.error.connect(self._mostrar_error)
        self._worker.start()

    def recargar(self) -> None:
        self.cargar_datos()

    def _mostrar_datos(self, datos: dict) -> None:
        ventas_hoy = datos["ventas_hoy"]
        self.kpi_ventas_hoy.set_valor(f"${float(ventas_hoy['total']):,.2f}")
        pct = ventas_hoy["porcentaje_vs_ayer"]
        color = COLOR_SUCCESS if pct >= 0 else COLOR_DANGER
        signo = "+" if pct >= 0 else ""
        self.kpi_ventas_hoy.set_detalle(f"{signo}{pct:.1f}% vs ayer", color)

        por_cobrar = datos["por_cobrar"]
        self.kpi_por_cobrar.set_valor(f"${float(por_cobrar['saldo_total']):,.2f}")
        self.kpi_por_cobrar.set_detalle(f"{por_cobrar['facturas_vencidas']} facturas vencidas", COLOR_DANGER)

        por_pagar = datos["por_pagar"]
        self.kpi_por_pagar.set_valor(f"${float(por_pagar['saldo_total']):,.2f}")
        self.kpi_por_pagar.set_detalle(f"{por_pagar['compras_vencidas']} compras vencidas", COLOR_DANGER)

        self.kpi_productos_alerta.set_valor(str(datos["productos_alerta"]))
        self.kpi_productos_alerta.set_detalle("Bajo el mínimo", COLOR_WARNING)

        self.grafico_ventas.set_datos(datos["grafico_semanal"])
        self.etiquetas_dias.set_datos(datos["grafico_semanal"])

        self._poblar_lista(self.cajas_lista, datos["cajas_activas"], FilaCaja, "Ninguna caja abierta hoy")
        self._poblar_lista(self.facturas_lista, datos["facturas_recientes"], FilaFactura, "Sin facturas registradas")
        self._poblar_lista(
            self.inventario_lista, datos["inventario_alerta"], FilaInventarioAlerta, "Sin alertas de inventario"
        )

    def _poblar_lista(self, layout: QVBoxLayout, items: list[dict], clase_fila, texto_vacio: str) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not items:
            layout.addWidget(ListaVaciaLabel(texto_vacio))
            return

        for item in items:
            layout.addWidget(clase_fila(item))

    def _mostrar_error(self, mensaje: str) -> None:
        logger.error("Fallo al cargar el panel general: %s", mensaje)
        QMessageBox.critical(self, "Error", "No se pudo cargar el panel general.")
