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
