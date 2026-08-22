from decimal import Decimal

import pytest

from app.db.models import CompraDetalle, CuentaPorPagar
from app.services.compras import CompraService
from app.services.pagos import PagoService
from app.services.tesoreria import CajaService
from tests.factories import crear_caja, crear_producto, crear_proveedor


def test_registrar_compra_contado_repone_stock_y_calcula_total(db_session):
    producto = crear_producto(db_session, cantidad_unidad=10)
    proveedor = crear_proveedor(db_session)

    compra = CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=None,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 5, "costo_unitario": "8.00"}],
    )

    db_session.refresh(producto)
    assert producto.cantidad_unidad == Decimal("15.00")
    assert compra.total_compra == Decimal("40.00")


def test_registrar_compra_contado_no_abre_cuenta_por_pagar(db_session):
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session)

    compra = CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=None,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
    )

    cxp = db_session.query(CuentaPorPagar).filter_by(id_compra=compra.id_compra).first()
    assert cxp is None


def test_registrar_compra_credito_abre_cuenta_por_pagar(db_session):
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session, limite_credito=1000)

    compra = CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=None,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 4, "costo_unitario": "10.00"}],
    )

    cxp = db_session.query(CuentaPorPagar).filter_by(id_compra=compra.id_compra).first()
    assert cxp is not None
    assert cxp.saldo_pendiente == Decimal("40.00")
    assert cxp.estado == "pendiente"


def test_registrar_compra_credito_excede_limite(db_session):
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session, limite_credito=50)

    with pytest.raises(ValueError, match="limite de credito"):
        CompraService.registrar_compra(
            db_session,
            id_proveedor=proveedor.id_proveedor,
            id_usuario=None,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": 10, "costo_unitario": "10.00"}],
        )


def test_registrar_compra_credito_acumula_deuda_de_compras_previas(db_session):
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session, limite_credito=100)

    CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=None,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 6, "costo_unitario": "10.00"}],
    )

    with pytest.raises(ValueError, match="limite de credito"):
        CompraService.registrar_compra(
            db_session,
            id_proveedor=proveedor.id_proveedor,
            id_usuario=None,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": 6, "costo_unitario": "10.00"}],
        )


def test_registrar_compra_sin_items(db_session):
    proveedor = crear_proveedor(db_session)
    with pytest.raises(ValueError, match="al menos un item"):
        CompraService.registrar_compra(
            db_session,
            id_proveedor=proveedor.id_proveedor,
            id_usuario=None,
            condicion_pago="contado",
            items=[],
        )


def test_registrar_compra_condicion_pago_invalida(db_session):
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session)
    with pytest.raises(ValueError, match="condicion_pago"):
        CompraService.registrar_compra(
            db_session,
            id_proveedor=proveedor.id_proveedor,
            id_usuario=None,
            condicion_pago="otra",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
        )


def test_registrar_compra_proveedor_inexistente(db_session):
    producto = crear_producto(db_session)
    with pytest.raises(ValueError, match="Proveedor no encontrado"):
        CompraService.registrar_compra(
            db_session,
            id_proveedor=999999,
            id_usuario=None,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
        )


def test_anular_compra_contado_repone_stock(db_session):
    producto = crear_producto(db_session, cantidad_unidad=10)
    proveedor = crear_proveedor(db_session)

    compra = CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=None,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 5, "costo_unitario": "8.00"}],
    )

    CompraService.anular_compra(db_session, compra.id_compra, id_usuario=None, motivo="Error de carga")

    db_session.refresh(compra)
    db_session.refresh(producto)
    assert compra.estado_compra == "ANULADA"
    assert producto.cantidad_unidad == Decimal("10.00")  # se revierte el stock recibido
    assert compra.total_compra == Decimal("0.00")
    assert db_session.query(CompraDetalle).filter_by(id_compra=compra.id_compra).count() == 0


def test_anular_compra_credito_repone_stock_y_cierra_cxp(db_session):
    producto = crear_producto(db_session, cantidad_unidad=10)
    proveedor = crear_proveedor(db_session, limite_credito=1000)

    compra = CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=None,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 4, "costo_unitario": "10.00"}],
    )
    cxp = db_session.query(CuentaPorPagar).filter_by(id_compra=compra.id_compra).one()

    CompraService.anular_compra(db_session, compra.id_compra, id_usuario=None, motivo="Error de carga")

    db_session.refresh(producto)
    assert producto.cantidad_unidad == Decimal("10.00")
    assert db_session.get(CuentaPorPagar, cxp.id_cuenta) is None


def test_anular_compra_con_pago_aplicado_bloqueada(db_session):
    producto = crear_producto(db_session, cantidad_unidad=10)
    proveedor = crear_proveedor(db_session, limite_credito=1000)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=None, saldo_apertura=0)

    compra = CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=None,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 4, "costo_unitario": "10.00"}],
    )
    cxp = db_session.query(CuentaPorPagar).filter_by(id_compra=compra.id_compra).one()
    PagoService.registrar_pago_proveedor(
        db_session, id_cuenta_por_pagar=cxp.id_cuenta, monto=Decimal("10.00"), metodo_pago="efectivo", id_caja=caja.id_caja
    )

    with pytest.raises(ValueError, match="pagos aplicados"):
        CompraService.anular_compra(db_session, compra.id_compra, id_usuario=None, motivo="Error de carga")

    db_session.refresh(compra)
    db_session.refresh(producto)
    assert compra.estado_compra != "ANULADA"
    assert producto.cantidad_unidad == Decimal("14.00")  # stock intacto, no se repuso


def test_anular_compra_sin_motivo(db_session):
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session)
    compra = CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=None,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
    )

    with pytest.raises(ValueError, match="motivo"):
        CompraService.anular_compra(db_session, compra.id_compra, id_usuario=None, motivo="")


def test_anular_compra_ya_anulada(db_session):
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session)
    compra = CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=None,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
    )
    CompraService.anular_compra(db_session, compra.id_compra, id_usuario=None, motivo="Motivo 1")

    with pytest.raises(ValueError, match="ya esta anulada"):
        CompraService.anular_compra(db_session, compra.id_compra, id_usuario=None, motivo="Motivo 2")


def test_anular_compra_inexistente(db_session):
    with pytest.raises(ValueError, match="Compra no encontrada"):
        CompraService.anular_compra(db_session, 999999, id_usuario=None, motivo="Motivo")


def test_listar_compras_filtra_por_proveedor(db_session):
    producto = crear_producto(db_session)
    proveedor_a = crear_proveedor(db_session)
    proveedor_b = crear_proveedor(db_session)

    CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor_a.id_proveedor,
        id_usuario=None,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
    )
    CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor_b.id_proveedor,
        id_usuario=None,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
    )

    resultado = CompraService.listar_compras(db_session, id_proveedor=proveedor_a.id_proveedor)

    assert resultado["total"] == 1
    assert resultado["items"][0].id_proveedor == proveedor_a.id_proveedor
