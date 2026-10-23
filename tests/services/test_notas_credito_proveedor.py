"""Notas de credito de proveedor: se generan al anular una compra ya pagada (contado, o
credito con pagos) y se consumen aplicandolas a otra deuda del mismo proveedor o
registrando el reembolso del proveedor a caja/banco."""

from decimal import Decimal

import pytest

from app.db.models import BancoMovimiento, CajaMovimiento, CuentaPorPagar, NotaCreditoProveedor
from app.services.compras import CompraService
from app.services.notas_credito import NotaCreditoService
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import CajaService
from tests.factories import (
    crear_caja,
    crear_cuenta_bancaria,
    crear_producto,
    crear_proveedor,
    crear_usuario_admin,
)


def _caja_abierta(db_session, admin, saldo=Decimal("1000.00")):
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=saldo)
    return caja


def _compra(db_session, admin, proveedor, condicion_pago, total="40.00", caja=None):
    producto = crear_producto(db_session, cantidad_unidad=10)
    pago = None
    if condicion_pago == "contado":
        pago = {
            "metodo_pago": "efectivo",
            "moneda": "USD",
            "monto_moneda_origen": Decimal(total),
            "id_caja": caja.id_caja,
            "id_cuenta_bancaria": None,
            "referencia": None,
        }
    return CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago=condicion_pago,
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": total}],
        pago=pago,
    )


def _nota_de_compra(db_session, compra):
    return db_session.query(NotaCreditoProveedor).filter_by(id_compra_origen=compra.id_compra).one()


def _cxp(db_session, compra):
    return db_session.query(CuentaPorPagar).filter_by(id_compra=compra.id_compra).one()


def test_anular_compra_de_contado_genera_nota_de_credito_por_lo_pagado(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session)
    caja = _caja_abierta(db_session, admin)
    compra = _compra(db_session, admin, proveedor, "contado", total="40.00", caja=caja)

    CompraService.anular_compra(db_session, compra.id_compra, id_usuario=admin.id_usuario, motivo="Error de carga")

    nota = _nota_de_compra(db_session, compra)
    assert nota.monto == Decimal("40.00")
    assert nota.saldo_disponible == Decimal("40.00")
    assert nota.estado == "disponible"
    assert nota.id_proveedor == proveedor.id_proveedor


def test_aplicar_nota_a_otra_deuda_del_proveedor(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session, limite_credito=Decimal("1000.00"))
    caja = _caja_abierta(db_session, admin)
    anulada = _compra(db_session, admin, proveedor, "contado", total="40.00", caja=caja)
    CompraService.anular_compra(db_session, anulada.id_compra, id_usuario=admin.id_usuario, motivo="Error")
    nota = _nota_de_compra(db_session, anulada)
    deuda = _compra(db_session, admin, proveedor, "credito", total="100.00")
    cxp = _cxp(db_session, deuda)
    saldo_caja = CajaService.calcular_saldo_actual(db_session, caja.id_caja)

    NotaCreditoService.aplicar_nota_credito_proveedor(
        db_session,
        id_nota_credito=nota.id_nota_credito,
        id_cuenta_por_pagar=cxp.id_cuenta,
        monto=Decimal("40.00"),
        id_usuario=admin.id_usuario,
    )

    db_session.refresh(nota)
    db_session.refresh(cxp)
    assert nota.saldo_disponible == Decimal("0.00")
    assert nota.estado == "aplicada"
    assert cxp.saldo_pendiente == Decimal("60.00")
    assert cxp.estado == "parcial"
    # Compensacion contable: no mueve caja.
    assert CajaService.calcular_saldo_actual(db_session, caja.id_caja) == saldo_caja


def test_aplicar_nota_parcial_que_salda_la_deuda(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session, limite_credito=Decimal("1000.00"))
    caja = _caja_abierta(db_session, admin)
    anulada = _compra(db_session, admin, proveedor, "contado", total="40.00", caja=caja)
    CompraService.anular_compra(db_session, anulada.id_compra, id_usuario=admin.id_usuario, motivo="Error")
    nota = _nota_de_compra(db_session, anulada)
    cxp = _cxp(db_session, _compra(db_session, admin, proveedor, "credito", total="25.00"))

    NotaCreditoService.aplicar_nota_credito_proveedor(
        db_session,
        id_nota_credito=nota.id_nota_credito,
        id_cuenta_por_pagar=cxp.id_cuenta,
        monto=Decimal("25.00"),
        id_usuario=admin.id_usuario,
    )

    db_session.refresh(nota)
    db_session.refresh(cxp)
    assert nota.saldo_disponible == Decimal("15.00")
    assert nota.estado == "disponible"
    assert cxp.estado == "pagada"


def test_aplicar_nota_a_deuda_de_otro_proveedor_falla(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session)
    otro = crear_proveedor(db_session, limite_credito=Decimal("1000.00"))
    caja = _caja_abierta(db_session, admin)
    anulada = _compra(db_session, admin, proveedor, "contado", caja=caja)
    CompraService.anular_compra(db_session, anulada.id_compra, id_usuario=admin.id_usuario, motivo="Error")
    nota = _nota_de_compra(db_session, anulada)
    cxp_ajena = _cxp(db_session, _compra(db_session, admin, otro, "credito", total="100.00"))

    with pytest.raises(ValueError, match="otro proveedor"):
        NotaCreditoService.aplicar_nota_credito_proveedor(
            db_session,
            id_nota_credito=nota.id_nota_credito,
            id_cuenta_por_pagar=cxp_ajena.id_cuenta,
            monto=Decimal("10.00"),
            id_usuario=admin.id_usuario,
        )


def test_aplicar_mas_que_el_saldo_de_la_nota_falla(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session, limite_credito=Decimal("1000.00"))
    caja = _caja_abierta(db_session, admin)
    anulada = _compra(db_session, admin, proveedor, "contado", total="40.00", caja=caja)
    CompraService.anular_compra(db_session, anulada.id_compra, id_usuario=admin.id_usuario, motivo="Error")
    nota = _nota_de_compra(db_session, anulada)
    cxp = _cxp(db_session, _compra(db_session, admin, proveedor, "credito", total="100.00"))

    with pytest.raises(ValueError, match="excede el saldo disponible"):
        NotaCreditoService.aplicar_nota_credito_proveedor(
            db_session,
            id_nota_credito=nota.id_nota_credito,
            id_cuenta_por_pagar=cxp.id_cuenta,
            monto=Decimal("50.00"),
            id_usuario=admin.id_usuario,
        )


def test_reembolso_en_efectivo_entra_a_la_caja(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session)
    caja = _caja_abierta(db_session, admin)
    anulada = _compra(db_session, admin, proveedor, "contado", total="40.00", caja=caja)
    CompraService.anular_compra(db_session, anulada.id_compra, id_usuario=admin.id_usuario, motivo="Error")
    nota = _nota_de_compra(db_session, anulada)
    saldo_antes = CajaService.calcular_saldo_actual(db_session, caja.id_caja)

    NotaCreditoService.reembolsar_nota_credito_proveedor(
        db_session,
        id_nota_credito=nota.id_nota_credito,
        monto=Decimal("40.00"),
        metodo_reembolso="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    db_session.refresh(nota)
    assert nota.estado == "devuelta"
    assert nota.saldo_disponible == Decimal("0.00")
    assert CajaService.calcular_saldo_actual(db_session, caja.id_caja) == saldo_antes + Decimal("40.00")
    movimiento = db_session.query(CajaMovimiento).filter(CajaMovimiento.tipo_movimiento == "entrada").all()[-1]
    assert anulada.numero_compra in movimiento.descripcion_movimiento


def test_reembolso_por_transferencia_entra_al_banco_con_referencia(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session)
    caja = _caja_abierta(db_session, admin)
    anulada = _compra(db_session, admin, proveedor, "contado", total="40.00", caja=caja)
    CompraService.anular_compra(db_session, anulada.id_compra, id_usuario=admin.id_usuario, motivo="Error")
    nota = _nota_de_compra(db_session, anulada)
    banco = crear_cuenta_bancaria(db_session, saldo_total_banco=Decimal("100.00"))

    NotaCreditoService.reembolsar_nota_credito_proveedor(
        db_session,
        id_nota_credito=nota.id_nota_credito,
        monto=Decimal("15.00"),
        metodo_reembolso="transferencia",
        id_cuenta_bancaria=banco.id_cuenta,
        referencia="REF-9876",
        id_usuario=admin.id_usuario,
    )

    db_session.refresh(nota)
    db_session.refresh(banco)
    assert nota.saldo_disponible == Decimal("25.00")
    assert nota.estado == "disponible"
    assert banco.saldo_total_banco == Decimal("115.00")
    movimiento = db_session.query(BancoMovimiento).filter_by(id_cuenta=banco.id_cuenta).one()
    assert movimiento.tipo_movimiento == "abono"
    assert movimiento.referencia_movimiento == "REF-9876"


def test_reembolso_bancario_sin_referencia_falla(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session)
    caja = _caja_abierta(db_session, admin)
    anulada = _compra(db_session, admin, proveedor, "contado", caja=caja)
    CompraService.anular_compra(db_session, anulada.id_compra, id_usuario=admin.id_usuario, motivo="Error")
    nota = _nota_de_compra(db_session, anulada)
    banco = crear_cuenta_bancaria(db_session)

    with pytest.raises(ValueError, match="referencia"):
        NotaCreditoService.reembolsar_nota_credito_proveedor(
            db_session,
            id_nota_credito=nota.id_nota_credito,
            monto=Decimal("10.00"),
            metodo_reembolso="transferencia",
            id_cuenta_bancaria=banco.id_cuenta,
            id_usuario=admin.id_usuario,
        )


def test_nota_ya_consumida_no_se_puede_volver_a_usar(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session)
    caja = _caja_abierta(db_session, admin)
    anulada = _compra(db_session, admin, proveedor, "contado", total="40.00", caja=caja)
    CompraService.anular_compra(db_session, anulada.id_compra, id_usuario=admin.id_usuario, motivo="Error")
    nota = _nota_de_compra(db_session, anulada)
    NotaCreditoService.reembolsar_nota_credito_proveedor(
        db_session,
        id_nota_credito=nota.id_nota_credito,
        monto=Decimal("40.00"),
        metodo_reembolso="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    with pytest.raises(ValueError, match="no esta disponible"):
        NotaCreditoService.reembolsar_nota_credito_proveedor(
            db_session,
            id_nota_credito=nota.id_nota_credito,
            monto=Decimal("1.00"),
            metodo_reembolso="efectivo",
            id_caja=caja.id_caja,
            id_usuario=admin.id_usuario,
        )


def test_listar_disponibles_excluye_las_consumidas(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session)
    caja = _caja_abierta(db_session, admin)
    notas = []
    for _ in range(2):
        compra = _compra(db_session, admin, proveedor, "contado", total="10.00", caja=caja)
        CompraService.anular_compra(db_session, compra.id_compra, id_usuario=admin.id_usuario, motivo="Error")
        notas.append(_nota_de_compra(db_session, compra))
    NotaCreditoService.reembolsar_nota_credito_proveedor(
        db_session,
        id_nota_credito=notas[0].id_nota_credito,
        monto=Decimal("10.00"),
        metodo_reembolso="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    disponibles = NotaCreditoService.listar_notas_credito_proveedor_disponibles(db_session, id_usuario=admin.id_usuario)

    assert [n.id_nota_credito for n in disponibles] == [notas[1].id_nota_credito]


def test_aplicar_y_reembolsar_sin_permiso_fallan(db_session):
    with pytest.raises(PermisoDenegadoError):
        NotaCreditoService.aplicar_nota_credito_proveedor(
            db_session, id_nota_credito=1, id_cuenta_por_pagar=1, monto=1, id_usuario=None
        )
    with pytest.raises(PermisoDenegadoError):
        NotaCreditoService.reembolsar_nota_credito_proveedor(
            db_session, id_nota_credito=1, monto=1, metodo_reembolso="efectivo", id_caja=1, id_usuario=None
        )
