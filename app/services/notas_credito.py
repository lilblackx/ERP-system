import logging
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Caja,
    CuentaBancaria,
    CuentaPorCobrar,
    FacturaVenta,
    NotaCreditoCliente,
    NotaCreditoProveedor,
)
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso
from app.services.tesoreria import BancoService, CajaService

logger = logging.getLogger(__name__)


def _numero_nota_credito_temporal() -> str:
    """Placeholder unico para el INSERT inicial: numero_nota_credito es NOT NULL UNIQUE y
    el numero definitivo (NC-{id_nota_credito:06d}) solo se conoce despues del flush que
    asigna el id autoincremental -- mismo patron y motivo que
    VentaService._numero_factura_temporal(): evita la carrera de leer MAX(id)+1 sin lock
    entre dos anulaciones concurrentes, que violaria UQ_notas_credito_clientes_numero."""
    return f"TMP-{uuid.uuid4().hex[:16]}"


class NotaCreditoService:
    """Saldo a favor de un cliente/proveedor generado cuando se anula una factura/compra
    que ya tenia pagos aplicados. Ver la nota en VentaService.anular_factura() y
    CompraService.anular_compra() para por que existe: no revierte el pago original (ese
    dinero, y el movimiento de caja/banco que lo trajo, quedan intactos), solo deja
    constancia de que se le debe. Del lado cliente ya existen las dos formas de
    consumirla (2026-08-27): aplicar_nota_credito_cliente() (abono a otra factura del
    mismo cliente, transferencia contable interna, sin mover caja/banco) y
    devolver_nota_credito_cliente() (egreso real de efectivo/banco, SIEMPRE con
    autorizacion de supervisor). El lado proveedor (NotaCreditoProveedor) sigue sin un
    flujo de consumo -- desarrollo aparte, pendiente si el negocio lo necesita.

    NotaCreditoCliente es un documento fiscal que la empresa emite (reduce lo que el
    cliente le debe): tiene numero_nota_credito correlativo, igual que numero_factura,
    para poder reportarlo al SENIAT cuando se solicite -- ver listar_notas_credito_clientes().

    NotaCreditoProveedor NO es un documento fiscal nuestro: si anulamos una compra ya
    pagada, quien debe emitir la nota de credito es el proveedor hacia nosotros, no al
    reves. Por eso no tiene correlativo -- es solo un registro interno de que se nos debe.
    """

    @staticmethod
    def _crear_nota_credito_cliente(
        session: Session,
        id_cliente: int,
        id_factura_origen: int,
        monto,
        motivo: str,
        id_usuario: int | None,
    ) -> NotaCreditoCliente:
        """Nucleo sin commit propio -- para que VentaService.anular_factura() pueda crear
        la nota de credito en la MISMA transaccion atomica que la anulacion (antes cada una
        comiteaba por separado: si esta insercion fallaba -- p. ej. por la carrera de
        numero_nota_credito que esto tambien corrige -- la anulacion ya habia quedado
        comprometida sin su compensacion, y el dinero que el cliente ya pago desaparecia
        contablemente sin dejar rastro ni forma de revertir)."""
        monto = Decimal(str(monto))
        if monto <= 0:
            raise ValueError("monto debe ser mayor a cero")

        nota = NotaCreditoCliente(
            numero_nota_credito=_numero_nota_credito_temporal(),
            id_cliente=id_cliente,
            id_factura_origen=id_factura_origen,
            monto=monto,
            saldo_disponible=monto,
            motivo=motivo,
            estado="disponible",
            creado_por=id_usuario,
        )
        session.add(nota)
        session.flush()
        nota.numero_nota_credito = f"NC-{nota.id_nota_credito:06d}"
        return nota

    @staticmethod
    def crear_nota_credito_cliente(
        session: Session,
        id_cliente: int,
        id_factura_origen: int,
        monto,
        motivo: str,
        id_usuario: int | None,
    ) -> NotaCreditoCliente:
        # Sin require_permiso a proposito: este metodo publico (y su nucleo
        # _crear_nota_credito_cliente) son un efecto secundario interno de una accion ya
        # autorizada -- VentaService.anular_factura()/CompraService.anular_compra() ya
        # exigen su propio require_permiso("ventas"/"compras", "eliminar") antes de
        # generar la nota, mismo criterio que id_tasa en VentaService.emitir_factura. No
        # existe ningun callsite de UI que llame a este metodo publico directamente
        # (solo tests, que lo usan con id_usuario=None para probarlo en aislamiento).
        nota = NotaCreditoService._crear_nota_credito_cliente(
            session,
            id_cliente=id_cliente,
            id_factura_origen=id_factura_origen,
            monto=monto,
            motivo=motivo,
            id_usuario=id_usuario,
        )
        session.commit()
        session.refresh(nota)

        logger.info(
            "Nota de credito %s generada: cliente=%s factura_origen=%s monto=%s usuario=%s",
            nota.numero_nota_credito,
            id_cliente,
            id_factura_origen,
            monto,
            id_usuario,
        )

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="NOTA_CREDITO_CLIENTE",
            modulo="NOTAS_CREDITO",
            detalle={
                "numero_nota_credito": nota.numero_nota_credito,
                "id_cliente": id_cliente,
                "id_factura_origen": id_factura_origen,
                "monto": str(monto),
            },
        )
        return nota

    @staticmethod
    def aplicar_nota_credito_cliente(
        session: Session,
        id_nota_credito: int,
        id_factura_destino: int,
        monto,
        id_usuario: int | None,
    ) -> NotaCreditoCliente:
        """Aplica (total o parcialmente) una nota de credito disponible como abono a OTRA
        factura del MISMO cliente que todavia tenga saldo pendiente. Es una transferencia
        contable interna, no un pago real -- el dinero ya entro fisicamente cuando se
        cobro la factura que origino la nota (ver anular_factura), asi que esto NO crea un
        PagoCobro ni ningun movimiento de caja/banco nuevo. Por eso decrementa
        saldo_pendiente/estado de la CuentaPorCobrar destino a mano en vez de reusar
        PagoService._aplicar_pago_cobro (que exige exactamente un origen caja/cuenta y
        dispara trg_pagos_cobros_io, pensado para dinero que efectivamente se mueve)."""
        require_permiso(session, id_usuario, "notas_credito", "crear")

        monto = Decimal(str(monto))
        if monto <= 0:
            raise ValueError("El monto a aplicar debe ser mayor a cero")

        # WITH (UPDLOCK, ROWLOCK): mismo patron que C1/C18/C22/C24 -- evita que dos
        # aplicaciones concurrentes de la MISMA nota (o contra la MISMA factura destino)
        # pasen ambas la validacion de saldo antes de que ninguna haya comiteado.
        nota = session.execute(
            select(NotaCreditoCliente)
            .where(NotaCreditoCliente.id_nota_credito == id_nota_credito)
            .with_hint(NotaCreditoCliente, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        ).scalar_one_or_none()
        if nota is None:
            raise ValueError("Nota de credito no encontrada")
        if nota.estado != "disponible":
            raise ValueError(
                f"La nota de credito '{nota.numero_nota_credito}' no esta disponible (estado: {nota.estado})"
            )
        if monto > nota.saldo_disponible:
            raise ValueError(f"El monto {monto} excede el saldo disponible {nota.saldo_disponible} de la nota")

        factura_destino = session.get(FacturaVenta, id_factura_destino)
        if factura_destino is None:
            raise ValueError("Factura destino no encontrada")
        if factura_destino.id_cliente_factura != nota.id_cliente:
            raise ValueError("La nota de credito pertenece a otro cliente")
        if factura_destino.estado_factura == "ANULADA":
            raise ValueError("No se puede aplicar una nota de credito a una factura anulada")

        cxc = session.execute(
            select(CuentaPorCobrar)
            .where(CuentaPorCobrar.id_factura == id_factura_destino)
            .with_hint(CuentaPorCobrar, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        ).scalar_one_or_none()
        if cxc is None or cxc.estado not in ("pendiente", "parcial"):
            raise ValueError("La factura destino no tiene saldo pendiente")
        if monto > cxc.saldo_pendiente:
            raise ValueError(f"El monto {monto} excede el saldo pendiente {cxc.saldo_pendiente} de la factura destino")

        nota.saldo_disponible -= monto
        if nota.saldo_disponible == 0:
            nota.estado = "aplicada"

        cxc.saldo_pendiente -= monto
        cxc.estado = "pagada" if cxc.saldo_pendiente == 0 else "parcial"

        session.commit()
        session.refresh(nota)

        logger.info(
            "Nota de credito %s aplicada: monto=%s factura_destino=%s saldo_restante_nota=%s usuario=%s",
            nota.numero_nota_credito,
            monto,
            factura_destino.numero_factura,
            nota.saldo_disponible,
            id_usuario,
        )

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="APLICACION_NOTA_CREDITO_CLIENTE",
            modulo="NOTAS_CREDITO",
            detalle={
                "numero_nota_credito": nota.numero_nota_credito,
                "id_factura_destino": id_factura_destino,
                "numero_factura_destino": factura_destino.numero_factura,
                "monto": str(monto),
                "saldo_restante_nota": str(nota.saldo_disponible),
            },
        )
        return nota

    @staticmethod
    def devolver_nota_credito_cliente(
        session: Session,
        id_nota_credito: int,
        monto,
        metodo_devolucion: str,
        id_autorizador: int | None,
        id_usuario: int | None,
        id_caja: int | None = None,
        id_cuenta_bancaria: int | None = None,
        referencia: str | None = None,
    ) -> NotaCreditoCliente:
        """Devuelve en efectivo/banco (total o parcialmente) el saldo disponible de una
        nota de credito -- a diferencia de aplicar_nota_credito_cliente() (transferencia
        contable interna), esto SI mueve dinero real: un egreso fechado HOY, no
        retroactivo al momento en que se genero la nota (ver docstring de la clase).

        A diferencia del vuelto de una venta (VentaService.emitir_factura), donde el
        efectivo es libre porque forma parte de la MISMA transaccion que ya se esta
        autorizando, una devolucion de nota de credito SIEMPRE exige autorizacion de un
        supervisor sin importar el metodo: es plata saliendo sin ninguna venta en curso
        que la explique, el escenario con mas riesgo de abuso de los dos. Por eso el
        autorizador necesita el permiso 'notas_credito'/'editar' -- distinto de
        'notas_credito'/'crear' (que ya tiene cualquiera que pueda iniciar la devolucion o
        aplicar una nota) -- para que autorizar sea realmente una segunda persona con un
        permiso que el cajero comun no tiene, mismo criterio que 'vueltos_bancarios'/
        'crear' es distinto de 'ventas'/'crear'.

        Reusa CajaService/BancoService._registrar_egreso_vuelto() tal cual (mismo
        movimiento real de caja/banco que el vuelto, solo cambia la descripcion) en vez de
        duplicar esa logica aca."""
        require_permiso(session, id_usuario, "notas_credito", "crear")

        monto = Decimal(str(monto))
        if monto <= 0:
            raise ValueError("El monto a devolver debe ser mayor a cero")
        if metodo_devolucion not in ("efectivo", "pago_movil", "transferencia"):
            raise ValueError("metodo_devolucion debe ser 'efectivo', 'pago_movil' o 'transferencia'")
        if id_autorizador is None:
            raise ValueError("La devolucion de una nota de credito requiere autorizacion de un supervisor")
        require_permiso(session, id_autorizador, "notas_credito", "editar")

        # WITH (UPDLOCK, ROWLOCK): mismo patron que aplicar_nota_credito_cliente() -- evita
        # que dos devoluciones concurrentes de la MISMA nota pasen ambas la validacion de
        # saldo antes de que ninguna haya comiteado.
        nota = session.execute(
            select(NotaCreditoCliente)
            .where(NotaCreditoCliente.id_nota_credito == id_nota_credito)
            .with_hint(NotaCreditoCliente, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        ).scalar_one_or_none()
        if nota is None:
            raise ValueError("Nota de credito no encontrada")
        if nota.estado != "disponible":
            raise ValueError(
                f"La nota de credito '{nota.numero_nota_credito}' no esta disponible (estado: {nota.estado})"
            )
        if monto > nota.saldo_disponible:
            raise ValueError(f"El monto {monto} excede el saldo disponible {nota.saldo_disponible} de la nota")

        fecha = datetime.now()
        descripcion = f"Devolucion nota de credito {nota.numero_nota_credito}"

        if metodo_devolucion == "efectivo":
            if id_caja is None:
                raise ValueError("La devolucion en efectivo requiere indicar la caja de origen")
            caja = session.execute(
                select(Caja)
                .where(Caja.id_caja == id_caja)
                .with_hint(Caja, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
            ).scalar_one_or_none()
            if caja is None:
                raise ValueError("Caja no encontrada")
            if caja.fecha_apertura is None or caja.fecha_cierre is not None:
                raise ValueError(f"La caja '{caja.nombre_caja}' no tiene un turno abierto")
            saldo_actual = CajaService.calcular_saldo_actual(session, id_caja)
            if saldo_actual < monto:
                raise ValueError(
                    f"La caja '{caja.nombre_caja}' no tiene saldo suficiente para la devolucion: "
                    f"disponible ${saldo_actual}, requerido ${monto}"
                )
            CajaService._registrar_egreso_vuelto(
                session, id_caja=id_caja, monto=monto, descripcion=descripcion, id_usuario=id_usuario, fecha=fecha
            )
        else:
            if id_cuenta_bancaria is None:
                raise ValueError("La devolucion por pago movil/transferencia requiere una cuenta bancaria de origen")
            cuenta = session.get(CuentaBancaria, id_cuenta_bancaria)
            if cuenta is None:
                raise ValueError("Cuenta bancaria no encontrada")
            if cuenta.estado_cuenta != "ACTIVO":
                raise ValueError(f"La cuenta bancaria '{cuenta.numero_cuenta}' esta inactiva")
            referencia = (referencia or "").strip()
            if len(referencia) < 4:
                raise ValueError(
                    "La devolucion por pago movil/transferencia requiere una referencia bancaria "
                    "de al menos 4 caracteres"
                )
            if len(referencia) > 50:
                raise ValueError("La referencia bancaria no puede superar 50 caracteres")
            BancoService._registrar_egreso_vuelto(
                session,
                id_cuenta=id_cuenta_bancaria,
                monto=monto,
                descripcion=descripcion,
                referencia=referencia,
                id_usuario=id_usuario,
                fecha=fecha,
            )

        nota.saldo_disponible -= monto
        if nota.saldo_disponible == 0:
            nota.estado = "devuelta"

        session.commit()
        session.refresh(nota)

        logger.info(
            "Nota de credito %s devuelta: monto=%s metodo=%s saldo_restante=%s autorizador=%s usuario=%s",
            nota.numero_nota_credito,
            monto,
            metodo_devolucion,
            nota.saldo_disponible,
            id_autorizador,
            id_usuario,
        )

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="DEVOLUCION_NOTA_CREDITO_CLIENTE",
            modulo="NOTAS_CREDITO",
            detalle={
                "numero_nota_credito": nota.numero_nota_credito,
                "metodo_devolucion": metodo_devolucion,
                "monto": str(monto),
                "saldo_restante_nota": str(nota.saldo_disponible),
                "autorizado_por": id_autorizador,
            },
        )
        return nota

    @staticmethod
    def _crear_nota_credito_proveedor(
        session: Session,
        id_proveedor: int,
        id_compra_origen: int,
        monto,
        motivo: str,
        id_usuario: int | None,
    ) -> NotaCreditoProveedor:
        """Nucleo sin commit propio -- ver _crear_nota_credito_cliente(): mismo motivo,
        usado por CompraService.anular_compra() para la misma atomicidad. No tiene
        numero_nota_credito (ver docstring de la clase), asi que no hereda la carrera de
        correlativo que si tenia el lado cliente."""
        monto = Decimal(str(monto))
        if monto <= 0:
            raise ValueError("monto debe ser mayor a cero")

        nota = NotaCreditoProveedor(
            id_proveedor=id_proveedor,
            id_compra_origen=id_compra_origen,
            monto=monto,
            saldo_disponible=monto,
            motivo=motivo,
            estado="disponible",
            creado_por=id_usuario,
        )
        session.add(nota)
        session.flush()
        return nota

    @staticmethod
    def crear_nota_credito_proveedor(
        session: Session,
        id_proveedor: int,
        id_compra_origen: int,
        monto,
        motivo: str,
        id_usuario: int | None,
    ) -> NotaCreditoProveedor:
        nota = NotaCreditoService._crear_nota_credito_proveedor(
            session,
            id_proveedor=id_proveedor,
            id_compra_origen=id_compra_origen,
            monto=monto,
            motivo=motivo,
            id_usuario=id_usuario,
        )
        session.commit()
        session.refresh(nota)

        logger.info(
            "Nota de credito de proveedor generada: proveedor=%s compra_origen=%s monto=%s usuario=%s",
            id_proveedor,
            id_compra_origen,
            monto,
            id_usuario,
        )

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="NOTA_CREDITO_PROVEEDOR",
            modulo="NOTAS_CREDITO",
            detalle={"id_proveedor": id_proveedor, "id_compra_origen": id_compra_origen, "monto": str(monto)},
        )
        return nota

    @staticmethod
    def listar_notas_credito_cliente(
        session: Session, id_cliente: int, id_usuario: int | None = None
    ) -> list[NotaCreditoCliente]:
        require_permiso(session, id_usuario, "notas_credito", "ver")
        return (
            session.query(NotaCreditoCliente)
            .filter(NotaCreditoCliente.id_cliente == id_cliente)
            .order_by(NotaCreditoCliente.fecha_creacion.desc())
            .all()
        )

    @staticmethod
    def listar_notas_credito_clientes(
        session: Session,
        fecha_desde: date | datetime | None = None,
        fecha_hasta: date | datetime | None = None,
        id_cliente: int | None = None,
        estado: str | None = None,
        pagina: int = 1,
        por_pagina: int = 20,
        id_usuario: int | None = None,
    ) -> dict:
        """Reporte paginado con filtros -- pensado para armar lo que pida el SENIAT
        (rango de fechas, o todas las de un cliente) sin tener que consultar la tabla
        directamente. Ver listar_notas_credito_cliente() para el caso simple de listar
        las notas disponibles de un cliente puntual."""
        require_permiso(session, id_usuario, "notas_credito", "ver")
        query = session.query(NotaCreditoCliente)
        if fecha_desde:
            query = query.filter(NotaCreditoCliente.fecha_creacion >= fecha_desde)
        if fecha_hasta:
            query = query.filter(NotaCreditoCliente.fecha_creacion <= fecha_hasta)
        if id_cliente:
            query = query.filter(NotaCreditoCliente.id_cliente == id_cliente)
        if estado:
            query = query.filter(NotaCreditoCliente.estado == estado)

        total = query.count()
        notas = (
            query.order_by(NotaCreditoCliente.numero_nota_credito.desc())
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
            .all()
        )
        return {"items": notas, "total": total, "pagina": pagina, "por_pagina": por_pagina}

    @staticmethod
    def listar_notas_credito_proveedor(
        session: Session, id_proveedor: int, id_usuario: int | None = None
    ) -> list[NotaCreditoProveedor]:
        require_permiso(session, id_usuario, "notas_credito", "ver")
        return (
            session.query(NotaCreditoProveedor)
            .filter(NotaCreditoProveedor.id_proveedor == id_proveedor)
            .order_by(NotaCreditoProveedor.fecha_creacion.desc())
            .all()
        )
