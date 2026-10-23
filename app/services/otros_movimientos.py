import logging
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    BancoMovimiento,
    Caja,
    CajaMovimiento,
    Cliente,
    ConciliacionPartida,
    CuentaBancaria,
    CuentaPorCobrar,
    CuentaPorCobrarOtro,
    CuentaPorPagarOtro,
)
from app.services.auditoria import AuditoriaService
from app.services.db_utils import aplicar_lock_timeout
from app.services.permisos import require_permiso
from app.services.tesoreria import BancoService, CajaService

logger = logging.getLogger(__name__)

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
        id_caja: int | None = None,
        id_cuenta_bancaria: int | None = None,
        referencia: str | None = None,
    ) -> CuentaPorCobrarOtro:
        """Un prestamo/anticipo es dinero que SALE de la empresa: se indica de donde (caja con
        turno abierto o cuenta bancaria, con saldo suficiente) y el egreso se registra en la
        misma transaccion. Antes solo se creaba la deuda y la salida de dinero no quedaba en
        ningun lado -- la caja/banco mostraba mas plata de la que habia."""
        require_permiso(session, creado_por, "otros_movimientos", "crear")
        monto_total = Decimal(str(monto_total))
        if monto_total <= 0:
            raise ValueError("monto_total debe ser mayor a cero")
        cliente = session.get(Cliente, id_cliente)
        if cliente is None:
            raise ValueError("Cliente no encontrado")
        if cliente.estado_cliente != "ACTIVO":
            raise ValueError(f"El cliente '{cliente.nombre_razon_social}' esta inactivo")
        _validar_origen_pago(id_caja, id_cuenta_bancaria)

        aplicar_lock_timeout(session)
        ahora = datetime.now()
        # Valida y bloquea el origen ANTES de crear nada.
        if id_caja is not None:
            caja = session.execute(
                select(Caja)
                .where(Caja.id_caja == id_caja)
                .with_hint(Caja, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
            ).scalar_one_or_none()
            if caja is None:
                raise ValueError("Caja no encontrada")
            if caja.fecha_apertura is None or caja.fecha_cierre is not None:
                raise ValueError(f"La caja '{caja.nombre_caja}' no tiene un turno abierto")
            saldo = CajaService.calcular_saldo_actual(session, id_caja)
            if saldo < monto_total:
                raise ValueError(
                    f"La caja '{caja.nombre_caja}' no tiene saldo suficiente: disponible ${saldo}, "
                    f"requerido ${monto_total}"
                )
        else:
            cuenta_bancaria = session.execute(
                select(CuentaBancaria)
                .where(CuentaBancaria.id_cuenta == id_cuenta_bancaria)
                .with_hint(CuentaBancaria, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
            ).scalar_one_or_none()
            if cuenta_bancaria is None:
                raise ValueError("Cuenta bancaria no encontrada")
            if cuenta_bancaria.estado_cuenta != "ACTIVO":
                raise ValueError(f"La cuenta bancaria '{cuenta_bancaria.numero_cuenta}' esta inactiva")
            if (cuenta_bancaria.saldo_total_banco or Decimal("0")) < monto_total:
                raise ValueError(
                    f"La cuenta bancaria '{cuenta_bancaria.numero_cuenta}' no tiene saldo suficiente: "
                    f"disponible ${cuenta_bancaria.saldo_total_banco}, requerido ${monto_total}"
                )
            referencia = (referencia or "").strip()
            if len(referencia) < 4:
                raise ValueError("El egreso bancario requiere una referencia de al menos 4 caracteres")

        cuenta = CuentaPorCobrarOtro(
            monto_total=monto_total,
            fecha_emision=ahora,
            descripcion=descripcion,
            id_cliente=id_cliente,
            saldo_pendiente=monto_total,
            fecha_vencimiento=fecha_vencimiento,
            estado="pendiente",
            creado_por=creado_por,
        )
        session.add(cuenta)
        session.flush()

        motivo = f"Prestamo (otros) #{cuenta.id_cuenta} a {cliente.nombre_razon_social}"[:255]
        if id_caja is not None:
            CajaService._registrar_egreso_vuelto(
                session, id_caja=id_caja, monto=monto_total, descripcion=motivo, id_usuario=creado_por, fecha=ahora
            )
        else:
            BancoService._registrar_egreso_vuelto(
                session,
                id_cuenta=id_cuenta_bancaria,
                monto=monto_total,
                descripcion=motivo,
                referencia=referencia,
                id_usuario=creado_por,
                fecha=ahora,
            )
        session.commit()
        session.refresh(cuenta)

        logger.info(
            "Cuenta por cobrar (otros) creada: id_cuenta=%s cliente=%s monto_total=%s usuario=%s",
            cuenta.id_cuenta,
            id_cliente,
            cuenta.monto_total,
            creado_por,
        )

        AuditoriaService.registrar_evento(
            session,
            id_usuario=creado_por,
            accion="CREAR_CXC_OTRO",
            modulo="OTROS_MOVIMIENTOS",
            detalle={
                "id_cuenta": cuenta.id_cuenta,
                "id_cliente": id_cliente,
                "monto_total": str(cuenta.monto_total),
                "origen": "caja" if id_caja is not None else "banco",
            },
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
        require_permiso(session, id_usuario, "otros_movimientos", "editar")
        _validar_origen_pago(id_caja, id_cuenta_bancaria)

        monto = Decimal(str(monto))
        if monto <= 0:
            raise ValueError("El monto debe ser mayor a cero")

        # WITH (UPDLOCK, ROWLOCK): mismo patron que el fix de C1 en ventas.py -- bloquea
        # la fila hasta el commit para que un segundo abono/conciliacion concurrente sobre
        # la misma cuenta espere en vez de leer el mismo saldo_pendiente stale (TOCTOU).
        cuenta = session.execute(
            select(CuentaPorCobrarOtro)
            .where(CuentaPorCobrarOtro.id_cuenta == id_cuenta)
            .with_hint(CuentaPorCobrarOtro, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        ).scalar_one_or_none()
        if cuenta is None:
            raise ValueError("Cuenta por cobrar (otros) no encontrada")
        if cuenta.estado == "pagada":
            raise ValueError("La cuenta ya esta pagada en su totalidad")
        if monto > cuenta.saldo_pendiente:
            raise ValueError(f"El monto excede el saldo pendiente ({cuenta.saldo_pendiente})")

        if id_cuenta_bancaria is not None:
            cuenta_bancaria = session.get(CuentaBancaria, id_cuenta_bancaria)
            if cuenta_bancaria is None:
                raise ValueError("Cuenta bancaria no encontrada")
            if cuenta_bancaria.estado_cuenta != "ACTIVO":
                raise ValueError(f"La cuenta bancaria '{cuenta_bancaria.numero_cuenta}' esta inactiva")
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
                    monto_bolivares=None,  # Otros movimientos generalmente en USD
                    tasa_cambio=None,
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

        logger.info(
            "Abono a cuenta por cobrar (otros) %s: monto=%s estado_resultante=%s usuario=%s",
            id_cuenta,
            monto,
            cuenta.estado,
            id_usuario,
        )

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="ABONO_CXC_OTRO",
            modulo="OTROS_MOVIMIENTOS",
            detalle={
                "id_cuenta": id_cuenta,
                "monto": str(monto),
                "estado_resultante": cuenta.estado,
            },
        )
        return cuenta

    @staticmethod
    def listar_cuentas_cobrar_otro(
        session: Session,
        estado: str | None = None,
        id_cliente: int | None = None,
        fecha_desde: date | datetime | None = None,
        fecha_hasta: date | datetime | None = None,
        id_usuario: int | None = None,
    ) -> list[CuentaPorCobrarOtro]:
        require_permiso(session, id_usuario, "otros_movimientos", "ver")
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
        """Registra una transferencia recibida sin poder identificar al cliente. Siempre
        respaldada por el movimiento bancario real que la trajo (`id_movimiento`): tiene que
        existir, ser un abono de ESA cuenta, no estar ya atribuido a un pago, no pasar de su
        monto, y cada movimiento origina una sola partida. Sin esto se podia inventar dinero
        sin respaldo, o usar una misma transferencia para saldar varias facturas."""
        require_permiso(session, creado_por, "otros_movimientos", "crear")
        monto = Decimal(str(monto))
        if monto <= 0:
            raise ValueError("monto debe ser mayor a cero")
        cuenta_bancaria = session.get(CuentaBancaria, id_cuenta_bancaria)
        if cuenta_bancaria is None:
            raise ValueError("Cuenta bancaria no encontrada")
        if cuenta_bancaria.estado_cuenta != "ACTIVO":
            raise ValueError(f"La cuenta bancaria '{cuenta_bancaria.numero_cuenta}' esta inactiva")
        if id_movimiento is None:
            raise ValueError("Indique el movimiento bancario de la transferencia (id_movimiento)")

        movimiento = session.execute(
            select(BancoMovimiento)
            .where(BancoMovimiento.id_movimiento == id_movimiento)
            .with_hint(BancoMovimiento, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        ).scalar_one_or_none()
        if movimiento is None:
            raise ValueError("Movimiento bancario no encontrado")
        if movimiento.id_cuenta != id_cuenta_bancaria:
            raise ValueError("El movimiento bancario pertenece a otra cuenta")
        if movimiento.tipo_movimiento != "abono":
            raise ValueError("Solo un abono (dinero recibido) puede quedar como transferencia sin identificar")
        if any(
            (
                movimiento.id_pago_cobro,
                movimiento.id_pago_proveedor,
                movimiento.id_pago_comision,
                movimiento.id_pago_cobro_bcv,
            )
        ):
            raise ValueError("Ese movimiento bancario ya esta asociado a un pago")
        if monto > (movimiento.monto_movimiento or Decimal("0")):
            raise ValueError(f"El monto excede el del movimiento bancario (${movimiento.monto_movimiento})")
        if session.query(CuentaPorPagarOtro.id_cuenta).filter_by(id_movimiento=id_movimiento).first() is not None:
            raise ValueError("Ese movimiento bancario ya tiene una transferencia sin identificar registrada")

        partida = CuentaPorPagarOtro(
            id_cuenta_bancaria=id_cuenta_bancaria,
            id_movimiento=id_movimiento,
            monto_total=monto,
            saldo_pendiente=monto,
            fecha_recepcion=datetime.now(),
            referencia_bancaria=referencia_bancaria or movimiento.referencia_movimiento,
            descripcion=descripcion,
            estado="pendiente",
            creado_por=creado_por,
        )
        session.add(partida)
        session.commit()
        session.refresh(partida)

        logger.info(
            "Partida no conciliada creada: id_cuenta=%s cuenta_bancaria=%s movimiento=%s monto=%s usuario=%s",
            partida.id_cuenta,
            id_cuenta_bancaria,
            id_movimiento,
            monto,
            creado_por,
        )

        AuditoriaService.registrar_evento(
            session,
            id_usuario=creado_por,
            accion="CREAR_PARTIDA_NO_CONCILIADA",
            modulo="OTROS_MOVIMIENTOS",
            detalle={
                "id_cuenta": partida.id_cuenta,
                "id_cuenta_bancaria": id_cuenta_bancaria,
                "id_movimiento": id_movimiento,
                "monto": str(monto),
            },
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
        require_permiso(session, id_usuario, "otros_movimientos", "editar")
        monto = Decimal(str(monto))
        if monto <= 0:
            raise ValueError("El monto debe ser mayor a cero")

        # Ver el comentario de registrar_abono_otro() -- mismo patron de C1.
        partida = session.execute(
            select(CuentaPorPagarOtro)
            .where(CuentaPorPagarOtro.id_cuenta == id_cuenta)
            .with_hint(CuentaPorPagarOtro, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        ).scalar_one_or_none()
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
        if cliente.estado_cliente != "ACTIVO":
            raise ValueError(f"El cliente '{cliente.nombre_razon_social}' esta inactivo")

        cxc = session.execute(
            select(CuentaPorCobrar)
            .where(CuentaPorCobrar.id_cuenta_por_cobrar == id_cuenta_por_cobrar)
            .with_hint(CuentaPorCobrar, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        ).scalar_one_or_none()
        if cxc is None:
            raise ValueError("Cuenta por cobrar no encontrada")
        if cxc.factura.id_cliente_factura != id_cliente:
            raise ValueError("La cuenta por cobrar indicada no pertenece al cliente identificado")
        # Solo una factura viva y con saldo: antes se podia "conciliar" contra una factura
        # anulada o ya pagada.
        if cxc.factura.estado_factura == "ANULADA" or cxc.estado not in ("pendiente", "parcial"):
            raise ValueError("La factura indicada no tiene saldo pendiente (esta pagada o anulada)")
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

        # Constancia de la aplicacion (aparece como abono en el historial del cliente).
        session.add(
            ConciliacionPartida(
                id_partida=partida.id_cuenta,
                id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
                monto=monto,
                fecha_conciliacion=partida.fecha_conciliacion,
                conciliado_por=id_usuario,
            )
        )

        session.commit()
        session.refresh(partida)
        session.refresh(cxc)

        logger.info(
            "Partida %s conciliada: cliente=%s cuenta_por_cobrar=%s monto=%s usuario=%s",
            partida.id_cuenta,
            id_cliente,
            id_cuenta_por_cobrar,
            monto,
            id_usuario,
        )

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
        id_usuario: int | None = None,
    ) -> list[CuentaPorPagarOtro]:
        """fecha_desde/fecha_hasta filtran por fecha_recepcion (estas partidas no tienen
        vencimiento propio, es dinero ya recibido pendiente de identificar). responsable
        filtra por quien registro la partida (creado_por) o quien la concilio (conciliado_por).
        """
        require_permiso(session, id_usuario, "otros_movimientos", "ver")
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
