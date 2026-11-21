"""Dialogo de rutas: la zona se traza punto a punto en el orden de los clics y se cierra tocando el primer
punto (el mapa avisa con zona_cerrada_solicitada). Lo que se guarda es esa misma lista, sin reordenar.
El mapa real (QtWebEngine) esta reemplazado por un doble en tests/ui/conftest.py: aqui se verifica lo que
el dialogo le pide al mapa y como reacciona a sus senales, no el JavaScript de Leaflet."""

import json
from types import SimpleNamespace

import pytest

import app.ui.ruta_form_dialog as rfd
from app.ui.mapa_widget import MapaWidget

PUNTOS = [(10.0, -66.0), (10.0, -65.0), (11.0, -65.0), (11.0, -66.0)]


def _crear(qtbot, monkeypatch, ruta=None):
    avisos = []
    monkeypatch.setattr(rfd.MessageBox, "warning", staticmethod(lambda *a, **k: avisos.append(("warning", a[2]))))
    monkeypatch.setattr(
        rfd.MessageBox, "information", staticmethod(lambda *a, **k: avisos.append(("information", a[2])))
    )
    dibujos = []
    # El dialogo precarga la zona al construirse: se espia el mapa ANTES para ver tambien ese dibujo.
    monkeypatch.setattr(
        MapaWidget, "establecer_zona", lambda self, vertices, cerrada=True: dibujos.append((list(vertices), cerrada))
    )
    dialogo = rfd.RutaFormDialog(ruta=ruta)
    qtbot.addWidget(dialogo)
    dialogo.avisos = avisos
    dialogo.dibujos = dibujos
    return dialogo


def _marcar(dialogo, puntos):
    for lat, lng in puntos:
        dialogo.mapa.vertice_zona_agregado.emit(lat, lng)


def test_los_vertices_se_dibujan_en_el_orden_de_los_clics_y_sin_cerrar(qtbot, monkeypatch):
    dialogo = _crear(qtbot, monkeypatch)
    desordenados = [PUNTOS[0], PUNTOS[2], PUNTOS[1], PUNTOS[3]]  # el orden de los clics no es el del perimetro

    _marcar(dialogo, desordenados)

    assert dialogo.dibujos[-1] == (desordenados, False)
    assert dialogo.lbl_contador.text() == "4 vértices marcados"


def test_tocar_el_primer_punto_con_3_vertices_cierra_la_zona(qtbot, monkeypatch):
    dialogo = _crear(qtbot, monkeypatch)
    _marcar(dialogo, PUNTOS[:3])

    dialogo.mapa.zona_cerrada_solicitada.emit()

    assert dialogo.dibujos[-1] == (PUNTOS[:3], True)
    assert dialogo.lbl_contador.text() == "Zona cerrada — 3 vértices"


def test_cerrar_con_menos_de_3_vertices_avisa_y_no_cierra(qtbot, monkeypatch):
    dialogo = _crear(qtbot, monkeypatch)
    _marcar(dialogo, PUNTOS[:2])
    dibujos_antes = len(dialogo.dibujos)

    dialogo.mapa.zona_cerrada_solicitada.emit()

    assert dialogo.avisos and dialogo.avisos[0][0] == "information"
    assert "3 puntos" in dialogo.avisos[0][1]
    assert len(dialogo.dibujos) == dibujos_antes
    assert dialogo.lbl_contador.text() == "2 vértices marcados (mínimo 3)"


def test_un_vertice_nuevo_despues_de_cerrar_reabre_el_trazo(qtbot, monkeypatch):
    dialogo = _crear(qtbot, monkeypatch)
    _marcar(dialogo, PUNTOS[:3])
    dialogo.mapa.zona_cerrada_solicitada.emit()

    _marcar(dialogo, [PUNTOS[3]])

    assert dialogo.dibujos[-1] == (PUNTOS, False)
    assert dialogo.lbl_contador.text() == "4 vértices marcados"


def test_deshacer_por_debajo_de_3_vertices_deja_de_estar_cerrada(qtbot, monkeypatch):
    dialogo = _crear(qtbot, monkeypatch)
    _marcar(dialogo, PUNTOS[:3])
    dialogo.mapa.zona_cerrada_solicitada.emit()

    dialogo._deshacer_vertice()

    assert dialogo.dibujos[-1] == (PUNTOS[:2], False)
    assert dialogo._cerrada is False


def test_deshacer_con_zona_cerrada_de_4_vertices_quita_el_ultimo_clic(qtbot, monkeypatch):
    dialogo = _crear(qtbot, monkeypatch)
    _marcar(dialogo, PUNTOS)
    dialogo.mapa.zona_cerrada_solicitada.emit()

    dialogo._deshacer_vertice()

    assert dialogo._vertices == PUNTOS[:3]
    assert dialogo.dibujos[-1][0] == PUNTOS[:3]


def test_limpiar_borra_los_vertices_y_vuelve_a_abierta(qtbot, monkeypatch):
    dialogo = _crear(qtbot, monkeypatch)
    limpiezas = []
    monkeypatch.setattr(dialogo.mapa, "limpiar_zona", lambda: limpiezas.append(True))
    _marcar(dialogo, PUNTOS[:3])
    dialogo.mapa.zona_cerrada_solicitada.emit()

    dialogo._limpiar_zona()

    assert dialogo._vertices == [] and dialogo._cerrada is False
    assert limpiezas == [True]
    assert dialogo.lbl_contador.text() == "0 vértices marcados (mínimo 3)"


def test_editar_una_ruta_precarga_la_zona_cerrada_en_su_orden_original(qtbot, monkeypatch):
    ruta = SimpleNamespace(
        nombre_ruta="Ruta Norte", descripcion_ruta="Zona alta", zona_geojson=json.dumps([list(p) for p in PUNTOS])
    )

    dialogo = _crear(qtbot, monkeypatch, ruta=ruta)

    assert dialogo._vertices == PUNTOS
    assert dialogo._cerrada is True
    assert dialogo.dibujos[-1] == (PUNTOS, True)
    assert dialogo.nombre_input.text() == "Ruta Norte"
    assert dialogo.lbl_contador.text() == "Zona cerrada — 4 vértices"


def test_get_data_guarda_los_vertices_tal_como_se_marcaron(qtbot, monkeypatch):
    dialogo = _crear(qtbot, monkeypatch)
    dialogo.nombre_input.setText("  Ruta Sur ")
    desordenados = [PUNTOS[0], PUNTOS[2], PUNTOS[1]]
    _marcar(dialogo, desordenados)

    datos = dialogo.get_data()

    assert datos["nombre_ruta"] == "Ruta Sur"
    assert datos["descripcion_ruta"] is None
    assert json.loads(datos["zona_geojson"]) == [list(p) for p in desordenados]


def test_guardar_sin_nombre_avisa_y_no_acepta(qtbot, monkeypatch):
    dialogo = _crear(qtbot, monkeypatch)
    _marcar(dialogo, PUNTOS[:3])

    dialogo._validar_y_aceptar()

    assert dialogo.avisos == [("warning", "El nombre de la ruta es obligatorio.")]
    assert dialogo.result() == 0


def test_guardar_con_menos_de_3_vertices_avisa_y_no_acepta(qtbot, monkeypatch):
    dialogo = _crear(qtbot, monkeypatch)
    dialogo.nombre_input.setText("Ruta")
    _marcar(dialogo, PUNTOS[:2])

    dialogo._validar_y_aceptar()

    assert len(dialogo.avisos) == 1 and "3 vértices" in dialogo.avisos[0][1]
    assert dialogo.result() == 0


def test_guardar_con_zona_valida_acepta(qtbot, monkeypatch):
    dialogo = _crear(qtbot, monkeypatch)
    dialogo.nombre_input.setText("Ruta")
    _marcar(dialogo, PUNTOS[:3])

    dialogo._validar_y_aceptar()

    assert dialogo.avisos == []
    assert dialogo.result() == 1


# --- MapaWidget: lo que el dialogo le pide y lo que el JS le avisa --------------------


def _mapa(qtbot, modo):
    mapa = MapaWidget(editable=True, modo=modo)
    qtbot.addWidget(mapa)
    return mapa


@pytest.mark.parametrize(("cerrada", "literal"), [(True, "true"), (False, "false")])
def test_establecer_zona_le_pasa_al_js_si_la_zona_esta_cerrada(qtbot, monkeypatch, cerrada, literal):
    mapa = _mapa(qtbot, "zona")
    scripts = []
    monkeypatch.setattr(mapa, "_ejecutar", scripts.append)

    mapa.establecer_zona([(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)], cerrada=cerrada)

    assert scripts == [f"establecerZona([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]], {literal});"]


def test_establecer_zona_por_defecto_la_pinta_cerrada(qtbot, monkeypatch):
    """El mapa de rutas (solo lectura) y las zonas guardadas llaman sin `cerrada`: deben verse como poligono."""
    mapa = _mapa(qtbot, "zona")
    scripts = []
    monkeypatch.setattr(mapa, "_ejecutar", scripts.append)

    mapa.establecer_zona([(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)])

    assert scripts[0].endswith(", true);")


def test_el_aviso_de_cierre_del_js_solo_emite_en_modo_zona(qtbot):
    zona = _mapa(qtbot, "zona")
    punto = _mapa(qtbot, "punto")
    emitidas = []
    zona.zona_cerrada_solicitada.connect(lambda: emitidas.append("zona"))
    punto.zona_cerrada_solicitada.connect(lambda: emitidas.append("punto"))

    zona._on_cierre_zona_js()
    punto._on_cierre_zona_js()

    assert emitidas == ["zona"]
