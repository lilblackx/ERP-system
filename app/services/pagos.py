from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import CuentaPorCobrar, CuentaPorPagar, PagoCobro, PagoProveedor
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso

# trg_pagos_cobros_io / trg_pagos_proveedores_io (INSTEAD OF INSERT) ya validan
# "exactamente un origen" y "monto <= saldo_pendiente" en la base de datos, pero lo
# hacen con RAISERROR: dejarlo pasar hasta ahi obligaria al caller a interpretar un
# pyodbc.ProgrammingError crudo. Se valida antes en Python para dar el mismo estilo de
# error (ValueError) que el resto de los servicios.


class PagoService:
    @staticmethod
    def registrar_pago_cobro(
        session: Session,
        id_cuenta_por_cobrar: int,
        monto,
        metodo_pago: str,
        id_cuenta_bancaria: int | None = None,
        id_caja: int | None = None,
        id_tasa: int | None = None,
        referencia: str | None = None,
        fecha_pago: date | datetime | None = None,
        id_usuario: int | None = None,
    ) -> PagoCobro:
        require_permiso(session, id_usuario, "pagos", "crear")
        if (id_cuenta_bancaria is None) == (id_caja is None):
            raise ValueError("Indique exactamente un origen del pago: cuenta bancaria o caja")

        monto = Decimal(str(monto))
        if monto <= 0:
            raise ValueError("El monto debe ser mayor a cero")

        cuenta = session.get(CuentaPorCobrar, id_cuenta_por_cobrar)
        if cuenta is None:
            raise ValueError("Cuenta por cobrar no encontrada")
        if monto > cuenta.saldo_pendiente:
            raise ValueError(f"El monto {monto} excede el saldo pendiente {cuenta.saldo_pendiente}")

        pago = PagoCobro(
            id_cuenta_por_cobrar=id_cuenta_por_cobrar,
            id_cuenta_bancaria=id_cuenta_bancaria,
            id_caja=id_caja,
            id_tasa=id_tasa,
            metodo_pago=metodo_pago,
            monto=monto,
            referencia=referencia,
            fecha_pago=fecha_pago,
            creado_por=id_usuario,
        )
        session.add(pago)
        session.commit()
        session.refresh(pago)
        session.refresh(cuenta)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="PAGO_COBRO",
            modulo="TESORERIA",
            detalle={
                "id_cuenta_por_cobrar": id_cuenta_por_cobrar,
                "monto": str(pago.monto),
                "estado_resultante": cuenta.estado,
            },
        )
        return pago

    @staticmethod
    def registrar_pago_proveedor(
        session: Session,
        id_cuenta_por_pagar: int,
        monto,
        metodo_pago: str,
        id_cuenta_bancaria: int | None = None,
        id_caja: int | None = None,
        id_tasa: int | None = None,
        referencia: str | None = None,
        fecha_pago: date | datetime | None = None,
        id_usuario: int | None = None,
    ) -> PagoProveedor:
        require_permiso(session, id_usuario, "pagos", "crear")
        if (id_cuenta_bancaria is None) == (id_caja is None):
            raise ValueError("Indique exactamente un origen del pago: cuenta bancaria o caja")

        monto = Decimal(str(monto))
        if monto <= 0:
            raise ValueError("El monto debe ser mayor a cero")

        cuenta = session.get(CuentaPorPagar, id_cuenta_por_pagar)
        if cuenta is None:
            raise ValueError("Cuenta por pagar no encontrada")
        if monto > cuenta.saldo_pendiente:
            raise ValueError(f"El monto {monto} excede el saldo pendiente {cuenta.saldo_pendiente}")

        pago = PagoProveedor(
            id_cuenta_por_pagar=id_cuenta_por_pagar,
            id_cuenta_bancaria=id_cuenta_bancaria,
            id_caja=id_caja,
            id_tasa=id_tasa,
            metodo_pago=metodo_pago,
            monto=monto,
            referencia=referencia,
            fecha_pago=fecha_pago,
            creado_por=id_usuario,
        )
        session.add(pago)
        session.commit()
        session.refresh(pago)
        session.refresh(cuenta)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="PAGO_PROVEEDOR",
            modulo="TESORERIA",
            detalle={
                "id_cuenta_por_pagar": id_cuenta_por_pagar,
                "monto": str(pago.monto),
                "estado_resultante": cuenta.estado,
            },
        )
        return pago

    @staticmethod
    def listar_pagos_cobro(
        session: Session, id_cuenta_por_cobrar: int, id_usuario: int | None = None
    ) -> list[PagoCobro]:
        require_permiso(session, id_usuario, "pagos", "ver")
        return (
            session.query(PagoCobro)
            .filter(PagoCobro.id_cuenta_por_cobrar == id_cuenta_por_cobrar)
            .order_by(PagoCobro.fecha_pago.desc())
            .all()
        )

    @staticmethod
    def listar_pagos_proveedor(
        session: Session, id_cuenta_por_pagar: int, id_usuario: int | None = None
    ) -> list[PagoProveedor]:
        require_permiso(session, id_usuario, "pagos", "ver")
        return (
            session.query(PagoProveedor)
            .filter(PagoProveedor.id_cuenta_por_pagar == id_cuenta_por_pagar)
            .order_by(PagoProveedor.fecha_pago.desc())
            .all()
        )
