"""Efectos de FacturaFormDialog: la linea agregada y el total se resaltan un momento, y el boton Facturar muestra
un icono que gira mientras se emite. Mismos dobles que tests/ui/test_factura_form_dialog.py (el __init__ del dialogo
consulta varios catalogos: se parchean a resultados vacios)."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication

import app.ui.factura_form_dialog as ffd
from app.ui import animaciones
from app.ui.animaciones import _Destello


def _crear_dialogo(qtbot, monkeypatch):
    producto = SimpleNamespace(
        id_producto=1,
        cod_producto="P-1",
        nombre_producto="Producto uno",
        cantidad_unidad=Decimal("100"),
        cantidad_caja=Decimal("0"),
        cantidad_caja_total=Decimal("0"),
        estado_producto="ACTIVO",
        articulo_bcv=False,
    )
    precio = SimpleNamespace(precio_1=10.0, precio_2=None, precio_3=None, precio_venta=10.0)
    monkeypatch.setattr(ffd, "list_clientes", lambda *a, **k: {"items": []})
    monkeypatch.setattr(ffd.VendedorService, "listar", staticmethod(lambda *a, **k: {"items": []}))
    monkeypatch.setattr(ffd.ProductoService, "buscar", staticmethod(lambda *a, **k: {"items": [producto]}))
    monkeypatch.setattr(ffd.PrecioService, "obtener_precio", staticmethod(lambda *a, **k: precio))
    monkeypatch.setattr(ffd.TasaService, "obtener_tasa_actual", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(ffd.EmpresaService, "obtener_iva_vigente", staticmethod(lambda *a: (False, Decimal("0"))))
    monkeypatch.setattr(ffd.CajaService, "listar_cajas", staticmethod(lambda *a, **k: []))
    monkeypatch.setattr(ffd.BancoService, "listar_cuentas", staticmethod(lambda *a, **k: []))
    session = MagicMock()
    session.get.return_value = None
    dialogo = ffd.FacturaFormDialog(session, id_usuario=1)
    qtbot.addWidget(dialogo)
    return dialogo


def test_agregar_un_item_resalta_la_fila_y_el_total(qtbot, monkeypatch):
    animaciones.forzar(True)
    dialogo = _crear_dialogo(qtbot, monkeypatch)
    dialogo.show()
    qtbot.waitExposed(dialogo)
    dialogo._agregar_item()
    assert len(dialogo.items) == 1
    assert dialogo.tabla_items.viewport().findChildren(_Destello)
    assert dialogo.lbl_total.findChildren(_Destello)
    qtbot.waitUntil(
        lambda: (
            not dialogo.tabla_items.viewport().findChildren(_Destello) and not dialogo.lbl_total.findChildren(_Destello)
        ),
        timeout=3000,
    )


def test_agregar_el_mismo_item_otra_vez_resalta_la_fila_existente(qtbot, monkeypatch):
    animaciones.forzar(True)
    dialogo = _crear_dialogo(qtbot, monkeypatch)
    dialogo.show()
    qtbot.waitExposed(dialogo)
    dialogo._agregar_item()
    dialogo._agregar_item()
    assert len(dialogo.items) == 1 and dialogo.items[0]["cantidad"] == 2
    assert dialogo.tabla_items.viewport().findChildren(_Destello)


def test_sin_animaciones_agregar_un_item_no_crea_capas(qtbot, monkeypatch):
    dialogo = _crear_dialogo(qtbot, monkeypatch)
    dialogo.show()
    qtbot.waitExposed(dialogo)
    dialogo._agregar_item()
    assert len(dialogo.items) == 1
    assert not dialogo.tabla_items.viewport().findChildren(_Destello)
    assert not dialogo.lbl_total.findChildren(_Destello)


def test_el_boton_facturar_muestra_el_giro_mientras_se_emite(qtbot, monkeypatch):
    animaciones.forzar(True)
    dialogo = _crear_dialogo(qtbot, monkeypatch)
    dialogo._iniciar_emision_ui()
    try:
        assert dialogo.btn_emitir.isEnabled() is False
        assert dialogo.btn_emitir.property("_ocupado") is True
        assert dialogo.btn_cancelar.isEnabled() is False
    finally:
        dialogo._finalizar_emision_ui()
    assert dialogo.btn_emitir.isEnabled() is True
    assert dialogo.btn_emitir.property("_ocupado") is False
    assert dialogo.btn_cancelar.isEnabled() is True
    assert QApplication.overrideCursor() is None
