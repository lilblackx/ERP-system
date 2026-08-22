from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.db.models import Caja, CuentaPorCobrar, CuentaPorPagar, FacturaVenta, Inventario
from app.services.permisos import require_permiso

CUENTA_ABIERTA = ("pendiente", "parcial", "vencida")


def _rango_dia(dia: date) -> tuple[datetime, datetime]:
    inicio = datetime.combine(dia, datetime.min.time())
    return inicio, inicio + timedelta(days=1)


class DashboardService:
    @staticmethod
    def get_panel_general_data(
        session: Session, umbral_stock_minimo: int = 10, id_usuario: int | None = None
    ) -> dict:
        require_permiso(session, id_usuario, "dashboard", "ver")
        hoy = date.today()
        ayer = hoy - timedelta(days=1)

        return {
            "ventas_hoy": DashboardService._kpi_ventas_hoy(session, hoy, ayer),
            "por_cobrar": DashboardService._kpi_por_cobrar(session, hoy),
            "por_pagar": DashboardService._kpi_por_pagar(session, hoy),
            "productos_alerta": DashboardService._kpi_productos_alerta(session, umbral_stock_minimo),
            "grafico_semanal": DashboardService._grafico_semanal(session, hoy),
            "cajas_activas": DashboardService._cajas_activas(session, hoy),
            "facturas_recientes": DashboardService._facturas_recientes(session),
            "inventario_alerta": DashboardService._inventario_alerta(session, umbral_stock_minimo),
        }

    @staticmethod
    def _total_ventas_del_dia(session: Session, dia: date) -> Decimal:
        inicio, fin = _rango_dia(dia)
        return session.query(func.coalesce(func.sum(FacturaVenta.total_venta), 0)).filter(
            FacturaVenta.fecha_emision >= inicio,
            FacturaVenta.fecha_emision < fin,
            FacturaVenta.estado_factura != "ANULADA",
        ).scalar()

    @staticmethod
    def _kpi_ventas_hoy(session: Session, hoy: date, ayer: date) -> dict:
        total_hoy = DashboardService._total_ventas_del_dia(session, hoy)
        total_ayer = DashboardService._total_ventas_del_dia(session, ayer)

        if total_ayer:
            porcentaje_vs_ayer = float((total_hoy - total_ayer) / total_ayer * 100)
        elif total_hoy:
            porcentaje_vs_ayer = 100.0
        else:
            porcentaje_vs_ayer = 0.0

        return {"total": total_hoy, "porcentaje_vs_ayer": round(porcentaje_vs_ayer, 2)}

    @staticmethod
    def _kpi_por_cobrar(session: Session, hoy: date) -> dict:
        saldo_total = session.query(func.coalesce(func.sum(CuentaPorCobrar.saldo_pendiente), 0)).filter(
            CuentaPorCobrar.estado.in_(CUENTA_ABIERTA)
        ).scalar()

        facturas_vencidas = session.query(func.count(CuentaPorCobrar.id_cuenta_por_cobrar)).filter(
            CuentaPorCobrar.estado.in_(CUENTA_ABIERTA),
            CuentaPorCobrar.fecha_vencimiento < hoy,
        ).scalar()

        return {"saldo_total": saldo_total, "facturas_vencidas": facturas_vencidas}

    @staticmethod
    def _kpi_por_pagar(session: Session, hoy: date) -> dict:
        saldo_total = session.query(func.coalesce(func.sum(CuentaPorPagar.saldo_pendiente), 0)).filter(
            CuentaPorPagar.estado.in_(CUENTA_ABIERTA)
        ).scalar()

        compras_vencidas = session.query(func.count(CuentaPorPagar.id_cuenta)).filter(
            CuentaPorPagar.estado.in_(CUENTA_ABIERTA),
            CuentaPorPagar.fecha_vencimiento < hoy,
        ).scalar()

        return {"saldo_total": saldo_total, "compras_vencidas": compras_vencidas}

    @staticmethod
    def _kpi_productos_alerta(session: Session, umbral_stock_minimo: int) -> int:
        return session.query(func.count(Inventario.id_producto)).filter(
            Inventario.cantidad_unidad <= umbral_stock_minimo
        ).scalar()

    @staticmethod
    def _grafico_semanal(session: Session, hoy: date) -> list[dict]:
        dias = [hoy - timedelta(days=offset) for offset in range(6, -1, -1)]
        return [{"fecha": dia, "monto": DashboardService._total_ventas_del_dia(session, dia)} for dia in dias]

    @staticmethod
    def _cajas_activas(session: Session, hoy: date) -> list[dict]:
        inicio, fin = _rango_dia(hoy)
        cajas = (
            session.query(Caja)
            .options(joinedload(Caja.usuario))
            .filter(
                Caja.fecha_apertura >= inicio,
                Caja.fecha_apertura < fin,
                Caja.fecha_cierre.is_(None),
            )
            .order_by(Caja.fecha_apertura)
            .all()
        )
        return [
            {
                "id_caja": caja.id_caja,
                "nombre_caja": caja.nombre_caja,
                "saldo_apertura": caja.saldo_apertura,
                "fecha_apertura": caja.fecha_apertura,
                "cajero": caja.usuario.nombre_usuario if caja.usuario else None,
            }
            for caja in cajas
        ]

    @staticmethod
    def _facturas_recientes(session: Session, limite: int = 5) -> list[dict]:
        facturas = (
            session.query(FacturaVenta)
            .options(joinedload(FacturaVenta.cliente))
            .order_by(FacturaVenta.fecha_emision.desc())
            .limit(limite)
            .all()
        )
        return [
            {
                "numero_factura": factura.numero_factura,
                "cliente": factura.cliente.nombre_razon_social if factura.cliente else None,
                "total_venta": factura.total_venta,
                "estado_factura": factura.estado_factura,
            }
            for factura in facturas
        ]

    @staticmethod
    def _inventario_alerta(session: Session, umbral_stock_minimo: int, limite: int = 5) -> list[dict]:
        productos = (
            session.query(Inventario)
            .options(joinedload(Inventario.categoria))
            .filter(Inventario.cantidad_unidad <= umbral_stock_minimo)
            .order_by(Inventario.cantidad_unidad)
            .limit(limite)
            .all()
        )
        return [
            {
                "cod_producto": producto.cod_producto,
                "nombre_producto": producto.nombre_producto,
                "categoria": producto.categoria.nombre if producto.categoria else None,
                "cantidad_unidad": producto.cantidad_unidad,
            }
            for producto in productos
        ]
