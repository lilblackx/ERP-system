"""Permisos de los botones de escritura de InventarioPanel (app/ui/inventario_panel.py).

Bug real: el panel solo ocultaba "Nuevo Producto" a los vendedores. Un CAJERO (inventario:ver, sin
crear/editar/eliminar) veia el boton, y al pulsarlo se abria el formulario completo -- con un aviso
de "sin permiso" de categorias dentro del propio formulario -- y recien al guardar fallaba. Ahora el
boton no aparece sin el permiso y, aunque se llegue al handler, se avisa ANTES de abrir el
formulario. Se usan permisos y usuarios reales (db_session), no mocks: lo que se prueba es la matriz."""

import pytest
from PySide6.QtWidgets import QPushButton
from sqlalchemy.orm import sessionmaker

import app.ui.inventario_panel as inv
from app.db.models import Permiso, RolPermiso
from app.services.permisos import PermisoDenegadoError
from tests.factories import (
    asignar_permiso,
    crear_permiso,
    crear_rol,
    crear_usuario,
    crear_usuario_admin,
    crear_vendedor,
)


def _rol_con_permisos(db_session, *acciones):
    """Rol con inventario:<accion> para cada accion pedida (siempre incluye 'ver')."""
    rol = crear_rol(db_session)
    for accion in {"ver", *acciones}:
        # (recurso, accion) es unico en el catalogo: se reutiliza el permiso si otro rol ya lo creo.
        permiso = db_session.query(Permiso).filter_by(recurso="inventario", accion=accion).first()
        asignar_permiso(db_session, rol, permiso or crear_permiso(db_session, recurso="inventario", accion=accion))
    return rol


def _panel(qtbot, db_session, usuario):
    fabrica = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)
    panel = inv.InventarioPanel(fabrica, usuario)
    qtbot.addWidget(panel)
    return panel


def _botones(panel) -> set[str]:
    return {boton.text() for boton in panel.findChildren(QPushButton)}


@pytest.fixture()
def avisos(monkeypatch):
    recibidos = []
    monkeypatch.setattr(inv.MessageBox, "warning", lambda parent, titulo, texto: recibidos.append((titulo, texto)))
    return recibidos


@pytest.fixture()
def sin_formulario(monkeypatch):
    """Cualquier intento de abrir el formulario de producto hace fallar el test."""

    def fallar(*args, **kwargs):
        pytest.fail("no debe abrir el formulario de producto")

    monkeypatch.setattr(inv, "ProductoFormDialog", fallar)


# -- Botones visibles segun el rol --------------------------------------------------------


def test_cajero_solo_con_ver_no_ve_nuevo_editar_ni_cambiar_estado(qtbot, db_session):
    usuario = crear_usuario(db_session, id_rol=_rol_con_permisos(db_session).id_rol)

    panel = _panel(qtbot, db_session, usuario)

    assert (panel.puede_crear, panel.puede_editar, panel.puede_cambiar_estado) == (False, False, False)
    botones = _botones(panel)
    assert not {"Nuevo Producto", "Editar seleccionado", "Cambiar estado"} & botones


def test_admin_ve_los_tres_botones_de_escritura(qtbot, db_session):
    panel = _panel(qtbot, db_session, crear_usuario_admin(db_session))

    assert {"Nuevo Producto", "Editar seleccionado", "Cambiar estado"} <= _botones(panel)


def test_cada_boton_aparece_solo_con_su_permiso(qtbot, db_session):
    solo_crear = crear_usuario(db_session, id_rol=_rol_con_permisos(db_session, "crear").id_rol)
    solo_editar = crear_usuario(db_session, id_rol=_rol_con_permisos(db_session, "editar").id_rol)
    solo_eliminar = crear_usuario(db_session, id_rol=_rol_con_permisos(db_session, "eliminar").id_rol)

    botones_crear = _botones(_panel(qtbot, db_session, solo_crear))
    botones_editar = _botones(_panel(qtbot, db_session, solo_editar))
    botones_eliminar = _botones(_panel(qtbot, db_session, solo_eliminar))

    escritura = {"Nuevo Producto", "Editar seleccionado", "Cambiar estado"}
    assert escritura & botones_crear == {"Nuevo Producto"}
    assert escritura & botones_editar == {"Editar seleccionado"}
    assert escritura & botones_eliminar == {"Cambiar estado"}


def test_un_vendedor_no_ve_botones_de_escritura_aunque_su_rol_tenga_el_permiso(qtbot, db_session):
    vendedor = crear_vendedor(db_session)
    rol = _rol_con_permisos(db_session, "crear", "editar", "eliminar")
    usuario = crear_usuario(db_session, id_rol=rol.id_rol, id_vendedor_usuario=vendedor.id_vendedor)

    panel = _panel(qtbot, db_session, usuario)

    assert not {"Nuevo Producto", "Editar seleccionado", "Cambiar estado"} & _botones(panel)


# -- Handlers: aviso ANTES de abrir el formulario ----------------------------------------------


def test_nuevo_producto_sin_permiso_avisa_y_no_abre_el_formulario(qtbot, db_session, avisos, sin_formulario):
    usuario = crear_usuario(db_session, id_rol=_rol_con_permisos(db_session).id_rol)
    panel = _panel(qtbot, db_session, usuario)

    panel.nuevo_producto()

    assert avisos == [("Sin permiso", "No tienes permiso para crear productos.")]


def test_nuevo_producto_si_se_quita_el_permiso_con_la_pantalla_abierta_tambien_avisa(
    qtbot, db_session, avisos, sin_formulario
):
    rol = _rol_con_permisos(db_session, "crear")
    usuario = crear_usuario(db_session, id_rol=rol.id_rol)
    panel = _panel(qtbot, db_session, usuario)
    assert panel.puede_crear

    permiso_crear = next(
        rp for rp in db_session.query(RolPermiso).filter_by(id_rol=rol.id_rol) if rp.permiso.accion == "crear"
    )
    db_session.delete(permiso_crear)
    db_session.commit()

    panel.nuevo_producto()

    assert [titulo for titulo, _ in avisos] == ["Sin permiso"]


def test_editar_producto_sin_permiso_avisa_y_no_abre_el_formulario(qtbot, db_session, avisos, sin_formulario):
    usuario = crear_usuario(db_session, id_rol=_rol_con_permisos(db_session).id_rol)
    panel = _panel(qtbot, db_session, usuario)
    panel._fila_seleccionada_id = lambda: 1

    panel.editar_producto()

    assert avisos == [("Sin permiso", "No tienes permiso para editar productos.")]


def test_cambiar_estado_sin_permiso_avisa_y_no_pide_confirmacion(qtbot, db_session, avisos, monkeypatch):
    usuario = crear_usuario(db_session, id_rol=_rol_con_permisos(db_session, "editar").id_rol)
    panel = _panel(qtbot, db_session, usuario)
    panel._fila_seleccionada_id = lambda: 1
    monkeypatch.setattr(inv.MessageBox, "question", lambda *a, **k: pytest.fail("no debe pedir confirmacion"))

    panel.cambiar_estado_producto_seleccionado()

    assert avisos == [("Sin permiso", "No tienes permiso para cambiar el estado de productos.")]


def test_nuevo_producto_si_el_servicio_deniega_al_guardar_avisa_sin_romper(qtbot, db_session, avisos, monkeypatch):
    usuario = crear_usuario_admin(db_session)
    panel = _panel(qtbot, db_session, usuario)

    class FormularioFalso:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return 1

        def get_data(self):
            return {"nombre_producto": "X"}

    def denegar(*args, **kwargs):
        raise PermisoDenegadoError("sin permiso")

    monkeypatch.setattr(inv, "ProductoFormDialog", FormularioFalso)
    monkeypatch.setattr(inv.ProductoService, "crear", staticmethod(denegar))

    panel.nuevo_producto()

    assert avisos == [("Sin permiso", "No tienes permiso para crear productos.")]
