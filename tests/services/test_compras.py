from decimal import Decimal

import pytest

from app.db.models import (
    BancoMovimiento,
    CajaMovimiento,
    CompraDetalle,
    CuentaPorPagar,
    NotaCreditoProveedor,
    PagoProveedor,
)
from app.services.compras import CompraService
from app.services.pagos import PagoService
from app.services.permisos import PermisoDenegadoError
from app.services.tasas import TasaService
from app.services.tesoreria import CajaService
from tests.factories import crear_caja, crear_cuenta_bancaria, crear_producto, crear_proveedor, crear_usuario_admin


def _abrir_caja_con_saldo(db_session, admin, saldo=Decimal("1000.00")):
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=saldo)
    return caja


def _pago_efectivo(id_caja, monto) -> dict:
    return {
        "metodo_pago": "efectivo",
        "moneda": "USD",
        "monto_moneda_origen": monto,
        "id_caja": id_caja,
        "id_cuenta_bancaria": None,
        "referencia": None,
    }


def _pago_transferencia(id_cuenta_bancaria, monto, referencia="REF-001") -> dict:
    return {
        "metodo_pago": "transferencia",
        "moneda": "USD",
        "monto_moneda_origen": monto,
        "id_caja": None,
        "id_cuenta_bancaria": id_cuenta_bancaria,
        "referencia": referencia,
    }


def test_registrar_compra_contado_repone_stock_y_calcula_total(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=10)
    proveedor = crear_proveedor(db_session)
    caja = _abrir_caja_con_saldo(db_session, admin)

    compra = CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 5, "costo_unitario": "8.00"}],
        pago=_pago_efectivo(caja.id_caja, Decimal("40.00")),
    )

    db_session.refresh(producto)
    assert producto.cantidad_unidad == Decimal("15.00")
    assert compra.total_compra == Decimal("40.00")


def test_registrar_compra_sin_usuario_autorizado_falla(db_session):
    producto = crear_producto(db_session, cantidad_unidad=10)
    proveedor = crear_proveedor(db_session)

    with pytest.raises(PermisoDenegadoError):
        CompraService.registrar_compra(
            db_session,
            id_proveedor=proveedor.id_proveedor,
            id_usuario=None,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 5, "costo_unitario": "8.00"}],
        )


def test_registrar_compra_proveedor_inactivo_falla(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=10)
    proveedor = crear_proveedor(db_session, estado_proveedor="INACTIVO")

    with pytest.raises(ValueError, match="inactivo"):
        CompraService.registrar_compra(
            db_session,
            id_proveedor=proveedor.id_proveedor,
            id_usuario=admin.id_usuario,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 5, "costo_unitario": "8.00"}],
        )


def test_registrar_compra_producto_inactivo_falla(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=10, estado_producto="INACTIVO")
    proveedor = crear_proveedor(db_session)

    with pytest.raises(ValueError, match="inactivo"):
        CompraService.registrar_compra(
            db_session,
            id_proveedor=proveedor.id_proveedor,
            id_usuario=admin.id_usuario,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 5, "costo_unitario": "8.00"}],
        )


def test_registrar_compra_producto_inexistente_falla(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session)

    with pytest.raises(ValueError, match="no encontrado"):
        CompraService.registrar_compra(
            db_session,
            id_proveedor=proveedor.id_proveedor,
            id_usuario=admin.id_usuario,
            condicion_pago="contado",
            items=[{"id_producto": 999999, "cantidad": 5, "costo_unitario": "8.00"}],
        )


def test_registrar_compra_contado_no_abre_cuenta_por_pagar(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session)
    caja = _abrir_caja_con_saldo(db_session, admin)

    compra = CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
        pago=_pago_efectivo(caja.id_caja, Decimal("8.00")),
    )

    cxp = db_session.query(CuentaPorPagar).filter_by(id_compra=compra.id_compra).first()
    assert cxp is None


def test_registrar_compra_credito_abre_cuenta_por_pagar(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session, limite_credito=1000)

    compra = CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 4, "costo_unitario": "10.00"}],
    )

    cxp = db_session.query(CuentaPorPagar).filter_by(id_compra=compra.id_compra).first()
    assert cxp is not None
    assert cxp.saldo_pendiente == Decimal("40.00")
    assert cxp.estado == "pendiente"


def test_registrar_compra_credito_excede_limite(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session, limite_credito=50)

    with pytest.raises(ValueError, match="limite de credito"):
        CompraService.registrar_compra(
            db_session,
            id_proveedor=proveedor.id_proveedor,
            id_usuario=admin.id_usuario,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": 10, "costo_unitario": "10.00"}],
        )


def test_registrar_compra_credito_acumula_deuda_de_compras_previas(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session, limite_credito=100)

    CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 6, "costo_unitario": "10.00"}],
    )

    with pytest.raises(ValueError, match="limite de credito"):
        CompraService.registrar_compra(
            db_session,
            id_proveedor=proveedor.id_proveedor,
            id_usuario=admin.id_usuario,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": 6, "costo_unitario": "10.00"}],
        )


def test_registrar_compra_sin_items(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session)
    with pytest.raises(ValueError, match="al menos un item"):
        CompraService.registrar_compra(
            db_session,
            id_proveedor=proveedor.id_proveedor,
            id_usuario=admin.id_usuario,
            condicion_pago="contado",
            items=[],
        )


def test_registrar_compra_condicion_pago_invalida(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session)
    with pytest.raises(ValueError, match="condicion_pago"):
        CompraService.registrar_compra(
            db_session,
            id_proveedor=proveedor.id_proveedor,
            id_usuario=admin.id_usuario,
            condicion_pago="otra",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
        )


def test_registrar_compra_proveedor_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    with pytest.raises(ValueError, match="Proveedor no encontrado"):
        CompraService.registrar_compra(
            db_session,
            id_proveedor=999999,
            id_usuario=admin.id_usuario,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
        )


def test_anular_compra_contado_repone_stock(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=10)
    proveedor = crear_proveedor(db_session)
    caja = _abrir_caja_con_saldo(db_session, admin)

    compra = CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 5, "costo_unitario": "8.00"}],
        pago=_pago_efectivo(caja.id_caja, Decimal("40.00")),
    )

    CompraService.anular_compra(db_session, compra.id_compra, id_usuario=admin.id_usuario, motivo="Error de carga")

    db_session.refresh(compra)
    db_session.refresh(producto)
    assert compra.estado_compra == "ANULADA"
    assert producto.cantidad_unidad == Decimal("10.00")  # se revierte el stock recibido
    assert compra.total_compra == Decimal("0.00")
    assert db_session.query(CompraDetalle).filter_by(id_compra=compra.id_compra).count() == 0


def test_anular_compra_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=10)
    proveedor = crear_proveedor(db_session)
    caja = _abrir_caja_con_saldo(db_session, admin)

    compra = CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 5, "costo_unitario": "8.00"}],
        pago=_pago_efectivo(caja.id_caja, Decimal("40.00")),
    )

    with pytest.raises(PermisoDenegadoError):
        CompraService.anular_compra(db_session, compra.id_compra, id_usuario=None, motivo="Error de carga")


def test_anular_compra_credito_repone_stock_y_cierra_cxp(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=10)
    proveedor = crear_proveedor(db_session, limite_credito=1000)

    compra = CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 4, "costo_unitario": "10.00"}],
    )
    cxp = db_session.query(CuentaPorPagar).filter_by(id_compra=compra.id_compra).one()

    CompraService.anular_compra(db_session, compra.id_compra, id_usuario=admin.id_usuario, motivo="Error de carga")

    db_session.refresh(producto)
    assert producto.cantidad_unidad == Decimal("10.00")
    assert db_session.get(CuentaPorPagar, cxp.id_cuenta) is None


def test_anular_compra_con_pago_aplicado_genera_nota_de_credito(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=10)
    proveedor = crear_proveedor(db_session, limite_credito=1000)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    compra = CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 4, "costo_unitario": "10.00"}],
    )
    cxp = db_session.query(CuentaPorPagar).filter_by(id_compra=compra.id_compra).one()
    pago = PagoService.registrar_pago_proveedor(
        db_session,
        id_cuenta_por_pagar=cxp.id_cuenta,
        monto=Decimal("10.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )
    id_pago_proveedor = pago.id_pago_proveedor

    CompraService.anular_compra(db_session, compra.id_compra, id_usuario=admin.id_usuario, motivo="Error de carga")

    db_session.refresh(compra)
    db_session.refresh(producto)
    assert compra.estado_compra == "ANULADA"
    assert producto.cantidad_unidad == Decimal("10.00")  # stock repuesto

    db_session.refresh(cxp)
    assert cxp.estado == "anulada"
    assert cxp.saldo_pendiente == Decimal("0.00")

    assert db_session.query(PagoProveedor).filter_by(id_pago_proveedor=id_pago_proveedor).one().monto == Decimal(
        "10.00"
    )
    assert db_session.query(CajaMovimiento).filter_by(id_pago_proveedor=id_pago_proveedor).first() is not None

    nota = db_session.query(NotaCreditoProveedor).filter_by(id_compra_origen=compra.id_compra).one()
    assert nota.id_proveedor == proveedor.id_proveedor
    assert nota.monto == Decimal("10.00")
    assert nota.saldo_disponible == Decimal("10.00")
    assert nota.estado == "disponible"


def test_anular_compra_sin_motivo(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session)
    caja = _abrir_caja_con_saldo(db_session, admin)
    compra = CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
        pago=_pago_efectivo(caja.id_caja, Decimal("8.00")),
    )

    with pytest.raises(ValueError, match="motivo"):
        CompraService.anular_compra(db_session, compra.id_compra, id_usuario=admin.id_usuario, motivo="")


def test_anular_compra_ya_anulada(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session)
    caja = _abrir_caja_con_saldo(db_session, admin)
    compra = CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
        pago=_pago_efectivo(caja.id_caja, Decimal("8.00")),
    )
    CompraService.anular_compra(db_session, compra.id_compra, id_usuario=admin.id_usuario, motivo="Motivo 1")

    with pytest.raises(ValueError, match="ya esta anulada"):
        CompraService.anular_compra(db_session, compra.id_compra, id_usuario=admin.id_usuario, motivo="Motivo 2")


def test_anular_compra_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Compra no encontrada"):
        CompraService.anular_compra(db_session, 999999, id_usuario=admin.id_usuario, motivo="Motivo")


def test_listar_compras_filtra_por_proveedor(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    proveedor_a = crear_proveedor(db_session)
    proveedor_b = crear_proveedor(db_session)
    caja = _abrir_caja_con_saldo(db_session, admin)

    CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor_a.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
        pago=_pago_efectivo(caja.id_caja, Decimal("8.00")),
    )
    CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor_b.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
        pago=_pago_efectivo(caja.id_caja, Decimal("8.00")),
    )

    resultado = CompraService.listar_compras(
        db_session, id_proveedor=proveedor_a.id_proveedor, id_usuario=admin.id_usuario
    )

    assert resultado["total"] == 1
    assert resultado["items"][0].id_proveedor == proveedor_a.id_proveedor


def test_listar_compras_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        CompraService.listar_compras(db_session)


def test_registrar_compra_contado_sin_pago_falla(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session)

    with pytest.raises(ValueError, match="pago es requerido"):
        CompraService.registrar_compra(
            db_session,
            id_proveedor=proveedor.id_proveedor,
            id_usuario=admin.id_usuario,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
        )


def test_registrar_compra_contado_efectivo_descuenta_caja(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session)
    caja = _abrir_caja_con_saldo(db_session, admin, saldo=Decimal("100.00"))

    CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
        pago=_pago_efectivo(caja.id_caja, Decimal("8.00")),
    )

    movimiento = db_session.query(CajaMovimiento).filter_by(id_caja=caja.id_caja, tipo_movimiento="salida").one()
    assert movimiento.monto_movimiento == Decimal("8.00")
    assert CajaService.calcular_saldo_actual(db_session, caja.id_caja) == Decimal("92.00")


def test_registrar_compra_contado_transferencia_registra_movimiento_bancario(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session)
    cuenta = crear_cuenta_bancaria(db_session)

    CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
        pago=_pago_transferencia(cuenta.id_cuenta, Decimal("8.00")),
    )

    movimiento = db_session.query(BancoMovimiento).filter_by(id_cuenta=cuenta.id_cuenta, tipo_movimiento="cargo").one()
    assert movimiento.monto_movimiento == Decimal("8.00")
    assert movimiento.referencia_movimiento == "REF-001"


def test_registrar_compra_contado_pago_no_coincide_con_total_falla(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session)
    caja = _abrir_caja_con_saldo(db_session, admin)

    with pytest.raises(ValueError, match="no coincide"):
        CompraService.registrar_compra(
            db_session,
            id_proveedor=proveedor.id_proveedor,
            id_usuario=admin.id_usuario,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
            pago=_pago_efectivo(caja.id_caja, Decimal("5.00")),
        )


def test_registrar_compra_contado_caja_sin_saldo_suficiente_falla(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session)
    caja = _abrir_caja_con_saldo(db_session, admin, saldo=Decimal("1.00"))

    with pytest.raises(ValueError, match="no tiene saldo suficiente"):
        CompraService.registrar_compra(
            db_session,
            id_proveedor=proveedor.id_proveedor,
            id_usuario=admin.id_usuario,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
            pago=_pago_efectivo(caja.id_caja, Decimal("8.00")),
        )


def test_registrar_compra_contado_convierte_pago_ves_con_tasa_vigente(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session)
    caja = _abrir_caja_con_saldo(db_session, admin)
    TasaService.registrar_tasa(db_session, tasa_bcv=Decimal("40.00"), creado_por=admin.id_usuario)

    compra = CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
        pago={
            "metodo_pago": "efectivo",
            "moneda": "VES",
            "monto_moneda_origen": Decimal("320.00"),
            "id_caja": caja.id_caja,
            "id_cuenta_bancaria": None,
            "referencia": None,
        },
    )

    assert compra.total_compra == Decimal("8.00")
    movimiento = db_session.query(CajaMovimiento).filter_by(id_caja=caja.id_caja, tipo_movimiento="salida").one()
    assert movimiento.monto_movimiento == Decimal("8.00")  # el movimiento de caja se guarda en su equivalente USD


def test_registrar_compra_credito_con_pago_falla(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session, limite_credito=1000)
    caja = _abrir_caja_con_saldo(db_session, admin)

    with pytest.raises(ValueError, match="no admite pago"):
        CompraService.registrar_compra(
            db_session,
            id_proveedor=proveedor.id_proveedor,
            id_usuario=admin.id_usuario,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "8.00"}],
            pago=_pago_efectivo(caja.id_caja, Decimal("8.00")),
        )


def test_obtener_compra_devuelve_compra_y_detalles(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    proveedor = crear_proveedor(db_session)
    caja = _abrir_caja_con_saldo(db_session, admin)
    compra = CompraService.registrar_compra(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "costo_unitario": "8.00"}],
        pago=_pago_efectivo(caja.id_caja, Decimal("16.00")),
    )

    resultado = CompraService.obtener_compra(db_session, compra.id_compra, id_usuario=admin.id_usuario)

    assert resultado["compra"].id_compra == compra.id_compra
    assert len(resultado["detalles"]) == 1
    assert resultado["detalles"][0].cantidad_producto == Decimal("2.00")


def test_obtener_compra_inexistente_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Compra no encontrada"):
        CompraService.obtener_compra(db_session, 999999, id_usuario=admin.id_usuario)


def test_obtener_compra_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        CompraService.obtener_compra(db_session, 999999)
