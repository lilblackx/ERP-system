from decimal import Decimal

import pytest

from app.services.tesoreria import BancoService, CajaService
from tests.factories import crear_banco, crear_caja, crear_cuenta_bancaria


# --- BancoService ---------------------------------------------------------


def test_crear_banco_y_listar(db_session):
    crear_banco(db_session, nombre_banco="Banco Z")
    crear_banco(db_session, nombre_banco="Banco A")

    bancos = BancoService.listar_bancos(db_session)

    assert [b.nombre_banco for b in bancos] == ["Banco A", "Banco Z"]


def test_actualizar_banco_inexistente(db_session):
    with pytest.raises(ValueError, match="Banco no encontrado"):
        BancoService.actualizar_banco(db_session, 999999, nombre_banco="X")


def test_eliminar_banco(db_session):
    banco = crear_banco(db_session)
    BancoService.eliminar_banco(db_session, banco.id_banco)
    assert BancoService.listar_bancos(db_session) == []


def test_crear_cuenta_banco_inexistente(db_session):
    with pytest.raises(ValueError, match="Banco no encontrado"):
        BancoService.crear_cuenta(db_session, id_banco=999999, numero_cuenta="123")


def test_crear_cuenta_ok(db_session):
    banco = crear_banco(db_session)
    cuenta = BancoService.crear_cuenta(db_session, id_banco=banco.id_banco, numero_cuenta="0123456789")
    assert cuenta.id_cuenta is not None
    assert cuenta.saldo_total_banco == Decimal("0.00")


def test_actualizar_cuenta_inexistente(db_session):
    with pytest.raises(ValueError, match="Cuenta bancaria no encontrada"):
        BancoService.actualizar_cuenta(db_session, 999999, nombre_titular="X")


def test_eliminar_cuenta(db_session):
    cuenta = crear_cuenta_bancaria(db_session)
    BancoService.eliminar_cuenta(db_session, cuenta.id_cuenta)
    assert BancoService.listar_cuentas(db_session) == []


def test_obtener_resumen_cuentas_enmascara_numero(db_session):
    crear_cuenta_bancaria(db_session, numero_cuenta="01021234567890123456")

    resumen = BancoService.obtener_resumen_cuentas(db_session)

    assert len(resumen) == 1
    numero_enmascarado = resumen[0]["numero_cuenta"]
    assert numero_enmascarado.endswith("3456")
    assert numero_enmascarado.startswith("*")
    assert "0102" not in numero_enmascarado


def test_obtener_movimientos_tipo_invalido(db_session):
    with pytest.raises(ValueError, match="tipo_movimiento invalido"):
        BancoService.obtener_movimientos(db_session, tipo_movimiento="no_existe")


# --- CajaService ------------------------------------------------------------


def test_abrir_caja(db_session):
    caja = crear_caja(db_session)
    abierta = CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=None, saldo_apertura=Decimal("100.00"))

    assert abierta.estado_caja == "ABIERTA"
    assert abierta.saldo_apertura == Decimal("100.00")
    assert abierta.fecha_apertura is not None
    assert abierta.fecha_cierre is None


def test_abrir_caja_inexistente(db_session):
    with pytest.raises(ValueError, match="Caja no encontrada"):
        CajaService.abrir_caja(db_session, 999999, id_usuario=None, saldo_apertura=0)


def test_abrir_caja_ya_abierta(db_session):
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=None, saldo_apertura=0)

    with pytest.raises(ValueError, match="ya esta abierta"):
        CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=None, saldo_apertura=0)


def test_cerrar_caja_sin_turno_abierto(db_session):
    caja = crear_caja(db_session)
    with pytest.raises(ValueError, match="no tiene un turno abierto"):
        CajaService.cerrar_caja(db_session, caja.id_caja, id_usuario_cierre=None)


def test_cerrar_caja_calcula_saldo_con_movimientos(db_session):
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=None, saldo_apertura=Decimal("100.00"))

    CajaService.registrar_movimiento_manual(
        db_session, caja.id_caja, tipo="entrada", monto=Decimal("50.00"), descripcion="Ingreso", id_usuario=None
    )
    CajaService.registrar_movimiento_manual(
        db_session, caja.id_caja, tipo="salida", monto=Decimal("20.00"), descripcion="Egreso", id_usuario=None
    )

    cerrada = CajaService.cerrar_caja(db_session, caja.id_caja, id_usuario_cierre=None)

    assert cerrada.estado_caja == "CERRADA"
    assert cerrada.saldo_cierre == Decimal("130.00")  # 100 + 50 - 20


def test_registrar_movimiento_manual_tipo_invalido(db_session):
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=None, saldo_apertura=0)

    with pytest.raises(ValueError, match="tipo invalido"):
        CajaService.registrar_movimiento_manual(
            db_session, caja.id_caja, tipo="otro", monto=10, descripcion=None, id_usuario=None
        )


def test_registrar_movimiento_manual_monto_invalido(db_session):
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=None, saldo_apertura=0)

    with pytest.raises(ValueError, match="mayor a cero"):
        CajaService.registrar_movimiento_manual(
            db_session, caja.id_caja, tipo="entrada", monto=0, descripcion=None, id_usuario=None
        )


def test_registrar_movimiento_manual_caja_sin_turno(db_session):
    caja = crear_caja(db_session)
    with pytest.raises(ValueError, match="no tiene un turno abierto"):
        CajaService.registrar_movimiento_manual(
            db_session, caja.id_caja, tipo="entrada", monto=10, descripcion=None, id_usuario=None
        )


def test_obtener_estado_cajas(db_session):
    caja = crear_caja(db_session, nombre_caja="Caja 1")
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=None, saldo_apertura=Decimal("50.00"))

    estado = CajaService.obtener_estado_cajas(db_session)

    assert len(estado) == 1
    assert estado[0]["estado"] == "ABIERTA"
    assert estado[0]["saldo_apertura"] == Decimal("50.00")
