"""R-01 (docs/CHECKLIST_PRODUCCION.md): motor de reportes. Empieza por los dos de mayor
valor de negocio y que tocan caja/cobranza real: antiguedad de saldos de CxC (aging) y
arqueo de caja. RBAC via el recurso 'reportes' (migrations/0016).

Aging CxP es el espejo exacto de aging CxC (mismos estados abiertos, mismos rangos de
antiguedad) del lado de lo que la empresa debe pagar en vez de lo que le deben.

libro_ventas() es la base del Libro de Ventas exigido por el SENIAT para el IVA: base
imponible = total_venta - monto_descuento, IVA = monto_iva (ambos ya snapshoteados en la
factura al emitirse, ver FacturaVenta.monto_iva). Las notas de credito del periodo se
listan aparte con su monto plano -- notas_credito_clientes no guarda el desglose
base/IVA de la nota, asi que no se resta del total de IVA del periodo (haria falta
decidir con contaduria como prorratear eso antes de restarlo).

R-06: el filtro "un VENDEDOR solo ve sus propias facturas" queda pendiente para cuando
el reporte de ventas lo necesite -- ninguno de los reportes de aca abajo esta ligado a un
vendedor especifico.

Modulo de Compras (compras_por_*, ordenes_compra_abiertas, cumplimiento_proveedores,
devoluciones_proveedor, notas_credito_proveedor): espejo del modulo de Ventas del lado de
lo que la empresa le compra a sus proveedores, siguiendo el flujo OC -> NotaRecepcion ->
Compra -> NotaDevolucion/NotaCreditoProveedor (ver CompraOC/NotaRecepcion/NotaDevolucion
en models.py). Compra no tiene desglose de IVA propio (a diferencia de FacturaVenta) --
Libro de Compras y Retenciones de IVA quedan pendientes de una migracion que le agregue
esas columnas.
"""

import json
import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import Date, case, cast, exists, func, literal, literal_column, or_
from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    Auditoria,
    BancoMovimiento,
    Caja,
    CajaMovimiento,
    Categoria,  # noqa: F401 - usado en joinedload(Inventario.categoria)
    Cliente,
    ComisionFactura,
    Compra,
    CompraDetalle,
    CompraOC,
    ControlDeTasa,
    CuentaBancaria,
    CuentaPorCobrar,
    CuentaPorCobrarBCV,
    CuentaPorCobrarOtro,
    CuentaPorPagar,
    CuentaPorPagarOtro,
    FacturaDetalle,
    FacturaVenta,
    Inventario,
    NotaCreditoCliente,
    NotaCreditoProveedor,
    NotaDevolucion,
    NotaRecepcion,
    NotaRecepcionDetalle,
    PagoCobro,
    PagoCobroBCV,
    PagoProveedor,
    Proveedor,
    Ruta,
    Vendedor,
)
from app.services.otros_movimientos import ESTADOS_CXC_OTRO
from app.services.paginacion import paginar
from app.services.permisos import require_permiso
from app.services.tesoreria import TIPOS_MOVIMIENTO_CAJA
from app.utils.decimal_utils import to_decimal

logger = logging.getLogger(__name__)


def _pagina_o_todo(query, pagina, por_pagina, *orden):
    """(filas de la consulta, `paginacion`): con `pagina=None` todas las filas (la exportacion) y `paginacion=None`; con
    `pagina`, solo esa pagina y su diccionario de paginacion (ver `paginar`). `orden` termina en la clave primaria."""
    if pagina is None:
        return query.order_by(*orden).all(), None
    resultado = paginar(query, pagina, por_pagina, *orden)
    return resultado["items"], {k: v for k, v in resultado.items() if k != "items"}


# Filas por pagina de un reporte de listado en pantalla (la exportacion pide todas, con `pagina=None`).
POR_PAGINA_REPORTE = 100

# Tamano maximo de un IN (...): SQL Server rechaza consultas con mas de ~2100 parametros.
_TAMANO_LOTE_IN = 1000

ESTADOS_CXC_ABIERTOS = ("pendiente", "parcial", "vencida")
ESTADOS_CXP_ABIERTOS = ("pendiente", "parcial", "vencida")
ESTADOS_OC_ABIERTAS = ("PENDIENTE", "PARCIAL")
ESTADOS_CXC_BCV_ABIERTOS = ("pendiente", "parcial", "vencida")
# Espejo de ESTADOS_CXC_OTRO (app/services/otros_movimientos.py) del lado de
# cuentas_por_pagar_otros -- ahi no existe como constante nombrada, solo un tuple inline
# en OtrosMovimientosService.listar_partidas_no_conciliadas().
ESTADOS_CXP_OTRO = ("pendiente", "parcial", "conciliado")

# R-07: lista blanca explicita de columnas ordenables -- nunca
# getattr(Modelo, campo_del_usuario) con un valor que venga de la UI/API. Si se agrega un
# criterio de orden nuevo, agregarlo aca primero.
_ORDEN_AGING_CXC = {
    "fecha_vencimiento": CuentaPorCobrar.fecha_vencimiento,
    "saldo_pendiente": CuentaPorCobrar.saldo_pendiente,
}
_ORDEN_AGING_CXP = {
    "fecha_vencimiento": CuentaPorPagar.fecha_vencimiento,
    "saldo_pendiente": CuentaPorPagar.saldo_pendiente,
}
_ORDEN_AGING_CXC_BCV = {
    "fecha_vencimiento": CuentaPorCobrarBCV.fecha_vencimiento,
    "saldo_pendiente": CuentaPorCobrarBCV.saldo_pendiente,
}


# Total de una factura: subtotal - descuento + IVA. Expresion SQL para sumar en la base de datos.
_TOTAL_FACTURA_SQL = FacturaVenta.total_venta - FacturaVenta.monto_descuento + FacturaVenta.monto_iva


def _periodo_sql(columna, agrupacion: str):
    """Expresion SQL que agrupa una fecha por dia (date) o por mes (primer dia del mes)."""
    if agrupacion == "dia":
        return cast(columna, Date)
    return func.datefromparts(func.year(columna), func.month(columna), literal_column("1"))


def _bucket_aging(dias_vencido: int) -> str:
    if dias_vencido <= 0:
        return "vigente"
    if dias_vencido <= 30:
        return "1-30"
    if dias_vencido <= 60:
        return "31-60"
    if dias_vencido <= 90:
        return "61-90"
    return "90+"


def _aplicaciones_nc_cliente(
    session: Session, desde: datetime | None = None, hasta: datetime | None = None
) -> list[dict]:
    """Aplicaciones de notas de credito de cliente a facturas (NotaCreditoService.aplicar_nota_credito_cliente).
    No hay una tabla propia: esa operacion solo baja el saldo de la cuenta por cobrar y deja constancia en
    Auditoria (accion APLICACION_NOTA_CREDITO_CLIENTE, con factura destino y monto), asi que de ahi se leen."""
    query = session.query(Auditoria).filter(
        Auditoria.accion == "APLICACION_NOTA_CREDITO_CLIENTE", Auditoria.modulo == "NOTAS_CREDITO"
    )
    if desde is not None:
        query = query.filter(Auditoria.fecha_evento >= desde)
    if hasta is not None:
        query = query.filter(Auditoria.fecha_evento <= hasta)
    aplicaciones = []
    for evento in query.order_by(Auditoria.fecha_evento).all():
        try:
            detalle = json.loads(evento.detalle) if evento.detalle else {}
            aplicaciones.append(
                {
                    "fecha": evento.fecha_evento,
                    "numero_nota_credito": detalle.get("numero_nota_credito"),
                    "id_factura": int(detalle["id_factura_destino"]),
                    "monto": Decimal(str(detalle["monto"])),
                }
            )
        except (TypeError, ValueError, KeyError, ArithmeticError):
            continue
    return aplicaciones


def _cuentas_al_corte(
    session: Session,
    query,
    modelo,
    pago_modelo,
    pago_fk,
    fecha_emision,
    estados_abiertos: tuple,
    fecha_corte: date,
    orden,
    nc_por_factura: dict[int, Decimal] | None = None,
) -> list[tuple]:
    """Pares (cuenta, saldo) con saldo > 0 a `fecha_corte`.

    Corte de hoy o futuro: las cuentas abiertas con su saldo actual. Corte pasado: el saldo actual es el de
    hoy, no el de entonces, asi que se reconstruye -- solo facturas/compras emitidas hasta el corte, y a cada
    saldo se le suman los pagos (y notas de credito aplicadas, `nc_por_factura`) posteriores al corte. Las
    cuentas hoy pagadas que a esa fecha estaban abiertas entran por eso mismo."""
    if fecha_corte >= date.today():
        cuentas = query.filter(modelo.estado.in_(estados_abiertos)).order_by(orden).all()
        return [(c, c.saldo_pendiente) for c in cuentas if c.saldo_pendiente > 0]

    fin_corte = datetime.combine(fecha_corte, time.max)
    cuentas = query.filter(modelo.estado != "anulada").filter(fecha_emision <= fin_corte).order_by(orden).all()
    posteriores = dict(
        session.query(pago_fk, func.sum(pago_modelo.monto))
        .filter(pago_modelo.fecha_pago > fin_corte)
        .group_by(pago_fk)
        .all()
    )
    pares = []
    for cuenta in cuentas:
        saldo = cuenta.saldo_pendiente + to_decimal(posteriores.get(_pk_cuenta(cuenta), 0))
        if nc_por_factura:
            saldo += nc_por_factura.get(getattr(cuenta, "id_factura", None), Decimal("0.00"))
        if saldo > 0:
            pares.append((cuenta, saldo))
    return pares


def _nc_aplicadas_despues_del_corte(session: Session, fecha_corte: date) -> dict[int, Decimal] | None:
    """Total de notas de credito aplicadas por factura DESPUES de `fecha_corte` (None si el corte es de hoy o
    futuro: no hay nada que reconstruir)."""
    if fecha_corte >= date.today():
        return None
    por_factura: dict[int, Decimal] = {}
    for aplicacion in _aplicaciones_nc_cliente(session, desde=datetime.combine(fecha_corte, time.max)):
        id_factura = aplicacion["id_factura"]
        por_factura[id_factura] = por_factura.get(id_factura, Decimal("0.00")) + aplicacion["monto"]
    return por_factura


def _pk_cuenta(cuenta) -> int:
    return getattr(cuenta, "id_cuenta_por_cobrar", None) or cuenta.id_cuenta


class ReporteService:
    @staticmethod
    def aging_cuentas_por_cobrar(
        session: Session,
        id_usuario: int | None,
        fecha_corte: date | None = None,
        id_cliente: int | None = None,
        id_vendedor: int | None = None,
        orden: str = "fecha_vencimiento",
    ) -> dict:
        """Antiguedad de saldos de cuentas por cobrar abiertas (pendiente/parcial/vencida),
        agrupadas en los rangos estandar de cobranza (vigente, 1-30, 31-60, 61-90, 90+)
        segun dias transcurridos desde fecha_vencimiento hasta fecha_corte."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if orden not in _ORDEN_AGING_CXC:
            raise ValueError(f"orden invalido: {orden!r}, debe ser uno de {sorted(_ORDEN_AGING_CXC)}")
        fecha_corte = fecha_corte or date.today()

        query = (
            session.query(CuentaPorCobrar)
            .join(FacturaVenta, FacturaVenta.id_factura == CuentaPorCobrar.id_factura)
            .join(Cliente, Cliente.id_cliente == FacturaVenta.id_cliente_factura)
            .options(joinedload(CuentaPorCobrar.factura).joinedload(FacturaVenta.cliente))
        )
        if id_cliente:
            query = query.filter(FacturaVenta.id_cliente_factura == id_cliente)
        if id_vendedor:
            query = query.filter(Cliente.vendedor_cliente == id_vendedor)
        cuentas = _cuentas_al_corte(
            session,
            query,
            CuentaPorCobrar,
            PagoCobro,
            PagoCobro.id_cuenta_por_cobrar,
            FacturaVenta.fecha_emision,
            ESTADOS_CXC_ABIERTOS,
            fecha_corte,
            _ORDEN_AGING_CXC[orden],
            nc_por_factura=_nc_aplicadas_despues_del_corte(session, fecha_corte),
        )

        filas = []
        totales_por_bucket: dict[str, Decimal] = {}
        for cuenta, saldo in cuentas:
            dias_vencido = (fecha_corte - cuenta.fecha_vencimiento).days if cuenta.fecha_vencimiento else 0
            dias_transcurridos = (
                (fecha_corte - cuenta.factura.fecha_emision.date()).days if cuenta.factura.fecha_emision else 0
            )
            bucket = _bucket_aging(dias_vencido)
            totales_por_bucket[bucket] = totales_por_bucket.get(bucket, Decimal("0.00")) + saldo
            filas.append(
                {
                    "id_cuenta_por_cobrar": cuenta.id_cuenta_por_cobrar,
                    "numero_factura": cuenta.factura.numero_factura,
                    "cliente": (cuenta.factura.cliente.nombre_razon_social if cuenta.factura.cliente else None),
                    "fecha_vencimiento": cuenta.fecha_vencimiento,
                    "saldo_pendiente": saldo,
                    "dias_vencido": dias_vencido,
                    "dias_transcurridos": dias_transcurridos,
                    "bucket": bucket,
                }
            )

        return {
            "fecha_corte": fecha_corte,
            "filas": filas,
            "total_general": sum((f["saldo_pendiente"] for f in filas), Decimal("0.00")),
            "totales_por_bucket": totales_por_bucket,
        }

    @staticmethod
    def aging_cuentas_por_cobrar_bcv(
        session: Session,
        id_usuario: int | None,
        fecha_corte: date | None = None,
        id_cliente: int | None = None,
        id_vendedor: int | None = None,
        orden: str = "fecha_vencimiento",
    ) -> dict:
        """Antiguedad de saldos de cuentas por cobrar BCV abiertas (pendiente/parcial/vencida),
        agrupadas en los rangos estandar de cobranza (vigente, 1-30, 31-60, 61-90, 90+)
        segun dias transcurridos desde fecha_vencimiento hasta fecha_corte."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if orden not in _ORDEN_AGING_CXC_BCV:
            raise ValueError(f"orden invalido: {orden!r}, debe ser uno de {sorted(_ORDEN_AGING_CXC_BCV)}")
        fecha_corte = fecha_corte or date.today()

        query = (
            session.query(CuentaPorCobrarBCV)
            .join(FacturaVenta, FacturaVenta.id_factura == CuentaPorCobrarBCV.id_factura)
            .join(Cliente, Cliente.id_cliente == FacturaVenta.id_cliente_factura)
            .options(joinedload(CuentaPorCobrarBCV.factura).joinedload(FacturaVenta.cliente))
        )
        if id_cliente:
            query = query.filter(FacturaVenta.id_cliente_factura == id_cliente)
        if id_vendedor:
            query = query.filter(Cliente.vendedor_cliente == id_vendedor)
        cuentas = _cuentas_al_corte(
            session,
            query,
            CuentaPorCobrarBCV,
            PagoCobroBCV,
            PagoCobroBCV.id_cuenta_por_cobrar,
            FacturaVenta.fecha_emision,
            ESTADOS_CXC_BCV_ABIERTOS,
            fecha_corte,
            _ORDEN_AGING_CXC_BCV[orden],
        )

        filas = []
        totales_por_bucket: dict[str, Decimal] = {}
        for cuenta, saldo in cuentas:
            dias_vencido = (fecha_corte - cuenta.fecha_vencimiento).days if cuenta.fecha_vencimiento else 0
            dias_transcurridos = (fecha_corte - cuenta.fecha_emision).days if cuenta.fecha_emision else 0
            bucket = _bucket_aging(dias_vencido)
            totales_por_bucket[bucket] = totales_por_bucket.get(bucket, Decimal("0.00")) + saldo
            filas.append(
                {
                    "id_cuenta_por_cobrar": cuenta.id_cuenta_por_cobrar,
                    "numero_factura": cuenta.factura.numero_factura,
                    "cliente": (cuenta.factura.cliente.nombre_razon_social if cuenta.factura.cliente else None),
                    "fecha_vencimiento": cuenta.fecha_vencimiento,
                    "saldo_pendiente": saldo,
                    "porcentaje_bcv": cuenta.porcentaje,
                    "dias_vencido": dias_vencido,
                    "dias_transcurridos": dias_transcurridos,
                    "bucket": bucket,
                }
            )

        return {
            "fecha_corte": fecha_corte,
            "filas": filas,
            "total_general": sum((f["saldo_pendiente"] for f in filas), Decimal("0.00")),
            "totales_por_bucket": totales_por_bucket,
        }

    @staticmethod
    def aging_cuentas_por_pagar(
        session: Session,
        id_usuario: int | None,
        fecha_corte: date | None = None,
        id_proveedor: int | None = None,
        orden: str = "fecha_vencimiento",
    ) -> dict:
        """Antiguedad de saldos de cuentas por pagar abiertas (pendiente/parcial/vencida),
        mismo criterio que aging_cuentas_por_cobrar pero del lado de lo que la empresa le
        debe a sus proveedores."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if orden not in _ORDEN_AGING_CXP:
            raise ValueError(f"orden invalido: {orden!r}, debe ser uno de {sorted(_ORDEN_AGING_CXP)}")
        fecha_corte = fecha_corte or date.today()

        query = (
            session.query(CuentaPorPagar)
            .join(Compra, Compra.id_compra == CuentaPorPagar.id_compra)
            .options(joinedload(CuentaPorPagar.compra).joinedload(Compra.proveedor))
        )
        if id_proveedor:
            query = query.filter(Compra.id_proveedor == id_proveedor)
        cuentas = _cuentas_al_corte(
            session,
            query,
            CuentaPorPagar,
            PagoProveedor,
            PagoProveedor.id_cuenta_por_pagar,
            Compra.fecha_emision,
            ESTADOS_CXP_ABIERTOS,
            fecha_corte,
            _ORDEN_AGING_CXP[orden],
        )

        filas = []
        totales_por_bucket: dict[str, Decimal] = {}
        for cuenta, saldo in cuentas:
            dias_vencido = (fecha_corte - cuenta.fecha_vencimiento).days if cuenta.fecha_vencimiento else 0
            bucket = _bucket_aging(dias_vencido)
            totales_por_bucket[bucket] = totales_por_bucket.get(bucket, Decimal("0.00")) + saldo
            filas.append(
                {
                    "id_cuenta": cuenta.id_cuenta,
                    "numero_compra": cuenta.compra.numero_compra,
                    "proveedor": (cuenta.compra.proveedor.nombre_razon_social if cuenta.compra.proveedor else None),
                    "fecha_vencimiento": cuenta.fecha_vencimiento,
                    "saldo_pendiente": saldo,
                    "dias_vencido": dias_vencido,
                    "bucket": bucket,
                }
            )

        return {
            "fecha_corte": fecha_corte,
            "filas": filas,
            "total_general": sum((f["saldo_pendiente"] for f in filas), Decimal("0.00")),
            "totales_por_bucket": totales_por_bucket,
        }

    @staticmethod
    def libro_ventas(
        session: Session,
        id_usuario: int | None,
        fecha_desde: date,
        fecha_hasta: date,
        id_cliente: int | None = None,
        pagina: int | None = None,
        por_pagina: int = POR_PAGINA_REPORTE,
    ) -> dict:
        """Libro de Ventas para el IVA (base del formato exigido por el SENIAT): detalle
        de facturas emitidas en el rango, con base imponible, monto exento y monto de IVA
        desglosados por factura, y su equivalente en Bs a la tasa BCV de la factura. Las
        facturas ANULADA se listan (el SENIAT exige conservar el correlativo) con montos en
        cero y no entran en los totales. Las notas de credito emitidas en el mismo rango se
        listan aparte: no se restan del IVA porque las unicas que existen nacen de anular una
        factura (que ya cuenta en cero) o de un sobreabono (que no es una venta).

        Con `pagina=None` devuelve TODAS las filas (es lo que usa la exportacion). Con `pagina` devuelve solo esa
        pagina de `por_pagina` filas (es lo que muestra la pantalla; ver `paginacion` en el resultado). Los totales
        son siempre los de todo el filtro: se suman en la base y no dependen de la pagina."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        filtros = [FacturaVenta.fecha_emision >= desde_dt, FacturaVenta.fecha_emision <= hasta_dt]
        if id_cliente:
            filtros.append(FacturaVenta.id_cliente_factura == id_cliente)
        query = (
            session.query(FacturaVenta)
            .options(joinedload(FacturaVenta.cliente), joinedload(FacturaVenta.tasa))
            .filter(*filtros)
        )
        orden = (FacturaVenta.fecha_emision, FacturaVenta.numero_control, FacturaVenta.id_factura)
        paginacion = None
        if pagina is None:
            facturas = query.order_by(*orden).all()
        else:
            resultado_pagina = paginar(query, pagina, por_pagina, *orden)
            facturas = resultado_pagina["items"]
            paginacion = {k: v for k, v in resultado_pagina.items() if k != "items"}

        centavo = Decimal("0.01")
        filas = []
        for factura in facturas:
            anulada = factura.estado_factura == "ANULADA"
            if anulada:
                base_total = monto_iva = Decimal("0.00")
            else:
                base_total = factura.total_venta - factura.monto_descuento
                monto_iva = factura.monto_iva
            base_imponible = base_total if factura.iva_aplicado else Decimal("0.00")
            monto_exento = Decimal("0.00") if factura.iva_aplicado else base_total
            total = base_total + monto_iva
            tasa = factura.tasa.tasa_dolar_bcv if factura.tasa else None
            total_en_bs = (total * to_decimal(tasa)).quantize(centavo) if tasa else None
            filas.append(
                {
                    "fecha_emision": factura.fecha_emision,
                    "numero_control": factura.numero_control,
                    "numero_factura": factura.numero_factura,
                    "estado": "ANULADA" if anulada else "EMITIDA",
                    "cliente": (factura.cliente.nombre_razon_social if factura.cliente else None),
                    "identificacion_cliente": (factura.cliente.identificacion_cliente if factura.cliente else None),
                    "monto_exento": monto_exento,
                    "base_imponible": base_imponible,
                    "porcentaje_iva": factura.porcentaje_iva_aplicado,
                    "monto_iva": monto_iva,
                    "total": total,
                    "tasa_cambio": tasa,
                    "total_bs": total_en_bs,
                }
            )

        totales = ReporteService._totales_libro_ventas(session, filtros)

        nc_query = (
            session.query(NotaCreditoCliente)
            .options(joinedload(NotaCreditoCliente.cliente))
            .filter(NotaCreditoCliente.fecha_creacion >= desde_dt)
            .filter(NotaCreditoCliente.fecha_creacion <= hasta_dt)
        )
        if id_cliente:
            nc_query = nc_query.filter(NotaCreditoCliente.id_cliente == id_cliente)
        notas_credito = nc_query.order_by(NotaCreditoCliente.fecha_creacion).all()

        filas_nc = [
            {
                "fecha_creacion": nc.fecha_creacion,
                "numero_nota_credito": nc.numero_nota_credito,
                "cliente": nc.cliente.nombre_razon_social if nc.cliente else None,
                "identificacion_cliente": (nc.cliente.identificacion_cliente if nc.cliente else None),
                "monto": nc.monto,
                "motivo": nc.motivo,
            }
            for nc in notas_credito
        ]

        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "paginacion": paginacion,
            "cantidad_facturas": totales["vigentes"],
            "cantidad_anuladas": totales["anuladas"],
            "total_base_imponible": totales["base_imponible"],
            "total_exento": totales["exento"],
            "total_iva": totales["iva"],
            "total_general": totales["base_imponible"] + totales["exento"] + totales["iva"],
            "total_bs": totales["total_bs"],
            "notas_credito": filas_nc,
            "total_notas_credito": sum((nc["monto"] for nc in filas_nc), Decimal("0.00")),
        }

    @staticmethod
    def _totales_libro_ventas(session: Session, filtros: list) -> dict:
        """Cantidades y totales del Libro de Ventas de TODO el filtro, sumados en la base (las ANULADA no suman).
        El total en Bs es la suma del total de cada factura por su tasa, redondeado factura a factura: se agrupa por
        (total, tasa) y se multiplica por la cantidad de facturas iguales, que da exactamente lo mismo sin traer
        una fila por factura."""
        vigente = FacturaVenta.estado_factura != "ANULADA"
        base_total = FacturaVenta.total_venta - FacturaVenta.monto_descuento

        def suma(condicion, columna):
            return func.coalesce(func.sum(case((condicion, columna), else_=0)), 0)

        vigentes, anuladas, base_imponible, exento, iva = (
            session.query(
                suma(vigente, 1),
                suma(~vigente, 1),
                suma(vigente & (FacturaVenta.iva_aplicado == 1), base_total),
                suma(vigente & (FacturaVenta.iva_aplicado == 0), base_total),
                suma(vigente, FacturaVenta.monto_iva),
            )
            .filter(*filtros)
            .one()
        )

        total_factura = base_total + FacturaVenta.monto_iva
        por_total_y_tasa = (
            session.query(total_factura, ControlDeTasa.tasa_dolar_bcv, func.count(FacturaVenta.id_factura))
            .outerjoin(ControlDeTasa, FacturaVenta.id_tasa_factura == ControlDeTasa.id_tasa)
            .filter(*filtros, vigente)
            .group_by(total_factura, ControlDeTasa.tasa_dolar_bcv)
            .all()
        )
        centavo = Decimal("0.01")
        total_bs = Decimal("0.00")
        for total, tasa, cantidad in por_total_y_tasa:
            if tasa:
                total_bs += (to_decimal(total) * to_decimal(tasa)).quantize(centavo) * cantidad
        return {
            "vigentes": int(vigentes),
            "anuladas": int(anuladas),
            "base_imponible": to_decimal(base_imponible),
            "exento": to_decimal(exento),
            "iva": to_decimal(iva),
            "total_bs": total_bs,
        }

    @staticmethod
    def ventas_por_periodo(
        session: Session,
        id_usuario: int | None,
        fecha_desde: date,
        fecha_hasta: date,
        agrupacion: str = "dia",
    ) -> dict:
        """Total facturado (base - descuento + IVA) y cantidad de facturas por dia o por
        mes, excluyendo ANULADA. Agregado en Python (no SQL) sobre un rango acotado, mismo
        criterio que el resto de los reportes de este modulo."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if agrupacion not in ("dia", "mes"):
            raise ValueError("agrupacion invalida, debe ser 'dia' o 'mes'")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        # Se agrupa y suma en la base de datos (una fila por dia o mes), no en Python sobre cada factura.
        clave_sql = _periodo_sql(FacturaVenta.fecha_emision, agrupacion)
        agrupado = (
            session.query(clave_sql, func.count(FacturaVenta.id_factura), func.sum(_TOTAL_FACTURA_SQL))
            .filter(FacturaVenta.estado_factura != "ANULADA")
            .filter(FacturaVenta.fecha_emision >= desde_dt)
            .filter(FacturaVenta.fecha_emision <= hasta_dt)
            .group_by(clave_sql)
            .order_by(clave_sql)
            .all()
        )
        filas = [
            {"fecha": clave, "cantidad_facturas": cantidad, "total": to_decimal(total)}
            for clave, cantidad, total in agrupado
        ]
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "agrupacion": agrupacion,
            "filas": filas,
            "total_general": sum((f["total"] for f in filas), Decimal("0.00")),
            "total_facturas": sum(f["cantidad_facturas"] for f in filas),
        }

    @staticmethod
    def ventas_por_cliente(session: Session, id_usuario: int | None, fecha_desde: date, fecha_hasta: date) -> dict:
        """Ranking de clientes por monto facturado (base - descuento + IVA) en el rango,
        excluyendo ANULADA."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        # Se agrupa y suma en la base de datos (una fila por cliente), no en Python sobre cada factura.
        total_sql = func.sum(_TOTAL_FACTURA_SQL)
        agrupado = (
            session.query(
                Cliente.id_cliente, Cliente.nombre_razon_social, func.count(FacturaVenta.id_factura), total_sql
            )
            .select_from(FacturaVenta)
            .outerjoin(Cliente, Cliente.id_cliente == FacturaVenta.id_cliente_factura)
            .filter(FacturaVenta.estado_factura != "ANULADA")
            .filter(FacturaVenta.fecha_emision >= desde_dt)
            .filter(FacturaVenta.fecha_emision <= hasta_dt)
            .group_by(Cliente.id_cliente, Cliente.nombre_razon_social)
            .order_by(total_sql.desc(), Cliente.id_cliente)
            .all()
        )
        filas = [
            {"cliente": nombre, "cantidad_facturas": cantidad, "total": to_decimal(total)}
            for _id, nombre, cantidad, total in agrupado
        ]
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "total_general": sum((f["total"] for f in filas), Decimal("0.00")),
        }

    @staticmethod
    def ventas_por_vendedor(session: Session, id_usuario: int | None, fecha_desde: date, fecha_hasta: date) -> dict:
        """Ranking de vendedores por monto facturado (base - descuento + IVA) en el
        rango, excluyendo ANULADA."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        # Se agrupa y suma en la base de datos (una fila por vendedor), no en Python sobre cada factura.
        total_sql = func.sum(_TOTAL_FACTURA_SQL)
        agrupado = (
            session.query(
                Vendedor.id_vendedor, Vendedor.nombre_vendedor, func.count(FacturaVenta.id_factura), total_sql
            )
            .select_from(FacturaVenta)
            .outerjoin(Vendedor, Vendedor.id_vendedor == FacturaVenta.id_vendedor)
            .filter(FacturaVenta.estado_factura != "ANULADA")
            .filter(FacturaVenta.fecha_emision >= desde_dt)
            .filter(FacturaVenta.fecha_emision <= hasta_dt)
            .group_by(Vendedor.id_vendedor, Vendedor.nombre_vendedor)
            .order_by(total_sql.desc(), Vendedor.id_vendedor)
            .all()
        )
        filas = []
        for _id, nombre, cantidad, total in agrupado:
            total = to_decimal(total)
            filas.append(
                {
                    "vendedor": nombre,
                    "cantidad_facturas": cantidad,
                    "total": total,
                    "ticket_promedio": total / to_decimal(cantidad),
                }
            )
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "total_general": sum((f["total"] for f in filas), Decimal("0.00")),
        }

    @staticmethod
    def ventas_por_ruta(session: Session, id_usuario: int | None, fecha_desde: date, fecha_hasta: date) -> dict:
        """Mismo reporte que `ventas_por_vendedor`, agrupado por `Vendedor.id_ruta` en vez
        de por vendedor -- cubre "Dolares totales facturados por ruta" y "ticket promedio
        por ruta" (el 'drop site' pedido por el cliente, 2026-09-02: total facturado en $
        entre cantidad de facturas) en un solo reporte, mismo criterio de agrupacion.
        Una factura cuyo vendedor no tiene ruta asignada (o sin vendedor, caso legacy) cae
        en el grupo 'Sin ruta' en vez de perderse del reporte."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        # Se agrupa y suma en la base de datos (una fila por ruta), no en Python sobre cada factura.
        total_sql = func.sum(_TOTAL_FACTURA_SQL)
        agrupado = (
            session.query(Ruta.id_ruta, Ruta.nombre_ruta, func.count(FacturaVenta.id_factura), total_sql)
            .select_from(FacturaVenta)
            .outerjoin(Vendedor, Vendedor.id_vendedor == FacturaVenta.id_vendedor)
            .outerjoin(Ruta, Ruta.id_ruta == Vendedor.id_ruta)
            .filter(FacturaVenta.estado_factura != "ANULADA")
            .filter(FacturaVenta.fecha_emision >= desde_dt)
            .filter(FacturaVenta.fecha_emision <= hasta_dt)
            .group_by(Ruta.id_ruta, Ruta.nombre_ruta)
            .order_by(total_sql.desc(), Ruta.id_ruta)
            .all()
        )
        filas = []
        for id_ruta, nombre, cantidad, total in agrupado:
            total = to_decimal(total)
            filas.append(
                {
                    "ruta": nombre if id_ruta is not None else "Sin ruta",
                    "cantidad_facturas": cantidad,
                    "total": total,
                    "ticket_promedio": total / to_decimal(cantidad),
                }
            )
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "total_general": sum((f["total"] for f in filas), Decimal("0.00")),
        }

    @staticmethod
    def ventas_productos_clientes(
        session: Session,
        id_usuario: int | None,
        fecha_desde: date,
        fecha_hasta: date,
        id_vendedor: int | None = None,
        id_producto: int | None = None,
    ) -> dict:
        """Reporte de ventas de productos a clientes: muestra por cada producto a qué
        clientes fue vendido, con cantidad y monto total. Permite filtrar por vendedor
        para ver solo las ventas realizadas por un vendedor específico, y por producto
        para ver solo las ventas de un producto específico."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        # Se suma en la base de datos (una fila por producto y cliente), no en Python sobre todas las lineas del
        # periodo. Bultos y unidades van aparte (medidas distintas); lineas sin tipo_venta = unidades.
        es_bulto = FacturaDetalle.tipo_venta == "bulto"
        monto_sql = func.sum(FacturaDetalle.cantidad_producto * FacturaDetalle.precio_unitario)
        query = (
            session.query(
                Inventario.id_producto,
                Inventario.nombre_producto,
                Inventario.cod_producto,
                Cliente.id_cliente,
                Cliente.nombre_razon_social,
                Cliente.identificacion_cliente,
                func.sum(case((es_bulto, FacturaDetalle.cantidad_producto), else_=0)),
                func.sum(case((es_bulto, 0), else_=FacturaDetalle.cantidad_producto)),
                monto_sql,
            )
            .select_from(FacturaDetalle)
            .join(FacturaVenta, FacturaDetalle.id_factura == FacturaVenta.id_factura)
            .join(Inventario, Inventario.id_producto == FacturaDetalle.id_producto_factura)
            .join(Cliente, Cliente.id_cliente == FacturaVenta.id_cliente_factura)
            .filter(FacturaVenta.estado_factura != "ANULADA")
            .filter(FacturaVenta.fecha_emision >= desde_dt)
            .filter(FacturaVenta.fecha_emision <= hasta_dt)
        )
        if id_vendedor:
            query = query.filter(FacturaVenta.id_vendedor == id_vendedor)
        if id_producto:
            query = query.filter(FacturaDetalle.id_producto_factura == id_producto)

        agrupado = query.group_by(
            Inventario.id_producto,
            Inventario.nombre_producto,
            Inventario.cod_producto,
            Cliente.id_cliente,
            Cliente.nombre_razon_social,
            Cliente.identificacion_cliente,
        ).order_by(monto_sql.desc(), Cliente.id_cliente)

        # Agrupar por producto, luego por cliente
        grupos: dict[int, dict] = {}
        for id_prod, nombre, codigo, id_cli, cliente, identificacion, bultos, unidades, monto in agrupado.all():
            grupo_producto = grupos.setdefault(id_prod, {"producto": nombre, "cod_producto": codigo, "clientes": {}})
            grupo_producto["clientes"][id_cli] = {
                "cliente": cliente,
                "identificacion_cliente": identificacion,
                "bultos": to_decimal(bultos),
                "unidades": to_decimal(unidades),
                "monto_total": to_decimal(monto),
            }

        # Convertir a lista de filas (producto + lista de clientes)
        filas = []
        for _id_producto, grupo in grupos.items():
            clientes_lista = sorted(grupo["clientes"].values(), key=lambda c: c["monto_total"], reverse=True)
            total_producto = sum(c["monto_total"] for c in clientes_lista)
            filas.append(
                {
                    "producto": grupo["producto"],
                    "cod_producto": grupo["cod_producto"],
                    "bultos": sum((c["bultos"] for c in clientes_lista), Decimal("0.00")),
                    "unidades": sum((c["unidades"] for c in clientes_lista), Decimal("0.00")),
                    "monto_total": total_producto,
                    "clientes": clientes_lista,
                }
            )

        # Ordenar por monto total descendente
        filas = sorted(filas, key=lambda f: f["monto_total"], reverse=True)

        total_general = sum(f["monto_total"] for f in filas)

        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "id_vendedor": id_vendedor,
            "id_producto": id_producto,
            "filas": filas,
            "total_general": total_general,
            "bultos_general": sum((f["bultos"] for f in filas), Decimal("0.00")),
            "unidades_general": sum((f["unidades"] for f in filas), Decimal("0.00")),
        }

    @staticmethod
    def activacion_clientes(
        session: Session,
        id_usuario: int | None,
        fecha_desde: date,
        fecha_hasta: date,
        id_vendedor: int | None = None,
    ) -> dict:
        """Cuenta cuantas facturas tuvo cada cliente en el rango y lo compara contra la
        cuota de activacion de SU vendedor asignado (Vendedor.meta_activacion,
        migrations/0042) -- decision de negocio 2026-09-03: la meta de frecuencia se
        configura por vendedor, no por cliente/ruta/categoria (VendedorFormDialog). Sin
        meta configurada (None) el cliente aparece en el reporte pero sin
        efectividad_pct -- no hay contra que comparar."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        def _filtros_clientes(query):
            query = query.filter(Cliente.estado_cliente == "ACTIVO").filter(Cliente.vendedor_cliente.isnot(None))
            if id_vendedor is not None:
                query = query.filter(Cliente.vendedor_cliente == id_vendedor)
            return query

        clientes = (
            _filtros_clientes(session.query(Cliente).options(joinedload(Cliente.vendedor)))
            .order_by(Cliente.nombre_razon_social)
            .all()
        )

        # El conteo se hace en la base, unido a los mismos clientes: antes se pasaba la lista de ids en un
        # IN, que SQL Server rechaza con mas de ~2100 clientes.
        conteo_facturas: dict[int, int] = dict(
            _filtros_clientes(
                session.query(FacturaVenta.id_cliente_factura, func.count(FacturaVenta.id_factura)).join(
                    Cliente, Cliente.id_cliente == FacturaVenta.id_cliente_factura
                )
            )
            .filter(FacturaVenta.estado_factura != "ANULADA")
            .filter(FacturaVenta.fecha_emision >= desde_dt)
            .filter(FacturaVenta.fecha_emision <= hasta_dt)
            .group_by(FacturaVenta.id_cliente_factura)
            .all()
        )

        filas = []
        for cliente in clientes:
            cantidad_facturas = conteo_facturas.get(cliente.id_cliente, 0)
            meta = cliente.vendedor.meta_activacion if cliente.vendedor else None
            if meta:
                efectividad_pct = round(to_decimal(cantidad_facturas) / to_decimal(meta) * Decimal("100"), 2)
            else:
                efectividad_pct = None
            filas.append(
                {
                    "cliente": cliente.nombre_razon_social,
                    "vendedor": (cliente.vendedor.nombre_vendedor if cliente.vendedor else None),
                    "cantidad_facturas": cantidad_facturas,
                    "meta_activacion": meta,
                    "efectividad_pct": efectividad_pct,
                    "activo": cantidad_facturas > 0,
                }
            )

        efectividades = [f["efectividad_pct"] for f in filas if f["efectividad_pct"] is not None]
        if efectividades:
            efectividad_promedio = round(to_decimal(sum(efectividades)) / to_decimal(len(efectividades)), 2)
        else:
            efectividad_promedio = None
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "total_clientes": len(filas),
            "total_activos": sum(1 for f in filas if f["activo"]),
            "efectividad_promedio": efectividad_promedio,
        }

    @staticmethod
    def productos_mas_vendidos(
        session: Session,
        id_usuario: int | None,
        fecha_desde: date,
        fecha_hasta: date,
        orden: str = "desc",
    ) -> dict:
        """Ranking de productos por monto vendido (cantidad x precio_unitario de cada
        linea) en el rango, excluyendo facturas ANULADA. orden='asc' para ver los menos
        vendidos en vez de los mas vendidos -- mismo reporte, mismo criterio, un solo
        parametro de orden en vez de dos reportes separados."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if orden not in ("asc", "desc"):
            raise ValueError("orden invalido, debe ser 'asc' o 'desc'")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        # Se suma en la base de datos (una fila por producto), no en Python sobre todas las lineas del periodo: con un
        # rango de meses eran decenas de miles de lineas traidas una por una. Bultos y unidades van aparte: sumarlos
        # en una sola cantidad mezclaria medidas distintas; las lineas viejas sin tipo_venta cuentan como unidades.
        es_bulto = FacturaDetalle.tipo_venta == "bulto"
        total_sql = func.sum(FacturaDetalle.cantidad_producto * FacturaDetalle.precio_unitario)
        agrupado = (
            session.query(
                Inventario.nombre_producto,
                func.sum(case((es_bulto, FacturaDetalle.cantidad_producto), else_=0)),
                func.sum(case((es_bulto, 0), else_=FacturaDetalle.cantidad_producto)),
                total_sql,
            )
            .select_from(FacturaDetalle)
            .join(FacturaVenta, FacturaVenta.id_factura == FacturaDetalle.id_factura)
            .join(Inventario, Inventario.id_producto == FacturaDetalle.id_producto_factura)
            .filter(FacturaVenta.estado_factura != "ANULADA")
            .filter(FacturaVenta.fecha_emision >= desde_dt)
            .filter(FacturaVenta.fecha_emision <= hasta_dt)
            .group_by(Inventario.id_producto, Inventario.nombre_producto)
            .order_by(total_sql.desc() if orden == "desc" else total_sql.asc(), Inventario.id_producto)
            .all()
        )
        filas = [
            {
                "producto": nombre,
                "bultos": to_decimal(bultos),
                "unidades": to_decimal(unidades),
                "total": to_decimal(total),
            }
            for nombre, bultos, unidades, total in agrupado
        ]
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "orden": orden,
            "filas": filas,
            "total_general": sum((f["total"] for f in filas), Decimal("0.00")),
        }

    @staticmethod
    def productos_proximos_a_vencer(
        session: Session,
        id_usuario: int | None,
        dias_horizonte: int = 30,
        id_categoria: int | None = None,
    ) -> dict:
        """Listado de productos proximos a vencerse, con los dias restantes hasta la
        fecha de vencimiento (fecha_vencimiento - fecha_actual). Solo incluye productos
        con fecha_vencimiento definida y que vencen dentro del horizonte especificado.
        """
        require_permiso(session, id_usuario, "reportes", "ver")
        if dias_horizonte <= 0:
            raise ValueError("dias_horizonte debe ser mayor a 0")

        fecha_actual = date.today()
        fecha_limite = fecha_actual + timedelta(days=dias_horizonte)

        query = (
            session.query(Inventario)
            .options(joinedload(Inventario.categoria))
            .filter(Inventario.fecha_vencimiento.isnot(None))
            .filter(Inventario.fecha_vencimiento >= fecha_actual)
            .filter(Inventario.fecha_vencimiento <= fecha_limite)
            .filter(Inventario.estado_producto == "ACTIVO")
        )
        if id_categoria:
            query = query.filter(Inventario.id_categoria == id_categoria)

        productos = query.order_by(Inventario.fecha_vencimiento).all()

        filas = []
        for producto in productos:
            dias_para_vencer = (producto.fecha_vencimiento - fecha_actual).days if producto.fecha_vencimiento else 0
            filas.append(
                {
                    "id_producto": producto.id_producto,
                    "cod_producto": producto.cod_producto,
                    "producto": producto.nombre_producto,
                    "categoria": (producto.categoria.nombre if producto.categoria else None),
                    "cantidad_unidad": producto.cantidad_unidad,
                    "fecha_vencimiento": producto.fecha_vencimiento,
                    "dias_para_vencer": dias_para_vencer,
                }
            )

        return {
            "fecha_actual": fecha_actual,
            "dias_horizonte": dias_horizonte,
            "filas": filas,
            "total_productos": len(filas),
        }

    @staticmethod
    def facturas_anuladas(session: Session, id_usuario: int | None, fecha_desde: date, fecha_hasta: date) -> dict:
        """Listado de facturas anuladas EN el rango (por fecha de anulacion, no de emision: una factura
        de octubre anulada en noviembre sale en el reporte de noviembre), con el motivo. La fecha y el
        motivo vienen de Auditoria (accion ANULACION_FACTURA), la unica fuente que los guarda --
        FacturaVenta no tiene columnas propias para eso. Se parte de los eventos del rango y no de las
        facturas, para no recorrer toda la auditoria. No incluye un monto: total_venta/monto_iva quedan
        en 0 despues de anular (el trigger de recalculo se dispara al borrar las lineas de
        factura_detalle, ver CLAUDE.md seccion de triggers) y no hay ningun otro lado donde el monto
        original haya quedado guardado -- mostrar un total aca seria inventar un dato que el sistema no
        conserva."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        eventos = (
            session.query(Auditoria)
            .filter(Auditoria.accion == "ANULACION_FACTURA")
            .filter(Auditoria.modulo == "VENTAS")
            .filter(Auditoria.fecha_evento >= desde_dt)
            .filter(Auditoria.fecha_evento <= hasta_dt)
            .order_by(Auditoria.fecha_evento)
            .all()
        )
        anulaciones: dict[str, tuple[datetime, str | None]] = {}
        for evento in eventos:
            try:
                detalle = json.loads(evento.detalle) if evento.detalle else {}
            except (TypeError, ValueError):
                continue
            numero = detalle.get("numero_factura") if isinstance(detalle, dict) else None
            if numero:
                anulaciones[numero] = (evento.fecha_evento, detalle.get("motivo"))

        facturas: list[FacturaVenta] = []
        numeros = list(anulaciones)
        for i in range(0, len(numeros), _TAMANO_LOTE_IN):  # por lotes: SQL Server limita los parametros de un IN
            facturas.extend(
                session.query(FacturaVenta)
                .options(joinedload(FacturaVenta.cliente), joinedload(FacturaVenta.vendedor))
                .filter(FacturaVenta.estado_factura == "ANULADA")
                .filter(FacturaVenta.numero_factura.in_(numeros[i : i + _TAMANO_LOTE_IN]))
                .all()
            )

        filas = [
            {
                "numero_factura": factura.numero_factura,
                "cliente": (factura.cliente.nombre_razon_social if factura.cliente else None),
                "vendedor": (factura.vendedor.nombre_vendedor if factura.vendedor else None),
                "fecha_emision": factura.fecha_emision,
                "fecha_anulacion": anulaciones[factura.numero_factura][0],
                "motivo": anulaciones[factura.numero_factura][1],
            }
            for factura in facturas
        ]
        filas.sort(key=lambda f: f["fecha_anulacion"])
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "total_facturas": len(filas),
        }

    @staticmethod
    def notas_credito_emitidas(
        session: Session,
        id_usuario: int | None,
        fecha_desde: date,
        fecha_hasta: date,
        id_cliente: int | None = None,
        pagina: int | None = None,
        por_pagina: int = POR_PAGINA_REPORTE,
    ) -> dict:
        """Listado detallado de notas de credito de cliente emitidas en el rango (motivo,
        factura de origen, estado disponible/aplicada/devuelta) -- version standalone del
        resumen que libro_ventas() ya muestra como un solo chip agregado. Con `pagina=None` devuelve todas las filas
        (la exportacion); con `pagina`, solo esa (ver `paginacion`). El total es siempre el de todo el filtro."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        filtros = [NotaCreditoCliente.fecha_creacion >= desde_dt, NotaCreditoCliente.fecha_creacion <= hasta_dt]
        if id_cliente:
            filtros.append(NotaCreditoCliente.id_cliente == id_cliente)
        query = (
            session.query(NotaCreditoCliente)
            .options(
                joinedload(NotaCreditoCliente.cliente),
                joinedload(NotaCreditoCliente.factura_origen),
            )
            .filter(*filtros)
        )
        notas, paginacion = _pagina_o_todo(
            query, pagina, por_pagina, NotaCreditoCliente.fecha_creacion, NotaCreditoCliente.id_nota_credito
        )
        total_general = to_decimal(
            session.query(func.coalesce(func.sum(NotaCreditoCliente.monto), 0)).filter(*filtros).scalar()
        )

        filas = [
            {
                "numero_nota_credito": nota.numero_nota_credito,
                "cliente": nota.cliente.nombre_razon_social if nota.cliente else None,
                "numero_factura_origen": (nota.factura_origen.numero_factura if nota.factura_origen else None),
                "fecha_creacion": nota.fecha_creacion,
                "monto": nota.monto,
                "saldo_disponible": nota.saldo_disponible,
                "motivo": nota.motivo,
                "estado": nota.estado,
            }
            for nota in notas
        ]
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "paginacion": paginacion,
            "total_general": total_general,
        }

    @staticmethod
    def ventas_contado_vs_credito(
        session: Session, id_usuario: int | None, fecha_desde: date, fecha_hasta: date
    ) -> dict:
        """Comparativo de ventas de contado vs. credito en el rango, excluyendo ANULADA."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        # Se agrupa y suma en la base de datos (una fila por condicion de pago), no en Python sobre cada factura.
        agrupado = (
            session.query(
                FacturaVenta.condicion_pago, func.count(FacturaVenta.id_factura), func.sum(_TOTAL_FACTURA_SQL)
            )
            .filter(FacturaVenta.estado_factura != "ANULADA")
            .filter(FacturaVenta.fecha_emision >= desde_dt)
            .filter(FacturaVenta.fecha_emision <= hasta_dt)
            .group_by(FacturaVenta.condicion_pago)
            .all()
        )

        # contado y credito aparecen siempre, aunque no haya ventas de alguno
        resumen = {
            "contado": {"cantidad_facturas": 0, "total": Decimal("0.00")},
            "credito": {"cantidad_facturas": 0, "total": Decimal("0.00")},
        }
        for condicion, cantidad, total in agrupado:
            resumen[condicion] = {"cantidad_facturas": cantidad, "total": to_decimal(total)}

        total_general = sum((g["total"] for g in resumen.values()), Decimal("0.00"))
        filas = [
            {
                "condicion_pago": condicion,
                "cantidad_facturas": grupo["cantidad_facturas"],
                "total": grupo["total"],
                "porcentaje": (
                    (to_decimal(grupo["total"]) / to_decimal(total_general) * Decimal("100"))
                    if total_general
                    else Decimal("0.00")
                ),
            }
            for condicion, grupo in resumen.items()
        ]
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "total_general": total_general,
        }

    @staticmethod
    def margen_utilidad_productos(
        session: Session, id_usuario: int | None, fecha_desde: date, fecha_hasta: date
    ) -> dict:
        """Margen de utilidad por producto vendido en el rango (ingreso - costo,
        excluyendo ANULADA). Usa el costo ACTUAL de Inventario.costo_producto (costo de UNA
        unidad; las lineas vendidas por bulto se pasan a unidades con cantidad_caja) -- el schema
        no guarda un costo historico por linea de venta, asi que el margen de una venta
        vieja es una aproximacion si el costo del producto cambio desde entonces."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        # Se suma en la base de datos (una fila por producto), no en Python sobre todas las lineas del periodo.
        # Bultos y unidades van en columnas separadas (medidas distintas); lineas sin tipo_venta = unidades.
        # costo_producto es el costo de UNA unidad: una linea vendida por bulto cuesta cantidad_caja unidades por
        # bulto (mismo calculo que descuenta el stock en trg_factura_detalle_stock_ins).
        es_bulto = FacturaDetalle.tipo_venta == "bulto"
        unidades_por_bulto = func.coalesce(func.nullif(Inventario.cantidad_caja, 0), 1)
        agrupado = (
            session.query(
                Inventario.nombre_producto,
                Inventario.costo_producto,
                func.sum(case((es_bulto, FacturaDetalle.cantidad_producto), else_=0)),
                func.sum(case((es_bulto, 0), else_=FacturaDetalle.cantidad_producto)),
                func.sum(FacturaDetalle.cantidad_producto * FacturaDetalle.precio_unitario),
                func.sum(
                    case(
                        (es_bulto, FacturaDetalle.cantidad_producto * unidades_por_bulto),
                        else_=FacturaDetalle.cantidad_producto,
                    )
                ),
            )
            .select_from(FacturaDetalle)
            .join(FacturaVenta, FacturaVenta.id_factura == FacturaDetalle.id_factura)
            .join(Inventario, Inventario.id_producto == FacturaDetalle.id_producto_factura)
            .filter(FacturaVenta.estado_factura != "ANULADA")
            .filter(FacturaVenta.fecha_emision >= desde_dt)
            .filter(FacturaVenta.fecha_emision <= hasta_dt)
            .group_by(Inventario.id_producto, Inventario.nombre_producto, Inventario.costo_producto)
            .all()
        )

        filas = []
        for nombre, costo_unitario, bultos, unidades, ingreso, unidades_costeadas in agrupado:
            grupo = {
                "producto": nombre,
                "bultos": to_decimal(bultos),
                "unidades": to_decimal(unidades),
                "ingreso": to_decimal(ingreso),
                "costo": to_decimal(unidades_costeadas) * to_decimal(costo_unitario or 0),
            }
            margen = to_decimal(grupo["ingreso"]) - to_decimal(grupo["costo"])
            if grupo["ingreso"]:
                margen_pct = margen / to_decimal(grupo["ingreso"]) * Decimal("100")
            else:
                margen_pct = Decimal("0.00")
            filas.append({**grupo, "margen": margen, "margen_pct": margen_pct})
        filas.sort(key=lambda f: f["margen"], reverse=True)

        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "total_ingreso": sum((f["ingreso"] for f in filas), Decimal("0.00")),
            "total_costo": sum((f["costo"] for f in filas), Decimal("0.00")),
            "total_margen": sum((f["margen"] for f in filas), Decimal("0.00")),
        }

    @staticmethod
    def compras_por_periodo(
        session: Session,
        id_usuario: int | None,
        fecha_desde: date,
        fecha_hasta: date,
        agrupacion: str = "dia",
    ) -> dict:
        """Total comprado y cantidad de compras por dia o por mes, excluyendo ANULADA.
        Compra no tiene desglose de IVA (a diferencia de FacturaVenta) asi que el total
        es directamente total_compra."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if agrupacion not in ("dia", "mes"):
            raise ValueError("agrupacion invalida, debe ser 'dia' o 'mes'")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        # Se agrupa y suma en la base de datos (una fila por dia o mes), no en Python sobre cada compra.
        clave_sql = _periodo_sql(Compra.fecha_emision, agrupacion)
        agrupado = (
            session.query(clave_sql, func.count(Compra.id_compra), func.sum(Compra.total_compra))
            .filter(Compra.estado_compra != "ANULADA")
            .filter(Compra.fecha_emision >= desde_dt)
            .filter(Compra.fecha_emision <= hasta_dt)
            .group_by(clave_sql)
            .order_by(clave_sql)
            .all()
        )
        filas = [
            {"fecha": clave, "cantidad_compras": cantidad, "total": to_decimal(total)}
            for clave, cantidad, total in agrupado
        ]
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "agrupacion": agrupacion,
            "filas": filas,
            "total_general": sum((f["total"] for f in filas), Decimal("0.00")),
            "total_compras": sum(f["cantidad_compras"] for f in filas),
        }

    @staticmethod
    def compras_por_proveedor(session: Session, id_usuario: int | None, fecha_desde: date, fecha_hasta: date) -> dict:
        """Ranking de proveedores por monto comprado en el rango, excluyendo ANULADA."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        # Se agrupa y suma en la base de datos (una fila por proveedor), no en Python sobre cada compra.
        total_sql = func.sum(Compra.total_compra)
        agrupado = (
            session.query(
                Proveedor.id_proveedor, Proveedor.nombre_razon_social, func.count(Compra.id_compra), total_sql
            )
            .select_from(Compra)
            .outerjoin(Proveedor, Proveedor.id_proveedor == Compra.id_proveedor)
            .filter(Compra.estado_compra != "ANULADA")
            .filter(Compra.fecha_emision >= desde_dt)
            .filter(Compra.fecha_emision <= hasta_dt)
            .group_by(Proveedor.id_proveedor, Proveedor.nombre_razon_social)
            .order_by(total_sql.desc(), Proveedor.id_proveedor)
            .all()
        )
        filas = [
            {"proveedor": nombre, "cantidad_compras": cantidad, "total": to_decimal(total)}
            for _id, nombre, cantidad, total in agrupado
        ]
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "total_general": sum((f["total"] for f in filas), Decimal("0.00")),
        }

    @staticmethod
    def compras_por_producto(
        session: Session,
        id_usuario: int | None,
        fecha_desde: date,
        fecha_hasta: date,
        orden: str = "desc",
    ) -> dict:
        """Ranking de productos por monto comprado (cantidad x costo_unitario de cada
        linea) en el rango, excluyendo compras ANULADA. orden='asc' para ver los que
        menos se compran."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if orden not in ("asc", "desc"):
            raise ValueError("orden invalido, debe ser 'asc' o 'desc'")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        # Se suma en la base de datos (una fila por producto), no en Python sobre todas las lineas del periodo.
        total_sql = func.sum(CompraDetalle.cantidad_producto * CompraDetalle.costo_unitario)
        agrupado = (
            session.query(Inventario.nombre_producto, func.sum(CompraDetalle.cantidad_producto), total_sql)
            .select_from(CompraDetalle)
            .join(Compra, Compra.id_compra == CompraDetalle.id_compra)
            .join(Inventario, Inventario.id_producto == CompraDetalle.id_producto_compra)
            .filter(Compra.estado_compra != "ANULADA")
            .filter(Compra.fecha_emision >= desde_dt)
            .filter(Compra.fecha_emision <= hasta_dt)
            .group_by(Inventario.id_producto, Inventario.nombre_producto)
            .order_by(total_sql.desc() if orden == "desc" else total_sql.asc(), Inventario.id_producto)
            .all()
        )
        filas = [
            {"producto": nombre, "cantidad": to_decimal(cantidad), "total": to_decimal(total)}
            for nombre, cantidad, total in agrupado
        ]
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "orden": orden,
            "filas": filas,
            "total_general": sum((f["total"] for f in filas), Decimal("0.00")),
        }

    @staticmethod
    def ordenes_compra_abiertas(session: Session, id_usuario: int | None, id_proveedor: int | None = None) -> dict:
        """Ordenes de compra abiertas (PENDIENTE o PARCIAL) a la fecha actual, con lo
        solicitado/recibido/pendiente por OC -- para ver que hay comprometido con
        proveedores y todavia no ha llegado. Es una foto al presente (como los aging de
        CxC/CxP), no un reporte por rango de fechas."""
        require_permiso(session, id_usuario, "reportes", "ver")
        hoy = date.today()

        query = (
            session.query(CompraOC)
            .options(joinedload(CompraOC.proveedor))
            .filter(CompraOC.estado.in_(ESTADOS_OC_ABIERTAS))
        )
        if id_proveedor:
            query = query.filter(CompraOC.id_proveedor == id_proveedor)
        ordenes = query.order_by(CompraOC.fecha_oc).all()

        filas = [
            {
                "numero_oc": oc.numero_oc,
                "proveedor": oc.proveedor.nombre_razon_social if oc.proveedor else None,
                "fecha_oc": oc.fecha_oc,
                "fecha_estimada_entrega": oc.fecha_estimada_entrega,
                "cantidad_solicitada": oc.cantidad_solicitada,
                "cantidad_recibida": oc.cantidad_recibida,
                "cantidad_pendiente": oc.cantidad_solicitada - oc.cantidad_recibida,
                "estado": oc.estado,
                "total_oc": oc.total_oc,
                "vencida": bool(oc.fecha_estimada_entrega and oc.fecha_estimada_entrega < hoy),
            }
            for oc in ordenes
        ]
        return {
            "fecha_corte": hoy,
            "filas": filas,
            "total_vencidas": sum(1 for f in filas if f["vencida"]),
            "total_ordenes": len(filas),
            "total_general": sum((f["total_oc"] for f in filas), Decimal("0.00")),
        }

    @staticmethod
    def cumplimiento_proveedores(
        session: Session, id_usuario: int | None, fecha_desde: date, fecha_hasta: date
    ) -> dict:
        """Cumplimiento de entrega por proveedor: de las OC con al menos una recepcion en
        el rango, que porcentaje llego a tiempo (fecha de la ultima recepcion <=
        fecha_estimada_entrega de la OC). Las OC sin fecha_estimada_entrega cuentan en
        cantidad_oc pero quedan fuera de a_tiempo/tardias -- no hay con que compararlas.
        """
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        # Fecha de la ultima recepcion de cada OC (dentro del rango), calculada en la base; despues se cuenta por
        # proveedor tambien en la base, no en Python sobre cada recepcion.
        ultima = (
            session.query(
                NotaRecepcion.id_oc.label("id_oc"), func.max(NotaRecepcion.fecha_recepcion).label("ultima_recepcion")
            )
            .filter(NotaRecepcion.estado != "ANULADA")
            .filter(NotaRecepcion.fecha_recepcion >= desde_dt)
            .filter(NotaRecepcion.fecha_recepcion <= hasta_dt)
            .group_by(NotaRecepcion.id_oc)
            .subquery()
        )
        sin_fecha = CompraOC.fecha_estimada_entrega.is_(None)
        llego_a_tiempo = cast(ultima.c.ultima_recepcion, Date) <= CompraOC.fecha_estimada_entrega
        agrupado = (
            session.query(
                CompraOC.id_proveedor,
                Proveedor.nombre_razon_social,
                func.count(CompraOC.id_oc),
                func.sum(case((~sin_fecha & llego_a_tiempo, 1), else_=0)),
                func.sum(case((~sin_fecha & ~llego_a_tiempo, 1), else_=0)),
                func.sum(case((sin_fecha, 1), else_=0)),
            )
            .select_from(CompraOC)
            .join(ultima, ultima.c.id_oc == CompraOC.id_oc)
            .outerjoin(Proveedor, Proveedor.id_proveedor == CompraOC.id_proveedor)
            .group_by(CompraOC.id_proveedor, Proveedor.nombre_razon_social)
            .order_by(func.count(CompraOC.id_oc).desc(), CompraOC.id_proveedor)
            .all()
        )
        filas = []
        for _id, nombre, cantidad_oc, a_tiempo, tardias, sin_fecha_estimada in agrupado:
            evaluables = to_decimal(a_tiempo) + to_decimal(tardias)
            pct_a_tiempo = (to_decimal(a_tiempo) / evaluables * Decimal("100")) if evaluables else None
            filas.append(
                {
                    "proveedor": nombre,
                    "cantidad_oc": cantidad_oc,
                    "a_tiempo": int(a_tiempo),
                    "tardias": int(tardias),
                    "sin_fecha_estimada": int(sin_fecha_estimada),
                    "pct_a_tiempo": pct_a_tiempo,
                }
            )

        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
        }

    @staticmethod
    def devoluciones_proveedor(
        session: Session,
        id_usuario: int | None,
        fecha_desde: date,
        fecha_hasta: date,
        id_proveedor: int | None = None,
        pagina: int | None = None,
        por_pagina: int = POR_PAGINA_REPORTE,
    ) -> dict:
        """Listado de devoluciones a proveedor (nota_devolucion) emitidas en el rango, con
        motivo, cantidad y el proveedor/OC de origen (via nota_recepcion). Con `pagina=None` devuelve todas las filas
        (la exportacion); con `pagina`, solo esa. Los totales son siempre los de todo el filtro."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        filtros = [NotaDevolucion.fecha_devolucion >= desde_dt, NotaDevolucion.fecha_devolucion <= hasta_dt]
        if id_proveedor:
            filtros.append(CompraOC.id_proveedor == id_proveedor)

        def con_origen(consulta):
            return (
                consulta.join(NotaRecepcion, NotaRecepcion.id_nr == NotaDevolucion.id_nr)
                .join(CompraOC, CompraOC.id_oc == NotaRecepcion.id_oc)
                .filter(*filtros)
            )

        query = con_origen(session.query(NotaDevolucion)).options(
            joinedload(NotaDevolucion.nota_recepcion).joinedload(NotaRecepcion.oc).joinedload(CompraOC.proveedor)
        )
        devoluciones, paginacion = _pagina_o_todo(
            query, pagina, por_pagina, NotaDevolucion.fecha_devolucion, NotaDevolucion.id_devolucion
        )
        cantidad, total_cantidad = con_origen(
            session.query(
                func.count(NotaDevolucion.id_devolucion), func.coalesce(func.sum(NotaDevolucion.cantidad_total), 0)
            )
        ).one()

        filas = [
            {
                "numero_nota_devolucion": d.numero_nota_devolucion,
                "proveedor": (
                    d.nota_recepcion.oc.proveedor.nombre_razon_social if d.nota_recepcion.oc.proveedor else None
                ),
                "numero_oc": d.nota_recepcion.oc.numero_oc,
                "fecha_devolucion": d.fecha_devolucion,
                "motivo": d.motivo,
                "cantidad_total": d.cantidad_total,
                "estado": d.estado,
            }
            for d in devoluciones
        ]
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "paginacion": paginacion,
            "total_devoluciones": int(cantidad),
            "total_cantidad": to_decimal(total_cantidad),
        }

    @staticmethod
    def notas_credito_proveedor(
        session: Session,
        id_usuario: int | None,
        fecha_desde: date,
        fecha_hasta: date,
        id_proveedor: int | None = None,
        pagina: int | None = None,
        por_pagina: int = POR_PAGINA_REPORTE,
    ) -> dict:
        """Listado de notas de credito de proveedor (saldo a favor de la empresa,
        generado al anular una compra con pagos ya aplicados) creadas en el rango. A
        diferencia de NotaCreditoCliente esta no es un documento fiscal correlativo -- ver
        el docstring de NotaCreditoProveedor en models.py. Con `pagina=None` devuelve todas las filas (la exportacion);
        con `pagina`, solo esa. El total es siempre el de todo el filtro."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        filtros = [NotaCreditoProveedor.fecha_creacion >= desde_dt, NotaCreditoProveedor.fecha_creacion <= hasta_dt]
        if id_proveedor:
            filtros.append(NotaCreditoProveedor.id_proveedor == id_proveedor)
        query = (
            session.query(NotaCreditoProveedor)
            .options(
                joinedload(NotaCreditoProveedor.proveedor),
                joinedload(NotaCreditoProveedor.compra_origen),
            )
            .filter(*filtros)
        )
        notas, paginacion = _pagina_o_todo(
            query, pagina, por_pagina, NotaCreditoProveedor.fecha_creacion, NotaCreditoProveedor.id_nota_credito
        )
        total_general = to_decimal(
            session.query(func.coalesce(func.sum(NotaCreditoProveedor.monto), 0)).filter(*filtros).scalar()
        )

        filas = [
            {
                "id_nota_credito": nota.id_nota_credito,
                "proveedor": (nota.proveedor.nombre_razon_social if nota.proveedor else None),
                "numero_compra_origen": (nota.compra_origen.numero_compra if nota.compra_origen else None),
                "fecha_creacion": nota.fecha_creacion,
                "monto": nota.monto,
                "saldo_disponible": nota.saldo_disponible,
                "motivo": nota.motivo,
                "estado": nota.estado,
            }
            for nota in notas
        ]
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "paginacion": paginacion,
            "total_general": total_general,
        }

    @staticmethod
    def arqueo_caja(session: Session, id_usuario: int | None, id_caja: int) -> dict:
        """Arqueo de una caja: saldo esperado (apertura + entradas - salidas, segun
        caja_movimientos) contra el saldo_cierre registrado -- para detectar faltantes o
        sobrantes. Si la caja sigue abierta (fecha_cierre NULL), saldo_cierre/diferencia
        quedan en None y se cuentan los movimientos desde la apertura hasta ahora."""
        require_permiso(session, id_usuario, "reportes", "ver")
        caja = session.get(Caja, id_caja)
        if caja is None:
            raise ValueError("Caja no encontrada")
        if caja.fecha_apertura is None:
            raise ValueError(f"La caja '{caja.nombre_caja}' nunca se ha abierto")

        query = session.query(CajaMovimiento).filter(
            CajaMovimiento.id_caja == id_caja,
            CajaMovimiento.fecha_registro >= caja.fecha_apertura,
        )
        if caja.fecha_cierre is not None:
            query = query.filter(CajaMovimiento.fecha_registro <= caja.fecha_cierre)
        movimientos = query.order_by(CajaMovimiento.fecha_registro).all()

        total_entradas = sum(
            (to_decimal(m.monto_movimiento) for m in movimientos if m.tipo_movimiento == "entrada"),
            Decimal("0.00"),
        )
        total_salidas = sum(
            (to_decimal(m.monto_movimiento) for m in movimientos if m.tipo_movimiento == "salida"),
            Decimal("0.00"),
        )
        saldo_apertura = caja.saldo_apertura or Decimal("0.00")
        saldo_esperado = saldo_apertura + total_entradas - total_salidas
        diferencia = (caja.saldo_cierre - saldo_esperado) if caja.saldo_cierre is not None else None

        return {
            "id_caja": caja.id_caja,
            "nombre_caja": caja.nombre_caja,
            "fecha_apertura": caja.fecha_apertura,
            "fecha_cierre": caja.fecha_cierre,
            "saldo_apertura": saldo_apertura,
            "total_entradas": total_entradas,
            "total_salidas": total_salidas,
            "saldo_esperado": saldo_esperado,
            "saldo_cierre": caja.saldo_cierre,
            "diferencia": diferencia,
            "movimientos": [
                {
                    "fecha_registro": m.fecha_registro,
                    "tipo_movimiento": m.tipo_movimiento,
                    "descripcion_movimiento": m.descripcion_movimiento,
                    "monto_movimiento": m.monto_movimiento,
                }
                for m in movimientos
            ],
        }

    # ── Inventario ────────────────────────────────────────────────────────

    @staticmethod
    def kardex_producto(
        session: Session,
        id_usuario: int | None,
        id_producto: int,
        fecha_desde: date,
        fecha_hasta: date,
    ) -> dict:
        """Reconstruye el historial de movimientos de stock de un producto: no existe una
        tabla de movimientos dedicada (el stock se mueve directamente sobre
        Inventario.cantidad_unidad via triggers), asi que se arma desde las tablas de
        detalle que los disparan -- entradas: CompraDetalle (compra directa, sin OC, con
        stock_ya_contabilizado=False) y NotaRecepcionDetalle (recepcion de una OC, solo lo
        ACEPTADO: recibido - rechazado, ver migrations/0086); salidas: FacturaDetalle (una
        venta por bulto descuenta cantidad_caja unidades por bulto, ver migrations/0067).
        La devolucion a proveedor NO aparece: lo rechazado nunca entro al stock, asi que no
        lo mueve. Una factura/compra ANULADA no necesita caso especial: sus filas de
        detalle se borran (revirtiendo el stock via trigger), asi que simplemente dejan de
        aparecer aca."""
        require_permiso(session, id_usuario, "reportes", "ver")
        producto = session.get(Inventario, id_producto)
        if producto is None:
            raise ValueError("Producto no encontrado")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")

        eventos = []
        compras = (
            session.query(CompraDetalle, Compra)
            .join(Compra, CompraDetalle.id_compra == Compra.id_compra)
            .filter(CompraDetalle.id_producto_compra == id_producto)
            .filter(CompraDetalle.stock_ya_contabilizado == False)  # noqa: E712 -- BIT en mssql
            .all()
        )
        for detalle, compra in compras:
            eventos.append(
                {
                    "fecha": compra.fecha_emision,
                    "tipo": "Compra",
                    "referencia": compra.numero_compra,
                    "entrada": detalle.cantidad_producto,
                    "salida": Decimal("0.00"),
                }
            )
        recepciones = (
            session.query(NotaRecepcionDetalle, NotaRecepcion)
            .join(NotaRecepcion, NotaRecepcionDetalle.id_nr == NotaRecepcion.id_nr)
            .filter(NotaRecepcionDetalle.id_producto == id_producto)
            .all()
        )
        for detalle, nr in recepciones:
            eventos.append(
                {
                    "fecha": nr.fecha_recepcion,
                    "tipo": "Recepción OC",
                    "referencia": nr.numero_nr,
                    "entrada": detalle.cantidad_recibida - detalle.cantidad_rechazada,
                    "salida": Decimal("0.00"),
                }
            )
        ventas = (
            session.query(FacturaDetalle, FacturaVenta)
            .join(FacturaVenta, FacturaDetalle.id_factura == FacturaVenta.id_factura)
            .filter(FacturaDetalle.id_producto_factura == id_producto)
            .all()
        )
        # El stock esta en unidades: una venta por bulto descuenta cantidad_caja unidades por
        # cada bulto (mismo calculo que trg_factura_detalle_stock_ins).
        unidades_por_bulto = to_decimal(producto.cantidad_caja or 1)
        for detalle, factura in ventas:
            salida = detalle.cantidad_producto
            if detalle.tipo_venta == "bulto":
                salida = detalle.cantidad_producto * unidades_por_bulto
            eventos.append(
                {
                    "fecha": factura.fecha_emision,
                    "tipo": "Venta",
                    "referencia": factura.numero_factura,
                    "entrada": Decimal("0.00"),
                    "salida": salida,
                }
            )

        eventos.sort(key=lambda e: e["fecha"])
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        # Stock con que el producto ya contaba antes de su primer movimiento rastreable (carga inicial,
        # ajustes manuales de inventario): lo que le falta al historial de eventos para llegar al stock
        # real de hoy. Sin esto el kardex arrancaba en 0 y su saldo final no coincidia con el inventario.
        movimiento_total = sum((e["entrada"] - e["salida"] for e in eventos), Decimal("0.00"))
        saldo_apertura = to_decimal(producto.cantidad_unidad or 0) - movimiento_total

        saldo_inicial = saldo_apertura
        for evento in eventos:
            if evento["fecha"] < desde_dt:
                saldo_inicial += evento["entrada"] - evento["salida"]

        saldo = saldo_inicial
        filas = []
        for evento in eventos:
            if desde_dt <= evento["fecha"] <= hasta_dt:
                saldo += evento["entrada"] - evento["salida"]
                filas.append({**evento, "saldo": saldo})

        return {
            "id_producto": producto.id_producto,
            "cod_producto": producto.cod_producto,
            "nombre_producto": producto.nombre_producto,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "saldo_apertura": saldo_apertura,
            "saldo_inicial": saldo_inicial,
            "filas": filas,
            "saldo_final": saldo,
        }

    @staticmethod
    def valorizacion_inventario(session: Session, id_usuario: int | None, id_categoria: int | None = None) -> dict:
        """Valor de inventario a valor de costo actual (cantidad_unidad * costo_producto),
        snapshot de ahora mismo -- no hay costeo historico (FIFO/promedio) en el sistema,
        solo un costo_producto vigente por producto. Solo cantidad_unidad cuenta para el
        stock real (cantidad_caja fue deliberadamente descartada del flujo, ver
        producto_form_dialog.py)."""
        require_permiso(session, id_usuario, "reportes", "ver")
        query = (
            session.query(Inventario)
            .options(joinedload(Inventario.categoria))
            .filter(Inventario.estado_producto == "ACTIVO")
        )
        if id_categoria is not None:
            query = query.filter(Inventario.id_categoria == id_categoria)
        productos = query.order_by(Inventario.nombre_producto).all()

        filas = []
        totales_por_categoria: dict[str, Decimal] = {}
        for producto in productos:
            valor: Decimal = to_decimal(producto.cantidad_unidad or Decimal("0.00")) * to_decimal(
                producto.costo_producto or Decimal("0.00")
            )
            categoria = producto.categoria.nombre if producto.categoria else "Sin categoría"
            totales_por_categoria[categoria] = totales_por_categoria.get(categoria, Decimal("0.00")) + valor
            filas.append(
                {
                    "cod_producto": producto.cod_producto,
                    "nombre_producto": producto.nombre_producto,
                    "categoria": categoria,
                    "cantidad_unidad": producto.cantidad_unidad,
                    "costo_producto": producto.costo_producto,
                    "valor_total": valor,
                }
            )
        return {
            "filas": filas,
            "totales_por_categoria": totales_por_categoria,
            "total_general": sum(totales_por_categoria.values(), Decimal("0.00")),
        }

    @staticmethod
    def productos_bajo_minimo(session: Session, id_usuario: int | None, id_categoria: int | None = None) -> dict:
        """cantidad_minima=0 significa 'sin minimo configurado para este producto' (default
        de migrations/0037), no 'minimo es cero unidades' -- esos productos se excluyen.
        """
        require_permiso(session, id_usuario, "reportes", "ver")
        query = (
            session.query(Inventario)
            .options(joinedload(Inventario.categoria))
            .filter(Inventario.estado_producto == "ACTIVO")
            .filter(Inventario.cantidad_minima > 0)
            .filter(Inventario.cantidad_unidad < Inventario.cantidad_minima)
        )
        if id_categoria is not None:
            query = query.filter(Inventario.id_categoria == id_categoria)
        productos = query.all()

        filas = [
            {
                "cod_producto": producto.cod_producto,
                "nombre_producto": producto.nombre_producto,
                "categoria": producto.categoria.nombre if producto.categoria else None,
                "cantidad_unidad": producto.cantidad_unidad,
                "cantidad_minima": producto.cantidad_minima,
                "deficit": producto.cantidad_minima - producto.cantidad_unidad,
            }
            for producto in productos
        ]
        filas.sort(key=lambda f: f["deficit"], reverse=True)
        return {"filas": filas, "total_productos": len(filas)}

    @staticmethod
    def productos_sin_movimiento(
        session: Session,
        id_usuario: int | None,
        fecha_desde: date,
        fecha_hasta: date,
        id_categoria: int | None = None,
    ) -> dict:
        """Productos activos sin ventas ni compras en el rango, con la fecha de su ultimo movimiento
        (en cualquier fecha). Todo se resuelve en la base con tres consultas, sin importar cuantos
        productos haya: la exclusion es un NOT EXISTS y las ultimas fechas un GROUP BY."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        con_venta = exists().where(
            FacturaDetalle.id_producto_factura == Inventario.id_producto,
            FacturaDetalle.id_factura == FacturaVenta.id_factura,
            FacturaVenta.fecha_emision >= desde_dt,
            FacturaVenta.fecha_emision <= hasta_dt,
        )
        con_compra = exists().where(
            CompraDetalle.id_producto_compra == Inventario.id_producto,
            CompraDetalle.id_compra == Compra.id_compra,
            Compra.fecha_emision >= desde_dt,
            Compra.fecha_emision <= hasta_dt,
        )
        query = (
            session.query(Inventario)
            .options(joinedload(Inventario.categoria))
            .filter(Inventario.estado_producto == "ACTIVO")
            .filter(~con_venta, ~con_compra)
        )
        if id_categoria is not None:
            query = query.filter(Inventario.id_categoria == id_categoria)
        productos = query.order_by(Inventario.nombre_producto).all()

        ultima_venta = dict(
            session.query(FacturaDetalle.id_producto_factura, func.max(FacturaVenta.fecha_emision))
            .join(FacturaVenta, FacturaVenta.id_factura == FacturaDetalle.id_factura)
            .group_by(FacturaDetalle.id_producto_factura)
            .all()
        )
        ultima_compra = dict(
            session.query(CompraDetalle.id_producto_compra, func.max(Compra.fecha_emision))
            .join(Compra, Compra.id_compra == CompraDetalle.id_compra)
            .group_by(CompraDetalle.id_producto_compra)
            .all()
        )

        filas = []
        for producto in productos:
            fechas = [
                f
                for f in (ultima_venta.get(producto.id_producto), ultima_compra.get(producto.id_producto))
                if f is not None
            ]
            filas.append(
                {
                    "cod_producto": producto.cod_producto,
                    "nombre_producto": producto.nombre_producto,
                    "categoria": (producto.categoria.nombre if producto.categoria else None),
                    "cantidad_unidad": producto.cantidad_unidad,
                    "costo_producto": producto.costo_producto,
                    "fecha_ultimo_movimiento": max(fechas) if fechas else None,
                }
            )
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "total_productos": len(filas),
        }

    @staticmethod
    def historico_precios(
        session: Session,
        id_usuario: int | None,
        id_producto: int,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
    ) -> dict:
        """No hay tabla de historial de precios (producto_precios es un snapshot, una fila
        por producto desde migrations/0036) -- se reconstruye desde Auditoria, donde
        PrecioService.establecer_precio() (app/services/inventario.py) ya deja constancia
        de cada cambio (accion=CAMBIO_PRECIO, modulo=INVENTARIO). Mismo patron que
        facturas_anuladas() para leer Auditoria.detalle."""
        require_permiso(session, id_usuario, "reportes", "ver")
        producto = session.get(Inventario, id_producto)
        if producto is None:
            raise ValueError("Producto no encontrado")
        if fecha_desde is not None and fecha_hasta is not None and fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")

        query = session.query(Auditoria).filter(Auditoria.modulo == "INVENTARIO", Auditoria.accion == "CAMBIO_PRECIO")
        if fecha_desde is not None:
            query = query.filter(Auditoria.fecha_evento >= datetime.combine(fecha_desde, time.min))
        if fecha_hasta is not None:
            query = query.filter(Auditoria.fecha_evento <= datetime.combine(fecha_hasta, time.max))
        # El producto se filtra en la base (el detalle es un JSON con "id_producto": N); el chequeo exacto de
        # abajo descarta las coincidencias parciales por prefijo ("id_producto": 12 dentro de "id_producto": 123
        # no pasa el LIKE porque va seguido de coma o llave, pero el JSON podria cambiar de formato).
        query = query.filter(
            or_(
                Auditoria.detalle.like(f'%"id_producto": {int(id_producto)},%'),
                Auditoria.detalle.like(f'%"id_producto": {int(id_producto)}}}%'),
            )
        )
        eventos = query.options(joinedload(Auditoria.usuario)).order_by(Auditoria.fecha_evento).all()

        filas = []
        for evento in eventos:
            try:
                detalle = json.loads(evento.detalle) if evento.detalle else {}
            except (TypeError, ValueError):
                continue
            if detalle.get("id_producto") != id_producto:
                continue

            # Adaptar a la nueva estructura del detalle de PrecioService.establecer_precio
            # Ahora usa cambios_precio con objetos anidados para precio_1, precio_2, precio_3, margen
            precio_valor = None
            margen_valor = None

            # Intentar nueva estructura con cambios_precio
            cambios_precio = detalle.get("cambios_precio", {})
            if cambios_precio:
                # Obtener precio_1 (precio de venta principal)
                precio_1_cambio = cambios_precio.get("precio_1", {})
                if precio_1_cambio:
                    precio_valor = precio_1_cambio.get("nuevo")
                # Obtener margen
                margen_cambio = cambios_precio.get("margen", {})
                if margen_cambio:
                    margen_valor = margen_cambio.get("nuevo")
            else:
                # Fallback a estructura antigua para compatibilidad
                precio_valor = detalle.get("precio_nuevo") or detalle.get("precio_venta")
                margen_valor = detalle.get("margen_nuevo") or detalle.get("porcentaje_ganancia")

            filas.append(
                {
                    "fecha_evento": evento.fecha_evento,
                    "precio_venta": Decimal(precio_valor) if precio_valor else None,
                    "porcentaje_ganancia": (Decimal(margen_valor) if margen_valor else None),
                    "usuario": (evento.usuario.nombre_usuario if evento.usuario else None),
                }
            )
        return {
            "id_producto": producto.id_producto,
            "cod_producto": producto.cod_producto,
            "nombre_producto": producto.nombre_producto,
            "filas": filas,
        }

    # ── CxC ───────────────────────────────────────────────────────────────

    @staticmethod
    def estado_cuenta_cliente(
        session: Session,
        id_usuario: int | None,
        id_cliente: int,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
    ) -> dict:
        """Estado de cuenta de un cliente: cargos (facturas a credito, normales y BCV) y abonos (pagos
        aplicados y notas de credito aplicadas) en orden cronologico con saldo corrido. El cargo original
        de cada factura se reconstruye como saldo_pendiente + pagos ya aplicados + notas de credito
        aplicadas (la cuenta por cobrar no guarda el monto original, solo el saldo que va quedando). Las
        facturas con cuenta BCV cargan su monto por la cuenta BCV: su cuenta normal queda en cero. Sin
        fecha_desde/hasta muestra todo el historial (saldo_inicial=0); con rango, los movimientos previos
        a fecha_desde se pliegan en saldo_inicial, mismo criterio que kardex_producto."""
        require_permiso(session, id_usuario, "reportes", "ver")
        cliente = session.get(Cliente, id_cliente)
        if cliente is None:
            raise ValueError("Cliente no encontrado")
        if fecha_desde is not None and fecha_hasta is not None and fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")

        cuentas = (
            session.query(CuentaPorCobrar)
            .join(FacturaVenta, FacturaVenta.id_factura == CuentaPorCobrar.id_factura)
            .options(joinedload(CuentaPorCobrar.factura))
            .filter(FacturaVenta.id_cliente_factura == id_cliente)
            .all()
        )
        pagos = (
            session.query(PagoCobro)
            .join(
                CuentaPorCobrar,
                CuentaPorCobrar.id_cuenta_por_cobrar == PagoCobro.id_cuenta_por_cobrar,
            )
            .join(FacturaVenta, FacturaVenta.id_factura == CuentaPorCobrar.id_factura)
            .filter(FacturaVenta.id_cliente_factura == id_cliente)
            .options(joinedload(PagoCobro.cuenta_por_cobrar).joinedload(CuentaPorCobrar.factura))
            .all()
        )
        cuentas_bcv = (
            session.query(CuentaPorCobrarBCV)
            .join(FacturaVenta, FacturaVenta.id_factura == CuentaPorCobrarBCV.id_factura)
            .options(joinedload(CuentaPorCobrarBCV.factura))
            .filter(FacturaVenta.id_cliente_factura == id_cliente)
            .filter(CuentaPorCobrarBCV.estado != "anulada")
            .all()
        )
        pagos_bcv = (
            session.query(PagoCobroBCV)
            .join(
                CuentaPorCobrarBCV,
                CuentaPorCobrarBCV.id_cuenta_por_cobrar == PagoCobroBCV.id_cuenta_por_cobrar,
            )
            .join(FacturaVenta, FacturaVenta.id_factura == CuentaPorCobrarBCV.id_factura)
            .filter(FacturaVenta.id_cliente_factura == id_cliente)
            .options(joinedload(PagoCobroBCV.cuenta_por_cobrar).joinedload(CuentaPorCobrarBCV.factura))
            .all()
        )
        ids_facturas_cliente = {c.id_factura for c in cuentas}
        aplicaciones_nc = [a for a in _aplicaciones_nc_cliente(session) if a["id_factura"] in ids_facturas_cliente]
        ids_facturas_bcv = {c.id_factura for c in cuentas_bcv}

        # Sumas por cuenta/factura de una sola pasada: recorrer todos los pagos por cada cuenta era cuadratico (un
        # cliente con 3 500 movimientos tardaba 1,4 s).
        pagos_por_cuenta: dict[int, Decimal] = {}
        for p in pagos:
            pagos_por_cuenta[p.id_cuenta_por_cobrar] = (
                pagos_por_cuenta.get(p.id_cuenta_por_cobrar, Decimal("0.00")) + p.monto
            )
        pagos_bcv_por_cuenta: dict[int, Decimal] = {}
        for p in pagos_bcv:
            pagos_bcv_por_cuenta[p.id_cuenta_por_cobrar] = (
                pagos_bcv_por_cuenta.get(p.id_cuenta_por_cobrar, Decimal("0.00")) + p.monto
            )
        nc_por_factura: dict[int, Decimal] = {}
        for a in aplicaciones_nc:
            nc_por_factura[a["id_factura"]] = nc_por_factura.get(a["id_factura"], Decimal("0.00")) + a["monto"]

        eventos = []
        for cuenta in cuentas:
            pagos_de_cuenta = pagos_por_cuenta.get(cuenta.id_cuenta_por_cobrar, Decimal("0.00"))
            nc_de_cuenta = nc_por_factura.get(cuenta.id_factura, Decimal("0.00"))
            cargo = cuenta.saldo_pendiente + pagos_de_cuenta + nc_de_cuenta
            if cargo == 0 and cuenta.id_factura in ids_facturas_bcv:
                continue  # factura BCV: su cargo va por la cuenta BCV, esta cuenta normal solo esta en cero
            eventos.append(
                {
                    "fecha": cuenta.factura.fecha_emision,
                    "tipo": "Factura",
                    "referencia": cuenta.factura.numero_factura,
                    "cargo": cargo,
                    "abono": Decimal("0.00"),
                }
            )
        for cuenta in cuentas_bcv:
            pagos_de_cuenta = pagos_bcv_por_cuenta.get(cuenta.id_cuenta_por_cobrar, Decimal("0.00"))
            eventos.append(
                {
                    "fecha": cuenta.factura.fecha_emision,
                    "tipo": "Factura",
                    "referencia": f"{cuenta.factura.numero_factura} (BCV)",
                    "cargo": cuenta.saldo_pendiente + pagos_de_cuenta,
                    "abono": Decimal("0.00"),
                }
            )
        for pago in pagos:
            eventos.append(
                {
                    "fecha": pago.fecha_pago,
                    "tipo": "Pago",
                    "referencia": pago.referencia or pago.cuenta_por_cobrar.factura.numero_factura,
                    "cargo": Decimal("0.00"),
                    "abono": pago.monto,
                }
            )
        for pago in pagos_bcv:
            eventos.append(
                {
                    "fecha": pago.fecha_pago,
                    "tipo": "Pago",
                    "referencia": pago.referencia or f"{pago.cuenta_por_cobrar.factura.numero_factura} (BCV)",
                    "cargo": Decimal("0.00"),
                    "abono": pago.monto,
                }
            )
        for aplicacion in aplicaciones_nc:
            eventos.append(
                {
                    "fecha": aplicacion["fecha"],
                    "tipo": "Nota de crédito",
                    "referencia": aplicacion["numero_nota_credito"],
                    "cargo": Decimal("0.00"),
                    "abono": aplicacion["monto"],
                }
            )
        eventos.sort(key=lambda e: e["fecha"])

        desde_dt = datetime.combine(fecha_desde, time.min) if fecha_desde else None
        hasta_dt = datetime.combine(fecha_hasta, time.max) if fecha_hasta else None

        saldo_inicial = Decimal("0.00")
        for evento in eventos:
            if desde_dt is not None and evento["fecha"] < desde_dt:
                saldo_inicial += evento["cargo"] - evento["abono"]

        saldo = saldo_inicial
        filas = []
        for evento in eventos:
            if desde_dt is not None and evento["fecha"] < desde_dt:
                continue
            if hasta_dt is not None and evento["fecha"] > hasta_dt:
                continue
            saldo += evento["cargo"] - evento["abono"]
            filas.append({**evento, "saldo": saldo})

        return {
            "id_cliente": cliente.id_cliente,
            "cliente": cliente.nombre_razon_social,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "saldo_inicial": saldo_inicial,
            "filas": filas,
            "saldo_final": saldo,
        }

    @staticmethod
    def cobros_del_periodo(
        session: Session,
        id_usuario: int | None,
        fecha_desde: date,
        fecha_hasta: date,
        id_cliente: int | None = None,
        pagina: int | None = None,
        por_pagina: int = POR_PAGINA_REPORTE,
    ) -> dict:
        """Cobros (pagos aplicados a cuentas por cobrar) del rango, de la cartera normal y de la BCV
        (cada fila dice de cual viene en `cartera`), en orden cronologico. Con `pagina=None` devuelve todas las filas
        (la exportacion); con `pagina`, solo esa (ver `paginacion`): la pagina se elige con un UNION ALL de las dos
        carteras (solo id y fecha) y despues se cargan unicamente esos pagos. Los totales son siempre los de todo el
        filtro."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        def con_factura(consulta, pago, cuenta):
            consulta = consulta.join(cuenta, cuenta.id_cuenta_por_cobrar == pago.id_cuenta_por_cobrar).join(
                FacturaVenta, FacturaVenta.id_factura == cuenta.id_factura
            )
            consulta = consulta.filter(pago.fecha_pago >= desde_dt, pago.fecha_pago <= hasta_dt)
            if id_cliente is not None:
                consulta = consulta.filter(FacturaVenta.id_cliente_factura == id_cliente)
            return consulta

        carteras = (
            ("Normal", 0, PagoCobro, CuentaPorCobrar, PagoCobro.id_pago_cobro),
            ("BCV", 1, PagoCobroBCV, CuentaPorCobrarBCV, PagoCobroBCV.id_pago_cobro_bcv),
        )

        # Totales de todo el filtro, sumados en la base.
        totales_por_metodo: dict[str, Decimal] = {}
        for _nombre, _rango, pago, cuenta, _id in carteras:
            for metodo, total in con_factura(
                session.query(pago.metodo_pago, func.sum(pago.monto)), pago, cuenta
            ).group_by(pago.metodo_pago):
                totales_por_metodo[metodo] = totales_por_metodo.get(metodo, Decimal("0.00")) + to_decimal(total)

        if pagina is None:
            pagos = []
            for nombre, rango, pago, cuenta, id_pago in carteras:
                consulta = con_factura(session.query(pago), pago, cuenta).options(
                    joinedload(pago.cuenta_por_cobrar).joinedload(cuenta.factura).joinedload(FacturaVenta.cliente)
                )
                pagos.extend((p.fecha_pago, rango, getattr(p, id_pago.key), nombre, p) for p in consulta)
            pagos.sort(key=lambda t: t[:3])
            paginacion = None
        else:
            ids = []
            for _nombre, rango, pago, cuenta, id_pago in carteras:
                ids.append(
                    con_factura(
                        session.query(
                            literal(rango).label("rango"),
                            id_pago.label("id"),
                            pago.fecha_pago.label("fecha"),
                        ),
                        pago,
                        cuenta,
                    )
                )
            union = ids[0].union_all(ids[1]).subquery()
            elegidos = paginar(
                session.query(union.c.rango, union.c.id, union.c.fecha),
                pagina,
                por_pagina,
                union.c.fecha,
                union.c.rango,
                union.c.id,
            )
            paginacion = {k: v for k, v in elegidos.items() if k != "items"}
            por_cartera = {}
            for nombre, rango, pago, cuenta, id_pago in carteras:
                pedidos = [fila.id for fila in elegidos["items"] if fila.rango == rango]
                if pedidos:
                    cargados = (
                        session.query(pago)
                        .options(
                            joinedload(pago.cuenta_por_cobrar)
                            .joinedload(cuenta.factura)
                            .joinedload(FacturaVenta.cliente)
                        )
                        .filter(id_pago.in_(pedidos))
                        .all()
                    )
                    por_cartera.update({(rango, getattr(p, id_pago.key)): (nombre, p) for p in cargados})
            pagos = [
                (fila.fecha, fila.rango, fila.id, *por_cartera[(fila.rango, fila.id)]) for fila in elegidos["items"]
            ]

        filas = []
        for _fecha, _rango, _id, cartera, pago in pagos:
            factura = pago.cuenta_por_cobrar.factura
            filas.append(
                {
                    "fecha_pago": pago.fecha_pago,
                    "cliente": (factura.cliente.nombre_razon_social if factura.cliente else None),
                    "numero_factura": factura.numero_factura,
                    "cartera": cartera,
                    "metodo_pago": pago.metodo_pago,
                    "moneda": pago.moneda,
                    "monto": pago.monto,
                }
            )
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "paginacion": paginacion,
            "totales_por_metodo": totales_por_metodo,
            "total_general": sum(totales_por_metodo.values(), Decimal("0.00")),
        }

    @staticmethod
    def clientes_morosos(session: Session, id_usuario: int | None, fecha_corte: date | None = None) -> dict:
        """Agrupa por cliente las cuentas por cobrar abiertas y VENCIDAS, de la cartera normal y de la BCV
        (mismo universo que los aging excluyendo el bucket 'vigente'), agregando saldo total vencido y
        antiguedad maxima por cliente en vez de por bucket. Con un corte pasado se reconstruye el saldo
        que tenia cada cuenta a esa fecha (ver _cuentas_al_corte)."""
        require_permiso(session, id_usuario, "reportes", "ver")
        fecha_corte = fecha_corte or date.today()

        cuentas = _cuentas_al_corte(
            session,
            session.query(CuentaPorCobrar)
            .join(FacturaVenta, FacturaVenta.id_factura == CuentaPorCobrar.id_factura)
            .options(joinedload(CuentaPorCobrar.factura).joinedload(FacturaVenta.cliente)),
            CuentaPorCobrar,
            PagoCobro,
            PagoCobro.id_cuenta_por_cobrar,
            FacturaVenta.fecha_emision,
            ESTADOS_CXC_ABIERTOS,
            fecha_corte,
            CuentaPorCobrar.fecha_vencimiento,
            nc_por_factura=_nc_aplicadas_despues_del_corte(session, fecha_corte),
        ) + _cuentas_al_corte(
            session,
            session.query(CuentaPorCobrarBCV)
            .join(FacturaVenta, FacturaVenta.id_factura == CuentaPorCobrarBCV.id_factura)
            .options(joinedload(CuentaPorCobrarBCV.factura).joinedload(FacturaVenta.cliente)),
            CuentaPorCobrarBCV,
            PagoCobroBCV,
            PagoCobroBCV.id_cuenta_por_cobrar,
            FacturaVenta.fecha_emision,
            ESTADOS_CXC_BCV_ABIERTOS,
            fecha_corte,
            CuentaPorCobrarBCV.fecha_vencimiento,
        )

        por_cliente: dict[int | None, dict] = {}
        for cuenta, saldo in cuentas:
            dias_vencido = (fecha_corte - cuenta.fecha_vencimiento).days if cuenta.fecha_vencimiento else 0
            if dias_vencido <= 0:
                continue
            cliente = cuenta.factura.cliente
            id_cliente = cliente.id_cliente if cliente else None
            entrada = por_cliente.setdefault(
                id_cliente,
                {
                    "id_cliente": id_cliente,
                    "cliente": cliente.nombre_razon_social if cliente else None,
                    "saldo_vencido": Decimal("0.00"),
                    "dias_vencido_max": 0,
                    "facturas_vencidas": 0,
                },
            )
            entrada["saldo_vencido"] += saldo
            entrada["dias_vencido_max"] = max(entrada["dias_vencido_max"], dias_vencido)
            entrada["facturas_vencidas"] += 1

        filas = sorted(por_cliente.values(), key=lambda f: f["saldo_vencido"], reverse=True)
        return {
            "fecha_corte": fecha_corte,
            "filas": filas,
            "total_general": sum((f["saldo_vencido"] for f in filas), Decimal("0.00")),
        }

    @staticmethod
    def cxc_otras(
        session: Session,
        id_usuario: int | None,
        id_cliente: int | None = None,
        estado: str | None = None,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
        pagina: int | None = None,
        por_pagina: int = POR_PAGINA_REPORTE,
    ) -> dict:
        """Cuentas por cobrar "otras". Con `pagina=None` devuelve todas las filas (la exportacion); con `pagina`, solo
        esa (ver `paginacion`). El total es siempre el de todo el filtro."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if estado is not None and estado not in ESTADOS_CXC_OTRO:
            raise ValueError(f"estado invalido: {estado!r}, debe ser uno de {ESTADOS_CXC_OTRO}")
        if fecha_desde is not None and fecha_hasta is not None and fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")

        filtros = []
        if id_cliente is not None:
            filtros.append(CuentaPorCobrarOtro.id_cliente == id_cliente)
        if estado is not None:
            filtros.append(CuentaPorCobrarOtro.estado == estado)
        if fecha_desde is not None:
            filtros.append(CuentaPorCobrarOtro.fecha_emision >= datetime.combine(fecha_desde, time.min))
        if fecha_hasta is not None:
            filtros.append(CuentaPorCobrarOtro.fecha_emision <= datetime.combine(fecha_hasta, time.max))
        query = session.query(CuentaPorCobrarOtro).options(joinedload(CuentaPorCobrarOtro.cliente)).filter(*filtros)
        cuentas, paginacion = _pagina_o_todo(
            query, pagina, por_pagina, CuentaPorCobrarOtro.fecha_emision, CuentaPorCobrarOtro.id_cuenta
        )
        total_general = to_decimal(
            session.query(func.coalesce(func.sum(CuentaPorCobrarOtro.saldo_pendiente), 0)).filter(*filtros).scalar()
        )

        filas = [
            {
                "id_cuenta": cuenta.id_cuenta,
                "cliente": (cuenta.cliente.nombre_razon_social if cuenta.cliente else None),
                "descripcion": cuenta.descripcion,
                "fecha_emision": cuenta.fecha_emision,
                "fecha_vencimiento": cuenta.fecha_vencimiento,
                "monto_total": cuenta.monto_total,
                "saldo_pendiente": cuenta.saldo_pendiente,
                "estado": cuenta.estado,
            }
            for cuenta in cuentas
        ]
        return {
            "filas": filas,
            "paginacion": paginacion,
            "total_general": total_general,
        }

    # ── Tesoreria ─────────────────────────────────────────────────────────

    @staticmethod
    def movimientos_caja_periodo(
        session: Session,
        id_usuario: int | None,
        fecha_desde: date,
        fecha_hasta: date,
        id_caja: int | None = None,
        tipo_movimiento: str | None = None,
        pagina: int | None = None,
        por_pagina: int = POR_PAGINA_REPORTE,
    ) -> dict:
        """Movimientos de caja del rango. Con `pagina=None` devuelve todas las filas (lo que usa la exportacion); con
        `pagina`, solo esa pagina (ver `paginacion`). Los totales son siempre los de todo el filtro."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        if tipo_movimiento is not None and tipo_movimiento not in TIPOS_MOVIMIENTO_CAJA:
            raise ValueError(f"tipo_movimiento invalido: {tipo_movimiento!r}, debe ser uno de {TIPOS_MOVIMIENTO_CAJA}")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        filtros = [CajaMovimiento.fecha_registro >= desde_dt, CajaMovimiento.fecha_registro <= hasta_dt]
        if id_caja is not None:
            filtros.append(CajaMovimiento.id_caja == id_caja)
        if tipo_movimiento is not None:
            filtros.append(CajaMovimiento.tipo_movimiento == tipo_movimiento)
        query = session.query(CajaMovimiento).options(joinedload(CajaMovimiento.caja)).filter(*filtros)
        orden = (CajaMovimiento.fecha_registro, CajaMovimiento.id_movimiento)
        paginacion = None
        if pagina is None:
            movimientos = query.order_by(*orden).all()
        else:
            resultado_pagina = paginar(query, pagina, por_pagina, *orden)
            movimientos = resultado_pagina["items"]
            paginacion = {k: v for k, v in resultado_pagina.items() if k != "items"}

        def _origen(m: CajaMovimiento) -> str:
            if m.id_pago_cobro is not None or m.id_pago_cobro_bcv is not None:
                return "Cobro"
            if m.id_pago_proveedor is not None:
                return "Pago Proveedor"
            if m.id_pago_comision is not None:
                return "Pago Comisión"
            return "Manual"

        filas = [
            {
                "fecha_registro": m.fecha_registro,
                "caja": m.caja.nombre_caja if m.caja else None,
                "tipo_movimiento": m.tipo_movimiento,
                "descripcion_movimiento": m.descripcion_movimiento,
                "origen": _origen(m),
                "monto_movimiento": m.monto_movimiento,
            }
            for m in movimientos
        ]
        # Los totales se suman en la base sobre todo el filtro (no sobre la pagina que se muestra).
        entradas_sql, salidas_sql = (
            session.query(
                func.coalesce(
                    func.sum(
                        case((CajaMovimiento.tipo_movimiento == "entrada", CajaMovimiento.monto_movimiento), else_=0)
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case((CajaMovimiento.tipo_movimiento == "salida", CajaMovimiento.monto_movimiento), else_=0)
                    ),
                    0,
                ),
            )
            .filter(*filtros)
            .one()
        )
        total_entradas = to_decimal(entradas_sql)
        total_salidas = to_decimal(salidas_sql)
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "paginacion": paginacion,
            "total_entradas": total_entradas,
            "total_salidas": total_salidas,
            "neto": total_entradas - total_salidas,
        }

    @staticmethod
    def cierre_diario_por_cajero(
        session: Session,
        id_usuario: int | None,
        fecha_desde: date,
        fecha_hasta: date,
        id_usuario_cajero: int | None = None,
    ) -> dict:
        """Historico de turnos de caja (una fila = un turno, ver Caja) filtrados por fecha
        de apertura. Mismo calculo de saldo esperado que
        CajaService.calcular_saldo_actual() (tesoreria.py) pero para turnos ya cerrados:
        las entradas/salidas de caja_movimientos se agregan por id_caja (cada turno es una
        fila propia de la tabla Caja), sin necesidad de filtrar por fecha dentro del
        agregado."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        def _filtros_turnos(query):
            query = query.filter(Caja.fecha_apertura.isnot(None)).filter(
                Caja.fecha_apertura >= desde_dt, Caja.fecha_apertura <= hasta_dt
            )
            if id_usuario_cajero is not None:
                query = query.filter(Caja.id_usuario == id_usuario_cajero)
            return query

        turnos = (
            _filtros_turnos(session.query(Caja).options(joinedload(Caja.usuario))).order_by(Caja.fecha_apertura).all()
        )

        # Entradas/salidas de todos los turnos en una sola consulta (antes una por turno).
        totales: dict[tuple[int, str], Decimal] = {
            (id_caja, tipo): to_decimal(monto)
            for id_caja, tipo, monto in _filtros_turnos(
                session.query(
                    CajaMovimiento.id_caja, CajaMovimiento.tipo_movimiento, func.sum(CajaMovimiento.monto_movimiento)
                ).join(Caja, Caja.id_caja == CajaMovimiento.id_caja)
            )
            .group_by(CajaMovimiento.id_caja, CajaMovimiento.tipo_movimiento)
            .all()
        }

        filas = []
        for caja in turnos:
            total_entradas = totales.get((caja.id_caja, "entrada"), Decimal("0.00"))
            total_salidas = totales.get((caja.id_caja, "salida"), Decimal("0.00"))
            saldo_apertura = caja.saldo_apertura or Decimal("0.00")
            saldo_esperado = saldo_apertura + total_entradas - total_salidas
            diferencia = (caja.saldo_cierre - saldo_esperado) if caja.saldo_cierre is not None else None
            filas.append(
                {
                    "id_caja": caja.id_caja,
                    "caja": caja.nombre_caja,
                    "cajero": caja.usuario.nombre_usuario if caja.usuario else None,
                    "fecha_apertura": caja.fecha_apertura,
                    "fecha_cierre": caja.fecha_cierre,
                    "saldo_apertura": saldo_apertura,
                    "total_entradas": total_entradas,
                    "total_salidas": total_salidas,
                    "saldo_esperado": saldo_esperado,
                    "saldo_cierre": caja.saldo_cierre,
                    "diferencia": diferencia,
                }
            )
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "total_turnos": len(filas),
        }

    @staticmethod
    def flujo_caja_consolidado(
        session: Session,
        id_usuario: int | None,
        fecha_desde: date,
        fecha_hasta: date,
        agrupacion: str = "dia",
    ) -> dict:
        """Consolida caja_movimientos y banco_movimientos por periodo. Direccion de
        banco_movimientos: entrada si tipo_movimiento in ('abono','deposito'), salida en
        cualquier otro caso ('cargo','transferencia') -- exactamente el CASE de
        trg_banco_movimientos_saldo (schema_sqlserver.sql:1273), no una suposicion propia.
        """
        require_permiso(session, id_usuario, "reportes", "ver")
        if agrupacion not in ("dia", "mes"):
            raise ValueError("agrupacion debe ser 'dia' o 'mes'")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        def _fila_vacia(periodo: date) -> dict:
            return {
                "periodo": periodo,
                "entradas_caja": Decimal("0.00"),
                "salidas_caja": Decimal("0.00"),
                "entradas_banco": Decimal("0.00"),
                "salidas_banco": Decimal("0.00"),
            }

        # Se suma en la base de datos (una fila por periodo y direccion), no en Python sobre cada movimiento.
        periodo_caja = _periodo_sql(CajaMovimiento.fecha_registro, agrupacion)
        periodo_banco = _periodo_sql(BancoMovimiento.fecha_movimiento, agrupacion)
        entra_caja = CajaMovimiento.tipo_movimiento == "entrada"
        entra_banco = BancoMovimiento.tipo_movimiento.in_(("abono", "deposito"))
        caja_por_periodo = (
            session.query(
                periodo_caja,
                func.sum(case((entra_caja, CajaMovimiento.monto_movimiento), else_=0)),
                func.sum(case((entra_caja, 0), else_=CajaMovimiento.monto_movimiento)),
            )
            .filter(CajaMovimiento.fecha_registro >= desde_dt, CajaMovimiento.fecha_registro <= hasta_dt)
            .group_by(periodo_caja)
            .all()
        )
        banco_por_periodo = (
            session.query(
                periodo_banco,
                func.sum(case((entra_banco, BancoMovimiento.monto_movimiento), else_=0)),
                func.sum(case((entra_banco, 0), else_=BancoMovimiento.monto_movimiento)),
            )
            .filter(BancoMovimiento.fecha_movimiento >= desde_dt, BancoMovimiento.fecha_movimiento <= hasta_dt)
            .group_by(periodo_banco)
            .all()
        )

        por_periodo: dict[date, dict] = {}
        for periodo, entradas, salidas in caja_por_periodo:
            fila = por_periodo.setdefault(periodo, _fila_vacia(periodo))
            fila["entradas_caja"] += to_decimal(entradas)
            fila["salidas_caja"] += to_decimal(salidas)
        for periodo, entradas, salidas in banco_por_periodo:
            fila = por_periodo.setdefault(periodo, _fila_vacia(periodo))
            fila["entradas_banco"] += to_decimal(entradas)
            fila["salidas_banco"] += to_decimal(salidas)

        filas = sorted(por_periodo.values(), key=lambda f: f["periodo"])
        for fila in filas:
            fila["neto"] = fila["entradas_caja"] + fila["entradas_banco"] - fila["salidas_caja"] - fila["salidas_banco"]

        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "agrupacion": agrupacion,
            "filas": filas,
            "total_entradas": sum(
                (f["entradas_caja"] + f["entradas_banco"] for f in filas),
                Decimal("0.00"),
            ),
            "total_salidas": sum((f["salidas_caja"] + f["salidas_banco"] for f in filas), Decimal("0.00")),
        }

    # ── CxP ───────────────────────────────────────────────────────────────

    @staticmethod
    def estado_cuenta_proveedor(
        session: Session,
        id_usuario: int | None,
        id_proveedor: int,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
    ) -> dict:
        """Espejo de estado_cuenta_cliente del lado de lo que la empresa le debe a un
        proveedor: cargos (compras a credito) y abonos (pagos aplicados) en orden
        cronologico con saldo corrido."""
        require_permiso(session, id_usuario, "reportes", "ver")
        proveedor = session.get(Proveedor, id_proveedor)
        if proveedor is None:
            raise ValueError("Proveedor no encontrado")
        if fecha_desde is not None and fecha_hasta is not None and fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")

        cuentas = (
            session.query(CuentaPorPagar)
            .join(Compra, Compra.id_compra == CuentaPorPagar.id_compra)
            .options(joinedload(CuentaPorPagar.compra))
            .filter(Compra.id_proveedor == id_proveedor)
            .all()
        )
        pagos = (
            session.query(PagoProveedor)
            .join(
                CuentaPorPagar,
                CuentaPorPagar.id_cuenta == PagoProveedor.id_cuenta_por_pagar,
            )
            .join(Compra, Compra.id_compra == CuentaPorPagar.id_compra)
            .filter(Compra.id_proveedor == id_proveedor)
            .options(joinedload(PagoProveedor.cuenta_por_pagar).joinedload(CuentaPorPagar.compra))
            .all()
        )

        pagos_por_cuenta: dict[int, Decimal] = {}  # una sola pasada: recorrer los pagos por cada cuenta era cuadratico
        for p in pagos:
            pagos_por_cuenta[p.id_cuenta_por_pagar] = (
                pagos_por_cuenta.get(p.id_cuenta_por_pagar, Decimal("0.00")) + p.monto
            )

        eventos = []
        for cuenta in cuentas:
            pagos_de_cuenta = pagos_por_cuenta.get(cuenta.id_cuenta, Decimal("0.00"))
            eventos.append(
                {
                    "fecha": cuenta.compra.fecha_emision,
                    "tipo": "Compra",
                    "referencia": cuenta.compra.numero_compra,
                    "cargo": cuenta.saldo_pendiente + pagos_de_cuenta,
                    "abono": Decimal("0.00"),
                }
            )
        for pago in pagos:
            eventos.append(
                {
                    "fecha": pago.fecha_pago,
                    "tipo": "Pago",
                    "referencia": pago.referencia or pago.cuenta_por_pagar.compra.numero_compra,
                    "cargo": Decimal("0.00"),
                    "abono": pago.monto,
                }
            )
        eventos.sort(key=lambda e: e["fecha"])

        desde_dt = datetime.combine(fecha_desde, time.min) if fecha_desde else None
        hasta_dt = datetime.combine(fecha_hasta, time.max) if fecha_hasta else None

        saldo_inicial = Decimal("0.00")
        for evento in eventos:
            if desde_dt is not None and evento["fecha"] < desde_dt:
                saldo_inicial += evento["cargo"] - evento["abono"]

        saldo = saldo_inicial
        filas = []
        for evento in eventos:
            if desde_dt is not None and evento["fecha"] < desde_dt:
                continue
            if hasta_dt is not None and evento["fecha"] > hasta_dt:
                continue
            saldo += evento["cargo"] - evento["abono"]
            filas.append({**evento, "saldo": saldo})

        return {
            "id_proveedor": proveedor.id_proveedor,
            "proveedor": proveedor.nombre_razon_social,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "saldo_inicial": saldo_inicial,
            "filas": filas,
            "saldo_final": saldo,
        }

    @staticmethod
    def pagos_del_periodo(
        session: Session,
        id_usuario: int | None,
        fecha_desde: date,
        fecha_hasta: date,
        id_proveedor: int | None = None,
        pagina: int | None = None,
        por_pagina: int = POR_PAGINA_REPORTE,
    ) -> dict:
        """Pagos a proveedores del rango. Con `pagina=None` devuelve todas las filas (la exportacion); con `pagina`,
        solo esa (ver `paginacion`). Los totales son siempre los de todo el filtro."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        filtros = [PagoProveedor.fecha_pago >= desde_dt, PagoProveedor.fecha_pago <= hasta_dt]
        if id_proveedor is not None:
            filtros.append(Compra.id_proveedor == id_proveedor)

        def con_compra(consulta):
            return (
                consulta.join(CuentaPorPagar, CuentaPorPagar.id_cuenta == PagoProveedor.id_cuenta_por_pagar)
                .join(Compra, Compra.id_compra == CuentaPorPagar.id_compra)
                .filter(*filtros)
            )

        query = con_compra(session.query(PagoProveedor)).options(
            joinedload(PagoProveedor.cuenta_por_pagar).joinedload(CuentaPorPagar.compra).joinedload(Compra.proveedor)
        )
        pagos, paginacion = _pagina_o_todo(
            query, pagina, por_pagina, PagoProveedor.fecha_pago, PagoProveedor.id_pago_proveedor
        )
        totales_por_metodo = {
            metodo: to_decimal(total)
            for metodo, total in con_compra(
                session.query(PagoProveedor.metodo_pago, func.sum(PagoProveedor.monto))
            ).group_by(PagoProveedor.metodo_pago)
        }

        filas = []
        for pago in pagos:
            compra = pago.cuenta_por_pagar.compra
            filas.append(
                {
                    "fecha_pago": pago.fecha_pago,
                    "proveedor": (compra.proveedor.nombre_razon_social if compra.proveedor else None),
                    "numero_compra": compra.numero_compra,
                    "metodo_pago": pago.metodo_pago,
                    "monto": pago.monto,
                }
            )
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "paginacion": paginacion,
            "totales_por_metodo": totales_por_metodo,
            "total_general": sum(totales_por_metodo.values(), Decimal("0.00")),
        }

    @staticmethod
    def proximos_vencimientos(
        session: Session,
        id_usuario: int | None,
        dias_horizonte: int = 30,
        id_proveedor: int | None = None,
        pagina: int | None = None,
        por_pagina: int = POR_PAGINA_REPORTE,
    ) -> dict:
        """Cuentas por pagar que vencen en el horizonte. Con `pagina=None` devuelve todas las filas (la exportacion);
        con `pagina`, solo esa (ver `paginacion`). El total es siempre el de todo el filtro."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if dias_horizonte < 0:
            raise ValueError("dias_horizonte no puede ser negativo")
        hoy = date.today()
        limite = hoy + timedelta(days=dias_horizonte)

        filtros = [
            CuentaPorPagar.estado.in_(ESTADOS_CXP_ABIERTOS),
            CuentaPorPagar.fecha_vencimiento.isnot(None),
            CuentaPorPagar.fecha_vencimiento >= hoy,
            CuentaPorPagar.fecha_vencimiento <= limite,
        ]
        if id_proveedor is not None:
            filtros.append(Compra.id_proveedor == id_proveedor)
        query = (
            session.query(CuentaPorPagar)
            .join(Compra, Compra.id_compra == CuentaPorPagar.id_compra)
            .options(joinedload(CuentaPorPagar.compra).joinedload(Compra.proveedor))
            .filter(*filtros)
        )
        cuentas, paginacion = _pagina_o_todo(
            query, pagina, por_pagina, CuentaPorPagar.fecha_vencimiento, CuentaPorPagar.id_cuenta
        )
        total_general = to_decimal(
            session.query(func.coalesce(func.sum(CuentaPorPagar.saldo_pendiente), 0))
            .join(Compra, Compra.id_compra == CuentaPorPagar.id_compra)
            .filter(*filtros)
            .scalar()
        )

        filas = [
            {
                "numero_compra": cuenta.compra.numero_compra,
                "proveedor": (cuenta.compra.proveedor.nombre_razon_social if cuenta.compra.proveedor else None),
                "fecha_vencimiento": cuenta.fecha_vencimiento,
                "dias_para_vencer": (cuenta.fecha_vencimiento - hoy).days,
                "saldo_pendiente": cuenta.saldo_pendiente,
            }
            for cuenta in cuentas
        ]
        return {
            "fecha_corte": hoy,
            "dias_horizonte": dias_horizonte,
            "filas": filas,
            "paginacion": paginacion,
            "total_general": total_general,
        }

    @staticmethod
    def cxp_otras(
        session: Session,
        id_usuario: int | None,
        id_cuenta_bancaria: int | None = None,
        estado: str | None = None,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
        pagina: int | None = None,
        por_pagina: int = POR_PAGINA_REPORTE,
    ) -> dict:
        """cuentas_por_pagar_otros pese al nombre no son pasivos comerciales: son
        transferencias recibidas en una cuenta bancaria propia que aun no se han podido
        identificar/conciliar contra un cliente (ver docstring de CuentaPorPagarOtro en
        models.py). Comparte tabla con Bancos -> conciliacion_bancaria, pero con
        agregacion distinta: aca se lista el detalle filtrable por cuenta/estado/fecha,
        alla se resume por cuenta con totales pendiente vs conciliado. Con `pagina=None` devuelve todas las filas (la
        exportacion); con `pagina`, solo esa (ver `paginacion`). El total es siempre el de todo el filtro."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if estado is not None and estado not in ESTADOS_CXP_OTRO:
            raise ValueError(f"estado invalido: {estado!r}, debe ser uno de {ESTADOS_CXP_OTRO}")
        if fecha_desde is not None and fecha_hasta is not None and fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")

        filtros = []
        if id_cuenta_bancaria is not None:
            filtros.append(CuentaPorPagarOtro.id_cuenta_bancaria == id_cuenta_bancaria)
        if estado is not None:
            filtros.append(CuentaPorPagarOtro.estado == estado)
        if fecha_desde is not None:
            filtros.append(CuentaPorPagarOtro.fecha_recepcion >= datetime.combine(fecha_desde, time.min))
        if fecha_hasta is not None:
            filtros.append(CuentaPorPagarOtro.fecha_recepcion <= datetime.combine(fecha_hasta, time.max))
        query = (
            session.query(CuentaPorPagarOtro)
            .options(
                joinedload(CuentaPorPagarOtro.cuenta_bancaria),
                joinedload(CuentaPorPagarOtro.cliente_identificado),
            )
            .filter(*filtros)
        )
        cuentas, paginacion = _pagina_o_todo(
            query, pagina, por_pagina, CuentaPorPagarOtro.fecha_recepcion, CuentaPorPagarOtro.id_cuenta
        )
        total_general = to_decimal(
            session.query(func.coalesce(func.sum(CuentaPorPagarOtro.saldo_pendiente), 0)).filter(*filtros).scalar()
        )

        filas = [
            {
                "id_cuenta": cuenta.id_cuenta,
                "cuenta_bancaria": (cuenta.cuenta_bancaria.numero_cuenta if cuenta.cuenta_bancaria else None),
                "referencia_bancaria": cuenta.referencia_bancaria,
                "descripcion": cuenta.descripcion,
                "fecha_recepcion": cuenta.fecha_recepcion,
                "cliente_identificado": (
                    cuenta.cliente_identificado.nombre_razon_social if cuenta.cliente_identificado else None
                ),
                "monto_total": cuenta.monto_total,
                "saldo_pendiente": cuenta.saldo_pendiente,
                "estado": cuenta.estado,
            }
            for cuenta in cuentas
        ]
        return {
            "filas": filas,
            "paginacion": paginacion,
            "total_general": total_general,
        }

    # ── Bancos ────────────────────────────────────────────────────────────

    @staticmethod
    def movimientos_cuenta_bancaria(
        session: Session,
        id_usuario: int | None,
        id_cuenta_bancaria: int,
        fecha_desde: date,
        fecha_hasta: date,
        pagina: int | None = None,
        por_pagina: int = POR_PAGINA_REPORTE,
    ) -> dict:
        """Movimientos de una cuenta en el rango, con el saldo corrido de cada uno. Con `pagina=None` devuelve todas
        las filas (lo que usa la exportacion); con `pagina`, solo esa pagina (ver `paginacion`).

        El saldo inicial y el saldo corrido se calculan en la base (suma anterior al rango y suma acumulada con una
        funcion de ventana): ya no se trae a Python todo el historial de la cuenta."""
        require_permiso(session, id_usuario, "reportes", "ver")
        cuenta = session.get(CuentaBancaria, id_cuenta_bancaria)
        if cuenta is None:
            raise ValueError("Cuenta bancaria no encontrada")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        # Direccion: entrada si tipo_movimiento in ('abono','deposito'), salida en
        # cualquier otro caso -- mismo CASE que trg_banco_movimientos_saldo
        # (schema_sqlserver.sql:1273), ver flujo_caja_consolidado.
        monto = func.coalesce(BancoMovimiento.monto_movimiento, 0)
        con_signo = case((BancoMovimiento.tipo_movimiento.in_(("abono", "deposito")), monto), else_=-monto)

        saldo_inicial = to_decimal(
            session.query(func.coalesce(func.sum(con_signo), 0))
            .filter(BancoMovimiento.id_cuenta == id_cuenta_bancaria, BancoMovimiento.fecha_movimiento < desde_dt)
            .scalar()
        )
        en_el_rango = [
            BancoMovimiento.id_cuenta == id_cuenta_bancaria,
            BancoMovimiento.fecha_movimiento >= desde_dt,
            BancoMovimiento.fecha_movimiento <= hasta_dt,
        ]
        neto_del_rango = to_decimal(session.query(func.coalesce(func.sum(con_signo), 0)).filter(*en_el_rango).scalar())

        orden = (BancoMovimiento.fecha_movimiento, BancoMovimiento.id_movimiento)
        acumulado = (
            session.query(
                BancoMovimiento.id_movimiento.label("id_movimiento"),
                func.sum(con_signo).over(order_by=orden).label("acumulado"),
            )
            .filter(*en_el_rango)
            .subquery()
        )
        query = (
            session.query(BancoMovimiento, acumulado.c.acumulado)
            .join(acumulado, acumulado.c.id_movimiento == BancoMovimiento.id_movimiento)
            .filter(*en_el_rango)
        )
        paginacion = None
        if pagina is None:
            registros = query.order_by(*orden).all()
        else:
            resultado_pagina = paginar(query, pagina, por_pagina, *orden)
            registros = resultado_pagina["items"]
            paginacion = {k: v for k, v in resultado_pagina.items() if k != "items"}

        filas = [
            {
                "fecha_movimiento": m.fecha_movimiento,
                "tipo_movimiento": m.tipo_movimiento,
                "referencia_movimiento": m.referencia_movimiento,
                "descripcion_movimiento": m.descripcion_movimiento,
                "monto_movimiento": m.monto_movimiento or Decimal("0.00"),
                "saldo": saldo_inicial + to_decimal(corrido),
            }
            for m, corrido in registros
        ]
        return {
            "id_cuenta": cuenta.id_cuenta,
            "numero_cuenta": cuenta.numero_cuenta,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "saldo_inicial": saldo_inicial,
            "filas": filas,
            "paginacion": paginacion,
            "saldo_final": saldo_inicial + neto_del_rango,
        }

    @staticmethod
    def conciliacion_bancaria(
        session: Session,
        id_usuario: int | None,
        id_cuenta_bancaria: int | None = None,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
    ) -> dict:
        """Resumen de conciliacion bancaria por cuenta: cuanto de las transferencias
        recibidas sin identificar (CuentaPorPagarOtro, ver docstring en models.py) sigue
        pendiente vs ya se concilio contra un cliente. Mismo universo de datos que
        cxp_otras (modulo CxP), pero agregado por cuenta bancaria en vez de listado por
        partida -- 'parcial' cuenta como pendiente (saldo_pendiente ya refleja lo que
        falta conciliar de esa partida)."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde is not None and fecha_hasta is not None and fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")

        # Se agrupa y suma en la base de datos (una fila por cuenta bancaria), no en Python sobre cada partida.
        conciliada = CuentaPorPagarOtro.estado == "conciliado"
        total_pendiente_sql = func.sum(case((conciliada, 0), else_=CuentaPorPagarOtro.saldo_pendiente))
        query = (
            session.query(
                CuentaPorPagarOtro.id_cuenta_bancaria,
                CuentaBancaria.numero_cuenta,
                total_pendiente_sql,
                func.sum(case((conciliada, CuentaPorPagarOtro.monto_total), else_=0)),
                func.sum(case((conciliada, 0), else_=1)),
                func.sum(case((conciliada, 1), else_=0)),
            )
            .select_from(CuentaPorPagarOtro)
            .outerjoin(CuentaBancaria, CuentaBancaria.id_cuenta == CuentaPorPagarOtro.id_cuenta_bancaria)
        )
        if id_cuenta_bancaria is not None:
            query = query.filter(CuentaPorPagarOtro.id_cuenta_bancaria == id_cuenta_bancaria)
        if fecha_desde is not None:
            query = query.filter(CuentaPorPagarOtro.fecha_recepcion >= datetime.combine(fecha_desde, time.min))
        if fecha_hasta is not None:
            query = query.filter(CuentaPorPagarOtro.fecha_recepcion <= datetime.combine(fecha_hasta, time.max))
        agrupado = (
            query.group_by(CuentaPorPagarOtro.id_cuenta_bancaria, CuentaBancaria.numero_cuenta)
            .order_by(total_pendiente_sql.desc(), CuentaPorPagarOtro.id_cuenta_bancaria)
            .all()
        )
        filas = [
            {
                "id_cuenta_bancaria": id_cuenta,
                "numero_cuenta": numero,
                "total_pendiente": to_decimal(pendiente),
                "total_conciliado": to_decimal(conciliado_total),
                "cantidad_pendiente": int(n_pendientes),
                "cantidad_conciliada": int(n_conciliadas),
            }
            for id_cuenta, numero, pendiente, conciliado_total, n_pendientes, n_conciliadas in agrupado
        ]
        return {
            "filas": filas,
            "total_pendiente": sum((f["total_pendiente"] for f in filas), Decimal("0.00")),
            "total_conciliado": sum((f["total_conciliado"] for f in filas), Decimal("0.00")),
        }

    @staticmethod
    def saldo_consolidado(session: Session, id_usuario: int | None) -> dict:
        """Snapshot actual de saldos bancarios agrupado por banco. No reusa
        BancoService.obtener_resumen_cuentas() (tesoreria.py) porque ese metodo gatea con
        el permiso 'bancos'/'ver' propio -- este reporte, como los otros 20, gatea solo
        con 'reportes'/'ver'."""
        require_permiso(session, id_usuario, "reportes", "ver")
        cuentas = (
            session.query(CuentaBancaria)
            .options(joinedload(CuentaBancaria.banco))
            .filter(CuentaBancaria.estado_cuenta == "ACTIVO")
            .order_by(CuentaBancaria.id_cuenta)
            .all()
        )

        filas = []
        totales_por_banco: dict[str, Decimal] = {}
        for cuenta in cuentas:
            banco = cuenta.banco.nombre_banco if cuenta.banco else "Sin banco"
            saldo = cuenta.saldo_total_banco or Decimal("0.00")
            totales_por_banco[banco] = totales_por_banco.get(banco, Decimal("0.00")) + saldo
            filas.append(
                {
                    "banco": banco,
                    "numero_cuenta": cuenta.numero_cuenta,
                    "tipo_cuenta": cuenta.tipo_cuenta_banco,
                    "nombre_titular": cuenta.nombre_titular,
                    "saldo_actual": saldo,
                }
            )
        return {
            "filas": filas,
            "totales_por_banco": totales_por_banco,
            "total_general": sum(totales_por_banco.values(), Decimal("0.00")),
        }

    # ── Comisiones ────────────────────────────────────────────────────────

    @staticmethod
    def comisiones_por_vendedor_periodo(
        session: Session,
        id_usuario: int | None,
        fecha_desde: date,
        fecha_hasta: date,
        id_vendedor: int | None = None,
    ) -> dict:
        """Gerencial: usa 'reportes'/'ver' igual que los otros 20 reportes -- no el permiso
        separado 'reportes_comisiones'/'ver' que existe para la variante self-service
        'mis comisiones' de un vendedor (ComisionService.listar_mis_comisiones(),
        app/services/comisiones.py)."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        # Se agrupa y suma en la base de datos (una fila por vendedor), no en Python sobre cada comision.
        monto_sql = func.sum(func.coalesce(ComisionFactura.monto_comision, 0))
        query = (
            session.query(
                ComisionFactura.id_vendedor,
                Vendedor.nombre_vendedor,
                func.count(ComisionFactura.id_comision),
                monto_sql,
            )
            .select_from(ComisionFactura)
            .outerjoin(Vendedor, Vendedor.id_vendedor == ComisionFactura.id_vendedor)
            .filter(
                ComisionFactura.fecha_calculo >= desde_dt,
                ComisionFactura.fecha_calculo <= hasta_dt,
            )
        )
        if id_vendedor is not None:
            query = query.filter(ComisionFactura.id_vendedor == id_vendedor)
        agrupado = (
            query.group_by(ComisionFactura.id_vendedor, Vendedor.nombre_vendedor)
            .order_by(monto_sql.desc(), ComisionFactura.id_vendedor)
            .all()
        )
        filas = [
            {
                "id_vendedor": id_vend,
                "vendedor": nombre,
                "cantidad_facturas": cantidad,
                "monto_comision": to_decimal(monto),
            }
            for id_vend, nombre, cantidad, monto in agrupado
        ]
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "total_general": sum((f["monto_comision"] for f in filas), Decimal("0.00")),
        }

    @staticmethod
    def comisiones_pagadas_vs_pendientes(
        session: Session,
        id_usuario: int | None,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
        id_vendedor: int | None = None,
    ) -> dict:
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde is not None and fecha_hasta is not None and fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")

        # Se agrupa y suma en la base de datos (una fila por vendedor), no en Python sobre cada comision.
        monto = func.coalesce(ComisionFactura.monto_comision, 0)
        pagada = ComisionFactura.estado_pago == "pagada"
        liberada = ComisionFactura.estado_pago == "liberada"
        liberada_sql = func.sum(case((liberada, monto), else_=0))
        query = (
            session.query(
                ComisionFactura.id_vendedor,
                Vendedor.nombre_vendedor,
                func.sum(case((pagada, monto), else_=0)),
                liberada_sql,
                func.sum(case((pagada | liberada, 0), else_=monto)),
            )
            .select_from(ComisionFactura)
            .outerjoin(Vendedor, Vendedor.id_vendedor == ComisionFactura.id_vendedor)
        )
        if id_vendedor is not None:
            query = query.filter(ComisionFactura.id_vendedor == id_vendedor)
        if fecha_desde is not None:
            query = query.filter(ComisionFactura.fecha_calculo >= datetime.combine(fecha_desde, time.min))
        if fecha_hasta is not None:
            query = query.filter(ComisionFactura.fecha_calculo <= datetime.combine(fecha_hasta, time.max))
        agrupado = (
            query.group_by(ComisionFactura.id_vendedor, Vendedor.nombre_vendedor)
            .order_by(liberada_sql.desc(), ComisionFactura.id_vendedor)
            .all()
        )
        filas = [
            {
                "id_vendedor": id_vend,
                "vendedor": nombre,
                "pagado": to_decimal(pagado),
                "liberada": to_decimal(liberada_total),
                "pendiente": to_decimal(pendiente),
            }
            for id_vend, nombre, pagado, liberada_total, pendiente in agrupado
        ]
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "total_pagado": sum((f["pagado"] for f in filas), Decimal("0.00")),
            "total_liberada": sum((f["liberada"] for f in filas), Decimal("0.00")),
            "total_pendiente": sum((f["pendiente"] for f in filas), Decimal("0.00")),
        }
