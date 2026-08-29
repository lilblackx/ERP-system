"""
Panel del modulo Auditoria: consulta de solo lectura sobre la bitacora que
AuditoriaService.registrar_evento() alimenta desde los 18 modulos de servicio (ver
docs/ESTADO_DEL_PROYECTO.md seccion 5). No hay alta/edicion/baja -- la tabla es
append-only por diseno, este panel solo filtra y pagina sobre consultar_auditoria().

Mismo patron de paginacion servidor que app/ui/cuentas_por_cobrar_panel.py (resultado
{"items", "total", "pagina", "por_pagina"}). El filtro "Modulo" se puebla desde
AuditoriaService.MODULOS_SUGERIDOS (unica fuente de verdad de que modulos loguean
eventos hoy) en vez de hardcodear la lista aca.
"""

import json
import logging
from datetime import datetime, time

import qtawesome as qta
from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtGui import QColor, QShowEvent, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.db.models import Auditoria, Usuario
from app.services.auditoria import MODULOS_SUGERIDOS, AuditoriaService
from app.services.permisos import PermisoDenegadoError
from app.services.usuarios import UsuarioService
from app.ui.styles import (
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_FIELD_BG,
    COLOR_PRIMARY,
    COLOR_PRIMARY_LIGHT,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MUTED,
    FONT_FAMILY,
    ICON_CHEVRON_DOWN_URL,
    SEARCH_QSS,
    TABLE_QSS,
    alinear_encabezados,
    aplicar_sombra,
)
from app.ui.toolbar_popups import BotonFiltros

logger = logging.getLogger(__name__)

POR_PAGINA = 50
COLS_VISIBLES = ["Fecha", "Usuario", "Módulo", "Acción", "Detalle"]
LIMITE_RESUMEN_DETALLE = 80

# AuditoriaService.registrar_evento() guarda `detalle` como JSON crudo (ver
# app/services/auditoria.py) armado por cada modulo con sus propias claves internas en
# ingles/snake_case (ej. {"numero_oc": "ODC-000001", "id_proveedor": 10}) -- perfecto para
# depurar, ilegible para un usuario que no conoce el modelo de datos (hallazgo del
# usuario, 2026-08-28). Este diccionario traduce las claves que efectivamente se usan hoy
# (relevado con grep de `detalle={` en app/services/*.py) a una etiqueta en español; una
# clave nueva que no este aca simplemente cae al fallback de _etiqueta_campo() (snake_case
# -> "Snake case"), nunca revienta.
ETIQUETAS_DETALLE: dict[str, str] = {
    "agregados": "Permisos agregados",
    "autorizado_por": "Autorizado por (usuario)",
    "autorizado_por_descuento": "Descuento autorizado por",
    "autorizado_por_dias_credito": "Días de crédito autorizados por",
    "campos": "Campos modificados",
    "cantidad_comisiones": "Cantidad de comisiones",
    "clave_restablecida": "Clave restablecida",
    "cod_producto": "Código de producto",
    "condicion_pago": "Condición de pago",
    "descripcion": "Descripción",
    "dias_credito": "Días de crédito",
    "dias_credito_aplicados": "Días de crédito aplicados",
    "estado_enmienda": "Estado de la enmienda",
    "estado_resultante": "Estado resultante",
    "id_banco": "Banco (ID)",
    "id_caja": "Caja (ID)",
    "id_categoria": "Categoría (ID)",
    "id_cliente": "Cliente (ID)",
    "id_compra_origen": "Compra de origen (ID)",
    "id_cuenta": "Cuenta (ID)",
    "id_cuenta_bancaria": "Cuenta bancaria (ID)",
    "id_cuenta_partida": "Cuenta (ID)",
    "id_cuenta_por_cobrar": "Cuenta por cobrar (ID)",
    "id_cuenta_por_pagar": "Cuenta por pagar (ID)",
    "id_factura_destino": "Factura destino (ID)",
    "id_factura_origen": "Factura de origen (ID)",
    "id_nr": "Nota de recepción (ID)",
    "id_oc": "Orden de compra (ID)",
    "id_permiso": "Permiso (ID)",
    "id_producto": "Producto (ID)",
    "id_proveedor": "Proveedor (ID)",
    "id_rol": "Rol (ID)",
    "id_tasa": "Tasa (ID)",
    "id_usuario": "Usuario (ID)",
    "id_vendedor": "Vendedor (ID)",
    "iva_activo": "IVA activo",
    "iva_porcentaje": "Porcentaje de IVA",
    "limite_credito": "Límite de crédito",
    "lineas": "Líneas",
    "metodo_devolucion": "Método de devolución",
    "metodo_pago": "Método de pago",
    "moneda": "Moneda",
    "monto": "Monto",
    "monto_descuento": "Monto del descuento",
    "monto_iva": "Monto del IVA",
    "monto_total": "Monto total",
    "nombre": "Nombre",
    "nombre_banco": "Banco",
    "nombre_razon_social": "Nombre / razón social",
    "nombre_usuario": "Usuario",
    "nombre_vendedor": "Vendedor",
    "nota_credito_generada": "Nota de crédito generada",
    "numero_compra": "N.º de compra",
    "numero_control": "N.º de control",
    "numero_cuenta": "N.º de cuenta",
    "numero_enmienda": "N.º de enmienda",
    "numero_factura": "N.º de factura",
    "numero_factura_destino": "N.º de factura destino",
    "numero_nota_credito": "N.º de nota de crédito",
    "numero_nota_devolucion": "N.º de nota de devolución",
    "numero_nr": "N.º de nota de recepción",
    "numero_oc": "N.º de orden de compra",
    "nuevo_estado": "Nuevo estado",
    "pago": "Pago",
    "quitados": "Permisos quitados",
    "razon_social": "Razón social",
    "rif": "RIF",
    "saldo_restante_nota": "Saldo restante de la nota",
    "tasa_bcv": "Tasa BCV",
    "tasa_cop": "Tasa COP",
    "tasa_paralelo": "Tasa paralelo",
    "tipo": "Tipo",
    "tipo_cambio": "Tipo de cambio",
    "total_compra": "Total de la compra",
    "total_oc": "Total de la orden de compra",
    "total_venta": "Total de la venta",
}


def _etiqueta_campo(clave: str) -> str:
    etiqueta = ETIQUETAS_DETALLE.get(clave)
    if etiqueta:
        return etiqueta
    texto = clave.replace("_", " ").strip()
    return texto[:1].upper() + texto[1:] if texto else clave


def _formatear_valor_detalle(valor) -> str:
    if isinstance(valor, bool):
        return "Sí" if valor else "No"
    if isinstance(valor, list):
        return ", ".join(str(v) for v in valor) if valor else "Ninguno"
    if isinstance(valor, dict):
        partes = [f"{_etiqueta_campo(k)}: {_formatear_valor_detalle(v)}" for k, v in valor.items() if v is not None]
        return "; ".join(partes) if partes else "—"
    return str(valor)


def _formatear_detalle(detalle_crudo: str | None) -> list[str]:
    """Convierte el JSON crudo que guarda registrar_evento() en lineas "Etiqueta: valor"
    legibles. Si `detalle` no es JSON (auth.py/recuperacion_acceso.py guardan una frase
    ya armada, ej. "Usuario 'admin' inicio sesion") se devuelve tal cual -- ya es texto
    para humanos, no hay nada que traducir."""
    if not detalle_crudo:
        return []
    try:
        datos = json.loads(detalle_crudo)
    except (json.JSONDecodeError, TypeError):
        return [detalle_crudo]
    if not isinstance(datos, dict):
        return [str(datos)]
    return [
        f"{_etiqueta_campo(clave)}: {_formatear_valor_detalle(valor)}"
        for clave, valor in datos.items()
        if valor is not None
    ]


# QDateEdit no hereda GLOBAL_QSS de forma confiable cuando se usa suelto en un toolbar
# (a diferencia de un QComboBox metido en el popup de BotonFiltros, que si hereda el QSS
# del propio popup) -- mismo motivo por el que los dialogos con stylesheet propio
# (DIALOG_STYLE en varios *_dialog.py) redefinen esta misma regla en vez de confiar en la
# cascada. Se aplica explicitamente via .setStyleSheet() sobre cada QDateEdit.
#
# Borde de 1px solido (igual a SEARCH_QSS/DIALOG_STYLE) se veia demasiado marcado en un
# campo angosto de solo fecha -- y hasta con "border: 1px solid transparent" (reserva el
# espacio pero no deberia pintarse) seguia notandose un contorno (hallazgo del usuario,
# 2026-08-28, segunda vuelta). Sin borde en ningun estado: transparente en reposo, relleno
# tipo "chip" (COLOR_FIELD_BG) solo en hover/focus como unica señal visual -- ninguna linea.
FECHA_QSS = f"""
QDateEdit {{
    background-color: transparent;
    border: none;
    border-radius: 6px;
    padding: 5px 8px;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
    min-height: 20px;
}}
QDateEdit:hover, QDateEdit:focus {{
    background-color: {COLOR_FIELD_BG};
}}
QDateEdit::drop-down {{
    border: none;
    width: 22px;
}}
QDateEdit::down-arrow {{
    image: url({ICON_CHEVRON_DOWN_URL});
    width: 12px;
    height: 12px;
    margin-right: 6px;
}}
"""

# El popup del calendario (QCalendarWidget) es una ventana propia (Qt.WindowType.Popup)
# igual que _PopupAnclado en toolbar_popups.py -- tampoco hereda GLOBAL_QSS, asi que sin
# esto se ve con el chrome nativo de Windows (fondo blanco liso, sabado/domingo en rojo,
# barra de navegacion gris) en vez de la paleta de la app.
CALENDARIO_QSS = f"""
QCalendarWidget {{
    background-color: {COLOR_CARD_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    font-family: '{FONT_FAMILY}', Arial, sans-serif;
}}
QCalendarWidget QWidget#qt_calendar_navigationbar {{
    background-color: {COLOR_PRIMARY};
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}}
QCalendarWidget QToolButton {{
    color: #FFFFFF;
    background-color: transparent;
    border: none;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 13px;
    font-weight: 600;
}}
QCalendarWidget QToolButton:hover {{
    background-color: {COLOR_PRIMARY_LIGHT};
}}
QCalendarWidget QToolButton::menu-indicator {{
    image: none;
}}
QCalendarWidget QMenu {{
    background-color: {COLOR_CARD_BG};
    border: 1px solid {COLOR_BORDER};
    color: {COLOR_TEXT_DARK};
}}
QCalendarWidget QSpinBox {{
    background-color: #FFFFFF;
    color: {COLOR_TEXT_DARK};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    padding: 2px 4px;
}}
QCalendarWidget QAbstractItemView:enabled {{
    background-color: {COLOR_CARD_BG};
    color: {COLOR_TEXT_DARK};
    selection-background-color: {COLOR_PRIMARY};
    selection-color: #FFFFFF;
    outline: none;
}}
QCalendarWidget QAbstractItemView:disabled {{
    color: {COLOR_TEXT_LIGHT};
}}
"""


def _estilizar_fecha(date_edit: QDateEdit) -> None:
    """Aplica FECHA_QSS al campo y CALENDARIO_QSS a su popup, y normaliza el color de
    sabado/domingo (Qt los pinta en rojo/azul por defecto via setWeekdayTextFormat,
    QSS no lo sobreescribe porque el modelo del calendario fija su propio ForegroundRole)
    para que no desentonen con la paleta gris/azul del resto de la app.

    Nota: se probo setReadOnly(True) para bloquear el tecleo de digitos (hallazgo del
    usuario, 2026-08-28) pero en QDateTimeEdit/QDateEdit el modo solo-lectura tambien
    desactiva el boton del calendario -- no solo el tecleo -- asi que quedaba imposible
    abrirlo con el mouse. Se revierte: el campo queda editable por teclado igual que el
    resto de los QDateEdit de la app (compras.py, producto_form_dialog.py,
    factura_form_dialog.py, ninguno usa read-only), a cambio de mantener el calendario
    funcional."""
    date_edit.setStyleSheet(FECHA_QSS)
    calendario = date_edit.calendarWidget()
    calendario.setStyleSheet(CALENDARIO_QSS)
    formato = QTextCharFormat()
    formato.setForeground(QColor(COLOR_TEXT_DARK))
    for dia in (
        Qt.DayOfWeek.Monday,
        Qt.DayOfWeek.Tuesday,
        Qt.DayOfWeek.Wednesday,
        Qt.DayOfWeek.Thursday,
        Qt.DayOfWeek.Friday,
        Qt.DayOfWeek.Saturday,
        Qt.DayOfWeek.Sunday,
    ):
        calendario.setWeekdayTextFormat(dia, formato)


def _resumir_detalle(detalle: str | None) -> str:
    lineas = _formatear_detalle(detalle)
    if not lineas:
        return "—"
    texto = " · ".join(lineas)
    if len(texto) <= LIMITE_RESUMEN_DETALLE:
        return texto
    return texto[:LIMITE_RESUMEN_DETALLE].rstrip() + "…"


class AuditoriaPanel(QWidget):
    """Panel principal del modulo Auditoria: listado filtrable y paginado de
    AuditoriaService.consultar_auditoria(), gateado con el permiso 'auditoria'/'ver'."""

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.pagina_actual = 1
        self.total_paginas = 1
        self._eventos_pagina: list[Auditoria] = []
        self.setObjectName("ContentArea")
        self._setup_ui()
        QTimer.singleShot(100, self._cargar_usuarios_filtro)
        QTimer.singleShot(100, self.cargar_eventos)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.cargar_eventos()

    # ── Construcción de la UI ─────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        root.addWidget(self._make_header())
        root.addWidget(self._make_toolbar())
        root.addWidget(self._make_table())
        root.addWidget(self._make_footer())

        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

    def _make_header(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("Auditoría")
        lbl.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        self.lbl_total = QLabel("Cargando…")
        self.lbl_total.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 13px;"
            f" background-color: {COLOR_TABLE_HEADER}; border-radius: 10px;"
            " padding: 3px 10px;"
        )

        h.addWidget(lbl)
        h.addWidget(self.lbl_total)
        h.addStretch()
        return w

    def _make_toolbar(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(
            f"background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 8px; padding: 4px;"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)

        self.buscar_input = QLineEdit()
        self.buscar_input.setPlaceholderText("Buscar por acción, módulo, usuario o detalle…")
        self.buscar_input.addAction(qta.icon("fa5s.search", color="#94A3B8"), QLineEdit.ActionPosition.LeadingPosition)
        self.buscar_input.setObjectName("SearchInput")
        self.buscar_input.setStyleSheet(SEARCH_QSS)
        self.buscar_input.setFixedWidth(240)
        self.buscar_input.returnPressed.connect(self._buscar_desde_inicio)
        self.buscar_input.textChanged.connect(self._busqueda_dinamica)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(f"border: none; background: transparent; color: {COLOR_TEXT_DARK}; font-weight: 600;")
        self.fecha_desde_input = QDateEdit()
        self.fecha_desde_input.setCalendarPopup(True)
        self.fecha_desde_input.setDisplayFormat("dd/MM/yyyy")
        self.fecha_desde_input.setDate(QDate.currentDate().addDays(-30))
        self.fecha_desde_input.setFixedHeight(32)
        self.fecha_desde_input.setFixedWidth(130)
        _estilizar_fecha(self.fecha_desde_input)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(f"border: none; background: transparent; color: {COLOR_TEXT_DARK}; font-weight: 600;")
        self.fecha_hasta_input = QDateEdit()
        self.fecha_hasta_input.setCalendarPopup(True)
        self.fecha_hasta_input.setDisplayFormat("dd/MM/yyyy")
        self.fecha_hasta_input.setDate(QDate.currentDate())
        self.fecha_hasta_input.setFixedHeight(32)
        self.fecha_hasta_input.setFixedWidth(130)
        _estilizar_fecha(self.fecha_hasta_input)

        # Cada campo restringe el rango del otro (min/max cruzados) para que sea
        # imposible elegir Hasta < Desde desde el propio calendario -- antes se podia
        # armar un rango invertido sin aviso, que consultar_auditoria() resuelve como
        # "0 eventos" en silencio en vez de fallar (hallazgo del usuario, 2026-08-28).
        # Se fija el rango cruzado inicial antes de conectar las señales para no disparar
        # una recarga de mas durante la construccion del panel.
        self.fecha_hasta_input.setMinimumDate(self.fecha_desde_input.date())
        self.fecha_desde_input.setMaximumDate(self.fecha_hasta_input.date())
        self.fecha_desde_input.dateChanged.connect(self._on_fecha_desde_cambiada)
        self.fecha_hasta_input.dateChanged.connect(self._on_fecha_hasta_cambiada)

        self.modulo_combo = QComboBox()
        self.modulo_combo.addItem("Todos los módulos", None)
        for modulo in sorted(MODULOS_SUGERIDOS):
            self.modulo_combo.addItem(modulo.replace("_", " ").title(), modulo)

        self.usuario_combo = QComboBox()
        self.usuario_combo.addItem("Todos los usuarios", None)

        self.btn_filtrar = BotonFiltros([("Módulo", self.modulo_combo), ("Usuario", self.usuario_combo)])

        h.addWidget(self.buscar_input)
        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_input)
        h.addSpacerItem(QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        h.addWidget(self.btn_filtrar)
        return w

    def _make_table(self) -> QTableWidget:
        self.tabla = QTableWidget(0, len(COLS_VISIBLES))
        self.tabla.setHorizontalHeaderLabels(COLS_VISIBLES)
        alinear_encabezados(
            self.tabla,
            {
                0: Qt.AlignmentFlag.AlignLeft,
                1: Qt.AlignmentFlag.AlignLeft,
                2: Qt.AlignmentFlag.AlignLeft,
                3: Qt.AlignmentFlag.AlignLeft,
                4: Qt.AlignmentFlag.AlignLeft,
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
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(self.tabla)
        self.tabla.verticalHeader().setDefaultSectionSize(44)
        return self.tabla

    def _make_footer(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        self.lbl_pagina = QLabel("Página 1")
        self.lbl_pagina.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")

        self.btn_anterior = QPushButton()
        self.btn_anterior.setIcon(qta.icon("fa5s.chevron-left", color=COLOR_TEXT_DARK))
        self.btn_anterior.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_anterior.setFixedWidth(40)
        self.btn_anterior.clicked.connect(self._pagina_anterior)

        self.btn_siguiente = QPushButton()
        self.btn_siguiente.setIcon(qta.icon("fa5s.chevron-right", color=COLOR_TEXT_DARK))
        self.btn_siguiente.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_siguiente.setFixedWidth(40)
        self.btn_siguiente.clicked.connect(self._pagina_siguiente)

        btn_ver_detalle = QPushButton("Ver detalle")
        btn_ver_detalle.setIcon(qta.icon("fa5s.info-circle", color=COLOR_TEXT_DARK))
        btn_ver_detalle.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_ver_detalle.clicked.connect(self.ver_detalle_seleccionado)

        h.addWidget(self.lbl_pagina)
        h.addWidget(self.btn_anterior)
        h.addWidget(self.btn_siguiente)
        h.addStretch()
        h.addWidget(btn_ver_detalle)
        return w

    # ── Timer para búsqueda dinámica (300 ms debounce) ────────────────────

    def _busqueda_dinamica(self) -> None:
        if not hasattr(self, "_timer_busqueda"):
            self._timer_busqueda = QTimer()
            self._timer_busqueda.setSingleShot(True)
            self._timer_busqueda.timeout.connect(self._buscar_desde_inicio)
        self._timer_busqueda.start(300)

    # ── Rango de fechas cruzado (evita Hasta < Desde) ──────────────────────

    def _on_fecha_desde_cambiada(self, fecha: QDate) -> None:
        self.fecha_hasta_input.setMinimumDate(fecha)
        # Reusa el debounce de busqueda_dinamica: si setMinimumDate() arriba obliga a
        # Hasta a subir (estaba por debajo del nuevo Desde), eso dispara su propio
        # dateChanged -- el debounce coalesce ambos en una sola recarga en vez de dos.
        self._busqueda_dinamica()

    def _on_fecha_hasta_cambiada(self, fecha: QDate) -> None:
        self.fecha_desde_input.setMaximumDate(fecha)
        self._busqueda_dinamica()

    # ── Paginación ───────────────────────────────────────────────────────

    def _buscar_desde_inicio(self) -> None:
        self.pagina_actual = 1
        self.cargar_eventos()

    def _pagina_anterior(self) -> None:
        if self.pagina_actual > 1:
            self.pagina_actual -= 1
            self.cargar_eventos()

    def _pagina_siguiente(self) -> None:
        if self.pagina_actual < self.total_paginas:
            self.pagina_actual += 1
            self.cargar_eventos()

    # ── Lógica de datos ───────────────────────────────────────────────────

    def _cargar_usuarios_filtro(self) -> None:
        session = self.session_factory()
        try:
            usuarios = UsuarioService.listar_usuarios(session, id_usuario=self.usuario.id_usuario)
            for u in usuarios:
                nombre = u["nombre_completo"] or u["nombre_usuario"]
                self.usuario_combo.addItem(f"{nombre} ({u['nombre_usuario']})", u["id_usuario"])
        except PermisoDenegadoError:
            # El actor puede tener 'auditoria:ver' sin 'usuarios:ver' (roles distintos a
            # ADMIN, que si bypassa ambos) -- el filtro por usuario simplemente queda
            # reducido a "Todos los usuarios", no es un error del panel.
            pass
        except Exception:
            logger.exception("Fallo al cargar usuarios para el filtro de auditoria")
        finally:
            session.close()

    def cargar_eventos(self) -> None:
        session = self.session_factory()
        try:
            fecha_desde = datetime.combine(self.fecha_desde_input.date().toPython(), time.min)
            fecha_hasta = datetime.combine(self.fecha_hasta_input.date().toPython(), time.max)
            resultado = AuditoriaService.consultar_auditoria(
                session,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                id_usuario=self.usuario_combo.currentData(),
                modulo=self.modulo_combo.currentData(),
                texto_busqueda=self.buscar_input.text().strip() or None,
                pagina=self.pagina_actual,
                por_pagina=POR_PAGINA,
                id_usuario_actor=self.usuario.id_usuario,
            )
            self._poblar_tabla(resultado)
        except PermisoDenegadoError:
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar la auditoría.")
        except Exception:
            logger.exception("Fallo al cargar la bitácora de auditoría")
            QMessageBox.critical(self, "Error de conexión", "No se pudo cargar la bitácora de auditoría.")
        finally:
            session.close()

    def _poblar_tabla(self, resultado: dict) -> None:
        eventos: list[Auditoria] = resultado["items"]
        self._eventos_pagina = eventos
        self.tabla.setRowCount(len(eventos))
        for fila, evento in enumerate(eventos):
            fecha_texto = evento.fecha_evento.strftime("%d/%m/%Y %H:%M:%S") if evento.fecha_evento else "—"
            usuario_texto = evento.usuario.nombre_usuario if evento.usuario else "Sistema"
            self.tabla.setItem(fila, 0, QTableWidgetItem(fecha_texto))
            self.tabla.setItem(fila, 1, QTableWidgetItem(usuario_texto))
            self.tabla.setItem(fila, 2, QTableWidgetItem(evento.modulo))
            self.tabla.setItem(fila, 3, QTableWidgetItem(evento.accion))
            self.tabla.setItem(fila, 4, QTableWidgetItem(_resumir_detalle(evento.detalle)))

        total = resultado["total"]
        self.total_paginas = max(1, -(-total // POR_PAGINA))
        self.pagina_actual = min(self.pagina_actual, self.total_paginas)

        self.lbl_total.setText(f"{total} evento{'s' if total != 1 else ''}")
        self.lbl_pagina.setText(f"Página {self.pagina_actual} de {self.total_paginas}")
        self.btn_anterior.setEnabled(self.pagina_actual > 1)
        self.btn_siguiente.setEnabled(self.pagina_actual < self.total_paginas)

    def ver_detalle_seleccionado(self) -> None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            QMessageBox.information(self, "Selección requerida", "Selecciona un evento de la lista.")
            return
        evento = self._eventos_pagina[filas[0].row()]
        fecha_texto = evento.fecha_evento.strftime("%d/%m/%Y %H:%M:%S") if evento.fecha_evento else "—"
        usuario_texto = evento.usuario.nombre_usuario if evento.usuario else "Sistema"
        lineas_detalle = _formatear_detalle(evento.detalle)
        detalle_texto = (
            "\n".join(f"• {linea}" for linea in lineas_detalle) if lineas_detalle else "Sin información adicional."
        )
        cuerpo = (
            f"Fecha: {fecha_texto}\n"
            f"Usuario: {usuario_texto}\n"
            f"Módulo: {evento.modulo}\n"
            f"Acción: {evento.accion}\n\n"
            f"Detalle:\n{detalle_texto}"
        )
        QMessageBox.information(self, "Detalle del evento", cuerpo)
