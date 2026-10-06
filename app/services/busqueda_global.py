"""
Búsqueda global de la barra superior (app/ui/topbar.py): una sola caja que encuentra
clientes, productos, proveedores y facturas sin que el usuario tenga que entrar primero al
módulo. Los módulos en sí (Facturación, Compras, ...) los resuelve la propia TopBar, no
necesita base de datos.

Cada tipo se omite si el usuario no tiene el permiso de ver ese módulo -- misma comodidad de
UX que el sidebar (MODULO_PERMISO); la autorización real sigue en los servicios de cada
módulo cuando el usuario abre el resultado.
"""

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session, joinedload

from app.db.models import Cliente, FacturaVenta, Inventario, Proveedor
from app.services.usuarios import UsuarioService

logger = logging.getLogger(__name__)

LONGITUD_MINIMA = 2
LIMITE_POR_TIPO = 4

TIPO_CLIENTE = "Cliente"
TIPO_PRODUCTO = "Producto"
TIPO_PROVEEDOR = "Proveedor"
TIPO_FACTURA = "Factura"


@dataclass(frozen=True)
class ResultadoBusqueda:
    tipo: str
    titulo: str
    detalle: str
    modulo: str  # clave del modulo al que lleva (ver MODULOS_CONFIG)
    texto_busqueda: str  # lo que se escribe en la caja de busqueda de ese modulo


def _escapar_like(texto: str) -> str:
    """% y _ son comodines de LIKE: sin escape, buscar '%' devolveria todo (mismo criterio
    que clientes._escapar_like)."""
    return texto.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def _identificacion(id_legal: str | None, numero: str | None) -> str:
    return "-".join(p for p in (id_legal, numero) if p)


class BusquedaGlobalService:
    @staticmethod
    def buscar(
        session: Session,
        id_usuario: int,
        texto: str,
        limite_por_tipo: int = LIMITE_POR_TIPO,
    ) -> list[ResultadoBusqueda]:
        texto = (texto or "").strip()
        if len(texto) < LONGITUD_MINIMA:
            return []
        like = f"%{_escapar_like(texto)}%"

        buscadores = (
            ("clientes", BusquedaGlobalService._clientes),
            ("inventario", BusquedaGlobalService._productos),
            ("proveedores", BusquedaGlobalService._proveedores),
            ("ventas", BusquedaGlobalService._facturas),
        )
        resultados: list[ResultadoBusqueda] = []
        for recurso, buscador in buscadores:
            if not UsuarioService.verificar_permiso(session, id_usuario, recurso, "ver"):
                continue
            try:
                resultados.extend(buscador(session, like, limite_por_tipo))
            except Exception:
                # Un tipo que falle no debe vaciar los demas resultados.
                logger.exception("Fallo la busqueda global de '%s'", recurso)
                session.rollback()
        return resultados

    @staticmethod
    def _clientes(session: Session, like: str, limite: int) -> list[ResultadoBusqueda]:
        filas = (
            session.query(Cliente)
            .filter(
                Cliente.nombre_razon_social.ilike(like, escape="\\")
                | Cliente.identificacion_cliente.ilike(like, escape="\\")
                | Cliente.codigo_cliente.ilike(like, escape="\\")
            )
            .order_by(Cliente.nombre_razon_social)
            .limit(limite)
            .all()
        )
        return [
            ResultadoBusqueda(
                TIPO_CLIENTE,
                c.nombre_razon_social,
                _identificacion(c.id_legal, c.identificacion_cliente) or (c.codigo_cliente or ""),
                "clientes",
                c.nombre_razon_social,
            )
            for c in filas
        ]

    @staticmethod
    def _productos(session: Session, like: str, limite: int) -> list[ResultadoBusqueda]:
        filas = (
            session.query(Inventario)
            .filter(
                Inventario.nombre_producto.ilike(like, escape="\\") | Inventario.cod_producto.ilike(like, escape="\\")
            )
            .order_by(Inventario.nombre_producto)
            .limit(limite)
            .all()
        )
        return [
            ResultadoBusqueda(TIPO_PRODUCTO, p.nombre_producto, p.cod_producto, "inventario", p.cod_producto)
            for p in filas
        ]

    @staticmethod
    def _proveedores(session: Session, like: str, limite: int) -> list[ResultadoBusqueda]:
        filas = (
            session.query(Proveedor)
            .filter(
                Proveedor.nombre_razon_social.ilike(like, escape="\\")
                | Proveedor.identificacion_proveedor.ilike(like, escape="\\")
                | Proveedor.codigo_proveedor.ilike(like, escape="\\")
            )
            .order_by(Proveedor.nombre_razon_social)
            .limit(limite)
            .all()
        )
        return [
            ResultadoBusqueda(
                TIPO_PROVEEDOR,
                p.nombre_razon_social,
                _identificacion(p.id_legal, p.identificacion_proveedor) or (p.codigo_proveedor or ""),
                "proveedores",
                p.nombre_razon_social,
            )
            for p in filas
        ]

    @staticmethod
    def _facturas(session: Session, like: str, limite: int) -> list[ResultadoBusqueda]:
        filas = (
            session.query(FacturaVenta)
            .options(joinedload(FacturaVenta.cliente))
            .filter(FacturaVenta.numero_factura.ilike(like, escape="\\"))
            .order_by(FacturaVenta.fecha_emision.desc())
            .limit(limite)
            .all()
        )
        return [
            ResultadoBusqueda(
                TIPO_FACTURA,
                f.numero_factura,
                f"{f.cliente.nombre_razon_social if f.cliente else '—'} — ${f.total_venta:,.2f}",
                "facturacion",
                f.numero_factura,
            )
            for f in filas
        ]
