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


# --- aplicaciones_nota_credito_proveedor (migrations/0101) ---------------------------------


def _nota_y_deuda(db_session, nota_total="40.00", deuda="100.00"):
    """Una nota de proveedor disponible (compra de contado anulada) y una deuda a credito del mismo proveedor."""
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session, limite_credito=Decimal("1000.00"))
    caja = _caja_abierta(db_session, admin)
    anulada = _compra(db_session, admin, proveedor, "contado", total=nota_total, caja=caja)
    CompraService.anular_compra(db_session, anulada.id_compra, id_usuario=admin.id_usuario, motivo="Error")
    nota = _nota_de_compra(db_session, anulada)
    cxp = _cxp(db_session, _compra(db_session, admin, proveedor, "credito", total=deuda))
    return admin, nota, cxp


def test_aplicar_una_nota_de_proveedor_deja_una_fila_con_la_nota_la_cuenta_el_monto_y_quien_la_aplico(db_session):
    from app.db.models import AplicacionNotaCreditoProveedor

    admin, nota, cxp = _nota_y_deuda(db_session)

    NotaCreditoService.aplicar_nota_credito_proveedor(
        db_session, nota.id_nota_credito, cxp.id_cuenta, Decimal("25.00"), admin.id_usuario
    )

    (aplicacion,) = db_session.query(AplicacionNotaCreditoProveedor).all()
    assert aplicacion.id_nota_credito == nota.id_nota_credito
    assert aplicacion.id_cuenta_por_pagar == cxp.id_cuenta
    assert aplicacion.monto == Decimal("25.00")
    assert aplicacion.aplicado_por == admin.id_usuario
    assert aplicacion.fecha_aplicacion is not None


def test_dos_aplicaciones_parciales_de_proveedor_dejan_dos_filas_que_suman_lo_aplicado(db_session):
    from app.db.models import AplicacionNotaCreditoProveedor

    admin, nota, cxp = _nota_y_deuda(db_session)

    for monto in ("10.00", "15.00"):
        NotaCreditoService.aplicar_nota_credito_proveedor(
            db_session, nota.id_nota_credito, cxp.id_cuenta, Decimal(monto), admin.id_usuario
        )

    filas = db_session.query(AplicacionNotaCreditoProveedor).order_by(AplicacionNotaCreditoProveedor.id_aplicacion)
    assert [f.monto for f in filas] == [Decimal("10.00"), Decimal("15.00")]
    db_session.refresh(nota)
    assert nota.monto - nota.saldo_disponible == Decimal("25.00")  # lo aplicado cuadra con la nota


def test_una_aplicacion_de_proveedor_rechazada_no_deja_ninguna_fila(db_session):
    from app.db.models import AplicacionNotaCreditoProveedor

    admin, nota, cxp = _nota_y_deuda(db_session)

    with pytest.raises(ValueError, match="excede"):
        NotaCreditoService.aplicar_nota_credito_proveedor(
            db_session, nota.id_nota_credito, cxp.id_cuenta, Decimal("500.00"), admin.id_usuario
        )

    db_session.rollback()
    assert db_session.query(AplicacionNotaCreditoProveedor).count() == 0


def test_si_falla_el_commit_de_proveedor_no_queda_la_fila_ni_baja_el_saldo(db_session, monkeypatch):
    from app.db.models import AplicacionNotaCreditoProveedor

    admin, nota, cxp = _nota_y_deuda(db_session)
    original = db_session.commit

    def commit_roto():
        raise RuntimeError("se cayo la conexion")

    monkeypatch.setattr(db_session, "commit", commit_roto)
    with pytest.raises(RuntimeError):
        NotaCreditoService.aplicar_nota_credito_proveedor(
            db_session, nota.id_nota_credito, cxp.id_cuenta, Decimal("25.00"), admin.id_usuario
        )
    monkeypatch.setattr(db_session, "commit", original)
    db_session.rollback()

    assert db_session.query(AplicacionNotaCreditoProveedor).count() == 0
    assert _cxp_por_id(db_session, cxp.id_cuenta).saldo_pendiente == Decimal("100.00")


def _cxp_por_id(db_session, id_cuenta):
    return db_session.query(CuentaPorPagar).filter_by(id_cuenta=id_cuenta).one()


@pytest.mark.parametrize("monto", ["0.00", "-5.00"])
def test_la_base_rechaza_una_aplicacion_de_proveedor_con_monto_no_positivo(db_session, monto):
    from sqlalchemy.exc import IntegrityError

    from app.db.models import AplicacionNotaCreditoProveedor

    _admin, nota, cxp = _nota_y_deuda(db_session)

    db_session.add(
        AplicacionNotaCreditoProveedor(
            id_nota_credito=nota.id_nota_credito, id_cuenta_por_pagar=cxp.id_cuenta, monto=Decimal(monto)
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_la_base_rechaza_una_aplicacion_de_proveedor_a_una_nota_o_cuenta_inexistente(db_session):
    from sqlalchemy.exc import IntegrityError

    from app.db.models import AplicacionNotaCreditoProveedor

    db_session.add(
        AplicacionNotaCreditoProveedor(id_nota_credito=999_999, id_cuenta_por_pagar=999_999, monto=Decimal("5.00"))
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
