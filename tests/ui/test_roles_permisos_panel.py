"""Roles y permisos: la lista de roles y la matriz se piden en un hilo aparte (ver app/ui/carga_asincrona.py)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.permisos import PermisoDenegadoError
from app.ui import roles_permisos_panel as rpp


@pytest.fixture()
def panel(qtbot):
    panel = rpp.RolesPermisosPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    return panel


def _matriz():
    return [
        {"id_permiso": 1, "recurso": "clientes", "accion": "ver", "descripcion": "", "asignado": True},
        {"id_permiso": 2, "recurso": "clientes", "accion": "crear", "descripcion": "", "asignado": False},
    ]


def test_cargar_pinta_los_roles_y_la_matriz_del_primero(panel, monkeypatch):
    monkeypatch.setattr(
        rpp.RolService,
        "listar_roles",
        lambda session, id_usuario: [
            SimpleNamespace(id_rol=1, nombre="CAJERO"),
            SimpleNamespace(id_rol=2, nombre="ADMIN"),
        ],
    )
    monkeypatch.setattr(rpp.PermisoService, "obtener_matriz_rol", lambda session, id_rol, id_usuario: _matriz())

    panel.cargar()

    assert [panel.lista_roles.item(i).text() for i in range(panel.lista_roles.count())] == ["CAJERO", "ADMIN"]
    assert panel.lbl_titulo_matriz.text() == "Permisos de CAJERO"
    assert set(panel._checkboxes) == {1, 2}
    assert panel._checkboxes[1].isChecked() and not panel._checkboxes[2].isChecked()


def test_el_rol_seleccionado_se_conserva_al_recargar(panel, monkeypatch):
    roles = [SimpleNamespace(id_rol=1, nombre="CAJERO"), SimpleNamespace(id_rol=2, nombre="VENDEDOR")]
    monkeypatch.setattr(rpp.RolService, "listar_roles", lambda session, id_usuario: roles)
    monkeypatch.setattr(rpp.PermisoService, "obtener_matriz_rol", lambda session, id_rol, id_usuario: _matriz())
    panel.cargar()
    panel.lista_roles.setCurrentRow(1)

    panel.cargar()

    assert panel.lista_roles.currentItem().text() == "VENDEDOR"
    assert panel.lbl_titulo_matriz.text() == "Permisos de VENDEDOR"


def test_sin_permiso_avisa_y_no_revienta(panel, monkeypatch):
    def denegar(session, id_usuario):
        raise PermisoDenegadoError("sin permiso")

    avisos = []
    monkeypatch.setattr(rpp.RolService, "listar_roles", denegar)
    monkeypatch.setattr(rpp.MessageBox, "warning", lambda *a, **k: avisos.append(a[1]))

    panel.cargar()

    assert avisos == ["Sin permiso"]
    assert panel.lista_roles.count() == 0
