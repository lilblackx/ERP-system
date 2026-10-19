import pytest

from app.utils.rif import formatear_identificacion, formatear_numero, formatear_rif, partir


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("070007508", "J-07000750-8"),  # el caso real: 9 digitos sin letra
        ("J-07000750-8", "J-07000750-8"),  # ya formateado: no cambia
        ("j070007508", "J-07000750-8"),
        ("J 07.000.750-8", "J-07000750-8"),
        ("j-7000750-8", "J-07000750-8"),  # completa a 8 digitos con ceros
        ("07000750-8", "J-07000750-8"),
        ("G-20000001-0", "G-20000001-0"),
        ("V-12345678", "V-12345678"),  # cedula: sin verificador, sin ceros agregados
        ("v12345678", "V-12345678"),
        ("E-84555111", "E-84555111"),
    ],
)
def test_formatear_rif(texto, esperado):
    assert formatear_rif(texto, letra_defecto="J") == esperado


def test_sin_letra_y_sin_defecto_no_se_inventa_la_letra():
    assert formatear_rif("070007508") == "07000750-8"
    assert formatear_rif("12345678") == "12345678"


def test_la_letra_defecto_no_pisa_la_que_trae_el_texto():
    assert formatear_rif("V-12345678", letra_defecto="J") == "V-12345678"


@pytest.mark.parametrize("texto", ["", None, "abc", "Sin RIF", "J-", "1234567890", "J-1-2-3"])
def test_texto_no_reconocible_se_devuelve_tal_cual(texto):
    assert formatear_rif(texto, letra_defecto="J") == (texto or "")


def test_formatear_rif_es_idempotente():
    una_vez = formatear_rif("070007508", letra_defecto="J")
    assert formatear_rif(una_vez, letra_defecto="J") == una_vez


@pytest.mark.parametrize(
    "numero, esperado",
    [
        ("07000750-8", "07000750-8"),
        ("070007508", "07000750-8"),
        ("12345678", "12345678"),
        ("7000750-8", "07000750-8"),
        (" 30489713 ", "30489713"),
        ("", ""),
        (None, ""),
        ("abc", "abc"),
    ],
)
def test_formatear_numero(numero, esperado):
    assert formatear_numero(numero) == esperado


def test_formatear_identificacion_une_letra_y_numero():
    assert formatear_identificacion("J", "07000750-8") == "J-07000750-8"
    assert formatear_identificacion("j", "070007508") == "J-07000750-8"
    assert formatear_identificacion("V", "12345678") == "V-12345678"
    assert formatear_identificacion(None, "12345678") == "12345678"
    assert formatear_identificacion("J", None) == "J"
    assert formatear_identificacion(None, None) == ""


def test_partir_devuelve_none_si_no_es_un_rif():
    assert partir("hola") is None
    assert partir(None) is None
    assert partir("J-07000750-8") == ("J", "07000750", "8")
