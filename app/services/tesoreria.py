from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Banco, BancoMovimiento, Caja, CajaMovimiento, CuentaBancaria
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso

TIPOS_MOVIMIENTO_BANCO = {"abono", "cargo", "transferencia", "deposito"}
TIPOS_MOVIMIENTO_CAJA = {"entrada", "salida"}
ESTADOS_VALIDOS = {"ACTIVO", "INACTIVO"}


def _enmascarar_numero_cuenta(numero_cuenta: str | None) -> str | None:
    if not numero_cuenta:
        return numero_cuenta
    visibles = numero_cuenta[-4:]
    return "*" * (len(numero_cuenta) - len(visibles)) + visibles


class BancoService:
    @staticmethod
    def listar_bancos(session: Session, id_usuario: int | None = None) -> list[Banco]:
        require_permiso(session, id_usuario, "bancos", "ver")
        return session.query(Banco).order_by(Banco.nombre_banco).all()

    @staticmethod
    def crear_banco(session: Session, **datos) -> Banco:
        require_permiso(session, datos.get("creado_por"), "bancos", "crear")
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
        require_permiso(session, id_usuario, "bancos", "editar")
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

    # Un banco nunca se borra fisicamente: FK_cuentas_bancarias_id_banco es ON DELETE NO
    # ACTION, asi que borrar uno con cuentas bancarias asociadas revienta con un
    # IntegrityError crudo de pyodbc -- y aunque no tenga ninguna todavia, podria
    # tenerlas despues, asi que la politica es no permitir el DELETE nunca. Usar
    # cambiar_estado_banco(..., "INACTIVO") para retirarlo de circulacion preservando el
    # historial. Decision de producto 2026-08-22 (hallazgo de auditoria del mismo dia).
    @staticmethod
    def eliminar_banco(session: Session, id_banco: int, id_usuario: int | None = None) -> None:
        require_permiso(session, id_usuario, "bancos", "eliminar")
        raise ValueError(
            "No se puede eliminar un banco para proteger la integridad de los datos. "
            "Use BancoService.cambiar_estado_banco() para desactivarlo."
        )

    @staticmethod
    def cambiar_estado_banco(
        session: Session, id_banco: int, nuevo_estado: str, id_usuario: int | None = None
    ) -> Banco:
        require_permiso(session, id_usuario, "bancos", "eliminar")
        if nuevo_estado not in ESTADOS_VALIDOS:
            raise ValueError(f"nuevo_estado debe ser uno de {ESTADOS_VALIDOS}")
        banco = session.get(Banco, id_banco)
        if banco is None:
            raise ValueError("Banco no encontrado")

        banco.estado_banco = nuevo_estado
        session.commit()
        session.refresh(banco)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="CAMBIAR_ESTADO_BANCO",
            modulo="BANCOS",
            detalle={"id_banco": banco.id_banco, "nuevo_estado": nuevo_estado},
        )
        return banco

    @staticmethod
    def listar_cuentas(
        session: Session, id_banco: int | None = None, id_usuario: int | None = None
    ) -> list[CuentaBancaria]:
        require_permiso(session, id_usuario, "bancos", "ver")
        query = session.query(CuentaBancaria).options(joinedload(CuentaBancaria.banco))
        if id_banco:
            query = query.filter(CuentaBancaria.id_banco == id_banco)
        return query.order_by(CuentaBancaria.id_cuenta).all()

    @staticmethod
    def crear_cuenta(session: Session, **datos) -> CuentaBancaria:
        require_permiso(session, datos.get("creado_por"), "bancos", "crear")
        banco = session.get(Banco, datos.get("id_banco"))
        if banco is None:
            raise ValueError("Banco no encontrado")
        if banco.estado_banco != "ACTIVO":
            raise ValueError(f"El banco '{banco.nombre_banco}' esta inactivo")
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
        require_permiso(session, id_usuario, "bancos", "editar")
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

    # Una cuenta bancaria nunca se borra fisicamente: FK_banco_movimientos_id_cuenta,
    # FK_pagos_cobros_id_cuenta_bancaria, FK_pagos_proveedores_id_cuenta_bancaria y
    # FK_cxp_otros_id_cuenta_bancaria (todas ON DELETE NO ACTION) hacen que borrar una
    # con movimientos o pagos ya registrados reviente con un IntegrityError crudo de
    # pyodbc -- y aunque no tenga ninguno todavia, podria tenerlos despues, asi que la
    # politica es no permitir el DELETE nunca. Usar cambiar_estado_cuenta(...,
    # "INACTIVO") para retirarla de circulacion preservando el historial. Decision de
    # producto 2026-08-22 (hallazgo de auditoria del mismo dia).
    @staticmethod
    def eliminar_cuenta(session: Session, id_cuenta: int, id_usuario: int | None = None) -> None:
        require_permiso(session, id_usuario, "bancos", "eliminar")
        raise ValueError(
            "No se puede eliminar una cuenta bancaria para proteger la integridad de los datos. "
            "Use BancoService.cambiar_estado_cuenta() para desactivarla."
        )

    @staticmethod
    def cambiar_estado_cuenta(
        session: Session, id_cuenta: int, nuevo_estado: str, id_usuario: int | None = None
    ) -> CuentaBancaria:
        require_permiso(session, id_usuario, "bancos", "eliminar")
        if nuevo_estado not in ESTADOS_VALIDOS:
            raise ValueError(f"nuevo_estado debe ser uno de {ESTADOS_VALIDOS}")
        cuenta = session.get(CuentaBancaria, id_cuenta)
        if cuenta is None:
            raise ValueError("Cuenta bancaria no encontrada")

        cuenta.estado_cuenta = nuevo_estado
        session.commit()
        session.refresh(cuenta)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="CAMBIAR_ESTADO_CUENTA_BANCARIA",
            modulo="BANCOS",
            detalle={"id_cuenta": cuenta.id_cuenta, "nuevo_estado": nuevo_estado},
        )
        return cuenta

    @staticmethod
    def obtener_resumen_cuentas(session: Session, id_usuario: int | None = None) -> list[dict]:
        require_permiso(session, id_usuario, "bancos", "ver")
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
        id_usuario: int | None = None,
    ) -> list[BancoMovimiento]:
        require_permiso(session, id_usuario, "bancos", "ver")
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
    def listar_cajas(session: Session, id_usuario: int | None = None) -> list[Caja]:
        require_permiso(session, id_usuario, "cajas", "ver")
        return session.query(Caja).options(joinedload(Caja.usuario)).order_by(Caja.nombre_caja).all()

    @staticmethod
    def abrir_caja(session: Session, id_caja: int, id_usuario: int, saldo_apertura) -> Caja:
        require_permiso(session, id_usuario, "cajas", "editar")
        # WITH (UPDLOCK, ROWLOCK): mismo patron que C1/C18 -- bloquea la fila hasta el
        # commit para que una segunda apertura/cierre concurrente sobre la misma caja
        # espere en vez de leer el mismo estado stale y pisar el saldo_apertura ya fijado
        # (C22).
        caja = session.execute(
            select(Caja).where(Caja.id_caja == id_caja).with_hint(Caja, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        ).scalar_one_or_none()
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
        require_permiso(session, id_usuario_cierre, "cajas", "editar")
        # Ver el comentario de abrir_caja() -- mismo patron.
        caja = session.execute(
            select(Caja).where(Caja.id_caja == id_caja).with_hint(Caja, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        ).scalar_one_or_none()
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
    def obtener_estado_cajas(session: Session, id_usuario: int | None = None) -> list[dict]:
        cajas = CajaService.listar_cajas(session, id_usuario=id_usuario)
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
        require_permiso(session, id_usuario, "cajas", "crear")
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
