import logging
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    Caja,
    Cliente,
    CuentaBancaria,
    CuentaPorCobrarBCV,
    FacturaVenta,
)
from app.services.auditoria import AuditoriaService
from app.services.db_utils import _es_deadlock, _es_lock_timeout, aplicar_lock_timeout, traducir_error_trigger
from app.services.permisos import require_permiso
from app.utils.decimal_utils import to_decimal

logger = logging.getLogger(__name__)


class PagoBCVService:
    """Servicio para gestionar pagos de cuentas por cobrar BCV.
    
    Similar a PagoService pero operando sobre cuentas_por_cobrar_bcv
    en lugar de cuentas_por_cobrar regulares.
    """

    @staticmethod
    def _aplicar_pago_cobro_bcv(
        session: Session,
        id_cuenta_por_cobrar: int,
        monto,
        metodo_pago: str,
        moneda: str = "USD",
        monto_moneda_origen=None,
        monto_bolivares=None,
        tasa_cambio=None,
        id_cuenta_bancaria: int | None = None,
        id_caja: int | None = None,
        id_tasa: int | None = None,
        referencia: str | None = None,
        fecha_pago: date | datetime | None = None,
        id_usuario: int | None = None,
    ):
        """Núcleo de registrar_pago_cobro_bcv() sin el require_permiso ni el commit/refresh."""
        if (id_cuenta_bancaria is None) == (id_caja is None):
            raise ValueError("Indique exactamente un origen del pago: cuenta bancaria o caja")

        monto = to_decimal(monto)
        if monto <= 0:
            raise ValueError("El monto debe ser mayor a cero")

        aplicar_lock_timeout(session)

        # WITH (UPDLOCK, ROWLOCK): previene race condition similar a PagoService
        cuenta = session.execute(
            select(CuentaPorCobrarBCV)
            .where(CuentaPorCobrarBCV.id_cuenta_por_cobrar == id_cuenta_por_cobrar)
            .with_hint(CuentaPorCobrarBCV, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        ).scalar_one_or_none()
        if cuenta is None:
            raise ValueError("Cuenta por cobrar BCV no encontrada")
        if monto > cuenta.saldo_pendiente:
            raise ValueError(f"El monto {monto} excede el saldo pendiente {cuenta.saldo_pendiente}")

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

        if fecha_pago is None:
            fecha_pago = datetime.now()

        # Crear registro de pago similar a PagoCobro pero para BCV
        # Nota: Necesitaríamos crear un modelo PagoCobroBCV o reutilizar PagoCobro
        # Por ahora, vamos a asumir que usamos la misma tabla pagos_cobros
        # con un indicador de que es BCV, o creamos una tabla separada
        # Para simplificar, vamos a registrar el pago y actualizar la cuenta
        
        # Actualizar saldo pendiente
        cuenta.saldo_pendiente = cuenta.saldo_pendiente - monto
        
        # Determinar nuevo estado
        if cuenta.saldo_pendiente <= 0:
            cuenta.estado = "pagada"
            cuenta.saldo_pendiente = Decimal("0.00")
        elif cuenta.saldo_pendiente < (cuenta.factura.total_venta if cuenta.factura else Decimal("0.00")):
            cuenta.estado = "parcial"
        
        session.add(cuenta)
        try:
            session.flush()
        except Exception as e:
            session.rollback()
            if _es_deadlock(e):
                raise
            if _es_lock_timeout(e):
                raise ValueError("La operación tardó demasiado esperando acceso a la cuenta. Intente de nuevo.") from e
            raise ValueError(traducir_error_trigger(e)) from e
        return cuenta

    @staticmethod
    def registrar_pago_cobro_bcv(
        session: Session,
        id_cuenta_por_cobrar: int,
        monto,
        metodo_pago: str,
        moneda: str = "USD",
        monto_moneda_origen=None,
        monto_bolivares=None,
        tasa_cambio=None,
        id_cuenta_bancaria: int | None = None,
        id_caja: int | None = None,
        id_tasa: int | None = None,
        referencia: str | None = None,
        fecha_pago: date | datetime | None = None,
        id_usuario: int | None = None,
    ):
        require_permiso(session, id_usuario, "pagos", "crear")
        cuenta = PagoBCVService._aplicar_pago_cobro_bcv(
            session,
            id_cuenta_por_cobrar=id_cuenta_por_cobrar,
            monto=monto,
            metodo_pago=metodo_pago,
            moneda=moneda,
            monto_moneda_origen=monto_moneda_origen,
            monto_bolivares=monto_bolivares,
            tasa_cambio=tasa_cambio,
            id_cuenta_bancaria=id_cuenta_bancaria,
            id_caja=id_caja,
            id_tasa=id_tasa,
            referencia=referencia,
            fecha_pago=fecha_pago,
            id_usuario=id_usuario,
        )
        try:
            session.commit()
        except Exception as e:
            session.rollback()
            if _es_deadlock(e):
                raise
            raise ValueError(f"Error al registrar pago de cobro BCV: {str(e)}") from e
        session.refresh(cuenta)

        logger.info(
            "Pago de cobro BCV registrado: cuenta_por_cobrar_bcv=%s monto=%s moneda=%s metodo_pago=%s "
            "estado_resultante=%s usuario=%s",
            id_cuenta_por_cobrar,
            monto,
            moneda,
            metodo_pago,
            cuenta.estado,
            id_usuario,
        )

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="PAGO_COBRO_BCV",
            modulo="TESORERIA",
            detalle={
                "id_cuenta_por_cobrar": id_cuenta_por_cobrar,
                "monto": str(monto),
                "estado_resultante": cuenta.estado,
            },
        )
        return cuenta

    @staticmethod
    def listar_cuentas_por_cobrar_bcv(
        session: Session,
        id_cliente: int | None = None,
        estado: str | None = None,
        pagina: int = 1,
        por_pagina: int = 20,
        id_usuario: int | None = None,
        busqueda: str | None = None,
    ) -> dict:
        """Análogo a listar_cuentas_por_cobrar pero para cuentas BCV."""
        require_permiso(session, id_usuario, "pagos", "ver")
        hoy = date.today()
        query = (
            session.query(CuentaPorCobrarBCV)
            .join(FacturaVenta, FacturaVenta.id_factura == CuentaPorCobrarBCV.id_factura)
            .join(Cliente, Cliente.id_cliente == FacturaVenta.id_cliente_factura)
        )
        if id_cliente:
            query = query.filter(FacturaVenta.id_cliente_factura == id_cliente)
        if busqueda:
            query = query.filter(Cliente.nombre_razon_social.ilike(f"%{busqueda}%"))
        if estado == "vencida":
            query = query.filter(
                CuentaPorCobrarBCV.estado.in_(("pendiente", "parcial")),
                CuentaPorCobrarBCV.fecha_vencimiento < hoy,
            )
        elif estado in ("pendiente", "parcial"):
            query = query.filter(
                CuentaPorCobrarBCV.estado == estado,
                or_(CuentaPorCobrarBCV.fecha_vencimiento.is_(None), CuentaPorCobrarBCV.fecha_vencimiento >= hoy),
            )
        elif estado:
            query = query.filter(CuentaPorCobrarBCV.estado == estado)

        total = query.count()
        logger.info(f"BCV - Listar cuentas: estado filtro={estado}, busqueda={busqueda}, total encontrado={total}")
        
        cuentas = (
            query.options(
                joinedload(CuentaPorCobrarBCV.factura).joinedload(FacturaVenta.cliente)
            )
            .order_by(CuentaPorCobrarBCV.fecha_vencimiento.desc())
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
            .all()
        )

        logger.info(f"BCV - Cuentas recuperadas: {len(cuentas)}")

        # estado_visual: atributo Python plano (no mapeado)
        for cuenta in cuentas:
            cuenta.estado_visual = (
                "vencida"
                if cuenta.estado in ("pendiente", "parcial")
                and cuenta.fecha_vencimiento is not None
                and cuenta.fecha_vencimiento < hoy
                else cuenta.estado
            )
            logger.info(
                f"BCV - Cuenta: ID={cuenta.id_cuenta_por_cobrar}, estado={cuenta.estado}, "
                f"estado_visual={cuenta.estado_visual}, saldo={cuenta.saldo_pendiente}"
            )

        return {"items": cuentas, "total": total, "pagina": pagina, "por_pagina": por_pagina}

    @staticmethod
    def listar_cuentas_por_cobrar_bcv_agrupadas(
        session: Session,
        id_cliente: int | None = None,
        estado: str | None = None,
        pagina: int = 1,
        por_pagina: int = 20,
        id_usuario: int | None = None,
        busqueda: str | None = None,
    ) -> dict:
        """Lista cuentas por cobrar BCV agrupadas por cliente con saldo pendiente acumulado."""
        require_permiso(session, id_usuario, "pagos", "ver")
        hoy = date.today()

        # Query base con joins
        query = (
            session.query(
                Cliente.id_cliente,
                Cliente.nombre_razon_social,
                func.sum(CuentaPorCobrarBCV.saldo_pendiente).label("saldo_pendiente_total"),
                func.sum(CuentaPorCobrarBCV.saldo_favor).label("saldo_favor_total"),
                func.count(CuentaPorCobrarBCV.id_cuenta_por_cobrar).label("cantidad_cuentas"),
                func.min(CuentaPorCobrarBCV.fecha_vencimiento).label("fecha_vencimiento_min"),
                func.min(CuentaPorCobrarBCV.fecha_emision).label("fecha_emision_min"),
                func.min(CuentaPorCobrarBCV.dias_credito).label("dias_credito_min"),
            )
            .join(FacturaVenta, FacturaVenta.id_factura == CuentaPorCobrarBCV.id_factura)
            .join(Cliente, Cliente.id_cliente == FacturaVenta.id_cliente_factura)
            .group_by(Cliente.id_cliente, Cliente.nombre_razon_social)
        )

        # Filtros
        if id_cliente:
            query = query.filter(FacturaVenta.id_cliente_factura == id_cliente)
        if busqueda:
            query = query.filter(Cliente.nombre_razon_social.ilike(f"%{busqueda}%"))

        # Filtro por estado
        if estado == "vencida":
            query = query.filter(
                CuentaPorCobrarBCV.estado.in_(("pendiente", "parcial")),
                CuentaPorCobrarBCV.fecha_vencimiento < hoy,
            )
        elif estado in ("pendiente", "parcial"):
            query = query.filter(
                CuentaPorCobrarBCV.estado == estado,
                or_(CuentaPorCobrarBCV.fecha_vencimiento.is_(None), CuentaPorCobrarBCV.fecha_vencimiento >= hoy),
            )
        elif estado:
            query = query.filter(CuentaPorCobrarBCV.estado == estado)
        else:
            # Por defecto, solo mostrar cuentas pendientes/parciales
            query = query.filter(CuentaPorCobrarBCV.estado.in_(("pendiente", "parcial")))

        # Solo mostrar clientes con saldo pendiente > 0
        query = query.having(func.sum(CuentaPorCobrarBCV.saldo_pendiente) > 0)

        total = query.count()
        logger.info(
            f"BCV - Listar cuentas agrupadas: estado filtro={estado}, "
            f"busqueda={busqueda}, total clientes={total}"
        )

        # Ejecutar query con paginación
        resultados = (
            query.order_by(Cliente.nombre_razon_social)
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
            .all()
        )

        # Construir lista de objetos agrupados
        items = []
        for row in resultados:
            # Determinar estado visual basado en la fecha de vencimiento más antigua
            fecha_venc_min = row.fecha_vencimiento_min
            estado_visual = "pendiente"
            if fecha_venc_min and fecha_venc_min < hoy:
                estado_visual = "vencida"

            # Crear objeto simple con los datos agrupados
            saldo_pendiente = (
                Decimal(str(row.saldo_pendiente_total))
                if row.saldo_pendiente_total
                else Decimal("0.00")
            )
            saldo_favor = (
                Decimal(str(row.saldo_favor_total))
                if row.saldo_favor_total
                else Decimal("0.00")
            )

            item = type('obj', (object,), {
                'id_cliente': row.id_cliente,
                'nombre_cliente': row.nombre_razon_social,
                'saldo_pendiente': saldo_pendiente,
                'saldo_favor': saldo_favor,
                'cantidad_cuentas': row.cantidad_cuentas,
                'fecha_vencimiento': fecha_venc_min,
                'fecha_emision': row.fecha_emision_min,
                'dias_credito': row.dias_credito_min,
                'estado': estado_visual,
                'estado_visual': estado_visual,
            })()
            items.append(item)

        logger.info(f"BCV - Clientes agrupados recuperados: {len(items)}")

        return {"items": items, "total": total, "pagina": pagina, "por_pagina": por_pagina}
