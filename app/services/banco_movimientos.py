import datetime

from sqlalchemy.orm import Session

from app.db.models import BancoMovimiento, CuentaBancaria
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso

TIPOS_MOVIMIENTO = {"abono", "cargo"}


class BancoMovimientoService:
    @staticmethod
    def crear(
        session: Session,
        id_cuenta: int,
        tipo_movimiento: str,
        monto: float,
        referencia: str | None = None,
        descripcion: str | None = None,
        id_pago_cobro: int | None = None,
        id_pago_proveedor: int | None = None,
        id_pago_comision: int | None = None,
        id_usuario: int | None = None,
    ) -> BancoMovimiento:
        """Crea un movimiento bancario y actualiza el saldo de la cuenta."""
        require_permiso(session, id_usuario, "bancos", "crear")
        if tipo_movimiento not in TIPOS_MOVIMIENTO:
            raise ValueError(f"tipo_movimiento debe ser uno de {TIPOS_MOVIMIENTO}")
        if monto <= 0:
            raise ValueError("El monto debe ser mayor a 0")

        cuenta = session.get(CuentaBancaria, id_cuenta)
        if cuenta is None:
            raise ValueError("Cuenta bancaria no encontrada")
        if cuenta.estado_cuenta != "ACTIVO":
            raise ValueError("La cuenta bancaria está inactiva")

        movimiento = BancoMovimiento(
            id_cuenta=id_cuenta,
            tipo_movimiento=tipo_movimiento,
            monto_movimiento=monto,
            fecha_movimiento=datetime.datetime.now(),
            referencia_movimiento=referencia,
            descripcion_movimiento=descripcion,
            creado_por=id_usuario,
            fecha_creacion=datetime.datetime.now(),
            id_pago_cobro=id_pago_cobro,
            id_pago_proveedor=id_pago_proveedor,
            id_pago_comision=id_pago_comision,
        )
        session.add(movimiento)
        session.commit()
        session.refresh(movimiento)

        # El trigger trg_banco_movimientos_saldo actualiza saldo_total_banco automáticamente
        session.refresh(cuenta)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="CREAR_MOVIMIENTO_BANCO",
            modulo="BANCOS",
            detalle={
                "id_movimiento": movimiento.id_movimiento,
                "id_cuenta": id_cuenta,
                "tipo": tipo_movimiento,
                "monto": float(monto),
            },
        )
        return movimiento

    @staticmethod
    def listar(
        session: Session,
        id_cuenta: int | None = None,
        fecha_desde: datetime.datetime | None = None,
        fecha_hasta: datetime.datetime | None = None,
        tipo_movimiento: str | None = None,
        id_usuario: int | None = None,
    ) -> list[BancoMovimiento]:
        """Lista movimientos bancarios con filtros opcionales."""
        require_permiso(session, id_usuario, "bancos", "ver")
        if tipo_movimiento and tipo_movimiento not in TIPOS_MOVIMIENTO:
            raise ValueError(f"tipo_movimiento invalido: {tipo_movimiento}")

        query = session.query(BancoMovimiento)
        if id_cuenta:
            query = query.filter(BancoMovimiento.id_cuenta == id_cuenta)
        if fecha_desde:
            query = query.filter(BancoMovimiento.fecha_movimiento >= fecha_desde)
        if fecha_hasta:
            query = query.filter(BancoMovimiento.fecha_movimiento <= fecha_hasta)
        if tipo_movimiento:
            query = query.filter(BancoMovimiento.tipo_movimiento == tipo_movimiento)

        return query.order_by(BancoMovimiento.fecha_movimiento.desc()).all()

    @staticmethod
    def obtener_saldo_actual(session: Session, id_cuenta: int, id_usuario: int | None = None) -> float:
        """Obtiene el saldo actual de una cuenta bancaria."""
        require_permiso(session, id_usuario, "bancos", "ver")
        cuenta = session.get(CuentaBancaria, id_cuenta)
        if cuenta is None:
            raise ValueError("Cuenta bancaria no encontrada")
        return float(cuenta.saldo_total_banco)
