"""Pruebas de PagoService, que aplica pagos_cobros/pagos_proveedores contra sus
cuentas por cobrar/pagar. Ver la nota en trg_pagos_cobros_io (schema_sqlserver.sql)
sobre por que estos triggers necesitan un SELECT final para que SQLAlchemy pueda
leer el id autogenerado con session.add(...) + commit() como cualquier otro modelo.
"""

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import ProgrammingError

from app.db.models import BancoMovimiento, CajaMovimiento, PagoCobro, PagoProveedor
from app.services.compras import CompraService
from app.services.pagos import PagoService
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import CajaService
from app.services.ventas import VentaService
from tests.factories import (
    crear_caja,
    crear_cliente,
    crear_cuenta_bancaria,
    crear_producto,
    crear_proveedor,
    crear_usuario_admin,
    crear_vendedor,
)


def _crear_cxc(session, saldo: Decimal):
    """Devuelve (cxc, admin): admin es un actor autorizado listo para usar en
    abrir_caja/registrar_pago_cobro en el test que llama esto."""
    admin = crear_usuario_admin(session)
    vendedor = crear_vendedor(session)
    producto = crear_producto(session, cantidad_unidad=100)
    cliente = crear_cliente(session, limite_credito=saldo * 2)
    factura = VentaService.emitir_factura(
        session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": str(saldo)}],
    )
    from app.db.models import CuentaPorCobrar

    return session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one(), admin


def _crear_cxp(session, saldo: Decimal):
    """Devuelve (cxp, admin), igual que _crear_cxc."""
    admin = crear_usuario_admin(session)
    producto = crear_producto(session, cantidad_unidad=100)
    proveedor = crear_proveedor(session, limite_credito=saldo * 2)
    compra = CompraService.registrar_compra(
        session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": str(saldo)}],
    )
    from app.db.models import CuentaPorPagar

    return session.query(CuentaPorPagar).filter_by(id_compra=compra.id_compra).one(), admin


# --- registrar_pago_cobro -----------------------------------------------------


def test_registrar_pago_cobro_por_caja(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    pago = PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("40.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    assert pago.id_pago_cobro is not None

    db_session.refresh(cxc)
    assert cxc.saldo_pendiente == Decimal("60.00")
    assert cxc.estado == "parcial"

    movimiento = db_session.query(CajaMovimiento).filter_by(id_caja=caja.id_caja).one()
    assert movimiento.tipo_movimiento == "entrada"
    assert movimiento.monto_movimiento == Decimal("40.00")
    assert movimiento.id_pago_cobro == pago.id_pago_cobro


def test_registrar_pago_cobro_sin_usuario_autorizado_falla(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    with pytest.raises(PermisoDenegadoError):
        PagoService.registrar_pago_cobro(
            db_session,
            id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
            monto=Decimal("40.00"),
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
        )


def test_registrar_pago_cobro_completo_marca_pagada(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("100.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    db_session.refresh(cxc)
    assert cxc.saldo_pendiente == Decimal("0.00")
    assert cxc.estado == "pagada"


def test_registrar_pago_cobro_por_banco_actualiza_saldo(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    cuenta = crear_cuenta_bancaria(db_session, saldo_total_banco=Decimal("500.00"))

    pago = PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("30.00"),
        metodo_pago="transferencia",
        id_cuenta_bancaria=cuenta.id_cuenta,
        id_usuario=admin.id_usuario,
    )

    db_session.refresh(cuenta)
    assert cuenta.saldo_total_banco == Decimal("530.00")

    movimiento = db_session.query(BancoMovimiento).filter_by(id_cuenta=cuenta.id_cuenta).one()
    assert movimiento.tipo_movimiento == "abono"
    assert movimiento.id_pago_cobro == pago.id_pago_cobro


def test_registrar_pago_cobro_por_banco_cuenta_inactiva_falla(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    cuenta = crear_cuenta_bancaria(db_session, estado_cuenta="INACTIVO")

    with pytest.raises(ValueError, match="inactiva"):
        PagoService.registrar_pago_cobro(
            db_session,
            id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
            monto=Decimal("30.00"),
            metodo_pago="transferencia",
            id_cuenta_bancaria=cuenta.id_cuenta,
            id_usuario=admin.id_usuario,
        )


def test_registrar_pago_cobro_por_banco_cuenta_inexistente_falla(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))

    with pytest.raises(ValueError, match="Cuenta bancaria no encontrada"):
        PagoService.registrar_pago_cobro(
            db_session,
            id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
            monto=Decimal("30.00"),
            metodo_pago="transferencia",
            id_cuenta_bancaria=999999,
            id_usuario=admin.id_usuario,
        )


def test_registrar_pago_cobro_sin_origen(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    with pytest.raises(ValueError, match="exactamente un origen"):
        PagoService.registrar_pago_cobro(
            db_session,
            id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
            monto=Decimal("10.00"),
            metodo_pago="efectivo",
            id_usuario=admin.id_usuario,
        )


def test_registrar_pago_cobro_con_dos_origenes(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)
    cuenta = crear_cuenta_bancaria(db_session)

    with pytest.raises(ValueError, match="exactamente un origen"):
        PagoService.registrar_pago_cobro(
            db_session,
            id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
            monto=Decimal("10.00"),
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
            id_cuenta_bancaria=cuenta.id_cuenta,
            id_usuario=admin.id_usuario,
        )


def test_registrar_pago_cobro_excede_saldo(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    with pytest.raises(ValueError, match="excede el saldo pendiente"):
        PagoService.registrar_pago_cobro(
            db_session,
            id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
            monto=Decimal("999.00"),
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
            id_usuario=admin.id_usuario,
        )


def test_registrar_pago_cobro_monto_invalido(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    with pytest.raises(ValueError, match="mayor a cero"):
        PagoService.registrar_pago_cobro(
            db_session,
            id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
            monto=Decimal("0.00"),
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
            id_usuario=admin.id_usuario,
        )


def test_registrar_pago_cobro_cuenta_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    with pytest.raises(ValueError, match="Cuenta por cobrar no encontrada"):
        PagoService.registrar_pago_cobro(
            db_session,
            id_cuenta_por_cobrar=999999,
            monto=Decimal("10.00"),
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
            id_usuario=admin.id_usuario,
        )


def test_registrar_pago_cobro_caja_sin_turno_abierto_falla(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    caja = crear_caja(db_session)  # nunca se abrio

    with pytest.raises(ValueError, match="no tiene un turno abierto"):
        PagoService.registrar_pago_cobro(
            db_session,
            id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
            monto=Decimal("40.00"),
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
            id_usuario=admin.id_usuario,
        )


def test_registrar_pago_cobro_caja_con_turno_ya_cerrado_falla(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)
    CajaService.cerrar_caja(db_session, caja.id_caja, id_usuario_cierre=admin.id_usuario)

    with pytest.raises(ValueError, match="no tiene un turno abierto"):
        PagoService.registrar_pago_cobro(
            db_session,
            id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
            monto=Decimal("40.00"),
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
            id_usuario=admin.id_usuario,
        )


def test_registrar_pago_cobro_guarda_moneda_y_monto_moneda_origen(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    cuenta = crear_cuenta_bancaria(db_session)

    pago = PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("40.00"),  # equivalente ya convertido a USD
        metodo_pago="zelle",
        moneda="USD",
        monto_moneda_origen=Decimal("40.00"),
        id_cuenta_bancaria=cuenta.id_cuenta,
        id_usuario=admin.id_usuario,
    )

    assert pago.moneda == "USD"
    assert pago.monto_moneda_origen == Decimal("40.00")
    assert pago.metodo_pago == "zelle"


def test_registrar_pago_cobro_moneda_por_defecto_es_usd(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    pago = PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("40.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    assert pago.moneda == "USD"
    assert pago.monto_moneda_origen is None


def test_listar_pagos_cobro(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("20.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )
    PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("30.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    pagos = PagoService.listar_pagos_cobro(db_session, cxc.id_cuenta_por_cobrar, id_usuario=admin.id_usuario)
    assert len(pagos) == 2


def test_listar_pagos_cobro_sin_usuario_autorizado_falla(db_session):
    cxc, _admin = _crear_cxc(db_session, Decimal("100.00"))
    with pytest.raises(PermisoDenegadoError):
        PagoService.listar_pagos_cobro(db_session, cxc.id_cuenta_por_cobrar)


# --- registrar_pago_proveedor --------------------------------------------------


def test_registrar_pago_proveedor_por_caja(db_session):
    cxp, admin = _crear_cxp(db_session, Decimal("80.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    pago = PagoService.registrar_pago_proveedor(
        db_session,
        id_cuenta_por_pagar=cxp.id_cuenta,
        monto=Decimal("30.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    assert pago.id_pago_proveedor is not None
    db_session.refresh(cxp)
    assert cxp.saldo_pendiente == Decimal("50.00")
    assert cxp.estado == "parcial"

    movimiento = db_session.query(CajaMovimiento).filter_by(id_caja=caja.id_caja).one()
    assert movimiento.tipo_movimiento == "salida"


def test_registrar_pago_proveedor_sin_usuario_autorizado_falla(db_session):
    cxp, admin = _crear_cxp(db_session, Decimal("80.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    with pytest.raises(PermisoDenegadoError):
        PagoService.registrar_pago_proveedor(
            db_session,
            id_cuenta_por_pagar=cxp.id_cuenta,
            monto=Decimal("30.00"),
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
        )


def test_registrar_pago_proveedor_por_banco_completo(db_session):
    cxp, admin = _crear_cxp(db_session, Decimal("80.00"))
    cuenta = crear_cuenta_bancaria(db_session, saldo_total_banco=Decimal("500.00"))

    PagoService.registrar_pago_proveedor(
        db_session,
        id_cuenta_por_pagar=cxp.id_cuenta,
        monto=Decimal("80.00"),
        metodo_pago="transferencia",
        id_cuenta_bancaria=cuenta.id_cuenta,
        id_usuario=admin.id_usuario,
    )

    db_session.refresh(cuenta)
    assert cuenta.saldo_total_banco == Decimal("420.00")

    db_session.refresh(cxp)
    assert cxp.estado == "pagada"

    movimiento = db_session.query(BancoMovimiento).filter_by(id_cuenta=cuenta.id_cuenta).one()
    assert movimiento.tipo_movimiento == "cargo"


def test_registrar_pago_proveedor_excede_saldo(db_session):
    cxp, admin = _crear_cxp(db_session, Decimal("80.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    with pytest.raises(ValueError, match="excede el saldo pendiente"):
        PagoService.registrar_pago_proveedor(
            db_session,
            id_cuenta_por_pagar=cxp.id_cuenta,
            monto=Decimal("999.00"),
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
            id_usuario=admin.id_usuario,
        )


def test_registrar_pago_proveedor_por_banco_cuenta_inactiva_falla(db_session):
    cxp, admin = _crear_cxp(db_session, Decimal("80.00"))
    cuenta = crear_cuenta_bancaria(db_session, estado_cuenta="INACTIVO")

    with pytest.raises(ValueError, match="inactiva"):
        PagoService.registrar_pago_proveedor(
            db_session,
            id_cuenta_por_pagar=cxp.id_cuenta,
            monto=Decimal("30.00"),
            metodo_pago="transferencia",
            id_cuenta_bancaria=cuenta.id_cuenta,
            id_usuario=admin.id_usuario,
        )


def test_registrar_pago_proveedor_cuenta_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    with pytest.raises(ValueError, match="Cuenta por pagar no encontrada"):
        PagoService.registrar_pago_proveedor(
            db_session,
            id_cuenta_por_pagar=999999,
            monto=Decimal("10.00"),
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
            id_usuario=admin.id_usuario,
        )


def test_listar_pagos_proveedor(db_session):
    cxp, admin = _crear_cxp(db_session, Decimal("80.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    PagoService.registrar_pago_proveedor(
        db_session,
        id_cuenta_por_pagar=cxp.id_cuenta,
        monto=Decimal("20.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )
    PagoService.registrar_pago_proveedor(
        db_session,
        id_cuenta_por_pagar=cxp.id_cuenta,
        monto=Decimal("30.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    pagos = PagoService.listar_pagos_proveedor(db_session, cxp.id_cuenta, id_usuario=admin.id_usuario)
    assert len(pagos) == 2


def test_listar_pagos_proveedor_sin_usuario_autorizado_falla(db_session):
    cxp, _admin = _crear_cxp(db_session, Decimal("80.00"))
    with pytest.raises(PermisoDenegadoError):
        PagoService.listar_pagos_proveedor(db_session, cxp.id_cuenta)


# --- el trigger sigue siendo una red de seguridad a nivel BD ------------------


def test_trigger_rechaza_pago_sin_origen_si_se_inserta_sin_pasar_por_el_service(db_session):
    """PagoService valida en Python, pero si algo inserta el modelo directamente
    (saltandose el servicio), trg_pagos_cobros_io debe seguir rechazando el insert."""
    cxc, _admin = _crear_cxc(db_session, Decimal("100.00"))

    with pytest.raises(ProgrammingError, match="indique exactamente un origen"):
        db_session.add(
            PagoCobro(id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar, metodo_pago="efectivo", monto=Decimal("10.00"))
        )
        db_session.commit()


# --- reversion automatica al borrar un pago (migrations/0001_reversion_automatica_pagos.sql) ---


def test_borrar_pago_cobro_por_caja_revierte_saldo_y_borra_movimiento(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    pago = PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("40.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )
    id_pago = pago.id_pago_cobro

    db_session.query(PagoCobro).filter_by(id_pago_cobro=id_pago).delete(synchronize_session=False)
    db_session.commit()

    db_session.refresh(cxc)
    assert cxc.saldo_pendiente == Decimal("100.00")
    assert cxc.estado == "pendiente"
    assert db_session.query(CajaMovimiento).filter_by(id_pago_cobro=id_pago).first() is None


def test_borrar_pago_cobro_por_banco_revierte_saldo_bancario_y_borra_movimiento(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    cuenta = crear_cuenta_bancaria(db_session, saldo_total_banco=Decimal("500.00"))

    pago = PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("30.00"),
        metodo_pago="transferencia",
        id_cuenta_bancaria=cuenta.id_cuenta,
        id_usuario=admin.id_usuario,
    )
    id_pago = pago.id_pago_cobro

    db_session.query(PagoCobro).filter_by(id_pago_cobro=id_pago).delete(synchronize_session=False)
    db_session.commit()

    db_session.refresh(cuenta)
    assert cuenta.saldo_total_banco == Decimal("500.00")
    assert db_session.query(BancoMovimiento).filter_by(id_pago_cobro=id_pago).first() is None


def test_borrar_pago_cobro_con_turno_de_caja_ya_cerrado_recalcula_saldo_cierre(db_session):
    """Caso limite: el pago se revierte despues de que el turno de caja donde se
    registro ya cerro. saldo_cierre se calculo una sola vez al cerrar (trg_cajas_cierre)
    y no se recalcula solo -- trg_caja_movimientos_cierre_recalc_del debe encargarse de
    eso cuando el caja_movimiento del pago se borra en cascada."""
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("50.00"))

    # fecha_pago explicita (reloj de Python, igual que fecha_apertura/fecha_cierre): si
    # se deja en None, trg_pagos_cobros_io usa GETDATE() (reloj del servidor SQL), y un
    # desfase de reloj entre app y SQL Server podria dejar el movimiento fuera del rango
    # [fecha_apertura, fecha_cierre] que usa trg_cajas_cierre para sumar el turno.
    pago = PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("40.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        fecha_pago=datetime.now(),
        id_usuario=admin.id_usuario,
    )
    id_pago = pago.id_pago_cobro

    CajaService.cerrar_caja(db_session, caja.id_caja, id_usuario_cierre=admin.id_usuario)
    db_session.refresh(caja)
    assert caja.saldo_cierre == Decimal("90.00")  # 50 de apertura + 40 de entrada

    db_session.query(PagoCobro).filter_by(id_pago_cobro=id_pago).delete(synchronize_session=False)
    db_session.commit()

    db_session.refresh(caja)
    assert caja.saldo_cierre == Decimal("50.00")  # el pago revertido ya no cuenta


def test_borrar_pago_proveedor_por_banco_revierte_saldo_bancario(db_session):
    cxp, admin = _crear_cxp(db_session, Decimal("80.00"))
    cuenta = crear_cuenta_bancaria(db_session, saldo_total_banco=Decimal("500.00"))

    pago = PagoService.registrar_pago_proveedor(
        db_session,
        id_cuenta_por_pagar=cxp.id_cuenta,
        monto=Decimal("80.00"),
        metodo_pago="transferencia",
        id_cuenta_bancaria=cuenta.id_cuenta,
        id_usuario=admin.id_usuario,
    )
    id_pago = pago.id_pago_proveedor

    db_session.query(PagoProveedor).filter_by(id_pago_proveedor=id_pago).delete(synchronize_session=False)
    db_session.commit()

    db_session.refresh(cuenta)
    assert cuenta.saldo_total_banco == Decimal("500.00")
    db_session.refresh(cxp)
    assert cxp.saldo_pendiente == Decimal("80.00")
    assert cxp.estado == "pendiente"


def test_registrar_pago_proveedor_por_caja_valida_turno_abierto(db_session):
    """Fix: PagoService.registrar_pago_proveedor debe validar que la caja tenga turno
    abierto, no solo la UI. El lock WITH (UPDLOCK, ROWLOCK) serializa pagos concurrentes
    contra la misma caja, previniendo race conditions en saldo_actual."""
    cxp, admin = _crear_cxp(db_session, Decimal("100.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("200.00"))

    # Pagar parte
    PagoService.registrar_pago_proveedor(
        db_session,
        id_cuenta_por_pagar=cxp.id_cuenta,
        monto=Decimal("40.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    # Verificar que saldo se descuento correctamente
    saldo_actual = CajaService.calcular_saldo_actual(db_session, caja.id_caja)
    assert saldo_actual == Decimal("160.00")

    # Cerrar caja
    CajaService.cerrar_caja(db_session, caja.id_caja, id_usuario_cierre=admin.id_usuario)

    # Intentar pagar contra caja cerrada - debe fallar
    with pytest.raises(ValueError, match="no tiene un turno abierto"):
        PagoService.registrar_pago_proveedor(
            db_session,
            id_cuenta_por_pagar=cxp.id_cuenta,
            monto=Decimal("30.00"),
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
            id_usuario=admin.id_usuario,
        )


def test_registrar_pago_cobro_bloquea_con_updlock_rowlock_concurrente(db_session, test_engine):
    """Auditoria de CxC (2026-08-28), hallazgo H2: _aplicar_pago_cobro leia la
    CuentaPorCobrar con session.get() sin lock -- dos cobros concurrentes contra la MISMA
    cuenta podian ambos leer el mismo saldo_pendiente antes de que ninguno commitee, pasar
    el guard "monto > saldo_pendiente" cada uno por separado y sobregirar la cuenta (el
    segundo terminaria en un RAISERROR crudo de trg_pagos_cobros_io en vez de un ValueError
    legible). Este test abre una segunda sesion real sobre test_engine (db_session no sirve
    para esto, no es segura para compartir entre threads) que sostiene el lock manualmente
    y comprueba que un registrar_pago_cobro() concurrente sobre esa MISMA cuenta se queda
    bloqueado esperando el lock, mismo patron que
    test_emitir_factura_bloquea_stock_con_updlock_rowlock_concurrente."""
    import threading

    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from app.db.models import CuentaPorCobrar

    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)
    id_cxc, id_caja, id_usuario = cxc.id_cuenta_por_cobrar, caja.id_caja, admin.id_usuario

    session_factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    sesion_bloqueadora = session_factory()
    resultado: dict = {}

    try:
        sesion_bloqueadora.execute(
            select(CuentaPorCobrar)
            .where(CuentaPorCobrar.id_cuenta_por_cobrar == id_cxc)
            .with_hint(CuentaPorCobrar, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        ).scalar_one()

        def _pagar_en_thread():
            sesion_hilo = session_factory()
            try:
                pago = PagoService.registrar_pago_cobro(
                    sesion_hilo,
                    id_cuenta_por_cobrar=id_cxc,
                    monto=Decimal("40.00"),
                    metodo_pago="efectivo",
                    id_caja=id_caja,
                    id_usuario=id_usuario,
                )
                resultado["id_pago_cobro"] = pago.id_pago_cobro
            finally:
                sesion_hilo.close()

        hilo = threading.Thread(target=_pagar_en_thread)
        hilo.start()

        # El lock sigue sostenido: registrar_pago_cobro debe seguir esperando, no adelantarse.
        hilo.join(timeout=1.5)
        assert hilo.is_alive(), "registrar_pago_cobro no se bloqueo por el UPDLOCK/ROWLOCK esperado sobre la CxC"

        # Libera el lock (rollback: esta sesion solo leyo, no debe dejar nada escrito).
        sesion_bloqueadora.rollback()

        hilo.join(timeout=10)
        assert not hilo.is_alive(), "registrar_pago_cobro no continuo tras liberarse el lock"
        assert "id_pago_cobro" in resultado
    finally:
        sesion_bloqueadora.close()

    db_session.refresh(cxc)
    assert cxc.saldo_pendiente == Decimal("60.00")


# --- listar_cuentas_por_cobrar --------------------------------------------------


def test_listar_cuentas_por_cobrar_sin_filtro(db_session):
    cxc1, admin = _crear_cxc(db_session, Decimal("100.00"))
    cxc2, _ = _crear_cxc(db_session, Decimal("50.00"))

    resultado = PagoService.listar_cuentas_por_cobrar(db_session, id_usuario=admin.id_usuario)

    assert resultado["total"] == 2
    assert {c.id_cuenta_por_cobrar for c in resultado["items"]} == {
        cxc1.id_cuenta_por_cobrar,
        cxc2.id_cuenta_por_cobrar,
    }


def test_listar_cuentas_por_cobrar_filtra_por_cliente(db_session):
    cxc1, admin = _crear_cxc(db_session, Decimal("100.00"))
    _crear_cxc(db_session, Decimal("50.00"))
    id_cliente = cxc1.factura.id_cliente_factura

    resultado = PagoService.listar_cuentas_por_cobrar(db_session, id_cliente=id_cliente, id_usuario=admin.id_usuario)

    assert resultado["total"] == 1
    assert resultado["items"][0].id_cuenta_por_cobrar == cxc1.id_cuenta_por_cobrar


def test_listar_cuentas_por_cobrar_filtra_por_estado_vencida(db_session):
    from datetime import date, timedelta

    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    cxc.fecha_vencimiento = date.today() - timedelta(days=5)
    db_session.commit()

    resultado_vencida = PagoService.listar_cuentas_por_cobrar(db_session, estado="vencida", id_usuario=admin.id_usuario)
    assert resultado_vencida["total"] == 1
    assert resultado_vencida["items"][0].estado_visual == "vencida"

    resultado_pendiente = PagoService.listar_cuentas_por_cobrar(
        db_session, estado="pendiente", id_usuario=admin.id_usuario
    )
    assert resultado_pendiente["total"] == 0


def test_listar_cuentas_por_cobrar_filtra_por_estado_pagada(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)
    PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("100.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    resultado = PagoService.listar_cuentas_por_cobrar(db_session, estado="pagada", id_usuario=admin.id_usuario)

    assert resultado["total"] == 1
    assert resultado["items"][0].estado_visual == "pagada"


def test_listar_cuentas_por_cobrar_sin_usuario_autorizado_falla(db_session):
    _crear_cxc(db_session, Decimal("100.00"))
    with pytest.raises(PermisoDenegadoError):
        PagoService.listar_cuentas_por_cobrar(db_session)
