"""codigo_cliente es autoincremental en SQL (SEQUENCE, migrations/0093) y de solo lectura en
el formulario: ni se puede escribir ni se manda al servicio."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.ui.cliente_form_dialog import ClienteFormDialog
from app.ui.mapa_widget import MapaWidget


@pytest.fixture(autouse=True)
def _sin_carga_del_mapa(monkeypatch):
    """El formulario incrusta un mapa (QWebEngineView) que carga su pagina con
    QTimer.singleShot(0, ...): en el test el dialogo se destruye antes y esa carga cae sobre un
    objeto C++ ya borrado. El mapa no es lo que se prueba aca."""
    monkeypatch.setattr(MapaWidget, "_cargar_pagina", lambda self: None)


def _dialogo(qtbot, cliente=None):
    dialogo = ClienteFormDialog(MagicMock(), cliente=cliente, id_usuario=1)
    qtbot.addWidget(dialogo)
    return dialogo


def test_alta_el_codigo_es_solo_lectura_y_vacio_hasta_guardar(qtbot):
    dialogo = _dialogo(qtbot)

    assert dialogo.codigo_input.isReadOnly()
    assert not dialogo.codigo_input.isEnabled()
    assert dialogo.codigo_input.text() == ""  # no se adelanta un numero: lo asigna SQL al guardar


def test_edicion_muestra_el_codigo_asignado_en_solo_lectura(qtbot):
    cliente = SimpleNamespace(
        codigo_cliente="42",
        id_legal="V",
        identificacion_cliente="12345678",
        nombre_razon_social="Cliente",
        telefono=None,
        email=None,
        direccion=None,
        limite_credito=0,
        dias_credito=0,
        vendedor_cliente=None,
        id_categoria_cliente=None,
        latitud=10.0,
        longitud=-66.0,
    )
    dialogo = _dialogo(qtbot, cliente=cliente)

    assert dialogo.codigo_input.text() == "42"
    assert dialogo.codigo_input.isReadOnly()
    assert not dialogo.codigo_input.isEnabled()


def test_get_data_no_envia_codigo_cliente(qtbot):
    dialogo = _dialogo(qtbot)
    dialogo.nombre_input.setText("Cliente Nuevo")

    assert "codigo_cliente" not in dialogo.get_data()
