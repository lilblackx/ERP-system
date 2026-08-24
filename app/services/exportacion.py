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
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
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
) -> None:
    """Exporta datos a un archivo PDF con formato de tabla."""
    doc = SimpleDocTemplate(str(ruta), pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=18)
    
    elements = []
    styles = getSampleStyleSheet()
    
    # Título del reporte
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=18,
        textColor=colors.HexColor("#0D47A1"),
        spaceAfter=12,
    )
    elements.append(Paragraph(titulo, title_style))
    
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
    table_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0D47A1")),  # Header azul
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
        ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
        ("GRID", (0, 0), (-1, -1), 1, colors.grey),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
    ])
    
    # Alternar colores de filas
    for i in range(1, len(data)):
        if i % 2 == 0:
            table_style.add("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F8FAFC"))
        else:
            table_style.add("BACKGROUND", (0, i), (-1, i), colors.white)
    
    table = Table(
        data,
        colWidths=[
            1.2 * inch,
            1.2 * inch,
            1.2 * inch,
            1.0 * inch,
            1.0 * inch,
            1.0 * inch,
            0.8 * inch,
            1.5 * inch,
            1.0 * inch,
            1.0 * inch,
        ],
    )
    table.setStyle(table_style)
    elements.append(table)
    
    doc.build(elements)
    logger.info("PDF exportado: %s", ruta)
