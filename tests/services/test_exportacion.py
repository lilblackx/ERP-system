from openpyxl import load_workbook

from app.services.exportacion import exportar_excel


def test_exportar_excel_escribe_encabezados_y_filas(tmp_path):
    ruta = tmp_path / "reporte.xlsx"

    exportar_excel(ruta, ["Cliente", "Saldo"], [["Cliente A", 100], ["Cliente B", 50]])

    libro = load_workbook(ruta)
    hoja = libro.active
    filas = [[celda.value for celda in fila] for fila in hoja.iter_rows()]
    assert filas == [["Cliente", "Saldo"], ["Cliente A", 100], ["Cliente B", 50]]


def test_exportar_excel_sin_filas_escribe_solo_encabezados(tmp_path):
    ruta = tmp_path / "vacio.xlsx"

    exportar_excel(ruta, ["Cliente", "Saldo"], [])

    libro = load_workbook(ruta)
    hoja = libro.active
    filas = [[celda.value for celda in fila] for fila in hoja.iter_rows()]
    assert filas == [["Cliente", "Saldo"]]


def test_exportar_excel_acepta_generador_de_filas(tmp_path):
    ruta = tmp_path / "generador.xlsx"

    def filas():
        yield ["A", 1]
        yield ["B", 2]

    exportar_excel(ruta, ["Letra", "Numero"], filas())

    libro = load_workbook(ruta)
    hoja = libro.active
    valores = [[celda.value for celda in fila] for fila in hoja.iter_rows()]
    assert valores == [["Letra", "Numero"], ["A", 1], ["B", 2]]


# -- Valores negativos y textos "peligrosos": se exportan intactos y con su tipo ---------------------

from datetime import date, datetime  # noqa: E402
from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402

from app.services.exportacion import (  # noqa: E402
    _formatear_numero,
    _texto_celda_pdf,
    exportar_pdf,
    valor_para_exportar,
)


def _celdas(ruta):
    hoja = load_workbook(ruta).active
    return [[celda for celda in fila] for fila in hoja.iter_rows()]


def test_numeros_negativos_se_exportan_como_numeros_con_su_signo(tmp_path):
    ruta = tmp_path / "neg.xlsx"

    exportar_excel(ruta, ["A", "B", "C"], [[-1234.5, Decimal("-100.00"), -7]])

    a, b, c = _celdas(ruta)[1]
    assert (a.value, a.data_type) == (-1234.5, "n")
    assert (b.value, b.data_type) == (-100, "n")
    assert (c.value, c.data_type) == (-7, "n")
    assert a.number_format == "#,##0.00##"  # separador de miles y 2 decimales; el signo "-" se conserva


@pytest.mark.parametrize("texto", ["-100.00", "-5.00%", "+584141234567", "-", "=1+1", "@usuario", "- guion"])
def test_los_textos_que_empiezan_con_signo_o_formula_se_guardan_intactos(tmp_path, texto):
    """Antes se les anteponia un apostrofe literal ("'-100.00"): corrompia el dato."""
    ruta = tmp_path / "txt.xlsx"

    exportar_excel(ruta, ["Valor"], [[texto]])

    celda = _celdas(ruta)[1][0]
    assert celda.value == texto
    assert celda.data_type == "s"  # texto literal: nunca una formula que Excel evalue


def test_un_texto_con_igual_no_se_guarda_como_formula(tmp_path):
    ruta = tmp_path / "f.xlsx"

    exportar_excel(ruta, ["Valor"], [['=HYPERLINK("http://x","y")']])

    celda = _celdas(ruta)[1][0]
    assert celda.data_type != "f"
    assert celda.quotePrefix  # Excel lo trata como texto aunque el usuario edite la celda


def test_fila_de_totales_conserva_numeros_y_negativos(tmp_path):
    ruta = tmp_path / "tot.xlsx"

    exportar_excel(ruta, ["Concepto", "Monto"], [["x", 10]], total_row=["", Decimal("-25.50")], total_label="TOTAL")

    etiqueta, total = _celdas(ruta)[2]
    assert etiqueta.value == "TOTAL"
    assert (total.value, total.data_type) == (Decimal("-25.50"), "n") or total.value == -25.5


def test_fechas_y_valores_especiales_no_rompen_el_excel(tmp_path):
    ruta = tmp_path / "esp.xlsx"

    exportar_excel(
        ruta,
        ["F", "FH", "None", "NaN", "Bool", "Ctrl"],
        [[date(2026, 1, 2), datetime(2026, 1, 2, 13, 5), None, float("nan"), True, "a\x00b\x07c"]],
    )

    f, fh, nada, nan, booleano, ctrl = _celdas(ruta)[1]
    assert f.number_format == "dd/mm/yyyy"
    assert fh.number_format == "dd/mm/yyyy hh:mm"
    assert nada.value is None and nan.value is None
    assert booleano.value is True
    assert ctrl.value == "abc"  # los caracteres de control ilegales en XML se quitan en vez de romper el archivo


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("$1,234.50", Decimal("1234.50")),
        ("$-5.00", Decimal("-5.00")),
        ("-$5.00", Decimal("-5.00")),
        ("-1,234.50", Decimal("-1234.50")),
        ("1,234.50", Decimal("1234.50")),
        ("$0.00", Decimal("0.00")),
        ("-5.00", Decimal("-5.00")),
        # lo que NO es un monto se devuelve igual
        ("FV-000123", "FV-000123"),
        ("CLI-000045", "CLI-000045"),
        ("0414-1234567", "0414-1234567"),
        ("+584141234567", "+584141234567"),
        ("12.50%", "12.50%"),
        ("10/05/2026", "10/05/2026"),
        ("000123", "000123"),
        ("15", "15"),
        ("", ""),
        ("-", "-"),
    ],
)
def test_valor_para_exportar_solo_convierte_montos_claros(texto, esperado):
    assert valor_para_exportar(texto) == esperado


def test_valor_para_exportar_deja_pasar_lo_que_no_es_texto():
    assert valor_para_exportar(5) == 5
    assert valor_para_exportar(None) is None
    assert valor_para_exportar(Decimal("-1")) == Decimal("-1")


# -- PDF ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (1234.5, "1,234.50"),
        (-1234.5, "-1,234.50"),
        (Decimal("-100.00"), "-100.00"),
        (Decimal("0.00"), "0.00"),
        (-0.0, "0.00"),
        (Decimal("-0.00"), "0.00"),
        (1.2345, "1.2345"),
        (100.0, "100.00"),
        (float("nan"), ""),
    ],
)
def test_formato_de_numeros_en_pdf_conserva_el_signo(valor, esperado):
    assert _formatear_numero(valor) == esperado


def test_texto_de_celda_pdf_para_cada_tipo():
    assert _texto_celda_pdf(None) == ""
    assert _texto_celda_pdf(True) == "Sí"
    assert _texto_celda_pdf(7) == "7"
    assert _texto_celda_pdf(date(2026, 1, 2)) == "02/01/2026"
    assert _texto_celda_pdf(datetime(2026, 1, 2, 13, 5)) == "02/01/2026 13:05"
    assert _texto_celda_pdf("-5.00") == "-5.00"


def test_exportar_pdf_con_negativos_texto_largo_y_caracteres_especiales(tmp_path):
    ruta = tmp_path / "r.pdf"
    largo = "Observación muy larga " * 30 + "<b>&amp;</b> -no es formula"

    exportar_pdf(
        ruta,
        "Reporte",
        ["Texto", "Monto", "Fecha", "Vacío"],
        [[largo, Decimal("-1234.50"), date(2026, 1, 2), None], ["-", -0.0, datetime(2026, 1, 2, 9, 0), ""]],
        total_row=["", Decimal("-1234.50"), "", ""],
        total_label="TOTAL",
    )

    contenido = ruta.read_bytes()
    assert contenido.startswith(b"%PDF") and len(contenido) > 1000


# -- PDF: la tabla nunca se sale de la hoja ----------------------------------------------------------

from types import SimpleNamespace  # noqa: E402

from reportlab.lib.pagesizes import landscape, letter  # noqa: E402
from reportlab.platypus import Paragraph, Table  # noqa: E402

import app.services.exportacion as exportacion  # noqa: E402

_ANCHO_UTIL = letter[0] - 2 * 30  # margen_horizontal de exportar_pdf


@pytest.fixture
def elementos_pdf(monkeypatch):
    """Captura los flowables que exportar_pdf manda a construir, sin escribir el archivo."""
    capturados: list = []
    monkeypatch.setattr(exportacion.SimpleDocTemplate, "build", lambda self, elementos: capturados.extend(elementos))
    return capturados


def _tabla(elementos) -> Table:
    return next(e for e in elementos if isinstance(e, Table) and getattr(e, "repeatRows", 0) == 1)


def test_pdf_con_mas_columnas_que_encabezados_no_se_sale_de_la_hoja(tmp_path, elementos_pdf):
    """Caso real (CxC): la pantalla gano columnas y el exportador seguia pasando 5 encabezados/anchos;
    reportlab repetia el ultimo ancho y la tabla salia cortada por los dos lados."""
    exportar_pdf(
        tmp_path / "r.pdf",
        "Cuentas por Cobrar",
        ["Cliente", "Saldo", "Días", "Fecha", "Estado"],
        [["Cliente A", 10.0, 0.0, 0.0, 3, "05/11/2026", "Pendiente"]],
        col_widths=[2.5, 1.5, 0.8, 1.2, 1.0],
    )

    tabla = _tabla(elementos_pdf)
    assert tabla._ncols == 7
    assert sum(tabla._colWidths) == pytest.approx(_ANCHO_UTIL)


def test_pdf_con_menos_anchos_que_columnas_ocupa_exactamente_la_hoja(tmp_path, elementos_pdf):
    columnas = ["Factura", "Cliente", "Venc.", "Saldo", "Días", "Días T.", "Rango"]
    exportar_pdf(tmp_path / "r.pdf", "Aging", columnas, [["F-1", "C", "x", 1.0, 1, 2, "1-30"]], col_widths=[1, 2, 1])

    tabla = _tabla(elementos_pdf)
    assert tabla._ncols == len(columnas)
    assert sum(tabla._colWidths) == pytest.approx(_ANCHO_UTIL)


def test_pdf_repite_el_encabezado_en_cada_pagina(tmp_path, elementos_pdf):
    exportar_pdf(tmp_path / "r.pdf", "R", ["A"], [[str(i)] for i in range(5)])

    assert _tabla(elementos_pdf).repeatRows == 1


def test_pdf_no_pierde_texto_con_ampersand_ni_menor_que_en_empresa_titulo_y_filtros(tmp_path, elementos_pdf):
    empresa = SimpleNamespace(
        razon_social_empresa="Inversiones A&B, C.A.",
        rif_empresa="J123456789",
        direccion_empresa="Av. <Principal>",
        telefono_empresa=None,
        logotipo_empresa=None,
    )

    exportar_pdf(
        tmp_path / "r.pdf",
        "Compras & Pagos",
        ["A"],
        [["x"]],
        filtros={"Cliente": "Ferre <b>El Tornillo"},  # etiqueta sin cerrar: antes tumbaba la exportacion
        config_empresa=empresa,
    )

    def _textos(elementos):
        for e in elementos:
            if isinstance(e, Paragraph):
                yield "".join(f.text for f in e.frags)
            elif isinstance(e, Table):
                for fila in e._cellvalues:
                    for celda in fila:
                        yield from _textos(celda if isinstance(celda, list) else [celda])

    textos = list(_textos(elementos_pdf))
    assert "Inversiones A&B, C.A." in textos
    assert "Av. <Principal>" in textos
    assert any(t.startswith("Compras & Pagos - ") for t in textos)
    assert "Filtros: Cliente: Ferre <b>El Tornillo" in textos


# -- Excel: filtros, secciones adicionales y anchos --------------------------------------------------


def _valores(ruta):
    return [[celda.value for celda in fila] for fila in load_workbook(ruta).active.iter_rows()]


def test_excel_incluye_periodo_filtros_y_totales_como_pares_clave_valor(tmp_path):
    ruta = tmp_path / "f.xlsx"

    exportar_excel(
        ruta,
        ["Cliente", "Saldo"],
        [["A", 10]],
        titulo="Aging",
        filtros={"Corte": "16/10/2026", "Cliente": "Todos", "Vacio": "", "Nulo": None, "Total general": "$10.00"},
    )

    valores = _valores(ruta)
    assert valores[0][0] == "Aging"
    assert valores[2][:2] == ["Corte", "16/10/2026"]
    assert valores[3][:2] == ["Cliente", "Todos"]
    assert valores[4][:2] == ["Total general", "$10.00"]  # los filtros vacios no se escriben
    assert valores[6][:2] == ["Cliente", "Saldo"]  # una fila en blanco y la tabla
    assert valores[7][:2] == ["A", 10]


def test_excel_sin_filtros_queda_igual_que_antes(tmp_path):
    ruta = tmp_path / "s.xlsx"

    exportar_excel(ruta, ["A"], [[1]], titulo="T")

    assert _valores(ruta) == [["T"], [None], ["A"], [1]]


def test_excel_agrega_secciones_debajo_de_la_tabla_principal(tmp_path):
    ruta = tmp_path / "sec.xlsx"

    exportar_excel(
        ruta,
        ["Factura", "Total"],
        [["FV-1", 100]],
        secciones=[
            {"titulo": "Notas de crédito", "encabezados": ["NC", "Monto", "Motivo"], "filas": [["NC-1", 30, "x"]]}
        ],
    )

    assert _valores(ruta) == [
        ["Factura", "Total", None],
        ["FV-1", 100, None],
        [None, None, None],
        ["Notas de crédito", None, None],
        ["NC", "Monto", "Motivo"],
        ["NC-1", 30, "x"],
    ]


def test_la_fila_de_totales_no_pinta_de_azul_una_columna_fija(tmp_path):
    ruta = tmp_path / "t.xlsx"

    exportar_excel(ruta, ["A", "B", "C"], [["x", 1, 2]], total_row=["", 1, 2], total_label="TOTAL")

    total = [celda for celda in load_workbook(ruta).active[3]]
    assert all(celda.font.bold for celda in total)
    assert all(celda.font.color is None or celda.font.color.rgb != "0012459B" for celda in total)


def test_excel_ajusta_el_ancho_de_las_columnas_al_contenido(tmp_path):
    ruta = tmp_path / "w.xlsx"

    exportar_excel(ruta, ["Cliente", "N"], [["Distribuidora de Alimentos del Sur, C.A.", 1]], titulo="Reporte largo")

    hoja = load_workbook(ruta).active
    assert hoja.column_dimensions["A"].width > 40
    assert hoja.column_dimensions["B"].width <= 12  # el titulo combinado no ensancha la columna


# -- PDF: secciones adicionales y hoja horizontal -----------------------------------------------------


def test_pdf_agrega_una_tabla_por_seccion_con_su_titulo(tmp_path, elementos_pdf):
    exportar_pdf(
        tmp_path / "r.pdf",
        "Libro de Ventas",
        ["Factura", "Total"],
        [["FV-1", 100.0]],
        secciones=[
            {"titulo": "Notas de crédito del período", "encabezados": ["NC", "Monto"], "filas": [["NC-1", 30.0]]}
        ],
    )

    tablas = [e for e in elementos_pdf if isinstance(e, Table)]
    titulos = ["".join(f.text for f in e.frags) for e in elementos_pdf if isinstance(e, Paragraph)]
    assert len(tablas) == 2
    assert "Notas de crédito del período" in titulos
    assert sum(tablas[1]._colWidths) == pytest.approx(_ANCHO_UTIL)


def test_pdf_apaisado_usa_el_ancho_de_la_hoja_horizontal(tmp_path, elementos_pdf):
    columnas = [f"C{i}" for i in range(13)]

    exportar_pdf(tmp_path / "h.pdf", "Ancho", columnas, [list(range(13))], apaisado=True)

    assert sum(_tabla(elementos_pdf)._colWidths) == pytest.approx(landscape(letter)[0] - 60)


def test_pdf_apaisado_se_genera_de_verdad(tmp_path):
    ruta = tmp_path / "h.pdf"

    exportar_pdf(ruta, "Ancho", [f"C{i}" for i in range(13)], [list(range(13))] * 40, apaisado=True)

    contenido = ruta.read_bytes()
    assert contenido.startswith(b"%PDF") and b"/MediaBox [ 0 0 792 612 ]" in contenido
