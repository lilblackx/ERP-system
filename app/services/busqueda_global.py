"""
Búsqueda global de la barra superior (app/ui/topbar.py): una sola caja que encuentra
clientes, productos, proveedores, facturas, vendedores, compras, cuentas por cobrar y por
pagar, bancos, cuentas bancarias, cajas y usuarios sin que el usuario tenga que entrar primero
al módulo, más ACCIONES ("Nueva factura", "Configuración › Correo", ...) que abren directo
el formulario o la pantalla. Los módulos en sí (Facturación, Compras, ...) los resuelve la
propia TopBar, no necesita base de datos.

Cada tipo se omite si el usuario no tiene el permiso de ver ese módulo -- misma comodidad de
UX que el sidebar (MODULO_PERMISO); la autorización real sigue en los servicios de cada
módulo cuando el usuario abre el resultado.
"""

import logging
import unicodedata
from dataclasses import dataclass

from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    Banco,
    Caja,
    Cliente,
    Compra,
    CuentaBancaria,
    CuentaPorCobrar,
    CuentaPorPagar,
    FacturaVenta,
    Inventario,
    Proveedor,
    Usuario,
    Vendedor,
)
from app.services.tesoreria import _enmascarar_numero_cuenta
from app.services.usuarios import UsuarioService
from app.utils.rif import formatear_identificacion

logger = logging.getLogger(__name__)

LONGITUD_MINIMA = 2
# Los tipos que crecen sin limite (compras, cuentas por cobrar/pagar) exigen una letra mas
# antes de consultar: con 2 letras casi todo coincide y la consulta no ayuda a nadie.
LONGITUD_MINIMA_TIPOS_GRANDES = 3
LIMITE_POR_TIPO = 4
CUENTA_ABIERTA = ("pendiente", "parcial", "vencida")

TIPO_CLIENTE = "Cliente"
TIPO_PRODUCTO = "Producto"
TIPO_PROVEEDOR = "Proveedor"
TIPO_FACTURA = "Factura"
TIPO_VENDEDOR = "Vendedor"
TIPO_COMPRA = "Compra"
TIPO_CXC = "Cuenta por cobrar"
TIPO_CXP = "Cuenta por pagar"
TIPO_BANCO = "Banco"
TIPO_CUENTA_BANCARIA = "Cuenta bancaria"
TIPO_CAJA = "Caja"
TIPO_USUARIO = "Usuario"
TIPO_ACCION = "Acción"


@dataclass(frozen=True)
class ResultadoBusqueda:
    tipo: str
    titulo: str
    detalle: str
    modulo: str  # clave del modulo al que lleva (ver MODULOS_CONFIG)
    texto_busqueda: str  # lo que se escribe en la caja de busqueda de ese modulo
    accion: str = ""  # si no esta vacia, en vez de solo navegar se ejecuta esa accion (ver ACCIONES)


@dataclass(frozen=True)
class AccionBusqueda:
    clave: str
    titulo: str
    detalle: str
    modulo: str
    palabras: tuple[str, ...]  # sinonimos que tambien la encuentran ("facturar" -> Nueva factura)
    permiso: tuple[str, str]  # (recurso, accion): se omite si el usuario no lo tiene


# Destinos que no son datos sino pantallas o formularios. main_window._ejecutar_accion sabe
# abrir cada `clave` (ver ACCIONES_PANEL / ACCIONES_CONFIG ahi).
ACCIONES: tuple[AccionBusqueda, ...] = (
    AccionBusqueda(
        "nueva_factura",
        "Nueva factura",
        "Emitir una factura",
        "facturacion",
        ("facturar", "vender", "venta"),
        ("ventas", "crear"),
    ),
    AccionBusqueda(
        "nuevo_cliente",
        "Nuevo cliente",
        "Registrar un cliente",
        "clientes",
        ("agregar cliente", "crear cliente"),
        ("clientes", "crear"),
    ),
    AccionBusqueda(
        "nuevo_producto",
        "Nuevo producto",
        "Registrar un producto",
        "inventario",
        ("articulo", "agregar producto", "crear producto"),
        ("inventario", "crear"),
    ),
    AccionBusqueda(
        "nuevo_proveedor",
        "Nuevo proveedor",
        "Registrar un proveedor",
        "proveedores",
        ("agregar proveedor", "crear proveedor"),
        ("proveedores", "crear"),
    ),
    AccionBusqueda(
        "nuevo_vendedor",
        "Nuevo vendedor",
        "Registrar un vendedor",
        "vendedores",
        ("agregar vendedor", "crear vendedor"),
        ("vendedores", "crear"),
    ),
    AccionBusqueda(
        "nueva_compra",
        "Nueva orden de compra",
        "Registrar una orden de compra",
        "compras",
        ("comprar", "pedido", "orden"),
        ("compras", "crear"),
    ),
    AccionBusqueda(
        "registrar_tasa",
        "Registrar tasa de cambio",
        "Cargar la tasa del día",
        "control_tasas",
        ("dolar", "bcv", "bolivares", "cambio"),
        ("tasas", "crear"),
    ),
    AccionBusqueda(
        "config_empresa",
        "Configuración › Empresa",
        "Datos, logo, IVA e impresora",
        "config_empresa",
        ("impresora", "logo", "iva", "razon social", "rif", "pie de factura"),
        ("empresa", "ver"),
    ),
    AccionBusqueda(
        "config_correo",
        "Configuración › Correo",
        "Servidor de correo (SMTP)",
        "config_empresa",
        ("smtp", "email", "mail"),
        ("empresa", "ver"),
    ),
    AccionBusqueda(
        "config_licencia",
        "Configuración › Licencia",
        "Estado y activación de la licencia",
        "config_empresa",
        ("activar", "vence", "vencimiento"),
        ("empresa", "ver"),
    ),
)


def normalizar(texto: str) -> str:
    """Minúsculas y sin tildes: 'facturacion' tiene que encontrar 'Facturación'."""
    sin_tildes = unicodedata.normalize("NFD", texto)
    return "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn").lower()


def _escapar_like(texto: str) -> str:
    """% y _ son comodines de LIKE: sin escape, buscar '%' devolveria todo (mismo criterio
    que clientes._escapar_like)."""
    return texto.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def _identificacion(id_legal: str | None, numero: str | None) -> str:
    return formatear_identificacion(id_legal, numero)


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

        # (recurso, buscador, minimo de caracteres)
        buscadores = (
            ("clientes", BusquedaGlobalService._clientes, LONGITUD_MINIMA),
            ("inventario", BusquedaGlobalService._productos, LONGITUD_MINIMA),
            ("proveedores", BusquedaGlobalService._proveedores, LONGITUD_MINIMA),
            ("ventas", BusquedaGlobalService._facturas, LONGITUD_MINIMA),
            ("vendedores", BusquedaGlobalService._vendedores, LONGITUD_MINIMA),
            ("compras", BusquedaGlobalService._compras, LONGITUD_MINIMA_TIPOS_GRANDES),
            ("pagos", BusquedaGlobalService._cuentas_por_cobrar, LONGITUD_MINIMA_TIPOS_GRANDES),
            ("pagos", BusquedaGlobalService._cuentas_por_pagar, LONGITUD_MINIMA_TIPOS_GRANDES),
            ("bancos", BusquedaGlobalService._bancos, LONGITUD_MINIMA),
            ("bancos", BusquedaGlobalService._cuentas_bancarias, LONGITUD_MINIMA),
            ("cajas", BusquedaGlobalService._cajas, LONGITUD_MINIMA),
            ("usuarios", BusquedaGlobalService._usuarios, LONGITUD_MINIMA),
        )
        resultados: list[ResultadoBusqueda] = BusquedaGlobalService._acciones(session, id_usuario, texto)
        for recurso, buscador, minimo in buscadores:
            if len(texto) < minimo:
                continue
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
    def _acciones(session: Session, id_usuario: int, texto: str) -> list[ResultadoBusqueda]:
        """Acciones cuyo titulo o sinonimos contienen el texto (sin tildes ni mayusculas) y para
        las que el usuario tiene permiso. Van antes que los datos: si alguien escribe 'nueva
        fact' quiere la accion, no una factura existente."""
        buscado = normalizar(texto)
        encontradas = []
        for accion in ACCIONES:
            titulo = normalizar(accion.titulo)
            if buscado not in titulo and not any(buscado in normalizar(p) for p in accion.palabras):
                continue
            try:
                permitido = UsuarioService.verificar_permiso(session, id_usuario, *accion.permiso)
            except Exception:
                logger.exception("Fallo el permiso de la accion '%s'", accion.clave)
                session.rollback()
                continue
            if permitido:
                encontradas.append(
                    ResultadoBusqueda(TIPO_ACCION, accion.titulo, accion.detalle, accion.modulo, "", accion.clave)
                )
        return encontradas

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

    @staticmethod
    def _vendedores(session: Session, like: str, limite: int) -> list[ResultadoBusqueda]:
        filas = (
            session.query(Vendedor)
            .filter(
                Vendedor.nombre_vendedor.ilike(like, escape="\\")
                | Vendedor.identificacion_vendedor.ilike(like, escape="\\")
                | Vendedor.codigo_vendedor.ilike(like, escape="\\")
            )
            .order_by(Vendedor.nombre_vendedor)
            .limit(limite)
            .all()
        )
        return [
            ResultadoBusqueda(
                TIPO_VENDEDOR,
                v.nombre_vendedor,
                v.codigo_vendedor or v.identificacion_vendedor or "",
                "vendedores",
                v.nombre_vendedor,
            )
            for v in filas
        ]

    @staticmethod
    def _compras(session: Session, like: str, limite: int) -> list[ResultadoBusqueda]:
        filas = (
            session.query(Compra)
            .options(joinedload(Compra.proveedor))
            .join(Proveedor, Compra.id_proveedor == Proveedor.id_proveedor)
            .filter(
                Compra.numero_compra.ilike(like, escape="\\") | Proveedor.nombre_razon_social.ilike(like, escape="\\")
            )
            .order_by(Compra.fecha_emision.desc())
            .limit(limite)
            .all()
        )
        # El modulo de compras no tiene caja de busqueda propia: el resultado solo navega.
        return [
            ResultadoBusqueda(
                TIPO_COMPRA,
                c.numero_compra,
                f"{c.proveedor.nombre_razon_social if c.proveedor else '—'} — ${c.total_compra:,.2f}",
                "compras",
                "",
            )
            for c in filas
        ]

    @staticmethod
    def _cuentas_por_cobrar(session: Session, like: str, limite: int) -> list[ResultadoBusqueda]:
        filas = (
            session.query(CuentaPorCobrar)
            .options(joinedload(CuentaPorCobrar.factura).joinedload(FacturaVenta.cliente))
            .join(FacturaVenta, CuentaPorCobrar.id_factura == FacturaVenta.id_factura)
            .join(Cliente, FacturaVenta.id_cliente_factura == Cliente.id_cliente)
            .filter(
                CuentaPorCobrar.estado.in_(CUENTA_ABIERTA),
                FacturaVenta.numero_factura.ilike(like, escape="\\")
                | Cliente.nombre_razon_social.ilike(like, escape="\\"),
            )
            .order_by(CuentaPorCobrar.fecha_vencimiento)
            .limit(limite)
            .all()
        )
        resultados = []
        for c in filas:
            cliente = c.factura.cliente.nombre_razon_social if c.factura and c.factura.cliente else "—"
            numero = c.factura.numero_factura if c.factura else ""
            resultados.append(
                ResultadoBusqueda(
                    TIPO_CXC,
                    numero,
                    f"{cliente} — saldo ${c.saldo_pendiente:,.2f} ({c.estado})",
                    "cuentas_por_cobrar",
                    cliente,
                )
            )
        return resultados

    @staticmethod
    def _cuentas_por_pagar(session: Session, like: str, limite: int) -> list[ResultadoBusqueda]:
        filas = (
            session.query(CuentaPorPagar)
            .options(joinedload(CuentaPorPagar.compra).joinedload(Compra.proveedor))
            .join(Compra, CuentaPorPagar.id_compra == Compra.id_compra)
            .join(Proveedor, Compra.id_proveedor == Proveedor.id_proveedor)
            .filter(
                CuentaPorPagar.estado.in_(CUENTA_ABIERTA),
                Compra.numero_compra.ilike(like, escape="\\") | Proveedor.nombre_razon_social.ilike(like, escape="\\"),
            )
            .order_by(CuentaPorPagar.fecha_vencimiento)
            .limit(limite)
            .all()
        )
        resultados = []
        for c in filas:
            proveedor = c.compra.proveedor.nombre_razon_social if c.compra and c.compra.proveedor else "—"
            numero = c.compra.numero_compra if c.compra else ""
            resultados.append(
                ResultadoBusqueda(
                    TIPO_CXP,
                    numero,
                    f"{proveedor} — saldo ${c.saldo_pendiente:,.2f} ({c.estado})",
                    "cuentas_por_pagar",
                    proveedor,
                )
            )
        return resultados

    @staticmethod
    def _bancos(session: Session, like: str, limite: int) -> list[ResultadoBusqueda]:
        filas = (
            session.query(Banco)
            .filter(Banco.nombre_banco.ilike(like, escape="\\") | Banco.codigo_banco.ilike(like, escape="\\"))
            .order_by(Banco.nombre_banco)
            .limit(limite)
            .all()
        )
        return [
            ResultadoBusqueda(TIPO_BANCO, b.nombre_banco, b.codigo_banco or "", "bancos", b.nombre_banco) for b in filas
        ]

    @staticmethod
    def _cuentas_bancarias(session: Session, like: str, limite: int) -> list[ResultadoBusqueda]:
        """Se busca por banco o titular; el numero de cuenta se muestra enmascarado, igual que en
        el modulo (ver tesoreria._enmascarar_numero_cuenta), y no se usa para buscar."""
        filas = (
            session.query(CuentaBancaria)
            .options(joinedload(CuentaBancaria.banco))
            .join(Banco, CuentaBancaria.id_banco == Banco.id_banco)
            .filter(
                CuentaBancaria.nombre_titular.ilike(like, escape="\\") | Banco.nombre_banco.ilike(like, escape="\\")
            )
            .order_by(Banco.nombre_banco)
            .limit(limite)
            .all()
        )
        return [
            ResultadoBusqueda(
                TIPO_CUENTA_BANCARIA,
                f"{c.banco.nombre_banco if c.banco else 'Banco'} — {c.nombre_titular or 's/n'}",
                _enmascarar_numero_cuenta(c.numero_cuenta) or "",
                "cuentas_bancarias",
                c.nombre_titular or "",
            )
            for c in filas
        ]

    @staticmethod
    def _cajas(session: Session, like: str, limite: int) -> list[ResultadoBusqueda]:
        filas = (
            session.query(Caja)
            .filter(Caja.nombre_caja.ilike(like, escape="\\"))
            .order_by(Caja.nombre_caja)
            .limit(limite)
            .all()
        )
        return [
            ResultadoBusqueda(TIPO_CAJA, c.nombre_caja or f"Caja {c.id_caja}", c.estado_caja or "", "cajas", "")
            for c in filas
        ]

    @staticmethod
    def _usuarios(session: Session, like: str, limite: int) -> list[ResultadoBusqueda]:
        filas = (
            session.query(Usuario)
            .filter(
                Usuario.nombre_usuario.ilike(like, escape="\\")
                | Usuario.nombre.ilike(like, escape="\\")
                | Usuario.apellido.ilike(like, escape="\\")
            )
            .order_by(Usuario.nombre_usuario)
            .limit(limite)
            .all()
        )
        return [
            ResultadoBusqueda(
                TIPO_USUARIO,
                " ".join(p for p in (u.nombre, u.apellido) if p) or u.nombre_usuario,
                u.nombre_usuario,
                "usuarios",
                u.nombre_usuario,
            )
            for u in filas
        ]
