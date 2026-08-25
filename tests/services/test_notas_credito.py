"""Pruebas de NotaCreditoService en aislamiento. El flujo real (generarla automaticamente
al anular una factura/compra con pagos aplicados) se prueba en
test_ventas.py::test_anular_factura_con_pago_aplicado_genera_nota_de_credito y su
equivalente en test_compras.py.
"""

from decimal import Decimal

import pytest

from app.services.compras import CompraService
from app.services.notas_credito import NotaCreditoService
from app.services.permisos import PermisoDenegadoError
from app.services.ventas import VentaService
from tests.factories import (
    crear_cliente,
    crear_producto,
    crear_proveedor,
    crear_usuario_admin,
    crear_vendedor,
    pago_contado,
)


def _crear_factura(session):
    admin = crear_usuario_admin(session)
    vendedor = crear_vendedor(session)
    producto = crear_producto(session, cantidad_unidad=10)
    cliente = crear_cliente(session)
    factura = VentaService.emitir_factura(
        session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "10.00"}],
        pagos=pago_contado(session),
    )
    return cliente, factura, admin


def _crear_compra(session):
    admin = crear_usuario_admin(session)
    producto = crear_producto(session, cantidad_unidad=10)
    proveedor = crear_proveedor(session)
    compra = CompraService.registrar_compra(
        session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "10.00"}],
    )
    return proveedor, compra, admin


# --- crear_nota_credito_cliente --------------------------------------------------


def test_crear_nota_credito_cliente_ok(db_session):
    cliente, factura, _ = _crear_factura(db_session)

    nota = NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura.id_factura,
        monto=Decimal("25.00"),
        motivo="Factura anulada con pago ya aplicado",
        id_usuario=None,
    )

    assert nota.id_nota_credito is not None
    assert nota.numero_nota_credito.startswith("NC-")
    assert nota.monto == Decimal("25.00")
    assert nota.saldo_disponible == Decimal("25.00")
    assert nota.estado == "disponible"


def test_crear_nota_credito_cliente_correlativo_es_unico_y_valido(db_session):
    # El generador usa MAX(id_nota_credito)+1 (igual que numero_factura/numero_compra),
    # que en tests puede no coincidir con lo que uno esperaria a simple vista porque el
    # IDENTITY real no se resetea entre tests aunque las filas se limpien -- por eso no
    # se afirma un valor exacto ni un incremento de +1 puntual, solo formato y unicidad.
    cliente, factura, _ = _crear_factura(db_session)

    primera = NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura.id_factura,
        monto=Decimal("10.00"),
        motivo="x",
        id_usuario=None,
    )
    segunda = NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura.id_factura,
        monto=Decimal("5.00"),
        motivo="y",
        id_usuario=None,
    )

    assert primera.numero_nota_credito != segunda.numero_nota_credito
    for numero in (primera.numero_nota_credito, segunda.numero_nota_credito):
        assert numero.startswith("NC-")
        assert numero.split("-")[1].isdigit()


def test_crear_nota_credito_cliente_monto_invalido(db_session):
    cliente, factura, _ = _crear_factura(db_session)

    with pytest.raises(ValueError, match="mayor a cero"):
        NotaCreditoService.crear_nota_credito_cliente(
            db_session,
            id_cliente=cliente.id_cliente,
            id_factura_origen=factura.id_factura,
            monto=Decimal("0.00"),
            motivo="x",
            id_usuario=None,
        )


def test_listar_notas_credito_cliente(db_session):
    cliente, factura, admin = _crear_factura(db_session)
    NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura.id_factura,
        monto=Decimal("10.00"),
        motivo="x",
        id_usuario=None,
    )
    NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura.id_factura,
        monto=Decimal("5.00"),
        motivo="y",
        id_usuario=None,
    )

    notas = NotaCreditoService.listar_notas_credito_cliente(db_session, cliente.id_cliente, id_usuario=admin.id_usuario)
    assert len(notas) == 2


def test_listar_notas_credito_cliente_sin_usuario_autorizado_falla(db_session):
    cliente, _, _ = _crear_factura(db_session)
    with pytest.raises(PermisoDenegadoError):
        NotaCreditoService.listar_notas_credito_cliente(db_session, cliente.id_cliente)


def test_listar_notas_credito_clientes_reporte_filtra_por_cliente_y_pagina(db_session):
    """El reporte con filtros (fecha, cliente, estado, paginacion) es el que se usaria
    para armar lo que pida el SENIAT -- distinto del listado simple por cliente."""
    cliente_a, factura_a, admin = _crear_factura(db_session)
    cliente_b, factura_b, _ = _crear_factura(db_session)
    NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente_a.id_cliente,
        id_factura_origen=factura_a.id_factura,
        monto=Decimal("10.00"),
        motivo="x",
        id_usuario=None,
    )
    NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente_b.id_cliente,
        id_factura_origen=factura_b.id_factura,
        monto=Decimal("20.00"),
        motivo="y",
        id_usuario=None,
    )

    reporte = NotaCreditoService.listar_notas_credito_clientes(
        db_session, id_cliente=cliente_a.id_cliente, id_usuario=admin.id_usuario
    )
    assert reporte["total"] == 1
    assert reporte["items"][0].id_cliente == cliente_a.id_cliente

    reporte_todas = NotaCreditoService.listar_notas_credito_clientes(
        db_session, pagina=1, por_pagina=1, id_usuario=admin.id_usuario
    )
    assert reporte_todas["total"] == 2
    assert len(reporte_todas["items"]) == 1


def test_listar_notas_credito_clientes_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        NotaCreditoService.listar_notas_credito_clientes(db_session)


# --- crear_nota_credito_proveedor -------------------------------------------------


def test_crear_nota_credito_proveedor_ok(db_session):
    proveedor, compra, _ = _crear_compra(db_session)

    nota = NotaCreditoService.crear_nota_credito_proveedor(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_compra_origen=compra.id_compra,
        monto=Decimal("15.00"),
        motivo="Compra anulada con pago ya aplicado",
        id_usuario=None,
    )

    assert nota.id_nota_credito is not None
    assert nota.saldo_disponible == Decimal("15.00")
    assert nota.estado == "disponible"


def test_crear_nota_credito_proveedor_monto_invalido(db_session):
    proveedor, compra, _ = _crear_compra(db_session)

    with pytest.raises(ValueError, match="mayor a cero"):
        NotaCreditoService.crear_nota_credito_proveedor(
            db_session,
            id_proveedor=proveedor.id_proveedor,
            id_compra_origen=compra.id_compra,
            monto=Decimal("-5.00"),
            motivo="x",
            id_usuario=None,
        )


def test_listar_notas_credito_proveedor(db_session):
    proveedor, compra, admin = _crear_compra(db_session)
    NotaCreditoService.crear_nota_credito_proveedor(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_compra_origen=compra.id_compra,
        monto=Decimal("15.00"),
        motivo="x",
        id_usuario=None,
    )

    notas = NotaCreditoService.listar_notas_credito_proveedor(
        db_session, proveedor.id_proveedor, id_usuario=admin.id_usuario
    )
    assert len(notas) == 1


def test_listar_notas_credito_proveedor_sin_usuario_autorizado_falla(db_session):
    proveedor, _, _ = _crear_compra(db_session)
    with pytest.raises(PermisoDenegadoError):
        NotaCreditoService.listar_notas_credito_proveedor(db_session, proveedor.id_proveedor)
