"""R-01 (docs/CHECKLIST_PRODUCCION.md): motor de reportes. Empieza por los dos de mayor
valor de negocio y que tocan caja/cobranza real: antiguedad de saldos de CxC (aging) y
arqueo de caja. RBAC via el recurso 'reportes' (migrations/0016).

R-06: el filtro "un VENDEDOR solo ve sus propias facturas" queda pendiente para cuando
exista un reporte de ventas -- ninguno de los dos reportes de aca abajo esta ligado a un
vendedor especifico.
"""

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session, joinedload

from app.db.models import Caja, CajaMovimiento, CuentaPorCobrar, FacturaVenta
from app.services.permisos import require_permiso

logger = logging.getLogger(__name__)

ESTADOS_CXC_ABIERTOS = ("pendiente", "parcial", "vencida")

# R-07: lista blanca explicita de columnas ordenables -- nunca
# getattr(Modelo, campo_del_usuario) con un valor que venga de la UI/API. Si se agrega un
# criterio de orden nuevo, agregarlo aca primero.
_ORDEN_AGING_CXC = {
    "fecha_vencimiento": CuentaPorCobrar.fecha_vencimiento,
    "saldo_pendiente": CuentaPorCobrar.saldo_pendiente,
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
