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
import math
import re
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.db.models import ConfiguracionEmpresa
from app.utils.rif import formatear_rif

logger = logging.getLogger(__name__)

_COLOR_PRIMARIO = colors.HexColor("#12459B")
_COLOR_MUTED = colors.HexColor("#64748B")

# Excel/LibreOffice interpretan como formula un TEXTO que empieza con estos caracteres cuando se
# edita la celda o se abre un CSV (CSV/Formula Injection, OWASP). En un .xlsx las celdas de texto se
# guardan como texto y no se evaluan, asi que NO hace falta alterar el valor: antes se le anteponia un
# apostrofe literal, y eso corrompia los datos (un "-100.00" salia como "'-100.00", un telefono
# "+58414..." como "'+58414..."). Ahora el valor se guarda intacto, forzado a texto y con la marca
# "quotePrefix" de Excel (el apostrofe invisible), para que tampoco se evalue si el usuario edita la celda.
_PREFIJOS_FORMULA = ("=", "+", "-", "@")

# Dos decimales como minimo y hasta cuatro si el dato los tiene (costos/cantidades), con separador de
# miles; los negativos salen con "-". Solo cambia como SE VE el numero: el valor guardado no se redondea.
_FORMATO_NUMERO_EXCEL = "#,##0.00##"
_FORMATO_FECHA_EXCEL = "dd/mm/yyyy"
_FORMATO_FECHA_HORA_EXCEL = "dd/mm/yyyy hh:mm"

# Montos tal como los muestra la interfaz ("$1,234.50", "$-5.00", "-$5.00", "1,234.50"): solo se
# reconocen formatos estrictos, para no convertir por error un codigo o un numero de factura.
_PATRON_MONTO_TEXTO = re.compile(r"^(?P<neg>-)?\$?(?P<neg2>-)?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+)$")
_PATRON_MONTO_CON_SIMBOLO = re.compile(r"^-?\$-?\d+(?:,\d{3})*(?:\.\d+)?$|^-?\$-?\d+$")


def valor_para_exportar(valor: Any) -> Any:
    """Convierte a `Decimal` un texto que es claramente un monto de la interfaz ("$1,234.50", "$-5.00",
    "-$5.00", "1,234.50", "-5.00") para que Excel lo reciba como numero (sumable, con su signo) y no como
    texto. Todo lo demas (codigos, fechas, textos, numeros de factura como "FV-000123", porcentajes) se
    devuelve igual."""
    if not isinstance(valor, str):
        return valor
    texto = valor.strip()
    if not texto:
        return valor
    if not (_PATRON_MONTO_CON_SIMBOLO.match(texto) or _PATRON_MONTO_TEXTO.match(texto)):
        return valor
    negativo = texto.startswith("-") or "$-" in texto
    limpio = texto.replace("$", "").replace(",", "").lstrip("-")
    try:
        numero = Decimal(limpio)
    except Exception:
        return valor
    return -numero if negativo else numero


def _poner_valor_excel(celda, valor: Any) -> None:
    """Escribe `valor` en la celda conservando su tipo: numeros como numeros (con su signo y formato),
    fechas como fechas y texto como texto literal, sin modificarlo."""
    if valor is None or isinstance(valor, bool):
        celda.value = valor
    elif isinstance(valor, (int,)):
        celda.value = valor
    elif isinstance(valor, (float, Decimal)):
        if isinstance(valor, float) and not math.isfinite(valor):
            celda.value = None
            return
        celda.value = valor + 0 if isinstance(valor, float) else valor  # -0.0 -> 0.0
        celda.number_format = _FORMATO_NUMERO_EXCEL
    elif isinstance(valor, datetime):
        celda.value = valor.replace(tzinfo=None)
        celda.number_format = _FORMATO_FECHA_HORA_EXCEL
    elif isinstance(valor, date):
        celda.value = valor
        celda.number_format = _FORMATO_FECHA_EXCEL
    else:
        texto = ILLEGAL_CHARACTERS_RE.sub("", str(valor))
        celda.value = texto
        if texto.startswith(_PREFIJOS_FORMULA):
            celda.data_type = "s"  # texto literal: nunca una formula (openpyxl marca "=..." como formula)
            celda.quotePrefix = True


def _ajustar_anchos_excel(hoja) -> None:
    """Ancho de cada columna segun su contenido (con tope), para que no haya que ensancharlas a mano. Las
    celdas combinadas (el titulo) no cuentan: son mas anchas que la tabla y ensancharian la primera columna."""
    combinadas = {
        celda.coordinate for rango in hoja.merged_cells.ranges for fila in hoja[rango.coord] for celda in fila
    }
    anchos: dict[int, int] = {}
    for fila in hoja.iter_rows():
        for celda in fila:
            if celda.value is None or celda.coordinate in combinadas:
                continue
            if isinstance(celda.value, (int, float, Decimal)):
                largo = len(f"{celda.value:,.2f}") + 1
            elif isinstance(celda.value, (date, datetime)):
                largo = 16
            else:
                largo = max((len(linea) for linea in str(celda.value).splitlines()), default=0)
            anchos[celda.column] = max(anchos.get(celda.column, 0), largo)
    for columna, largo in anchos.items():
        hoja.column_dimensions[get_column_letter(columna)].width = min(max(largo + 2, 10), 50)


def exportar_excel(
    ruta: str | Path,
    encabezados: Sequence[str],
    filas: Iterable[Sequence[Any]],
    titulo: str | None = None,
    config_empresa: ConfiguracionEmpresa | None = None,
    total_row: Sequence[Any] | None = None,
    total_label: str | None = None,
    filtros: dict[str, Any] | None = None,
    secciones: Sequence[dict[str, Any]] | None = None,
) -> None:
    """Escribe una unica hoja (encabezados + filas) a un archivo .xlsx en `ruta`.

    `titulo`/`config_empresa` son opcionales para no romper a los callers existentes
    (catalogos de clientes/bancos/inventario/etc., que solo pasan encabezados+filas): sin
    ellos el archivo queda igual que antes (solo encabezados+filas desde la fila 1). Con
    `config_empresa` se antepone la razon social/RIF/direccion/telefono de la empresa
    (sin logo -- Excel no lo necesita) y, si hay `titulo`, el nombre del reporte centrado
    una fila en blanco despues de esos datos -- pedido del usuario 2026-09-01 para que
    todo reporte exportado (Excel o PDF) traiga la info de la empresa.

    `total_row` y `total_label` son opcionales para agregar una fila de totales al final
    de la tabla.

    `filtros` (periodo, filtros aplicados y totales del reporte, el mismo diccionario que va al PDF) se
    escribe como pares "clave | valor" entre el titulo y la tabla. `secciones` agrega tablas debajo de la
    principal (dicts con "titulo", "encabezados" y "filas")."""
    libro = Workbook()
    hoja = libro.active
    ancho_tabla = max(len(encabezados), 1)
    fila_actual = 1

    if config_empresa is not None:
        lineas_empresa = (
            (
                config_empresa.razon_social_empresa,
                Font(bold=True, size=13, color="12459B"),
            ),
            (formatear_rif(config_empresa.rif_empresa, "J"), Font(size=10, color="64748B")),
            (config_empresa.direccion_empresa, Font(size=10, color="64748B")),
            (config_empresa.telefono_empresa, Font(size=10, color="64748B")),
        )
        escribio_alguna = False
        for indice, (valor, fuente) in enumerate(lineas_empresa):
            if not valor:
                continue
            celda = hoja.cell(row=fila_actual, column=1)
            _poner_valor_excel(celda, valor)
            celda.font = fuente
            if indice == 0:
                # mas alto que el resto -- separa visualmente la razon social del RIF que
                # sigue justo debajo, quedaban muy pegados (hallazgo del usuario).
                hoja.row_dimensions[fila_actual].height = 22
            fila_actual += 1
            escribio_alguna = True
        if escribio_alguna:
            fila_actual += 1  # fila en blanco antes del titulo

    if titulo:
        celda_titulo = hoja.cell(row=fila_actual, column=1, value=titulo)
        celda_titulo.font = Font(bold=True, size=14)
        celda_titulo.alignment = Alignment(horizontal="center")
        if ancho_tabla > 1:
            hoja.merge_cells(
                start_row=fila_actual,
                start_column=1,
                end_row=fila_actual,
                end_column=ancho_tabla,
            )
        fila_actual += 2  # fila en blanco despues del titulo

    # Periodo, filtros aplicados y totales del reporte (el mismo diccionario que va al PDF), como pares
    # clave | valor entre el titulo y la tabla.
    pares = [(k, v) for k, v in (filtros or {}).items() if v not in (None, "")]
    for clave, valor in pares:
        hoja.cell(row=fila_actual, column=1, value=clave).font = Font(bold=True, color="64748B")
        _poner_valor_excel(hoja.cell(row=fila_actual, column=2), valor)
        fila_actual += 1
    if pares:
        fila_actual += 1  # fila en blanco antes de la tabla

    for col_idx, encabezado in enumerate(encabezados, start=1):
        hoja.cell(row=fila_actual, column=col_idx, value=encabezado).font = Font(bold=True)
    fila_actual += 1

    cantidad_filas = 0
    for fila in filas:
        for col_idx, valor in enumerate(fila, start=1):
            _poner_valor_excel(hoja.cell(row=fila_actual, column=col_idx), valor)
        fila_actual += 1
        cantidad_filas += 1

    # Agregar fila de totales si se proporciona
    if total_row is not None:
        if total_label:
            # Reemplazar la primera celda con la etiqueta de total
            total_row_con_label = list(total_row)
            total_row_con_label[0] = total_label
            total_row = total_row_con_label

        for col_idx, valor in enumerate(total_row, start=1):
            celda = hoja.cell(row=fila_actual, column=col_idx)
            _poner_valor_excel(celda, valor)
            celda.font = Font(bold=True)
        fila_actual += 1
        cantidad_filas += 1

    for seccion in secciones or ():
        fila_actual += 1  # fila en blanco antes de la seccion
        hoja.cell(row=fila_actual, column=1, value=seccion["titulo"]).font = Font(bold=True, size=12, color="12459B")
        fila_actual += 1
        for col_idx, encabezado in enumerate(seccion["encabezados"], start=1):
            hoja.cell(row=fila_actual, column=col_idx, value=encabezado).font = Font(bold=True)
        fila_actual += 1
        for fila in seccion["filas"]:
            for col_idx, valor in enumerate(fila, start=1):
                _poner_valor_excel(hoja.cell(row=fila_actual, column=col_idx), valor)
            fila_actual += 1
            cantidad_filas += 1

    _ajustar_anchos_excel(hoja)
    libro.save(ruta)
    logger.info("Excel exportado: %s (%d filas)", ruta, cantidad_filas)


def _imagen_logo_pdf(logo_bytes: bytes, dimension_max: float = 55) -> Image | None:
    """Escala el logo (bytes PNG/JPG guardados en ConfiguracionEmpresa.logotipo_empresa,
    subidos sin control de tamaño en config_empresa_panel.py) a un cuadro de a lo sumo
    `dimension_max` puntos, preservando proporcion -- sin esto reportlab dibujaria la
    imagen a su tamaño nativo en pixeles interpretado como puntos, facilmente mas grande
    que la pagina."""
    try:
        ancho_px, alto_px = ImageReader(BytesIO(logo_bytes)).getSize()
    except (OSError, ValueError):
        return None
    if not ancho_px or not alto_px:
        return None
    escala = dimension_max / max(ancho_px, alto_px)
    return Image(BytesIO(logo_bytes), width=ancho_px * escala, height=alto_px * escala)


def _texto_paragraph(texto: Any) -> str:
    """Texto plano listo para un Paragraph de reportlab, que interpreta su contenido como marcado: sin
    escapar, un "<...>" en un nombre o direccion desaparece, "A&B" sale como "A&B;" y una etiqueta sin
    cerrar hace fallar toda la exportacion."""
    return escape(str(texto)).replace("\n", "<br/>")


def _bloque_empresa_pdf(config_empresa: ConfiguracionEmpresa, styles) -> Table | Paragraph | None:
    estilo_nombre = ParagraphStyle(
        "EmpresaNombre",
        parent=styles["Normal"],
        fontSize=13,
        fontName="Helvetica-Bold",
        textColor=_COLOR_PRIMARIO,
        spaceAfter=5,
    )
    estilo_dato = ParagraphStyle("EmpresaDato", parent=styles["Normal"], fontSize=9, textColor=_COLOR_MUTED)

    lineas: list[Paragraph] = []
    if config_empresa.razon_social_empresa:
        lineas.append(Paragraph(_texto_paragraph(config_empresa.razon_social_empresa), estilo_nombre))
    for valor in (
        formatear_rif(config_empresa.rif_empresa, "J"),
        config_empresa.direccion_empresa,
        config_empresa.telefono_empresa,
    ):
        if valor:
            lineas.append(Paragraph(_texto_paragraph(valor), estilo_dato))
    if not lineas:
        return None

    logo = _imagen_logo_pdf(config_empresa.logotipo_empresa) if config_empresa.logotipo_empresa else None
    if logo is None:
        return (
            lineas[0]
            if len(lineas) == 1
            else Table(
                [[linea] for linea in lineas],
                style=[("LEFTPADDING", (0, 0), (-1, -1), 0)],
            )
        )

    fila = Table([[logo, lineas]], colWidths=[65, None])
    fila.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("LEFTPADDING", (1, 0), (1, 0), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return fila


def _formatear_numero(valor: Any) -> str:
    """Numero con separador de miles y, como minimo, 2 decimales (hasta 4 si el dato los tiene). El signo
    negativo se conserva ("-1,234.50"); un cero negativo sale como "0.00"."""
    try:
        d = valor if isinstance(valor, Decimal) else Decimal(repr(float(valor)))
    except (ValueError, ArithmeticError):
        return str(valor)
    if not d.is_finite():
        return ""
    exponente = d.as_tuple().exponent
    decimales = min(max(2, -exponente if isinstance(exponente, int) else 2), 4)
    texto = f"{d:,.{decimales}f}"
    if texto.startswith("-") and not any(c in "123456789" for c in texto):
        texto = texto[1:]
    return texto


def _es_numero(valor: Any) -> bool:
    return isinstance(valor, (int, float, Decimal)) and not isinstance(valor, bool)


def _texto_celda_pdf(valor: Any) -> str:
    """Texto con que se imprime un valor en una celda del PDF: numeros formateados (con su signo), fechas
    dd/mm/aaaa y vacio para None -- antes salia el repr crudo ("1234.5", "None", "2026-01-02 00:00:00")."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "Sí" if valor else "No"
    if isinstance(valor, int):
        return str(valor)
    if isinstance(valor, (float, Decimal)):
        return _formatear_numero(valor)
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    return str(valor)


def _tabla_pdf(
    titulo: str,
    encabezados: Sequence[str],
    filas: Iterable[Sequence[Any]],
    col_widths: Sequence[float] | None,
    total_row: Sequence[Any] | None,
    total_label: str | None,
    styles,
    ancho_disponible: float,
) -> Table:
    """Tabla de datos de un reporte (o de una seccion adicional) lista para el PDF."""
    # Datos de la tabla. Las columnas con numeros se alinean a la derecha; el texto de las filas de datos se
    # envuelve en un Paragraph para que un texto largo (observaciones, motivo, nombre) baje de linea dentro
    # de su columna en vez de salirse sobre la columna vecina.
    filas_lista = [list(fila) for fila in filas]
    total_fila = None
    if total_row is not None:
        total_fila = list(total_row) or [""]
        if total_label:
            total_fila[0] = total_label  # reemplaza la primera celda con la etiqueta de total

    # Toda fila (encabezado, datos, total) con la misma cantidad de columnas. Si el caller pasa filas con
    # mas celdas que encabezados (p.ej. la pantalla gano una columna y el exportador no se actualizo), antes
    # la tabla salia mas ancha que la hoja y quedaba cortada por los dos lados.
    encabezados = list(encabezados)
    ancho_maximo_filas = max((len(f) for f in [*filas_lista, *([total_fila] if total_fila else [])]), default=0)
    n_columnas = max(len(encabezados), ancho_maximo_filas, 1)
    if ancho_maximo_filas > len(encabezados):
        logger.warning(
            "exportar_pdf(%r): filas con %d columnas pero %d encabezados", titulo, ancho_maximo_filas, len(encabezados)
        )
    encabezados += [""] * (n_columnas - len(encabezados))
    filas_lista = [fila + [None] * (n_columnas - len(fila)) for fila in filas_lista]
    if total_fila is not None:
        total_fila += [None] * (n_columnas - len(total_fila))

    todas_las_filas = [*filas_lista, *([total_fila] if total_fila is not None else [])]
    columnas_numericas = {i for i in range(n_columnas) if any(_es_numero(fila[i]) for fila in todas_las_filas)}

    estilo_celda = ParagraphStyle("CeldaTabla", parent=styles["Normal"], fontSize=8, leading=10)
    estilo_encabezado = ParagraphStyle(
        "EncabezadoTabla",
        parent=styles["Normal"],
        fontSize=9,
        leading=11,
        fontName="Helvetica-Bold",
        textColor=colors.white,
    )
    estilo_encabezado_derecha = ParagraphStyle("EncabezadoTablaDerecha", parent=estilo_encabezado, alignment=2)

    def _celda_dato(valor: Any):
        texto = _texto_celda_pdf(valor)
        if _es_numero(valor) or not texto:
            return texto
        return Paragraph(_texto_paragraph(texto), estilo_celda)

    # Encabezados en Paragraph para que un titulo largo ("Días Transcurridos") baje de linea dentro de su
    # columna en vez de montarse sobre la vecina.
    data = [
        [
            Paragraph(
                _texto_paragraph(_texto_celda_pdf(h)),
                estilo_encabezado_derecha if i in columnas_numericas else estilo_encabezado,
            )
            for i, h in enumerate(encabezados)
        ]
    ]
    for fila in filas_lista:
        data.append([_celda_dato(v) for v in fila])
    if total_fila is not None:
        data.append([_texto_celda_pdf(v) for v in total_fila])  # sin Paragraph: lleva texto blanco en negrita

    # Estilo de la tabla
    table_style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#12459B")),  # Header azul
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
            (
                "WORDWRAP",
                (0, 0),
                (-1, -1),
                "CJK",
            ),  # Permite mejor ajuste de texto largo
        ]
    )

    for col in columnas_numericas:
        table_style.add("ALIGN", (col, 0), (col, -1), "RIGHT")

    # Alternar colores de filas
    for i in range(1, len(data)):
        if total_row is not None and i == len(data) - 1:
            # Fila de totales - fondo azul oscuro, texto blanco
            table_style.add("BACKGROUND", (0, i), (-1, i), colors.HexColor("#12459B"))
            table_style.add("TEXTCOLOR", (0, i), (-1, i), colors.white)
            table_style.add("FONTNAME", (0, i), (-1, i), "Helvetica-Bold")
        elif i % 2 == 0:
            table_style.add("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F8FAFC"))
        else:
            table_style.add("BACKGROUND", (0, i), (-1, i), colors.white)

    # Ancho de columnas: usar anchos específicos si se proporcionan,
    # de lo contrario repartir equitativamente
    pesos = list(col_widths) if col_widths else [1.0] * n_columnas
    if len(pesos) != n_columnas:
        # reportlab repite el ultimo ancho para las columnas que falten, y como los pesos ya se normalizaron al
        # ancho de la hoja la tabla se pasaba del margen. Se completa/recorta para que siempre sume la hoja.
        logger.warning("exportar_pdf(%r): %d anchos para %d columnas", titulo, len(pesos), n_columnas)
        pesos = (pesos + [1.0] * n_columnas)[:n_columnas]
    total_ancho = sum(pesos) or n_columnas
    col_widths_normalizados = [w * ancho_disponible / total_ancho for w in pesos]
    # repeatRows=1: el encabezado se repite en cada pagina de un reporte largo.
    table = Table(data, colWidths=col_widths_normalizados, repeatRows=1)
    table.setStyle(table_style)
    return table


def exportar_pdf(
    ruta: str | Path,
    titulo: str,
    encabezados: Sequence[str],
    filas: Iterable[Sequence[Any]],
    cliente_nombre: str | None = None,
    filtros: dict[str, Any] | None = None,
    col_widths: Sequence[float] | None = None,
    config_empresa: ConfiguracionEmpresa | None = None,
    total_row: Sequence[Any] | None = None,
    total_label: str | None = None,
    secciones: Sequence[dict[str, Any]] | None = None,
    apaisado: bool = False,
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
        config_empresa: datos de la empresa (razón social, RIF, dirección, teléfono,
            logo) a imprimir arriba del título -- opcional para no romper a los callers
            existentes que no lo pasan (catálogos de clientes/bancos/inventario/etc.).
        total_row: Fila de totales a agregar al final de la tabla (opcional).
        total_label: Etiqueta para la fila de totales (opcional, ej: "TOTAL:").
        secciones: tablas adicionales debajo de la principal, cada una un dict con "titulo",
            "encabezados", "filas" y opcionalmente "col_widths" (opcional).
        apaisado: hoja horizontal, para reportes con muchas columnas (opcional).
    """
    margen_horizontal = 30
    pagina = landscape(letter) if apaisado else letter
    ancho_util = pagina[0] - 2 * margen_horizontal
    doc = SimpleDocTemplate(
        str(ruta),
        pagesize=pagina,
        rightMargin=margen_horizontal,
        leftMargin=margen_horizontal,
        topMargin=30,
        bottomMargin=18,
    )

    elements = []
    styles = getSampleStyleSheet()

    # Datos de la empresa (con logo) arriba de todo -- pedido del usuario 2026-09-01.
    if config_empresa is not None:
        bloque_empresa = _bloque_empresa_pdf(config_empresa, styles)
        if bloque_empresa is not None:
            elements.append(bloque_empresa)
            elements.append(Spacer(1, 14))  # 1-2 lineas de separacion antes del titulo

    # Título del reporte con fecha y hora, centrado
    fecha_hora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    titulo_completo = f"{titulo} - {fecha_hora}"
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=16,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#12459B"),
        spaceAfter=12,
    )
    elements.append(Paragraph(_texto_paragraph(titulo_completo), title_style))

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
            elements.append(Paragraph(_texto_paragraph(f"Filtros: {filtro_texto}"), filtro_style))

    # Nombre del cliente si se proporciona
    if cliente_nombre:
        cliente_style = ParagraphStyle(
            "Cliente",
            parent=styles["Normal"],
            fontSize=12,
            textColor=colors.HexColor("#64748B"),
            spaceAfter=12,
        )
        elements.append(Paragraph(_texto_paragraph(f"Cliente: {cliente_nombre}"), cliente_style))

    elements.append(_tabla_pdf(titulo, encabezados, filas, col_widths, total_row, total_label, styles, ancho_util))

    # Secciones adicionales (p.ej. las notas de credito del Libro de Ventas): otra tabla debajo, con su titulo.
    estilo_seccion = ParagraphStyle(
        "SeccionTitulo", parent=styles["Heading2"], fontSize=12, textColor=_COLOR_PRIMARIO, spaceBefore=16, spaceAfter=6
    )
    for seccion in secciones or ():
        elements.append(Paragraph(_texto_paragraph(seccion["titulo"]), estilo_seccion))
        elements.append(
            _tabla_pdf(
                seccion["titulo"],
                seccion["encabezados"],
                seccion["filas"],
                seccion.get("col_widths"),
                None,
                None,
                styles,
                ancho_util,
            )
        )

    doc.build(elements)
    logger.info("PDF exportado: %s", ruta)
