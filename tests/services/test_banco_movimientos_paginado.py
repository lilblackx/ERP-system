"""Movimientos de una cuenta bancaria: una pagina a la vez y totales de toda la cuenta sumados en la base."""

from app.services.banco_movimientos import BancoMovimientoService
from tests.factories import crear_cuenta_bancaria, crear_usuario_admin


def _movimientos(db_session, admin, cuenta, abonos, cargos, **extra):
    for _ in range(abonos):
        BancoMovimientoService.crear(db_session, cuenta.id_cuenta, "abono", 10.00, id_usuario=admin.id_usuario, **extra)
    for _ in range(cargos):
        BancoMovimientoService.crear(db_session, cuenta.id_cuenta, "cargo", 4.00, id_usuario=admin.id_usuario, **extra)


def test_pagina_los_movimientos_y_suma_toda_la_cuenta(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session)
    _movimientos(db_session, admin, cuenta, abonos=5, cargos=3)

    pagina_1 = BancoMovimientoService.listar_paginado(
        db_session, cuenta.id_cuenta, pagina=1, por_pagina=3, id_usuario=admin.id_usuario
    )
    pagina_3 = BancoMovimientoService.listar_paginado(
        db_session, cuenta.id_cuenta, pagina=3, por_pagina=3, id_usuario=admin.id_usuario
    )

    assert (pagina_1["total"], pagina_1["total_paginas"], len(pagina_1["items"])) == (8, 3, 3)
    assert len(pagina_3["items"]) == 2
    # los totales son de toda la cuenta, no de la pagina que se pidio
    assert pagina_1["totales"] == pagina_3["totales"]
    assert pagina_1["totales"]["entradas"] == 50.0
    assert pagina_1["totales"]["salidas"] == 12.0


def test_el_monto_en_bolivares_usa_el_registrado_o_monto_por_tasa(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session)
    BancoMovimientoService.crear(
        db_session, cuenta.id_cuenta, "abono", 10.00, id_usuario=admin.id_usuario, monto_bolivares=400.00
    )
    BancoMovimientoService.crear(
        db_session, cuenta.id_cuenta, "abono", 10.00, id_usuario=admin.id_usuario, tasa_cambio=50.00
    )
    BancoMovimientoService.crear(db_session, cuenta.id_cuenta, "cargo", 10.00, id_usuario=admin.id_usuario)

    totales = BancoMovimientoService.listar_paginado(db_session, cuenta.id_cuenta, id_usuario=admin.id_usuario)[
        "totales"
    ]

    assert totales["entradas_bs"] == 900.0  # 400 registrados + 10 * 50
    assert totales["salidas_bs"] == 0.0  # sin bolivares ni tasa


def test_la_pagina_trae_el_usuario_creador_sin_consultas_por_fila(db_session):
    from sqlalchemy import event

    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session)
    _movimientos(db_session, admin, cuenta, abonos=6, cargos=0)
    # los ids se leen antes de expirar: leerlos despues sumaria al conteo un refresco del propio test
    id_usuario, id_cuenta = admin.id_usuario, cuenta.id_cuenta
    db_session.expire_all()
    sentencias = []
    motor = db_session.get_bind()
    event.listen(motor, "before_cursor_execute", lambda *a, **k: sentencias.append(a[2]))

    resultado = BancoMovimientoService.listar_paginado(db_session, id_cuenta, id_usuario=id_usuario)
    nombres = [m.creador.nombre if m.creador else None for m in resultado["items"]]

    assert len(nombres) == 6
    # una sola consulta suelta a usuarios (la del chequeo de permisos), no una por cada movimiento
    assert len([s for s in sentencias if "FROM usuarios" in s and "banco_movimientos" not in s]) <= 1
