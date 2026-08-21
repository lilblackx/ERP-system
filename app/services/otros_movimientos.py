from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import (
    BancoMovimiento,
    Caja,
    CajaMovimiento,
    Cliente,
    CuentaBancaria,
    CuentaPorCobrar,
    CuentaPorCobrarOtro,
    CuentaPorPagarOtro,
)
from app.services.auditoria import AuditoriaService

ESTADOS_CXC_OTRO = ("pendiente", "parcial", "pagada", "vencida")


def _validar_origen_pago(id_caja: int | None, id_cuenta_bancaria: int | None) -> None:
    if (id_caja is None) == (id_cuenta_bancaria is None):
        raise ValueError("Debe indicar exactamente un origen del pago: id_caja o id_cuenta_bancaria")


class OtrosMovimientosService:
    # ------------------------------------------------------------------
    # Cuentas por cobrar otros (prestamos a empleados, anticipos, etc.)
    # ------------------------------------------------------------------
    @staticmethod
    def crear_cuenta_cobrar_otro(
        session: Session,
        id_cliente: int,
        monto_total,
        descripcion: str | None,
        fecha_vencimiento: date | None,
        creado_por: int | None,
    ) -> CuentaPorCobrarOtro:
        if Decimal(str(monto_total)) <= 0:
            raise ValueError("monto_total debe ser mayor a cero")
        if session.get(Cliente, id_cliente) is None:
            raise ValueError("Cliente no encontrado")

        cuenta = CuentaPorCobrarOtro(
            monto_total=monto_total,
            fecha_emision=datetime.now(),
            descripcion=descripcion,
            id_cliente=id_cliente,
            saldo_pendiente=monto_total,
            fecha_vencimiento=fecha_vencimiento,
            estado="pendiente",
            creado_por=creado_por,
        )
        session.add(cuenta)
        session.commit()
        session.refresh(cuenta)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=creado_por,
            accion="CREAR_CXC_OTRO",
            modulo="OTROS_MOVIMIENTOS",
            detalle={"id_cuenta": cuenta.id_cuenta, "id_cliente": id_cliente, "monto_total": str(cuenta.monto_total)},
        )
        return cuenta

    @staticmethod
    def registrar_abono_otro(
        session: Session,
        id_cuenta: int,
        monto,
        id_caja: int | None = None,
        id_cuenta_bancaria: int | None = None,
        referencia: str | None = None,
        id_usuario: int | None = None,
    ) -> CuentaPorCobrarOtro:
        _validar_origen_pago(id_caja, id_cuenta_bancaria)

        monto = Decimal(str(monto))
        if monto <= 0:
            raise ValueError("El monto debe ser mayor a cero")

        cuenta = session.get(CuentaPorCobrarOtro, id_cuenta)
        if cuenta is None:
            raise ValueError("Cuenta por cobrar (otros) no encontrada")
        if cuenta.estado == "pagada":
            raise ValueError("La cuenta ya esta pagada en su totalidad")
        if monto > cuenta.saldo_pendiente:
            raise ValueError(f"El monto excede el saldo pendiente ({cuenta.saldo_pendiente})")

        if id_cuenta_bancaria is not None and session.get(CuentaBancaria, id_cuenta_bancaria) is None:
            raise ValueError("Cuenta bancaria no encontrada")
        if id_caja is not None:
            caja = session.get(Caja, id_caja)
            if caja is None:
                raise ValueError("Caja no encontrada")
            if caja.fecha_apertura is None or caja.fecha_cierre is not None:
                raise ValueError(f"La caja '{caja.nombre_caja}' no tiene un turno abierto")

        cuenta.saldo_pendiente = cuenta.saldo_pendiente - monto
        cuenta.estado = "pagada" if cuenta.saldo_pendiente <= 0 else "parcial"

        ahora = datetime.now()
        if id_cuenta_bancaria is not None:
            session.add(
                BancoMovimiento(
                    id_cuenta=id_cuenta_bancaria,
                    tipo_movimiento="abono",
                    monto_movimiento=monto,
                    fecha_movimiento=ahora,
                    referencia_movimiento=referencia,
                    descripcion_movimiento=f"Abono cuenta por cobrar (otros) #{id_cuenta}",
                    creado_por=id_usuario,
                    fecha_creacion=ahora,
                )
            )
        else:
            session.add(
                CajaMovimiento(
                    id_caja=id_caja,
                    tipo_movimiento="entrada",
                    descripcion_movimiento=f"Abono cuenta por cobrar (otros) #{id_cuenta}"
                    + (f" - {referencia}" if referencia else ""),
                    monto_movimiento=monto,
                    fecha_registro=ahora,
                    creado_por=id_usuario,
                )
            )

        session.commit()
        session.refresh(cuenta)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="ABONO_CXC_OTRO",
            modulo="OTROS_MOVIMIENTOS",
            detalle={"id_cuenta": id_cuenta, "monto": str(monto), "estado_resultante": cuenta.estado},
        )
        return cuenta

    @staticmethod
    def listar_cuentas_cobrar_otro(
        session: Session,
        estado: str | None = None,
        id_cliente: int | None = None,
        fecha_desde: date | datetime | None = None,
        fecha_hasta: date | datetime | None = None,
    ) -> list[CuentaPorCobrarOtro]:
        if estado and estado not in ESTADOS_CXC_OTRO:
            raise ValueError(f"estado invalido: {estado}")

        query = session.query(CuentaPorCobrarOtro)
        if estado:
            query = query.filter(CuentaPorCobrarOtro.estado == estado)
        if id_cliente:
            query = query.filter(CuentaPorCobrarOtro.id_cliente == id_cliente)
        if fecha_desde:
            query = query.filter(CuentaPorCobrarOtro.fecha_emision >= fecha_desde)
        if fecha_hasta:
            query = query.filter(CuentaPorCobrarOtro.fecha_emision <= fecha_hasta)

        return query.order_by(CuentaPorCobrarOtro.fecha_emision.desc()).all()

    # ------------------------------------------------------------------
    # Cuentas por pagar otros: transferencias recibidas sin conciliar
    # ------------------------------------------------------------------
    @staticmethod
    def crear_partida_no_conciliada(
        session: Session,
        id_cuenta_bancaria: int,
        monto,
        id_movimiento: int | None = None,
        referencia_bancaria: str | None = None,
        descripcion: str | None = None,
        creado_por: int | None = None,
    ) -> CuentaPorPagarOtro:
        if Decimal(str(monto)) <= 0:
            raise ValueError("monto debe ser mayor a cero")
        if session.get(CuentaBancaria, id_cuenta_bancaria) is None:
            raise ValueError("Cuenta bancaria no encontrada")
        if id_movimiento is not None and session.get(BancoMovimiento, id_movimiento) is None:
            raise ValueError("Movimiento bancario no encontrado")

        partida = CuentaPorPagarOtro(
            id_cuenta_bancaria=id_cuenta_bancaria,
            id_movimiento=id_movimiento,
            monto_total=monto,
            saldo_pendiente=monto,
            fecha_recepcion=datetime.now(),
            referencia_bancaria=referencia_bancaria,
            descripcion=descripcion,
            estado="pendiente",
            creado_por=creado_por,
        )
        session.add(partida)
        session.commit()
        session.refresh(partida)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=creado_por,
            accion="CREAR_PARTIDA_NO_CONCILIADA",
            modulo="OTROS_MOVIMIENTOS",
            detalle={"id_cuenta": partida.id_cuenta, "id_cuenta_bancaria": id_cuenta_bancaria, "monto": str(monto)},
        )
        return partida

    @staticmethod
    def conciliar_partida(
        session: Session,
        id_cuenta: int,
        id_cliente: int,
        id_cuenta_por_cobrar: int,
        monto,
        id_usuario: int | None,
    ) -> dict:
        monto = Decimal(str(monto))
        if monto <= 0:
            raise ValueError("El monto debe ser mayor a cero")

        partida = session.get(CuentaPorPagarOtro, id_cuenta)
        if partida is None:
            raise ValueError("Partida no conciliada no encontrada")
        if partida.estado == "conciliado":
            raise ValueError("La partida ya esta completamente conciliada")
        if monto > partida.saldo_pendiente:
            raise ValueError(f"El monto excede el saldo sin conciliar de la partida ({partida.saldo_pendiente})")
        if partida.id_cliente_identificado is not None and partida.id_cliente_identificado != id_cliente:
            raise ValueError("Esta partida ya fue atribuida a otro cliente")

        cliente = session.get(Cliente, id_cliente)
        if cliente is None:
            raise ValueError("Cliente no encontrado")

        cxc = session.get(CuentaPorCobrar, id_cuenta_por_cobrar)
        if cxc is None:
            raise ValueError("Cuenta por cobrar no encontrada")
        if cxc.factura.id_cliente_factura != id_cliente:
            raise ValueError("La cuenta por cobrar indicada no pertenece al cliente identificado")
        if monto > cxc.saldo_pendiente:
            raise ValueError(f"El monto excede el saldo pendiente de la factura ({cxc.saldo_pendiente})")

        # No se crea un banco_movimientos nuevo: el dinero ya esta contabilizado en el
        # banco desde que llego la transferencia sin conciliar.
        cxc.saldo_pendiente = cxc.saldo_pendiente - monto
        cxc.estado = "pagada" if cxc.saldo_pendiente <= 0 else "parcial"

        partida.saldo_pendiente = partida.saldo_pendiente - monto
        partida.estado = "conciliado" if partida.saldo_pendiente <= 0 else "parcial"
        partida.id_cliente_identificado = id_cliente
        partida.conciliado_por = id_usuario
        partida.fecha_conciliacion = datetime.now()

        session.commit()
        session.refresh(partida)
        session.refresh(cxc)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="CONCILIACION_PARTIDA",
            modulo="OTROS_MOVIMIENTOS",
            detalle={
                "id_cuenta_partida": partida.id_cuenta,
                "id_cliente": id_cliente,
                "id_cuenta_por_cobrar": id_cuenta_por_cobrar,
                "monto": str(monto),
            },
        )
        return {"partida": partida, "cuenta_por_cobrar": cxc}

    @staticmethod
    def listar_partidas_no_conciliadas(
        session: Session,
        estado: str | None = None,
        fecha_desde: date | datetime | None = None,
        fecha_hasta: date | datetime | None = None,
        responsable: int | None = None,
    ) -> list[CuentaPorPagarOtro]:
        """fecha_desde/fecha_hasta filtran por fecha_recepcion (estas partidas no tienen
        vencimiento propio, es dinero ya recibido pendiente de identificar). responsable
        filtra por quien registro la partida (creado_por) o quien la concilio (conciliado_por)."""
        if estado and estado not in ("pendiente", "parcial", "conciliado"):
            raise ValueError(f"estado invalido: {estado}")

        query = session.query(CuentaPorPagarOtro)
        if estado:
            query = query.filter(CuentaPorPagarOtro.estado == estado)
        if fecha_desde:
            query = query.filter(CuentaPorPagarOtro.fecha_recepcion >= fecha_desde)
        if fecha_hasta:
            query = query.filter(CuentaPorPagarOtro.fecha_recepcion <= fecha_hasta)
        if responsable:
            query = query.filter(
                (CuentaPorPagarOtro.creado_por == responsable) | (CuentaPorPagarOtro.conciliado_por == responsable)
            )

        return query.order_by(CuentaPorPagarOtro.fecha_recepcion.desc()).all()
