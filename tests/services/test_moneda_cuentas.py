"""Moneda de la cuenta bancaria (VES / USD / COP): una cuenta solo recibe pagos en su moneda.

Zelle/Binance van a cuentas en dolares, un pago en pesos a una cuenta en pesos y el resto de los metodos bancarios
(transferencia, punto de venta, pago movil) a cuentas en bolivares. El efectivo no usa cuenta bancaria.
"""

from decimal import Decimal

import pytest

from app.services.cuentas_bancarias import CuentaBancariaService
from app.services.moneda_cuentas import (
    filtrar_cuentas_por_metodo,
    moneda_pago_por_tasa,
    moneda_para_metodo,
    nombre_moneda,
)
from app.services.pagos import PagoService
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import BancoService, CajaService
from tests.factories import (
    crear_banco,
    crear_caja,
    crear_cliente,
    crear_cuenta_bancaria,
    crear_usuario_admin,
)
from tests.services.test_pagos import _crear_cxc, _crear_facturas_cliente_cxc

# -- Regla pura -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("metodo", "moneda_pago", "esperada"),
    [
        ("zelle", None, "USD"),
        ("binance", None, "USD"),
        ("zelle", "USD", "USD"),
        ("binance", "USDT", "USD"),
        ("transferencia", None, "VES"),
        ("punto_de_venta", None, "VES"),
        ("pago_movil", None, "VES"),
        # los cobros a clientes registran el monto en USD aunque se pague por transferencia en bolivares
        ("transferencia", "USD", "VES"),
        ("transferencia", "VES", "VES"),
        ("transferencia", "COP", "COP"),
        ("zelle", "COP", "COP"),
        (None, None, "VES"),
    ],
)
def test_moneda_que_debe_tener_la_cuenta_segun_el_pago(metodo, moneda_pago, esperada):
    assert moneda_para_metodo(metodo, moneda_pago) == esperada


def test_la_tasa_cop_del_combo_marca_el_pago_en_pesos():
    assert moneda_pago_por_tasa("COP: 4,000.00") == "COP"
    assert moneda_pago_por_tasa("cop: 4000") == "COP"
    assert moneda_pago_por_tasa("BCV: 897.54") is None
    assert moneda_pago_por_tasa("Paralelo: 1,035.00") is None
    assert moneda_pago_por_tasa(None) is None
    assert moneda_pago_por_tasa("-- Seleccionar --") is None


def test_filtrar_cuentas_por_metodo_deja_solo_las_de_la_moneda_del_pago():
    class _C:
        def __init__(self, moneda):
            self.moneda = moneda

    ves, usd, cop, sin_moneda = _C("VES"), _C("USD"), _C("COP"), _C(None)
    todas = [ves, usd, cop, sin_moneda]

    assert filtrar_cuentas_por_metodo(todas, "zelle") == [usd]
    assert filtrar_cuentas_por_metodo(todas, "transferencia") == [ves, sin_moneda]  # sin moneda = bolivares
    assert filtrar_cuentas_por_metodo(todas, "transferencia", "COP") == [cop]


def test_nombres_de_moneda_para_los_mensajes():
    assert "USD" in nombre_moneda("USD")
    assert "VES" in nombre_moneda("VES")
    assert "COP" in nombre_moneda("COP")


# -- Cuenta bancaria con moneda -----------------------------------------------------------------------------------


def _datos_cuenta(banco, admin, **extra):
    datos = {
        "id_banco": banco.id_banco,
        "numero_cuenta": "0134000000000001",
        "tipo_cuenta_banco": "CORRIENTE",
        "nombre_titular": "Distribuidora DJ",
        "identificacion_titular": "J-12345678-9",
        "creado_por": admin.id_usuario,
    }
    datos.update(extra)
    return datos


def test_una_cuenta_nueva_sin_moneda_queda_en_bolivares(db_session):
    admin = crear_usuario_admin(db_session)
    banco = crear_banco(db_session)

    cuenta = CuentaBancariaService.crear(db_session, **_datos_cuenta(banco, admin))

    assert cuenta.moneda == "VES"


@pytest.mark.parametrize("moneda", ["VES", "USD", "COP"])
def test_se_puede_crear_una_cuenta_en_cada_moneda(db_session, moneda):
    admin = crear_usuario_admin(db_session)
    banco = crear_banco(db_session)

    cuenta = CuentaBancariaService.crear(db_session, **_datos_cuenta(banco, admin, moneda=moneda))

    assert cuenta.moneda == moneda


def test_una_moneda_invalida_se_rechaza(db_session):
    admin = crear_usuario_admin(db_session)
    banco = crear_banco(db_session)

    with pytest.raises(ValueError, match="moneda"):
        CuentaBancariaService.crear(db_session, **_datos_cuenta(banco, admin, moneda="EUR"))


def test_la_moneda_de_una_cuenta_sin_movimientos_se_puede_cambiar(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session)

    actualizada = CuentaBancariaService.actualizar(
        db_session, cuenta.id_cuenta, id_usuario=admin.id_usuario, moneda="USD"
    )

    assert actualizada.moneda == "USD"


def _cuenta_con_historial(db_session, admin, moneda="VES", abonos=1):
    from app.services.banco_movimientos import BancoMovimientoService

    cuenta = crear_cuenta_bancaria(db_session, moneda=moneda)
    for _ in range(abonos):
        BancoMovimientoService.crear(db_session, cuenta.id_cuenta, "abono", 10.00, id_usuario=admin.id_usuario)
    return cuenta


def test_cambiar_la_moneda_de_una_cuenta_con_movimientos_exige_confirmacion_explicita(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = _cuenta_con_historial(db_session, admin)

    with pytest.raises(ValueError, match="confirmación"):
        CuentaBancariaService.actualizar(db_session, cuenta.id_cuenta, id_usuario=admin.id_usuario, moneda="USD")

    db_session.rollback()
    assert db_session.get(type(cuenta), cuenta.id_cuenta).moneda == "VES"


def test_un_admin_confirmando_cambia_la_moneda_con_historial_y_queda_auditado(db_session):
    from app.db.models import Auditoria

    admin = crear_usuario_admin(db_session)
    cuenta = _cuenta_con_historial(db_session, admin, abonos=3)

    actualizada = CuentaBancariaService.actualizar(
        db_session, cuenta.id_cuenta, id_usuario=admin.id_usuario, moneda="USD", confirmar_cambio_moneda=True
    )

    assert actualizada.moneda == "USD"
    evento = db_session.query(Auditoria).filter_by(accion="CAMBIAR_MONEDA_CUENTA_BANCARIA").one()
    assert evento.id_usuario == admin.id_usuario
    detalle = evento.detalle if isinstance(evento.detalle, str) else str(evento.detalle)
    assert '"moneda_anterior": "VES"' in detalle and '"moneda_nueva": "USD"' in detalle
    assert '"movimientos": 3' in detalle


def test_quien_no_es_admin_no_puede_cambiar_la_moneda_con_historial_ni_confirmando(db_session):
    from tests.factories import asignar_permiso, crear_permiso, crear_rol, crear_usuario

    admin = crear_usuario_admin(db_session)
    cuenta = _cuenta_con_historial(db_session, admin)
    rol = crear_rol(db_session, nombre="CONTADOR")
    asignar_permiso(db_session, rol, crear_permiso(db_session, recurso="bancos", accion="editar"))
    contador = crear_usuario(db_session, id_rol=rol.id_rol)

    with pytest.raises(PermisoDenegadoError, match="administrador"):
        CuentaBancariaService.actualizar(
            db_session, cuenta.id_cuenta, id_usuario=contador.id_usuario, moneda="USD", confirmar_cambio_moneda=True
        )

    db_session.rollback()
    assert db_session.get(type(cuenta), cuenta.id_cuenta).moneda == "VES"


def test_el_resumen_de_uso_cuenta_movimientos_y_pagos_por_metodo(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    cuenta = crear_cuenta_bancaria(db_session, moneda="USD")
    for _ in range(2):
        PagoService.registrar_pago_cobro(
            db_session,
            id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
            monto=Decimal("10.00"),
            metodo_pago="zelle",
            id_cuenta_bancaria=cuenta.id_cuenta,
            tasa_cambio=Decimal("40.00"),
            id_usuario=admin.id_usuario,
        )

    resumen = CuentaBancariaService.resumen_uso(db_session, cuenta.id_cuenta, id_usuario=admin.id_usuario)

    assert resumen == {"movimientos": 2, "por_metodo": {"zelle": 2}}


def test_el_resumen_de_una_cuenta_sin_uso_esta_vacio(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session)

    assert CuentaBancariaService.resumen_uso(db_session, cuenta.id_cuenta, id_usuario=admin.id_usuario) == {
        "movimientos": 0,
        "por_metodo": {},
    }


def test_actualizar_con_la_misma_moneda_en_una_cuenta_con_movimientos_no_falla(db_session):
    from app.services.banco_movimientos import BancoMovimientoService

    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session, moneda="USD")
    BancoMovimientoService.crear(db_session, cuenta.id_cuenta, "abono", 10.00, id_usuario=admin.id_usuario)

    actualizada = CuentaBancariaService.actualizar(
        db_session, cuenta.id_cuenta, id_usuario=admin.id_usuario, moneda="USD", nombre_titular="Otro Titular"
    )

    assert actualizada.nombre_titular == "Otro Titular"
    assert actualizada.moneda == "USD"


def test_listar_cuentas_filtra_por_moneda(db_session):
    admin = crear_usuario_admin(db_session)
    ves = crear_cuenta_bancaria(db_session)
    usd = crear_cuenta_bancaria(db_session, moneda="USD")
    cop = crear_cuenta_bancaria(db_session, moneda="COP")

    solo_usd = BancoService.listar_cuentas(db_session, id_usuario=admin.id_usuario, moneda="USD")
    todas = BancoService.listar_cuentas(db_session, id_usuario=admin.id_usuario)

    assert [c.id_cuenta for c in solo_usd] == [usd.id_cuenta]
    assert {c.id_cuenta for c in todas} == {ves.id_cuenta, usd.id_cuenta, cop.id_cuenta}


def test_la_base_rechaza_una_moneda_fuera_de_las_tres(db_session):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        crear_cuenta_bancaria(db_session, moneda="EUR")
    db_session.rollback()


# -- Validador: pago vs moneda de la cuenta -----------------------------------------------------------------------


def test_zelle_a_una_cuenta_en_bolivares_se_rechaza_con_un_mensaje_claro(db_session):
    cuenta = crear_cuenta_bancaria(db_session)

    with pytest.raises(ValueError, match=r"zelle.*dólares.*bolívares"):
        BancoService.validar_cuenta_para_pago(db_session, cuenta.id_cuenta, "zelle")


def test_transferencia_a_una_cuenta_en_dolares_se_rechaza(db_session):
    cuenta = crear_cuenta_bancaria(db_session, moneda="USD")

    with pytest.raises(ValueError, match=r"transferencia.*bolívares.*dólares"):
        BancoService.validar_cuenta_para_pago(db_session, cuenta.id_cuenta, "transferencia")


def test_cada_pago_acepta_la_cuenta_de_su_moneda(db_session):
    ves = crear_cuenta_bancaria(db_session)
    usd = crear_cuenta_bancaria(db_session, moneda="USD")
    cop = crear_cuenta_bancaria(db_session, moneda="COP")

    BancoService.validar_cuenta_para_pago(db_session, ves.id_cuenta, "transferencia")
    BancoService.validar_cuenta_para_pago(db_session, usd.id_cuenta, "zelle")
    BancoService.validar_cuenta_para_pago(db_session, usd.id_cuenta, "binance")
    BancoService.validar_cuenta_para_pago(db_session, cop.id_cuenta, "transferencia", "COP")
    with pytest.raises(ValueError):
        BancoService.validar_cuenta_para_pago(db_session, ves.id_cuenta, "transferencia", "COP")


def test_sin_cuenta_bancaria_no_se_valida_nada(db_session):
    BancoService.validar_cuenta_para_pago(db_session, None, "efectivo")


# -- Los servicios de cobro usan el validador ---------------------------------------------------------------------


def test_registrar_pago_cobro_por_zelle_a_cuenta_en_bolivares_falla_y_no_deja_pago(db_session):
    from app.db.models import PagoCobro

    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    cuenta_ves = crear_cuenta_bancaria(db_session)

    with pytest.raises(ValueError, match="dólares"):
        PagoService.registrar_pago_cobro(
            db_session,
            id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
            monto=Decimal("10.00"),
            metodo_pago="zelle",
            id_cuenta_bancaria=cuenta_ves.id_cuenta,
            tasa_cambio=Decimal("40.00"),
            id_usuario=admin.id_usuario,
        )

    db_session.rollback()
    assert db_session.query(PagoCobro).count() == 0


def test_registrar_pago_cobro_por_transferencia_a_cuenta_en_bolivares_funciona(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    cuenta = crear_cuenta_bancaria(db_session)

    pago = PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("10.00"),
        metodo_pago="transferencia",
        id_cuenta_bancaria=cuenta.id_cuenta,
        tasa_cambio=Decimal("40.00"),
        id_usuario=admin.id_usuario,
    )

    assert pago.id_cuenta_bancaria == cuenta.id_cuenta


def test_registrar_pago_cobro_en_pesos_solo_acepta_cuenta_en_pesos(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    cuenta_ves = crear_cuenta_bancaria(db_session)
    cuenta_cop = crear_cuenta_bancaria(db_session, moneda="COP")

    with pytest.raises(ValueError, match="pesos colombianos"):
        PagoService.registrar_pago_cobro(
            db_session,
            id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
            monto=Decimal("10.00"),
            metodo_pago="transferencia",
            moneda="COP",
            monto_moneda_origen=Decimal("40000.00"),
            id_cuenta_bancaria=cuenta_ves.id_cuenta,
            tasa_cambio=Decimal("4000.00"),
            id_usuario=admin.id_usuario,
        )
    db_session.rollback()

    pago = PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("10.00"),
        metodo_pago="transferencia",
        moneda="COP",
        monto_moneda_origen=Decimal("40000.00"),
        id_cuenta_bancaria=cuenta_cop.id_cuenta,
        tasa_cambio=Decimal("4000.00"),
        id_usuario=admin.id_usuario,
    )
    assert pago.id_cuenta_bancaria == cuenta_cop.id_cuenta


def test_el_efectivo_por_caja_no_se_ve_afectado(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    pago = PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("10.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    assert pago.id_caja == caja.id_caja


def _abonar(db_session, admin, cliente, cuenta, metodo, **extra):
    return PagoService.aplicar_abono_general_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        monto_abono=Decimal("50.00"),
        tasa_cambio=Decimal("900.00"),
        metodo_pago=metodo,
        id_cuenta_bancaria=cuenta.id_cuenta,
        id_usuario=admin.id_usuario,
        **extra,
    )


def _cliente_con_deuda(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session, limite_credito=1000)
    _crear_facturas_cliente_cxc(db_session, cliente, admin, [Decimal("100.00")])
    return admin, cliente


def test_abono_general_por_zelle_exige_cuenta_en_dolares(db_session):
    admin, cliente = _cliente_con_deuda(db_session)
    cuenta_ves = crear_cuenta_bancaria(db_session)
    cuenta_usd = crear_cuenta_bancaria(db_session, moneda="USD")

    with pytest.raises(ValueError, match="dólares"):
        _abonar(db_session, admin, cliente, cuenta_ves, "zelle")
    db_session.rollback()

    resultado = _abonar(db_session, admin, cliente, cuenta_usd, "zelle")
    assert resultado["monto_total_aplicado"] == Decimal("50.00")


def test_abono_general_por_transferencia_exige_cuenta_en_bolivares_y_en_pesos_cuenta_cop(db_session):
    admin, cliente = _cliente_con_deuda(db_session)
    cuenta_usd = crear_cuenta_bancaria(db_session, moneda="USD")
    cuenta_cop = crear_cuenta_bancaria(db_session, moneda="COP")
    cuenta_ves = crear_cuenta_bancaria(db_session)

    with pytest.raises(ValueError, match="bolívares"):
        _abonar(db_session, admin, cliente, cuenta_usd, "transferencia")
    db_session.rollback()
    with pytest.raises(ValueError, match="pesos colombianos"):
        _abonar(db_session, admin, cliente, cuenta_ves, "transferencia", moneda_pago="COP")
    db_session.rollback()

    _abonar(db_session, admin, cliente, cuenta_cop, "transferencia", moneda_pago="COP")


def test_sin_permiso_de_bancos_no_se_pueden_listar_cuentas_por_moneda(db_session):
    from tests.factories import crear_usuario

    crear_cuenta_bancaria(db_session, moneda="USD")
    cajero = crear_usuario(db_session)

    with pytest.raises(PermisoDenegadoError):
        BancoService.listar_cuentas(db_session, id_usuario=cajero.id_usuario, moneda="USD")


def test_el_listado_paginado_de_cuentas_filtra_por_moneda(db_session):
    admin = crear_usuario_admin(db_session)
    crear_cuenta_bancaria(db_session)
    usd = crear_cuenta_bancaria(db_session, moneda="USD")
    crear_cuenta_bancaria(db_session, moneda="COP")

    resultado = CuentaBancariaService.listar(db_session, id_usuario=admin.id_usuario, moneda="USD")
    todas = CuentaBancariaService.listar(db_session, id_usuario=admin.id_usuario)

    assert [c.id_cuenta for c in resultado["items"]] == [usd.id_cuenta]
    assert resultado["total"] == 1
    assert todas["total"] == 3


# -- Migracion 0097: moneda de las cuentas existentes segun su historial --------------------------------------------


def _aplicar_migracion_0097(db_session):
    from pathlib import Path

    from sqlalchemy import text

    ruta = Path(__file__).resolve().parents[2] / "migrations" / "0097_moneda_de_cuentas_segun_su_historial.sql"
    # el runner de migraciones separa por "GO"; aqui el archivo es un solo lote
    lineas = [linea for linea in ruta.read_text(encoding="utf-8").splitlines() if linea.strip() != "GO"]
    sql = chr(10).join(lineas)
    db_session.execute(text(sql))
    db_session.commit()


def _con_historial(db_session, cxc, admin, cuenta, pagos):
    """Registra `pagos` ([(metodo, moneda)]) en la cuenta y la deja en 'VES', el estado en que la migracion 0096 dejo
    todas las cuentas. (Cada pago se registra con la cuenta en la moneda que le corresponde porque el servicio valida
    la moneda de la cuenta.)"""
    for metodo, moneda in pagos:
        cuenta.moneda = moneda_para_metodo(metodo, moneda)
        db_session.commit()
        PagoService.registrar_pago_cobro(
            db_session,
            id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
            monto=Decimal("5.00"),
            metodo_pago=metodo,
            moneda=moneda,
            id_cuenta_bancaria=cuenta.id_cuenta,
            tasa_cambio=Decimal("40.00"),
            id_usuario=admin.id_usuario,
        )
    cuenta.moneda = "VES"
    db_session.commit()


def _moneda_de(db_session, cuenta):
    db_session.expire_all()
    return db_session.get(type(cuenta), cuenta.id_cuenta).moneda


def _auditoria(db_session, accion):
    from app.db.models import Auditoria

    return [a.detalle for a in db_session.query(Auditoria).filter_by(accion=accion).all()]


def test_la_migracion_pone_en_usd_la_cuenta_que_solo_recibio_zelle_y_binance(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    cuenta = crear_cuenta_bancaria(db_session)
    _con_historial(db_session, cxc, admin, cuenta, [("zelle", "USD"), ("binance", "USDT"), ("zelle", "USD")])

    _aplicar_migracion_0097(db_session)

    assert _moneda_de(db_session, cuenta) == "USD"
    avisos = _auditoria(db_session, "MONEDA_CUENTA_DEDUCIDA")
    assert len(avisos) == 1 and "VES -> USD" in avisos[0] and "3 pago(s)" in avisos[0]


def test_la_migracion_deja_en_bolivares_la_cuenta_que_solo_uso_transferencias(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    cuenta = crear_cuenta_bancaria(db_session)
    _con_historial(db_session, cxc, admin, cuenta, [("transferencia", "VES"), ("punto_de_venta", "USD")])

    _aplicar_migracion_0097(db_session)

    assert _moneda_de(db_session, cuenta) == "VES"
    assert _auditoria(db_session, "MONEDA_CUENTA_DEDUCIDA") == []
    assert _auditoria(db_session, "MONEDA_CUENTA_REVISAR") == []


def test_la_migracion_pone_en_cop_la_cuenta_que_solo_recibio_pesos(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    cuenta = crear_cuenta_bancaria(db_session)
    _con_historial(db_session, cxc, admin, cuenta, [("transferencia", "COP"), ("transferencia", "COP")])

    _aplicar_migracion_0097(db_session)

    assert _moneda_de(db_session, cuenta) == "COP"


def test_con_pagos_mezclados_la_migracion_no_adivina_y_deja_un_aviso_para_revisar(db_session):
    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    cuenta = crear_cuenta_bancaria(db_session)
    _con_historial(db_session, cxc, admin, cuenta, [("zelle", "USD"), ("transferencia", "VES")])

    _aplicar_migracion_0097(db_session)

    assert _moneda_de(db_session, cuenta) == "VES"
    avisos = _auditoria(db_session, "MONEDA_CUENTA_REVISAR")
    assert len(avisos) == 1 and "2 monedas distintas" in avisos[0] and str(cuenta.id_cuenta) in avisos[0]
    assert _auditoria(db_session, "MONEDA_CUENTA_DEDUCIDA") == []


def test_una_cuenta_sin_pagos_no_cambia_ni_deja_avisos(db_session):
    cuenta = crear_cuenta_bancaria(db_session)

    _aplicar_migracion_0097(db_session)

    assert _moneda_de(db_session, cuenta) == "VES"
    assert _auditoria(db_session, "MONEDA_CUENTA_REVISAR") == []


def test_la_migracion_considera_tambien_los_pagos_a_proveedores(db_session):
    from app.db.models import PagoProveedor

    cxc, admin = _crear_cxc(db_session, Decimal("100.00"))
    cuenta = crear_cuenta_bancaria(db_session)
    _con_historial(db_session, cxc, admin, cuenta, [("zelle", "USD")])
    # un pago a proveedor por transferencia en la misma cuenta la vuelve ambigua
    db_session.add(
        PagoProveedor(
            id_cuenta_por_pagar=_crear_cxp_id(db_session),
            id_cuenta_bancaria=cuenta.id_cuenta,
            metodo_pago="transferencia",
            monto=Decimal("1.00"),
        )
    )
    db_session.commit()

    _aplicar_migracion_0097(db_session)

    assert _moneda_de(db_session, cuenta) == "VES"
    assert len(_auditoria(db_session, "MONEDA_CUENTA_REVISAR")) == 1


def _crear_cxp_id(db_session):
    from tests.services.test_pagos import _crear_cxp

    cxp, _admin = _crear_cxp(db_session, Decimal("50.00"))
    return cxp.id_cuenta
