"""listar_pagos_proveedor trae la caja y la cuenta bancaria (con su banco) de cada pago en la misma consulta: el
dialogo de detalle los muestra y antes cada fila disparaba sus propias consultas."""

from decimal import Decimal

from sqlalchemy import event

from app.services.pagos import PagoService
from app.services.tesoreria import CajaService
from tests.factories import crear_caja, crear_cuenta_bancaria
from tests.services.test_pagos import _crear_cxp


def test_los_pagos_vienen_con_su_origen_sin_consultas_por_fila(db_session):
    cxp, admin = _crear_cxp(db_session, Decimal("100.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=500)
    cuenta = crear_cuenta_bancaria(db_session, saldo_total_banco=Decimal("500.00"))
    PagoService.registrar_pago_proveedor(
        db_session,
        id_cuenta_por_pagar=cxp.id_cuenta,
        monto=Decimal("10.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )
    for _ in range(3):
        PagoService.registrar_pago_proveedor(
            db_session,
            id_cuenta_por_pagar=cxp.id_cuenta,
            monto=Decimal("5.00"),
            metodo_pago="transferencia",
            id_cuenta_bancaria=cuenta.id_cuenta,
            tasa_cambio=Decimal("40.00"),
            id_usuario=admin.id_usuario,
        )
    db_session.expire_all()
    sentencias = []
    motor = db_session.get_bind()
    event.listen(motor, "before_cursor_execute", lambda *a, **k: sentencias.append(a[2]))

    pagos = PagoService.listar_pagos_proveedor(db_session, cxp.id_cuenta, id_usuario=admin.id_usuario)
    sentencias_del_listado = len(sentencias)
    origenes = [
        (p.caja.nombre_caja if p.caja else None, p.cuenta_bancaria.banco.nombre_banco if p.cuenta_bancaria else None)
        for p in pagos
    ]

    assert len(pagos) == 4 and sum(1 for caja_, banco in origenes if caja_ or banco) == 4
    # acceder al origen de cada pago no agrega consultas: ya venian con el listado
    assert len(sentencias) == sentencias_del_listado
