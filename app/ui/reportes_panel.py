"""
Panel del modulo Reportes: primer consumidor de UI para ReporteService
(app/services/reportes.py), que hasta ahora solo tenia cobertura de tests.
Cubre los cuatro reportes ya resueltos en el servicio -- antiguedad de saldos
de cuentas por cobrar y por pagar (aging CxC/CxP), libro de ventas (base del
formato exigido por el SENIAT) y arqueo de caja -- ver
docs/CHECKLIST_PRODUCCION.md seccion "Reportes y Analitica" para el resto del
catalogo (kardex, conciliacion bancaria, comisiones, etc.) que se agrega en
pasos siguientes sobre esta misma pantalla.

Todos son acotados por naturaleza (cuentas abiertas, un rango de fechas, los
movimientos de un turno) asi que se cargan enteros via QueryWorker sin
paginacion -- ver R-04 en el checklist para cuando eso deje de ser cierto.
"""

import logging
from decimal import Decimal

import qtawesome as qta
from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtGui import QColor, QShowEvent, QTextCharFormat
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.db.models import Caja, Categoria, Cliente, CuentaBancaria, Inventario, Proveedor, Usuario, Vendedor
from app.services.empresa import EmpresaService
from app.services.exportacion import exportar_excel, exportar_pdf
from app.services.reportes import ReporteService
from app.ui.message_box import MessageBox
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_FIELD_BG,
    COLOR_PRIMARY,
    COLOR_PRIMARY_LIGHT,
    COLOR_SUCCESS,
    COLOR_TABLE_HEADER,
    COLOR_TABLE_SELECTED,
    COLOR_TEXT_DARK,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
    FONT_FAMILY,
    ICON_CHEVRON_DOWN_URL,
    TABLE_QSS,
    aplicar_sombra,
)
from app.ui.toolbar_popups import BotonExportar
from app.ui.workers import QueryWorker

logger = logging.getLogger(__name__)

REPORTE_AGING_CXC = "aging_cxc"
REPORTE_AGING_CXP = "aging_cxp"
REPORTE_LIBRO_VENTAS = "libro_ventas"
REPORTE_VENTAS_PERIODO = "ventas_periodo"
REPORTE_VENTAS_CLIENTE = "ventas_cliente"
REPORTE_VENTAS_VENDEDOR = "ventas_vendedor"
REPORTE_VENTAS_RUTA = "ventas_ruta"
REPORTE_PRODUCTOS_VENDIDOS = "productos_vendidos"
REPORTE_FACTURAS_ANULADAS = "facturas_anuladas"
REPORTE_NC_EMITIDAS = "nc_emitidas"
REPORTE_CONTADO_CREDITO = "contado_credito"
REPORTE_MARGEN_UTILIDAD = "margen_utilidad"
REPORTE_COMPRAS_PERIODO = "compras_periodo"
REPORTE_COMPRAS_PROVEEDOR = "compras_proveedor"
REPORTE_COMPRAS_PRODUCTO = "compras_producto"
REPORTE_OC_ABIERTAS = "oc_abiertas"
REPORTE_CUMPLIMIENTO_PROVEEDORES = "cumplimiento_proveedores"
REPORTE_DEVOLUCIONES_PROVEEDOR = "devoluciones_proveedor"
REPORTE_NC_PROVEEDOR = "nc_proveedor"
REPORTE_ARQUEO_CAJA = "arqueo_caja"
REPORTE_KARDEX = "kardex"
REPORTE_VALORIZACION = "valorizacion_inventario"
REPORTE_BAJO_MINIMO = "bajo_minimo"
REPORTE_SIN_MOVIMIENTO = "sin_movimiento"
REPORTE_HISTORICO_PRECIOS = "historico_precios"
REPORTE_ESTADO_CTA_CLIENTE = "estado_cuenta_cliente"
REPORTE_COBROS_PERIODO = "cobros_periodo"
REPORTE_CLIENTES_MOROSOS = "clientes_morosos"
REPORTE_CXC_OTRAS = "cxc_otras"
REPORTE_ESTADO_CTA_PROVEEDOR = "estado_cuenta_proveedor"
REPORTE_PAGOS_PERIODO = "pagos_periodo"
REPORTE_PROXIMOS_VENCIMIENTOS = "proximos_vencimientos"
REPORTE_CXP_OTRAS = "cxp_otras"
REPORTE_MOV_CAJA_PERIODO = "mov_caja_periodo"
REPORTE_CIERRE_CAJERO = "cierre_cajero"
REPORTE_FLUJO_CAJA = "flujo_caja"
REPORTE_MOV_CUENTA_BANCARIA = "mov_cuenta_bancaria"
REPORTE_CONCILIACION_BANCARIA = "conciliacion_bancaria"
REPORTE_SALDO_CONSOLIDADO = "saldo_consolidado"
REPORTE_COMISIONES_VENDEDOR = "comisiones_vendedor"
REPORTE_COMISIONES_PAGADAS_PENDIENTES = "comisiones_pagadas_pendientes"

COLS_AGING_CXC = ["Factura", "Cliente", "Vencimiento", "Saldo Pendiente", "Días Vencido", "Rango"]
COLS_AGING_CXP = ["Compra", "Proveedor", "Vencimiento", "Saldo Pendiente", "Días Vencido", "Rango"]
COLS_LIBRO_VENTAS = [
    "Fecha",
    "N° Control",
    "N° Factura",
    "Cliente",
    "RIF/Cédula",
    "Base Imponible",
    "% IVA",
    "IVA",
    "Total",
]
COLS_VENTAS_PERIODO = ["Fecha", "Facturas", "Total"]
COLS_VENTAS_CLIENTE = ["Cliente", "Facturas", "Total"]
COLS_VENTAS_VENDEDOR = ["Vendedor", "Facturas", "Total", "Ticket Promedio"]
COLS_VENTAS_RUTA = ["Ruta", "Facturas", "Total", "Ticket Promedio"]
COLS_PRODUCTOS_VENDIDOS = ["Producto", "Cantidad", "Total"]
COLS_FACTURAS_ANULADAS = ["N° Factura", "Cliente", "Vendedor", "Fecha", "Motivo"]
COLS_NC_EMITIDAS = ["N° NC", "Cliente", "Factura Origen", "Fecha", "Monto", "Saldo Disp.", "Estado"]
COLS_CONTADO_CREDITO = ["Condición", "Facturas", "Total", "% del Total"]
COLS_MARGEN_UTILIDAD = ["Producto", "Cantidad", "Ingreso", "Costo", "Margen $", "Margen %"]
COLS_COMPRAS_PERIODO = ["Fecha", "Compras", "Total"]
COLS_COMPRAS_PROVEEDOR = ["Proveedor", "Compras", "Total"]
COLS_COMPRAS_PRODUCTO = ["Producto", "Cantidad", "Total"]
COLS_OC_ABIERTAS = [
    "N° OC",
    "Proveedor",
    "Fecha OC",
    "Entrega Est.",
    "Solicitado",
    "Recibido",
    "Pendiente",
    "Estado",
    "Total OC",
    "Vencida",
]
COLS_CUMPLIMIENTO_PROVEEDORES = ["Proveedor", "OC", "A Tiempo", "Tardías", "Sin Fecha Est.", "% A Tiempo"]
COLS_DEVOLUCIONES_PROVEEDOR = ["N° Devolución", "Proveedor", "N° OC", "Fecha", "Motivo", "Cantidad", "Estado"]
COLS_NC_PROVEEDOR = ["ID NC", "Proveedor", "Compra Origen", "Fecha", "Monto", "Saldo Disp.", "Estado"]
COLS_ARQUEO_CAJA = ["Fecha", "Tipo", "Descripción", "Monto"]
COLS_KARDEX = ["Fecha", "Tipo", "Referencia", "Entrada", "Salida", "Saldo"]
COLS_VALORIZACION = ["Código", "Producto", "Categoría", "Cantidad", "Costo Unit.", "Valor Total"]
COLS_BAJO_MINIMO = ["Código", "Producto", "Categoría", "Cantidad", "Mínimo", "Déficit"]
COLS_SIN_MOVIMIENTO = ["Código", "Producto", "Categoría", "Cantidad", "Costo", "Último Movimiento"]
COLS_HISTORICO_PRECIOS = ["Fecha", "Precio Venta", "Margen %", "Usuario"]
COLS_ESTADO_CTA_CLIENTE = ["Fecha", "Tipo", "Referencia", "Cargo", "Abono", "Saldo"]
COLS_COBROS_PERIODO = ["Fecha", "Cliente", "Factura", "Método", "Moneda", "Monto"]
COLS_CLIENTES_MOROSOS = ["Cliente", "Saldo Vencido", "Días Vencido Máx.", "Facturas Vencidas"]
COLS_CXC_OTRAS = ["Cliente", "Descripción", "Emisión", "Vencimiento", "Monto Total", "Saldo Pendiente", "Estado"]

ETIQUETAS_ESTADO_CXC_OTRO = {"pendiente": "Pendiente", "parcial": "Parcial", "pagada": "Pagada", "vencida": "Vencida"}
COLS_ESTADO_CTA_PROVEEDOR = ["Fecha", "Tipo", "Referencia", "Cargo", "Abono", "Saldo"]
COLS_PAGOS_PERIODO = ["Fecha", "Proveedor", "Compra", "Método", "Monto"]
COLS_PROXIMOS_VENCIMIENTOS = ["Compra", "Proveedor", "Vencimiento", "Días para Vencer", "Saldo Pendiente"]
COLS_CXP_OTRAS = [
    "Cuenta Bancaria",
    "Referencia",
    "Descripción",
    "Recepción",
    "Cliente Identificado",
    "Monto Total",
    "Saldo Pendiente",
    "Estado",
]

ETIQUETAS_ESTADO_CXP_OTRO = {"pendiente": "Pendiente", "parcial": "Parcial", "conciliado": "Conciliado"}
COLS_MOV_CAJA_PERIODO = ["Fecha", "Caja", "Tipo", "Origen", "Descripción", "Monto"]
COLS_CIERRE_CAJERO = [
    "Caja",
    "Cajero",
    "Apertura",
    "Cierre",
    "Apertura $",
    "Entradas",
    "Salidas",
    "Esperado",
    "Cierre $",
    "Diferencia",
]
COLS_FLUJO_CAJA = ["Período", "Entradas Caja", "Salidas Caja", "Entradas Banco", "Salidas Banco", "Neto"]
COLS_MOV_CUENTA_BANCARIA = ["Fecha", "Tipo", "Referencia", "Descripción", "Monto", "Saldo"]
COLS_CONCILIACION_BANCARIA = ["Cuenta", "Pendiente", "Cant. Pendiente", "Conciliado", "Cant. Conciliada"]
COLS_SALDO_CONSOLIDADO = ["Banco", "Cuenta", "Tipo", "Titular", "Saldo"]
COLS_COMISIONES_VENDEDOR = ["Vendedor", "Facturas", "Comisión"]
COLS_COMISIONES_PAGADAS_PENDIENTES = ["Vendedor", "Pagado", "Pendiente"]

ETIQUETAS_ESTADO_NC = {"disponible": "Disponible", "aplicada": "Aplicada", "devuelta": "Devuelta"}
ETIQUETAS_ESTADO_OC = {"PENDIENTE": "Pendiente", "PARCIAL": "Parcial", "COMPLETA": "Completa", "ANULADA": "Anulada"}

BUCKETS_AGING = ["vigente", "1-30", "31-60", "61-90", "90+"]
ETIQUETAS_BUCKET = {
    "vigente": "Vigente",
    "1-30": "1-30 días",
    "31-60": "31-60 días",
    "61-90": "61-90 días",
    "90+": "90+ días",
}

# QDateEdit no hereda GLOBAL_QSS de forma confiable cuando se usa suelto en un toolbar --
# mismo motivo/mismo bloque que app/ui/auditoria_panel.py (cada panel con un QDateEdit
# suelto redefine esta regla en vez de confiar en la cascada, ver el comentario extenso
# alla).
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

# Mismo problema que FECHA_QSS de aca abajo, pero para QComboBox: heredar GLOBAL_QSS
# (fijado en MainWindow, no en QApplication) se vuelve fragil en cuanto un ancestro
# intermedio tiene su propio setStyleSheet() -- el combo en si se ve bien pero su POPUP
# (una ventana top-level aparte) cae al tema nativo, oscuro e ilegible (hallazgo del
# usuario, 2026-08-31, con el QStackedWidget que se uso primero para filtros_container).
# Mismo patron ya usado en config_empresa_panel.py (impresora_combo): copiar el bloque
# QComboBox de GLOBAL_QSS local en vez de confiar en la cascada, agregando ademas la
# regla de QAbstractItemView (el popup) que ese caso no necesitaba pero este si.
COMBO_QSS = f"""
QComboBox {{
    background-color: {COLOR_CARD_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 6px 28px 6px 12px;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
}}
QComboBox:hover {{
    border-color: {COLOR_TEXT_MUTED};
}}
QComboBox:focus {{
    border-color: {COLOR_PRIMARY};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border: none;
    background: transparent;
}}
QComboBox::down-arrow {{
    image: url({ICON_CHEVRON_DOWN_URL});
    width: 12px;
    height: 12px;
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {COLOR_CARD_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 4px;
    outline: none;
    selection-background-color: {COLOR_TABLE_SELECTED};
    selection-color: {COLOR_TEXT_DARK};
}}
"""

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


# Reusado solo en los filtros nuevos (Ventas) -- los cuatro filtros originales
# (aging/libro de ventas/arqueo) repiten el mismo literal inline y no se tocaron, para no
# ensuciar un diff de una funcionalidad ya probada con un cambio puramente cosmetico.
LABEL_QSS = f"border: none; background: transparent; color: {COLOR_TEXT_DARK}; font-weight: 600;"


def _crear_fecha_edit(dias_atras: int = 0, ancho: int = 120) -> QDateEdit:
    fecha = QDateEdit()
    fecha.setCalendarPopup(True)
    fecha.setDisplayFormat("dd/MM/yyyy")
    fecha.setDate(QDate.currentDate().addDays(-dias_atras))
    fecha.setFixedHeight(32)
    fecha.setFixedWidth(ancho)
    _estilizar_fecha(fecha)
    return fecha


def _crear_combo(ancho: int | None = None) -> QComboBox:
    combo = QComboBox()
    combo.setStyleSheet(COMBO_QSS)
    if ancho:
        combo.setFixedWidth(ancho)
    return combo


def _estilizar_fecha(date_edit: QDateEdit) -> None:
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


def _tarea_aging_cxc(session, id_usuario, fecha_corte, id_cliente, orden):
    return ReporteService.aging_cuentas_por_cobrar(
        session, id_usuario=id_usuario, fecha_corte=fecha_corte, id_cliente=id_cliente, orden=orden
    )


def _tarea_aging_cxp(session, id_usuario, fecha_corte, id_proveedor, orden):
    return ReporteService.aging_cuentas_por_pagar(
        session, id_usuario=id_usuario, fecha_corte=fecha_corte, id_proveedor=id_proveedor, orden=orden
    )


def _tarea_libro_ventas(session, id_usuario, fecha_desde, fecha_hasta, id_cliente):
    return ReporteService.libro_ventas(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, id_cliente=id_cliente
    )


def _tarea_ventas_periodo(session, id_usuario, fecha_desde, fecha_hasta, agrupacion):
    return ReporteService.ventas_por_periodo(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, agrupacion=agrupacion
    )


def _tarea_ventas_cliente(session, id_usuario, fecha_desde, fecha_hasta):
    return ReporteService.ventas_por_cliente(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta
    )


def _tarea_ventas_vendedor(session, id_usuario, fecha_desde, fecha_hasta):
    return ReporteService.ventas_por_vendedor(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta
    )


def _tarea_ventas_ruta(session, id_usuario, fecha_desde, fecha_hasta):
    return ReporteService.ventas_por_ruta(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta
    )


def _tarea_productos_vendidos(session, id_usuario, fecha_desde, fecha_hasta, orden):
    return ReporteService.productos_mas_vendidos(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, orden=orden
    )


def _tarea_facturas_anuladas(session, id_usuario, fecha_desde, fecha_hasta):
    return ReporteService.facturas_anuladas(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta
    )


def _tarea_nc_emitidas(session, id_usuario, fecha_desde, fecha_hasta, id_cliente):
    return ReporteService.notas_credito_emitidas(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, id_cliente=id_cliente
    )


def _tarea_contado_credito(session, id_usuario, fecha_desde, fecha_hasta):
    return ReporteService.ventas_contado_vs_credito(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta
    )


def _tarea_margen_utilidad(session, id_usuario, fecha_desde, fecha_hasta):
    return ReporteService.margen_utilidad_productos(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta
    )


def _tarea_compras_periodo(session, id_usuario, fecha_desde, fecha_hasta, agrupacion):
    return ReporteService.compras_por_periodo(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, agrupacion=agrupacion
    )


def _tarea_compras_proveedor(session, id_usuario, fecha_desde, fecha_hasta):
    return ReporteService.compras_por_proveedor(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta
    )


def _tarea_compras_producto(session, id_usuario, fecha_desde, fecha_hasta, orden):
    return ReporteService.compras_por_producto(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, orden=orden
    )


def _tarea_oc_abiertas(session, id_usuario, id_proveedor):
    return ReporteService.ordenes_compra_abiertas(session, id_usuario=id_usuario, id_proveedor=id_proveedor)


def _tarea_cumplimiento_proveedores(session, id_usuario, fecha_desde, fecha_hasta):
    return ReporteService.cumplimiento_proveedores(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta
    )


def _tarea_devoluciones_proveedor(session, id_usuario, fecha_desde, fecha_hasta, id_proveedor):
    return ReporteService.devoluciones_proveedor(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, id_proveedor=id_proveedor
    )


def _tarea_nc_proveedor(session, id_usuario, fecha_desde, fecha_hasta, id_proveedor):
    return ReporteService.notas_credito_proveedor(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, id_proveedor=id_proveedor
    )


def _tarea_arqueo_caja(session, id_usuario, id_caja):
    return ReporteService.arqueo_caja(session, id_usuario=id_usuario, id_caja=id_caja)


def _tarea_kardex(session, id_usuario, id_producto, fecha_desde, fecha_hasta):
    return ReporteService.kardex_producto(
        session, id_usuario=id_usuario, id_producto=id_producto, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta
    )


def _tarea_valorizacion_inventario(session, id_usuario, id_categoria):
    return ReporteService.valorizacion_inventario(session, id_usuario=id_usuario, id_categoria=id_categoria)


def _tarea_bajo_minimo(session, id_usuario, id_categoria):
    return ReporteService.productos_bajo_minimo(session, id_usuario=id_usuario, id_categoria=id_categoria)


def _tarea_sin_movimiento(session, id_usuario, fecha_desde, fecha_hasta, id_categoria):
    return ReporteService.productos_sin_movimiento(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, id_categoria=id_categoria
    )


def _tarea_historico_precios(session, id_usuario, id_producto):
    return ReporteService.historico_precios(session, id_usuario=id_usuario, id_producto=id_producto)


def _tarea_estado_cuenta_cliente(session, id_usuario, id_cliente, fecha_desde, fecha_hasta):
    return ReporteService.estado_cuenta_cliente(
        session, id_usuario=id_usuario, id_cliente=id_cliente, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta
    )


def _tarea_cobros_periodo(session, id_usuario, fecha_desde, fecha_hasta, id_cliente):
    return ReporteService.cobros_del_periodo(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, id_cliente=id_cliente
    )


def _tarea_clientes_morosos(session, id_usuario, fecha_corte):
    return ReporteService.clientes_morosos(session, id_usuario=id_usuario, fecha_corte=fecha_corte)


def _tarea_cxc_otras(session, id_usuario, id_cliente, estado):
    return ReporteService.cxc_otras(session, id_usuario=id_usuario, id_cliente=id_cliente, estado=estado)


def _tarea_estado_cuenta_proveedor(session, id_usuario, id_proveedor, fecha_desde, fecha_hasta):
    return ReporteService.estado_cuenta_proveedor(
        session, id_usuario=id_usuario, id_proveedor=id_proveedor, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta
    )


def _tarea_pagos_periodo(session, id_usuario, fecha_desde, fecha_hasta, id_proveedor):
    return ReporteService.pagos_del_periodo(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, id_proveedor=id_proveedor
    )


def _tarea_proximos_vencimientos(session, id_usuario, dias_horizonte, id_proveedor):
    return ReporteService.proximos_vencimientos(
        session, id_usuario=id_usuario, dias_horizonte=dias_horizonte, id_proveedor=id_proveedor
    )


def _tarea_cxp_otras(session, id_usuario, id_cuenta_bancaria, estado):
    return ReporteService.cxp_otras(
        session, id_usuario=id_usuario, id_cuenta_bancaria=id_cuenta_bancaria, estado=estado
    )


def _tarea_mov_caja_periodo(session, id_usuario, fecha_desde, fecha_hasta, id_caja, tipo_movimiento):
    return ReporteService.movimientos_caja_periodo(
        session,
        id_usuario=id_usuario,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        id_caja=id_caja,
        tipo_movimiento=tipo_movimiento,
    )


def _tarea_cierre_cajero(session, id_usuario, fecha_desde, fecha_hasta, id_usuario_cajero):
    return ReporteService.cierre_diario_por_cajero(
        session,
        id_usuario=id_usuario,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        id_usuario_cajero=id_usuario_cajero,
    )


def _tarea_flujo_caja(session, id_usuario, fecha_desde, fecha_hasta, agrupacion):
    return ReporteService.flujo_caja_consolidado(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, agrupacion=agrupacion
    )


def _tarea_mov_cuenta_bancaria(session, id_usuario, id_cuenta_bancaria, fecha_desde, fecha_hasta):
    return ReporteService.movimientos_cuenta_bancaria(
        session,
        id_usuario=id_usuario,
        id_cuenta_bancaria=id_cuenta_bancaria,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )


def _tarea_conciliacion_bancaria(session, id_usuario, id_cuenta_bancaria):
    return ReporteService.conciliacion_bancaria(session, id_usuario=id_usuario, id_cuenta_bancaria=id_cuenta_bancaria)


def _tarea_saldo_consolidado(session, id_usuario):
    return ReporteService.saldo_consolidado(session, id_usuario=id_usuario)


def _tarea_comisiones_vendedor(session, id_usuario, fecha_desde, fecha_hasta, id_vendedor):
    return ReporteService.comisiones_por_vendedor_periodo(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, id_vendedor=id_vendedor
    )


def _tarea_comisiones_pagadas_pendientes(session, id_usuario, fecha_desde, fecha_hasta, id_vendedor):
    return ReporteService.comisiones_pagadas_vs_pendientes(
        session, id_usuario=id_usuario, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, id_vendedor=id_vendedor
    )


class ReportesPanel(QWidget):
    """Panel principal del modulo Reportes: selector de reporte + filtros propios de
    cada uno + tabla de resultados + exportacion a Excel/PDF."""

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self._ultimo_modo: str | None = None
        self._ultimo_resultado: dict | None = None
        self.setObjectName("ContentArea")
        self._setup_ui()
        self._cargar_clientes()
        self._cargar_proveedores()
        self._cargar_cajas()
        self._cargar_productos()
        self._cargar_categorias()
        self._cargar_cuentas_bancarias()
        self._cargar_usuarios_cajero()
        self._cargar_vendedores()
        QTimer.singleShot(100, self._generar)

    def showEvent(self, event: QShowEvent) -> None:
        # Mismo patron que el resto de los paneles (dashboard, facturacion, clientes...):
        # sin esto, volver a "Reportes" desde otro modulo mostraria datos ya viejos.
        super().showEvent(event)
        self._generar()

    # ── Construcción de la UI ─────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        root.addWidget(self._make_header())
        root.addWidget(self._make_toolbar())
        root.addWidget(self._make_resumen())
        root.addWidget(self._make_table(), stretch=1)

        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

    def _make_header(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.chart-bar", color=COLOR_PRIMARY).pixmap(28, 28))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 2px solid #BFDBFE; border-radius: 12px; padding: 8px;"
        )
        icon_lbl.setFixedSize(48, 48)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        lbl_titulo = QLabel("Reportes")
        lbl_titulo.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        lbl_subtitulo = QLabel("Reportes financieros y de cumplimiento fiscal")
        lbl_subtitulo.setStyleSheet(f"font-size: 13px; color: {COLOR_TEXT_MUTED};")
        titles.addWidget(lbl_titulo)
        titles.addWidget(lbl_subtitulo)

        self.lbl_total = QLabel("Cargando…")
        self.lbl_total.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 13px;"
            f" background-color: {COLOR_TABLE_HEADER}; border-radius: 10px;"
            " padding: 3px 10px;"
        )

        h.addWidget(icon_lbl)
        h.addLayout(titles)
        h.addStretch()
        h.addWidget(self.lbl_total)
        return w

    def _make_toolbar(self) -> QWidget:
        # Dos filas, no una: con 41 reportes la fila de filtros mas ancha (Movimientos de
        # Caja por Periodo, 4 campos) mide ~880px de sizeHint por si sola. Sumada en una
        # sola fila junto al combo de tipo (~380px, "Comisiones Pagadas vs. Pendientes")
        # y los botones Generar/Exportar (~265px), el minimo de esa fila superaba
        # los 1600px -- mas ancho que la ventana por defecto (1200px) y que el minimo
        # (900px), asi que Qt terminaba comprimiendo/truncando los campos (texto cortado
        # tipo "24/08/20" o "TODOS LOS CLIEI") en vez de mostrarlos completos. Partir en
        # dos filas acota el ancho minimo real al MAX de cada fila por separado (~880px)
        # en vez de la SUMA de ambas (~1600px+), hallazgo del usuario 2026-08-31.
        w = QWidget()
        w.setStyleSheet(
            f"background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 8px; padding: 4px;"
        )
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(8)

        fila_tipo = QWidget()
        fila_tipo.setStyleSheet("background: transparent;")
        h = QHBoxLayout(fila_tipo)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)

        lbl_reporte = QLabel("Reporte:")
        lbl_reporte.setStyleSheet(f"border: none; background: transparent; color: {COLOR_TEXT_DARK}; font-weight: 600;")
        self.tipo_combo = QComboBox()
        self.tipo_combo.setStyleSheet(COMBO_QSS)
        self.tipo_combo.addItem("Antigüedad de Saldos (CxC)", REPORTE_AGING_CXC)
        self.tipo_combo.addItem("Antigüedad de Saldos (CxP)", REPORTE_AGING_CXP)
        self.tipo_combo.addItem("Libro de Ventas (SENIAT)", REPORTE_LIBRO_VENTAS)
        self.tipo_combo.addItem("Ventas por Período", REPORTE_VENTAS_PERIODO)
        self.tipo_combo.addItem("Ventas por Cliente", REPORTE_VENTAS_CLIENTE)
        self.tipo_combo.addItem("Ventas por Vendedor", REPORTE_VENTAS_VENDEDOR)
        self.tipo_combo.addItem("Ventas por Ruta", REPORTE_VENTAS_RUTA)
        self.tipo_combo.addItem("Productos Más/Menos Vendidos", REPORTE_PRODUCTOS_VENDIDOS)
        self.tipo_combo.addItem("Facturas Anuladas", REPORTE_FACTURAS_ANULADAS)
        self.tipo_combo.addItem("Notas de Crédito Emitidas", REPORTE_NC_EMITIDAS)
        self.tipo_combo.addItem("Ventas Contado vs. Crédito", REPORTE_CONTADO_CREDITO)
        self.tipo_combo.addItem("Margen de Utilidad por Producto", REPORTE_MARGEN_UTILIDAD)
        self.tipo_combo.addItem("Compras por Período", REPORTE_COMPRAS_PERIODO)
        self.tipo_combo.addItem("Compras por Proveedor", REPORTE_COMPRAS_PROVEEDOR)
        self.tipo_combo.addItem("Compras por Producto", REPORTE_COMPRAS_PRODUCTO)
        self.tipo_combo.addItem("Órdenes de Compra Abiertas", REPORTE_OC_ABIERTAS)
        self.tipo_combo.addItem("Cumplimiento de Proveedores", REPORTE_CUMPLIMIENTO_PROVEEDORES)
        self.tipo_combo.addItem("Devoluciones a Proveedor", REPORTE_DEVOLUCIONES_PROVEEDOR)
        self.tipo_combo.addItem("Notas de Crédito de Proveedor", REPORTE_NC_PROVEEDOR)
        self.tipo_combo.addItem("Arqueo de Caja", REPORTE_ARQUEO_CAJA)
        self.tipo_combo.addItem("Kardex de Producto", REPORTE_KARDEX)
        self.tipo_combo.addItem("Valorización de Inventario", REPORTE_VALORIZACION)
        self.tipo_combo.addItem("Stock Bajo Mínimo", REPORTE_BAJO_MINIMO)
        self.tipo_combo.addItem("Productos sin Movimiento", REPORTE_SIN_MOVIMIENTO)
        self.tipo_combo.addItem("Histórico de Precios", REPORTE_HISTORICO_PRECIOS)
        self.tipo_combo.addItem("Estado de Cuenta por Cliente", REPORTE_ESTADO_CTA_CLIENTE)
        self.tipo_combo.addItem("Cobros del Período", REPORTE_COBROS_PERIODO)
        self.tipo_combo.addItem("Clientes Morosos", REPORTE_CLIENTES_MOROSOS)
        self.tipo_combo.addItem("CxC Otras", REPORTE_CXC_OTRAS)
        self.tipo_combo.addItem("Estado de Cuenta por Proveedor", REPORTE_ESTADO_CTA_PROVEEDOR)
        self.tipo_combo.addItem("Pagos del Período", REPORTE_PAGOS_PERIODO)
        self.tipo_combo.addItem("Próximos Vencimientos (CxP)", REPORTE_PROXIMOS_VENCIMIENTOS)
        self.tipo_combo.addItem("CxP Otras", REPORTE_CXP_OTRAS)
        self.tipo_combo.addItem("Movimientos de Caja por Período", REPORTE_MOV_CAJA_PERIODO)
        self.tipo_combo.addItem("Cierre Diario por Cajero", REPORTE_CIERRE_CAJERO)
        self.tipo_combo.addItem("Flujo de Caja Consolidado", REPORTE_FLUJO_CAJA)
        self.tipo_combo.addItem("Movimientos por Cuenta Bancaria", REPORTE_MOV_CUENTA_BANCARIA)
        self.tipo_combo.addItem("Conciliación Bancaria", REPORTE_CONCILIACION_BANCARIA)
        self.tipo_combo.addItem("Saldo Consolidado", REPORTE_SALDO_CONSOLIDADO)
        self.tipo_combo.addItem("Comisiones por Vendedor/Período", REPORTE_COMISIONES_VENDEDOR)
        self.tipo_combo.addItem("Comisiones Pagadas vs. Pendientes", REPORTE_COMISIONES_PAGADAS_PENDIENTES)
        self.tipo_combo.currentIndexChanged.connect(self._on_tipo_cambiado)

        # Con 41 reportes en un solo combo plano, encontrar uno por nombre exacto en la
        # lista es lento -- setEditable + QCompleter con MatchContains permite escribir
        # cualquier parte del nombre para saltar directo (ej. "caja" filtra Arqueo de Caja/
        # Movimientos de Caja/Cierre por Cajero/Flujo de Caja). InsertPolicy.NoInsert +
        # el comportamiento nativo de Qt evitan que quede texto libre sin corresponder a
        # ningun item: si no hay match exacto al perder foco, revierte al item ya
        # seleccionado (hallazgo de auditoria UX, 2026-09-01).
        self.tipo_combo.setEditable(True)
        self.tipo_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.tipo_combo.lineEdit().setPlaceholderText("Buscar reporte…")
        completer = QCompleter([self.tipo_combo.itemText(i) for i in range(self.tipo_combo.count())], self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.tipo_combo.setCompleter(completer)

        # QStackedWidget (usado antes aca) hereda de QFrame, y anidado dentro del
        # QStackedWidget de MainWindow (el que conmuta entre modulos), Qt le pinta un
        # frame por defecto pese a frameShape=NoFrame y sin ninguna regla QSS que lo pida
        # -- confirmado pintando el widget de rojo y viendo que coincidia exacto con la
        # caja que reportaba el usuario (2026-08-31). No es arreglable via QSS de forma
        # confiable, asi que en vez de pelear con eso se cambia de enfoque: un QWidget
        # simple (sin ascendencia QFrame, cero nocion de "frame") con una pagina de
        # filtros por reporte, alternando con setVisible() en vez de QStackedWidget.
        self.filtros_container = QWidget()
        self.filtros_container.setStyleSheet("background: transparent;")
        filtros_layout = QHBoxLayout(self.filtros_container)
        filtros_layout.setContentsMargins(0, 0, 0, 0)
        filtros_layout.setSpacing(0)
        self._filtros_paginas = {
            REPORTE_AGING_CXC: self._make_filtros_aging(),
            REPORTE_AGING_CXP: self._make_filtros_aging_cxp(),
            REPORTE_LIBRO_VENTAS: self._make_filtros_libro_ventas(),
            REPORTE_VENTAS_PERIODO: self._make_filtros_ventas_periodo(),
            REPORTE_VENTAS_CLIENTE: self._make_filtros_ventas_cliente(),
            REPORTE_VENTAS_VENDEDOR: self._make_filtros_ventas_vendedor(),
            REPORTE_VENTAS_RUTA: self._make_filtros_ventas_ruta(),
            REPORTE_PRODUCTOS_VENDIDOS: self._make_filtros_productos_vendidos(),
            REPORTE_FACTURAS_ANULADAS: self._make_filtros_facturas_anuladas(),
            REPORTE_NC_EMITIDAS: self._make_filtros_nc_emitidas(),
            REPORTE_CONTADO_CREDITO: self._make_filtros_contado_credito(),
            REPORTE_MARGEN_UTILIDAD: self._make_filtros_margen_utilidad(),
            REPORTE_COMPRAS_PERIODO: self._make_filtros_compras_periodo(),
            REPORTE_COMPRAS_PROVEEDOR: self._make_filtros_compras_proveedor(),
            REPORTE_COMPRAS_PRODUCTO: self._make_filtros_compras_producto(),
            REPORTE_OC_ABIERTAS: self._make_filtros_oc_abiertas(),
            REPORTE_CUMPLIMIENTO_PROVEEDORES: self._make_filtros_cumplimiento_proveedores(),
            REPORTE_DEVOLUCIONES_PROVEEDOR: self._make_filtros_devoluciones_proveedor(),
            REPORTE_NC_PROVEEDOR: self._make_filtros_nc_proveedor(),
            REPORTE_ARQUEO_CAJA: self._make_filtros_arqueo(),
            REPORTE_KARDEX: self._make_filtros_kardex(),
            REPORTE_VALORIZACION: self._make_filtros_valorizacion(),
            REPORTE_BAJO_MINIMO: self._make_filtros_bajo_minimo(),
            REPORTE_SIN_MOVIMIENTO: self._make_filtros_sin_movimiento(),
            REPORTE_HISTORICO_PRECIOS: self._make_filtros_historico_precios(),
            REPORTE_ESTADO_CTA_CLIENTE: self._make_filtros_estado_cuenta_cliente(),
            REPORTE_COBROS_PERIODO: self._make_filtros_cobros_periodo(),
            REPORTE_CLIENTES_MOROSOS: self._make_filtros_clientes_morosos(),
            REPORTE_CXC_OTRAS: self._make_filtros_cxc_otras(),
            REPORTE_ESTADO_CTA_PROVEEDOR: self._make_filtros_estado_cuenta_proveedor(),
            REPORTE_PAGOS_PERIODO: self._make_filtros_pagos_periodo(),
            REPORTE_PROXIMOS_VENCIMIENTOS: self._make_filtros_proximos_vencimientos(),
            REPORTE_CXP_OTRAS: self._make_filtros_cxp_otras(),
            REPORTE_MOV_CAJA_PERIODO: self._make_filtros_mov_caja_periodo(),
            REPORTE_CIERRE_CAJERO: self._make_filtros_cierre_cajero(),
            REPORTE_FLUJO_CAJA: self._make_filtros_flujo_caja(),
            REPORTE_MOV_CUENTA_BANCARIA: self._make_filtros_mov_cuenta_bancaria(),
            REPORTE_CONCILIACION_BANCARIA: self._make_filtros_conciliacion_bancaria(),
            REPORTE_SALDO_CONSOLIDADO: self._make_filtros_saldo_consolidado(),
            REPORTE_COMISIONES_VENDEDOR: self._make_filtros_comisiones_vendedor(),
            REPORTE_COMISIONES_PAGADAS_PENDIENTES: self._make_filtros_comisiones_pagadas_pendientes(),
        }
        for modo, pagina in self._filtros_paginas.items():
            filtros_layout.addWidget(pagina)
            pagina.setVisible(modo == REPORTE_AGING_CXC)

        self.btn_generar = QPushButton(" Generar")
        self.btn_generar.setIcon(qta.icon("fa5s.play", color="white"))
        self.btn_generar.setStyleSheet(BUTTON_PRIMARY_QSS)
        self.btn_generar.clicked.connect(self._generar)

        self.btn_exportar = BotonExportar(on_excel=self._exportar_excel, on_pdf=self._exportar_pdf)

        h.addWidget(lbl_reporte)
        h.addWidget(self.tipo_combo)
        h.addStretch()
        h.addWidget(self.btn_generar)
        h.addWidget(self.btn_exportar)

        fila_filtros = QWidget()
        fila_filtros.setStyleSheet("background: transparent;")
        h_filtros = QHBoxLayout(fila_filtros)
        h_filtros.setContentsMargins(0, 0, 0, 0)
        h_filtros.setSpacing(0)
        h_filtros.addWidget(self.filtros_container)
        h_filtros.addStretch()

        v.addWidget(fila_tipo)
        v.addWidget(fila_filtros)
        return w

    def _make_filtros_aging(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_corte = QLabel("Corte:")
        lbl_corte.setStyleSheet(f"border: none; background: transparent; color: {COLOR_TEXT_DARK}; font-weight: 600;")
        self.fecha_corte_input = QDateEdit()
        self.fecha_corte_input.setCalendarPopup(True)
        self.fecha_corte_input.setDisplayFormat("dd/MM/yyyy")
        self.fecha_corte_input.setDate(QDate.currentDate())
        self.fecha_corte_input.setFixedHeight(32)
        self.fecha_corte_input.setFixedWidth(120)
        _estilizar_fecha(self.fecha_corte_input)

        lbl_cliente = QLabel("Cliente:")
        lbl_cliente.setStyleSheet(f"border: none; background: transparent; color: {COLOR_TEXT_DARK}; font-weight: 600;")
        self.cliente_combo = QComboBox()
        self.cliente_combo.setStyleSheet(COMBO_QSS)
        self.cliente_combo.setFixedWidth(200)

        lbl_orden = QLabel("Orden:")
        lbl_orden.setStyleSheet(f"border: none; background: transparent; color: {COLOR_TEXT_DARK}; font-weight: 600;")
        self.orden_combo = QComboBox()
        self.orden_combo.setStyleSheet(COMBO_QSS)
        self.orden_combo.addItem("Vencimiento", "fecha_vencimiento")
        self.orden_combo.addItem("Saldo pendiente", "saldo_pendiente")

        h.addWidget(lbl_corte)
        h.addWidget(self.fecha_corte_input)
        h.addWidget(lbl_cliente)
        h.addWidget(self.cliente_combo)
        h.addWidget(lbl_orden)
        h.addWidget(self.orden_combo)
        return w

    def _make_filtros_aging_cxp(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_corte = QLabel("Corte:")
        lbl_corte.setStyleSheet(f"border: none; background: transparent; color: {COLOR_TEXT_DARK}; font-weight: 600;")
        self.fecha_corte_cxp_input = QDateEdit()
        self.fecha_corte_cxp_input.setCalendarPopup(True)
        self.fecha_corte_cxp_input.setDisplayFormat("dd/MM/yyyy")
        self.fecha_corte_cxp_input.setDate(QDate.currentDate())
        self.fecha_corte_cxp_input.setFixedHeight(32)
        self.fecha_corte_cxp_input.setFixedWidth(120)
        _estilizar_fecha(self.fecha_corte_cxp_input)

        lbl_proveedor = QLabel("Proveedor:")
        lbl_proveedor.setStyleSheet(
            f"border: none; background: transparent; color: {COLOR_TEXT_DARK}; font-weight: 600;"
        )
        self.proveedor_combo = QComboBox()
        self.proveedor_combo.setStyleSheet(COMBO_QSS)
        self.proveedor_combo.setFixedWidth(200)

        lbl_orden = QLabel("Orden:")
        lbl_orden.setStyleSheet(f"border: none; background: transparent; color: {COLOR_TEXT_DARK}; font-weight: 600;")
        self.orden_cxp_combo = QComboBox()
        self.orden_cxp_combo.setStyleSheet(COMBO_QSS)
        self.orden_cxp_combo.addItem("Vencimiento", "fecha_vencimiento")
        self.orden_cxp_combo.addItem("Saldo pendiente", "saldo_pendiente")

        h.addWidget(lbl_corte)
        h.addWidget(self.fecha_corte_cxp_input)
        h.addWidget(lbl_proveedor)
        h.addWidget(self.proveedor_combo)
        h.addWidget(lbl_orden)
        h.addWidget(self.orden_cxp_combo)
        return w

    def _make_filtros_libro_ventas(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(f"border: none; background: transparent; color: {COLOR_TEXT_DARK}; font-weight: 600;")
        self.fecha_desde_lv_input = QDateEdit()
        self.fecha_desde_lv_input.setCalendarPopup(True)
        self.fecha_desde_lv_input.setDisplayFormat("dd/MM/yyyy")
        self.fecha_desde_lv_input.setDate(QDate.currentDate().addDays(-30))
        self.fecha_desde_lv_input.setFixedHeight(32)
        self.fecha_desde_lv_input.setFixedWidth(120)
        _estilizar_fecha(self.fecha_desde_lv_input)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(f"border: none; background: transparent; color: {COLOR_TEXT_DARK}; font-weight: 600;")
        self.fecha_hasta_lv_input = QDateEdit()
        self.fecha_hasta_lv_input.setCalendarPopup(True)
        self.fecha_hasta_lv_input.setDisplayFormat("dd/MM/yyyy")
        self.fecha_hasta_lv_input.setDate(QDate.currentDate())
        self.fecha_hasta_lv_input.setFixedHeight(32)
        self.fecha_hasta_lv_input.setFixedWidth(120)
        _estilizar_fecha(self.fecha_hasta_lv_input)

        lbl_cliente = QLabel("Cliente:")
        lbl_cliente.setStyleSheet(f"border: none; background: transparent; color: {COLOR_TEXT_DARK}; font-weight: 600;")
        self.cliente_combo_lv = QComboBox()
        self.cliente_combo_lv.setStyleSheet(COMBO_QSS)
        self.cliente_combo_lv.setFixedWidth(200)

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_lv_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_lv_input)
        h.addWidget(lbl_cliente)
        h.addWidget(self.cliente_combo_lv)
        return w

    def _make_filtros_ventas_periodo(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_vp_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_vp_input = _crear_fecha_edit()

        lbl_agrup = QLabel("Agrupar:")
        lbl_agrup.setStyleSheet(LABEL_QSS)
        self.agrupacion_combo = _crear_combo()
        self.agrupacion_combo.addItem("Día", "dia")
        self.agrupacion_combo.addItem("Mes", "mes")

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_vp_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_vp_input)
        h.addWidget(lbl_agrup)
        h.addWidget(self.agrupacion_combo)
        return w

    def _make_filtros_ventas_cliente(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_vc_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_vc_input = _crear_fecha_edit()

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_vc_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_vc_input)
        return w

    def _make_filtros_ventas_vendedor(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_vv_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_vv_input = _crear_fecha_edit()

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_vv_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_vv_input)
        return w

    def _make_filtros_ventas_ruta(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_vr_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_vr_input = _crear_fecha_edit()

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_vr_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_vr_input)
        return w

    def _make_filtros_productos_vendidos(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_pv_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_pv_input = _crear_fecha_edit()

        lbl_orden = QLabel("Orden:")
        lbl_orden.setStyleSheet(LABEL_QSS)
        self.orden_productos_combo = _crear_combo()
        self.orden_productos_combo.addItem("Más vendidos", "desc")
        self.orden_productos_combo.addItem("Menos vendidos", "asc")

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_pv_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_pv_input)
        h.addWidget(lbl_orden)
        h.addWidget(self.orden_productos_combo)
        return w

    def _make_filtros_facturas_anuladas(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_fa_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_fa_input = _crear_fecha_edit()

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_fa_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_fa_input)
        return w

    def _make_filtros_nc_emitidas(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_nc_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_nc_input = _crear_fecha_edit()

        lbl_cliente = QLabel("Cliente:")
        lbl_cliente.setStyleSheet(LABEL_QSS)
        self.cliente_combo_nc = _crear_combo(ancho=200)

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_nc_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_nc_input)
        h.addWidget(lbl_cliente)
        h.addWidget(self.cliente_combo_nc)
        return w

    def _make_filtros_contado_credito(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_cc_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_cc_input = _crear_fecha_edit()

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_cc_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_cc_input)
        return w

    def _make_filtros_margen_utilidad(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_mu_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_mu_input = _crear_fecha_edit()

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_mu_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_mu_input)
        return w

    def _make_filtros_compras_periodo(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_cp_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_cp_input = _crear_fecha_edit()

        lbl_agrup = QLabel("Agrupar:")
        lbl_agrup.setStyleSheet(LABEL_QSS)
        self.agrupacion_compras_combo = _crear_combo()
        self.agrupacion_compras_combo.addItem("Día", "dia")
        self.agrupacion_compras_combo.addItem("Mes", "mes")

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_cp_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_cp_input)
        h.addWidget(lbl_agrup)
        h.addWidget(self.agrupacion_compras_combo)
        return w

    def _make_filtros_compras_proveedor(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_cpv_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_cpv_input = _crear_fecha_edit()

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_cpv_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_cpv_input)
        return w

    def _make_filtros_compras_producto(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_cpp_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_cpp_input = _crear_fecha_edit()

        lbl_orden = QLabel("Orden:")
        lbl_orden.setStyleSheet(LABEL_QSS)
        self.orden_compras_producto_combo = _crear_combo()
        self.orden_compras_producto_combo.addItem("Más comprados", "desc")
        self.orden_compras_producto_combo.addItem("Menos comprados", "asc")

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_cpp_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_cpp_input)
        h.addWidget(lbl_orden)
        h.addWidget(self.orden_compras_producto_combo)
        return w

    def _make_filtros_oc_abiertas(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_proveedor = QLabel("Proveedor:")
        lbl_proveedor.setStyleSheet(LABEL_QSS)
        self.proveedor_combo_oc = _crear_combo(ancho=200)

        h.addWidget(lbl_proveedor)
        h.addWidget(self.proveedor_combo_oc)
        return w

    def _make_filtros_cumplimiento_proveedores(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_cump_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_cump_input = _crear_fecha_edit()

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_cump_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_cump_input)
        return w

    def _make_filtros_devoluciones_proveedor(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_dp_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_dp_input = _crear_fecha_edit()

        lbl_proveedor = QLabel("Proveedor:")
        lbl_proveedor.setStyleSheet(LABEL_QSS)
        self.proveedor_combo_dp = _crear_combo(ancho=200)

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_dp_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_dp_input)
        h.addWidget(lbl_proveedor)
        h.addWidget(self.proveedor_combo_dp)
        return w

    def _make_filtros_nc_proveedor(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_ncp_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_ncp_input = _crear_fecha_edit()

        lbl_proveedor = QLabel("Proveedor:")
        lbl_proveedor.setStyleSheet(LABEL_QSS)
        self.proveedor_combo_ncp = _crear_combo(ancho=200)

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_ncp_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_ncp_input)
        h.addWidget(lbl_proveedor)
        h.addWidget(self.proveedor_combo_ncp)
        return w

    def _make_filtros_arqueo(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_caja = QLabel("Caja:")
        lbl_caja.setStyleSheet(f"border: none; background: transparent; color: {COLOR_TEXT_DARK}; font-weight: 600;")
        self.caja_combo = QComboBox()
        self.caja_combo.setStyleSheet(COMBO_QSS)
        self.caja_combo.setFixedWidth(200)

        h.addWidget(lbl_caja)
        h.addWidget(self.caja_combo)
        return w

    def _make_filtros_kardex(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_producto = QLabel("Producto:")
        lbl_producto.setStyleSheet(LABEL_QSS)
        self.producto_combo_kardex = _crear_combo(ancho=220)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_kardex_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_kardex_input = _crear_fecha_edit()

        h.addWidget(lbl_producto)
        h.addWidget(self.producto_combo_kardex)
        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_kardex_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_kardex_input)
        return w

    def _make_filtros_valorizacion(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_categoria = QLabel("Categoría:")
        lbl_categoria.setStyleSheet(LABEL_QSS)
        self.categoria_combo_valorizacion = _crear_combo(ancho=200)

        h.addWidget(lbl_categoria)
        h.addWidget(self.categoria_combo_valorizacion)
        return w

    def _make_filtros_bajo_minimo(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_categoria = QLabel("Categoría:")
        lbl_categoria.setStyleSheet(LABEL_QSS)
        self.categoria_combo_bajo_minimo = _crear_combo(ancho=200)

        h.addWidget(lbl_categoria)
        h.addWidget(self.categoria_combo_bajo_minimo)
        return w

    def _make_filtros_sin_movimiento(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_sm_input = _crear_fecha_edit(dias_atras=90)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_sm_input = _crear_fecha_edit()

        lbl_categoria = QLabel("Categoría:")
        lbl_categoria.setStyleSheet(LABEL_QSS)
        self.categoria_combo_sm = _crear_combo(ancho=200)

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_sm_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_sm_input)
        h.addWidget(lbl_categoria)
        h.addWidget(self.categoria_combo_sm)
        return w

    def _make_filtros_historico_precios(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_producto = QLabel("Producto:")
        lbl_producto.setStyleSheet(LABEL_QSS)
        self.producto_combo_hp = _crear_combo(ancho=220)

        h.addWidget(lbl_producto)
        h.addWidget(self.producto_combo_hp)
        return w

    def _make_filtros_estado_cuenta_cliente(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_cliente = QLabel("Cliente:")
        lbl_cliente.setStyleSheet(LABEL_QSS)
        self.cliente_combo_ecc = _crear_combo(ancho=200)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_ecc_input = _crear_fecha_edit(dias_atras=90)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_ecc_input = _crear_fecha_edit()

        h.addWidget(lbl_cliente)
        h.addWidget(self.cliente_combo_ecc)
        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_ecc_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_ecc_input)
        return w

    def _make_filtros_cobros_periodo(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_cbp_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_cbp_input = _crear_fecha_edit()

        lbl_cliente = QLabel("Cliente:")
        lbl_cliente.setStyleSheet(LABEL_QSS)
        self.cliente_combo_cbp = _crear_combo(ancho=200)

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_cbp_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_cbp_input)
        h.addWidget(lbl_cliente)
        h.addWidget(self.cliente_combo_cbp)
        return w

    def _make_filtros_clientes_morosos(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_corte = QLabel("Corte:")
        lbl_corte.setStyleSheet(LABEL_QSS)
        self.fecha_corte_morosos_input = _crear_fecha_edit()

        h.addWidget(lbl_corte)
        h.addWidget(self.fecha_corte_morosos_input)
        return w

    def _make_filtros_cxc_otras(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_cliente = QLabel("Cliente:")
        lbl_cliente.setStyleSheet(LABEL_QSS)
        self.cliente_combo_cxco = _crear_combo(ancho=200)

        lbl_estado = QLabel("Estado:")
        lbl_estado.setStyleSheet(LABEL_QSS)
        self.estado_combo_cxco = _crear_combo(ancho=150)
        self.estado_combo_cxco.addItem("Todos los estados", None)
        for valor, etiqueta in ETIQUETAS_ESTADO_CXC_OTRO.items():
            self.estado_combo_cxco.addItem(etiqueta, valor)

        h.addWidget(lbl_cliente)
        h.addWidget(self.cliente_combo_cxco)
        h.addWidget(lbl_estado)
        h.addWidget(self.estado_combo_cxco)
        return w

    def _make_filtros_estado_cuenta_proveedor(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_proveedor = QLabel("Proveedor:")
        lbl_proveedor.setStyleSheet(LABEL_QSS)
        self.proveedor_combo_ecp = _crear_combo(ancho=200)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_ecp_input = _crear_fecha_edit(dias_atras=90)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_ecp_input = _crear_fecha_edit()

        h.addWidget(lbl_proveedor)
        h.addWidget(self.proveedor_combo_ecp)
        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_ecp_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_ecp_input)
        return w

    def _make_filtros_pagos_periodo(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_pp_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_pp_input = _crear_fecha_edit()

        lbl_proveedor = QLabel("Proveedor:")
        lbl_proveedor.setStyleSheet(LABEL_QSS)
        self.proveedor_combo_pp = _crear_combo(ancho=200)

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_pp_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_pp_input)
        h.addWidget(lbl_proveedor)
        h.addWidget(self.proveedor_combo_pp)
        return w

    def _make_filtros_proximos_vencimientos(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_dias = QLabel("Horizonte (días):")
        lbl_dias.setStyleSheet(LABEL_QSS)
        self.dias_horizonte_input = QSpinBox()
        self.dias_horizonte_input.setRange(1, 365)
        self.dias_horizonte_input.setValue(30)
        self.dias_horizonte_input.setFixedHeight(32)
        self.dias_horizonte_input.setFixedWidth(80)

        lbl_proveedor = QLabel("Proveedor:")
        lbl_proveedor.setStyleSheet(LABEL_QSS)
        self.proveedor_combo_pv = _crear_combo(ancho=200)

        h.addWidget(lbl_dias)
        h.addWidget(self.dias_horizonte_input)
        h.addWidget(lbl_proveedor)
        h.addWidget(self.proveedor_combo_pv)
        return w

    def _make_filtros_cxp_otras(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_cuenta = QLabel("Cuenta:")
        lbl_cuenta.setStyleSheet(LABEL_QSS)
        self.cuenta_bancaria_combo_cxpo = _crear_combo(ancho=200)

        lbl_estado = QLabel("Estado:")
        lbl_estado.setStyleSheet(LABEL_QSS)
        self.estado_combo_cxpo = _crear_combo(ancho=150)
        self.estado_combo_cxpo.addItem("Todos los estados", None)
        for valor, etiqueta in ETIQUETAS_ESTADO_CXP_OTRO.items():
            self.estado_combo_cxpo.addItem(etiqueta, valor)

        h.addWidget(lbl_cuenta)
        h.addWidget(self.cuenta_bancaria_combo_cxpo)
        h.addWidget(lbl_estado)
        h.addWidget(self.estado_combo_cxpo)
        return w

    def _make_filtros_mov_caja_periodo(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_mcp_input = _crear_fecha_edit(dias_atras=7)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_mcp_input = _crear_fecha_edit()

        lbl_caja = QLabel("Caja:")
        lbl_caja.setStyleSheet(LABEL_QSS)
        self.caja_combo_mcp = _crear_combo(ancho=180)

        lbl_tipo = QLabel("Tipo:")
        lbl_tipo.setStyleSheet(LABEL_QSS)
        self.tipo_combo_mcp = _crear_combo(ancho=130)
        self.tipo_combo_mcp.addItem("Todos", None)
        self.tipo_combo_mcp.addItem("Entrada", "entrada")
        self.tipo_combo_mcp.addItem("Salida", "salida")

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_mcp_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_mcp_input)
        h.addWidget(lbl_caja)
        h.addWidget(self.caja_combo_mcp)
        h.addWidget(lbl_tipo)
        h.addWidget(self.tipo_combo_mcp)
        return w

    def _make_filtros_cierre_cajero(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_cc_cajero_input = _crear_fecha_edit(dias_atras=7)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_cc_cajero_input = _crear_fecha_edit()

        lbl_cajero = QLabel("Cajero:")
        lbl_cajero.setStyleSheet(LABEL_QSS)
        self.usuario_combo_cierre = _crear_combo(ancho=180)

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_cc_cajero_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_cc_cajero_input)
        h.addWidget(lbl_cajero)
        h.addWidget(self.usuario_combo_cierre)
        return w

    def _make_filtros_flujo_caja(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_flujo_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_flujo_input = _crear_fecha_edit()

        lbl_agrup = QLabel("Agrupar por:")
        lbl_agrup.setStyleSheet(LABEL_QSS)
        self.agrupacion_flujo_combo = _crear_combo(ancho=100)
        self.agrupacion_flujo_combo.addItem("Día", "dia")
        self.agrupacion_flujo_combo.addItem("Mes", "mes")

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_flujo_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_flujo_input)
        h.addWidget(lbl_agrup)
        h.addWidget(self.agrupacion_flujo_combo)
        return w

    def _make_filtros_mov_cuenta_bancaria(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_cuenta = QLabel("Cuenta:")
        lbl_cuenta.setStyleSheet(LABEL_QSS)
        self.cuenta_bancaria_combo_mcb = _crear_combo(ancho=200)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_mcb_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_mcb_input = _crear_fecha_edit()

        h.addWidget(lbl_cuenta)
        h.addWidget(self.cuenta_bancaria_combo_mcb)
        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_mcb_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_mcb_input)
        return w

    def _make_filtros_conciliacion_bancaria(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_cuenta = QLabel("Cuenta:")
        lbl_cuenta.setStyleSheet(LABEL_QSS)
        self.cuenta_bancaria_combo_conc = _crear_combo(ancho=200)

        h.addWidget(lbl_cuenta)
        h.addWidget(self.cuenta_bancaria_combo_conc)
        return w

    def _make_filtros_saldo_consolidado(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("Foto del saldo actual de todas las cuentas bancarias activas.")
        lbl.setStyleSheet(f"border: none; background: transparent; color: {COLOR_TEXT_MUTED}; font-style: italic;")
        h.addWidget(lbl)
        return w

    def _make_filtros_comisiones_vendedor(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_comv_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_comv_input = _crear_fecha_edit()

        lbl_vendedor = QLabel("Vendedor:")
        lbl_vendedor.setStyleSheet(LABEL_QSS)
        self.vendedor_combo_comv = _crear_combo(ancho=200)

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_comv_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_comv_input)
        h.addWidget(lbl_vendedor)
        h.addWidget(self.vendedor_combo_comv)
        return w

    def _make_filtros_comisiones_pagadas_pendientes(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setStyleSheet(LABEL_QSS)
        self.fecha_desde_cpp_com_input = _crear_fecha_edit(dias_atras=30)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setStyleSheet(LABEL_QSS)
        self.fecha_hasta_cpp_com_input = _crear_fecha_edit()

        lbl_vendedor = QLabel("Vendedor:")
        lbl_vendedor.setStyleSheet(LABEL_QSS)
        self.vendedor_combo_cpp = _crear_combo(ancho=200)

        h.addWidget(lbl_desde)
        h.addWidget(self.fecha_desde_cpp_com_input)
        h.addWidget(lbl_hasta)
        h.addWidget(self.fecha_hasta_cpp_com_input)
        h.addWidget(lbl_vendedor)
        h.addWidget(self.vendedor_combo_cpp)
        return w

    def _make_resumen(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        self.resumen_layout = QHBoxLayout(w)
        self.resumen_layout.setContentsMargins(0, 0, 0, 0)
        self.resumen_layout.setSpacing(8)
        return w

    def _make_table(self) -> QTableWidget:
        self.tabla = QTableWidget(0, len(COLS_AGING_CXC))
        self.tabla.setHorizontalHeaderLabels(COLS_AGING_CXC)
        self.tabla.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setShowGrid(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(self.tabla)
        self.tabla.verticalHeader().setDefaultSectionSize(40)
        return self.tabla

    # ── Filtros auxiliares (combos) ────────────────────────────────────────

    def _cargar_clientes(self) -> None:
        session = self.session_factory()
        try:
            clientes = (
                session.query(Cliente)
                .filter(Cliente.estado_cliente == "ACTIVO")
                .order_by(Cliente.nombre_razon_social)
                .all()
            )
            # Combos independientes, uno por pagina de filtros que necesita elegir cliente
            # -- un QWidget no puede pertenecer a dos layouts a la vez, asi que no se puede
            # reusar la misma instancia entre paginas distintas.
            for combo in (
                self.cliente_combo,
                self.cliente_combo_lv,
                self.cliente_combo_nc,
                self.cliente_combo_ecc,
                self.cliente_combo_cbp,
                self.cliente_combo_cxco,
            ):
                combo.clear()
                combo.addItem("Todos los clientes", None)
                for cliente in clientes:
                    combo.addItem(cliente.nombre_razon_social, cliente.id_cliente)
        finally:
            session.close()

    def _cargar_proveedores(self) -> None:
        session = self.session_factory()
        try:
            proveedores = (
                session.query(Proveedor)
                .filter(Proveedor.estado_proveedor == "ACTIVO")
                .order_by(Proveedor.nombre_razon_social)
                .all()
            )
            # Combos independientes, uno por pagina de filtros que necesita elegir
            # proveedor -- mismo motivo que _cargar_clientes: un QWidget no puede
            # pertenecer a dos layouts a la vez.
            for combo in (
                self.proveedor_combo,
                self.proveedor_combo_oc,
                self.proveedor_combo_dp,
                self.proveedor_combo_ncp,
                self.proveedor_combo_ecp,
                self.proveedor_combo_pp,
                self.proveedor_combo_pv,
            ):
                combo.clear()
                combo.addItem("Todos los proveedores", None)
                for proveedor in proveedores:
                    combo.addItem(proveedor.nombre_razon_social, proveedor.id_proveedor)
        finally:
            session.close()

    def _cargar_cajas(self) -> None:
        session = self.session_factory()
        try:
            cajas = session.query(Caja).order_by(Caja.nombre_caja).all()
            self.caja_combo.clear()
            for caja in cajas:
                self.caja_combo.addItem(caja.nombre_caja or f"Caja {caja.id_caja}", caja.id_caja)
            # caja_combo_mcp (movimientos de caja por periodo) es un filtro OPCIONAL, a
            # diferencia de caja_combo (arqueo, siempre requiere una caja puntual) -- por
            # eso lleva su propia opcion "Todas" y no puede compartir instancia.
            self.caja_combo_mcp.clear()
            self.caja_combo_mcp.addItem("Todas las cajas", None)
            for caja in cajas:
                self.caja_combo_mcp.addItem(caja.nombre_caja or f"Caja {caja.id_caja}", caja.id_caja)
        finally:
            session.close()

    def _cargar_vendedores(self) -> None:
        session = self.session_factory()
        try:
            vendedores = session.query(Vendedor).order_by(Vendedor.nombre_vendedor).all()
            for combo in (self.vendedor_combo_comv, self.vendedor_combo_cpp):
                combo.clear()
                combo.addItem("Todos los vendedores", None)
                for vendedor in vendedores:
                    combo.addItem(vendedor.nombre_vendedor, vendedor.id_vendedor)
        finally:
            session.close()

    def _cargar_usuarios_cajero(self) -> None:
        session = self.session_factory()
        try:
            usuarios = session.query(Usuario).filter(Usuario.estado == "ACTIVO").order_by(Usuario.nombre_usuario).all()
            self.usuario_combo_cierre.clear()
            self.usuario_combo_cierre.addItem("Todos los cajeros", None)
            for usuario in usuarios:
                self.usuario_combo_cierre.addItem(usuario.nombre_usuario, usuario.id_usuario)
        finally:
            session.close()

    def _cargar_productos(self) -> None:
        session = self.session_factory()
        try:
            productos = (
                session.query(Inventario)
                .filter(Inventario.estado_producto == "ACTIVO")
                .order_by(Inventario.nombre_producto)
                .all()
            )
            # Dos combos independientes (kardex, historico de precios) -- mismo motivo que
            # _cargar_clientes: un QWidget no puede pertenecer a dos layouts. Sin opcion
            # "Todos": ambos reportes son por un producto especifico.
            for combo in (self.producto_combo_kardex, self.producto_combo_hp):
                combo.clear()
                for producto in productos:
                    combo.addItem(f"{producto.cod_producto} - {producto.nombre_producto}", producto.id_producto)
        finally:
            session.close()

    def _cargar_categorias(self) -> None:
        session = self.session_factory()
        try:
            categorias = session.query(Categoria).order_by(Categoria.nombre).all()
            for combo in (self.categoria_combo_valorizacion, self.categoria_combo_bajo_minimo, self.categoria_combo_sm):
                combo.clear()
                combo.addItem("Todas las categorías", None)
                for categoria in categorias:
                    combo.addItem(categoria.nombre, categoria.id_categoria)
        finally:
            session.close()

    def _cargar_cuentas_bancarias(self) -> None:
        session = self.session_factory()
        try:
            cuentas = session.query(CuentaBancaria).order_by(CuentaBancaria.numero_cuenta).all()
            for combo in (self.cuenta_bancaria_combo_cxpo, self.cuenta_bancaria_combo_conc):
                combo.clear()
                combo.addItem("Todas las cuentas", None)
                for cuenta in cuentas:
                    banco = cuenta.banco.nombre_banco if cuenta.banco else "N/A"
                    combo.addItem(f"{banco} - {cuenta.numero_cuenta}", cuenta.id_cuenta)
            # cuenta_bancaria_combo_mcb (movimientos por cuenta) SIN "Todas": el reporte
            # requiere una cuenta puntual, mismo criterio que producto_combo_kardex.
            self.cuenta_bancaria_combo_mcb.clear()
            for cuenta in cuentas:
                banco = cuenta.banco.nombre_banco if cuenta.banco else "N/A"
                self.cuenta_bancaria_combo_mcb.addItem(f"{banco} - {cuenta.numero_cuenta}", cuenta.id_cuenta)
        finally:
            session.close()

    def _on_tipo_cambiado(self, index: int) -> None:
        modo = self.tipo_combo.itemData(index)
        for m, pagina in self._filtros_paginas.items():
            pagina.setVisible(m == modo)

    # ── Generación del reporte ──────────────────────────────────────────────

    def _generar(self) -> None:
        # Mismo guard que dashboard_panel/facturacion_panel: reasignar self._worker a un
        # QThread nuevo mientras el viejo sigue corriendo lo destruye a mitad de ejecucion.
        if getattr(self, "_worker", None) is not None and self._worker.isRunning():
            return

        modo = self.tipo_combo.currentData()
        if modo == REPORTE_AGING_CXC:
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_aging_cxc,
                id_usuario=self.usuario.id_usuario,
                fecha_corte=self.fecha_corte_input.date().toPython(),
                id_cliente=self.cliente_combo.currentData(),
                orden=self.orden_combo.currentData(),
            )
        elif modo == REPORTE_AGING_CXP:
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_aging_cxp,
                id_usuario=self.usuario.id_usuario,
                fecha_corte=self.fecha_corte_cxp_input.date().toPython(),
                id_proveedor=self.proveedor_combo.currentData(),
                orden=self.orden_cxp_combo.currentData(),
            )
        elif modo == REPORTE_LIBRO_VENTAS:
            fecha_desde = self.fecha_desde_lv_input.date().toPython()
            fecha_hasta = self.fecha_hasta_lv_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_libro_ventas,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                id_cliente=self.cliente_combo_lv.currentData(),
            )
        elif modo == REPORTE_VENTAS_PERIODO:
            fecha_desde = self.fecha_desde_vp_input.date().toPython()
            fecha_hasta = self.fecha_hasta_vp_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_ventas_periodo,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                agrupacion=self.agrupacion_combo.currentData(),
            )
        elif modo == REPORTE_VENTAS_CLIENTE:
            fecha_desde = self.fecha_desde_vc_input.date().toPython()
            fecha_hasta = self.fecha_hasta_vc_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_ventas_cliente,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
            )
        elif modo == REPORTE_VENTAS_VENDEDOR:
            fecha_desde = self.fecha_desde_vv_input.date().toPython()
            fecha_hasta = self.fecha_hasta_vv_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_ventas_vendedor,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
            )
        elif modo == REPORTE_VENTAS_RUTA:
            fecha_desde = self.fecha_desde_vr_input.date().toPython()
            fecha_hasta = self.fecha_hasta_vr_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_ventas_ruta,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
            )
        elif modo == REPORTE_PRODUCTOS_VENDIDOS:
            fecha_desde = self.fecha_desde_pv_input.date().toPython()
            fecha_hasta = self.fecha_hasta_pv_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_productos_vendidos,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                orden=self.orden_productos_combo.currentData(),
            )
        elif modo == REPORTE_FACTURAS_ANULADAS:
            fecha_desde = self.fecha_desde_fa_input.date().toPython()
            fecha_hasta = self.fecha_hasta_fa_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_facturas_anuladas,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
            )
        elif modo == REPORTE_NC_EMITIDAS:
            fecha_desde = self.fecha_desde_nc_input.date().toPython()
            fecha_hasta = self.fecha_hasta_nc_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_nc_emitidas,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                id_cliente=self.cliente_combo_nc.currentData(),
            )
        elif modo == REPORTE_CONTADO_CREDITO:
            fecha_desde = self.fecha_desde_cc_input.date().toPython()
            fecha_hasta = self.fecha_hasta_cc_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_contado_credito,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
            )
        elif modo == REPORTE_MARGEN_UTILIDAD:
            fecha_desde = self.fecha_desde_mu_input.date().toPython()
            fecha_hasta = self.fecha_hasta_mu_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_margen_utilidad,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
            )
        elif modo == REPORTE_COMPRAS_PERIODO:
            fecha_desde = self.fecha_desde_cp_input.date().toPython()
            fecha_hasta = self.fecha_hasta_cp_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_compras_periodo,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                agrupacion=self.agrupacion_compras_combo.currentData(),
            )
        elif modo == REPORTE_COMPRAS_PROVEEDOR:
            fecha_desde = self.fecha_desde_cpv_input.date().toPython()
            fecha_hasta = self.fecha_hasta_cpv_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_compras_proveedor,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
            )
        elif modo == REPORTE_COMPRAS_PRODUCTO:
            fecha_desde = self.fecha_desde_cpp_input.date().toPython()
            fecha_hasta = self.fecha_hasta_cpp_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_compras_producto,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                orden=self.orden_compras_producto_combo.currentData(),
            )
        elif modo == REPORTE_OC_ABIERTAS:
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_oc_abiertas,
                id_usuario=self.usuario.id_usuario,
                id_proveedor=self.proveedor_combo_oc.currentData(),
            )
        elif modo == REPORTE_CUMPLIMIENTO_PROVEEDORES:
            fecha_desde = self.fecha_desde_cump_input.date().toPython()
            fecha_hasta = self.fecha_hasta_cump_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_cumplimiento_proveedores,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
            )
        elif modo == REPORTE_DEVOLUCIONES_PROVEEDOR:
            fecha_desde = self.fecha_desde_dp_input.date().toPython()
            fecha_hasta = self.fecha_hasta_dp_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_devoluciones_proveedor,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                id_proveedor=self.proveedor_combo_dp.currentData(),
            )
        elif modo == REPORTE_NC_PROVEEDOR:
            fecha_desde = self.fecha_desde_ncp_input.date().toPython()
            fecha_hasta = self.fecha_hasta_ncp_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_nc_proveedor,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                id_proveedor=self.proveedor_combo_ncp.currentData(),
            )
        elif modo == REPORTE_ARQUEO_CAJA:
            id_caja = self.caja_combo.currentData()
            if id_caja is None:
                MessageBox.information(self, "Sin cajas", "No hay cajas registradas para generar el arqueo.")
                return
            self._worker = QueryWorker(
                self.session_factory, _tarea_arqueo_caja, id_usuario=self.usuario.id_usuario, id_caja=id_caja
            )
        elif modo == REPORTE_KARDEX:
            id_producto = self.producto_combo_kardex.currentData()
            if id_producto is None:
                MessageBox.information(self, "Sin productos", "No hay productos registrados para generar el kardex.")
                return
            fecha_desde = self.fecha_desde_kardex_input.date().toPython()
            fecha_hasta = self.fecha_hasta_kardex_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_kardex,
                id_usuario=self.usuario.id_usuario,
                id_producto=id_producto,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
            )
        elif modo == REPORTE_VALORIZACION:
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_valorizacion_inventario,
                id_usuario=self.usuario.id_usuario,
                id_categoria=self.categoria_combo_valorizacion.currentData(),
            )
        elif modo == REPORTE_BAJO_MINIMO:
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_bajo_minimo,
                id_usuario=self.usuario.id_usuario,
                id_categoria=self.categoria_combo_bajo_minimo.currentData(),
            )
        elif modo == REPORTE_SIN_MOVIMIENTO:
            fecha_desde = self.fecha_desde_sm_input.date().toPython()
            fecha_hasta = self.fecha_hasta_sm_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_sin_movimiento,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                id_categoria=self.categoria_combo_sm.currentData(),
            )
        elif modo == REPORTE_HISTORICO_PRECIOS:
            id_producto = self.producto_combo_hp.currentData()
            if id_producto is None:
                MessageBox.information(self, "Sin productos", "No hay productos registrados.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_historico_precios,
                id_usuario=self.usuario.id_usuario,
                id_producto=id_producto,
            )
        elif modo == REPORTE_ESTADO_CTA_CLIENTE:
            id_cliente = self.cliente_combo_ecc.currentData()
            if id_cliente is None:
                MessageBox.information(self, "Sin clientes", "No hay clientes registrados.")
                return
            fecha_desde = self.fecha_desde_ecc_input.date().toPython()
            fecha_hasta = self.fecha_hasta_ecc_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_estado_cuenta_cliente,
                id_usuario=self.usuario.id_usuario,
                id_cliente=id_cliente,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
            )
        elif modo == REPORTE_COBROS_PERIODO:
            fecha_desde = self.fecha_desde_cbp_input.date().toPython()
            fecha_hasta = self.fecha_hasta_cbp_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_cobros_periodo,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                id_cliente=self.cliente_combo_cbp.currentData(),
            )
        elif modo == REPORTE_CLIENTES_MOROSOS:
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_clientes_morosos,
                id_usuario=self.usuario.id_usuario,
                fecha_corte=self.fecha_corte_morosos_input.date().toPython(),
            )
        elif modo == REPORTE_CXC_OTRAS:
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_cxc_otras,
                id_usuario=self.usuario.id_usuario,
                id_cliente=self.cliente_combo_cxco.currentData(),
                estado=self.estado_combo_cxco.currentData(),
            )
        elif modo == REPORTE_ESTADO_CTA_PROVEEDOR:
            id_proveedor = self.proveedor_combo_ecp.currentData()
            if id_proveedor is None:
                MessageBox.information(self, "Sin proveedores", "No hay proveedores registrados.")
                return
            fecha_desde = self.fecha_desde_ecp_input.date().toPython()
            fecha_hasta = self.fecha_hasta_ecp_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_estado_cuenta_proveedor,
                id_usuario=self.usuario.id_usuario,
                id_proveedor=id_proveedor,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
            )
        elif modo == REPORTE_PAGOS_PERIODO:
            fecha_desde = self.fecha_desde_pp_input.date().toPython()
            fecha_hasta = self.fecha_hasta_pp_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_pagos_periodo,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                id_proveedor=self.proveedor_combo_pp.currentData(),
            )
        elif modo == REPORTE_PROXIMOS_VENCIMIENTOS:
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_proximos_vencimientos,
                id_usuario=self.usuario.id_usuario,
                dias_horizonte=self.dias_horizonte_input.value(),
                id_proveedor=self.proveedor_combo_pv.currentData(),
            )
        elif modo == REPORTE_CXP_OTRAS:
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_cxp_otras,
                id_usuario=self.usuario.id_usuario,
                id_cuenta_bancaria=self.cuenta_bancaria_combo_cxpo.currentData(),
                estado=self.estado_combo_cxpo.currentData(),
            )
        elif modo == REPORTE_MOV_CAJA_PERIODO:
            fecha_desde = self.fecha_desde_mcp_input.date().toPython()
            fecha_hasta = self.fecha_hasta_mcp_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_mov_caja_periodo,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                id_caja=self.caja_combo_mcp.currentData(),
                tipo_movimiento=self.tipo_combo_mcp.currentData(),
            )
        elif modo == REPORTE_CIERRE_CAJERO:
            fecha_desde = self.fecha_desde_cc_cajero_input.date().toPython()
            fecha_hasta = self.fecha_hasta_cc_cajero_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_cierre_cajero,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                id_usuario_cajero=self.usuario_combo_cierre.currentData(),
            )
        elif modo == REPORTE_FLUJO_CAJA:
            fecha_desde = self.fecha_desde_flujo_input.date().toPython()
            fecha_hasta = self.fecha_hasta_flujo_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_flujo_caja,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                agrupacion=self.agrupacion_flujo_combo.currentData(),
            )
        elif modo == REPORTE_MOV_CUENTA_BANCARIA:
            id_cuenta_bancaria = self.cuenta_bancaria_combo_mcb.currentData()
            if id_cuenta_bancaria is None:
                MessageBox.information(self, "Sin cuentas", "No hay cuentas bancarias registradas.")
                return
            fecha_desde = self.fecha_desde_mcb_input.date().toPython()
            fecha_hasta = self.fecha_hasta_mcb_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_mov_cuenta_bancaria,
                id_usuario=self.usuario.id_usuario,
                id_cuenta_bancaria=id_cuenta_bancaria,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
            )
        elif modo == REPORTE_CONCILIACION_BANCARIA:
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_conciliacion_bancaria,
                id_usuario=self.usuario.id_usuario,
                id_cuenta_bancaria=self.cuenta_bancaria_combo_conc.currentData(),
            )
        elif modo == REPORTE_SALDO_CONSOLIDADO:
            self._worker = QueryWorker(
                self.session_factory, _tarea_saldo_consolidado, id_usuario=self.usuario.id_usuario
            )
        elif modo == REPORTE_COMISIONES_VENDEDOR:
            fecha_desde = self.fecha_desde_comv_input.date().toPython()
            fecha_hasta = self.fecha_hasta_comv_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_comisiones_vendedor,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                id_vendedor=self.vendedor_combo_comv.currentData(),
            )
        else:
            fecha_desde = self.fecha_desde_cpp_com_input.date().toPython()
            fecha_hasta = self.fecha_hasta_cpp_com_input.date().toPython()
            if fecha_desde > fecha_hasta:
                MessageBox.warning(self, "Rango inválido", "La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                return
            self._worker = QueryWorker(
                self.session_factory,
                _tarea_comisiones_pagadas_pendientes,
                id_usuario=self.usuario.id_usuario,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                id_vendedor=self.vendedor_combo_cpp.currentData(),
            )

        self._ultimo_modo = modo
        self.btn_generar.setEnabled(False)
        self._worker.resultado.connect(self._mostrar_resultado)
        self._worker.error.connect(self._mostrar_error)
        self._worker.start()

    def _mostrar_resultado(self, resultado: dict) -> None:
        self.btn_generar.setEnabled(True)
        self._ultimo_resultado = resultado
        if self._ultimo_modo == REPORTE_AGING_CXC:
            self._mostrar_aging(resultado)
        elif self._ultimo_modo == REPORTE_AGING_CXP:
            self._mostrar_aging_cxp(resultado)
        elif self._ultimo_modo == REPORTE_LIBRO_VENTAS:
            self._mostrar_libro_ventas(resultado)
        elif self._ultimo_modo == REPORTE_VENTAS_PERIODO:
            self._mostrar_ventas_periodo(resultado)
        elif self._ultimo_modo == REPORTE_VENTAS_CLIENTE:
            self._mostrar_ventas_cliente(resultado)
        elif self._ultimo_modo == REPORTE_VENTAS_VENDEDOR:
            self._mostrar_ventas_vendedor(resultado)
        elif self._ultimo_modo == REPORTE_VENTAS_RUTA:
            self._mostrar_ventas_ruta(resultado)
        elif self._ultimo_modo == REPORTE_PRODUCTOS_VENDIDOS:
            self._mostrar_productos_vendidos(resultado)
        elif self._ultimo_modo == REPORTE_FACTURAS_ANULADAS:
            self._mostrar_facturas_anuladas(resultado)
        elif self._ultimo_modo == REPORTE_NC_EMITIDAS:
            self._mostrar_nc_emitidas(resultado)
        elif self._ultimo_modo == REPORTE_CONTADO_CREDITO:
            self._mostrar_contado_credito(resultado)
        elif self._ultimo_modo == REPORTE_MARGEN_UTILIDAD:
            self._mostrar_margen_utilidad(resultado)
        elif self._ultimo_modo == REPORTE_COMPRAS_PERIODO:
            self._mostrar_compras_periodo(resultado)
        elif self._ultimo_modo == REPORTE_COMPRAS_PROVEEDOR:
            self._mostrar_compras_proveedor(resultado)
        elif self._ultimo_modo == REPORTE_COMPRAS_PRODUCTO:
            self._mostrar_compras_producto(resultado)
        elif self._ultimo_modo == REPORTE_OC_ABIERTAS:
            self._mostrar_oc_abiertas(resultado)
        elif self._ultimo_modo == REPORTE_CUMPLIMIENTO_PROVEEDORES:
            self._mostrar_cumplimiento_proveedores(resultado)
        elif self._ultimo_modo == REPORTE_DEVOLUCIONES_PROVEEDOR:
            self._mostrar_devoluciones_proveedor(resultado)
        elif self._ultimo_modo == REPORTE_NC_PROVEEDOR:
            self._mostrar_nc_proveedor(resultado)
        elif self._ultimo_modo == REPORTE_ARQUEO_CAJA:
            self._mostrar_arqueo(resultado)
        elif self._ultimo_modo == REPORTE_KARDEX:
            self._mostrar_kardex(resultado)
        elif self._ultimo_modo == REPORTE_VALORIZACION:
            self._mostrar_valorizacion(resultado)
        elif self._ultimo_modo == REPORTE_BAJO_MINIMO:
            self._mostrar_bajo_minimo(resultado)
        elif self._ultimo_modo == REPORTE_SIN_MOVIMIENTO:
            self._mostrar_sin_movimiento(resultado)
        elif self._ultimo_modo == REPORTE_HISTORICO_PRECIOS:
            self._mostrar_historico_precios(resultado)
        elif self._ultimo_modo == REPORTE_ESTADO_CTA_CLIENTE:
            self._mostrar_estado_cuenta_cliente(resultado)
        elif self._ultimo_modo == REPORTE_COBROS_PERIODO:
            self._mostrar_cobros_periodo(resultado)
        elif self._ultimo_modo == REPORTE_CLIENTES_MOROSOS:
            self._mostrar_clientes_morosos(resultado)
        elif self._ultimo_modo == REPORTE_CXC_OTRAS:
            self._mostrar_cxc_otras(resultado)
        elif self._ultimo_modo == REPORTE_ESTADO_CTA_PROVEEDOR:
            self._mostrar_estado_cuenta_proveedor(resultado)
        elif self._ultimo_modo == REPORTE_PAGOS_PERIODO:
            self._mostrar_pagos_periodo(resultado)
        elif self._ultimo_modo == REPORTE_PROXIMOS_VENCIMIENTOS:
            self._mostrar_proximos_vencimientos(resultado)
        elif self._ultimo_modo == REPORTE_CXP_OTRAS:
            self._mostrar_cxp_otras(resultado)
        elif self._ultimo_modo == REPORTE_MOV_CAJA_PERIODO:
            self._mostrar_mov_caja_periodo(resultado)
        elif self._ultimo_modo == REPORTE_CIERRE_CAJERO:
            self._mostrar_cierre_cajero(resultado)
        elif self._ultimo_modo == REPORTE_FLUJO_CAJA:
            self._mostrar_flujo_caja(resultado)
        elif self._ultimo_modo == REPORTE_MOV_CUENTA_BANCARIA:
            self._mostrar_mov_cuenta_bancaria(resultado)
        elif self._ultimo_modo == REPORTE_CONCILIACION_BANCARIA:
            self._mostrar_conciliacion_bancaria(resultado)
        elif self._ultimo_modo == REPORTE_SALDO_CONSOLIDADO:
            self._mostrar_saldo_consolidado(resultado)
        elif self._ultimo_modo == REPORTE_COMISIONES_VENDEDOR:
            self._mostrar_comisiones_vendedor(resultado)
        else:
            self._mostrar_comisiones_pagadas_pendientes(resultado)

    def _mostrar_error(self, mensaje: str) -> None:
        self.btn_generar.setEnabled(True)
        logger.error("Fallo al generar el reporte: %s", mensaje)
        MessageBox.critical(self, "Error", "No se pudo generar el reporte.")

    # ── Resultados: aging CxC ────────────────────────────────────────────────

    def _reset_tabla(self, columnas: list[str]) -> None:
        self.tabla.clear()
        self.tabla.setColumnCount(len(columnas))
        self.tabla.setHorizontalHeaderLabels(columnas)
        self.tabla.setRowCount(0)

    def _mostrar_aging(self, resultado: dict) -> None:
        self._reset_tabla(COLS_AGING_CXC)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["numero_factura"]))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["cliente"] or "Consumidor final"))
            fecha_venc = f["fecha_vencimiento"].strftime("%d/%m/%Y") if f["fecha_vencimiento"] else "N/A"
            self.tabla.setItem(row, 2, QTableWidgetItem(fecha_venc))
            self.tabla.setItem(row, 3, QTableWidgetItem(f"${float(f['saldo_pendiente']):,.2f}"))
            self.tabla.setItem(row, 4, QTableWidgetItem(str(f["dias_vencido"])))
            self.tabla.setItem(row, 5, QTableWidgetItem(ETIQUETAS_BUCKET.get(f["bucket"], f["bucket"])))

        self.lbl_total.setText(
            f"{len(filas)} cuenta{'s' if len(filas) != 1 else ''} abierta{'s' if len(filas) != 1 else ''}"
        )
        self._mostrar_resumen_aging(resultado)

    def _mostrar_resumen_aging(self, resultado: dict) -> None:
        self._limpiar_resumen()
        totales = resultado["totales_por_bucket"]
        for bucket in BUCKETS_AGING:
            monto = totales.get(bucket, Decimal("0.00"))
            color = COLOR_DANGER if bucket != "vigente" and monto else COLOR_TEXT_MUTED
            self.resumen_layout.addWidget(self._chip(f"{ETIQUETAS_BUCKET[bucket]}: ${float(monto):,.2f}", color))
        self.resumen_layout.addWidget(
            self._chip(f"Total general: ${float(resultado['total_general']):,.2f}", "#FFFFFF", COLOR_PRIMARY)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: aging CxP ────────────────────────────────────────────────

    def _mostrar_aging_cxp(self, resultado: dict) -> None:
        self._reset_tabla(COLS_AGING_CXP)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["numero_compra"]))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["proveedor"] or "N/A"))
            fecha_venc = f["fecha_vencimiento"].strftime("%d/%m/%Y") if f["fecha_vencimiento"] else "N/A"
            self.tabla.setItem(row, 2, QTableWidgetItem(fecha_venc))
            self.tabla.setItem(row, 3, QTableWidgetItem(f"${float(f['saldo_pendiente']):,.2f}"))
            self.tabla.setItem(row, 4, QTableWidgetItem(str(f["dias_vencido"])))
            self.tabla.setItem(row, 5, QTableWidgetItem(ETIQUETAS_BUCKET.get(f["bucket"], f["bucket"])))

        self.lbl_total.setText(
            f"{len(filas)} cuenta{'s' if len(filas) != 1 else ''} abierta{'s' if len(filas) != 1 else ''}"
        )
        # Mismo formato de resultado que aging CxC (totales_por_bucket/total_general),
        # asi que reusa el mismo constructor de chips de resumen.
        self._mostrar_resumen_aging(resultado)

    # ── Resultados: libro de ventas ──────────────────────────────────────────

    def _mostrar_libro_ventas(self, resultado: dict) -> None:
        self._reset_tabla(COLS_LIBRO_VENTAS)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["fecha_emision"].strftime("%d/%m/%Y")))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["numero_control"]))
            self.tabla.setItem(row, 2, QTableWidgetItem(f["numero_factura"]))
            self.tabla.setItem(row, 3, QTableWidgetItem(f["cliente"] or "Consumidor final"))
            self.tabla.setItem(row, 4, QTableWidgetItem(f["identificacion_cliente"] or "N/A"))
            self.tabla.setItem(row, 5, QTableWidgetItem(f"${float(f['base_imponible']):,.2f}"))
            self.tabla.setItem(row, 6, QTableWidgetItem(f"{float(f['porcentaje_iva']):.2f}%"))
            self.tabla.setItem(row, 7, QTableWidgetItem(f"${float(f['monto_iva']):,.2f}"))
            self.tabla.setItem(row, 8, QTableWidgetItem(f"${float(f['total']):,.2f}"))

        self.lbl_total.setText(f"{len(filas)} factura{'s' if len(filas) != 1 else ''}")
        self._mostrar_resumen_libro_ventas(resultado)

    def _mostrar_resumen_libro_ventas(self, resultado: dict) -> None:
        self._limpiar_resumen()
        self.resumen_layout.addWidget(self._chip(f"Base imponible: ${float(resultado['total_base_imponible']):,.2f}"))
        self.resumen_layout.addWidget(self._chip(f"IVA: ${float(resultado['total_iva']):,.2f}"))
        self.resumen_layout.addWidget(
            self._chip(f"Total: ${float(resultado['total_general']):,.2f}", "#FFFFFF", COLOR_PRIMARY)
        )
        n_notas = len(resultado["notas_credito"])
        if n_notas:
            self.resumen_layout.addWidget(
                self._chip(
                    f"Notas de crédito del período: {n_notas} (${float(resultado['total_notas_credito']):,.2f})",
                    COLOR_WARNING,
                )
            )
        self.resumen_layout.addStretch()

    # ── Resultados: ventas por período ───────────────────────────────────────

    def _mostrar_ventas_periodo(self, resultado: dict) -> None:
        self._reset_tabla(COLS_VENTAS_PERIODO)
        filas = resultado["filas"]
        formato_fecha = "%d/%m/%Y" if resultado["agrupacion"] == "dia" else "%m/%Y"
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["fecha"].strftime(formato_fecha)))
            self.tabla.setItem(row, 1, QTableWidgetItem(str(f["cantidad_facturas"])))
            self.tabla.setItem(row, 2, QTableWidgetItem(f"${float(f['total']):,.2f}"))

        self.lbl_total.setText(f"{len(filas)} período{'s' if len(filas) != 1 else ''}")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(self._chip(f"Facturas: {resultado['total_facturas']}"))
        self.resumen_layout.addWidget(
            self._chip(f"Total general: ${float(resultado['total_general']):,.2f}", "#FFFFFF", COLOR_PRIMARY)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: ranking (cliente / vendedor / productos) ─────────────────

    def _mostrar_ranking(
        self,
        resultado: dict,
        columnas: list[str],
        clave_nombre: str,
        clave_cantidad: str,
        clave_promedio: str | None = None,
    ) -> None:
        """`clave_promedio` agrega una 4ta columna (ej. "Ticket Promedio") cuando el
        reporte la trae -- ventas por vendedor/ruta ("drop site", 2026-09-02: total
        facturado en $ entre cantidad de facturas), no cliente/productos."""
        self._reset_tabla(columnas)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f[clave_nombre] or "N/A"))
            valor_cantidad = f[clave_cantidad]
            texto_cantidad = str(valor_cantidad) if isinstance(valor_cantidad, int) else f"{float(valor_cantidad):,.2f}"
            self.tabla.setItem(row, 1, QTableWidgetItem(texto_cantidad))
            self.tabla.setItem(row, 2, QTableWidgetItem(f"${float(f['total']):,.2f}"))
            if clave_promedio is not None:
                self.tabla.setItem(row, 3, QTableWidgetItem(f"${float(f[clave_promedio]):,.2f}"))

        self.lbl_total.setText(f"{len(filas)} fila{'s' if len(filas) != 1 else ''}")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(
            self._chip(f"Total general: ${float(resultado['total_general']):,.2f}", "#FFFFFF", COLOR_PRIMARY)
        )
        self.resumen_layout.addStretch()

    def _mostrar_ventas_cliente(self, resultado: dict) -> None:
        self._mostrar_ranking(resultado, COLS_VENTAS_CLIENTE, "cliente", "cantidad_facturas")

    def _mostrar_ventas_vendedor(self, resultado: dict) -> None:
        self._mostrar_ranking(
            resultado, COLS_VENTAS_VENDEDOR, "vendedor", "cantidad_facturas", clave_promedio="ticket_promedio"
        )

    def _mostrar_ventas_ruta(self, resultado: dict) -> None:
        self._mostrar_ranking(
            resultado, COLS_VENTAS_RUTA, "ruta", "cantidad_facturas", clave_promedio="ticket_promedio"
        )

    def _mostrar_productos_vendidos(self, resultado: dict) -> None:
        self._mostrar_ranking(resultado, COLS_PRODUCTOS_VENDIDOS, "producto", "cantidad")

    # ── Resultados: facturas anuladas ─────────────────────────────────────────

    def _mostrar_facturas_anuladas(self, resultado: dict) -> None:
        self._reset_tabla(COLS_FACTURAS_ANULADAS)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["numero_factura"]))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["cliente"] or "Consumidor final"))
            self.tabla.setItem(row, 2, QTableWidgetItem(f["vendedor"] or "N/A"))
            self.tabla.setItem(row, 3, QTableWidgetItem(f["fecha_emision"].strftime("%d/%m/%Y")))
            self.tabla.setItem(row, 4, QTableWidgetItem(f["motivo"] or "Sin registrar"))

        self.lbl_total.setText(
            f"{len(filas)} factura{'s' if len(filas) != 1 else ''} anulada{'s' if len(filas) != 1 else ''}"
        )
        self._limpiar_resumen()
        self.resumen_layout.addWidget(self._chip(f"Total: {resultado['total_facturas']} facturas", COLOR_DANGER))
        self.resumen_layout.addStretch()

    # ── Resultados: notas de crédito emitidas ─────────────────────────────────

    def _mostrar_nc_emitidas(self, resultado: dict) -> None:
        self._reset_tabla(COLS_NC_EMITIDAS)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["numero_nota_credito"]))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["cliente"] or "N/A"))
            self.tabla.setItem(row, 2, QTableWidgetItem(f["numero_factura_origen"] or "N/A"))
            self.tabla.setItem(row, 3, QTableWidgetItem(f["fecha_creacion"].strftime("%d/%m/%Y")))
            self.tabla.setItem(row, 4, QTableWidgetItem(f"${float(f['monto']):,.2f}"))
            self.tabla.setItem(row, 5, QTableWidgetItem(f"${float(f['saldo_disponible']):,.2f}"))
            self.tabla.setItem(row, 6, QTableWidgetItem(ETIQUETAS_ESTADO_NC.get(f["estado"], f["estado"])))

        self.lbl_total.setText(f"{len(filas)} nota{'s' if len(filas) != 1 else ''} de crédito")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(
            self._chip(f"Total emitido: ${float(resultado['total_general']):,.2f}", "#FFFFFF", COLOR_WARNING)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: ventas contado vs. crédito ────────────────────────────────

    def _mostrar_contado_credito(self, resultado: dict) -> None:
        self._reset_tabla(COLS_CONTADO_CREDITO)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["condicion_pago"].capitalize()))
            self.tabla.setItem(row, 1, QTableWidgetItem(str(f["cantidad_facturas"])))
            self.tabla.setItem(row, 2, QTableWidgetItem(f"${float(f['total']):,.2f}"))
            self.tabla.setItem(row, 3, QTableWidgetItem(f"{float(f['porcentaje']):.1f}%"))

        self.lbl_total.setText("2 condiciones de pago")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(
            self._chip(f"Total general: ${float(resultado['total_general']):,.2f}", "#FFFFFF", COLOR_PRIMARY)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: margen de utilidad ────────────────────────────────────────

    def _mostrar_margen_utilidad(self, resultado: dict) -> None:
        self._reset_tabla(COLS_MARGEN_UTILIDAD)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["producto"] or "N/A"))
            self.tabla.setItem(row, 1, QTableWidgetItem(f"{float(f['cantidad']):,.2f}"))
            self.tabla.setItem(row, 2, QTableWidgetItem(f"${float(f['ingreso']):,.2f}"))
            self.tabla.setItem(row, 3, QTableWidgetItem(f"${float(f['costo']):,.2f}"))
            self.tabla.setItem(row, 4, QTableWidgetItem(f"${float(f['margen']):,.2f}"))
            self.tabla.setItem(row, 5, QTableWidgetItem(f"{float(f['margen_pct']):.1f}%"))

        self.lbl_total.setText(f"{len(filas)} producto{'s' if len(filas) != 1 else ''}")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(self._chip(f"Ingreso: ${float(resultado['total_ingreso']):,.2f}"))
        self.resumen_layout.addWidget(self._chip(f"Costo: ${float(resultado['total_costo']):,.2f}", COLOR_DANGER))
        self.resumen_layout.addWidget(
            self._chip(f"Margen: ${float(resultado['total_margen']):,.2f}", "#FFFFFF", COLOR_SUCCESS)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: compras por período ──────────────────────────────────────

    def _mostrar_compras_periodo(self, resultado: dict) -> None:
        self._reset_tabla(COLS_COMPRAS_PERIODO)
        filas = resultado["filas"]
        formato_fecha = "%d/%m/%Y" if resultado["agrupacion"] == "dia" else "%m/%Y"
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["fecha"].strftime(formato_fecha)))
            self.tabla.setItem(row, 1, QTableWidgetItem(str(f["cantidad_compras"])))
            self.tabla.setItem(row, 2, QTableWidgetItem(f"${float(f['total']):,.2f}"))

        self.lbl_total.setText(f"{len(filas)} período{'s' if len(filas) != 1 else ''}")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(self._chip(f"Compras: {resultado['total_compras']}"))
        self.resumen_layout.addWidget(
            self._chip(f"Total general: ${float(resultado['total_general']):,.2f}", "#FFFFFF", COLOR_PRIMARY)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: compras por proveedor / por producto ─────────────────────

    def _mostrar_compras_proveedor(self, resultado: dict) -> None:
        self._mostrar_ranking(resultado, COLS_COMPRAS_PROVEEDOR, "proveedor", "cantidad_compras")

    def _mostrar_compras_producto(self, resultado: dict) -> None:
        self._mostrar_ranking(resultado, COLS_COMPRAS_PRODUCTO, "producto", "cantidad")

    # ── Resultados: órdenes de compra abiertas ────────────────────────────────

    def _mostrar_oc_abiertas(self, resultado: dict) -> None:
        self._reset_tabla(COLS_OC_ABIERTAS)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["numero_oc"]))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["proveedor"] or "N/A"))
            self.tabla.setItem(row, 2, QTableWidgetItem(f["fecha_oc"].strftime("%d/%m/%Y")))
            fecha_est = f["fecha_estimada_entrega"].strftime("%d/%m/%Y") if f["fecha_estimada_entrega"] else "N/A"
            self.tabla.setItem(row, 3, QTableWidgetItem(fecha_est))
            self.tabla.setItem(row, 4, QTableWidgetItem(f"{float(f['cantidad_solicitada']):,.2f}"))
            self.tabla.setItem(row, 5, QTableWidgetItem(f"{float(f['cantidad_recibida']):,.2f}"))
            self.tabla.setItem(row, 6, QTableWidgetItem(f"{float(f['cantidad_pendiente']):,.2f}"))
            self.tabla.setItem(row, 7, QTableWidgetItem(ETIQUETAS_ESTADO_OC.get(f["estado"], f["estado"])))
            self.tabla.setItem(row, 8, QTableWidgetItem(f"${float(f['total_oc']):,.2f}"))
            self.tabla.setItem(row, 9, QTableWidgetItem("Sí" if f["vencida"] else "No"))

        self.lbl_total.setText(
            f"{len(filas)} orden{'es' if len(filas) != 1 else ''} abierta{'s' if len(filas) != 1 else ''}"
        )
        self._limpiar_resumen()
        n_vencidas = sum(1 for f in filas if f["vencida"])
        if n_vencidas:
            self.resumen_layout.addWidget(self._chip(f"Vencidas: {n_vencidas}", COLOR_DANGER))
        self.resumen_layout.addWidget(
            self._chip(f"Total comprometido: ${float(resultado['total_general']):,.2f}", "#FFFFFF", COLOR_PRIMARY)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: cumplimiento de proveedores ───────────────────────────────

    def _mostrar_cumplimiento_proveedores(self, resultado: dict) -> None:
        self._reset_tabla(COLS_CUMPLIMIENTO_PROVEEDORES)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["proveedor"] or "N/A"))
            self.tabla.setItem(row, 1, QTableWidgetItem(str(f["cantidad_oc"])))
            self.tabla.setItem(row, 2, QTableWidgetItem(str(f["a_tiempo"])))
            self.tabla.setItem(row, 3, QTableWidgetItem(str(f["tardias"])))
            self.tabla.setItem(row, 4, QTableWidgetItem(str(f["sin_fecha_estimada"])))
            pct = f["pct_a_tiempo"]
            self.tabla.setItem(row, 5, QTableWidgetItem(f"{float(pct):.1f}%" if pct is not None else "N/A"))

        self.lbl_total.setText(f"{len(filas)} proveedor{'es' if len(filas) != 1 else ''}")
        self._limpiar_resumen()
        self.resumen_layout.addStretch()

    # ── Resultados: devoluciones a proveedor ──────────────────────────────────

    def _mostrar_devoluciones_proveedor(self, resultado: dict) -> None:
        self._reset_tabla(COLS_DEVOLUCIONES_PROVEEDOR)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["numero_nota_devolucion"]))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["proveedor"] or "N/A"))
            self.tabla.setItem(row, 2, QTableWidgetItem(f["numero_oc"]))
            self.tabla.setItem(row, 3, QTableWidgetItem(f["fecha_devolucion"].strftime("%d/%m/%Y")))
            self.tabla.setItem(row, 4, QTableWidgetItem(f["motivo"]))
            self.tabla.setItem(row, 5, QTableWidgetItem(f"{float(f['cantidad_total']):,.2f}"))
            self.tabla.setItem(row, 6, QTableWidgetItem(f["estado"].capitalize()))

        self.lbl_total.setText(f"{len(filas)} {'devolución' if len(filas) == 1 else 'devoluciones'}")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(self._chip(f"Total devoluciones: {resultado['total_devoluciones']}"))
        self.resumen_layout.addWidget(
            self._chip(f"Cantidad total: {float(resultado['total_cantidad']):,.2f}", "#FFFFFF", COLOR_WARNING)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: notas de crédito de proveedor ─────────────────────────────

    def _mostrar_nc_proveedor(self, resultado: dict) -> None:
        self._reset_tabla(COLS_NC_PROVEEDOR)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(str(f["id_nota_credito"])))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["proveedor"] or "N/A"))
            self.tabla.setItem(row, 2, QTableWidgetItem(f["numero_compra_origen"] or "N/A"))
            self.tabla.setItem(row, 3, QTableWidgetItem(f["fecha_creacion"].strftime("%d/%m/%Y")))
            self.tabla.setItem(row, 4, QTableWidgetItem(f"${float(f['monto']):,.2f}"))
            self.tabla.setItem(row, 5, QTableWidgetItem(f"${float(f['saldo_disponible']):,.2f}"))
            self.tabla.setItem(row, 6, QTableWidgetItem(ETIQUETAS_ESTADO_NC.get(f["estado"], f["estado"])))

        self.lbl_total.setText(f"{len(filas)} nota{'s' if len(filas) != 1 else ''} de crédito")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(
            self._chip(f"Total emitido: ${float(resultado['total_general']):,.2f}", "#FFFFFF", COLOR_WARNING)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: arqueo de caja ───────────────────────────────────────────

    def _mostrar_arqueo(self, resultado: dict) -> None:
        self._reset_tabla(COLS_ARQUEO_CAJA)
        movimientos = resultado["movimientos"]
        self.tabla.setRowCount(len(movimientos))
        for row, m in enumerate(movimientos):
            self.tabla.setItem(row, 0, QTableWidgetItem(m["fecha_registro"].strftime("%d/%m/%Y %H:%M")))
            self.tabla.setItem(row, 1, QTableWidgetItem(m["tipo_movimiento"].capitalize()))
            self.tabla.setItem(row, 2, QTableWidgetItem(m["descripcion_movimiento"] or ""))
            self.tabla.setItem(row, 3, QTableWidgetItem(f"${float(m['monto_movimiento']):,.2f}"))

        self.lbl_total.setText(f"{len(movimientos)} movimiento{'s' if len(movimientos) != 1 else ''}")
        self._mostrar_resumen_arqueo(resultado)

    def _mostrar_resumen_arqueo(self, resultado: dict) -> None:
        self._limpiar_resumen()
        self.resumen_layout.addWidget(self._chip(f"Apertura: ${float(resultado['saldo_apertura']):,.2f}"))
        self.resumen_layout.addWidget(
            self._chip(f"Entradas: ${float(resultado['total_entradas']):,.2f}", COLOR_SUCCESS)
        )
        self.resumen_layout.addWidget(self._chip(f"Salidas: ${float(resultado['total_salidas']):,.2f}", COLOR_DANGER))
        self.resumen_layout.addWidget(self._chip(f"Esperado: ${float(resultado['saldo_esperado']):,.2f}"))
        if resultado["saldo_cierre"] is not None:
            self.resumen_layout.addWidget(self._chip(f"Cierre: ${float(resultado['saldo_cierre']):,.2f}"))
            diferencia = float(resultado["diferencia"])
            color_fondo = COLOR_SUCCESS if diferencia == 0 else COLOR_DANGER
            self.resumen_layout.addWidget(self._chip(f"Diferencia: ${diferencia:,.2f}", "#FFFFFF", color_fondo))
        else:
            self.resumen_layout.addWidget(self._chip("Caja sigue abierta", COLOR_WARNING))
        self.resumen_layout.addStretch()

    # ── Resultados: kardex de producto ────────────────────────────────────────

    def _mostrar_kardex(self, resultado: dict) -> None:
        self._reset_tabla(COLS_KARDEX)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["fecha"].strftime("%d/%m/%Y")))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["tipo"]))
            self.tabla.setItem(row, 2, QTableWidgetItem(f["referencia"] or "N/A"))
            self.tabla.setItem(row, 3, QTableWidgetItem(f"{float(f['entrada']):,.2f}" if f["entrada"] else ""))
            self.tabla.setItem(row, 4, QTableWidgetItem(f"{float(f['salida']):,.2f}" if f["salida"] else ""))
            self.tabla.setItem(row, 5, QTableWidgetItem(f"{float(f['saldo']):,.2f}"))

        self.lbl_total.setText(
            f"{resultado['nombre_producto']} — {len(filas)} movimiento{'s' if len(filas) != 1 else ''}"
        )
        self._limpiar_resumen()
        self.resumen_layout.addWidget(self._chip(f"Saldo inicial: {float(resultado['saldo_inicial']):,.2f}"))
        self.resumen_layout.addWidget(
            self._chip(f"Saldo final: {float(resultado['saldo_final']):,.2f}", "#FFFFFF", COLOR_PRIMARY)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: valorización de inventario ────────────────────────────────

    def _mostrar_valorizacion(self, resultado: dict) -> None:
        self._reset_tabla(COLS_VALORIZACION)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["cod_producto"]))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["nombre_producto"]))
            self.tabla.setItem(row, 2, QTableWidgetItem(f["categoria"]))
            self.tabla.setItem(row, 3, QTableWidgetItem(f"{float(f['cantidad_unidad']):,.2f}"))
            self.tabla.setItem(row, 4, QTableWidgetItem(f"${float(f['costo_producto']):,.2f}"))
            self.tabla.setItem(row, 5, QTableWidgetItem(f"${float(f['valor_total']):,.2f}"))

        self.lbl_total.setText(f"{len(filas)} producto{'s' if len(filas) != 1 else ''}")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(
            self._chip(f"Valor total: ${float(resultado['total_general']):,.2f}", "#FFFFFF", COLOR_PRIMARY)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: stock bajo mínimo ─────────────────────────────────────────

    def _mostrar_bajo_minimo(self, resultado: dict) -> None:
        self._reset_tabla(COLS_BAJO_MINIMO)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["cod_producto"]))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["nombre_producto"]))
            self.tabla.setItem(row, 2, QTableWidgetItem(f["categoria"] or "N/A"))
            self.tabla.setItem(row, 3, QTableWidgetItem(f"{float(f['cantidad_unidad']):,.2f}"))
            self.tabla.setItem(row, 4, QTableWidgetItem(f"{float(f['cantidad_minima']):,.2f}"))
            self.tabla.setItem(row, 5, QTableWidgetItem(f"{float(f['deficit']):,.2f}"))

        total = resultado["total_productos"]
        self.lbl_total.setText(f"{total} producto{'s' if total != 1 else ''} bajo mínimo")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(self._chip(f"{total} alertas", COLOR_DANGER))
        self.resumen_layout.addStretch()

    # ── Resultados: productos sin movimiento ──────────────────────────────────

    def _mostrar_sin_movimiento(self, resultado: dict) -> None:
        self._reset_tabla(COLS_SIN_MOVIMIENTO)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["cod_producto"]))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["nombre_producto"]))
            self.tabla.setItem(row, 2, QTableWidgetItem(f["categoria"] or "N/A"))
            self.tabla.setItem(row, 3, QTableWidgetItem(f"{float(f['cantidad_unidad']):,.2f}"))
            self.tabla.setItem(row, 4, QTableWidgetItem(f"${float(f['costo_producto']):,.2f}"))
            fecha_mov = f["fecha_ultimo_movimiento"]
            self.tabla.setItem(row, 5, QTableWidgetItem(fecha_mov.strftime("%d/%m/%Y") if fecha_mov else "Nunca"))

        total = resultado["total_productos"]
        self.lbl_total.setText(f"{total} producto{'s' if total != 1 else ''} sin movimiento")
        self._limpiar_resumen()
        self.resumen_layout.addStretch()

    # ── Resultados: histórico de precios ──────────────────────────────────────

    def _mostrar_historico_precios(self, resultado: dict) -> None:
        self._reset_tabla(COLS_HISTORICO_PRECIOS)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["fecha_evento"].strftime("%d/%m/%Y %H:%M")))
            precio = f["precio_venta"]
            self.tabla.setItem(row, 1, QTableWidgetItem(f"${float(precio):,.2f}" if precio is not None else "N/A"))
            margen = f["porcentaje_ganancia"]
            self.tabla.setItem(row, 2, QTableWidgetItem(f"{float(margen):.2f}%" if margen is not None else "N/A"))
            self.tabla.setItem(row, 3, QTableWidgetItem(f["usuario"] or "N/A"))

        self.lbl_total.setText(f"{resultado['nombre_producto']} — {len(filas)} cambio{'s' if len(filas) != 1 else ''}")
        self._limpiar_resumen()
        self.resumen_layout.addStretch()

    # ── Resultados: estado de cuenta por cliente ──────────────────────────────

    def _mostrar_estado_cuenta_cliente(self, resultado: dict) -> None:
        self._reset_tabla(COLS_ESTADO_CTA_CLIENTE)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["fecha"].strftime("%d/%m/%Y")))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["tipo"]))
            self.tabla.setItem(row, 2, QTableWidgetItem(f["referencia"] or "N/A"))
            self.tabla.setItem(row, 3, QTableWidgetItem(f"${float(f['cargo']):,.2f}" if f["cargo"] else ""))
            self.tabla.setItem(row, 4, QTableWidgetItem(f"${float(f['abono']):,.2f}" if f["abono"] else ""))
            self.tabla.setItem(row, 5, QTableWidgetItem(f"${float(f['saldo']):,.2f}"))

        self.lbl_total.setText(f"{resultado['cliente']} — {len(filas)} movimiento{'s' if len(filas) != 1 else ''}")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(self._chip(f"Saldo inicial: ${float(resultado['saldo_inicial']):,.2f}"))
        self.resumen_layout.addWidget(
            self._chip(f"Saldo final: ${float(resultado['saldo_final']):,.2f}", "#FFFFFF", COLOR_PRIMARY)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: cobros del período ────────────────────────────────────────

    def _mostrar_cobros_periodo(self, resultado: dict) -> None:
        self._reset_tabla(COLS_COBROS_PERIODO)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["fecha_pago"].strftime("%d/%m/%Y")))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["cliente"] or "N/A"))
            self.tabla.setItem(row, 2, QTableWidgetItem(f["numero_factura"]))
            self.tabla.setItem(row, 3, QTableWidgetItem(f["metodo_pago"].capitalize()))
            self.tabla.setItem(row, 4, QTableWidgetItem(f["moneda"]))
            self.tabla.setItem(row, 5, QTableWidgetItem(f"${float(f['monto']):,.2f}"))

        self.lbl_total.setText(f"{len(filas)} cobro{'s' if len(filas) != 1 else ''}")
        self._limpiar_resumen()
        for metodo, monto in resultado["totales_por_metodo"].items():
            self.resumen_layout.addWidget(self._chip(f"{metodo.capitalize()}: ${float(monto):,.2f}"))
        self.resumen_layout.addWidget(
            self._chip(f"Total: ${float(resultado['total_general']):,.2f}", "#FFFFFF", COLOR_PRIMARY)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: clientes morosos ──────────────────────────────────────────

    def _mostrar_clientes_morosos(self, resultado: dict) -> None:
        self._reset_tabla(COLS_CLIENTES_MOROSOS)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["cliente"] or "N/A"))
            self.tabla.setItem(row, 1, QTableWidgetItem(f"${float(f['saldo_vencido']):,.2f}"))
            self.tabla.setItem(row, 2, QTableWidgetItem(str(f["dias_vencido_max"])))
            self.tabla.setItem(row, 3, QTableWidgetItem(str(f["facturas_vencidas"])))

        total = len(filas)
        self.lbl_total.setText(f"{total} cliente{'s' if total != 1 else ''} moroso{'s' if total != 1 else ''}")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(
            self._chip(f"Total vencido: ${float(resultado['total_general']):,.2f}", "#FFFFFF", COLOR_DANGER)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: CxC otras ─────────────────────────────────────────────────

    def _mostrar_cxc_otras(self, resultado: dict) -> None:
        self._reset_tabla(COLS_CXC_OTRAS)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["cliente"] or "N/A"))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["descripcion"] or ""))
            fecha_em = f["fecha_emision"].strftime("%d/%m/%Y") if f["fecha_emision"] else "N/A"
            self.tabla.setItem(row, 2, QTableWidgetItem(fecha_em))
            fecha_venc = f["fecha_vencimiento"].strftime("%d/%m/%Y") if f["fecha_vencimiento"] else "N/A"
            self.tabla.setItem(row, 3, QTableWidgetItem(fecha_venc))
            self.tabla.setItem(row, 4, QTableWidgetItem(f"${float(f['monto_total']):,.2f}"))
            self.tabla.setItem(row, 5, QTableWidgetItem(f"${float(f['saldo_pendiente']):,.2f}"))
            self.tabla.setItem(row, 6, QTableWidgetItem(ETIQUETAS_ESTADO_CXC_OTRO.get(f["estado"], f["estado"])))

        self.lbl_total.setText(f"{len(filas)} cuenta{'s' if len(filas) != 1 else ''}")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(
            self._chip(f"Saldo pendiente: ${float(resultado['total_general']):,.2f}", "#FFFFFF", COLOR_PRIMARY)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: estado de cuenta por proveedor ────────────────────────────

    def _mostrar_estado_cuenta_proveedor(self, resultado: dict) -> None:
        self._reset_tabla(COLS_ESTADO_CTA_PROVEEDOR)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["fecha"].strftime("%d/%m/%Y")))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["tipo"]))
            self.tabla.setItem(row, 2, QTableWidgetItem(f["referencia"] or "N/A"))
            self.tabla.setItem(row, 3, QTableWidgetItem(f"${float(f['cargo']):,.2f}" if f["cargo"] else ""))
            self.tabla.setItem(row, 4, QTableWidgetItem(f"${float(f['abono']):,.2f}" if f["abono"] else ""))
            self.tabla.setItem(row, 5, QTableWidgetItem(f"${float(f['saldo']):,.2f}"))

        self.lbl_total.setText(f"{resultado['proveedor']} — {len(filas)} movimiento{'s' if len(filas) != 1 else ''}")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(self._chip(f"Saldo inicial: ${float(resultado['saldo_inicial']):,.2f}"))
        self.resumen_layout.addWidget(
            self._chip(f"Saldo final: ${float(resultado['saldo_final']):,.2f}", "#FFFFFF", COLOR_PRIMARY)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: pagos del período ─────────────────────────────────────────

    def _mostrar_pagos_periodo(self, resultado: dict) -> None:
        self._reset_tabla(COLS_PAGOS_PERIODO)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["fecha_pago"].strftime("%d/%m/%Y")))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["proveedor"] or "N/A"))
            self.tabla.setItem(row, 2, QTableWidgetItem(f["numero_compra"]))
            self.tabla.setItem(row, 3, QTableWidgetItem(f["metodo_pago"].capitalize()))
            self.tabla.setItem(row, 4, QTableWidgetItem(f"${float(f['monto']):,.2f}"))

        self.lbl_total.setText(f"{len(filas)} pago{'s' if len(filas) != 1 else ''}")
        self._limpiar_resumen()
        for metodo, monto in resultado["totales_por_metodo"].items():
            self.resumen_layout.addWidget(self._chip(f"{metodo.capitalize()}: ${float(monto):,.2f}"))
        self.resumen_layout.addWidget(
            self._chip(f"Total: ${float(resultado['total_general']):,.2f}", "#FFFFFF", COLOR_PRIMARY)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: próximos vencimientos (CxP) ───────────────────────────────

    def _mostrar_proximos_vencimientos(self, resultado: dict) -> None:
        self._reset_tabla(COLS_PROXIMOS_VENCIMIENTOS)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["numero_compra"]))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["proveedor"] or "N/A"))
            self.tabla.setItem(row, 2, QTableWidgetItem(f["fecha_vencimiento"].strftime("%d/%m/%Y")))
            self.tabla.setItem(row, 3, QTableWidgetItem(str(f["dias_para_vencer"])))
            self.tabla.setItem(row, 4, QTableWidgetItem(f"${float(f['saldo_pendiente']):,.2f}"))

        self.lbl_total.setText(f"{len(filas)} cuenta{'s' if len(filas) != 1 else ''} por vencer")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(
            self._chip(f"Total: ${float(resultado['total_general']):,.2f}", "#FFFFFF", COLOR_PRIMARY)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: CxP otras ──────────────────────────────────────────────────

    def _mostrar_cxp_otras(self, resultado: dict) -> None:
        self._reset_tabla(COLS_CXP_OTRAS)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["cuenta_bancaria"] or "N/A"))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["referencia_bancaria"] or ""))
            self.tabla.setItem(row, 2, QTableWidgetItem(f["descripcion"] or ""))
            self.tabla.setItem(row, 3, QTableWidgetItem(f["fecha_recepcion"].strftime("%d/%m/%Y")))
            self.tabla.setItem(row, 4, QTableWidgetItem(f["cliente_identificado"] or "Sin identificar"))
            self.tabla.setItem(row, 5, QTableWidgetItem(f"${float(f['monto_total']):,.2f}"))
            self.tabla.setItem(row, 6, QTableWidgetItem(f"${float(f['saldo_pendiente']):,.2f}"))
            self.tabla.setItem(row, 7, QTableWidgetItem(ETIQUETAS_ESTADO_CXP_OTRO.get(f["estado"], f["estado"])))

        self.lbl_total.setText(f"{len(filas)} cuenta{'s' if len(filas) != 1 else ''}")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(
            self._chip(f"Saldo pendiente: ${float(resultado['total_general']):,.2f}", "#FFFFFF", COLOR_PRIMARY)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: movimientos de caja por período ───────────────────────────

    def _mostrar_mov_caja_periodo(self, resultado: dict) -> None:
        self._reset_tabla(COLS_MOV_CAJA_PERIODO)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["fecha_registro"].strftime("%d/%m/%Y %H:%M")))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["caja"] or "N/A"))
            self.tabla.setItem(row, 2, QTableWidgetItem(f["tipo_movimiento"].capitalize()))
            self.tabla.setItem(row, 3, QTableWidgetItem(f["origen"]))
            self.tabla.setItem(row, 4, QTableWidgetItem(f["descripcion_movimiento"] or ""))
            self.tabla.setItem(row, 5, QTableWidgetItem(f"${float(f['monto_movimiento']):,.2f}"))

        self.lbl_total.setText(f"{len(filas)} movimiento{'s' if len(filas) != 1 else ''}")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(
            self._chip(f"Entradas: ${float(resultado['total_entradas']):,.2f}", COLOR_SUCCESS)
        )
        self.resumen_layout.addWidget(self._chip(f"Salidas: ${float(resultado['total_salidas']):,.2f}", COLOR_DANGER))
        self.resumen_layout.addWidget(self._chip(f"Neto: ${float(resultado['neto']):,.2f}", "#FFFFFF", COLOR_PRIMARY))
        self.resumen_layout.addStretch()

    # ── Resultados: cierre diario por cajero ──────────────────────────────────

    def _mostrar_cierre_cajero(self, resultado: dict) -> None:
        self._reset_tabla(COLS_CIERRE_CAJERO)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["caja"] or "N/A"))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["cajero"] or "N/A"))
            self.tabla.setItem(row, 2, QTableWidgetItem(f["fecha_apertura"].strftime("%d/%m/%Y %H:%M")))
            fecha_cierre = f["fecha_cierre"].strftime("%d/%m/%Y %H:%M") if f["fecha_cierre"] else "Abierta"
            self.tabla.setItem(row, 3, QTableWidgetItem(fecha_cierre))
            self.tabla.setItem(row, 4, QTableWidgetItem(f"${float(f['saldo_apertura']):,.2f}"))
            self.tabla.setItem(row, 5, QTableWidgetItem(f"${float(f['total_entradas']):,.2f}"))
            self.tabla.setItem(row, 6, QTableWidgetItem(f"${float(f['total_salidas']):,.2f}"))
            self.tabla.setItem(row, 7, QTableWidgetItem(f"${float(f['saldo_esperado']):,.2f}"))
            saldo_cierre = f"${float(f['saldo_cierre']):,.2f}" if f["saldo_cierre"] is not None else "N/A"
            self.tabla.setItem(row, 8, QTableWidgetItem(saldo_cierre))
            diferencia = f"${float(f['diferencia']):,.2f}" if f["diferencia"] is not None else "N/A"
            self.tabla.setItem(row, 9, QTableWidgetItem(diferencia))

        self.lbl_total.setText(f"{resultado['total_turnos']} turno{'s' if resultado['total_turnos'] != 1 else ''}")
        self._limpiar_resumen()
        self.resumen_layout.addStretch()

    # ── Resultados: flujo de caja consolidado ─────────────────────────────────

    def _mostrar_flujo_caja(self, resultado: dict) -> None:
        self._reset_tabla(COLS_FLUJO_CAJA)
        filas = resultado["filas"]
        formato_fecha = "%d/%m/%Y" if resultado["agrupacion"] == "dia" else "%m/%Y"
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["periodo"].strftime(formato_fecha)))
            self.tabla.setItem(row, 1, QTableWidgetItem(f"${float(f['entradas_caja']):,.2f}"))
            self.tabla.setItem(row, 2, QTableWidgetItem(f"${float(f['salidas_caja']):,.2f}"))
            self.tabla.setItem(row, 3, QTableWidgetItem(f"${float(f['entradas_banco']):,.2f}"))
            self.tabla.setItem(row, 4, QTableWidgetItem(f"${float(f['salidas_banco']):,.2f}"))
            self.tabla.setItem(row, 5, QTableWidgetItem(f"${float(f['neto']):,.2f}"))

        self.lbl_total.setText(f"{len(filas)} período{'s' if len(filas) != 1 else ''}")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(
            self._chip(f"Entradas: ${float(resultado['total_entradas']):,.2f}", COLOR_SUCCESS)
        )
        self.resumen_layout.addWidget(self._chip(f"Salidas: ${float(resultado['total_salidas']):,.2f}", COLOR_DANGER))
        self.resumen_layout.addStretch()

    # ── Resultados: movimientos por cuenta bancaria ───────────────────────────

    def _mostrar_mov_cuenta_bancaria(self, resultado: dict) -> None:
        self._reset_tabla(COLS_MOV_CUENTA_BANCARIA)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["fecha_movimiento"].strftime("%d/%m/%Y")))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["tipo_movimiento"].capitalize()))
            self.tabla.setItem(row, 2, QTableWidgetItem(f["referencia_movimiento"] or "N/A"))
            self.tabla.setItem(row, 3, QTableWidgetItem(f["descripcion_movimiento"] or ""))
            self.tabla.setItem(row, 4, QTableWidgetItem(f"${float(f['monto_movimiento']):,.2f}"))
            self.tabla.setItem(row, 5, QTableWidgetItem(f"${float(f['saldo']):,.2f}"))

        total = len(filas)
        self.lbl_total.setText(f"{resultado['numero_cuenta']} — {total} movimiento{'s' if total != 1 else ''}")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(self._chip(f"Saldo inicial: ${float(resultado['saldo_inicial']):,.2f}"))
        self.resumen_layout.addWidget(
            self._chip(f"Saldo final: ${float(resultado['saldo_final']):,.2f}", "#FFFFFF", COLOR_PRIMARY)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: conciliación bancaria ─────────────────────────────────────

    def _mostrar_conciliacion_bancaria(self, resultado: dict) -> None:
        self._reset_tabla(COLS_CONCILIACION_BANCARIA)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["numero_cuenta"] or "N/A"))
            self.tabla.setItem(row, 1, QTableWidgetItem(f"${float(f['total_pendiente']):,.2f}"))
            self.tabla.setItem(row, 2, QTableWidgetItem(str(f["cantidad_pendiente"])))
            self.tabla.setItem(row, 3, QTableWidgetItem(f"${float(f['total_conciliado']):,.2f}"))
            self.tabla.setItem(row, 4, QTableWidgetItem(str(f["cantidad_conciliada"])))

        self.lbl_total.setText(f"{len(filas)} cuenta{'s' if len(filas) != 1 else ''}")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(
            self._chip(f"Pendiente: ${float(resultado['total_pendiente']):,.2f}", COLOR_WARNING)
        )
        self.resumen_layout.addWidget(
            self._chip(f"Conciliado: ${float(resultado['total_conciliado']):,.2f}", COLOR_SUCCESS)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: saldo consolidado ─────────────────────────────────────────

    def _mostrar_saldo_consolidado(self, resultado: dict) -> None:
        self._reset_tabla(COLS_SALDO_CONSOLIDADO)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["banco"]))
            self.tabla.setItem(row, 1, QTableWidgetItem(f["numero_cuenta"] or "N/A"))
            self.tabla.setItem(row, 2, QTableWidgetItem(f["tipo_cuenta"] or "N/A"))
            self.tabla.setItem(row, 3, QTableWidgetItem(f["nombre_titular"] or "N/A"))
            self.tabla.setItem(row, 4, QTableWidgetItem(f"${float(f['saldo_actual']):,.2f}"))

        self.lbl_total.setText(f"{len(filas)} cuenta{'s' if len(filas) != 1 else ''}")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(
            self._chip(f"Total: ${float(resultado['total_general']):,.2f}", "#FFFFFF", COLOR_PRIMARY)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: comisiones por vendedor/período ───────────────────────────

    def _mostrar_comisiones_vendedor(self, resultado: dict) -> None:
        self._reset_tabla(COLS_COMISIONES_VENDEDOR)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["vendedor"] or "N/A"))
            self.tabla.setItem(row, 1, QTableWidgetItem(str(f["cantidad_facturas"])))
            self.tabla.setItem(row, 2, QTableWidgetItem(f"${float(f['monto_comision']):,.2f}"))

        self.lbl_total.setText(f"{len(filas)} vendedor{'es' if len(filas) != 1 else ''}")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(
            self._chip(f"Total comisiones: ${float(resultado['total_general']):,.2f}", "#FFFFFF", COLOR_PRIMARY)
        )
        self.resumen_layout.addStretch()

    # ── Resultados: comisiones pagadas vs. pendientes ─────────────────────────

    def _mostrar_comisiones_pagadas_pendientes(self, resultado: dict) -> None:
        self._reset_tabla(COLS_COMISIONES_PAGADAS_PENDIENTES)
        filas = resultado["filas"]
        self.tabla.setRowCount(len(filas))
        for row, f in enumerate(filas):
            self.tabla.setItem(row, 0, QTableWidgetItem(f["vendedor"] or "N/A"))
            self.tabla.setItem(row, 1, QTableWidgetItem(f"${float(f['pagado']):,.2f}"))
            self.tabla.setItem(row, 2, QTableWidgetItem(f"${float(f['pendiente']):,.2f}"))

        self.lbl_total.setText(f"{len(filas)} vendedor{'es' if len(filas) != 1 else ''}")
        self._limpiar_resumen()
        self.resumen_layout.addWidget(self._chip(f"Pagado: ${float(resultado['total_pagado']):,.2f}", COLOR_SUCCESS))
        self.resumen_layout.addWidget(
            self._chip(f"Pendiente: ${float(resultado['total_pendiente']):,.2f}", COLOR_WARNING)
        )
        self.resumen_layout.addStretch()

    # ── Chips de resumen ─────────────────────────────────────────────────────

    def _chip(self, texto: str, color: str = COLOR_TEXT_MUTED, fondo: str = COLOR_TABLE_HEADER) -> QLabel:
        lbl = QLabel(texto)
        lbl.setStyleSheet(
            f"color: {color}; background-color: {fondo}; border-radius: 10px;"
            " padding: 4px 12px; font-size: 12px; font-weight: 600;"
        )
        return lbl

    def _limpiar_resumen(self) -> None:
        while self.resumen_layout.count():
            item = self.resumen_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    # ── Exportación ──────────────────────────────────────────────────────────

    def _filas_para_exportar(self) -> tuple[str, list[str], list[list]]:
        if self._ultimo_modo == REPORTE_AGING_CXC:
            filas = [
                [
                    f["numero_factura"],
                    f["cliente"],
                    f["fecha_vencimiento"],
                    float(f["saldo_pendiente"]),
                    f["dias_vencido"],
                    ETIQUETAS_BUCKET.get(f["bucket"], f["bucket"]),
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "aging_cxc", COLS_AGING_CXC, filas

        if self._ultimo_modo == REPORTE_AGING_CXP:
            filas = [
                [
                    f["numero_compra"],
                    f["proveedor"],
                    f["fecha_vencimiento"],
                    float(f["saldo_pendiente"]),
                    f["dias_vencido"],
                    ETIQUETAS_BUCKET.get(f["bucket"], f["bucket"]),
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "aging_cxp", COLS_AGING_CXP, filas

        if self._ultimo_modo == REPORTE_LIBRO_VENTAS:
            filas = [
                [
                    f["fecha_emision"],
                    f["numero_control"],
                    f["numero_factura"],
                    f["cliente"],
                    f["identificacion_cliente"],
                    float(f["base_imponible"]),
                    float(f["porcentaje_iva"]),
                    float(f["monto_iva"]),
                    float(f["total"]),
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "libro_ventas", COLS_LIBRO_VENTAS, filas

        if self._ultimo_modo == REPORTE_VENTAS_PERIODO:
            filas = [[f["fecha"], f["cantidad_facturas"], float(f["total"])] for f in self._ultimo_resultado["filas"]]
            return "ventas_periodo", COLS_VENTAS_PERIODO, filas

        if self._ultimo_modo == REPORTE_VENTAS_CLIENTE:
            filas = [[f["cliente"], f["cantidad_facturas"], float(f["total"])] for f in self._ultimo_resultado["filas"]]
            return "ventas_cliente", COLS_VENTAS_CLIENTE, filas

        if self._ultimo_modo == REPORTE_VENTAS_VENDEDOR:
            filas = [
                [f["vendedor"], f["cantidad_facturas"], float(f["total"]), float(f["ticket_promedio"])]
                for f in self._ultimo_resultado["filas"]
            ]
            return "ventas_vendedor", COLS_VENTAS_VENDEDOR, filas

        if self._ultimo_modo == REPORTE_VENTAS_RUTA:
            filas = [
                [f["ruta"], f["cantidad_facturas"], float(f["total"]), float(f["ticket_promedio"])]
                for f in self._ultimo_resultado["filas"]
            ]
            return "ventas_ruta", COLS_VENTAS_RUTA, filas

        if self._ultimo_modo == REPORTE_PRODUCTOS_VENDIDOS:
            filas = [[f["producto"], float(f["cantidad"]), float(f["total"])] for f in self._ultimo_resultado["filas"]]
            return "productos_vendidos", COLS_PRODUCTOS_VENDIDOS, filas

        if self._ultimo_modo == REPORTE_FACTURAS_ANULADAS:
            filas = [
                [f["numero_factura"], f["cliente"], f["vendedor"], f["fecha_emision"], f["motivo"]]
                for f in self._ultimo_resultado["filas"]
            ]
            return "facturas_anuladas", COLS_FACTURAS_ANULADAS, filas

        if self._ultimo_modo == REPORTE_NC_EMITIDAS:
            filas = [
                [
                    f["numero_nota_credito"],
                    f["cliente"],
                    f["numero_factura_origen"],
                    f["fecha_creacion"],
                    float(f["monto"]),
                    float(f["saldo_disponible"]),
                    ETIQUETAS_ESTADO_NC.get(f["estado"], f["estado"]),
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "notas_credito_emitidas", COLS_NC_EMITIDAS, filas

        if self._ultimo_modo == REPORTE_CONTADO_CREDITO:
            filas = [
                [f["condicion_pago"].capitalize(), f["cantidad_facturas"], float(f["total"]), float(f["porcentaje"])]
                for f in self._ultimo_resultado["filas"]
            ]
            return "ventas_contado_vs_credito", COLS_CONTADO_CREDITO, filas

        if self._ultimo_modo == REPORTE_MARGEN_UTILIDAD:
            filas = [
                [
                    f["producto"],
                    float(f["cantidad"]),
                    float(f["ingreso"]),
                    float(f["costo"]),
                    float(f["margen"]),
                    float(f["margen_pct"]),
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "margen_utilidad", COLS_MARGEN_UTILIDAD, filas

        if self._ultimo_modo == REPORTE_COMPRAS_PERIODO:
            filas = [[f["fecha"], f["cantidad_compras"], float(f["total"])] for f in self._ultimo_resultado["filas"]]
            return "compras_periodo", COLS_COMPRAS_PERIODO, filas

        if self._ultimo_modo == REPORTE_COMPRAS_PROVEEDOR:
            filas = [
                [f["proveedor"], f["cantidad_compras"], float(f["total"])] for f in self._ultimo_resultado["filas"]
            ]
            return "compras_proveedor", COLS_COMPRAS_PROVEEDOR, filas

        if self._ultimo_modo == REPORTE_COMPRAS_PRODUCTO:
            filas = [[f["producto"], float(f["cantidad"]), float(f["total"])] for f in self._ultimo_resultado["filas"]]
            return "compras_producto", COLS_COMPRAS_PRODUCTO, filas

        if self._ultimo_modo == REPORTE_OC_ABIERTAS:
            filas = [
                [
                    f["numero_oc"],
                    f["proveedor"],
                    f["fecha_oc"],
                    f["fecha_estimada_entrega"],
                    float(f["cantidad_solicitada"]),
                    float(f["cantidad_recibida"]),
                    float(f["cantidad_pendiente"]),
                    ETIQUETAS_ESTADO_OC.get(f["estado"], f["estado"]),
                    float(f["total_oc"]),
                    "Sí" if f["vencida"] else "No",
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "ordenes_compra_abiertas", COLS_OC_ABIERTAS, filas

        if self._ultimo_modo == REPORTE_CUMPLIMIENTO_PROVEEDORES:
            filas = [
                [
                    f["proveedor"],
                    f["cantidad_oc"],
                    f["a_tiempo"],
                    f["tardias"],
                    f["sin_fecha_estimada"],
                    float(f["pct_a_tiempo"]) if f["pct_a_tiempo"] is not None else None,
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "cumplimiento_proveedores", COLS_CUMPLIMIENTO_PROVEEDORES, filas

        if self._ultimo_modo == REPORTE_DEVOLUCIONES_PROVEEDOR:
            filas = [
                [
                    f["numero_nota_devolucion"],
                    f["proveedor"],
                    f["numero_oc"],
                    f["fecha_devolucion"],
                    f["motivo"],
                    float(f["cantidad_total"]),
                    f["estado"].capitalize(),
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "devoluciones_proveedor", COLS_DEVOLUCIONES_PROVEEDOR, filas

        if self._ultimo_modo == REPORTE_NC_PROVEEDOR:
            filas = [
                [
                    f["id_nota_credito"],
                    f["proveedor"],
                    f["numero_compra_origen"],
                    f["fecha_creacion"],
                    float(f["monto"]),
                    float(f["saldo_disponible"]),
                    ETIQUETAS_ESTADO_NC.get(f["estado"], f["estado"]),
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "notas_credito_proveedor", COLS_NC_PROVEEDOR, filas

        if self._ultimo_modo == REPORTE_ARQUEO_CAJA:
            filas = [
                [m["fecha_registro"], m["tipo_movimiento"], m["descripcion_movimiento"], float(m["monto_movimiento"])]
                for m in self._ultimo_resultado["movimientos"]
            ]
            return "arqueo_caja", COLS_ARQUEO_CAJA, filas

        if self._ultimo_modo == REPORTE_KARDEX:
            filas = [
                [f["fecha"], f["tipo"], f["referencia"], float(f["entrada"]), float(f["salida"]), float(f["saldo"])]
                for f in self._ultimo_resultado["filas"]
            ]
            return "kardex_producto", COLS_KARDEX, filas

        if self._ultimo_modo == REPORTE_VALORIZACION:
            filas = [
                [
                    f["cod_producto"],
                    f["nombre_producto"],
                    f["categoria"],
                    float(f["cantidad_unidad"]),
                    float(f["costo_producto"]),
                    float(f["valor_total"]),
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "valorizacion_inventario", COLS_VALORIZACION, filas

        if self._ultimo_modo == REPORTE_BAJO_MINIMO:
            filas = [
                [
                    f["cod_producto"],
                    f["nombre_producto"],
                    f["categoria"],
                    float(f["cantidad_unidad"]),
                    float(f["cantidad_minima"]),
                    float(f["deficit"]),
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "productos_bajo_minimo", COLS_BAJO_MINIMO, filas

        if self._ultimo_modo == REPORTE_SIN_MOVIMIENTO:
            filas = [
                [
                    f["cod_producto"],
                    f["nombre_producto"],
                    f["categoria"],
                    float(f["cantidad_unidad"]),
                    float(f["costo_producto"]),
                    f["fecha_ultimo_movimiento"],
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "productos_sin_movimiento", COLS_SIN_MOVIMIENTO, filas

        if self._ultimo_modo == REPORTE_HISTORICO_PRECIOS:
            filas = [
                [
                    f["fecha_evento"],
                    float(f["precio_venta"]) if f["precio_venta"] is not None else None,
                    float(f["porcentaje_ganancia"]) if f["porcentaje_ganancia"] is not None else None,
                    f["usuario"],
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "historico_precios", COLS_HISTORICO_PRECIOS, filas

        if self._ultimo_modo == REPORTE_ESTADO_CTA_CLIENTE:
            filas = [
                [f["fecha"], f["tipo"], f["referencia"], float(f["cargo"]), float(f["abono"]), float(f["saldo"])]
                for f in self._ultimo_resultado["filas"]
            ]
            return "estado_cuenta_cliente", COLS_ESTADO_CTA_CLIENTE, filas

        if self._ultimo_modo == REPORTE_COBROS_PERIODO:
            filas = [
                [f["fecha_pago"], f["cliente"], f["numero_factura"], f["metodo_pago"], f["moneda"], float(f["monto"])]
                for f in self._ultimo_resultado["filas"]
            ]
            return "cobros_periodo", COLS_COBROS_PERIODO, filas

        if self._ultimo_modo == REPORTE_CLIENTES_MOROSOS:
            filas = [
                [f["cliente"], float(f["saldo_vencido"]), f["dias_vencido_max"], f["facturas_vencidas"]]
                for f in self._ultimo_resultado["filas"]
            ]
            return "clientes_morosos", COLS_CLIENTES_MOROSOS, filas

        if self._ultimo_modo == REPORTE_CXC_OTRAS:
            filas = [
                [
                    f["cliente"],
                    f["descripcion"],
                    f["fecha_emision"],
                    f["fecha_vencimiento"],
                    float(f["monto_total"]),
                    float(f["saldo_pendiente"]),
                    ETIQUETAS_ESTADO_CXC_OTRO.get(f["estado"], f["estado"]),
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "cxc_otras", COLS_CXC_OTRAS, filas

        if self._ultimo_modo == REPORTE_ESTADO_CTA_PROVEEDOR:
            filas = [
                [f["fecha"], f["tipo"], f["referencia"], float(f["cargo"]), float(f["abono"]), float(f["saldo"])]
                for f in self._ultimo_resultado["filas"]
            ]
            return "estado_cuenta_proveedor", COLS_ESTADO_CTA_PROVEEDOR, filas

        if self._ultimo_modo == REPORTE_PAGOS_PERIODO:
            filas = [
                [f["fecha_pago"], f["proveedor"], f["numero_compra"], f["metodo_pago"], float(f["monto"])]
                for f in self._ultimo_resultado["filas"]
            ]
            return "pagos_periodo", COLS_PAGOS_PERIODO, filas

        if self._ultimo_modo == REPORTE_PROXIMOS_VENCIMIENTOS:
            filas = [
                [
                    f["numero_compra"],
                    f["proveedor"],
                    f["fecha_vencimiento"],
                    f["dias_para_vencer"],
                    float(f["saldo_pendiente"]),
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "proximos_vencimientos", COLS_PROXIMOS_VENCIMIENTOS, filas

        if self._ultimo_modo == REPORTE_CXP_OTRAS:
            filas = [
                [
                    f["cuenta_bancaria"],
                    f["referencia_bancaria"],
                    f["descripcion"],
                    f["fecha_recepcion"],
                    f["cliente_identificado"],
                    float(f["monto_total"]),
                    float(f["saldo_pendiente"]),
                    ETIQUETAS_ESTADO_CXP_OTRO.get(f["estado"], f["estado"]),
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "cxp_otras", COLS_CXP_OTRAS, filas

        if self._ultimo_modo == REPORTE_MOV_CAJA_PERIODO:
            filas = [
                [
                    f["fecha_registro"],
                    f["caja"],
                    f["tipo_movimiento"],
                    f["origen"],
                    f["descripcion_movimiento"],
                    float(f["monto_movimiento"]),
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "movimientos_caja_periodo", COLS_MOV_CAJA_PERIODO, filas

        if self._ultimo_modo == REPORTE_CIERRE_CAJERO:
            filas = [
                [
                    f["caja"],
                    f["cajero"],
                    f["fecha_apertura"],
                    f["fecha_cierre"],
                    float(f["saldo_apertura"]),
                    float(f["total_entradas"]),
                    float(f["total_salidas"]),
                    float(f["saldo_esperado"]),
                    float(f["saldo_cierre"]) if f["saldo_cierre"] is not None else None,
                    float(f["diferencia"]) if f["diferencia"] is not None else None,
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "cierre_diario_cajero", COLS_CIERRE_CAJERO, filas

        if self._ultimo_modo == REPORTE_FLUJO_CAJA:
            filas = [
                [
                    f["periodo"],
                    float(f["entradas_caja"]),
                    float(f["salidas_caja"]),
                    float(f["entradas_banco"]),
                    float(f["salidas_banco"]),
                    float(f["neto"]),
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "flujo_caja_consolidado", COLS_FLUJO_CAJA, filas

        if self._ultimo_modo == REPORTE_MOV_CUENTA_BANCARIA:
            filas = [
                [
                    f["fecha_movimiento"],
                    f["tipo_movimiento"],
                    f["referencia_movimiento"],
                    f["descripcion_movimiento"],
                    float(f["monto_movimiento"]),
                    float(f["saldo"]),
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "movimientos_cuenta_bancaria", COLS_MOV_CUENTA_BANCARIA, filas

        if self._ultimo_modo == REPORTE_CONCILIACION_BANCARIA:
            filas = [
                [
                    f["numero_cuenta"],
                    float(f["total_pendiente"]),
                    f["cantidad_pendiente"],
                    float(f["total_conciliado"]),
                    f["cantidad_conciliada"],
                ]
                for f in self._ultimo_resultado["filas"]
            ]
            return "conciliacion_bancaria", COLS_CONCILIACION_BANCARIA, filas

        if self._ultimo_modo == REPORTE_SALDO_CONSOLIDADO:
            filas = [
                [f["banco"], f["numero_cuenta"], f["tipo_cuenta"], f["nombre_titular"], float(f["saldo_actual"])]
                for f in self._ultimo_resultado["filas"]
            ]
            return "saldo_consolidado", COLS_SALDO_CONSOLIDADO, filas

        if self._ultimo_modo == REPORTE_COMISIONES_VENDEDOR:
            filas = [
                [f["vendedor"], f["cantidad_facturas"], float(f["monto_comision"])]
                for f in self._ultimo_resultado["filas"]
            ]
            return "comisiones_vendedor", COLS_COMISIONES_VENDEDOR, filas

        filas = [[f["vendedor"], float(f["pagado"]), float(f["pendiente"])] for f in self._ultimo_resultado["filas"]]
        return "comisiones_pagadas_pendientes", COLS_COMISIONES_PAGADAS_PENDIENTES, filas

    def _info_pdf(self) -> tuple[str, dict, list[float]]:
        resultado = self._ultimo_resultado
        if self._ultimo_modo == REPORTE_AGING_CXC:
            filtros = {
                "Corte": resultado["fecha_corte"].strftime("%d/%m/%Y"),
                "Cliente": self.cliente_combo.currentText(),
                "Total general": f"${float(resultado['total_general']):,.2f}",
            }
            return "Antigüedad de Saldos - Cuentas por Cobrar", filtros, [1.2, 2.0, 1.2, 1.3, 1.0, 1.0]

        if self._ultimo_modo == REPORTE_AGING_CXP:
            filtros = {
                "Corte": resultado["fecha_corte"].strftime("%d/%m/%Y"),
                "Proveedor": self.proveedor_combo.currentText(),
                "Total general": f"${float(resultado['total_general']):,.2f}",
            }
            return "Antigüedad de Saldos - Cuentas por Pagar", filtros, [1.2, 2.0, 1.2, 1.3, 1.0, 1.0]

        if self._ultimo_modo == REPORTE_LIBRO_VENTAS:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Cliente": self.cliente_combo_lv.currentText(),
                "Base imponible": f"${float(resultado['total_base_imponible']):,.2f}",
                "IVA": f"${float(resultado['total_iva']):,.2f}",
                "Total": f"${float(resultado['total_general']):,.2f}",
            }
            return "Libro de Ventas", filtros, [1.0, 1.0, 1.0, 1.8, 1.2, 1.2, 0.8, 1.0, 1.0]

        if self._ultimo_modo == REPORTE_VENTAS_PERIODO:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Agrupación": "Día" if resultado["agrupacion"] == "dia" else "Mes",
                "Total general": f"${float(resultado['total_general']):,.2f}",
            }
            return "Ventas por Período", filtros, [1.0, 1.0, 1.0]

        if self._ultimo_modo == REPORTE_VENTAS_CLIENTE:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Total general": f"${float(resultado['total_general']):,.2f}",
            }
            return "Ventas por Cliente", filtros, [2.0, 1.0, 1.2]

        if self._ultimo_modo == REPORTE_VENTAS_VENDEDOR:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Total general": f"${float(resultado['total_general']):,.2f}",
            }
            return "Ventas por Vendedor", filtros, [2.0, 1.0, 1.2, 1.3]

        if self._ultimo_modo == REPORTE_VENTAS_RUTA:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Total general": f"${float(resultado['total_general']):,.2f}",
            }
            return "Ventas por Ruta", filtros, [2.0, 1.0, 1.2, 1.3]

        if self._ultimo_modo == REPORTE_PRODUCTOS_VENDIDOS:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Orden": "Más vendidos" if resultado["orden"] == "desc" else "Menos vendidos",
                "Total general": f"${float(resultado['total_general']):,.2f}",
            }
            return "Productos Más/Menos Vendidos", filtros, [2.0, 1.0, 1.2]

        if self._ultimo_modo == REPORTE_FACTURAS_ANULADAS:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Total": f"{resultado['total_facturas']} facturas",
            }
            return "Facturas Anuladas", filtros, [1.0, 1.5, 1.3, 1.0, 2.0]

        if self._ultimo_modo == REPORTE_NC_EMITIDAS:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Cliente": self.cliente_combo_nc.currentText(),
                "Total emitido": f"${float(resultado['total_general']):,.2f}",
            }
            return "Notas de Crédito Emitidas", filtros, [1.0, 1.6, 1.0, 1.0, 1.0, 1.0, 1.0]

        if self._ultimo_modo == REPORTE_CONTADO_CREDITO:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Total general": f"${float(resultado['total_general']):,.2f}",
            }
            return "Ventas Contado vs. Crédito", filtros, [1.2, 1.0, 1.2, 1.0]

        if self._ultimo_modo == REPORTE_MARGEN_UTILIDAD:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Ingreso": f"${float(resultado['total_ingreso']):,.2f}",
                "Costo": f"${float(resultado['total_costo']):,.2f}",
                "Margen": f"${float(resultado['total_margen']):,.2f}",
            }
            return "Margen de Utilidad por Producto", filtros, [1.8, 1.0, 1.0, 1.0, 1.0, 1.0]

        if self._ultimo_modo == REPORTE_COMPRAS_PERIODO:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Agrupación": "Día" if resultado["agrupacion"] == "dia" else "Mes",
                "Total general": f"${float(resultado['total_general']):,.2f}",
            }
            return "Compras por Período", filtros, [1.0, 1.0, 1.0]

        if self._ultimo_modo == REPORTE_COMPRAS_PROVEEDOR:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Total general": f"${float(resultado['total_general']):,.2f}",
            }
            return "Compras por Proveedor", filtros, [2.0, 1.0, 1.2]

        if self._ultimo_modo == REPORTE_COMPRAS_PRODUCTO:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Orden": "Más comprados" if resultado["orden"] == "desc" else "Menos comprados",
                "Total general": f"${float(resultado['total_general']):,.2f}",
            }
            return "Compras por Producto", filtros, [2.0, 1.0, 1.2]

        if self._ultimo_modo == REPORTE_OC_ABIERTAS:
            filtros = {
                "Corte": resultado["fecha_corte"].strftime("%d/%m/%Y"),
                "Proveedor": self.proveedor_combo_oc.currentText(),
                "Total comprometido": f"${float(resultado['total_general']):,.2f}",
            }
            return "Órdenes de Compra Abiertas", filtros, [1.0, 1.6, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.8]

        if self._ultimo_modo == REPORTE_CUMPLIMIENTO_PROVEEDORES:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
            }
            return "Cumplimiento de Proveedores", filtros, [2.0, 1.0, 1.0, 1.0, 1.2, 1.2]

        if self._ultimo_modo == REPORTE_DEVOLUCIONES_PROVEEDOR:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Proveedor": self.proveedor_combo_dp.currentText(),
                "Total devoluciones": str(resultado["total_devoluciones"]),
            }
            return "Devoluciones a Proveedor", filtros, [1.0, 1.6, 1.0, 1.0, 1.8, 1.0, 1.0]

        if self._ultimo_modo == REPORTE_NC_PROVEEDOR:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Proveedor": self.proveedor_combo_ncp.currentText(),
                "Total emitido": f"${float(resultado['total_general']):,.2f}",
            }
            return "Notas de Crédito de Proveedor", filtros, [0.8, 1.6, 1.2, 1.0, 1.0, 1.0, 1.0]

        if self._ultimo_modo == REPORTE_ARQUEO_CAJA:
            filtros = {
                "Caja": resultado["nombre_caja"],
                "Saldo esperado": f"${float(resultado['saldo_esperado']):,.2f}",
                "Saldo cierre": (
                    f"${float(resultado['saldo_cierre']):,.2f}"
                    if resultado["saldo_cierre"] is not None
                    else "Caja abierta"
                ),
            }
            return "Arqueo de Caja", filtros, [1.3, 1.0, 2.5, 1.2]

        if self._ultimo_modo == REPORTE_KARDEX:
            filtros = {
                "Producto": f"{resultado['cod_producto']} - {resultado['nombre_producto']}",
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Saldo inicial": f"{float(resultado['saldo_inicial']):,.2f}",
                "Saldo final": f"{float(resultado['saldo_final']):,.2f}",
            }
            return "Kardex de Producto", filtros, [1.0, 1.3, 1.5, 1.0, 1.0, 1.0]

        if self._ultimo_modo == REPORTE_VALORIZACION:
            filtros = {
                "Categoría": self.categoria_combo_valorizacion.currentText(),
                "Valor total": f"${float(resultado['total_general']):,.2f}",
            }
            return "Valorización de Inventario", filtros, [1.0, 2.0, 1.3, 1.0, 1.0, 1.2]

        if self._ultimo_modo == REPORTE_BAJO_MINIMO:
            filtros = {
                "Categoría": self.categoria_combo_bajo_minimo.currentText(),
                "Total": f"{resultado['total_productos']} productos",
            }
            return "Stock Bajo Mínimo", filtros, [1.0, 2.0, 1.3, 1.0, 1.0, 1.0]

        if self._ultimo_modo == REPORTE_SIN_MOVIMIENTO:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Total": f"{resultado['total_productos']} productos",
            }
            return "Productos sin Movimiento", filtros, [1.0, 2.0, 1.3, 1.0, 1.0, 1.2]

        if self._ultimo_modo == REPORTE_HISTORICO_PRECIOS:
            filtros = {"Producto": f"{resultado['cod_producto']} - {resultado['nombre_producto']}"}
            return "Histórico de Precios", filtros, [1.3, 1.0, 1.0, 1.5]

        if self._ultimo_modo == REPORTE_ESTADO_CTA_CLIENTE:
            filtros = {
                "Cliente": resultado["cliente"],
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y") if resultado["fecha_desde"] else "N/A",
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y") if resultado["fecha_hasta"] else "N/A",
                "Saldo inicial": f"${float(resultado['saldo_inicial']):,.2f}",
                "Saldo final": f"${float(resultado['saldo_final']):,.2f}",
            }
            return "Estado de Cuenta por Cliente", filtros, [1.0, 1.0, 1.5, 1.0, 1.0, 1.0]

        if self._ultimo_modo == REPORTE_COBROS_PERIODO:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Cliente": self.cliente_combo_cbp.currentText(),
                "Total": f"${float(resultado['total_general']):,.2f}",
            }
            return "Cobros del Período", filtros, [1.0, 1.6, 1.2, 1.0, 0.8, 1.0]

        if self._ultimo_modo == REPORTE_CLIENTES_MOROSOS:
            filtros = {
                "Corte": resultado["fecha_corte"].strftime("%d/%m/%Y"),
                "Total vencido": f"${float(resultado['total_general']):,.2f}",
            }
            return "Clientes Morosos", filtros, [2.0, 1.2, 1.2, 1.2]

        if self._ultimo_modo == REPORTE_CXC_OTRAS:
            filtros = {
                "Cliente": self.cliente_combo_cxco.currentText(),
                "Estado": self.estado_combo_cxco.currentText(),
                "Saldo pendiente": f"${float(resultado['total_general']):,.2f}",
            }
            return "CxC Otras", filtros, [1.6, 1.6, 1.0, 1.0, 1.0, 1.0, 1.0]

        if self._ultimo_modo == REPORTE_ESTADO_CTA_PROVEEDOR:
            filtros = {
                "Proveedor": resultado["proveedor"],
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y") if resultado["fecha_desde"] else "N/A",
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y") if resultado["fecha_hasta"] else "N/A",
                "Saldo inicial": f"${float(resultado['saldo_inicial']):,.2f}",
                "Saldo final": f"${float(resultado['saldo_final']):,.2f}",
            }
            return "Estado de Cuenta por Proveedor", filtros, [1.0, 1.0, 1.5, 1.0, 1.0, 1.0]

        if self._ultimo_modo == REPORTE_PAGOS_PERIODO:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Proveedor": self.proveedor_combo_pp.currentText(),
                "Total": f"${float(resultado['total_general']):,.2f}",
            }
            return "Pagos del Período", filtros, [1.0, 1.6, 1.2, 1.0, 1.0]

        if self._ultimo_modo == REPORTE_PROXIMOS_VENCIMIENTOS:
            filtros = {
                "Corte": resultado["fecha_corte"].strftime("%d/%m/%Y"),
                "Horizonte": f"{resultado['dias_horizonte']} días",
                "Total": f"${float(resultado['total_general']):,.2f}",
            }
            return "Próximos Vencimientos (CxP)", filtros, [1.2, 1.6, 1.0, 1.2, 1.2]

        if self._ultimo_modo == REPORTE_CXP_OTRAS:
            filtros = {
                "Cuenta": self.cuenta_bancaria_combo_cxpo.currentText(),
                "Estado": self.estado_combo_cxpo.currentText(),
                "Saldo pendiente": f"${float(resultado['total_general']):,.2f}",
            }
            return "CxP Otras", filtros, [1.3, 1.2, 1.6, 1.0, 1.3, 1.0, 1.0, 1.0]

        if self._ultimo_modo == REPORTE_MOV_CAJA_PERIODO:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Entradas": f"${float(resultado['total_entradas']):,.2f}",
                "Salidas": f"${float(resultado['total_salidas']):,.2f}",
                "Neto": f"${float(resultado['neto']):,.2f}",
            }
            return "Movimientos de Caja por Período", filtros, [1.2, 1.0, 0.8, 1.2, 1.8, 1.0]

        if self._ultimo_modo == REPORTE_CIERRE_CAJERO:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Turnos": str(resultado["total_turnos"]),
            }
            return (
                "Cierre Diario por Cajero",
                filtros,
                [1.0, 1.0, 1.2, 1.2, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
            )

        if self._ultimo_modo == REPORTE_FLUJO_CAJA:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Agrupación": "Día" if resultado["agrupacion"] == "dia" else "Mes",
                "Entradas": f"${float(resultado['total_entradas']):,.2f}",
                "Salidas": f"${float(resultado['total_salidas']):,.2f}",
            }
            return "Flujo de Caja Consolidado", filtros, [1.0, 1.2, 1.2, 1.2, 1.2, 1.2]

        if self._ultimo_modo == REPORTE_MOV_CUENTA_BANCARIA:
            filtros = {
                "Cuenta": resultado["numero_cuenta"] or "N/A",
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Saldo inicial": f"${float(resultado['saldo_inicial']):,.2f}",
                "Saldo final": f"${float(resultado['saldo_final']):,.2f}",
            }
            return "Movimientos por Cuenta Bancaria", filtros, [1.0, 1.0, 1.3, 1.6, 1.0, 1.0]

        if self._ultimo_modo == REPORTE_CONCILIACION_BANCARIA:
            filtros = {
                "Cuenta": self.cuenta_bancaria_combo_conc.currentText(),
                "Pendiente": f"${float(resultado['total_pendiente']):,.2f}",
                "Conciliado": f"${float(resultado['total_conciliado']):,.2f}",
            }
            return "Conciliación Bancaria", filtros, [1.6, 1.2, 1.0, 1.2, 1.0]

        if self._ultimo_modo == REPORTE_SALDO_CONSOLIDADO:
            filtros = {"Total general": f"${float(resultado['total_general']):,.2f}"}
            return "Saldo Consolidado", filtros, [1.3, 1.6, 1.0, 1.6, 1.0]

        if self._ultimo_modo == REPORTE_COMISIONES_VENDEDOR:
            filtros = {
                "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y"),
                "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y"),
                "Vendedor": self.vendedor_combo_comv.currentText(),
                "Total": f"${float(resultado['total_general']):,.2f}",
            }
            return "Comisiones por Vendedor/Período", filtros, [2.0, 1.0, 1.2]

        filtros = {
            "Desde": resultado["fecha_desde"].strftime("%d/%m/%Y") if resultado["fecha_desde"] else "N/A",
            "Hasta": resultado["fecha_hasta"].strftime("%d/%m/%Y") if resultado["fecha_hasta"] else "N/A",
            "Vendedor": self.vendedor_combo_cpp.currentText(),
            "Pagado": f"${float(resultado['total_pagado']):,.2f}",
            "Pendiente": f"${float(resultado['total_pendiente']):,.2f}",
        }
        return "Comisiones Pagadas vs. Pendientes", filtros, [2.0, 1.2, 1.2]

    def _obtener_config_empresa(self):
        session = self.session_factory()
        try:
            return EmpresaService.obtener_datos_documento(session)
        finally:
            session.close()

    def _exportar_excel(self) -> None:
        if self._ultimo_resultado is None:
            MessageBox.information(self, "Sin datos", "Generá un reporte antes de exportarlo.")
            return

        nombre_sugerido, encabezados, filas = self._filas_para_exportar()
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar reporte", f"{nombre_sugerido}.xlsx", "Excel (*.xlsx)")
        if not ruta:
            return

        try:
            titulo, _filtros, _col_widths = self._info_pdf()
            config_empresa = self._obtener_config_empresa()
            exportar_excel(ruta, encabezados, filas, titulo=titulo, config_empresa=config_empresa)
            MessageBox.information(self, "Exportación completa", f"Se exportaron {len(filas)} filas a:\n{ruta}")
        except Exception:
            logger.exception("Fallo al exportar el reporte a Excel")
            MessageBox.critical(self, "Error", "No se pudo exportar el reporte.")

    def _exportar_pdf(self) -> None:
        if self._ultimo_resultado is None:
            MessageBox.information(self, "Sin datos", "Generá un reporte antes de exportarlo.")
            return

        nombre_sugerido, encabezados, filas = self._filas_para_exportar()
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar reporte", f"{nombre_sugerido}.pdf", "PDF (*.pdf)")
        if not ruta:
            return

        try:
            titulo, filtros, col_widths = self._info_pdf()
            config_empresa = self._obtener_config_empresa()
            exportar_pdf(
                ruta, titulo, encabezados, filas, filtros=filtros, col_widths=col_widths, config_empresa=config_empresa
            )
            MessageBox.information(self, "Exportación completa", f"Se exportaron {len(filas)} filas a:\n{ruta}")
        except Exception:
            logger.exception("Fallo al exportar el reporte a PDF")
            MessageBox.critical(self, "Error", "No se pudo exportar el reporte.")
