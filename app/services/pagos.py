import logging
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    Caja,
    Cliente,
    Compra,
    CuentaBancaria,
    CuentaPorCobrar,
    CuentaPorPagar,
    FacturaVenta,
    NotaCreditoCliente,
    PagoCobro,
    PagoProveedor,
)
from app.services.auditoria import AuditoriaService
from app.services.db_utils import _es_deadlock, _es_lock_timeout, aplicar_lock_timeout, traducir_error_trigger
from app.services.permisos import require_permiso
from app.utils.decimal_utils import to_decimal

logger = logging.getLogger(__name__)

# trg_pagos_cobros_io / trg_pagos_proveedores_io (INSTEAD OF INSERT) ya validan
# "exactamente un origen" y "monto <= saldo_pendiente" en la base de datos, pero lo
# hacen con RAISERROR: dejarlo pasar hasta ahi obligaria al caller a interpretar un
# pyodbc.ProgrammingError crudo. Se valida antes en Python para dar el mismo estilo de
# error (ValueError) que el resto de los servicios.


class PagoService:
    @staticmethod
    def _aplicar_pago_cobro(
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
    ) -> PagoCobro:
        """Nucleo de registrar_pago_cobro() sin el require_permiso ni el commit/refresh --
        extraido para que VentaService.emitir_factura() pueda aplicar varios pagos de
        contado en la MISMA transaccion atomica que la factura (flush, no commit), igual
        que ya hace ComisionService.calcular_comisiones_factura ahi mismo. Los callers
        directos (registrar_pago_cobro) siguen viendo el mismo commit-por-llamada de
        siempre."""
        if (id_cuenta_bancaria is None) == (id_caja is None):
            raise ValueError("Indique exactamente un origen del pago: cuenta bancaria o caja")

        monto = to_decimal(monto)
        if monto <= 0:
            raise ValueError("El monto debe ser mayor a cero")

        aplicar_lock_timeout(session)

        # WITH (UPDLOCK, ROWLOCK): sin esto, dos pagos concurrentes contra la MISMA cuenta
        # por cobrar (ej. dos cajeros cobrando la misma factura por error, o un doble clic)
        # pueden ambos leer el mismo saldo_pendiente antes de que ninguno commitee, pasar
        # el guard de abajo por separado y sobregirar la cuenta -- trg_pagos_cobros_io
        # arreglaria el segundo con un RAISERROR crudo (CK_saldo_pendiente_no_negativo,
        # migrations/0010) en vez de este ValueError legible, pero de igual forma dejaria
        # al segundo cajero viendo un error de SQL sin sentido. Mismo patron que Inventario/
        # Cliente en VentaService.emitir_factura (C1/C18).
        cuenta = session.execute(
            select(CuentaPorCobrar)
            .where(CuentaPorCobrar.id_cuenta_por_cobrar == id_cuenta_por_cobrar)
            .with_hint(CuentaPorCobrar, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        ).scalar_one_or_none()
        if cuenta is None:
            raise ValueError("Cuenta por cobrar no encontrada")
        if monto > cuenta.saldo_pendiente:
            raise ValueError(f"El monto {monto} excede el saldo pendiente {cuenta.saldo_pendiente}")

        if id_cuenta_bancaria is not None:
            cuenta_bancaria = session.get(CuentaBancaria, id_cuenta_bancaria)
            if cuenta_bancaria is None:
                raise ValueError("Cuenta bancaria no encontrada")
            if cuenta_bancaria.estado_cuenta != "ACTIVO":
                raise ValueError(f"La cuenta bancaria '{cuenta_bancaria.numero_cuenta}' esta inactiva")

        if id_caja is not None:
            # Mismo criterio que CajaService.registrar_movimiento_manual: un pago en
            # efectivo/via caja necesita un turno abierto, si no queda sin arqueo posible.
            caja = session.get(Caja, id_caja)
            if caja is None:
                raise ValueError("Caja no encontrada")
            if caja.fecha_apertura is None or caja.fecha_cierre is not None:
                raise ValueError(f"La caja '{caja.nombre_caja}' no tiene un turno abierto")

        # Reloj de la app (Python), no el del trigger (GETDATE()): CajaService.abrir_caja/
        # cerrar_caja tambien usan datetime.now() para fecha_apertura/fecha_cierre, y
        # trg_cajas_cierre compara fecha_registro de caja_movimientos contra ese rango. Si
        # se dejara que el trigger use GETDATE(), un desfase entre el reloj de la app y el
        # del SQL Server podria dejar un pago fuera del rango del turno (C12).
        if fecha_pago is None:
            fecha_pago = datetime.now()

        pago = PagoCobro(
            id_cuenta_por_cobrar=id_cuenta_por_cobrar,
            id_cuenta_bancaria=id_cuenta_bancaria,
            id_caja=id_caja,
            id_tasa=id_tasa,
            metodo_pago=metodo_pago,
            moneda=moneda,
            monto=monto,
            monto_moneda_origen=to_decimal(monto_moneda_origen) if monto_moneda_origen is not None else None,
            monto_bolivares=to_decimal(monto_bolivares) if monto_bolivares is not None else None,
            tasa_cambio=to_decimal(tasa_cambio) if tasa_cambio is not None else None,
            referencia=referencia,
            fecha_pago=fecha_pago,
            creado_por=id_usuario,
        )
        session.add(pago)
        try:
            session.flush()
        except Exception as e:
            session.rollback()
            if _es_deadlock(e):
                raise
            if _es_lock_timeout(e):
                raise ValueError("La operación tardó demasiado esperando acceso a la cuenta. Intente de nuevo.") from e
            raise ValueError(traducir_error_trigger(e)) from e
        return pago

    @staticmethod
    def registrar_pago_cobro(
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
    ) -> PagoCobro:
        require_permiso(session, id_usuario, "pagos", "crear")
        pago = PagoService._aplicar_pago_cobro(
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
        cuenta = session.get(CuentaPorCobrar, id_cuenta_por_cobrar)
        assert cuenta is not None  # ya validada por _aplicar_pago_cobro, no puede ser None aca
        try:
            session.commit()
        except Exception as e:
            session.rollback()
            if _es_deadlock(e):
                raise
            raise ValueError(f"Error al registrar pago de cobro: {str(e)}") from e
        session.refresh(pago)
        session.refresh(cuenta)

        logger.info(
            "Pago de cobro registrado: cuenta_por_cobrar=%s monto=%s moneda=%s metodo_pago=%s "
            "estado_resultante=%s usuario=%s",
            id_cuenta_por_cobrar,
            pago.monto,
            pago.moneda,
            pago.metodo_pago,
            cuenta.estado,
            id_usuario,
        )

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
        monto_bolivares=None,
        tasa_cambio=None,
    ) -> PagoProveedor:
        require_permiso(session, id_usuario, "pagos", "crear")
        if (id_cuenta_bancaria is None) == (id_caja is None):
            raise ValueError("Indique exactamente un origen del pago: cuenta bancaria o caja")

        monto = to_decimal(monto)
        if monto <= 0:
            raise ValueError("El monto debe ser mayor a cero")

        aplicar_lock_timeout(session)

        # WITH (UPDLOCK, ROWLOCK): evita race condition -- dos pagos concurrentes contra
        # la misma cuenta por pagar podrían ambos leer el mismo saldo_pendiente antes de
        # que ninguno commitee, pasar la validación cada uno por separado y sobreguirar
        # la cuenta. El lock serializa la segunda transacción hasta que la primera commitee.
        cuenta = session.execute(
            select(CuentaPorPagar)
            .where(CuentaPorPagar.id_cuenta == id_cuenta_por_pagar)
            .with_hint(CuentaPorPagar, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        ).scalar_one_or_none()
        if cuenta is None:
            raise ValueError("Cuenta por pagar no encontrada")
        if monto > cuenta.saldo_pendiente:
            raise ValueError(f"El monto {monto} excede el saldo pendiente {cuenta.saldo_pendiente}")

        if id_cuenta_bancaria is not None:
            cuenta_bancaria = session.get(CuentaBancaria, id_cuenta_bancaria)
            if cuenta_bancaria is None:
                raise ValueError("Cuenta bancaria no encontrada")
            if cuenta_bancaria.estado_cuenta != "ACTIVO":
                raise ValueError(f"La cuenta bancaria '{cuenta_bancaria.numero_cuenta}' esta inactiva")

        if id_caja is not None:
            # Mismo lock que registrar_compra -- serializa dos pagos concurrentes contra
            # la misma caja: si dos usuarios pagan en paralelo, un pago queda bloqueado
            # hasta que el otro commit y libera la fila.
            caja = session.execute(
                select(Caja)
                .where(Caja.id_caja == id_caja)
                .with_hint(Caja, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
            ).scalar_one_or_none()
            if caja is None:
                raise ValueError("Caja no encontrada")
            if caja.fecha_apertura is None or caja.fecha_cierre is not None:
                raise ValueError(f"La caja '{caja.nombre_caja}' no tiene un turno abierto")

        # Ver el comentario equivalente en registrar_pago_cobro (C12).
        if fecha_pago is None:
            fecha_pago = datetime.now()

        pago = PagoProveedor(
            id_cuenta_por_pagar=id_cuenta_por_pagar,
            id_cuenta_bancaria=id_cuenta_bancaria,
            id_caja=id_caja,
            id_tasa=id_tasa,
            metodo_pago=metodo_pago,
            monto=monto,
            monto_bolivares=to_decimal(monto_bolivares) if monto_bolivares is not None else None,
            tasa_cambio=to_decimal(tasa_cambio) if tasa_cambio is not None else None,
            referencia=referencia,
            fecha_pago=fecha_pago,
            creado_por=id_usuario,
        )
        session.add(pago)
        try:
            session.commit()
        except Exception as e:
            session.rollback()
            if _es_deadlock(e):
                raise
            if _es_lock_timeout(e):
                raise ValueError("La operación tardó demasiado esperando acceso a la cuenta. Intente de nuevo.") from e
            raise ValueError(traducir_error_trigger(e)) from e
        session.refresh(pago)
        session.refresh(cuenta)

        logger.info(
            "Pago a proveedor registrado: cuenta_por_pagar=%s monto=%s metodo_pago=%s estado_resultante=%s usuario=%s",
            id_cuenta_por_pagar,
            pago.monto,
            pago.metodo_pago,
            cuenta.estado,
            id_usuario,
        )

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

    @staticmethod
    def listar_cuentas_por_pagar(
        session: Session,
        id_proveedor: int | None = None,
        estado: str | None = None,
        pagina: int = 1,
        por_pagina: int = 20,
        id_usuario: int | None = None,
    ) -> dict:
        """Necesario para la pestana 'CxP' de app/ui/compras.py -- no existia ningun
        metodo de lectura sobre cuentas_por_pagar hasta ahora (el flujo OC->NR->Compra->Pago
        es el primero en necesitar mostrarlas en una pantalla, ver auditoria de Compras/
        Proveedores previa a este trabajo)."""
        require_permiso(session, id_usuario, "pagos", "ver")
        query = session.query(CuentaPorPagar).join(Compra, Compra.id_compra == CuentaPorPagar.id_compra)
        if id_proveedor:
            query = query.filter(Compra.id_proveedor == id_proveedor)
        if estado:
            query = query.filter(CuentaPorPagar.estado == estado)

        total = query.count()
        cuentas = (
            query.order_by(CuentaPorPagar.fecha_vencimiento).offset((pagina - 1) * por_pagina).limit(por_pagina).all()
        )
        return {"items": cuentas, "total": total, "pagina": pagina, "por_pagina": por_pagina}

    @staticmethod
    def listar_cuentas_por_cobrar(
        session: Session,
        id_cliente: int | None = None,
        estado: str | None = None,
        pagina: int = 1,
        por_pagina: int = 20,
        id_usuario: int | None = None,
    ) -> dict:
        """Analogo a listar_cuentas_por_pagar, para la pestana de consulta+cobro del modulo
        Cuentas por Cobrar (app/ui/cuentas_por_cobrar_panel.py) -- antes de esto no existia
        ningun metodo de lectura publico sobre cuentas_por_cobrar, la unica UI que tocaba
        el modulo era FacturacionPanel mostrando el estado derivado por factura.

        'vencida' nunca se persiste en cuentas_por_cobrar.estado (el CHECK la admite pero
        ningun trigger la asigna) -- se deriva con el mismo criterio que
        VentaService._calcular_estado_visual/listar_facturas: pendiente o parcial con
        fecha_vencimiento ya pasada. Filtrar por estado='pendiente'/'parcial' excluye las
        que ya vencieron (van aparte, bajo 'vencida') para que los 4 filtros sean
        mutuamente excluyentes en la UI, igual que el combo de FacturacionPanel.
        """
        require_permiso(session, id_usuario, "pagos", "ver")
        hoy = date.today()
        # Desde migrations/0024_pagos_contado_multimetodo.sql, trg_factura_venta_cxc abre
        # una CuentaPorCobrar tambien para facturas de CONTADO -- no porque haya algo que
        # cobrar (nace con saldo_pendiente=0 / estado='pagada' en la misma transaccion),
        # sino como vehiculo tecnico para poder registrar los PagoCobro de esa venta
        # (requieren un id_cuenta_por_cobrar, ver app/db/models.py). Ese registro es
        # relevante en el detalle de la factura (VentaService.obtener_factura), no en este
        # listado de gestion de cobros -- filtrar por 'credito' evita que facturas de
        # contado, sin nada pendiente de cobrar, aparezcan aca como si lo tuvieran.
        query = (
            session.query(CuentaPorCobrar)
            .join(FacturaVenta, FacturaVenta.id_factura == CuentaPorCobrar.id_factura)
            .filter(FacturaVenta.condicion_pago == "credito")
        )
        if id_cliente:
            query = query.filter(FacturaVenta.id_cliente_factura == id_cliente)
        if estado == "vencida":
            query = query.filter(
                CuentaPorCobrar.estado.in_(("pendiente", "parcial")),
                CuentaPorCobrar.fecha_vencimiento < hoy,
            )
        elif estado in ("pendiente", "parcial"):
            query = query.filter(
                CuentaPorCobrar.estado == estado,
                or_(CuentaPorCobrar.fecha_vencimiento.is_(None), CuentaPorCobrar.fecha_vencimiento >= hoy),
            )
        elif estado:
            query = query.filter(CuentaPorCobrar.estado == estado)

        total = query.count()
        cuentas = (
            query.order_by(CuentaPorCobrar.fecha_vencimiento).offset((pagina - 1) * por_pagina).limit(por_pagina).all()
        )

        # estado_visual: atributo Python plano (no mapeado), mismo criterio que
        # VentaService._calcular_estado_visual -- 'vencida' es una etiqueta de UI, no un
        # valor que exista realmente en la columna.
        for cuenta in cuentas:
            cuenta.estado_visual = (
                "vencida"
                if cuenta.estado in ("pendiente", "parcial")
                and cuenta.fecha_vencimiento is not None
                and cuenta.fecha_vencimiento < hoy
                else cuenta.estado
            )

        return {"items": cuentas, "total": total, "pagina": pagina, "por_pagina": por_pagina}

    @staticmethod
    def aplicar_abono_general_cliente(
        session: Session,
        id_cliente: int,
        monto_abono: Decimal,
        tasa_cambio: Decimal,
        metodo_pago: str,
        id_cuenta_bancaria: int | None = None,
        id_caja: int | None = None,
        id_tasa: int | None = None,
        referencia: str | None = None,
        id_usuario: int | None = None,
    ) -> dict:
        """Aplica un abono general a un cliente usando el método FIFO (First In, First Out).

        Distribuye el monto del abono entre las facturas pendientes del cliente,
        ordenadas por fecha de emisión (más antiguas primero), usando la tasa de cambio
        proporcionada para calcular equivalentes en bolívares.

        Args:
            session: Sesión de base de datos
            id_cliente: ID del cliente
            monto_abono: Monto total del abono en USD
            tasa_cambio: Tasa de cambio USD a Bs
            metodo_pago: Método de pago (efectivo, transferencia, etc.)
            id_cuenta_bancaria: ID de cuenta bancaria (opcional)
            id_caja: ID de caja (opcional)
            id_tasa: ID del registro de tasa (opcional)
            referencia: Referencia del pago (opcional)
            id_usuario: ID del usuario que realiza la operación

        Returns:
            dict con información del proceso:
            - facturas_actualizadas: lista de facturas afectadas
            - monto_total_aplicado: monto total aplicado
            - saldo_restante: saldo no aplicado (si hay sobreabono)
            - es_sobreabono: True si el abono excedió todas las deudas

        Raises:
            ValueError: Si hay errores de validación
        """
        require_permiso(session, id_usuario, "pagos", "crear")

        # Validaciones básicas
        monto_abono = to_decimal(monto_abono)
        if monto_abono <= 0:
            raise ValueError("El monto del abono debe ser mayor a cero")

        tasa_cambio = to_decimal(tasa_cambio)
        if tasa_cambio <= 0:
            raise ValueError("La tasa de cambio debe ser mayor a cero")

        if (id_cuenta_bancaria is None) == (id_caja is None):
            raise ValueError("Indique exactamente un origen del pago: cuenta bancaria o caja")

        # Validar origen del pago
        if id_cuenta_bancaria is not None:
            cuenta_bancaria = session.get(CuentaBancaria, id_cuenta_bancaria)
            if cuenta_bancaria is None:
                raise ValueError("Cuenta bancaria no encontrada")
            if cuenta_bancaria.estado_cuenta != "ACTIVO":
                raise ValueError(f"La cuenta bancaria '{cuenta_bancaria.numero_cuenta}' está inactiva")

        if id_caja is not None:
            caja = session.get(Caja, id_caja)
            if caja is None:
                raise ValueError("Caja no encontrada")
            if caja.fecha_apertura is None or caja.fecha_cierre is not None:
                raise ValueError(f"La caja '{caja.nombre_caja}' no tiene un turno abierto")

        # Obtener todas las cuentas por cobrar pendientes del cliente
        # Ordenadas por fecha de emisión de la factura (FIFO)
        try:
            cuentas_pendientes = (
                session.query(CuentaPorCobrar)
                .join(FacturaVenta, FacturaVenta.id_factura == CuentaPorCobrar.id_factura)
                .filter(
                    FacturaVenta.id_cliente_factura == id_cliente,
                    FacturaVenta.condicion_pago == "credito",
                    CuentaPorCobrar.estado.in_(("pendiente", "parcial")),
                    CuentaPorCobrar.saldo_pendiente > 0,
                )
                .order_by(FacturaVenta.fecha_emision.asc())
                .all()
            )
            logger.info(f"Cuentas pendientes encontradas para cliente {id_cliente}: {len(cuentas_pendientes)}")
        except Exception as e:
            logger.error(f"Error al obtener cuentas pendientes: {e}")
            raise ValueError(f"Error al obtener cuentas pendientes: {str(e)}") from e

        # Calcular total de deuda (si hay facturas pendientes)
        if cuentas_pendientes:
            try:
                total_deuda = sum(cuenta.saldo_pendiente for cuenta in cuentas_pendientes)
                logger.info(f"Total deuda calculada: {total_deuda}")
            except Exception as e:
                logger.error(f"Error al calcular total deuda: {e}")
                raise ValueError(f"Error al calcular total deuda: {str(e)}") from e
        else:
            total_deuda = Decimal("0.00")
            logger.info(f"Cliente {id_cliente} no tiene facturas pendientes, todo el abono quedará como saldo a favor")

        # Verificar si es sobreabono o pago sin facturas
        es_sobreabono = monto_abono > total_deuda
        monto_a_aplicar = min(monto_abono, total_deuda)
        saldo_restante = monto_abono - monto_a_aplicar

        # Iniciar transacción
        try:
            facturas_actualizadas = []
            monto_restante = monto_a_aplicar

            # Determinar si es pago en efectivo (no incluye tasa en descripción)
            es_efectivo = metodo_pago == "efectivo"

            # Si no hay facturas pendientes, registrar directamente como saldo a favor
            if not cuentas_pendientes:
                logger.info(f"Registrando abono sin facturas pendientes para cliente {id_cliente}: ${monto_abono}")

                # Registrar movimiento de caja/banco
                fecha = datetime.now()
                cliente = session.get(Cliente, id_cliente)
                nombre_cliente = cliente.nombre_razon_social if cliente else "Desconocido"
                descripcion = f"Abono anticipado - {nombre_cliente}"
                if referencia:
                    descripcion += f" (Ref: {referencia})"
                monto_abono_bs = monto_abono * tasa_cambio

                if id_caja is not None:
                    from app.services.tesoreria import CajaService
                    CajaService._registrar_ingreso_excedente(
                        session,
                        id_caja=id_caja,
                        monto=monto_abono,
                        descripcion=descripcion,
                        id_usuario=id_usuario,
                        fecha=fecha,
                    )
                else:
                    from app.services.tesoreria import BancoService
                    BancoService._registrar_ingreso_excedente(
                        session,
                        id_cuenta=id_cuenta_bancaria,
                        monto=monto_abono,
                        descripcion=descripcion,
                        id_usuario=id_usuario,
                        fecha=fecha,
                        monto_bolivares=monto_abono_bs,
                        tasa_cambio=tasa_cambio,
                    )
            else:
                # Aplicar pagos usando FIFO
                for cuenta in cuentas_pendientes:
                    if monto_restante <= 0:
                        break

                    # Calcular monto a aplicar a esta factura
                    saldo_pendiente = cuenta.saldo_pendiente
                    monto_aplicar = min(monto_restante, saldo_pendiente)

                    # Calcular equivalentes en Bs
                    monto_aplicado_bs = monto_aplicar * tasa_cambio

                    # Generar descripción de auditoría (sin tasa para efectivo)
                    if es_efectivo:
                        descripcion_auditoria = (
                            f"Abono general efectivo: ${float(monto_aplicar):.2f} / "
                            f"Restante: ${float(monto_restante - monto_aplicar):.2f}"
                        )
                    else:
                        descripcion_auditoria = (
                            f"Abono general: ${float(monto_aplicar):.2f} ({float(monto_aplicado_bs):.2f} Bs) / "
                            f"Tasa: {float(tasa_cambio):.2f} / "
                            f"Restante: ${float(monto_restante - monto_aplicar):.2f}"
                        )

                    # Crear registro de pago
                    pago = PagoCobro(
                        id_cuenta_por_cobrar=cuenta.id_cuenta_por_cobrar,
                        id_cuenta_bancaria=id_cuenta_bancaria,
                        id_caja=id_caja,
                        id_tasa=id_tasa,
                        metodo_pago=metodo_pago,
                        moneda="USD",
                        monto=monto_aplicar,
                        monto_bolivares=monto_aplicado_bs,
                        tasa_cambio=tasa_cambio,
                        referencia=referencia,
                        fecha_pago=datetime.now(),
                        creado_por=id_usuario,
                    )
                    session.add(pago)
                    session.flush()  # Flush para obtener el ID del pago

                    # Actualizar saldo de la cuenta por cobrar
                    cuenta.saldo_pendiente -= monto_aplicar

                    # Actualizar estado según el saldo restante
                    if cuenta.saldo_pendiente <= 0:
                        cuenta.estado = "pagada"
                        cuenta.saldo_pendiente = Decimal("0.00")
                    else:
                        cuenta.estado = "parcial"

                    # Actualizar observaciones de la factura si existe (truncando si es necesario)
                    if cuenta.factura:
                        observaciones_actuales = cuenta.factura.observaciones_factura or ""
                        separador = " | " if observaciones_actuales else ""
                        nueva_observacion = f"{observaciones_actuales}{separador}{descripcion_auditoria}"

                        # Truncar a 255 caracteres si es necesario
                        if len(nueva_observacion) > 255:
                            nueva_observacion = nueva_observacion[:252] + "..."
                        cuenta.factura.observaciones_factura = nueva_observacion

                    facturas_actualizadas.append({
                        "id_cuenta_por_cobrar": cuenta.id_cuenta_por_cobrar,
                        "id_factura": cuenta.id_factura,
                        "numero_factura": cuenta.factura.numero_factura if cuenta.factura else "N/A",
                        "monto_aplicado": monto_aplicar,
                        "monto_aplicado_bs": monto_aplicado_bs,
                        "saldo_restante_factura": cuenta.saldo_pendiente,
                        "estado_resultante": cuenta.estado,
                        "descripcion_auditoria": descripcion_auditoria,
                    })

                    # Actualizar monto restante
                    monto_restante -= monto_aplicar

            # Si hay sobreabono o no hay facturas pendientes, crear nota de crédito como saldo a favor del cliente
            nota_credito_id = None
            if (es_sobreabono or not cuentas_pendientes) and saldo_restante > 0:
                try:
                    cliente = session.get(Cliente, id_cliente)
                    if cliente:
                        # Crear nota de crédito por el excedente o por pago sin facturas
                        if cuentas_pendientes:
                            motivo = f"Sobreabono por pago en exceso - {metodo_pago}"
                        else:
                            motivo = f"Abono anticipado sin facturas pendientes - {metodo_pago}"
                        nota_credito = NotaCreditoCliente(
                            numero_nota_credito=f"ABONO-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                            id_cliente=id_cliente,
                            id_factura_origen=None,  # No asociada a una factura específica
                            monto=saldo_restante,
                            saldo_disponible=saldo_restante,
                            motivo=motivo,
                            estado="disponible",
                            creado_por=id_usuario,
                            fecha_creacion=datetime.now(),
                        )
                        session.add(nota_credito)
                        session.flush()
                        nota_credito_id = nota_credito.id_nota_credito

                        logger.info(
                            "Nota de crédito creada por sobreabono: cliente=%s monto=%s metodo=%s nota_id=%s",
                            id_cliente,
                            saldo_restante,
                            metodo_pago,
                            nota_credito_id,
                        )
                except Exception as e:
                    logger.warning("No se pudo crear nota de crédito por sobreabono: %s", e)
                    # No fallar toda la transacción si falla la nota de crédito

            # Commit de la transacción
            session.commit()

            # Registrar evento de auditoría general
            AuditoriaService.registrar_evento(
                session,
                id_usuario=id_usuario,
                accion="ABONO_GENERAL_CLIENTE",
                modulo="TESORERIA",
                detalle={
                    "id_cliente": id_cliente,
                    "monto_abono": str(monto_abono),
                    "tasa_cambio": str(tasa_cambio),
                    "monto_total_aplicado": str(monto_a_aplicar),
                    "saldo_restante": str(saldo_restante),
                    "es_sobreabono": es_sobreabono,
                    "facturas_actualizadas": len(facturas_actualizadas),
                    "nota_credito_id": nota_credito_id,
                },
            )

            logger.info(
                "Abono general aplicado: cliente=%s monto_abono=%s tasa_cambio=%s "
                "monto_aplicado=%s facturas_actualizadas=%s es_sobreabono=%s nota_credito=%s",
                id_cliente,
                monto_abono,
                tasa_cambio,
                monto_a_aplicar,
                len(facturas_actualizadas),
                es_sobreabono,
                nota_credito_id,
            )

            return {
                "facturas_actualizadas": facturas_actualizadas,
                "monto_total_aplicado": monto_a_aplicar,
                "saldo_restante": saldo_restante,
                "es_sobreabono": es_sobreabono,
                "tasa_cambio_utilizada": tasa_cambio,
                "nota_credito_id": nota_credito_id,
            }

        except Exception as e:
            session.rollback()
            if _es_deadlock(e):
                raise
            if _es_lock_timeout(e):
                raise ValueError(
                    "La operación tardó demasiado esperando acceso a las cuentas. Intente de nuevo."
                ) from e
            raise ValueError(f"Error al aplicar abono general: {str(e)}") from e

    @staticmethod
    def listar_cuentas_por_cobrar_por_cliente(
        session: Session,
        id_cliente: int | None = None,
        id_vendedor: int | None = None,
        estado: str | None = None,
        pagina: int = 1,
        por_pagina: int = 20,
        id_usuario: int | None = None,
    ) -> dict:
        """Lista cuentas por cobrar agrupadas por cliente con el saldo total pendiente.
        Retorna una fila por cliente con la suma de todos los saldos pendientes de sus facturas.
        También incluye clientes que solo tienen saldo a favor (notas de crédito disponibles)."""
        require_permiso(session, id_usuario, "pagos", "ver")
        hoy = date.today()

        # Query base para obtener todas las cuentas relevantes
        query = (
            session.query(CuentaPorCobrar)
            .join(FacturaVenta, FacturaVenta.id_factura == CuentaPorCobrar.id_factura)
            .join(Cliente, Cliente.id_cliente == FacturaVenta.id_cliente_factura)
            .filter(FacturaVenta.condicion_pago == "credito")
        )

        if id_cliente:
            query = query.filter(FacturaVenta.id_cliente_factura == id_cliente)
        if id_vendedor:
            query = query.filter(Cliente.vendedor_cliente == id_vendedor)
        if estado == "vencida":
            query = query.filter(
                CuentaPorCobrar.estado.in_(("pendiente", "parcial")),
                CuentaPorCobrar.fecha_vencimiento < hoy,
            )
        elif estado in ("pendiente", "parcial"):
            query = query.filter(
                CuentaPorCobrar.estado == estado,
                or_(CuentaPorCobrar.fecha_vencimiento.is_(None), CuentaPorCobrar.fecha_vencimiento >= hoy),
            )
        elif estado:
            query = query.filter(CuentaPorCobrar.estado == estado)

        # Obtener todas las cuentas (sin paginación para agrupar correctamente)
        todas_las_cuentas = query.all()

        # Agrupar por cliente
        clientes_deuda = {}
        for cuenta in todas_las_cuentas:
            if cuenta.factura and cuenta.factura.cliente:
                cliente = cuenta.factura.cliente
                id_cliente_key = cliente.id_cliente

                if id_cliente_key not in clientes_deuda:
                    # Manejo seguro del campo saldo_favor (puede no existir si no se ejecutó la migración)
                    saldo_favor = Decimal("0.00")
                    try:
                        saldo_favor = getattr(cuenta, 'saldo_favor', Decimal("0.00"))
                        if saldo_favor is None:
                            saldo_favor = Decimal("0.00")
                    except Exception:
                        saldo_favor = Decimal("0.00")
                    
                    clientes_deuda[id_cliente_key] = {
                        "cliente": cliente,
                        "saldo_total": Decimal("0.00"),
                        "saldo_favor": saldo_favor,
                        "cuentas": [],
                        "fecha_vencimiento_mas_antigua": None,
                        "fecha_emision_mas_antigua_pendiente": None,
                    }

                clientes_deuda[id_cliente_key]["saldo_total"] += cuenta.saldo_pendiente
                clientes_deuda[id_cliente_key]["cuentas"].append(cuenta)
                
                # Actualizar saldo_favor con el valor más alto encontrado (por si hay inconsistencias)
                try:
                    cuenta_saldo_favor = getattr(cuenta, 'saldo_favor', Decimal("0.00"))
                    if cuenta_saldo_favor is None:
                        cuenta_saldo_favor = Decimal("0.00")
                    
                    saldo_favor_actual = clientes_deuda[id_cliente_key]["saldo_favor"]
                    if saldo_favor_actual is None:
                        saldo_favor_actual = Decimal("0.00")
                    
                    if cuenta_saldo_favor and cuenta_saldo_favor > saldo_favor_actual:
                        clientes_deuda[id_cliente_key]["saldo_favor"] = cuenta_saldo_favor
                except Exception:
                    pass

                # Calcular fecha de vencimiento más antigua
                if cuenta.fecha_vencimiento:
                    if clientes_deuda[id_cliente_key]["fecha_vencimiento_mas_antigua"] is None:
                        clientes_deuda[id_cliente_key]["fecha_vencimiento_mas_antigua"] = cuenta.fecha_vencimiento
                    else:
                        clientes_deuda[id_cliente_key]["fecha_vencimiento_mas_antigua"] = min(
                            clientes_deuda[id_cliente_key]["fecha_vencimiento_mas_antigua"],
                            cuenta.fecha_vencimiento,
                        )

                # Calcular fecha de emisión más antigua para facturas pendientes
                if cuenta.estado in ("pendiente", "parcial") and cuenta.factura and cuenta.factura.fecha_emision:
                    fecha_emision = cuenta.factura.fecha_emision.date()
                    if clientes_deuda[id_cliente_key]["fecha_emision_mas_antigua_pendiente"] is None:
                        clientes_deuda[id_cliente_key]["fecha_emision_mas_antigua_pendiente"] = fecha_emision
                    else:
                        clientes_deuda[id_cliente_key]["fecha_emision_mas_antigua_pendiente"] = min(
                            clientes_deuda[id_cliente_key]["fecha_emision_mas_antigua_pendiente"],
                            fecha_emision,
                        )

        # Convertir a lista y ordenar por saldo total (de mayor a menor)
        clientes_lista = sorted(
            clientes_deuda.values(),
            key=lambda x: x["saldo_total"],
            reverse=True,
        )

        # Aplicar paginación
        total = len(clientes_lista)
        inicio = (pagina - 1) * por_pagina
        fin = inicio + por_pagina
        clientes_paginados = clientes_lista[inicio:fin]

        # Calcular días transcurridos para cada cliente
        for cliente_data in clientes_paginados:
            fecha_emision = cliente_data["fecha_emision_mas_antigua_pendiente"]
            if fecha_emision:
                dias_transcurridos = (hoy - fecha_emision).days
                cliente_data["dias_transcurridos"] = dias_transcurridos
            else:
                cliente_data["dias_transcurridos"] = 0

        return {
            "items": clientes_paginados,
            "total": total,
            "pagina": pagina,
            "por_pagina": por_pagina,
        }
