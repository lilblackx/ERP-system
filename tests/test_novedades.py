"""Novedades por version y bienvenida al entrar (app/novedades.py): logica pura, sin Qt ni base de datos."""

import json
from datetime import datetime

import pytest

from app import novedades as nv
from app.novedades import (
    Cambio,
    Entrega,
    TipoBienvenida,
    clave_version,
    entregas_a_mostrar,
    filtrar_por_modulos,
    preparar_bienvenida,
    primer_nombre,
    saludo_segun_hora,
)
from app.ui.sidebar import SECCIONES
from app.version import VERSION

MODULOS_REALES = {clave for _seccion, items in SECCIONES for clave, _texto in items}


def _entrega(version, *cambios):
    return Entrega(version, "2026-11-06", f"Entrega {version}", tuple(cambios))


GENERAL = Cambio("mejorado", "Algo para todos")
CLIENTES = Cambio("nuevo", "Solo clientes", ("clientes",))
REPORTES = Cambio("mejorado", "Solo reportes", ("reportes",))
ENTREGAS = [_entrega("1.2.0", GENERAL, CLIENTES), _entrega("1.1.0", REPORTES), _entrega("1.0.0", GENERAL)]


# -- versiones --------------------


@pytest.mark.parametrize(
    ("menor", "mayor"),
    [("1.0.0", "1.0.1"), ("1.9.0", "1.10.0"), ("1.2.9", "1.3.0"), ("0.9", "1.0.0"), ("1.0.0", "2.0.0")],
)
def test_las_versiones_se_comparan_numericamente(menor, mayor):
    assert clave_version(menor) < clave_version(mayor)  # "1.9.0" < "1.10.0" (no como texto)


def test_clave_version_tolera_sufijos_y_valores_raros():
    assert clave_version("1.2.0-prueba") == (1, 2, 0)
    assert clave_version("") == (0,)
    assert clave_version(None) == (0,)


# -- que entregas se muestran --------------------


def test_solo_se_muestran_las_novedades_de_la_version_instalada():
    assert [e.version for e in entregas_a_mostrar(ENTREGAS, "1.2.0")] == ["1.2.0"]
    assert [e.version for e in entregas_a_mostrar(ENTREGAS, "1.1.0")] == ["1.1.0"]


def test_las_novedades_no_se_suman_entre_versiones():
    """Quien se salto versiones (1.0.0 -> 1.2.0) ve solo la 1.2.0, no la 1.1.0 intermedia."""
    assert [e.version for e in entregas_a_mostrar(ENTREGAS, "1.2.0")] != ["1.2.0", "1.1.0"]
    b = preparar_bienvenida(
        nombre="Luis",
        ultima_vista="1.0.0",
        version_actual="1.2.0",
        primer_ingreso=False,
        modulos_visibles=None,
        entregas=ENTREGAS,
        ahora=datetime(2026, 11, 6, 9, 0),
    )
    assert [e.version for e in b.entregas] == ["1.2.0"]


def test_una_version_sin_entrada_de_novedades_no_muestra_las_anteriores():
    assert entregas_a_mostrar(ENTREGAS, "1.3.0") == []


# -- filtro por modulos del rol --------------------


def test_el_filtro_deja_los_cambios_generales_y_los_de_modulos_visibles():
    r = filtrar_por_modulos([ENTREGAS[0]], {"clientes"})

    assert [c.texto for c in r[0].cambios] == ["Algo para todos", "Solo clientes"]


def test_el_filtro_quita_lo_de_modulos_que_el_rol_no_ve():
    r = filtrar_por_modulos([ENTREGAS[0]], {"reportes"})

    assert [c.texto for c in r[0].cambios] == ["Algo para todos"]  # "Solo clientes" no aplica a este rol


def test_una_entrega_sin_cambios_visibles_se_omite():
    assert filtrar_por_modulos([ENTREGAS[1]], {"clientes"}) == []  # solo traia un cambio de reportes
    assert len(filtrar_por_modulos([ENTREGAS[1]], {"reportes"})) == 1


def test_sin_filtro_se_ven_todos_los_cambios():
    assert filtrar_por_modulos(ENTREGAS, None) == ENTREGAS


# -- saludo --------------------


@pytest.mark.parametrize(
    ("hora", "esperado"),
    [
        (0, "Buenas noches"),
        (4, "Buenas noches"),
        (5, "Buenos días"),
        (11, "Buenos días"),
        (12, "Buenas tardes"),
        (18, "Buenas tardes"),
        (19, "Buenas noches"),
        (23, "Buenas noches"),
    ],
)
def test_el_saludo_depende_de_la_hora(hora, esperado):
    assert saludo_segun_hora(datetime(2026, 11, 6, hora, 30)) == esperado


def test_primer_nombre():
    assert primer_nombre("luis fernando", "lfernandez") == "Luis"
    assert primer_nombre("  Ana María ", "ana") == "Ana"
    assert primer_nombre(None, "admin") == "Admin"
    assert primer_nombre("", "cajero1") == "Cajero1"


# -- que se le muestra al usuario al entrar --------------------


def _bienvenida(**kw):
    base = dict(
        nombre="Luis",
        ultima_vista="1.0.0",
        version_actual="1.2.0",
        primer_ingreso=False,
        modulos_visibles=None,
        entregas=ENTREGAS,
        ahora=datetime(2026, 11, 6, 9, 0),
    )
    base.update(kw)
    return preparar_bienvenida(**base)


def test_el_primer_ingreso_recibe_una_bienvenida_sin_novedades():
    b = _bienvenida(primer_ingreso=True, ultima_vista=None)

    assert b.tipo is TipoBienvenida.PRIMER_INGRESO
    assert b.titulo == "¡Bienvenido, Luis!" and not b.mostrar_novedades


def test_tras_actualizar_se_muestran_las_novedades_con_el_nombre():
    b = _bienvenida()

    assert b.tipo is TipoBienvenida.NOVEDADES and b.mostrar_novedades
    assert b.titulo == "Hola, Luis"
    assert [e.version for e in b.entregas] == ["1.2.0"]


def test_la_misma_version_solo_saluda_segun_la_hora():
    b = _bienvenida(ultima_vista="1.2.0")

    assert b.tipo is TipoBienvenida.SALUDO and not b.mostrar_novedades
    assert (b.titulo, b.subtitulo) == ("Buenos días, Luis", "Bienvenido de nuevo")


def test_usuario_que_ya_usaba_la_app_y_no_tiene_version_guardada_ve_la_version_actual():
    b = _bienvenida(ultima_vista=None)

    assert b.mostrar_novedades and [e.version for e in b.entregas] == ["1.2.0"]


def test_si_el_filtro_por_rol_no_deja_nada_se_cae_al_saludo_normal():
    """Version nueva, pero ningun cambio aplica a los modulos de este rol: no se le muestra una ventana vacia."""
    b = _bienvenida(ultima_vista="1.0.0", version_actual="1.1.0", modulos_visibles={"clientes"})

    assert b.tipo is TipoBienvenida.SALUDO and b.titulo == "Buenos días, Luis"


def test_el_rol_solo_ve_las_novedades_de_sus_modulos():
    textos_reportes = [c.texto for e in _bienvenida(modulos_visibles={"reportes"}).entregas for c in e.cambios]
    textos_clientes = [c.texto for e in _bienvenida(modulos_visibles={"clientes"}).entregas for c in e.cambios]

    assert "Solo clientes" not in textos_reportes
    assert "Solo clientes" in textos_clientes


# -- el archivo REAL de novedades --------------------


def test_el_archivo_de_novedades_se_carga_y_esta_ordenado_de_la_mas_nueva_a_la_mas_vieja():
    entregas = nv.cargar_entregas()

    assert entregas
    claves = [clave_version(e.version) for e in entregas]
    assert claves == sorted(claves, reverse=True)


def test_la_version_actual_tiene_su_entrada_de_novedades():
    """Si se sube VERSION sin escribir sus novedades, esta prueba falla (ver app/version.py)."""
    versiones = [e.version for e in nv.cargar_entregas()]

    assert VERSION in versiones, f"Falta la entrada de {VERSION} en app/assets/novedades.json"


def test_todos_los_cambios_del_archivo_son_validos():
    for entrega in nv.cargar_entregas():
        assert entrega.titulo and entrega.fecha_legible != entrega.fecha  # fecha AAAA-MM-DD valida
        for cambio in entrega.cambios:
            assert cambio.tipo in nv.TIPOS_DE_CAMBIO, (entrega.version, cambio.tipo)
            assert len(cambio.texto) <= nv.MAX_LARGO_TEXTO, f"Demasiado detalle ({entrega.version}): {cambio.texto}"
            assert cambio.texto.strip(), entrega.version
            desconocidos = set(cambio.modulos) - MODULOS_REALES
            assert not desconocidos, f"Modulos que no existen en el sidebar: {desconocidos}"


def test_un_archivo_ausente_o_danado_no_rompe_la_app(tmp_path):
    assert nv.cargar_entregas(tmp_path / "no_existe.json") == []
    malo = tmp_path / "malo.json"
    malo.write_text("{esto no es json", encoding="utf-8")
    assert nv.cargar_entregas(malo) == []
    sin_clave = tmp_path / "sin_clave.json"
    sin_clave.write_text(json.dumps({"otra": []}), encoding="utf-8")
    assert nv.cargar_entregas(sin_clave) == []


def test_las_novedades_son_discretas():
    """Criterio editorial (ver app/version.py): poco y util. Los arreglos no se anuncian, se resumen en una linea."""
    for entrega in nv.cargar_entregas():
        assert len(entrega.cambios) <= nv.MAX_CAMBIOS_POR_ENTREGA, f"{entrega.version}: demasiadas lineas"
        assert sum(c.tipo == "general" for c in entrega.cambios) <= 1, f"{entrega.version}: una sola linea general"
        assert any(c.destacado for c in entrega.cambios), f"{entrega.version}: resalta lo mas util (destacado)"


def test_los_arreglos_no_tienen_tipo_propio_en_las_novedades():
    assert "corregido" not in nv.TIPOS_DE_CAMBIO


def test_la_linea_general_sola_no_abre_la_ventana_de_novedades():
    """Un rol al que no le aplica ningun cambio concreto no recibe una ventana con solo 'mejoras de estabilidad'."""
    general = Cambio("general", "Mejoras de estabilidad y funcionamiento.")
    entrega = _entrega("1.2.0", CLIENTES, general)

    assert filtrar_por_modulos([entrega], {"reportes"}) == []
    assert [c.texto for c in filtrar_por_modulos([entrega], {"clientes"})[0].cambios] == [
        "Solo clientes",
        "Mejoras de estabilidad y funcionamiento.",
    ]
