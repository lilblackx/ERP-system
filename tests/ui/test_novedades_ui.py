"""Ventana de novedades y bienvenida al entrar (MainWindow.mostrar_bienvenida / mostrar_novedades).

MainWindow real necesita base de datos y arma todos los paneles; aca se llama el metodo con un `self` minimo
(como test_main_window_topbar.py): lo que se prueba es QUE se le muestra a cada usuario, no el armado de la UI."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QLabel

from app.novedades import Cambio, Entrega
from app.ui import main_window as mw
from app.ui.novedades_dialog import NovedadesDialog
from app.ui.toast import Toast
from app.utils import novedades_local
from app.version import VERSION

ENTREGAS = [
    Entrega(
        VERSION,
        "2026-11-06",
        "Entrega de prueba",
        (
            Cambio("nuevo", "Cambio general"),
            Cambio("mejorado", "Cambio de clientes", ("clientes",), destacado=True),
            Cambio("general", "Mejoras de estabilidad y funcionamiento."),
            Cambio("mejorado", "<b>Texto con etiquetas</b>"),
        ),
    )
]


def _textos(dialogo):
    return [lbl.text() for lbl in dialogo.findChildren(QLabel)]


def test_el_dialogo_muestra_version_titulo_y_cada_cambio(qtbot):
    dialogo = NovedadesDialog(ENTREGAS, "Hola, Luis", "Esto es lo nuevo", parent=None)
    qtbot.addWidget(dialogo)

    textos = _textos(dialogo)
    assert "Hola, Luis" in textos and f"Versión {VERSION}" in textos and "06/11/2026" in textos
    assert {"Cambio general", "Cambio de clientes"} <= set(textos)
    assert {"NUEVO", "MEJORADO"} <= set(textos) and "Mejoras de estabilidad y funcionamiento." in textos


def test_el_dialogo_muestra_el_texto_tal_cual_sin_interpretar_html(qtbot):
    dialogo = NovedadesDialog(ENTREGAS, "t", "s", parent=None)
    qtbot.addWidget(dialogo)

    assert "<b>Texto con etiquetas</b>" in _textos(dialogo)


def test_entendido_cierra_el_dialogo(qtbot):
    dialogo = NovedadesDialog(ENTREGAS, "t", "s", parent=None)
    qtbot.addWidget(dialogo)
    dialogo.show()

    dialogo.btn_entendido.click()

    assert not dialogo.isVisible()


# -- orquestacion en MainWindow --------------------


@pytest.fixture
def entorno(monkeypatch):
    """`self` minimo + dobles de lo que toca la base de datos / la pantalla."""
    espia = SimpleNamespace(dialogos=[], toasts=[])

    class DialogoFalso:
        def __init__(self, entregas, titulo, subtitulo, parent=None):
            espia.dialogos.append((entregas, titulo, subtitulo))

        def exec(self):
            return 1

    monkeypatch.setattr(mw, "NovedadesDialog", DialogoFalso)
    monkeypatch.setattr(mw, "SessionLocal", MagicMock())
    monkeypatch.setattr(mw, "es_primer_ingreso", lambda _s, _id: espia.primer)
    monkeypatch.setattr(mw, "cargar_entregas", lambda: ENTREGAS)
    monkeypatch.setattr(
        mw.Toast,
        "mostrar",
        lambda parent, titulo, texto="", tipo="exito", **kw: espia.toasts.append(
            (titulo, texto, tipo, kw.get("inicial"))
        ),
    )
    espia.primer = False
    espia.ventana = SimpleNamespace(
        usuario=SimpleNamespace(id_usuario=7, nombre="luis fernando", nombre_usuario="lfernandez"),
        _modulos_visibles=None,
    )
    return espia


def test_tras_actualizar_abre_las_novedades_y_recuerda_la_version(entorno):
    novedades_local.marcar_version_vista(7, "0.9.0")

    mw.MainWindow.mostrar_bienvenida(entorno.ventana)

    assert len(entorno.dialogos) == 1 and entorno.dialogos[0][1] == "Hola, Luis"
    assert entorno.toasts == []
    assert novedades_local.ultima_version_vista(7) == VERSION


def test_en_la_misma_version_solo_saluda_con_un_aviso_que_se_quita_solo(entorno):
    novedades_local.marcar_version_vista(7, VERSION)

    mw.MainWindow.mostrar_bienvenida(entorno.ventana)

    assert entorno.dialogos == []
    ((titulo, texto, tipo, inicial),) = entorno.toasts
    assert titulo.endswith(", Luis") and texto == "Bienvenido de nuevo" and tipo == "saludo" and inicial == "Luis"


def test_primer_ingreso_saluda_y_no_muestra_el_historial(entorno):
    entorno.primer = True

    mw.MainWindow.mostrar_bienvenida(entorno.ventana)

    assert entorno.dialogos == []
    assert entorno.toasts[0][0] == "¡Bienvenido, Luis!"
    assert novedades_local.ultima_version_vista(7) == VERSION  # no se le mostraran las de esta version despues


def test_un_fallo_al_mostrar_la_bienvenida_no_rompe_la_app(entorno, monkeypatch):
    monkeypatch.setattr(mw, "cargar_entregas", MagicMock(side_effect=RuntimeError("boom")))

    mw.MainWindow.mostrar_bienvenida(entorno.ventana)  # no debe lanzar

    assert entorno.dialogos == [] and entorno.toasts == []


def test_el_rol_sin_modulos_afectados_recibe_solo_el_saludo(entorno, monkeypatch):
    novedades_local.marcar_version_vista(7, "0.9.0")
    entorno.ventana._modulos_visibles = {"cajas"}
    solo_clientes = [Entrega(VERSION, "2026-11-06", "x", (Cambio("nuevo", "Solo clientes", ("clientes",)),))]
    monkeypatch.setattr(mw, "cargar_entregas", lambda: solo_clientes)

    mw.MainWindow.mostrar_bienvenida(entorno.ventana)

    assert entorno.dialogos == [] and len(entorno.toasts) == 1


def test_el_toast_de_saludo_se_crea_y_se_cierra(qtbot):
    toast = Toast.mostrar(None, "Buenos días, Luis", "Bienvenido de nuevo", "saludo", duracion_ms=50)

    assert toast.lbl_titulo.text() == "Buenos días, Luis"
    qtbot.waitUntil(lambda: Toast._actual is None, timeout=3000)


def test_todos_los_tipos_de_toast_comparten_el_mismo_diseno(qtbot):
    """El componente es global: el tipo solo cambia el color y el glifo, nunca la estructura (sin franja lateral)."""
    for tipo in ("exito", "aviso", "error", "saludo"):
        toast = Toast(None, "Titulo", "Texto", tipo, "Luis" if tipo == "saludo" else None)
        qtbot.addWidget(toast)
        hoja = toast.findChild(object, "ToastCard").styleSheet()
        assert "border-left" not in hoja, tipo
