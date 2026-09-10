"""Tests de los dialogos de app/ui/compras.py tras migrar sus QDoubleSpinBox a
NumericLineEdit. A diferencia de factura_form_dialog.py, aca SI hay tablas dinamicas con
un NumericLineEdit real por fila (NotaRecepcionFormDialog, NotaDevolucionFormDialog,
CompraDesdeOCFormDialog) -- el foco de estos tests es la eleccion de decimals/rango/
tope-dinamico por columna real:

- OrdenCompraFormDialog.cantidad_input/precio_input y EnmiendaOCDialog.
  cantidad_nueva_input/precio_nuevo_input -> compra_oc/compra_oc_detalle, Numeric(18,4)
  ambos (cantidad Y precio) -- decimals=4, NO el default de 2 (ver app/db/models.py).
- NotaRecepcionFormDialog (spin_recibida/spin_rechazada) y NotaDevolucionFormDialog (spin)
  -> nota_recepcion_detalle/nota_devolucion_detalle, tambien Numeric(18,4) -- decimals=4.
- CompraDesdeOCFormDialog (spin "Cant. a Facturar") -> termina en
  CompraDetalle.cantidad_producto, que es Numeric(12,2) (NO el 18,4 de la OC) --
  decimals=2, el default de QUANTITY.

Cada dialogo hace sus propias consultas en el constructor (CompraOCService.obtener_oc,
NotaRecepcionService.obtener_nota_recepcion, ProveedorService.listar, ProductoService.
buscar) -- se monkeypatchean directo en vez de armar cadenas de mock de session.query(),
que no son el objeto de estos tests (los widgets numericos)."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import app.ui.compras as compras_mod
from app.ui.compras import (
    CompraDesdeOCFormDialog,
    EnmiendaOCDialog,
    NotaDevolucionFormDialog,
    NotaRecepcionFormDialog,
    OrdenCompraFormDialog,
)


def _dar_foco(qtbot, campo):
    campo.window().show()
    qtbot.waitExposed(campo.window())
    campo.setFocus()
    qtbot.waitUntil(campo.hasFocus)


def _escribir_y_perder_foco(qtbot, campo, texto):
    _dar_foco(qtbot, campo)
    qtbot.keyClicks(campo, texto)
    campo.clearFocus()


def _detalle_oc(id_detalle=1, cantidad_pendiente=Decimal("50.1234"), nombre="Producto Uno"):
    return SimpleNamespace(
        id_detalle=id_detalle,
        cantidad_pendiente=cantidad_pendiente,
        producto=SimpleNamespace(nombre_producto=nombre),
    )


# =============================================================================
# OrdenCompraFormDialog: cantidad_input/precio_input -- compra_oc_detalle Numeric(18,4)
# =============================================================================


def _crear_orden_compra_dialogo(qtbot, monkeypatch, productos=None):
    monkeypatch.setattr(compras_mod.ProveedorService, "listar", staticmethod(lambda *a, **k: {"items": []}))
    monkeypatch.setattr(compras_mod.ProductoService, "buscar", staticmethod(lambda *a, **k: {"items": productos or []}))
    dialogo = OrdenCompraFormDialog(MagicMock(), id_usuario=1)
    qtbot.addWidget(dialogo)
    return dialogo


def test_orden_compra_cantidad_input_preserva_4_decimales(qtbot, monkeypatch):
    dialogo = _crear_orden_compra_dialogo(qtbot, monkeypatch)
    _escribir_y_perder_foco(qtbot, dialogo.cantidad_input, "12,3456")
    assert dialogo.cantidad_input.get_value() == Decimal("12.3456")
    assert dialogo.cantidad_input.text() == "12,3456"


def test_orden_compra_precio_input_preserva_4_decimales_con_prefijo(qtbot, monkeypatch):
    dialogo = _crear_orden_compra_dialogo(qtbot, monkeypatch)
    _escribir_y_perder_foco(qtbot, dialogo.precio_input, "1000,1234")
    assert dialogo.precio_input.get_value() == Decimal("1000.1234")
    assert dialogo.precio_input.text() == "$ 1.000,1234"


def test_orden_compra_cantidad_y_precio_no_admiten_cero(qtbot, monkeypatch):
    dialogo = _crear_orden_compra_dialogo(qtbot, monkeypatch)
    _escribir_y_perder_foco(qtbot, dialogo.cantidad_input, "0")
    assert dialogo.cantidad_input.get_value() == Decimal("0.01")
    _escribir_y_perder_foco(qtbot, dialogo.precio_input, "0")
    assert dialogo.precio_input.get_value() == Decimal("0.01")


def test_orden_compra_agregar_item_conserva_precision_decimal(qtbot, monkeypatch):
    producto = SimpleNamespace(
        id_producto=1, cod_producto="P1", nombre_producto="Producto Uno", costo_producto=None, estado_producto="ACTIVO"
    )
    dialogo = _crear_orden_compra_dialogo(qtbot, monkeypatch, productos=[producto])
    indice = dialogo.producto_combo.findData(1)
    dialogo.producto_combo.setCurrentIndex(indice)
    _escribir_y_perder_foco(qtbot, dialogo.cantidad_input, "2,5")
    _escribir_y_perder_foco(qtbot, dialogo.precio_input, "10,1234")

    dialogo._agregar_item()

    assert len(dialogo.items) == 1
    assert dialogo.items[0]["cantidad"] == Decimal("2.5")
    assert dialogo.items[0]["precio"] == Decimal("10.1234")


def test_orden_compra_crear_oc_recibe_items_con_precision_de_4_decimales(qtbot, monkeypatch):
    producto = SimpleNamespace(
        id_producto=1, cod_producto="P1", nombre_producto="Producto Uno", costo_producto=None, estado_producto="ACTIVO"
    )
    dialogo = _crear_orden_compra_dialogo(qtbot, monkeypatch, productos=[producto])
    dialogo.proveedor_combo.addItem("Proveedor Test", 9)
    dialogo.proveedor_combo.setCurrentIndex(dialogo.proveedor_combo.findData(9))
    indice = dialogo.producto_combo.findData(1)
    dialogo.producto_combo.setCurrentIndex(indice)
    _escribir_y_perder_foco(qtbot, dialogo.cantidad_input, "2,5")
    _escribir_y_perder_foco(qtbot, dialogo.precio_input, "10,1234")
    dialogo._agregar_item()

    llamada = {}

    def _crear_oc_fake(session, id_proveedor, items, **kwargs):
        llamada["items"] = items
        return SimpleNamespace(id_oc=1)

    monkeypatch.setattr(compras_mod.CompraOCService, "crear_oc", staticmethod(_crear_oc_fake))
    dialogo._validar_y_aceptar()

    assert llamada["items"][0]["cantidad_solicitada"] == Decimal("2.5")
    assert llamada["items"][0]["precio_unitario"] == Decimal("10.1234")


# =============================================================================
# EnmiendaOCDialog: cantidad_nueva_input/precio_nuevo_input -- Numeric(18,4)
# =============================================================================


def _crear_enmienda_dialogo(qtbot, cantidad_solicitada=Decimal("100.0000")):
    oc = SimpleNamespace(id_oc=1, numero_oc="OC-001", cantidad_solicitada=cantidad_solicitada)
    dialogo = EnmiendaOCDialog(MagicMock(), id_usuario=1, oc=oc)
    qtbot.addWidget(dialogo)
    return dialogo, oc


def test_enmienda_cantidad_nueva_precargada_desde_oc(qtbot):
    dialogo, oc = _crear_enmienda_dialogo(qtbot, cantidad_solicitada=Decimal("55.1234"))
    assert dialogo.cantidad_nueva_input.get_value() == Decimal("55.1234")


def test_enmienda_precio_nuevo_preserva_4_decimales(qtbot):
    dialogo, _oc = _crear_enmienda_dialogo(qtbot)
    # precio_nuevo_input arranca oculto (_toggle_campos): solo se muestra, y por lo tanto
    # solo puede tomar foco, cuando tipo_combo esta en "PRECIO".
    dialogo.tipo_combo.setCurrentIndex(dialogo.tipo_combo.findData("PRECIO"))
    _escribir_y_perder_foco(qtbot, dialogo.precio_nuevo_input, "250,6789")
    assert dialogo.precio_nuevo_input.get_value() == Decimal("250.6789")
    assert dialogo.precio_nuevo_input.text() == "$ 250,6789"


def test_enmienda_crear_enmienda_recibe_decimal_de_4_cifras(qtbot, monkeypatch):
    dialogo, _oc = _crear_enmienda_dialogo(qtbot)
    dialogo.tipo_combo.setCurrentIndex(dialogo.tipo_combo.findData("PRECIO"))
    _escribir_y_perder_foco(qtbot, dialogo.precio_nuevo_input, "77,4321")
    dialogo.motivo_input.setText("Ajuste acordado con el proveedor")

    llamada = {}

    def _crear_enmienda_fake(session, **kwargs):
        llamada.update(kwargs)
        return SimpleNamespace(id_enmienda=1)

    monkeypatch.setattr(compras_mod.CompraOCService, "crear_enmienda", staticmethod(_crear_enmienda_fake))
    monkeypatch.setattr(compras_mod.UsuarioService, "verificar_permiso", staticmethod(lambda *a, **k: False))
    dialogo._validar_y_aceptar()

    assert llamada["precio_nuevo"] == Decimal("77.4321")


# =============================================================================
# NotaRecepcionFormDialog: spin_recibida/spin_rechazada -- nota_recepcion_detalle
# Numeric(18,4), con tope dinamico (spin_rechazada <= spin_recibida)
# =============================================================================


def _crear_recepcion_dialogo(qtbot, monkeypatch, detalles=None):
    detalles = detalles if detalles is not None else [_detalle_oc()]
    monkeypatch.setattr(compras_mod.CompraOCService, "obtener_oc", staticmethod(lambda *a, **k: {"detalles": detalles}))
    oc = SimpleNamespace(id_oc=1, numero_oc="OC-001")
    dialogo = NotaRecepcionFormDialog(MagicMock(), id_usuario=1, oc=oc)
    qtbot.addWidget(dialogo)
    return dialogo


def test_recepcion_spin_recibida_tope_es_cantidad_pendiente(qtbot, monkeypatch):
    dialogo = _crear_recepcion_dialogo(
        qtbot, monkeypatch, detalles=[_detalle_oc(cantidad_pendiente=Decimal("50.1234"))]
    )
    spin = dialogo._spins_recibida[0]
    assert spin.max_value == Decimal("50.1234")
    assert spin.decimals == 4
    _escribir_y_perder_foco(qtbot, spin, "999")
    assert spin.get_value() == Decimal("50.1234")


def test_recepcion_spin_rechazada_arranca_topeado_en_cero(qtbot, monkeypatch):
    dialogo = _crear_recepcion_dialogo(qtbot, monkeypatch)
    spin_rechazada = dialogo._spins_rechazada[0]
    assert spin_rechazada.max_value == Decimal("0")
    assert spin_rechazada.decimals == 4


def test_recepcion_subir_recibida_sube_el_tope_de_rechazada(qtbot, monkeypatch):
    dialogo = _crear_recepcion_dialogo(
        qtbot, monkeypatch, detalles=[_detalle_oc(cantidad_pendiente=Decimal("50.1234"))]
    )
    spin_recibida = dialogo._spins_recibida[0]
    spin_rechazada = dialogo._spins_rechazada[0]
    _escribir_y_perder_foco(qtbot, spin_recibida, "20,5")

    assert spin_rechazada.max_value == Decimal("20.5")


def test_recepcion_bajar_recibida_reclama_el_valor_de_rechazada_si_excede(qtbot, monkeypatch):
    dialogo = _crear_recepcion_dialogo(
        qtbot, monkeypatch, detalles=[_detalle_oc(cantidad_pendiente=Decimal("50.1234"))]
    )
    spin_recibida = dialogo._spins_recibida[0]
    spin_rechazada = dialogo._spins_rechazada[0]
    _escribir_y_perder_foco(qtbot, spin_recibida, "30")
    _escribir_y_perder_foco(qtbot, spin_rechazada, "25")
    assert spin_rechazada.get_value() == Decimal("25.0000")

    # Bajar la recibida por debajo de lo ya cargado en rechazada debe reclamar (clampear)
    # el valor de rechazada -- igual que hacia QDoubleSpinBox.setRange() automaticamente.
    _escribir_y_perder_foco(qtbot, spin_recibida, "10")
    assert spin_rechazada.max_value == Decimal("10")
    assert spin_rechazada.get_value() == Decimal("10")


def test_recepcion_validar_y_aceptar_envia_decimales_de_4_cifras(qtbot, monkeypatch):
    dialogo = _crear_recepcion_dialogo(
        qtbot, monkeypatch, detalles=[_detalle_oc(cantidad_pendiente=Decimal("50.1234"))]
    )
    _escribir_y_perder_foco(qtbot, dialogo._spins_recibida[0], "40,5")
    _escribir_y_perder_foco(qtbot, dialogo._spins_rechazada[0], "5,25")

    llamada = {}

    def _crear_nr_fake(session, **kwargs):
        llamada.update(kwargs)
        return SimpleNamespace(id_nr=1)

    monkeypatch.setattr(compras_mod.NotaRecepcionService, "crear_nota_recepcion", staticmethod(_crear_nr_fake))
    dialogo._validar_y_aceptar()

    item = llamada["items"][0]
    assert item["cantidad_recibida"] == Decimal("40.5")
    assert item["cantidad_rechazada"] == Decimal("5.25")


# =============================================================================
# NotaDevolucionFormDialog: spin -- nota_devolucion_detalle Numeric(18,4)
# =============================================================================


def _crear_devolucion_dialogo(qtbot, monkeypatch, disponible=Decimal("50.1234")):
    detalle = SimpleNamespace(
        id_producto=1,
        cantidad_rechazada=disponible,
        producto=SimpleNamespace(nombre_producto="Producto Uno"),
    )
    monkeypatch.setattr(
        compras_mod.NotaRecepcionService,
        "obtener_nota_recepcion",
        staticmethod(lambda *a, **k: {"detalles": [detalle]}),
    )
    session = MagicMock()
    session.query.return_value.join.return_value.filter.return_value.all.return_value = []
    nr = SimpleNamespace(id_nr=1, numero_nr="NR-001")
    dialogo = NotaDevolucionFormDialog(session, id_usuario=1, nr=nr)
    qtbot.addWidget(dialogo)
    return dialogo


def test_devolucion_spin_tope_es_disponible_con_4_decimales(qtbot, monkeypatch):
    dialogo = _crear_devolucion_dialogo(qtbot, monkeypatch, disponible=Decimal("50.1234"))
    spin = dialogo._spins[0]
    assert spin.max_value == Decimal("50.1234")
    assert spin.decimals == 4
    _escribir_y_perder_foco(qtbot, spin, "999")
    assert spin.get_value() == Decimal("50.1234")


def test_devolucion_validar_y_aceptar_envia_decimal_de_4_cifras(qtbot, monkeypatch):
    dialogo = _crear_devolucion_dialogo(qtbot, monkeypatch, disponible=Decimal("50.1234"))
    _escribir_y_perder_foco(qtbot, dialogo._spins[0], "12,3456")

    llamada = {}

    def _crear_devolucion_fake(session, **kwargs):
        llamada.update(kwargs)
        return SimpleNamespace(id_devolucion=1)

    monkeypatch.setattr(compras_mod.NotaRecepcionService, "crear_nota_devolucion", staticmethod(_crear_devolucion_fake))
    dialogo._validar_y_aceptar()

    assert llamada["items"][0]["cantidad_devuelta"] == Decimal("12.3456")


# =============================================================================
# CompraDesdeOCFormDialog: spin "Cant. a Facturar" -- CompraDetalle.cantidad_producto
# Numeric(12,2), NO el 18,4 de la OC -- decimals=2, el default de QUANTITY.
# =============================================================================


def _crear_compra_desde_oc_dialogo(qtbot, monkeypatch, disponible=Decimal("10.50"), precio_unitario=Decimal("5.00")):
    detalle = SimpleNamespace(
        id_detalle=1,
        cantidad_recibida=disponible,
        cantidad_facturada=Decimal("0"),
        precio_unitario=precio_unitario,
        producto=SimpleNamespace(nombre_producto="Producto Uno"),
    )
    monkeypatch.setattr(
        compras_mod.CompraOCService, "obtener_oc", staticmethod(lambda *a, **k: {"detalles": [detalle]})
    )
    oc = SimpleNamespace(id_oc=1, numero_oc="OC-001")
    dialogo = CompraDesdeOCFormDialog(MagicMock(), id_usuario=1, oc=oc)
    qtbot.addWidget(dialogo)
    return dialogo


def test_compra_desde_oc_spin_decimals_es_2_no_4(qtbot, monkeypatch):
    dialogo = _crear_compra_desde_oc_dialogo(qtbot, monkeypatch)
    spin = dialogo._spins[0]
    assert spin.decimals == 2


def test_compra_desde_oc_spin_arranca_en_el_disponible(qtbot, monkeypatch):
    dialogo = _crear_compra_desde_oc_dialogo(qtbot, monkeypatch, disponible=Decimal("10.50"))
    spin = dialogo._spins[0]
    assert spin.get_value() == Decimal("10.50")
    assert spin.max_value == Decimal("10.50")


def test_compra_desde_oc_validar_y_aceptar_envia_decimal(qtbot, monkeypatch):
    dialogo = _crear_compra_desde_oc_dialogo(qtbot, monkeypatch, disponible=Decimal("10.50"))
    dialogo.condicion_combo.setCurrentIndex(dialogo.condicion_combo.findData("credito"))

    llamada = {}

    def _crear_compra_fake(session, **kwargs):
        llamada.update(kwargs)
        return SimpleNamespace(id_compra=1)

    monkeypatch.setattr(compras_mod.CompraService, "crear_compra_desde_oc", staticmethod(_crear_compra_fake))
    dialogo._validar_y_aceptar()

    assert llamada["items"][0]["cantidad"] == Decimal("10.50")
