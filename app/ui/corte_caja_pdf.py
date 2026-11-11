"""Generación del PDF de corte de caja con día, hora, observaciones, total y detalle de entradas/salidas."""

import base64
import html
from datetime import datetime

from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

from app.db.models import Caja, CajaMovimiento
from app.ui.styles import COLOR_BORDER, COLOR_PRIMARY, COLOR_TEXT_DARK, COLOR_TEXT_MUTED
from app.utils.rif import formatear_rif

_PRIMARY = COLOR_PRIMARY
_MUTED = COLOR_TEXT_MUTED
_BORDER = COLOR_BORDER
_TD = f'style="border-bottom:1pt solid {_BORDER};"'
_TD_R = f'style="border-bottom:1pt solid {_BORDER};text-align:right;"'
_TH = f'style="text-align:left;color:#FFFFFF;background-color:{_PRIMARY};"'
_TH_R = f'style="text-align:right;color:#FFFFFF;background-color:{_PRIMARY};"'
_INFO_LBL = f'style="text-align:right;color:{_MUTED};font-size:9pt;white-space:nowrap;"'
_INFO_VAL = 'style="text-align:right;font-weight:bold;font-size:9pt;"'
_MB = "margin-bottom:4pt;"
_FILA_ALTERNA = "#F1F5F9"
# El relleno de las celdas va en el atributo `cellpadding` de cada <table>, no en un `padding` CSS por celda:
# QTextDocument dejaba ese `padding` en cero y el corte salia con todo el texto pegado.


def _esc(valor) -> str:
    return html.escape(str(valor)) if valor is not None else ""


def _money(valor) -> str:
    return f"${float(valor):,.2f}"


def _logo_img_tag(logotipo: bytes | None) -> str:
    if not logotipo:
        return ""
    b64 = base64.b64encode(logotipo).decode("ascii")
    return f'<img src="data:image/png;base64,{b64}" width="70" />'


def _fila_movimiento(mov: CajaMovimiento, indice: int = 0) -> str:
    es_entrada = mov.tipo_movimiento == "entrada"
    # Fila alterna sombreada: QTextDocument no dibuja el borde inferior de una celda, y sin separacion visual las
    # filas se leian pegadas.
    fondo = f' bgcolor="{_FILA_ALTERNA}"' if indice % 2 else ""
    tipo = "Entrada" if es_entrada else "Salida"
    color = "green" if es_entrada else "red"
    return (
        f"<tr{fondo}><td {_TD}>{mov.fecha_registro.strftime('%d/%m/%Y %H:%M')}</td>"
        f"<td {_TD}><span style='color:{color};font-weight:bold;'>{tipo}</span></td>"
        f"<td {_TD}>{_esc(mov.descripcion_movimiento or '')}</td>"
        f"<td {_TD_R}>{_money(mov.monto_movimiento or 0)}</td></tr>"
    )


def _armar_html(
    caja: Caja,
    movimientos: list[CajaMovimiento],
    total_entradas: float,
    total_salidas: float,
    saldo_neto: float,
    observaciones: str | None = None,
    config_empresa=None,
) -> str:
    # Datos de la empresa
    razon_social = config_empresa.razon_social_empresa if config_empresa else "Mi Empresa"
    rif = formatear_rif(config_empresa.rif_empresa, "J") if config_empresa else ""
    direccion = config_empresa.direccion_empresa if config_empresa else ""
    telefono = config_empresa.telefono_empresa if config_empresa else ""
    logo_tag = _logo_img_tag(config_empresa.logotipo_empresa if config_empresa else None)

    # Datos del corte
    fecha_corte = datetime.now()
    cajero = caja.usuario.nombre_usuario if caja.usuario else "—"
    fecha_apertura = caja.fecha_apertura.strftime("%d/%m/%Y %H:%M") if caja.fecha_apertura else "—"
    fecha_cierre = (
        caja.fecha_cierre.strftime("%d/%m/%Y %H:%M") if caja.fecha_cierre else fecha_corte.strftime("%d/%m/%Y %H:%M")
    )

    # Filas de movimientos
    filas_movimientos = "".join(_fila_movimiento(mov, i) for i, mov in enumerate(movimientos))

    # Observaciones
    observaciones_html = ""
    if observaciones:
        observaciones_html = f"<br/><p style='color:{_MUTED};'><b>Observaciones:</b> {_esc(observaciones)}</p>"

    encabezado_empresa = (
        f'<div style="font-size:13pt;font-weight:bold;color:{_PRIMARY};{_MB}">'
        f"{_esc(razon_social)}</div>"
        f'<div style="color:{_MUTED};font-size:9pt;{_MB}">{_esc(rif)}</div>'
        f'<div style="color:{_MUTED};font-size:9pt;{_MB}">{_esc(direccion)}</div>'
        f'<div style="color:{_MUTED};font-size:9pt;{_MB}">{_esc(telefono)}</div>'
    )

    # Filas de información de caja
    caja_info_rows = (
        f"<tr><td {_INFO_LBL}>Caja:</td><td {_INFO_VAL}>{_esc(caja.nombre_caja or f'Caja {caja.id_caja}')}</td></tr>"
        f"<tr><td {_INFO_LBL}>Cajero:</td><td {_INFO_VAL}>{_esc(cajero)}</td></tr>"
        f"<tr><td {_INFO_LBL}>Fecha Apertura:</td><td {_INFO_VAL}>{fecha_apertura}</td></tr>"
        f"<tr><td {_INFO_LBL}>Fecha Cierre:</td><td {_INFO_VAL}>{fecha_cierre}</td></tr>"
    )

    # Filas de totales
    totales_rows = (
        f"<tr><td {_INFO_LBL}>Total Entradas:</td><td {_INFO_VAL}>{_money(total_entradas)}</td></tr>"
        f"<tr><td {_INFO_LBL}>Total Salidas:</td><td {_INFO_VAL}>-{_money(total_salidas)}</td></tr>"
    )

    # Fila de saldo neto
    saldo_neto_row = (
        f'<tr><td style="text-align:right;font-weight:bold;border-top:2pt solid {_PRIMARY};">'
        f"Saldo Neto:</td>"
        f'<td style="text-align:right;font-weight:bold;font-size:14pt;color:{_PRIMARY};'
        f'border-top:2pt solid {_PRIMARY};">{_money(saldo_neto)}</td></tr>'
    )

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
                <table width="100%" cellpadding="3" cellspacing="0">
                    <tr><td colspan="2" style="background-color:{_PRIMARY};color:#FFFFFF;text-align:center;
                        font-size:12pt;font-weight:bold;">CORTE DE CAJA</td></tr>
                    {caja_info_rows}
                </table>
            </td>
        </tr></table>

        <br/>
        <table width="100%" cellpadding="6" cellspacing="0">
            <tr>
                <th {_TH}>Fecha</th>
                <th {_TH}>Tipo</th>
                <th {_TH}>Descripción</th>
                <th {_TH_R}>Monto</th>
            </tr>
            {filas_movimientos}
        </table>

        <br/>
        <table width="100%" cellpadding="4" cellspacing="0">
            {totales_rows}
            {saldo_neto_row}
        </table>

        {observaciones_html}
    </body></html>
    """


def _documento(
    caja: Caja,
    movimientos: list[CajaMovimiento],
    total_entradas: float,
    total_salidas: float,
    saldo_neto: float,
    observaciones: str | None = None,
    config_empresa=None,
) -> QTextDocument:
    documento = QTextDocument()
    documento.setHtml(
        _armar_html(
            caja,
            movimientos,
            total_entradas,
            total_salidas,
            saldo_neto,
            observaciones,
            config_empresa,
        )
    )
    return documento


def _configurar_pagina(impresora: QPrinter) -> None:
    impresora.setPageSize(QPageSize(QPageSize.PageSizeId.Letter))
    impresora.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)


def generar_pdf_corte_caja(
    caja: Caja,
    movimientos: list[CajaMovimiento],
    total_entradas: float,
    total_salidas: float,
    saldo_neto: float,
    observaciones: str | None = None,
    config_empresa=None,
    ruta_destino: str = None,
) -> None:
    """Genera el PDF del corte de caja."""
    if ruta_destino:
        impresora = QPrinter(QPrinter.PrinterMode.HighResolution)
        impresora.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        impresora.setOutputFileName(ruta_destino)
        _configurar_pagina(impresora)
        _documento(
            caja,
            movimientos,
            total_entradas,
            total_salidas,
            saldo_neto,
            observaciones,
            config_empresa,
        ).print_(impresora)


def imprimir_corte_caja(
    caja: Caja,
    movimientos: list[CajaMovimiento],
    total_entradas: float,
    total_salidas: float,
    saldo_neto: float,
    observaciones: str | None = None,
    config_empresa=None,
    nombre_impresora: str = None,
) -> None:
    """Imprime el corte de caja directamente a una impresora."""
    if nombre_impresora:
        info = QPrinterInfo.printerInfo(nombre_impresora)
        if info.isNull():
            raise ValueError(f"La impresora configurada '{nombre_impresora}' ya no está disponible en este equipo.")
        impresora = QPrinter(info, QPrinter.PrinterMode.HighResolution)
    else:
        impresora = QPrinter(QPrinter.PrinterMode.HighResolution)

    _configurar_pagina(impresora)
    _documento(
        caja,
        movimientos,
        total_entradas,
        total_salidas,
        saldo_neto,
        observaciones,
        config_empresa,
    ).print_(impresora)
