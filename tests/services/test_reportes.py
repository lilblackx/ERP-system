from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.db.models import Caja, CuentaPorCobrar
from app.services.pagos import PagoService
from app.services.permisos import PermisoDenegadoError
from app.services.reportes import ReporteService
from app.services.tesoreria import CajaService
from app.services.ventas import VentaService
from tests.factories import crear_caja, crear_cliente, crear_producto, crear_usuario_admin, crear_vendedor

# --- aging_cuentas_por_cobrar ------------------------------------------------------


def _factura_a_credito(session, admin, cliente, total, fecha_vencimiento):
    vendedor = crear_vendedor(session)
    producto = crear_producto(session, cantidad_unidad=1000)
    return VentaService.emitir_factura(
        session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": str(total)}],
        fecha_vencimiento=fecha_vencimiento,
    )


def test_aging_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ReporteService.aging_cuentas_por_cobrar(db_session, id_usuario=None)


def test_aging_orden_invalido_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="orden invalido"):
        ReporteService.aging_cuentas_por_cobrar(db_session, id_usuario=admin.id_usuario, orden="columna_inventada")


def test_aging_sin_cuentas_abiertas(db_session):
    admin = crear_usuario_admin(db_session)
    resultado = ReporteService.aging_cuentas_por_cobrar(db_session, id_usuario=admin.id_usuario)
    assert resultado["filas"] == []
    assert resultado["total_general"] == Decimal("0.00")


def test_aging_clasifica_por_bucket_segun_dias_vencidos(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    hoy = date.today()

    _factura_a_credito(db_session, admin, cliente, "80.00", hoy + timedelta(days=5))  # vigente
    _factura_a_credito(db_session, admin, cliente, "50.00", hoy - timedelta(days=10))  # 1-30
    _factura_a_credito(db_session, admin, cliente, "30.00", hoy - timedelta(days=45))  # 31-60

    resultado = ReporteService.aging_cuentas_por_cobrar(db_session, id_usuario=admin.id_usuario, fecha_corte=hoy)

    buckets = {f["bucket"] for f in resultado["filas"]}
    assert buckets == {"vigente", "1-30", "31-60"}
    assert resultado["totales_por_bucket"]["1-30"] == Decimal("50.00")
    assert resultado["totales_por_bucket"]["31-60"] == Decimal("30.00")
    assert resultado["total_general"] == Decimal("160.00")


def test_aging_excluye_cuentas_pagadas_por_completo(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    factura = _factura_a_credito(db_session, admin, cliente, "40.00", date.today() - timedelta(days=5))
    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()

    PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto="40.00",
        metodo_pago="efectivo",
        id_caja=crear_caja(db_session).id_caja,
        id_usuario=admin.id_usuario,
    )

    resultado = ReporteService.aging_cuentas_por_cobrar(db_session, id_usuario=admin.id_usuario)
    assert resultado["filas"] == []


def test_aging_filtra_por_cliente(db_session):
    admin = crear_usuario_admin(db_session)
    cliente_a = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    cliente_b = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    _factura_a_credito(db_session, admin, cliente_a, "70.00", date.today() - timedelta(days=5))
    _factura_a_credito(db_session, admin, cliente_b, "20.00", date.today() - timedelta(days=5))

    resultado = ReporteService.aging_cuentas_por_cobrar(
        db_session, id_usuario=admin.id_usuario, id_cliente=cliente_a.id_cliente
    )

    assert len(resultado["filas"]) == 1
    assert resultado["filas"][0]["cliente"] == cliente_a.nombre_razon_social


def test_aging_orden_por_saldo_pendiente(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    vencimiento = date.today() - timedelta(days=5)
    _factura_a_credito(db_session, admin, cliente, "90.00", vencimiento)
    _factura_a_credito(db_session, admin, cliente, "10.00", vencimiento)

    resultado = ReporteService.aging_cuentas_por_cobrar(
        db_session, id_usuario=admin.id_usuario, orden="saldo_pendiente"
    )

    saldos = [f["saldo_pendiente"] for f in resultado["filas"]]
    assert saldos == sorted(saldos)


# --- arqueo_caja --------------------------------------------------------------------


def test_arqueo_caja_sin_usuario_autorizado_falla(db_session):
    caja = crear_caja(db_session)
    with pytest.raises(PermisoDenegadoError):
        ReporteService.arqueo_caja(db_session, id_usuario=None, id_caja=caja.id_caja)


def test_arqueo_caja_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Caja no encontrada"):
        ReporteService.arqueo_caja(db_session, id_usuario=admin.id_usuario, id_caja=999999)


def test_arqueo_caja_nunca_abierta_falla(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)
    with pytest.raises(ValueError, match="nunca se ha abierto"):
        ReporteService.arqueo_caja(db_session, id_usuario=admin.id_usuario, id_caja=caja.id_caja)


def test_arqueo_caja_calcula_saldo_esperado_y_diferencia(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("100.00"))
    CajaService.registrar_movimiento_manual(
        db_session, caja.id_caja, "entrada", Decimal("50.00"), "Venta contado", admin.id_usuario
    )
    CajaService.registrar_movimiento_manual(
        db_session, caja.id_caja, "salida", Decimal("20.00"), "Compra insumos", admin.id_usuario
    )
    CajaService.cerrar_caja(db_session, caja.id_caja, id_usuario_cierre=admin.id_usuario)
    # saldo_cierre lo deja el usuario/proceso de cierre real; se fuerza aca para probar
    # el calculo de diferencia contra un valor que no coincide con lo esperado (130.00).
    caja_db = db_session.get(Caja, caja.id_caja)
    caja_db.saldo_cierre = Decimal("125.00")
    db_session.commit()

    resultado = ReporteService.arqueo_caja(db_session, id_usuario=admin.id_usuario, id_caja=caja.id_caja)

    assert resultado["total_entradas"] == Decimal("50.00")
    assert resultado["total_salidas"] == Decimal("20.00")
    assert resultado["saldo_esperado"] == Decimal("130.00")
    assert resultado["diferencia"] == Decimal("-5.00")
    assert len(resultado["movimientos"]) == 2


def test_arqueo_caja_incluye_movimientos_generados_por_pagos(db_session):
    """Un cobro con id_caja no crea CajaMovimiento explicito en pagos.py -- lo hace el
    trigger trg_pagos_cobros_io (INSTEAD OF INSERT). El arqueo debe verlo igual."""
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("0.00"))

    factura = _factura_a_credito(db_session, admin, cliente, "60.00", date.today())
    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()

    PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto="60.00",
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    resultado = ReporteService.arqueo_caja(db_session, id_usuario=admin.id_usuario, id_caja=caja.id_caja)

    assert resultado["total_entradas"] == Decimal("60.00")
    assert resultado["saldo_esperado"] == Decimal("60.00")
