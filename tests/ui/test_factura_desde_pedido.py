"""FacturaFormDialog con un pedido APROBADO (parametro `pedido`) y con stock apartado por pedidos.

Contra SQL Server real: lo que importa es que lo que arma el formulario (get_data) sea justo lo que emitir_factura
necesita para cerrar el pedido, y que el selector de productos hable del stock DISPONIBLE, no del real.
"""

from decimal import Decimal

import pytest

import app.ui.factura_form_dialog as ffd
from app.db.models import FacturaVenta, Pedido
from app.services.pedidos import PedidoService
from tests.factories import crear_vendedor, pago_contado
from tests.services.test_pedidos import _crear, _escenario


@pytest.fixture()
def avisos(monkeypatch):
    registro = []
    for tipo in ("information", "warning", "critical"):
        monkeypatch.setattr(
            ffd.MessageBox,
            tipo,
            staticmethod(lambda parent, titulo, texto, _t=tipo: registro.append((_t, titulo, texto))),
        )
    return registro


def _pedido_aprobado(db, esc, **kw):
    pedido = _crear(db, esc, **kw)
    PedidoService.aprobar_pedido(db, pedido.id_pedido, esc.admin.id_usuario)
    return pedido, PedidoService.datos_para_facturar(db, pedido.id_pedido, esc.admin.id_usuario)


def _dialogo(qtbot, db, esc, pedido=None):
    dialogo = ffd.FacturaFormDialog(db, esc.admin.id_usuario, pedido=pedido)
    qtbot.addWidget(dialogo)
    return dialogo


# -- Factura de un pedido -----------------------------------------------------------------------------------------


def test_el_formulario_sale_con_el_cliente_vendedor_condicion_y_lineas_del_pedido(qtbot, db_session):
    esc = _escenario(db_session)
    pedido, datos = _pedido_aprobado(db_session, esc, cantidad=5, observaciones="Entregar en la tarde")

    dialogo = _dialogo(qtbot, db_session, esc, datos)

    assert pedido.numero_pedido in dialogo.windowTitle()
    assert pedido.numero_pedido in dialogo.lbl_titulo.text()
    assert dialogo.cliente_combo.currentData() == esc.cliente.id_cliente
    assert dialogo.vendedor_combo.currentData() == esc.vendedor.id_vendedor
    assert dialogo.condicion_combo.currentData() == "contado"
    assert dialogo.observaciones_input.text() == "Entregar en la tarde"
    assert len(dialogo.items) == 1
    item = dialogo.items[0]
    assert (item["id_producto"], item["cantidad"], item["precio_unitario"]) == (esc.producto.id_producto, 5.0, 20.0)
    assert item["tipo_venta"] == "unidad"
    assert item["precio_lista"] == 20.0
    assert dialogo.lbl_total.text() == "Total: $100.00"


def test_el_vendedor_es_el_del_pedido_aunque_el_cliente_se_haya_reasignado(qtbot, db_session):
    """Elegir el cliente reasigna el vendedor del formulario al del cliente: si ese cambio ocurrio DESPUES del
    pedido, la factura saldria a nombre de otro y la comision se iria con el."""
    esc = _escenario(db_session)
    _, datos = _pedido_aprobado(db_session, esc)
    otro = crear_vendedor(db_session)
    esc.cliente.vendedor_cliente = otro.id_vendedor
    db_session.commit()

    dialogo = _dialogo(qtbot, db_session, esc, datos)

    assert dialogo.vendedor_combo.currentData() == esc.vendedor.id_vendedor
    assert dialogo.get_data()["id_vendedor"] == esc.vendedor.id_vendedor


def test_el_vendedor_del_pedido_se_conserva_aunque_hoy_este_inactivo(qtbot, db_session):
    esc = _escenario(db_session)
    _, datos = _pedido_aprobado(db_session, esc)
    esc.vendedor.estado_vendedor = "INACTIVO"  # el combo solo lista vendedores activos
    db_session.commit()

    dialogo = _dialogo(qtbot, db_session, esc, datos)

    assert dialogo.vendedor_combo.currentData() == esc.vendedor.id_vendedor
    assert dialogo.vendedor_combo.currentText() == esc.vendedor.nombre_vendedor


def test_lo_que_es_del_pedido_no_se_puede_cambiar(qtbot, db_session, avisos):
    esc = _escenario(db_session)
    _, datos = _pedido_aprobado(db_session, esc)

    dialogo = _dialogo(qtbot, db_session, esc, datos)

    for campo in (
        dialogo.cliente_combo,
        dialogo.vendedor_combo,
        dialogo.condicion_combo,
        dialogo.btn_agregar_item,
        dialogo.btn_nuevo_cliente,
        dialogo.cantidad_input,
        dialogo.precio_input,
    ):
        assert not campo.isEnabled()
    dialogo._agregar_item()  # aunque se dispare por teclado (Enter en cantidad): no hace nada
    dialogo._quitar_item(0)
    assert len(dialogo.items) == 1
    assert avisos == []  # ni siquiera llego a validar el producto: la guardia corta antes


def test_el_carrito_del_pedido_no_ofrece_quitar_lineas(qtbot, db_session):
    esc = _escenario(db_session)
    _, datos = _pedido_aprobado(db_session, esc)

    dialogo = _dialogo(qtbot, db_session, esc, datos)

    assert dialogo.tabla_items.cellWidget(0, 4) is None


def test_un_pedido_a_credito_deja_el_formulario_en_credito(qtbot, db_session):
    esc = _escenario(db_session)
    _, datos = _pedido_aprobado(db_session, esc, condicion_pago="credito")

    dialogo = _dialogo(qtbot, db_session, esc, datos)

    assert dialogo.condicion_combo.currentData() == "credito"
    assert dialogo.get_data()["condicion_pago"] == "credito"
    assert dialogo.get_data()["pagos"] == []


def test_get_data_lleva_el_id_del_pedido_solo_cuando_se_factura_un_pedido(qtbot, db_session):
    esc = _escenario(db_session)
    pedido, datos = _pedido_aprobado(db_session, esc)

    con_pedido = _dialogo(qtbot, db_session, esc, datos).get_data()
    sin_pedido = _dialogo(qtbot, db_session, esc).get_data()

    assert con_pedido["id_pedido"] == pedido.id_pedido
    assert "id_pedido" not in sin_pedido


def test_emitir_desde_el_formulario_factura_y_cierra_el_pedido(qtbot, db_session):
    esc = _escenario(db_session, stock=50)
    pedido, datos = _pedido_aprobado(db_session, esc, cantidad=5)
    dialogo = _dialogo(qtbot, db_session, esc, datos)
    datos_factura = {**dialogo.get_data(), "pagos": pago_contado(db_session)}

    resultado = ffd._tarea_emitir_factura(db_session, esc.admin.id_usuario, **datos_factura)

    assert resultado["ok"], resultado
    db_session.expire_all()
    cerrado = db_session.get(Pedido, pedido.id_pedido)
    assert cerrado.estado == "FACTURADO"
    assert cerrado.id_factura == resultado["id_factura"]
    factura = db_session.get(FacturaVenta, resultado["id_factura"])
    assert factura.total_venta == Decimal("100.00")
    assert factura.id_vendedor == esc.vendedor.id_vendedor


# -- Stock disponible (real menos apartado por pedidos) ------------------------------------------------------------


def test_el_selector_de_productos_muestra_el_stock_disponible_y_lo_apartado(qtbot, db_session):
    esc = _escenario(db_session, stock=50)
    _crear(db_session, esc, cantidad=8)

    dialogo = _dialogo(qtbot, db_session, esc)

    etiqueta = dialogo.producto_combo.itemText(dialogo.producto_combo.findData(esc.producto.id_producto))
    assert "stock: 42.00 Und" in etiqueta  # 50 reales - 8 apartados
    assert "8 apartadas" in etiqueta


def test_sin_pedidos_el_selector_de_productos_queda_como_siempre(qtbot, db_session):
    esc = _escenario(db_session, stock=50)

    dialogo = _dialogo(qtbot, db_session, esc)

    etiqueta = dialogo.producto_combo.itemText(dialogo.producto_combo.findData(esc.producto.id_producto))
    assert "stock: 50.00 Und" in etiqueta
    assert "apartadas" not in etiqueta


def test_no_deja_agregar_mas_de_lo_disponible_aunque_haya_stock_real(qtbot, db_session, avisos):
    esc = _escenario(db_session, stock=50, cantidad_caja=Decimal("1"))
    _crear(db_session, esc, cantidad=8)
    dialogo = _dialogo(qtbot, db_session, esc)
    dialogo.producto_combo.setCurrentIndex(dialogo.producto_combo.findData(esc.producto.id_producto))
    dialogo.cantidad_input.set_value(45)  # hay 50 reales, pero 8 estan apartados: disponibles 42

    dialogo._agregar_item()

    assert dialogo.items == []
    assert avisos[-1][1] == "Stock insuficiente"
    assert "apartadas por pedidos pendientes" in avisos[-1][2]


def test_si_cabe_en_lo_disponible_se_agrega(qtbot, db_session, avisos):
    esc = _escenario(db_session, stock=50, cantidad_caja=Decimal("1"))
    _crear(db_session, esc, cantidad=8)
    dialogo = _dialogo(qtbot, db_session, esc)
    dialogo.producto_combo.setCurrentIndex(dialogo.producto_combo.findData(esc.producto.id_producto))
    dialogo.cantidad_input.set_value(42)

    dialogo._agregar_item()

    assert len(dialogo.items) == 1 and avisos == []
