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

from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    Auditoria,
    BancoMovimiento,
    Caja,
    CajaMovimiento,
    Cliente,
    ComisionFactura,
    Compra,
    CompraDetalle,
    CompraOC,
    CuentaBancaria,
    CuentaPorCobrar,
    CuentaPorCobrarOtro,
    CuentaPorPagar,
    CuentaPorPagarOtro,
    FacturaDetalle,
    FacturaVenta,
    Inventario,
    NotaCreditoCliente,
    NotaCreditoProveedor,
    NotaDevolucion,
    NotaDevolucionDetalle,
    NotaRecepcion,
    NotaRecepcionDetalle,
    PagoCobro,
    PagoProveedor,
    Proveedor,
    Vendedor,
)
from app.services.otros_movimientos import ESTADOS_CXC_OTRO
from app.services.permisos import require_permiso
from app.services.tesoreria import TIPOS_MOVIMIENTO_CAJA

logger = logging.getLogger(__name__)

ESTADOS_CXC_ABIERTOS = ("pendiente", "parcial", "vencida")
ESTADOS_CXP_ABIERTOS = ("pendiente", "parcial", "vencida")
ESTADOS_OC_ABIERTAS = ("PENDIENTE", "PARCIAL")
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


class ReporteService:
    @staticmethod
    def aging_cuentas_por_cobrar(
        session: Session,
        id_usuario: int | None,
        fecha_corte: date | None = None,
        id_cliente: int | None = None,
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
            .options(joinedload(CuentaPorCobrar.factura).joinedload(FacturaVenta.cliente))
            .filter(CuentaPorCobrar.estado.in_(ESTADOS_CXC_ABIERTOS))
        )
        if id_cliente:
            query = query.filter(FacturaVenta.id_cliente_factura == id_cliente)
        cuentas = query.order_by(_ORDEN_AGING_CXC[orden]).all()

        filas = []
        totales_por_bucket: dict[str, Decimal] = {}
        for cuenta in cuentas:
            dias_vencido = (fecha_corte - cuenta.fecha_vencimiento).days if cuenta.fecha_vencimiento else 0
            bucket = _bucket_aging(dias_vencido)
            totales_por_bucket[bucket] = totales_por_bucket.get(bucket, Decimal("0.00")) + cuenta.saldo_pendiente
            filas.append(
                {
                    "id_cuenta_por_cobrar": cuenta.id_cuenta_por_cobrar,
                    "numero_factura": cuenta.factura.numero_factura,
                    "cliente": cuenta.factura.cliente.nombre_razon_social if cuenta.factura.cliente else None,
                    "fecha_vencimiento": cuenta.fecha_vencimiento,
                    "saldo_pendiente": cuenta.saldo_pendiente,
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
            .filter(CuentaPorPagar.estado.in_(ESTADOS_CXP_ABIERTOS))
        )
        if id_proveedor:
            query = query.filter(Compra.id_proveedor == id_proveedor)
        cuentas = query.order_by(_ORDEN_AGING_CXP[orden]).all()

        filas = []
        totales_por_bucket: dict[str, Decimal] = {}
        for cuenta in cuentas:
            dias_vencido = (fecha_corte - cuenta.fecha_vencimiento).days if cuenta.fecha_vencimiento else 0
            bucket = _bucket_aging(dias_vencido)
            totales_por_bucket[bucket] = totales_por_bucket.get(bucket, Decimal("0.00")) + cuenta.saldo_pendiente
            filas.append(
                {
                    "id_cuenta": cuenta.id_cuenta,
                    "numero_compra": cuenta.compra.numero_compra,
                    "proveedor": cuenta.compra.proveedor.nombre_razon_social if cuenta.compra.proveedor else None,
                    "fecha_vencimiento": cuenta.fecha_vencimiento,
                    "saldo_pendiente": cuenta.saldo_pendiente,
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
    ) -> dict:
        """Libro de Ventas para el IVA (base del formato exigido por el SENIAT): detalle
        de facturas emitidas (excluye ANULADA) en el rango, con base imponible y monto de
        IVA desglosados por factura, mas las notas de credito emitidas en el mismo rango
        (se listan aparte, ver nota del modulo sobre por que no se restan del IVA)."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        query = (
            session.query(FacturaVenta)
            .options(joinedload(FacturaVenta.cliente))
            .filter(FacturaVenta.estado_factura != "ANULADA")
            .filter(FacturaVenta.fecha_emision >= desde_dt)
            .filter(FacturaVenta.fecha_emision <= hasta_dt)
        )
        if id_cliente:
            query = query.filter(FacturaVenta.id_cliente_factura == id_cliente)
        facturas = query.order_by(FacturaVenta.fecha_emision, FacturaVenta.numero_control).all()

        filas = []
        total_base = Decimal("0.00")
        total_iva = Decimal("0.00")
        for factura in facturas:
            base_imponible = factura.total_venta - factura.monto_descuento
            total = base_imponible + factura.monto_iva
            total_base += base_imponible
            total_iva += factura.monto_iva
            filas.append(
                {
                    "fecha_emision": factura.fecha_emision,
                    "numero_control": factura.numero_control,
                    "numero_factura": factura.numero_factura,
                    "cliente": factura.cliente.nombre_razon_social if factura.cliente else None,
                    "identificacion_cliente": factura.cliente.identificacion_cliente if factura.cliente else None,
                    "base_imponible": base_imponible,
                    "porcentaje_iva": factura.porcentaje_iva_aplicado,
                    "monto_iva": factura.monto_iva,
                    "total": total,
                }
            )

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
                "identificacion_cliente": nc.cliente.identificacion_cliente if nc.cliente else None,
                "monto": nc.monto,
                "motivo": nc.motivo,
            }
            for nc in notas_credito
        ]

        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "total_base_imponible": total_base,
            "total_iva": total_iva,
            "total_general": total_base + total_iva,
            "notas_credito": filas_nc,
            "total_notas_credito": sum((nc["monto"] for nc in filas_nc), Decimal("0.00")),
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

        facturas = (
            session.query(FacturaVenta)
            .filter(FacturaVenta.estado_factura != "ANULADA")
            .filter(FacturaVenta.fecha_emision >= desde_dt)
            .filter(FacturaVenta.fecha_emision <= hasta_dt)
            .all()
        )

        grupos: dict[date, dict] = {}
        for factura in facturas:
            total_factura = factura.total_venta - factura.monto_descuento + factura.monto_iva
            fecha = factura.fecha_emision.date()
            clave = fecha if agrupacion == "dia" else fecha.replace(day=1)
            grupo = grupos.setdefault(clave, {"fecha": clave, "cantidad_facturas": 0, "total": Decimal("0.00")})
            grupo["cantidad_facturas"] += 1
            grupo["total"] += total_factura

        filas = sorted(grupos.values(), key=lambda g: g["fecha"])
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

        facturas = (
            session.query(FacturaVenta)
            .options(joinedload(FacturaVenta.cliente))
            .filter(FacturaVenta.estado_factura != "ANULADA")
            .filter(FacturaVenta.fecha_emision >= desde_dt)
            .filter(FacturaVenta.fecha_emision <= hasta_dt)
            .all()
        )

        grupos: dict[int, dict] = {}
        for factura in facturas:
            total_factura = factura.total_venta - factura.monto_descuento + factura.monto_iva
            grupo = grupos.setdefault(
                factura.id_cliente_factura,
                {
                    "cliente": factura.cliente.nombre_razon_social if factura.cliente else None,
                    "cantidad_facturas": 0,
                    "total": Decimal("0.00"),
                },
            )
            grupo["cantidad_facturas"] += 1
            grupo["total"] += total_factura

        filas = sorted(grupos.values(), key=lambda g: g["total"], reverse=True)
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

        facturas = (
            session.query(FacturaVenta)
            .options(joinedload(FacturaVenta.vendedor))
            .filter(FacturaVenta.estado_factura != "ANULADA")
            .filter(FacturaVenta.fecha_emision >= desde_dt)
            .filter(FacturaVenta.fecha_emision <= hasta_dt)
            .all()
        )

        grupos: dict[int, dict] = {}
        for factura in facturas:
            total_factura = factura.total_venta - factura.monto_descuento + factura.monto_iva
            grupo = grupos.setdefault(
                factura.id_vendedor,
                {
                    "vendedor": factura.vendedor.nombre_vendedor if factura.vendedor else None,
                    "cantidad_facturas": 0,
                    "total": Decimal("0.00"),
                },
            )
            grupo["cantidad_facturas"] += 1
            grupo["total"] += total_factura

        for grupo in grupos.values():
            grupo["ticket_promedio"] = grupo["total"] / grupo["cantidad_facturas"]

        filas = sorted(grupos.values(), key=lambda g: g["total"], reverse=True)
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

        facturas = (
            session.query(FacturaVenta)
            .options(joinedload(FacturaVenta.vendedor).joinedload(Vendedor.ruta))
            .filter(FacturaVenta.estado_factura != "ANULADA")
            .filter(FacturaVenta.fecha_emision >= desde_dt)
            .filter(FacturaVenta.fecha_emision <= hasta_dt)
            .all()
        )

        grupos: dict[int | None, dict] = {}
        for factura in facturas:
            total_factura = factura.total_venta - factura.monto_descuento + factura.monto_iva
            ruta = factura.vendedor.ruta if factura.vendedor else None
            grupo = grupos.setdefault(
                ruta.id_ruta if ruta else None,
                {
                    "ruta": ruta.nombre_ruta if ruta else "Sin ruta",
                    "cantidad_facturas": 0,
                    "total": Decimal("0.00"),
                },
            )
            grupo["cantidad_facturas"] += 1
            grupo["total"] += total_factura

        for grupo in grupos.values():
            grupo["ticket_promedio"] = grupo["total"] / grupo["cantidad_facturas"]

        filas = sorted(grupos.values(), key=lambda g: g["total"], reverse=True)
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "total_general": sum((f["total"] for f in filas), Decimal("0.00")),
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

        query = (
            session.query(Cliente)
            .options(joinedload(Cliente.vendedor))
            .filter(Cliente.estado_cliente == "ACTIVO")
            .filter(Cliente.vendedor_cliente.isnot(None))
        )
        if id_vendedor is not None:
            query = query.filter(Cliente.vendedor_cliente == id_vendedor)
        clientes = query.order_by(Cliente.nombre_razon_social).all()

        ids_cliente = [c.id_cliente for c in clientes]
        conteo_facturas: dict[int, int] = {}
        if ids_cliente:
            facturas = (
                session.query(FacturaVenta.id_cliente_factura)
                .filter(FacturaVenta.id_cliente_factura.in_(ids_cliente))
                .filter(FacturaVenta.estado_factura != "ANULADA")
                .filter(FacturaVenta.fecha_emision >= desde_dt)
                .filter(FacturaVenta.fecha_emision <= hasta_dt)
                .all()
            )
            for (id_cliente,) in facturas:
                conteo_facturas[id_cliente] = conteo_facturas.get(id_cliente, 0) + 1

        filas = []
        for cliente in clientes:
            cantidad_facturas = conteo_facturas.get(cliente.id_cliente, 0)
            meta = cliente.vendedor.meta_activacion if cliente.vendedor else None
            efectividad_pct = round(cantidad_facturas / meta * 100, 2) if meta else None
            filas.append(
                {
                    "cliente": cliente.nombre_razon_social,
                    "vendedor": cliente.vendedor.nombre_vendedor if cliente.vendedor else None,
                    "cantidad_facturas": cantidad_facturas,
                    "meta_activacion": meta,
                    "efectividad_pct": efectividad_pct,
                    "activo": cantidad_facturas > 0,
                }
            )

        efectividades = [f["efectividad_pct"] for f in filas if f["efectividad_pct"] is not None]
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "total_clientes": len(filas),
            "total_activos": sum(1 for f in filas if f["activo"]),
            "efectividad_promedio": round(sum(efectividades) / len(efectividades), 2) if efectividades else None,
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

        detalles = (
            session.query(FacturaDetalle)
            .join(FacturaVenta, FacturaVenta.id_factura == FacturaDetalle.id_factura)
            .options(joinedload(FacturaDetalle.producto))
            .filter(FacturaVenta.estado_factura != "ANULADA")
            .filter(FacturaVenta.fecha_emision >= desde_dt)
            .filter(FacturaVenta.fecha_emision <= hasta_dt)
            .all()
        )

        grupos: dict[int, dict] = {}
        for detalle in detalles:
            grupo = grupos.setdefault(
                detalle.id_producto_factura,
                {
                    "producto": detalle.producto.nombre_producto if detalle.producto else detalle.descripcion,
                    "cantidad": Decimal("0.00"),
                    "total": Decimal("0.00"),
                },
            )
            grupo["cantidad"] += detalle.cantidad_producto
            grupo["total"] += detalle.cantidad_producto * detalle.precio_unitario

        filas = sorted(grupos.values(), key=lambda g: g["total"], reverse=(orden == "desc"))
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "orden": orden,
            "filas": filas,
            "total_general": sum((f["total"] for f in filas), Decimal("0.00")),
        }

    @staticmethod
    def facturas_anuladas(session: Session, id_usuario: int | None, fecha_desde: date, fecha_hasta: date) -> dict:
        """Listado de facturas ANULADA emitidas en el rango, con el motivo de anulacion
        (viene de Auditoria.detalle, la unica fuente que lo guarda -- FacturaVenta no
        tiene columna propia para eso). No incluye un monto: total_venta/monto_iva quedan
        en 0 despues de anular (el trigger de recalculo se dispara al borrar las lineas de
        factura_detalle, ver CLAUDE.md seccion de triggers) y no hay ningun otro lado
        donde el monto original haya quedado guardado -- mostrar un total aca seria
        inventar un dato que el sistema no conserva."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        facturas = (
            session.query(FacturaVenta)
            .options(joinedload(FacturaVenta.cliente), joinedload(FacturaVenta.vendedor))
            .filter(FacturaVenta.estado_factura == "ANULADA")
            .filter(FacturaVenta.fecha_emision >= desde_dt)
            .filter(FacturaVenta.fecha_emision <= hasta_dt)
            .order_by(FacturaVenta.fecha_emision)
            .all()
        )

        numeros = {f.numero_factura for f in facturas}
        motivos_por_factura: dict[str, str | None] = {}
        if numeros:
            eventos = (
                session.query(Auditoria)
                .filter(Auditoria.accion == "ANULACION_FACTURA")
                .filter(Auditoria.modulo == "VENTAS")
                .all()
            )
            for evento in eventos:
                try:
                    detalle = json.loads(evento.detalle) if evento.detalle else {}
                except (TypeError, ValueError):
                    continue
                numero = detalle.get("numero_factura")
                if numero in numeros:
                    motivos_por_factura[numero] = detalle.get("motivo")

        filas = [
            {
                "numero_factura": factura.numero_factura,
                "cliente": factura.cliente.nombre_razon_social if factura.cliente else None,
                "vendedor": factura.vendedor.nombre_vendedor if factura.vendedor else None,
                "fecha_emision": factura.fecha_emision,
                "motivo": motivos_por_factura.get(factura.numero_factura),
            }
            for factura in facturas
        ]
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
    ) -> dict:
        """Listado detallado de notas de credito de cliente emitidas en el rango (motivo,
        factura de origen, estado disponible/aplicada/devuelta) -- version standalone del
        resumen que libro_ventas() ya muestra como un solo chip agregado."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        query = (
            session.query(NotaCreditoCliente)
            .options(joinedload(NotaCreditoCliente.cliente), joinedload(NotaCreditoCliente.factura_origen))
            .filter(NotaCreditoCliente.fecha_creacion >= desde_dt)
            .filter(NotaCreditoCliente.fecha_creacion <= hasta_dt)
        )
        if id_cliente:
            query = query.filter(NotaCreditoCliente.id_cliente == id_cliente)
        notas = query.order_by(NotaCreditoCliente.fecha_creacion).all()

        filas = [
            {
                "numero_nota_credito": nota.numero_nota_credito,
                "cliente": nota.cliente.nombre_razon_social if nota.cliente else None,
                "numero_factura_origen": nota.factura_origen.numero_factura if nota.factura_origen else None,
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
            "total_general": sum((f["monto"] for f in filas), Decimal("0.00")),
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

        facturas = (
            session.query(FacturaVenta)
            .filter(FacturaVenta.estado_factura != "ANULADA")
            .filter(FacturaVenta.fecha_emision >= desde_dt)
            .filter(FacturaVenta.fecha_emision <= hasta_dt)
            .all()
        )

        resumen = {
            "contado": {"cantidad_facturas": 0, "total": Decimal("0.00")},
            "credito": {"cantidad_facturas": 0, "total": Decimal("0.00")},
        }
        for factura in facturas:
            total_factura = factura.total_venta - factura.monto_descuento + factura.monto_iva
            grupo = resumen.setdefault(factura.condicion_pago, {"cantidad_facturas": 0, "total": Decimal("0.00")})
            grupo["cantidad_facturas"] += 1
            grupo["total"] += total_factura

        total_general = sum((g["total"] for g in resumen.values()), Decimal("0.00"))
        filas = [
            {
                "condicion_pago": condicion,
                "cantidad_facturas": grupo["cantidad_facturas"],
                "total": grupo["total"],
                "porcentaje": (grupo["total"] / total_general * 100) if total_general else Decimal("0.00"),
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
        excluyendo ANULADA). Usa el costo ACTUAL de Inventario.costo_producto -- el schema
        no guarda un costo historico por linea de venta, asi que el margen de una venta
        vieja es una aproximacion si el costo del producto cambio desde entonces."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        detalles = (
            session.query(FacturaDetalle)
            .join(FacturaVenta, FacturaVenta.id_factura == FacturaDetalle.id_factura)
            .options(joinedload(FacturaDetalle.producto))
            .filter(FacturaVenta.estado_factura != "ANULADA")
            .filter(FacturaVenta.fecha_emision >= desde_dt)
            .filter(FacturaVenta.fecha_emision <= hasta_dt)
            .all()
        )

        grupos: dict[int, dict] = {}
        for detalle in detalles:
            costo_unitario = detalle.producto.costo_producto if detalle.producto else Decimal("0.00")
            grupo = grupos.setdefault(
                detalle.id_producto_factura,
                {
                    "producto": detalle.producto.nombre_producto if detalle.producto else detalle.descripcion,
                    "cantidad": Decimal("0.00"),
                    "ingreso": Decimal("0.00"),
                    "costo": Decimal("0.00"),
                },
            )
            grupo["cantidad"] += detalle.cantidad_producto
            grupo["ingreso"] += detalle.cantidad_producto * detalle.precio_unitario
            grupo["costo"] += detalle.cantidad_producto * costo_unitario

        filas = []
        for grupo in grupos.values():
            margen = grupo["ingreso"] - grupo["costo"]
            margen_pct = (margen / grupo["ingreso"] * 100) if grupo["ingreso"] else Decimal("0.00")
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

        compras = (
            session.query(Compra)
            .filter(Compra.estado_compra != "ANULADA")
            .filter(Compra.fecha_emision >= desde_dt)
            .filter(Compra.fecha_emision <= hasta_dt)
            .all()
        )

        grupos: dict[date, dict] = {}
        for compra in compras:
            fecha = compra.fecha_emision.date()
            clave = fecha if agrupacion == "dia" else fecha.replace(day=1)
            grupo = grupos.setdefault(clave, {"fecha": clave, "cantidad_compras": 0, "total": Decimal("0.00")})
            grupo["cantidad_compras"] += 1
            grupo["total"] += compra.total_compra

        filas = sorted(grupos.values(), key=lambda g: g["fecha"])
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

        compras = (
            session.query(Compra)
            .options(joinedload(Compra.proveedor))
            .filter(Compra.estado_compra != "ANULADA")
            .filter(Compra.fecha_emision >= desde_dt)
            .filter(Compra.fecha_emision <= hasta_dt)
            .all()
        )

        grupos: dict[int, dict] = {}
        for compra in compras:
            grupo = grupos.setdefault(
                compra.id_proveedor,
                {
                    "proveedor": compra.proveedor.nombre_razon_social if compra.proveedor else None,
                    "cantidad_compras": 0,
                    "total": Decimal("0.00"),
                },
            )
            grupo["cantidad_compras"] += 1
            grupo["total"] += compra.total_compra

        filas = sorted(grupos.values(), key=lambda g: g["total"], reverse=True)
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

        detalles = (
            session.query(CompraDetalle)
            .join(Compra, Compra.id_compra == CompraDetalle.id_compra)
            .options(joinedload(CompraDetalle.producto))
            .filter(Compra.estado_compra != "ANULADA")
            .filter(Compra.fecha_emision >= desde_dt)
            .filter(Compra.fecha_emision <= hasta_dt)
            .all()
        )

        grupos: dict[int, dict] = {}
        for detalle in detalles:
            grupo = grupos.setdefault(
                detalle.id_producto_compra,
                {
                    "producto": detalle.producto.nombre_producto if detalle.producto else detalle.descripcion,
                    "cantidad": Decimal("0.00"),
                    "total": Decimal("0.00"),
                },
            )
            grupo["cantidad"] += detalle.cantidad_producto
            grupo["total"] += detalle.cantidad_producto * detalle.costo_unitario

        filas = sorted(grupos.values(), key=lambda g: g["total"], reverse=(orden == "desc"))
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
        cantidad_oc pero quedan fuera de a_tiempo/tardias -- no hay con que compararlas."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        recepciones = (
            session.query(NotaRecepcion)
            .join(CompraOC, CompraOC.id_oc == NotaRecepcion.id_oc)
            .options(joinedload(NotaRecepcion.oc).joinedload(CompraOC.proveedor))
            .filter(NotaRecepcion.estado != "ANULADA")
            .filter(NotaRecepcion.fecha_recepcion >= desde_dt)
            .filter(NotaRecepcion.fecha_recepcion <= hasta_dt)
            .all()
        )

        ultima_recepcion_por_oc: dict[int, datetime] = {}
        ocs_por_id = {}
        for nr in recepciones:
            ocs_por_id[nr.id_oc] = nr.oc
            actual = ultima_recepcion_por_oc.get(nr.id_oc)
            if actual is None or nr.fecha_recepcion > actual:
                ultima_recepcion_por_oc[nr.id_oc] = nr.fecha_recepcion

        grupos: dict[int, dict] = {}
        for id_oc, fecha_ultima in ultima_recepcion_por_oc.items():
            oc = ocs_por_id[id_oc]
            grupo = grupos.setdefault(
                oc.id_proveedor,
                {
                    "proveedor": oc.proveedor.nombre_razon_social if oc.proveedor else None,
                    "cantidad_oc": 0,
                    "a_tiempo": 0,
                    "tardias": 0,
                    "sin_fecha_estimada": 0,
                },
            )
            grupo["cantidad_oc"] += 1
            if oc.fecha_estimada_entrega is None:
                grupo["sin_fecha_estimada"] += 1
            elif fecha_ultima.date() <= oc.fecha_estimada_entrega:
                grupo["a_tiempo"] += 1
            else:
                grupo["tardias"] += 1

        filas = []
        for grupo in grupos.values():
            evaluables = grupo["a_tiempo"] + grupo["tardias"]
            pct_a_tiempo = (Decimal(grupo["a_tiempo"]) / evaluables * 100) if evaluables else None
            filas.append({**grupo, "pct_a_tiempo": pct_a_tiempo})
        filas.sort(key=lambda f: f["cantidad_oc"], reverse=True)

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
    ) -> dict:
        """Listado de devoluciones a proveedor (nota_devolucion) emitidas en el rango, con
        motivo, cantidad y el proveedor/OC de origen (via nota_recepcion)."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        query = (
            session.query(NotaDevolucion)
            .join(NotaRecepcion, NotaRecepcion.id_nr == NotaDevolucion.id_nr)
            .join(CompraOC, CompraOC.id_oc == NotaRecepcion.id_oc)
            .options(
                joinedload(NotaDevolucion.nota_recepcion).joinedload(NotaRecepcion.oc).joinedload(CompraOC.proveedor)
            )
            .filter(NotaDevolucion.fecha_devolucion >= desde_dt)
            .filter(NotaDevolucion.fecha_devolucion <= hasta_dt)
        )
        if id_proveedor:
            query = query.filter(CompraOC.id_proveedor == id_proveedor)
        devoluciones = query.order_by(NotaDevolucion.fecha_devolucion).all()

        filas = [
            {
                "numero_nota_devolucion": d.numero_nota_devolucion,
                "proveedor": d.nota_recepcion.oc.proveedor.nombre_razon_social
                if d.nota_recepcion.oc.proveedor
                else None,
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
            "total_devoluciones": len(filas),
            "total_cantidad": sum((f["cantidad_total"] for f in filas), Decimal("0.00")),
        }

    @staticmethod
    def notas_credito_proveedor(
        session: Session,
        id_usuario: int | None,
        fecha_desde: date,
        fecha_hasta: date,
        id_proveedor: int | None = None,
    ) -> dict:
        """Listado de notas de credito de proveedor (saldo a favor de la empresa,
        generado al anular una compra con pagos ya aplicados) creadas en el rango. A
        diferencia de NotaCreditoCliente esta no es un documento fiscal correlativo -- ver
        el docstring de NotaCreditoProveedor en models.py."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        query = (
            session.query(NotaCreditoProveedor)
            .options(joinedload(NotaCreditoProveedor.proveedor), joinedload(NotaCreditoProveedor.compra_origen))
            .filter(NotaCreditoProveedor.fecha_creacion >= desde_dt)
            .filter(NotaCreditoProveedor.fecha_creacion <= hasta_dt)
        )
        if id_proveedor:
            query = query.filter(NotaCreditoProveedor.id_proveedor == id_proveedor)
        notas = query.order_by(NotaCreditoProveedor.fecha_creacion).all()

        filas = [
            {
                "id_nota_credito": nota.id_nota_credito,
                "proveedor": nota.proveedor.nombre_razon_social if nota.proveedor else None,
                "numero_compra_origen": nota.compra_origen.numero_compra if nota.compra_origen else None,
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
            "total_general": sum((f["monto"] for f in filas), Decimal("0.00")),
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
            (m.monto_movimiento for m in movimientos if m.tipo_movimiento == "entrada"), Decimal("0.00")
        )
        total_salidas = sum((m.monto_movimiento for m in movimientos if m.tipo_movimiento == "salida"), Decimal("0.00"))
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
        session: Session, id_usuario: int | None, id_producto: int, fecha_desde: date, fecha_hasta: date
    ) -> dict:
        """Reconstruye el historial de movimientos de stock de un producto: no existe una
        tabla de movimientos dedicada (el stock se mueve directamente sobre
        Inventario.cantidad_unidad via triggers), asi que se arma desde las 4 tablas de
        detalle que los disparan -- entradas: CompraDetalle (compra directa, sin OC, con
        stock_ya_contabilizado=False) y NotaRecepcionDetalle (recepcion de una OC);
        salidas: FacturaDetalle y NotaDevolucionDetalle (devolucion a proveedor) -- ver
        las direcciones de cada trigger en migrations/0032 (lineas 333-426) y
        schema_sqlserver.sql:894-1064. Una factura/compra ANULADA no necesita caso
        especial: sus filas de detalle se borran (revirtiendo el stock via trigger), asi
        que simplemente dejan de aparecer aca."""
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
                    "entrada": detalle.cantidad_recibida,
                    "salida": Decimal("0.00"),
                }
            )
        ventas = (
            session.query(FacturaDetalle, FacturaVenta)
            .join(FacturaVenta, FacturaDetalle.id_factura == FacturaVenta.id_factura)
            .filter(FacturaDetalle.id_producto_factura == id_producto)
            .all()
        )
        for detalle, factura in ventas:
            eventos.append(
                {
                    "fecha": factura.fecha_emision,
                    "tipo": "Venta",
                    "referencia": factura.numero_factura,
                    "entrada": Decimal("0.00"),
                    "salida": detalle.cantidad_producto,
                }
            )
        devoluciones = (
            session.query(NotaDevolucionDetalle, NotaDevolucion)
            .join(NotaDevolucion, NotaDevolucionDetalle.id_devolucion == NotaDevolucion.id_devolucion)
            .filter(NotaDevolucionDetalle.id_producto == id_producto)
            .all()
        )
        for detalle, nota in devoluciones:
            eventos.append(
                {
                    "fecha": nota.fecha_devolucion,
                    "tipo": "Devolución a Proveedor",
                    "referencia": nota.numero_nota_devolucion,
                    "entrada": Decimal("0.00"),
                    "salida": detalle.cantidad_devuelta,
                }
            )

        eventos.sort(key=lambda e: e["fecha"])
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        saldo_inicial = Decimal("0.00")
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
            valor = (producto.cantidad_unidad or Decimal("0.00")) * (producto.costo_producto or Decimal("0.00"))
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
        de migrations/0037), no 'minimo es cero unidades' -- esos productos se excluyen."""
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
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        ids_con_venta = {
            fila[0]
            for fila in session.query(FacturaDetalle.id_producto_factura)
            .join(FacturaVenta, FacturaDetalle.id_factura == FacturaVenta.id_factura)
            .filter(FacturaVenta.fecha_emision >= desde_dt, FacturaVenta.fecha_emision <= hasta_dt)
            .distinct()
            .all()
        }
        ids_con_compra = {
            fila[0]
            for fila in session.query(CompraDetalle.id_producto_compra)
            .join(Compra, CompraDetalle.id_compra == Compra.id_compra)
            .filter(Compra.fecha_emision >= desde_dt, Compra.fecha_emision <= hasta_dt)
            .distinct()
            .all()
        }
        ids_con_movimiento = ids_con_venta | ids_con_compra

        query = (
            session.query(Inventario)
            .options(joinedload(Inventario.categoria))
            .filter(Inventario.estado_producto == "ACTIVO")
        )
        if id_categoria is not None:
            query = query.filter(Inventario.id_categoria == id_categoria)
        if ids_con_movimiento:
            query = query.filter(~Inventario.id_producto.in_(ids_con_movimiento))
        productos = query.order_by(Inventario.nombre_producto).all()

        filas = []
        for producto in productos:
            ultima_venta = (
                session.query(FacturaVenta.fecha_emision)
                .join(FacturaDetalle, FacturaDetalle.id_factura == FacturaVenta.id_factura)
                .filter(FacturaDetalle.id_producto_factura == producto.id_producto)
                .order_by(FacturaVenta.fecha_emision.desc())
                .first()
            )
            ultima_compra = (
                session.query(Compra.fecha_emision)
                .join(CompraDetalle, CompraDetalle.id_compra == Compra.id_compra)
                .filter(CompraDetalle.id_producto_compra == producto.id_producto)
                .order_by(Compra.fecha_emision.desc())
                .first()
            )
            fechas = [f[0] for f in (ultima_venta, ultima_compra) if f and f[0] is not None]
            filas.append(
                {
                    "cod_producto": producto.cod_producto,
                    "nombre_producto": producto.nombre_producto,
                    "categoria": producto.categoria.nombre if producto.categoria else None,
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
        eventos = query.options(joinedload(Auditoria.usuario)).order_by(Auditoria.fecha_evento).all()

        filas = []
        for evento in eventos:
            try:
                detalle = json.loads(evento.detalle) if evento.detalle else {}
            except (TypeError, ValueError):
                continue
            if detalle.get("id_producto") != id_producto:
                continue
            filas.append(
                {
                    "fecha_evento": evento.fecha_evento,
                    "precio_venta": Decimal(detalle["precio_venta"]) if detalle.get("precio_venta") else None,
                    "porcentaje_ganancia": (
                        Decimal(detalle["porcentaje_ganancia"]) if detalle.get("porcentaje_ganancia") else None
                    ),
                    "usuario": evento.usuario.nombre_usuario if evento.usuario else None,
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
        """Estado de cuenta de un cliente: cargos (facturas a credito) y abonos (pagos
        aplicados) en orden cronologico con saldo corrido. El cargo original de cada
        factura se reconstruye como saldo_pendiente + pagos ya aplicados (CuentaPorCobrar
        no guarda el monto original, solo el saldo que va quedando). Sin fecha_desde/hasta
        muestra todo el historial (saldo_inicial=0); con rango, los movimientos previos a
        fecha_desde se pliegan en saldo_inicial, mismo criterio que kardex_producto."""
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
            .join(CuentaPorCobrar, CuentaPorCobrar.id_cuenta_por_cobrar == PagoCobro.id_cuenta_por_cobrar)
            .join(FacturaVenta, FacturaVenta.id_factura == CuentaPorCobrar.id_factura)
            .filter(FacturaVenta.id_cliente_factura == id_cliente)
            .options(joinedload(PagoCobro.cuenta_por_cobrar).joinedload(CuentaPorCobrar.factura))
            .all()
        )

        eventos = []
        for cuenta in cuentas:
            pagos_de_cuenta = sum(
                (p.monto for p in pagos if p.id_cuenta_por_cobrar == cuenta.id_cuenta_por_cobrar), Decimal("0.00")
            )
            eventos.append(
                {
                    "fecha": cuenta.factura.fecha_emision,
                    "tipo": "Factura",
                    "referencia": cuenta.factura.numero_factura,
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
    ) -> dict:
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        query = (
            session.query(PagoCobro)
            .join(CuentaPorCobrar, CuentaPorCobrar.id_cuenta_por_cobrar == PagoCobro.id_cuenta_por_cobrar)
            .join(FacturaVenta, FacturaVenta.id_factura == CuentaPorCobrar.id_factura)
            .options(
                joinedload(PagoCobro.cuenta_por_cobrar)
                .joinedload(CuentaPorCobrar.factura)
                .joinedload(FacturaVenta.cliente)
            )
            .filter(PagoCobro.fecha_pago >= desde_dt, PagoCobro.fecha_pago <= hasta_dt)
        )
        if id_cliente is not None:
            query = query.filter(FacturaVenta.id_cliente_factura == id_cliente)
        pagos = query.order_by(PagoCobro.fecha_pago).all()

        filas = []
        totales_por_metodo: dict[str, Decimal] = {}
        for pago in pagos:
            factura = pago.cuenta_por_cobrar.factura
            totales_por_metodo[pago.metodo_pago] = (
                totales_por_metodo.get(pago.metodo_pago, Decimal("0.00")) + pago.monto
            )
            filas.append(
                {
                    "fecha_pago": pago.fecha_pago,
                    "cliente": factura.cliente.nombre_razon_social if factura.cliente else None,
                    "numero_factura": factura.numero_factura,
                    "metodo_pago": pago.metodo_pago,
                    "moneda": pago.moneda,
                    "monto": pago.monto,
                }
            )
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "totales_por_metodo": totales_por_metodo,
            "total_general": sum((f["monto"] for f in filas), Decimal("0.00")),
        }

    @staticmethod
    def clientes_morosos(session: Session, id_usuario: int | None, fecha_corte: date | None = None) -> dict:
        """Agrupa por cliente las cuentas por cobrar abiertas y VENCIDAS (mismo universo que
        aging_cuentas_por_cobrar excluyendo el bucket 'vigente'), agregando saldo total
        vencido y antiguedad maxima por cliente en vez de por bucket."""
        require_permiso(session, id_usuario, "reportes", "ver")
        fecha_corte = fecha_corte or date.today()

        cuentas = (
            session.query(CuentaPorCobrar)
            .join(FacturaVenta, FacturaVenta.id_factura == CuentaPorCobrar.id_factura)
            .options(joinedload(CuentaPorCobrar.factura).joinedload(FacturaVenta.cliente))
            .filter(CuentaPorCobrar.estado.in_(ESTADOS_CXC_ABIERTOS))
            .all()
        )

        por_cliente: dict[int | None, dict] = {}
        for cuenta in cuentas:
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
            entrada["saldo_vencido"] += cuenta.saldo_pendiente
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
    ) -> dict:
        require_permiso(session, id_usuario, "reportes", "ver")
        if estado is not None and estado not in ESTADOS_CXC_OTRO:
            raise ValueError(f"estado invalido: {estado!r}, debe ser uno de {ESTADOS_CXC_OTRO}")
        if fecha_desde is not None and fecha_hasta is not None and fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")

        query = session.query(CuentaPorCobrarOtro).options(joinedload(CuentaPorCobrarOtro.cliente))
        if id_cliente is not None:
            query = query.filter(CuentaPorCobrarOtro.id_cliente == id_cliente)
        if estado is not None:
            query = query.filter(CuentaPorCobrarOtro.estado == estado)
        if fecha_desde is not None:
            query = query.filter(CuentaPorCobrarOtro.fecha_emision >= datetime.combine(fecha_desde, time.min))
        if fecha_hasta is not None:
            query = query.filter(CuentaPorCobrarOtro.fecha_emision <= datetime.combine(fecha_hasta, time.max))
        cuentas = query.order_by(CuentaPorCobrarOtro.fecha_emision).all()

        filas = [
            {
                "id_cuenta": cuenta.id_cuenta,
                "cliente": cuenta.cliente.nombre_razon_social if cuenta.cliente else None,
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
            "total_general": sum((f["saldo_pendiente"] for f in filas), Decimal("0.00")),
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
    ) -> dict:
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        if tipo_movimiento is not None and tipo_movimiento not in TIPOS_MOVIMIENTO_CAJA:
            raise ValueError(f"tipo_movimiento invalido: {tipo_movimiento!r}, debe ser uno de {TIPOS_MOVIMIENTO_CAJA}")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        query = (
            session.query(CajaMovimiento)
            .options(joinedload(CajaMovimiento.caja))
            .filter(CajaMovimiento.fecha_registro >= desde_dt, CajaMovimiento.fecha_registro <= hasta_dt)
        )
        if id_caja is not None:
            query = query.filter(CajaMovimiento.id_caja == id_caja)
        if tipo_movimiento is not None:
            query = query.filter(CajaMovimiento.tipo_movimiento == tipo_movimiento)
        movimientos = query.order_by(CajaMovimiento.fecha_registro).all()

        def _origen(m: CajaMovimiento) -> str:
            if m.id_pago_cobro is not None:
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
        total_entradas = sum(
            (f["monto_movimiento"] for f in filas if f["tipo_movimiento"] == "entrada"), Decimal("0.00")
        )
        total_salidas = sum((f["monto_movimiento"] for f in filas if f["tipo_movimiento"] == "salida"), Decimal("0.00"))
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
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

        query = (
            session.query(Caja)
            .options(joinedload(Caja.usuario))
            .filter(Caja.fecha_apertura.isnot(None))
            .filter(Caja.fecha_apertura >= desde_dt, Caja.fecha_apertura <= hasta_dt)
        )
        if id_usuario_cajero is not None:
            query = query.filter(Caja.id_usuario == id_usuario_cajero)
        turnos = query.order_by(Caja.fecha_apertura).all()

        filas = []
        for caja in turnos:
            movimientos = session.query(CajaMovimiento).filter(CajaMovimiento.id_caja == caja.id_caja).all()
            total_entradas = sum(
                (m.monto_movimiento for m in movimientos if m.tipo_movimiento == "entrada"), Decimal("0.00")
            )
            total_salidas = sum(
                (m.monto_movimiento for m in movimientos if m.tipo_movimiento == "salida"), Decimal("0.00")
            )
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
        trg_banco_movimientos_saldo (schema_sqlserver.sql:1273), no una suposicion propia."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if agrupacion not in ("dia", "mes"):
            raise ValueError("agrupacion debe ser 'dia' o 'mes'")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        def _periodo(fecha: datetime) -> date:
            return date(fecha.year, fecha.month, 1) if agrupacion == "mes" else fecha.date()

        def _fila_vacia(periodo: date) -> dict:
            return {
                "periodo": periodo,
                "entradas_caja": Decimal("0.00"),
                "salidas_caja": Decimal("0.00"),
                "entradas_banco": Decimal("0.00"),
                "salidas_banco": Decimal("0.00"),
            }

        movimientos_caja = (
            session.query(CajaMovimiento)
            .filter(CajaMovimiento.fecha_registro >= desde_dt, CajaMovimiento.fecha_registro <= hasta_dt)
            .all()
        )
        movimientos_banco = (
            session.query(BancoMovimiento)
            .filter(BancoMovimiento.fecha_movimiento >= desde_dt, BancoMovimiento.fecha_movimiento <= hasta_dt)
            .all()
        )

        por_periodo: dict[date, dict] = {}
        for m in movimientos_caja:
            fila = por_periodo.setdefault(_periodo(m.fecha_registro), _fila_vacia(_periodo(m.fecha_registro)))
            if m.tipo_movimiento == "entrada":
                fila["entradas_caja"] += m.monto_movimiento
            else:
                fila["salidas_caja"] += m.monto_movimiento
        for m in movimientos_banco:
            fila = por_periodo.setdefault(_periodo(m.fecha_movimiento), _fila_vacia(_periodo(m.fecha_movimiento)))
            if m.tipo_movimiento in ("abono", "deposito"):
                fila["entradas_banco"] += m.monto_movimiento
            else:
                fila["salidas_banco"] += m.monto_movimiento

        filas = sorted(por_periodo.values(), key=lambda f: f["periodo"])
        for fila in filas:
            fila["neto"] = fila["entradas_caja"] + fila["entradas_banco"] - fila["salidas_caja"] - fila["salidas_banco"]

        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "agrupacion": agrupacion,
            "filas": filas,
            "total_entradas": sum((f["entradas_caja"] + f["entradas_banco"] for f in filas), Decimal("0.00")),
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
            .join(CuentaPorPagar, CuentaPorPagar.id_cuenta == PagoProveedor.id_cuenta_por_pagar)
            .join(Compra, Compra.id_compra == CuentaPorPagar.id_compra)
            .filter(Compra.id_proveedor == id_proveedor)
            .options(joinedload(PagoProveedor.cuenta_por_pagar).joinedload(CuentaPorPagar.compra))
            .all()
        )

        eventos = []
        for cuenta in cuentas:
            pagos_de_cuenta = sum(
                (p.monto for p in pagos if p.id_cuenta_por_pagar == cuenta.id_cuenta), Decimal("0.00")
            )
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
    ) -> dict:
        require_permiso(session, id_usuario, "reportes", "ver")
        if fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        desde_dt = datetime.combine(fecha_desde, time.min)
        hasta_dt = datetime.combine(fecha_hasta, time.max)

        query = (
            session.query(PagoProveedor)
            .join(CuentaPorPagar, CuentaPorPagar.id_cuenta == PagoProveedor.id_cuenta_por_pagar)
            .join(Compra, Compra.id_compra == CuentaPorPagar.id_compra)
            .options(
                joinedload(PagoProveedor.cuenta_por_pagar)
                .joinedload(CuentaPorPagar.compra)
                .joinedload(Compra.proveedor)
            )
            .filter(PagoProveedor.fecha_pago >= desde_dt, PagoProveedor.fecha_pago <= hasta_dt)
        )
        if id_proveedor is not None:
            query = query.filter(Compra.id_proveedor == id_proveedor)
        pagos = query.order_by(PagoProveedor.fecha_pago).all()

        filas = []
        totales_por_metodo: dict[str, Decimal] = {}
        for pago in pagos:
            compra = pago.cuenta_por_pagar.compra
            totales_por_metodo[pago.metodo_pago] = (
                totales_por_metodo.get(pago.metodo_pago, Decimal("0.00")) + pago.monto
            )
            filas.append(
                {
                    "fecha_pago": pago.fecha_pago,
                    "proveedor": compra.proveedor.nombre_razon_social if compra.proveedor else None,
                    "numero_compra": compra.numero_compra,
                    "metodo_pago": pago.metodo_pago,
                    "monto": pago.monto,
                }
            )
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "totales_por_metodo": totales_por_metodo,
            "total_general": sum((f["monto"] for f in filas), Decimal("0.00")),
        }

    @staticmethod
    def proximos_vencimientos(
        session: Session, id_usuario: int | None, dias_horizonte: int = 30, id_proveedor: int | None = None
    ) -> dict:
        require_permiso(session, id_usuario, "reportes", "ver")
        if dias_horizonte < 0:
            raise ValueError("dias_horizonte no puede ser negativo")
        hoy = date.today()
        limite = hoy + timedelta(days=dias_horizonte)

        query = (
            session.query(CuentaPorPagar)
            .join(Compra, Compra.id_compra == CuentaPorPagar.id_compra)
            .options(joinedload(CuentaPorPagar.compra).joinedload(Compra.proveedor))
            .filter(CuentaPorPagar.estado.in_(ESTADOS_CXP_ABIERTOS))
            .filter(CuentaPorPagar.fecha_vencimiento.isnot(None))
            .filter(CuentaPorPagar.fecha_vencimiento >= hoy, CuentaPorPagar.fecha_vencimiento <= limite)
        )
        if id_proveedor is not None:
            query = query.filter(Compra.id_proveedor == id_proveedor)
        cuentas = query.order_by(CuentaPorPagar.fecha_vencimiento).all()

        filas = [
            {
                "numero_compra": cuenta.compra.numero_compra,
                "proveedor": cuenta.compra.proveedor.nombre_razon_social if cuenta.compra.proveedor else None,
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
            "total_general": sum((f["saldo_pendiente"] for f in filas), Decimal("0.00")),
        }

    @staticmethod
    def cxp_otras(
        session: Session,
        id_usuario: int | None,
        id_cuenta_bancaria: int | None = None,
        estado: str | None = None,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
    ) -> dict:
        """cuentas_por_pagar_otros pese al nombre no son pasivos comerciales: son
        transferencias recibidas en una cuenta bancaria propia que aun no se han podido
        identificar/conciliar contra un cliente (ver docstring de CuentaPorPagarOtro en
        models.py). Comparte tabla con Bancos -> conciliacion_bancaria, pero con
        agregacion distinta: aca se lista el detalle filtrable por cuenta/estado/fecha,
        alla se resume por cuenta con totales pendiente vs conciliado."""
        require_permiso(session, id_usuario, "reportes", "ver")
        if estado is not None and estado not in ESTADOS_CXP_OTRO:
            raise ValueError(f"estado invalido: {estado!r}, debe ser uno de {ESTADOS_CXP_OTRO}")
        if fecha_desde is not None and fecha_hasta is not None and fecha_desde > fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")

        query = session.query(CuentaPorPagarOtro).options(
            joinedload(CuentaPorPagarOtro.cuenta_bancaria), joinedload(CuentaPorPagarOtro.cliente_identificado)
        )
        if id_cuenta_bancaria is not None:
            query = query.filter(CuentaPorPagarOtro.id_cuenta_bancaria == id_cuenta_bancaria)
        if estado is not None:
            query = query.filter(CuentaPorPagarOtro.estado == estado)
        if fecha_desde is not None:
            query = query.filter(CuentaPorPagarOtro.fecha_recepcion >= datetime.combine(fecha_desde, time.min))
        if fecha_hasta is not None:
            query = query.filter(CuentaPorPagarOtro.fecha_recepcion <= datetime.combine(fecha_hasta, time.max))
        cuentas = query.order_by(CuentaPorPagarOtro.fecha_recepcion).all()

        filas = [
            {
                "id_cuenta": cuenta.id_cuenta,
                "cuenta_bancaria": cuenta.cuenta_bancaria.numero_cuenta if cuenta.cuenta_bancaria else None,
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
            "total_general": sum((f["saldo_pendiente"] for f in filas), Decimal("0.00")),
        }

    # ── Bancos ────────────────────────────────────────────────────────────

    @staticmethod
    def movimientos_cuenta_bancaria(
        session: Session,
        id_usuario: int | None,
        id_cuenta_bancaria: int,
        fecha_desde: date,
        fecha_hasta: date,
    ) -> dict:
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
        todos = (
            session.query(BancoMovimiento)
            .filter(BancoMovimiento.id_cuenta == id_cuenta_bancaria)
            .order_by(BancoMovimiento.fecha_movimiento)
            .all()
        )

        saldo_inicial = Decimal("0.00")
        for m in todos:
            if m.fecha_movimiento < desde_dt:
                monto = m.monto_movimiento or Decimal("0.00")
                saldo_inicial += monto if m.tipo_movimiento in ("abono", "deposito") else -monto

        saldo = saldo_inicial
        filas = []
        for m in todos:
            if desde_dt <= m.fecha_movimiento <= hasta_dt:
                monto = m.monto_movimiento or Decimal("0.00")
                saldo += monto if m.tipo_movimiento in ("abono", "deposito") else -monto
                filas.append(
                    {
                        "fecha_movimiento": m.fecha_movimiento,
                        "tipo_movimiento": m.tipo_movimiento,
                        "referencia_movimiento": m.referencia_movimiento,
                        "descripcion_movimiento": m.descripcion_movimiento,
                        "monto_movimiento": monto,
                        "saldo": saldo,
                    }
                )

        return {
            "id_cuenta": cuenta.id_cuenta,
            "numero_cuenta": cuenta.numero_cuenta,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "saldo_inicial": saldo_inicial,
            "filas": filas,
            "saldo_final": saldo,
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

        query = session.query(CuentaPorPagarOtro).options(joinedload(CuentaPorPagarOtro.cuenta_bancaria))
        if id_cuenta_bancaria is not None:
            query = query.filter(CuentaPorPagarOtro.id_cuenta_bancaria == id_cuenta_bancaria)
        if fecha_desde is not None:
            query = query.filter(CuentaPorPagarOtro.fecha_recepcion >= datetime.combine(fecha_desde, time.min))
        if fecha_hasta is not None:
            query = query.filter(CuentaPorPagarOtro.fecha_recepcion <= datetime.combine(fecha_hasta, time.max))
        partidas = query.all()

        por_cuenta: dict[int, dict] = {}
        for partida in partidas:
            cuenta = partida.cuenta_bancaria
            entrada = por_cuenta.setdefault(
                partida.id_cuenta_bancaria,
                {
                    "id_cuenta_bancaria": partida.id_cuenta_bancaria,
                    "numero_cuenta": cuenta.numero_cuenta if cuenta else None,
                    "total_pendiente": Decimal("0.00"),
                    "total_conciliado": Decimal("0.00"),
                    "cantidad_pendiente": 0,
                    "cantidad_conciliada": 0,
                },
            )
            if partida.estado == "conciliado":
                entrada["total_conciliado"] += partida.monto_total
                entrada["cantidad_conciliada"] += 1
            else:
                entrada["total_pendiente"] += partida.saldo_pendiente
                entrada["cantidad_pendiente"] += 1

        filas = sorted(por_cuenta.values(), key=lambda f: f["total_pendiente"], reverse=True)
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

        query = (
            session.query(ComisionFactura)
            .options(joinedload(ComisionFactura.vendedor))
            .filter(ComisionFactura.fecha_calculo >= desde_dt, ComisionFactura.fecha_calculo <= hasta_dt)
        )
        if id_vendedor is not None:
            query = query.filter(ComisionFactura.id_vendedor == id_vendedor)
        comisiones = query.all()

        por_vendedor: dict[int, dict] = {}
        for c in comisiones:
            vendedor = c.vendedor
            entrada = por_vendedor.setdefault(
                c.id_vendedor,
                {
                    "id_vendedor": c.id_vendedor,
                    "vendedor": vendedor.nombre_vendedor if vendedor else None,
                    "cantidad_facturas": 0,
                    "monto_comision": Decimal("0.00"),
                },
            )
            entrada["cantidad_facturas"] += 1
            entrada["monto_comision"] += c.monto_comision or Decimal("0.00")

        filas = sorted(por_vendedor.values(), key=lambda f: f["monto_comision"], reverse=True)
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

        query = session.query(ComisionFactura).options(joinedload(ComisionFactura.vendedor))
        if id_vendedor is not None:
            query = query.filter(ComisionFactura.id_vendedor == id_vendedor)
        if fecha_desde is not None:
            query = query.filter(ComisionFactura.fecha_calculo >= datetime.combine(fecha_desde, time.min))
        if fecha_hasta is not None:
            query = query.filter(ComisionFactura.fecha_calculo <= datetime.combine(fecha_hasta, time.max))
        comisiones = query.all()

        por_vendedor: dict[int, dict] = {}
        for c in comisiones:
            vendedor = c.vendedor
            entrada = por_vendedor.setdefault(
                c.id_vendedor,
                {
                    "id_vendedor": c.id_vendedor,
                    "vendedor": vendedor.nombre_vendedor if vendedor else None,
                    "pagado": Decimal("0.00"),
                    "liberada": Decimal("0.00"),
                    "pendiente": Decimal("0.00"),
                },
            )
            monto = c.monto_comision or Decimal("0.00")
            if c.estado_pago == "pagada":
                entrada["pagado"] += monto
            elif c.estado_pago == "liberada":
                entrada["liberada"] += monto
            else:
                entrada["pendiente"] += monto

        filas = sorted(por_vendedor.values(), key=lambda f: f["liberada"], reverse=True)
        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filas": filas,
            "total_pagado": sum((f["pagado"] for f in filas), Decimal("0.00")),
            "total_liberada": sum((f["liberada"] for f in filas), Decimal("0.00")),
            "total_pendiente": sum((f["pendiente"] for f in filas), Decimal("0.00")),
        }
