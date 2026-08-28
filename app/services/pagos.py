import logging
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    Caja,
    Compra,
    CuentaBancaria,
    CuentaPorCobrar,
    CuentaPorPagar,
    FacturaVenta,
    PagoCobro,
    PagoProveedor,
)
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso

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

        monto = Decimal(str(monto))
        if monto <= 0:
            raise ValueError("El monto debe ser mayor a cero")

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
            monto_moneda_origen=Decimal(str(monto_moneda_origen)) if monto_moneda_origen is not None else None,
            referencia=referencia,
            fecha_pago=fecha_pago,
            creado_por=id_usuario,
        )
        session.add(pago)
        session.flush()
        return pago

    @staticmethod
    def registrar_pago_cobro(
        session: Session,
        id_cuenta_por_cobrar: int,
        monto,
        metodo_pago: str,
        moneda: str = "USD",
        monto_moneda_origen=None,
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
            id_cuenta_bancaria=id_cuenta_bancaria,
            id_caja=id_caja,
            id_tasa=id_tasa,
            referencia=referencia,
            fecha_pago=fecha_pago,
            id_usuario=id_usuario,
        )
        cuenta = session.get(CuentaPorCobrar, id_cuenta_por_cobrar)
        assert cuenta is not None  # ya validada por _aplicar_pago_cobro, no puede ser None aca
        session.commit()
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
            referencia=referencia,
            fecha_pago=fecha_pago,
            creado_por=id_usuario,
        )
        session.add(pago)
        session.commit()
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
        query = session.query(CuentaPorCobrar).join(FacturaVenta, FacturaVenta.id_factura == CuentaPorCobrar.id_factura)
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
