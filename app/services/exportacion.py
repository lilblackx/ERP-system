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
