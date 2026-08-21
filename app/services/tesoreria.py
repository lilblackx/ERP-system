from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.db.models import Banco, BancoMovimiento, Caja, CajaMovimiento, CuentaBancaria
from app.services.auditoria import AuditoriaService

TIPOS_MOVIMIENTO_BANCO = {"abono", "cargo", "transferencia", "deposito"}
TIPOS_MOVIMIENTO_CAJA = {"entrada", "salida"}


def _enmascarar_numero_cuenta(numero_cuenta: str | None) -> str | None:
    if not numero_cuenta:
        return numero_cuenta
    visibles = numero_cuenta[-4:]
    return "*" * (len(numero_cuenta) - len(visibles)) + visibles


class BancoService:
    @staticmethod
    def listar_bancos(session: Session) -> list[Banco]:
        return session.query(Banco).order_by(Banco.nombre_banco).all()

    @staticmethod
    def crear_banco(session: Session, **datos) -> Banco:
        banco = Banco(**datos)
        session.add(banco)
        session.commit()
        session.refresh(banco)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=banco.creado_por,
            accion="CREAR_BANCO",
            modulo="BANCOS",
            detalle={"id_banco": banco.id_banco, "nombre_banco": banco.nombre_banco},
        )
        return banco

    @staticmethod
    def actualizar_banco(session: Session, id_banco: int, id_usuario: int | None = None, **datos) -> Banco:
        banco = session.get(Banco, id_banco)
        if banco is None:
            raise ValueError("Banco no encontrado")
        for campo, valor in datos.items():
            setattr(banco, campo, valor)
        session.commit()
        session.refresh(banco)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="ACTUALIZAR_BANCO",
            modulo="BANCOS",
            detalle={"id_banco": banco.id_banco, "campos": list(datos.keys())},
        )
        return banco

    @staticmethod
    def eliminar_banco(session: Session, id_banco: int, id_usuario: int | None = None) -> None:
        banco = session.get(Banco, id_banco)
        if banco is None:
            return
        detalle = {"id_banco": banco.id_banco, "nombre_banco": banco.nombre_banco}
        session.delete(banco)
        session.commit()

        AuditoriaService.registrar_evento(
            session, id_usuario=id_usuario, accion="ELIMINAR_BANCO", modulo="BANCOS", detalle=detalle
        )

    @staticmethod
    def listar_cuentas(session: Session, id_banco: int | None = None) -> list[CuentaBancaria]:
        query = session.query(CuentaBancaria).options(joinedload(CuentaBancaria.banco))
        if id_banco:
            query = query.filter(CuentaBancaria.id_banco == id_banco)
        return query.order_by(CuentaBancaria.id_cuenta).all()

    @staticmethod
    def crear_cuenta(session: Session, **datos) -> CuentaBancaria:
        if not session.get(Banco, datos.get("id_banco")):
            raise ValueError("Banco no encontrado")
        cuenta = CuentaBancaria(**datos)
        session.add(cuenta)
        session.commit()
        session.refresh(cuenta)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=cuenta.creado_por,
            accion="CREAR_CUENTA_BANCARIA",
            modulo="BANCOS",
            detalle={"id_cuenta": cuenta.id_cuenta, "numero_cuenta": _enmascarar_numero_cuenta(cuenta.numero_cuenta)},
        )
        return cuenta

    @staticmethod
    def actualizar_cuenta(session: Session, id_cuenta: int, id_usuario: int | None = None, **datos) -> CuentaBancaria:
        cuenta = session.get(CuentaBancaria, id_cuenta)
        if cuenta is None:
            raise ValueError("Cuenta bancaria no encontrada")
        for campo, valor in datos.items():
            setattr(cuenta, campo, valor)
        session.commit()
        session.refresh(cuenta)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="ACTUALIZAR_CUENTA_BANCARIA",
            modulo="BANCOS",
            detalle={"id_cuenta": cuenta.id_cuenta, "campos": list(datos.keys())},
        )
        return cuenta

    @staticmethod
    def eliminar_cuenta(session: Session, id_cuenta: int, id_usuario: int | None = None) -> None:
        cuenta = session.get(CuentaBancaria, id_cuenta)
        if cuenta is None:
            return
        detalle = {"id_cuenta": cuenta.id_cuenta, "numero_cuenta": _enmascarar_numero_cuenta(cuenta.numero_cuenta)}
        session.delete(cuenta)
        session.commit()

        AuditoriaService.registrar_evento(
            session, id_usuario=id_usuario, accion="ELIMINAR_CUENTA_BANCARIA", modulo="BANCOS", detalle=detalle
        )

    @staticmethod
    def obtener_resumen_cuentas(session: Session) -> list[dict]:
        cuentas = (
            session.query(CuentaBancaria)
            .options(joinedload(CuentaBancaria.banco))
            .order_by(CuentaBancaria.id_cuenta)
            .all()
        )
        return [
            {
                "id_cuenta": cuenta.id_cuenta,
                "banco": cuenta.banco.nombre_banco if cuenta.banco else None,
                "numero_cuenta": _enmascarar_numero_cuenta(cuenta.numero_cuenta),
                "tipo_cuenta": cuenta.tipo_cuenta_banco,
                "nombre_titular": cuenta.nombre_titular,
                "saldo_actual": cuenta.saldo_total_banco,
            }
            for cuenta in cuentas
        ]

    @staticmethod
    def obtener_movimientos(
        session: Session,
        id_cuenta: int | None = None,
        fecha_desde: date | datetime | None = None,
        fecha_hasta: date | datetime | None = None,
        tipo_movimiento: str | None = None,
    ) -> list[BancoMovimiento]:
        if tipo_movimiento and tipo_movimiento not in TIPOS_MOVIMIENTO_BANCO:
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


class CajaService:
    @staticmethod
    def listar_cajas(session: Session) -> list[Caja]:
        return session.query(Caja).options(joinedload(Caja.usuario)).order_by(Caja.nombre_caja).all()

    @staticmethod
    def abrir_caja(session: Session, id_caja: int, id_usuario: int, saldo_apertura) -> Caja:
        caja = session.get(Caja, id_caja)
        if caja is None:
            raise ValueError("Caja no encontrada")
        if caja.fecha_apertura is not None and caja.fecha_cierre is None:
            raise ValueError(f"La caja '{caja.nombre_caja}' ya esta abierta")

        caja.fecha_apertura = datetime.now()
        caja.fecha_cierre = None
        caja.saldo_apertura = saldo_apertura
        caja.saldo_cierre = None
        caja.estado_caja = "ABIERTA"
        caja.id_usuario = id_usuario

        session.commit()
        session.refresh(caja)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="APERTURA_CAJA",
            modulo="CAJAS",
            detalle=f"Caja '{caja.nombre_caja}' (id={caja.id_caja}) abierta con saldo {saldo_apertura}",
        )
        return caja

    @staticmethod
    def cerrar_caja(session: Session, id_caja: int, id_usuario_cierre: int) -> Caja:
        caja = session.get(Caja, id_caja)
        if caja is None:
            raise ValueError("Caja no encontrada")
        if caja.fecha_apertura is None or caja.fecha_cierre is not None:
            raise ValueError(f"La caja '{caja.nombre_caja}' no tiene un turno abierto")

        caja.fecha_cierre = datetime.now()
        caja.estado_caja = "CERRADA"
        caja.modificado_por = id_usuario_cierre

        session.commit()
        session.refresh(caja)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario_cierre,
            accion="CIERRE_CAJA",
            modulo="CAJAS",
            detalle=f"Caja '{caja.nombre_caja}' (id={caja.id_caja}) cerrada con saldo_cierre {caja.saldo_cierre}",
        )
        return caja

    @staticmethod
    def obtener_estado_cajas(session: Session) -> list[dict]:
        cajas = CajaService.listar_cajas(session)
        resultado = []
        for caja in cajas:
            esta_abierta = caja.fecha_apertura is not None and caja.fecha_cierre is None

            query_movimientos = session.query(func.count(CajaMovimiento.id_movimiento)).filter(
                CajaMovimiento.id_caja == caja.id_caja
            )
            if caja.fecha_apertura is not None:
                query_movimientos = query_movimientos.filter(CajaMovimiento.fecha_registro >= caja.fecha_apertura)
            if caja.fecha_cierre is not None:
                query_movimientos = query_movimientos.filter(CajaMovimiento.fecha_registro <= caja.fecha_cierre)
            cantidad_movimientos = query_movimientos.scalar()

            resultado.append(
                {
                    "id_caja": caja.id_caja,
                    "nombre_caja": caja.nombre_caja,
                    "cajero": caja.usuario.nombre_usuario if caja.usuario else None,
                    "estado": "ABIERTA" if esta_abierta else "CERRADA",
                    "saldo_apertura": caja.saldo_apertura,
                    "saldo_cierre": caja.saldo_cierre,
                    "cantidad_movimientos": cantidad_movimientos,
                }
            )
        return resultado

    @staticmethod
    def registrar_movimiento_manual(
        session: Session,
        id_caja: int,
        tipo: str,
        monto,
        descripcion: str | None,
        id_usuario: int | None,
    ) -> CajaMovimiento:
        if tipo not in TIPOS_MOVIMIENTO_CAJA:
            raise ValueError(f"tipo invalido: {tipo}, debe ser uno de {TIPOS_MOVIMIENTO_CAJA}")
        if Decimal(str(monto)) <= 0:
            raise ValueError("El monto debe ser mayor a cero")

        caja = session.get(Caja, id_caja)
        if caja is None:
            raise ValueError("Caja no encontrada")
        if caja.fecha_apertura is None or caja.fecha_cierre is not None:
            raise ValueError(f"La caja '{caja.nombre_caja}' no tiene un turno abierto")

        movimiento = CajaMovimiento(
            id_caja=id_caja,
            tipo_movimiento=tipo,
            descripcion_movimiento=descripcion,
            monto_movimiento=monto,
            fecha_registro=datetime.now(),
            creado_por=id_usuario,
        )
        session.add(movimiento)
        session.commit()
        session.refresh(movimiento)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="MOVIMIENTO_MANUAL_CAJA",
            modulo="CAJAS",
            detalle={
                "id_caja": id_caja,
                "tipo": tipo,
                "monto": str(movimiento.monto_movimiento),
                "descripcion": descripcion,
            },
        )
        return movimiento
