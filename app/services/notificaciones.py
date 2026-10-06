"""
Alertas de la campana de la barra superior (app/ui/topbar.py). Todas se calculan con
consultas de solo lectura sobre datos que ya existen -- no hay una tabla de notificaciones:
el estado "pendiente" ES la condicion (una cuenta vencida deja de alertar cuando se cobra).

Cada alerta se omite en silencio si el usuario no tiene el permiso de ver su módulo: un rol
sin acceso a Inventario no debe ver "3 productos con stock bajo" que no puede abrir. Es una
comodidad de UX, igual que MODULO_PERMISO en main_window.py; la barrera real sigue siendo
require_permiso() en los servicios de cada módulo.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.db.models import ControlDeTasa, CuentaPorCobrar, CuentaPorPagar, Inventario
from app.services.licencia import ESTADO_ACTIVA, LicenciaService
from app.services.usuarios import UsuarioService

logger = logging.getLogger(__name__)

CUENTA_ABIERTA = ("pendiente", "parcial", "vencida")
DIAS_ALERTA_VENCIMIENTO_PRODUCTO = 30
DIAS_AVISO_LICENCIA = 15

SEVERIDAD_ALTA = "alta"
SEVERIDAD_MEDIA = "media"
SEVERIDAD_INFO = "info"
_ORDEN_SEVERIDAD = {SEVERIDAD_ALTA: 0, SEVERIDAD_MEDIA: 1, SEVERIDAD_INFO: 2}


@dataclass(frozen=True)
class Notificacion:
    clave: str
    titulo: str
    detalle: str
    modulo: str  # clave del modulo al que lleva al hacer click (ver MODULOS_CONFIG)
    severidad: str


def _plural(cantidad: int, singular: str, plural: str) -> str:
    return f"{cantidad} {singular if cantidad == 1 else plural}"


def _monto(valor: Decimal | None) -> str:
    return f"${(valor or Decimal('0')):,.2f}"


class NotificacionesService:
    @staticmethod
    def obtener(session: Session, id_usuario: int, hoy: date | None = None) -> list[Notificacion]:
        """Alertas vigentes para `id_usuario`, las mas urgentes primero. Cada fuente falla
        por separado: si una consulta revienta (o su tabla no existe todavia), el resto de
        las alertas se muestra igual -- la campana nunca debe tumbar el shell."""
        hoy = hoy or date.today()
        fuentes = (
            NotificacionesService._cuentas_por_cobrar_vencidas,
            NotificacionesService._cuentas_por_pagar_vencidas,
            NotificacionesService._stock_bajo,
            NotificacionesService._productos_por_vencer,
            NotificacionesService._tasa_sin_registrar,
            NotificacionesService._licencia,
        )
        notificaciones: list[Notificacion] = []
        for fuente in fuentes:
            try:
                notificacion = fuente(session, id_usuario, hoy)
            except Exception:
                logger.exception("Fallo la alerta '%s'", fuente.__name__)
                session.rollback()
                continue
            if notificacion is not None:
                notificaciones.append(notificacion)
        notificaciones.sort(key=lambda n: _ORDEN_SEVERIDAD[n.severidad])
        return notificaciones

    @staticmethod
    def _puede(session: Session, id_usuario: int, recurso: str) -> bool:
        return UsuarioService.verificar_permiso(session, id_usuario, recurso, "ver")

    @staticmethod
    def _cuentas_por_cobrar_vencidas(session: Session, id_usuario: int, hoy: date) -> Notificacion | None:
        if not NotificacionesService._puede(session, id_usuario, "pagos"):
            return None
        cantidad, saldo = (
            session.query(
                func.count(CuentaPorCobrar.id_cuenta_por_cobrar),
                func.coalesce(func.sum(CuentaPorCobrar.saldo_pendiente), 0),
            )
            .filter(CuentaPorCobrar.estado.in_(CUENTA_ABIERTA), CuentaPorCobrar.fecha_vencimiento < hoy)
            .one()
        )
        if not cantidad:
            return None
        return Notificacion(
            "cxc_vencidas",
            "Cuentas por cobrar vencidas",
            f"{_plural(cantidad, 'factura vencida', 'facturas vencidas')} — saldo {_monto(saldo)}",
            "cuentas_por_cobrar",
            SEVERIDAD_ALTA,
        )

    @staticmethod
    def _cuentas_por_pagar_vencidas(session: Session, id_usuario: int, hoy: date) -> Notificacion | None:
        if not NotificacionesService._puede(session, id_usuario, "pagos"):
            return None
        cantidad, saldo = (
            session.query(
                func.count(CuentaPorPagar.id_cuenta),
                func.coalesce(func.sum(CuentaPorPagar.saldo_pendiente), 0),
            )
            .filter(CuentaPorPagar.estado.in_(CUENTA_ABIERTA), CuentaPorPagar.fecha_vencimiento < hoy)
            .one()
        )
        if not cantidad:
            return None
        return Notificacion(
            "cxp_vencidas",
            "Cuentas por pagar vencidas",
            f"{_plural(cantidad, 'compra vencida', 'compras vencidas')} — saldo {_monto(saldo)}",
            "cuentas_por_pagar",
            SEVERIDAD_ALTA,
        )

    @staticmethod
    def _stock_bajo(session: Session, id_usuario: int, hoy: date) -> Notificacion | None:
        if not NotificacionesService._puede(session, id_usuario, "inventario"):
            return None
        # Mismo criterio que DashboardService._filtro_alerta_inventario: el minimo es POR
        # PRODUCTO y cantidad_minima=0 significa "sin minimo configurado", nunca alerta.
        cantidad = (
            session.query(func.count(Inventario.id_producto))
            .filter(
                Inventario.estado_producto == "ACTIVO",
                Inventario.cantidad_minima > 0,
                Inventario.cantidad_unidad < Inventario.cantidad_minima,
            )
            .scalar()
        )
        if not cantidad:
            return None
        return Notificacion(
            "stock_bajo",
            "Stock bajo",
            f"{_plural(cantidad, 'producto por debajo', 'productos por debajo')} de su mínimo",
            "inventario",
            SEVERIDAD_MEDIA,
        )

    @staticmethod
    def _productos_por_vencer(session: Session, id_usuario: int, hoy: date) -> Notificacion | None:
        if not NotificacionesService._puede(session, id_usuario, "inventario"):
            return None
        limite = hoy + timedelta(days=DIAS_ALERTA_VENCIMIENTO_PRODUCTO)
        cantidad = (
            session.query(func.count(Inventario.id_producto))
            .filter(
                Inventario.estado_producto == "ACTIVO",
                and_(Inventario.fecha_vencimiento.isnot(None), Inventario.fecha_vencimiento <= limite),
            )
            .scalar()
        )
        if not cantidad:
            return None
        return Notificacion(
            "productos_por_vencer",
            "Productos por vencer",
            f"{_plural(cantidad, 'producto vence', 'productos vencen')} en {DIAS_ALERTA_VENCIMIENTO_PRODUCTO} "
            "días o ya vencieron",
            "inventario",
            SEVERIDAD_MEDIA,
        )

    @staticmethod
    def _tasa_sin_registrar(session: Session, id_usuario: int, hoy: date) -> Notificacion | None:
        if not UsuarioService.verificar_permiso(session, id_usuario, "tasas", "ver"):
            return None
        ultima = session.query(func.max(ControlDeTasa.fecha_tasa)).scalar()
        if ultima is not None and ultima.date() >= hoy:
            return None
        return Notificacion(
            "tasa_sin_registrar",
            "Tasa de cambio",
            "La tasa de hoy todavía no está registrada"
            if ultima is not None
            else "Todavía no hay ninguna tasa de cambio registrada",
            "control_tasas",
            SEVERIDAD_INFO,
        )

    @staticmethod
    def _licencia(session: Session, id_usuario: int, hoy: date) -> Notificacion | None:
        if not UsuarioService.verificar_permiso(session, id_usuario, "empresa", "ver"):
            return None
        estado = LicenciaService.estado_actual()
        if estado.estado != ESTADO_ACTIVA:
            return Notificacion("licencia", "Licencia", estado.mensaje, "config_empresa", SEVERIDAD_ALTA)
        if estado.expira is not None:
            dias = (estado.expira.date() - hoy).days
            if dias <= DIAS_AVISO_LICENCIA:
                detalle = (
                    f"La licencia vence el {estado.expira:%d/%m/%Y}"
                    if dias >= 0
                    else f"La licencia venció el {estado.expira:%d/%m/%Y}"
                )
                return Notificacion("licencia", "Licencia", detalle, "config_empresa", SEVERIDAD_MEDIA)
        return None
