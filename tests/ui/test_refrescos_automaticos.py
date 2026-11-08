"""Los refrescos de 30 s de Facturacion, Inventario y Compras cargan en un hilo aparte: la ventana no se detiene
mientras la base responde. Cada panel pasa `al_terminar` para que AutoRefresco vuelva a seleccionar la fila."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import app.ui.compras as compras_mod
import app.ui.inventario_panel as inv


def _registrar_cargas(monkeypatch, clase):
    cargas = []
    monkeypatch.setattr(clase, "cargar_async", lambda self, clave, *a, **k: cargas.append((clave, k)))
    return cargas


def test_el_refresco_del_inventario_carga_en_un_hilo_y_avisa_al_terminar(qtbot, monkeypatch):
    cargas = _registrar_cargas(monkeypatch, inv.InventarioPanel)
    panel = inv.InventarioPanel(MagicMock(), SimpleNamespace(id_usuario=1, id_vendedor_usuario=None))
    qtbot.addWidget(panel)
    aviso = MagicMock()

    panel._refresco_periodico(aviso)

    clave, kwargs = cargas[-1]
    assert clave == "productos" and kwargs["al_terminar"] is aviso
    assert not kwargs["sincrono"] and kwargs["silencioso"] is True
    assert panel._auto_refresco._asincrono is True


def test_el_refresco_de_compras_carga_solo_la_pestana_visible_en_un_hilo(qtbot, monkeypatch):
    cargas = _registrar_cargas(monkeypatch, compras_mod.ComprasView)
    monkeypatch.setattr(compras_mod.MessageBox, "critical", lambda *a, **k: None)
    panel = compras_mod.ComprasView(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    aviso = MagicMock()

    for indice, clave in enumerate(("oc", "nr", "compra")):
        panel.tabs.setCurrentIndex(indice)
        cargas.clear()
        panel._refresco_periodico(aviso)
        assert [c for c, _ in cargas] == [clave]
        assert cargas[0][1]["al_terminar"] is aviso and not cargas[0][1]["sincrono"]
    assert panel._auto_refresco._asincrono is True
