"""Generacion de la factura digital en PDF (punto 1 del pedido de facturacion: no hay
impresora fiscal, es un documento digital con los datos de la empresa).

Vive en app/ui/ y no en app/services/ a proposito: usa QTextDocument/QPrinter
(PySide6.QtPrintSupport), que son clases de Qt -- meterlas en la capa de servicios
rompería la separacion servicios (framework-agnostico) / UI (PySide6) que sigue el resto
del proyecto (ver CLAUDE.md). No agrega ninguna dependencia nueva: QtPrintSupport ya
viene incluido en el PySide6 instalado.

`datos` es el dict que devuelve VentaService.obtener_factura() ({"factura":
FacturaVenta, "detalles": [FacturaDetalle, ...]}); `config_empresa` el que devuelve
EmpresaService.obtener_configuracion() (puede ser None si nunca se configuro)."""

import base64
import html

from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

from app.db.models import ConfiguracionEmpresa, FacturaDetalle, FacturaVenta
from app.ui.pago_linea_dialog import METODOS_PAGO
from app.ui.styles import COLOR_BORDER, COLOR_DANGER, COLOR_PRIMARY, COLOR_TEXT_DARK, COLOR_TEXT_MUTED

# Etiquetas de metodo de pago (venta) -- "mixto" es el sentinel que VentaService.
# obtener_factura() usa cuando hubo mas de una forma de pago con metodo distinto (ver
# tambien factura_detalle_dialog.py/facturacion_panel.py, mismo criterio). Metodo de
# VUELTO es un catalogo aparte (efectivo/pago_movil/transferencia, ver METODOS_VUELTO en
# factura_form_dialog.py) -- duplicado aca a proposito, 3 valores fijos.
_ETIQUETAS_METODO_PAGO = {valor: etiqueta for etiqueta, valor in METODOS_PAGO} | {"mixto": "Mixto"}
_ETIQUETAS_METODO_VUELTO = {
    "efectivo": "Efectivo",
    "pago_movil": "Pago Móvil",
    "transferencia": "Transferencia",
}

_PRIMARY = COLOR_PRIMARY
_MUTED = COLOR_TEXT_MUTED
_BORDER = COLOR_BORDER
_TD = f'style="padding:5pt 6pt;border-bottom:1pt solid {_BORDER};"'
_TD_R = f'style="padding:5pt 6pt;border-bottom:1pt solid {_BORDER};text-align:right;"'
_TH = f'style="padding:5pt 6pt;text-align:left;color:#FFFFFF;background-color:{_PRIMARY};"'
_TH_R = f'style="padding:5pt 6pt;text-align:right;color:#FFFFFF;background-color:{_PRIMARY};"'
_INFO_LBL = f'style="padding:3pt 6pt;text-align:right;color:{_MUTED};font-size:9pt;white-space:nowrap;"'
_INFO_VAL = 'style="padding:3pt 6pt;text-align:right;font-weight:bold;font-size:9pt;"'
_MB = "margin-bottom:4pt;"


def _esc(valor) -> str:
    return html.escape(str(valor)) if valor is not None else ""


def _money(valor) -> str:
    return f"${float(valor):,.2f}"


def _money_bs(valor) -> str:
    # Convencion venezolana: "." para miles, "," para decimales (ej. 18.877,36).
    return f"{float(valor):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _logo_img_tag(logotipo: bytes | None) -> str:
    if not logotipo:
        return ""
    b64 = base64.b64encode(logotipo).decode("ascii")
    return f'<img src="data:image/png;base64,{b64}" width="70" />'


def _fila_item(detalle: FacturaDetalle) -> str:
    producto = detalle.producto
    codigo = producto.cod_producto if producto else ""
    nombre = producto.nombre_producto if producto else "Producto eliminado"
    cantidad = float(detalle.cantidad_producto)
    precio = float(detalle.precio_unitario)
    subtotal = cantidad * precio
    nota = ""
    if detalle.observaciones_item:
        nota = f"<br/><span style='color:{_MUTED};font-size:8.5pt;'>{_esc(detalle.observaciones_item)}</span>"
    return (
        f"<tr><td {_TD}>{_esc(codigo)}</td>"
        f"<td {_TD}>{_esc(nombre)}{nota}</td>"
        f"<td {_TD_R}>{cantidad:,.2f}</td>"
        f"<td {_TD_R}>{_money(precio)}</td>"
        f"<td {_TD_R}>{_money(subtotal)}</td></tr>"
    )


def _filas_totales(factura: FacturaVenta) -> tuple[str, float]:
    subtotal = float(factura.total_venta)
    # padding:7pt (antes 3pt) -- con solo el margin-top de la tabla contenedora (ver
    # _bloque_totales_html) el bloque de totales quedaba pegado visualmente contra la
    # ultima fila de items: QTextDocument (el motor HTML/CSS de Qt, no un navegador
    # real) respeta el margin-top de una <table> de forma inconsistente/insuficiente
    # cuando sigue inmediatamente a otra tabla, asi que el espacio real hay que
    # garantizarlo tambien con padding dentro de la propia fila.
    td_lbl = f'style="padding:7pt 6pt;text-align:right;color:{_MUTED};"'
    td_val = 'style="padding:7pt 6pt;text-align:right;width:120pt;"'
    filas = f"<tr><td {td_lbl}>Subtotal:</td><td {td_val}>{_money(subtotal)}</td></tr>"

    descuento = float(factura.monto_descuento or 0)
    if descuento > 0:
        filas += f"<tr><td {td_lbl}>Descuento:</td><td {td_val}>-{_money(descuento)}</td></tr>"

    monto_iva = float(factura.monto_iva or 0)
    if factura.iva_aplicado:
        pct = factura.porcentaje_iva_aplicado
        filas += f"<tr><td {td_lbl}>IVA ({pct:g}%):</td><td {td_val}>{_money(monto_iva)}</td></tr>"

    total = subtotal - descuento + monto_iva
    td_lbl_total = f'style="padding:8pt 6pt;text-align:right;font-weight:bold;border-top:2pt solid {_PRIMARY};"'
    td_val_total = (
        f'style="padding:8pt 6pt 8pt 16pt;text-align:right;font-weight:bold;font-size:14pt;'
        f'color:{_PRIMARY};border-top:2pt solid {_PRIMARY};"'
    )
    filas += f"<tr><td {td_lbl_total}>Total a pagar:</td><td {td_val_total}>{_money(total)}</td></tr>"
    return filas, total


def _bloque_bolivares_html(tasa, total_usd: float) -> str:
    """Equivalente en bolivares del total, solo informativo (la factura y sus totales
    quedan siempre en USD -- ver docs/ESTADO_DEL_PROYECTO.md). No incluye IGTF: esa
    retencion no esta modelada en el sistema (ni FacturaVenta ni ConfiguracionEmpresa
    tienen un campo para ella) y no hay que inventarsela en un documento que se le
    entrega al cliente.

    Ancho 100% a proposito: el llamador la mete dentro de la misma columna fija que
    _filas_totales (ver _bloque_totales_html) en vez de auto-alinearse con
    align="right" -- eso fue lo que causaba que el monto se viera corrido del margen
    derecho de la pagina."""
    if tasa is None:
        return ""
    fecha_tasa = tasa.fecha_tasa.strftime("%d/%m/%Y")
    total_bs = total_usd * float(tasa.tasa_dolar_bcv)
    return f"""
    <table width="100%" style="border-collapse:collapse;margin-top:6pt;border:1pt solid {_PRIMARY};">
        <tr><td style="padding:4pt 8pt;color:{_MUTED};font-size:8.5pt;">
            Tasa BCV: {float(tasa.tasa_dolar_bcv):,.2f} Bs/USD ({fecha_tasa})
        </td></tr>
        <tr><td style="padding:5pt 8pt;background-color:{_PRIMARY};color:#FFFFFF;font-weight:bold;text-align:right;">
            Total Bs. {_money_bs(total_bs)}
        </td></tr>
    </table>
    """


def _bloque_totales_html(filas_totales: str, bloque_bs: str) -> str:
    """Envuelve totales + equivalente en Bs en una columna de ancho fijo dentro de una
    tabla al 100% del ancho de pagina -- el borde derecho de esa columna cae exacto
    sobre el margen derecho de la pagina, igual que el resto de las barras del
    documento (CLIENTE, tabla de items, pie de pagina). El truco anterior
    (`<table align="right">` envolviendo el contenido con ancho auto-ajustado) es lo
    que hacia que el monto se viera corrido/fuera del margen."""
    return f"""
    <table width="100%" style="border-collapse:collapse;margin-top:8pt;"><tr>
        <td></td>
        <td width="240" style="vertical-align:top;">
            <table width="100%" style="border-collapse:collapse;">
                {filas_totales}
            </table>
            {bloque_bs}
        </td>
    </tr></table>
    """


def _armar_html(datos: dict, config_empresa: ConfiguracionEmpresa | None) -> str:
    factura: FacturaVenta = datos["factura"]
    detalles: list[FacturaDetalle] = datos["detalles"]
    cliente = factura.cliente
    vendedor = factura.vendedor
    tasa = factura.tasa

    razon_social = config_empresa.razon_social_empresa if config_empresa else None
    rif = config_empresa.rif_empresa if config_empresa else None
    direccion = config_empresa.direccion_empresa if config_empresa else None
    telefono = config_empresa.telefono_empresa if config_empresa else None
    pie_pagina = config_empresa.pie_pagina_empresa if config_empresa else None
    logo_tag = _logo_img_tag(config_empresa.logotipo_empresa if config_empresa else None)

    condicion = "Contado" if factura.condicion_pago == "contado" else "Crédito"
    fecha = factura.fecha_emision.strftime("%d/%m/%Y") if factura.fecha_emision else ""
    hora = factura.fecha_emision.strftime("%I:%M %p") if factura.fecha_emision else ""
    vencimiento_row = ""
    if factura.condicion_pago == "credito" and factura.fecha_vencimiento:
        vencimiento = factura.fecha_vencimiento.strftime("%d/%m/%Y")
        vencimiento_row = f"<tr><td {_INFO_LBL}>Fecha de Vencimiento:</td><td {_INFO_VAL}>{vencimiento}</td></tr>"

    # Metodo de pago solo aplica a contado. Antes no se imprimia en absoluto (hallazgo de
    # la auditoria de facturacion: el dato ya llegaba en `datos["metodo_pago"]` pero
    # _armar_html() nunca lo usaba).
    metodo_pago_row = ""
    if factura.condicion_pago == "contado":
        metodo_pago = datos.get("metodo_pago")
        etiqueta_metodo_pago = _ETIQUETAS_METODO_PAGO.get(metodo_pago, metodo_pago or "—")
        metodo_pago_row = (
            f"<tr><td {_INFO_LBL}>Método de Pago:</td><td {_INFO_VAL}>{_esc(etiqueta_metodo_pago)}</td></tr>"
        )

    # Vuelto (cambio) entregado -- solo monto+metodo, igual criterio que el motivo/
    # autorizador de descuento (ver comentario mas abajo): la referencia bancaria y quien
    # autorizo son informacion de auditoria interna, no pertenecen al documento del
    # cliente.
    vuelto_row = ""
    if factura.monto_vuelto and float(factura.monto_vuelto) > 0:
        etiqueta_metodo_vuelto = _ETIQUETAS_METODO_VUELTO.get(factura.metodo_vuelto, factura.metodo_vuelto)
        vuelto_row = (
            f"<tr><td {_INFO_LBL}>Vuelto Entregado:</td>"
            f"<td {_INFO_VAL}>{_money(float(factura.monto_vuelto))} ({_esc(etiqueta_metodo_vuelto)})</td></tr>"
        )

    filas_items = "".join(_fila_item(det) for det in detalles)
    filas_totales, total_usd = _filas_totales(factura)
    bloque_bs = _bloque_bolivares_html(tasa, total_usd)
    bloque_totales = _bloque_totales_html(filas_totales, bloque_bs)

    # El motivo/autorizador del descuento es informacion de auditoria interna (quien
    # autorizo, por que) -- se sigue registrando en FacturaVenta.motivo_descuento /
    # autorizado_por_descuento y en AuditoriaService (ver VentaService.emitir_factura),
    # pero no pertenece al documento que recibe el cliente.

    watermark = ""
    if factura.estado_factura == "ANULADA":
        watermark = f"<p style='color:{COLOR_DANGER};font-weight:bold;font-size:13pt;'>*** FACTURA ANULADA ***</p>"

    observaciones_html = ""
    if factura.observaciones_factura:
        observaciones_html = (
            f"<p style='color:{_MUTED};'><b>Observaciones:</b> {_esc(factura.observaciones_factura)}</p>"
        )

    pie_html = ""
    if pie_pagina:
        pie_html = (
            f'<table width="100%" style="border-collapse:collapse;margin-top:10pt;"><tr>'
            f'<td style="background-color:{_PRIMARY};color:#FFFFFF;text-align:center;padding:6pt;font-size:9pt;">'
            f"{_esc(pie_pagina)}</td></tr></table>"
        )

    encabezado_empresa = (
        f'<div style="font-size:13pt;font-weight:bold;color:{_PRIMARY};{_MB}">'
        f"{_esc(razon_social) or 'Mi Empresa'}</div>"
        f'<div style="color:{_MUTED};font-size:9pt;{_MB}">{_esc(rif) or ""}</div>'
        f'<div style="color:{_MUTED};font-size:9pt;{_MB}">{_esc(direccion) or ""}</div>'
        f'<div style="color:{_MUTED};font-size:9pt;{_MB}">{_esc(telefono) or ""}</div>'
    )

    codigo_cliente = (cliente.codigo_cliente if cliente else None) or (f"{cliente.id_cliente:06d}" if cliente else "—")
    nombre_cliente = cliente.nombre_razon_social if cliente else "—"
    if cliente and cliente.id_legal and cliente.identificacion_cliente:
        identificacion_cliente = f"{cliente.id_legal}-{cliente.identificacion_cliente}"
    else:
        identificacion_cliente = cliente.id_legal or cliente.identificacion_cliente if cliente else "—"
    telefono_cliente = (cliente.telefono if cliente else None) or "—"
    email_cliente = (cliente.email if cliente else None) or "—"
    direccion_cliente = (cliente.direccion if cliente else None) or "—"

    return f"""
    <html><body style="font-family: Arial, sans-serif; color:{COLOR_TEXT_DARK}; font-size:10pt;">
        <table width="100%" style="border-collapse:collapse;"><tr>
            <td width="62%" style="vertical-align:top;">
                <table style="border-collapse:collapse;"><tr>
                    <td width="76" style="vertical-align:top;">{logo_tag}</td>
                    <td style="vertical-align:top;">{encabezado_empresa}</td>
                </tr></table>
            </td>
            <td width="38%" style="vertical-align:top;">
                <table width="100%" style="border-collapse:collapse;border:1pt solid {_BORDER};">
                    <tr><td colspan="2" style="background-color:{_PRIMARY};color:#FFFFFF;text-align:center;
                        font-size:12pt;font-weight:bold;padding:5pt;">FACTURA</td></tr>
                    <tr><td {_INFO_LBL}>N° de Factura:</td><td {_INFO_VAL}>{_esc(factura.numero_factura)}</td></tr>
                    <tr><td {_INFO_LBL}>Fecha de Emisión:</td><td {_INFO_VAL}>{fecha}</td></tr>
                    <tr><td {_INFO_LBL}>Hora de Emisión:</td><td {_INFO_VAL}>{hora}</td></tr>
                    <tr><td {_INFO_LBL}>N° de Control:</td><td {_INFO_VAL}>{_esc(factura.numero_control)}</td></tr>
                    <tr><td {_INFO_LBL}>Condición de Pago:</td><td {_INFO_VAL}>{condicion}</td></tr>
                    {metodo_pago_row}
                    {vencimiento_row}
                    <tr><td {_INFO_LBL}>Moneda:</td><td {_INFO_VAL}>$ (USD)</td></tr>
                    {vuelto_row}
                </table>
            </td>
        </tr></table>

        {watermark}

        <table width="100%" style="border-collapse:collapse;margin-top:10pt;"><tr>
            <td style="background-color:{_PRIMARY};color:#FFFFFF;padding:5pt 8pt;font-size:10pt;font-weight:bold;">
                CLIENTE N° {_esc(codigo_cliente)}
            </td>
        </tr></table>
        <table width="100%" style="border-collapse:collapse;border:1pt solid {_BORDER};border-top:none;"><tr>
            <td width="58%" style="padding:10pt;vertical-align:top;">
                <div style="{_MB}"><b>Cliente:</b> {_esc(nombre_cliente)}</div>
                <div style="{_MB}"><b>RIF / C.I.:</b> {_esc(identificacion_cliente)}</div>
                <div style="{_MB}"><b>Teléfono:</b> {_esc(telefono_cliente)}</div>
                <div style="{_MB}"><b>Email:</b> {_esc(email_cliente)}</div>
                <div><b>Vendedor:</b> {_esc(vendedor.nombre_vendedor) if vendedor else "—"}</div>
            </td>
            <td width="42%" style="padding:10pt;vertical-align:top;border-left:1pt solid {_BORDER};">
                <div><b>Dirección:</b> {_esc(direccion_cliente)}</div>
            </td>
        </tr></table>

        <table width="100%" style="border-collapse:collapse;margin-top:10pt;">
            <tr>
                <th {_TH}>Código</th>
                <th {_TH}>Producto</th>
                <th {_TH_R}>Cantidad</th>
                <th {_TH_R}>Precio Unit.</th>
                <th {_TH_R}>Subtotal</th>
            </tr>
            {filas_items}
        </table>
        <p style="margin:10pt 0 0 0;line-height:1pt;font-size:1pt;">&nbsp;</p>
        {bloque_totales}
        <div style="clear:both;"></div>
        {observaciones_html}
        {pie_html}
    </body></html>
    """


def _documento(datos: dict, config_empresa: ConfiguracionEmpresa | None) -> QTextDocument:
    documento = QTextDocument()
    documento.setHtml(_armar_html(datos, config_empresa))
    return documento


def _configurar_pagina(impresora: QPrinter) -> None:
    impresora.setPageSize(QPageSize(QPageSize.PageSizeId.Letter))
    impresora.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)


def generar_pdf_factura(datos: dict, config_empresa: ConfiguracionEmpresa | None, ruta_destino: str) -> None:
    """Escribe la factura como PDF directo en ruta_destino (elegida por el caller, ver
    patron ya usado en exportar_excel/app/services/exportacion.py -- se pide el destino
    ANTES de generar, se escribe directo ahi)."""
    impresora = QPrinter(QPrinter.PrinterMode.HighResolution)
    impresora.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    impresora.setOutputFileName(ruta_destino)
    _configurar_pagina(impresora)

    _documento(datos, config_empresa).print_(impresora)


def imprimir_factura(datos: dict, config_empresa: ConfiguracionEmpresa | None, nombre_impresora: str) -> None:
    """Envia la factura digital directo a una impresora instalada en el sistema (por
    nombre, via QPrinterInfo) en vez de guardarla en un archivo -- usada para el
    auto-print al emitir factura (ver FacturacionPanel.nueva_factura). Si el usuario
    configuro "Microsoft Print to PDF" (u otra impresora virtual) como impresora
    predeterminada, esto cubre tambien el caso de "guardar" automaticamente sin
    necesitar una ruta separada -- es la misma llamada a QPrinter.

    Lanza ValueError si `nombre_impresora` ya no corresponde a ninguna impresora
    instalada (se desconecto, se reinstalo con otro nombre, etc.) -- el caller decide
    como mostrarselo al usuario sin que esto tumbe la emision de la factura, que ya
    quedo commiteada en la base antes de llegar aca."""
    info = QPrinterInfo.printerInfo(nombre_impresora)
    if info.isNull():
        raise ValueError(f"La impresora configurada '{nombre_impresora}' ya no está disponible en este equipo.")

    impresora = QPrinter(info, QPrinter.PrinterMode.HighResolution)
    _configurar_pagina(impresora)

    _documento(datos, config_empresa).print_(impresora)
