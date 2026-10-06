"""
TopBar: barra superior del ERP con breadcrumb del módulo activo, búsqueda global
y notificaciones. La info del usuario autenticado vive en el pie de la sidebar
(ver `sidebar.py`), no aquí.

- Búsqueda: al escribir aparece una lista con módulos, clientes, productos, proveedores y
  facturas (app/services/busqueda_global.py). Elegir uno emite `modulo_solicitado`; MainWindow
  navega y deja el texto en la caja de búsqueda de ese módulo.
- Campana: contador de alertas vigentes (app/services/notificaciones.py) y menú con el detalle;
  cada alerta lleva al módulo donde se resuelve. MainWindow las refresca en segundo plano con
  `set_notificaciones`.
"""

import logging
import unicodedata

import qtawesome as qta
from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QWidget,
)

from app.db.models import Usuario
from app.services.busqueda_global import (
    LONGITUD_MINIMA,
    TIPO_CLIENTE,
    TIPO_FACTURA,
    TIPO_PRODUCTO,
    TIPO_PROVEEDOR,
    BusquedaGlobalService,
    ResultadoBusqueda,
)
from app.services.notificaciones import SEVERIDAD_ALTA, SEVERIDAD_MEDIA, Notificacion
from app.ui.styles import (
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_PRIMARY,
    COLOR_TEXT_DARK,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
    TOPBAR_HEIGHT,
    TOPBAR_QSS,
)
from app.ui.workers import QueryWorker

logger = logging.getLogger(__name__)

DEBOUNCE_BUSQUEDA_MS = 300
ANCHO_RESULTADOS = 380
ALTO_FILA_RESULTADO = 46
ALTO_MAX_RESULTADOS = 360
TIPO_MODULO = "Módulo"

_ICONO_TIPO = {
    TIPO_MODULO: "fa5s.th-large",
    TIPO_CLIENTE: "fa5s.user",
    TIPO_PRODUCTO: "fa5s.box",
    TIPO_PROVEEDOR: "fa5s.truck",
    TIPO_FACTURA: "fa5s.file-invoice-dollar",
}

# Títulos presentables para cada módulo
TITULOS = {
    "panel_general": "Panel General",
    "clientes": "Clientes",
    "proveedores": "Proveedores",
    "inventario": "Inventario",
    "facturacion": "Facturación / Ventas",
    "compras": "Compras",
    "bancos": "Bancos",
    "cuentas_bancarias": "Cuentas Bancarias",
    "cajas": "Cajas",
    "vendedores": "Vendedores",
    "comisiones": "Comisiones",
    "control_tasas": "Tasas de Cambio",
    "config_empresa": "Configuración",
    "usuarios": "Usuarios",
    "auditoria": "Auditoría",
    "cuentas_por_cobrar": "Cuentas por Cobrar",
    "cuentas_por_cobrar_bcv": "Cuentas por Cobrar BCV",
    "cuentas_por_pagar": "Cuentas por Pagar",
    "reportes": "Reportes",
}


def _normalizar(texto: str) -> str:
    """Minúsculas y sin tildes: 'facturacion' tiene que encontrar 'Facturación'."""
    sin_tildes = unicodedata.normalize("NFD", texto)
    return "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn").lower()


def _color_severidad(severidad: str) -> str:
    if severidad == SEVERIDAD_ALTA:
        return COLOR_DANGER
    if severidad == SEVERIDAD_MEDIA:
        return COLOR_WARNING
    return COLOR_PRIMARY


class TopBar(QWidget):
    """Barra superior con breadcrumb de módulo activo, búsqueda y notificaciones."""

    # (clave_modulo, texto_para_su_caja_de_busqueda) -- el texto va vacío para "ir al módulo".
    modulo_solicitado = Signal(str, str)

    def __init__(
        self,
        usuario: Usuario,
        session_factory=None,
        modulos_visibles: set[str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.usuario = usuario
        self.session_factory = session_factory
        # None = sin filtrar (cualquier caller que no pase el set calculado por rol).
        self._modulos_visibles = modulos_visibles
        self._notificaciones: list[Notificacion] = []
        self._workers: set[QueryWorker] = set()
        self._id_busqueda = 0
        self.setObjectName("TopBar")
        self.setFixedHeight(TOPBAR_HEIGHT)
        self.setStyleSheet(TOPBAR_QSS)

        self._timer_busqueda = QTimer(self)
        self._timer_busqueda.setSingleShot(True)
        self._timer_busqueda.setInterval(DEBOUNCE_BUSQUEDA_MS)
        self._timer_busqueda.timeout.connect(self._lanzar_busqueda)

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(16)

        layout.addWidget(self._make_breadcrumb())

        spacer = QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout.addSpacerItem(spacer)

        self.buscar_input = QLineEdit()
        self.buscar_input.setPlaceholderText("Buscar en el sistema…")
        self.buscar_input.addAction(
            qta.icon("fa5s.search", color=COLOR_TEXT_LIGHT),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.buscar_input.setObjectName("TopBarSearch")
        self.buscar_input.setFixedWidth(240)
        self.buscar_input.setFixedHeight(36)
        self.buscar_input.textChanged.connect(self._on_texto_cambiado)
        self.buscar_input.installEventFilter(self)
        layout.addWidget(self.buscar_input)

        # Lista de resultados: hija de la ventana (no una ventana propia) y sin foco, para
        # que no le quite el teclado a la caja mientras se escribe -- ver _posicionar_resultados().
        self.lista_resultados = QListWidget()
        self.lista_resultados.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lista_resultados.setIconSize(QSize(16, 16))
        self.lista_resultados.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLOR_CARD_BG};
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
                padding: 4px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 6px 8px;
                border-radius: 6px;
                color: {COLOR_TEXT_DARK};
            }}
            QListWidget::item:selected, QListWidget::item:hover {{
                background-color: {COLOR_CONTENT_BG};
                color: {COLOR_TEXT_DARK};
            }}
        """)
        self.lista_resultados.itemClicked.connect(self._elegir_item)
        self.lista_resultados.setVisible(False)

        self.btn_notif = QPushButton()
        self.btn_notif.setIcon(qta.icon("fa5s.bell", color=COLOR_TEXT_MUTED))
        self.btn_notif.setIconSize(QSize(18, 18))
        self.btn_notif.setObjectName("TopBarBtn")
        self.btn_notif.setFixedSize(38, 38)
        self.btn_notif.setToolTip("Notificaciones")
        self.btn_notif.clicked.connect(self._mostrar_menu_notificaciones)
        layout.addWidget(self.btn_notif)

        # Contador sobre la campana (hijo del botón: se posiciona sobre su esquina).
        self.lbl_contador = QLabel(self.btn_notif)
        self.lbl_contador.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_contador.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.lbl_contador.setVisible(False)

    def _make_breadcrumb(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        lbl_raiz = QLabel("Módulos")
        lbl_raiz.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED}; background: transparent;")

        lbl_sep = QLabel("›")
        lbl_sep.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED}; background: transparent;")

        self.lbl_titulo = QLabel("Panel General")
        self.lbl_titulo.setObjectName("TopBarTitle")
        self.lbl_titulo.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {COLOR_TEXT_DARK}; background: transparent;"
        )

        h.addWidget(lbl_raiz)
        h.addWidget(lbl_sep)
        h.addWidget(self.lbl_titulo)
        return w

    def actualizar_modulo(self, clave: str) -> None:
        """Actualiza el título del módulo activo en el breadcrumb."""
        titulo = TITULOS.get(clave, clave.replace("_", " ").title())
        self.lbl_titulo.setText(titulo)

    # ── Búsqueda global ─────────────────────────────────────────────────────

    def eventFilter(self, watched, event) -> bool:
        if watched is self.buscar_input:
            tipo = event.type()
            if tipo == QEvent.Type.FocusOut:
                self.lista_resultados.setVisible(False)
            elif tipo == QEvent.Type.FocusIn and self.lista_resultados.count():
                self._posicionar_resultados()
                self.lista_resultados.setVisible(True)
            elif tipo == QEvent.Type.KeyPress and self.lista_resultados.isVisible():
                if self._tecla_en_resultados(event):
                    return True
        return super().eventFilter(watched, event)

    def _tecla_en_resultados(self, event: QKeyEvent) -> bool:
        lista = self.lista_resultados
        tecla = event.key()
        if tecla in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            paso = 1 if tecla == Qt.Key.Key_Down else -1
            lista.setCurrentRow(max(0, min(lista.count() - 1, lista.currentRow() + paso)))
            return True
        if tecla in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            item = lista.currentItem() or (lista.item(0) if lista.count() else None)
            if item is not None:
                self._elegir_item(item)
                return True
        if tecla == Qt.Key.Key_Escape:
            lista.setVisible(False)
            return True
        return False

    def _on_texto_cambiado(self, texto: str) -> None:
        if len(texto.strip()) < LONGITUD_MINIMA:
            self._timer_busqueda.stop()
            self._id_busqueda += 1  # invalida cualquier consulta en vuelo
            self._limpiar_resultados()
            return
        self._timer_busqueda.start()  # debounce: una consulta por pausa al escribir

    def _lanzar_busqueda(self) -> None:
        texto = self.buscar_input.text().strip()
        if len(texto) < LONGITUD_MINIMA:
            return
        self._id_busqueda += 1
        id_busqueda = self._id_busqueda
        modulos = self._buscar_modulos(texto)

        if self.session_factory is None:
            self._mostrar_resultados(id_busqueda, modulos, [])
            return

        id_usuario = self.usuario.id_usuario

        def _tarea(session):
            return BusquedaGlobalService.buscar(session, id_usuario, texto)

        worker = QueryWorker(self.session_factory, _tarea)
        worker.resultado.connect(lambda entidades: self._mostrar_resultados(id_busqueda, modulos, entidades))
        # Si falla la consulta (QueryWorker ya lo registra en el log), al menos quedan los
        # módulos, que no dependen de la base.
        worker.error.connect(lambda _msg: self._mostrar_resultados(id_busqueda, modulos, []))
        worker.finished.connect(lambda w=worker: self._workers.discard(w))
        self._workers.add(worker)  # referencia viva mientras corre (ver workers.py)
        worker.start()

    def _buscar_modulos(self, texto: str) -> list[ResultadoBusqueda]:
        buscado = _normalizar(texto)
        encontrados = []
        for clave, titulo in TITULOS.items():
            if self._modulos_visibles is not None and clave not in self._modulos_visibles:
                continue
            if buscado in _normalizar(titulo):
                encontrados.append(ResultadoBusqueda(TIPO_MODULO, titulo, "Ir al módulo", clave, ""))
        return encontrados

    def _mostrar_resultados(
        self,
        id_busqueda: int,
        modulos: list[ResultadoBusqueda],
        entidades: list[ResultadoBusqueda],
    ) -> None:
        if id_busqueda != self._id_busqueda:
            return  # llegó tarde: el usuario ya escribió otra cosa
        resultados = [*modulos, *entidades]
        self.lista_resultados.clear()
        if not resultados:
            vacio = QListWidgetItem("Sin resultados")
            vacio.setFlags(Qt.ItemFlag.NoItemFlags)
            vacio.setForeground(QColor(COLOR_TEXT_MUTED))
            self.lista_resultados.addItem(vacio)
        for r in resultados:
            icono = qta.icon(_ICONO_TIPO.get(r.tipo, "fa5s.search"), color=COLOR_PRIMARY)
            segunda_linea = f"{r.tipo} · {r.detalle}" if r.detalle else r.tipo
            item = QListWidgetItem(icono, f"{r.titulo}\n{segunda_linea}")
            item.setData(Qt.ItemDataRole.UserRole, (r.modulo, r.texto_busqueda))
            self.lista_resultados.addItem(item)
        if resultados:
            self.lista_resultados.setCurrentRow(0)
        if self.buscar_input.hasFocus():
            self._posicionar_resultados()
            self.lista_resultados.setVisible(True)

    def _posicionar_resultados(self) -> None:
        ventana = self.window()
        if self.lista_resultados.parent() is not ventana:
            self.lista_resultados.setParent(ventana)
        # Alto real de una fila (depende de la fuente/escala), no una constante: con una fija
        # la última fila quedaba cortada.
        fila = self.lista_resultados.sizeHintForRow(0)
        if fila <= 0:
            fila = ALTO_FILA_RESULTADO
        alto = min(ALTO_MAX_RESULTADOS, max(1, self.lista_resultados.count()) * fila + 14)
        esquina = self.buscar_input.mapTo(ventana, QPoint(self.buscar_input.width(), self.buscar_input.height() + 4))
        x = max(8, esquina.x() - ANCHO_RESULTADOS)  # alineada al borde derecho de la caja
        self.lista_resultados.setGeometry(x, esquina.y(), ANCHO_RESULTADOS, alto)
        self.lista_resultados.raise_()

    def _limpiar_resultados(self) -> None:
        self.lista_resultados.clear()
        self.lista_resultados.setVisible(False)

    def _elegir_item(self, item: QListWidgetItem) -> None:
        datos = item.data(Qt.ItemDataRole.UserRole)
        if not datos:
            return  # "Sin resultados"
        modulo, texto = datos
        self.buscar_input.clear()  # también oculta la lista (ver _on_texto_cambiado)
        self.buscar_input.clearFocus()
        self.modulo_solicitado.emit(modulo, texto)

    # ── Notificaciones ──────────────────────────────────────────────────────

    def set_notificaciones(self, notificaciones: list[Notificacion]) -> None:
        self._notificaciones = list(notificaciones)
        cantidad = len(self._notificaciones)
        if not cantidad:
            self.lbl_contador.setVisible(False)
            self.btn_notif.setToolTip("Notificaciones — no hay alertas")
            return
        hay_alta = any(n.severidad == SEVERIDAD_ALTA for n in self._notificaciones)
        color = COLOR_DANGER if hay_alta else COLOR_WARNING
        self.lbl_contador.setText(str(cantidad) if cantidad < 10 else "9+")
        self.lbl_contador.setStyleSheet(
            f"background-color: {color}; color: white; font-size: 10px; font-weight: bold; border-radius: 8px;"
        )
        self.lbl_contador.setGeometry(self.btn_notif.width() - 18, 2, 16, 16)
        self.lbl_contador.setVisible(True)
        self.btn_notif.setToolTip(f"Notificaciones — {cantidad} alerta(s)")

    def _mostrar_menu_notificaciones(self) -> None:
        menu = self._construir_menu_notificaciones()
        ancla = QPoint(self.btn_notif.width() - menu.sizeHint().width(), self.btn_notif.height() + 4)
        menu.exec(self.btn_notif.mapToGlobal(ancla))
        menu.deleteLater()  # es hijo de la barra: sin esto se acumulaba uno por cada click

    def _construir_menu_notificaciones(self) -> QMenu:
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {COLOR_CARD_BG};
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
                padding: 6px;
            }}
            QMenu::item {{
                padding: 8px 14px 8px 10px;
                border-radius: 6px;
                color: {COLOR_TEXT_DARK};
            }}
            QMenu::item:selected {{
                background-color: {COLOR_CONTENT_BG};
            }}
            QMenu::item:disabled {{
                color: {COLOR_TEXT_MUTED};
            }}
        """)
        if not self._notificaciones:
            menu.addAction("No hay alertas por ahora").setEnabled(False)
        for n in self._notificaciones:
            icono = qta.icon("fa5s.circle", color=_color_severidad(n.severidad))
            accion = menu.addAction(icono, f"{n.titulo}: {n.detalle}")
            accion.triggered.connect(lambda _checked=False, modulo=n.modulo: self.modulo_solicitado.emit(modulo, ""))
        return menu
