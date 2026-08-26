"""R-02 (docs/CHECKLIST_PRODUCCION.md): exportacion de reportes/listados a Excel.

Escritor generico (encabezados + filas) reutilizado por el motor de reportes
(app/services/reportes.py) y por listados de catalogo con boton "Exportar" (ej.
app/ui/clientes_panel.py, R-10).

R-09: la ruta de destino la elige el caller (tipicamente via
QFileDialog.getSaveFileName() en la UI) ANTES de llamar a esta funcion -- se escribe
directo ahi, nunca a un archivo temporal, asi que no hace falta purgar nada al cerrar
la app.

No usa `write_only=True` (streaming): eso es para datasets grandes que no caben comodos
en memoria (kardex completo, facturas del año -- ver R-04, pendiente hasta que exista un
reporte de ese tamaño). Los listados actuales (aging de CxC, catalogo de clientes) son
acotados.
"""

import logging
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

logger = logging.getLogger(__name__)


def exportar_excel(ruta: str | Path, encabezados: Sequence[str], filas: Iterable[Sequence[Any]]) -> None:
    """Escribe una unica hoja (encabezados + filas) a un archivo .xlsx en `ruta`."""
    libro = Workbook()
    hoja = libro.active
    hoja.append(list(encabezados))
    cantidad_filas = 0
    for fila in filas:
        hoja.append(list(fila))
        cantidad_filas += 1
    libro.save(ruta)
    logger.info("Excel exportado: %s (%d filas)", ruta, cantidad_filas)


def exportar_pdf(
    ruta: str | Path,
    titulo: str,
    encabezados: Sequence[str],
    filas: Iterable[Sequence[Any]],
    cliente_nombre: str | None = None,
    filtros: dict[str, Any] | None = None,
    col_widths: Sequence[float] | None = None,
) -> None:
    """Exporta datos a un archivo PDF con formato de tabla.

    Args:
        ruta: Ruta del archivo PDF a generar.
        titulo: Título principal del reporte.
        encabezados: Lista de nombres de columnas.
        filas: Filas de datos a exportar.
        cliente_nombre: Nombre del cliente (opcional, para reportes específicos).
        filtros: Diccionario con los filtros aplicados (opcional).
        col_widths: Anchos específicos para cada columna (opcional).
    """
    margen_horizontal = 30
    doc = SimpleDocTemplate(
        str(ruta),
        pagesize=letter,
        rightMargin=margen_horizontal,
        leftMargin=margen_horizontal,
        topMargin=30,
        bottomMargin=18,
    )

    elements = []
    styles = getSampleStyleSheet()

    # Título del reporte con fecha y hora
    fecha_hora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    titulo_completo = f"{titulo} - {fecha_hora}"
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=16,
        textColor=colors.HexColor("#0D47A1"),
        spaceAfter=12,
    )
    elements.append(Paragraph(titulo_completo, title_style))

    # Información de filtros aplicados
    if filtros:
        filtro_parts = []
        for key, value in filtros.items():
            if value:
                filtro_parts.append(f"{key}: {value}")
        if filtro_parts:
            filtro_texto = " | ".join(filtro_parts)
            filtro_style = ParagraphStyle(
                "Filtros",
                parent=styles["Normal"],
                fontSize=10,
                textColor=colors.HexColor("#64748B"),
                spaceAfter=12,
            )
            elements.append(Paragraph(f"Filtros: {filtro_texto}", filtro_style))

    # Nombre del cliente si se proporciona
    if cliente_nombre:
        cliente_style = ParagraphStyle(
            "Cliente",
            parent=styles["Normal"],
            fontSize=12,
            textColor=colors.HexColor("#64748B"),
            spaceAfter=12,
        )
        elements.append(Paragraph(f"Cliente: {cliente_nombre}", cliente_style))

    # Datos de la tabla
    data = [list(encabezados)]
    for fila in filas:
        data.append(list(fila))

    # Estilo de la tabla
    table_style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0D47A1")),  # Header azul
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("TOPPADDING", (0, 0), (-1, 0), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("WORDWRAP", (0, 0), (-1, -1), "CJK"),  # Permite mejor ajuste de texto largo
        ]
    )

    # Alternar colores de filas
    for i in range(1, len(data)):
        if i % 2 == 0:
            table_style.add("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F8FAFC"))
        else:
            table_style.add("BACKGROUND", (0, i), (-1, i), colors.white)

    # Ancho de columnas: usar anchos específicos si se proporcionan,
    # de lo contrario repartir equitativamente
    ancho_disponible = letter[0] - 2 * margen_horizontal
    if col_widths:
        # Normalizar anchos para que sumen el ancho disponible
        total_ancho = sum(col_widths)
        col_widths_normalizados = [w * ancho_disponible / total_ancho for w in col_widths]
        table = Table(data, colWidths=col_widths_normalizados)
    else:
        ancho_columna = ancho_disponible / len(encabezados)
        table = Table(data, colWidths=[ancho_columna] * len(encabezados))
    table.setStyle(table_style)
    elements.append(table)

    doc.build(elements)
    logger.info("PDF exportado: %s", ruta)
