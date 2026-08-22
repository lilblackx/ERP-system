from decimal import Decimal

import pytest

from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import BancoService, CajaService
from tests.factories import crear_banco, crear_caja, crear_cuenta_bancaria, crear_usuario_admin


# --- BancoService ---------------------------------------------------------


def test_crear_banco_y_listar(db_session):
    admin = crear_usuario_admin(db_session)
    crear_banco(db_session, nombre_banco="Banco Z")
    crear_banco(db_session, nombre_banco="Banco A")

    bancos = BancoService.listar_bancos(db_session, id_usuario=admin.id_usuario)

    assert [b.nombre_banco for b in bancos if b.nombre_banco in ("Banco A", "Banco Z")] == ["Banco A", "Banco Z"]


def test_listar_bancos_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        BancoService.listar_bancos(db_session)


def test_crear_banco_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        BancoService.crear_banco(db_session, nombre_banco="Banco Z")


def test_actualizar_banco_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Banco no encontrado"):
        BancoService.actualizar_banco(db_session, 999999, id_usuario=admin.id_usuario, nombre_banco="X")


def test_eliminar_banco_siempre_falla_para_proteger_integridad(db_session):
    admin = crear_usuario_admin(db_session)
    banco = crear_banco(db_session)
    with pytest.raises(ValueError, match="No se puede eliminar"):
        BancoService.eliminar_banco(db_session, banco.id_banco, id_usuario=admin.id_usuario)
    assert len(BancoService.listar_bancos(db_session, id_usuario=admin.id_usuario)) == 1


def test_cambiar_estado_banco_desactiva(db_session):
    admin = crear_usuario_admin(db_session)
    banco = crear_banco(db_session)

    actualizado = BancoService.cambiar_estado_banco(db_session, banco.id_banco, "INACTIVO", id_usuario=admin.id_usuario)

    assert actualizado.estado_banco == "INACTIVO"


def test_cambiar_estado_banco_estado_invalido(db_session):
    admin = crear_usuario_admin(db_session)
    banco = crear_banco(db_session)

    with pytest.raises(ValueError, match="nuevo_estado"):
        BancoService.cambiar_estado_banco(db_session, banco.id_banco, "BLOQUEADO", id_usuario=admin.id_usuario)


def test_cambiar_estado_banco_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Banco no encontrado"):
        BancoService.cambiar_estado_banco(db_session, 999999, "INACTIVO", id_usuario=admin.id_usuario)


def test_cambiar_estado_banco_sin_usuario_autorizado_falla(db_session):
    banco = crear_banco(db_session)
    with pytest.raises(PermisoDenegadoError):
        BancoService.cambiar_estado_banco(db_session, banco.id_banco, "INACTIVO")


def test_crear_cuenta_banco_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Banco no encontrado"):
        BancoService.crear_cuenta(db_session, id_banco=999999, numero_cuenta="123", creado_por=admin.id_usuario)


def test_crear_cuenta_ok(db_session):
    admin = crear_usuario_admin(db_session)
    banco = crear_banco(db_session)
    cuenta = BancoService.crear_cuenta(
        db_session, id_banco=banco.id_banco, numero_cuenta="0123456789", creado_por=admin.id_usuario
    )
    assert cuenta.id_cuenta is not None
    assert cuenta.saldo_total_banco == Decimal("0.00")


def test_actualizar_cuenta_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Cuenta bancaria no encontrada"):
        BancoService.actualizar_cuenta(db_session, 999999, id_usuario=admin.id_usuario, nombre_titular="X")


def test_eliminar_cuenta_siempre_falla_para_proteger_integridad(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session)
    with pytest.raises(ValueError, match="No se puede eliminar"):
        BancoService.eliminar_cuenta(db_session, cuenta.id_cuenta, id_usuario=admin.id_usuario)
    assert len(BancoService.listar_cuentas(db_session, id_usuario=admin.id_usuario)) == 1


def test_cambiar_estado_cuenta_desactiva(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session)

    actualizada = BancoService.cambiar_estado_cuenta(db_session, cuenta.id_cuenta, "INACTIVO", id_usuario=admin.id_usuario)

    assert actualizada.estado_cuenta == "INACTIVO"


def test_cambiar_estado_cuenta_estado_invalido(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session)

    with pytest.raises(ValueError, match="nuevo_estado"):
        BancoService.cambiar_estado_cuenta(db_session, cuenta.id_cuenta, "BLOQUEADO", id_usuario=admin.id_usuario)


def test_cambiar_estado_cuenta_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Cuenta bancaria no encontrada"):
        BancoService.cambiar_estado_cuenta(db_session, 999999, "INACTIVO", id_usuario=admin.id_usuario)


def test_cambiar_estado_cuenta_sin_usuario_autorizado_falla(db_session):
    cuenta = crear_cuenta_bancaria(db_session)
    with pytest.raises(PermisoDenegadoError):
        BancoService.cambiar_estado_cuenta(db_session, cuenta.id_cuenta, "INACTIVO")


def test_obtener_resumen_cuentas_enmascara_numero(db_session):
    admin = crear_usuario_admin(db_session)
    crear_cuenta_bancaria(db_session, numero_cuenta="01021234567890123456")

    resumen = BancoService.obtener_resumen_cuentas(db_session, id_usuario=admin.id_usuario)

    assert len(resumen) == 1
    numero_enmascarado = resumen[0]["numero_cuenta"]
    assert numero_enmascarado.endswith("3456")
    assert numero_enmascarado.startswith("*")
    assert "0102" not in numero_enmascarado


def test_obtener_movimientos_tipo_invalido(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="tipo_movimiento invalido"):
        BancoService.obtener_movimientos(db_session, tipo_movimiento="no_existe", id_usuario=admin.id_usuario)


def test_obtener_movimientos_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        BancoService.obtener_movimientos(db_session)


# --- CajaService ------------------------------------------------------------


def test_abrir_caja(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)
    abierta = CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("100.00"))

    assert abierta.estado_caja == "ABIERTA"
    assert abierta.saldo_apertura == Decimal("100.00")
    assert abierta.fecha_apertura is not None
    assert abierta.fecha_cierre is None


def test_abrir_caja_sin_usuario_autorizado_falla(db_session):
    caja = crear_caja(db_session)
    with pytest.raises(PermisoDenegadoError):
        CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=None, saldo_apertura=Decimal("100.00"))


def test_abrir_caja_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Caja no encontrada"):
        CajaService.abrir_caja(db_session, 999999, id_usuario=admin.id_usuario, saldo_apertura=0)


def test_abrir_caja_ya_abierta(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    with pytest.raises(ValueError, match="ya esta abierta"):
        CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)


def test_cerrar_caja_sin_turno_abierto(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)
    with pytest.raises(ValueError, match="no tiene un turno abierto"):
        CajaService.cerrar_caja(db_session, caja.id_caja, id_usuario_cierre=admin.id_usuario)


def test_cerrar_caja_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    with pytest.raises(PermisoDenegadoError):
        CajaService.cerrar_caja(db_session, caja.id_caja, id_usuario_cierre=None)


def test_cerrar_caja_calcula_saldo_con_movimientos(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("100.00"))

    CajaService.registrar_movimiento_manual(
        db_session, caja.id_caja, tipo="entrada", monto=Decimal("50.00"), descripcion="Ingreso", id_usuario=admin.id_usuario
    )
    CajaService.registrar_movimiento_manual(
        db_session, caja.id_caja, tipo="salida", monto=Decimal("20.00"), descripcion="Egreso", id_usuario=admin.id_usuario
    )

    cerrada = CajaService.cerrar_caja(db_session, caja.id_caja, id_usuario_cierre=admin.id_usuario)

    assert cerrada.estado_caja == "CERRADA"
    assert cerrada.saldo_cierre == Decimal("130.00")  # 100 + 50 - 20


def test_registrar_movimiento_manual_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    with pytest.raises(PermisoDenegadoError):
        CajaService.registrar_movimiento_manual(
            db_session, caja.id_caja, tipo="entrada", monto=10, descripcion=None, id_usuario=None
        )


def test_registrar_movimiento_manual_tipo_invalido(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    with pytest.raises(ValueError, match="tipo invalido"):
        CajaService.registrar_movimiento_manual(
            db_session, caja.id_caja, tipo="otro", monto=10, descripcion=None, id_usuario=admin.id_usuario
        )


def test_registrar_movimiento_manual_monto_invalido(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    with pytest.raises(ValueError, match="mayor a cero"):
        CajaService.registrar_movimiento_manual(
            db_session, caja.id_caja, tipo="entrada", monto=0, descripcion=None, id_usuario=admin.id_usuario
        )


def test_registrar_movimiento_manual_caja_sin_turno(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)
    with pytest.raises(ValueError, match="no tiene un turno abierto"):
        CajaService.registrar_movimiento_manual(
            db_session, caja.id_caja, tipo="entrada", monto=10, descripcion=None, id_usuario=admin.id_usuario
        )


def test_obtener_estado_cajas(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session, nombre_caja="Caja 1")
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("50.00"))

    estado = CajaService.obtener_estado_cajas(db_session, id_usuario=admin.id_usuario)

    fila = next(e for e in estado if e["id_caja"] == caja.id_caja)
    assert fila["estado"] == "ABIERTA"
    assert fila["saldo_apertura"] == Decimal("50.00")


def test_obtener_estado_cajas_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        CajaService.obtener_estado_cajas(db_session)
