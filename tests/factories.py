"""Helpers para crear datos base en los tests de servicios.

Insertan directamente contra los modelos (sin pasar por la capa de
servicios) para mantener cada test enfocado en el servicio bajo prueba.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import (
    Banco,
    Caja,
    Categoria,
    Cliente,
    CuentaBancaria,
    Inventario,
    Permiso,
    ProductoPrecio,
    Proveedor,
    Rol,
    RolPermiso,
    Ruta,
    Usuario,
    Vendedor,
)

_contador = {"n": 0}


def _siguiente(prefijo: str) -> str:
    _contador["n"] += 1
    return f"{prefijo}{_contador['n']:04d}"


def crear_categoria(session: Session, **overrides) -> Categoria:
    datos = {"nombre": _siguiente("CAT-")}
    datos.update(overrides)
    categoria = Categoria(**datos)
    session.add(categoria)
    session.commit()
    session.refresh(categoria)
    return categoria


def crear_producto(session: Session, cantidad_unidad: Decimal | int = 100, **overrides) -> Inventario:
    categoria = overrides.pop("categoria", None) or crear_categoria(session)
    datos = {
        "id_categoria": categoria.id_categoria,
        "cod_producto": _siguiente("PROD-"),
        "nombre_producto": "Producto de prueba",
        "cantidad_unidad": Decimal(str(cantidad_unidad)),
        "costo_producto": Decimal("10.00"),
    }
    datos.update(overrides)
    producto = Inventario(**datos)
    session.add(producto)
    session.commit()
    session.refresh(producto)
    return producto


def crear_precio_producto(
    session: Session, producto: Inventario, precio_venta: Decimal | int | str, **overrides
) -> ProductoPrecio:
    """Inserta directo (sin pasar por PrecioService) el precio de lista de un producto --
    tipo_precio fijo en 'UNICO' desde C14 (migrations/0011_consolidar_producto_precios.sql)."""
    datos = {
        "id_producto": producto.id_producto,
        "tipo_precio": "UNICO",
        "precio_venta": Decimal(str(precio_venta)),
    }
    datos.update(overrides)
    precio = ProductoPrecio(**datos)
    session.add(precio)
    session.commit()
    session.refresh(precio)
    return precio


def crear_cliente(session: Session, limite_credito: Decimal | int = 0, dias_credito: int = 30, **overrides) -> Cliente:
    """dias_credito default 30 (no 0, el default real de la columna): la mayoria de los
    tests de credito de la suite no les interesa este valor en si, solo necesitan un
    cliente que SI califique para credito (VentaService.emitir_factura exige
    dias_credito>0, ver migrations/0025_autorizacion_dias_credito.sql) -- los tests que
    prueban especificamente el bloqueo pasan dias_credito=0 explicito."""
    datos = {
        "codigo_cliente": _siguiente("CLI-"),
        "id_legal": "V",
        "identificacion_cliente": _siguiente(""),
        "nombre_razon_social": "Cliente de prueba",
        "limite_credito": Decimal(str(limite_credito)),
        "dias_credito": dias_credito,
    }
    datos.update(overrides)
    cliente = Cliente(**datos)
    session.add(cliente)
    session.commit()
    session.refresh(cliente)
    return cliente


def crear_proveedor(session: Session, limite_credito: Decimal | int = 0, **overrides) -> Proveedor:
    datos = {
        "codigo_proveedor": _siguiente("PROV-"),
        "identificacion_proveedor": _siguiente("J-"),
        "nombre_razon_social": "Proveedor de prueba",
        "limite_credito": Decimal(str(limite_credito)),
    }
    datos.update(overrides)
    proveedor = Proveedor(**datos)
    session.add(proveedor)
    session.commit()
    session.refresh(proveedor)
    return proveedor


def crear_banco(session: Session, **overrides) -> Banco:
    datos = {"nombre_banco": "Banco de prueba", "identificacion_banco": _siguiente("BCO-")}
    datos.update(overrides)
    banco = Banco(**datos)
    session.add(banco)
    session.commit()
    session.refresh(banco)
    return banco


def crear_cuenta_bancaria(session: Session, saldo_total_banco: Decimal | int = 0, **overrides) -> CuentaBancaria:
    banco = overrides.pop("banco", None) or crear_banco(session)
    datos = {
        "id_banco": banco.id_banco,
        "numero_cuenta": _siguiente("0001-"),
        "tipo_cuenta_banco": "corriente",
        "nombre_titular": "Distribuidora DJ",
        "saldo_total_banco": Decimal(str(saldo_total_banco)),
    }
    datos.update(overrides)
    cuenta = CuentaBancaria(**datos)
    session.add(cuenta)
    session.commit()
    session.refresh(cuenta)
    return cuenta


def pago_contado(session: Session, **overrides) -> list[dict]:
    """Forma de pago 'de sobra' para VentaService.emitir_factura(condicion_pago='contado')
    en tests que no ejercitan el circuito de pagos en si (comisiones, notas de credito,
    desempeno de vendedor, etc.): efectivo por un monto grande en USD contra una caja
    nueva ya abierta con saldo de apertura igualmente generoso, para no tener que calcular
    el total exacto de cada factura. El sobrante (vuelto) ya no se descarta en silencio
    (ver migrations/0027_vuelto_factura.sql) -- pagar en efectivo hace que
    VentaService.emitir_factura() infiera metodo_vuelto='efectivo' contra esta misma caja
    automaticamente cuando el caller no indica uno explicito (unica caja usada en pagos),
    asi que estos tests siguen sin necesitar saber nada de vuelto."""
    caja = overrides.pop("caja", None)
    if caja is None:
        caja = Caja(
            nombre_caja=_siguiente("Caja-pago-contado-"),
            estado_caja="ABIERTA",
            saldo_apertura=Decimal("9999999999.99"),
            fecha_apertura=datetime.now(),
        )
        session.add(caja)
        session.commit()
        session.refresh(caja)
    linea = {
        "metodo_pago": "efectivo",
        "moneda": "USD",
        "monto_moneda_origen": Decimal("999999.99"),
        "id_caja": caja.id_caja,
    }
    linea.update(overrides)
    return [linea]


def crear_caja(session: Session, **overrides) -> Caja:
    datos = {"nombre_caja": _siguiente("Caja-")}
    datos.update(overrides)
    caja = Caja(**datos)
    session.add(caja)
    session.commit()
    session.refresh(caja)
    return caja


def crear_ruta(session: Session, **overrides) -> Ruta:
    datos = {"nombre_ruta": _siguiente("RUTA-")}
    datos.update(overrides)
    ruta = Ruta(**datos)
    session.add(ruta)
    session.commit()
    session.refresh(ruta)
    return ruta


def crear_vendedor(session: Session, **overrides) -> Vendedor:
    ruta = overrides.pop("ruta", None) or crear_ruta(session)
    datos = {
        "codigo_vendedor": _siguiente("VEN-"),
        "identificacion_vendedor": _siguiente("V-"),
        "nombre_vendedor": "Vendedor de prueba",
        "id_ruta": ruta.id_ruta,
    }
    datos.update(overrides)
    vendedor = Vendedor(**datos)
    session.add(vendedor)
    session.commit()
    session.refresh(vendedor)
    return vendedor


def crear_rol(session: Session, **overrides) -> Rol:
    datos = {"nombre": _siguiente("ROL-")}
    datos.update(overrides)
    rol = Rol(**datos)
    session.add(rol)
    session.commit()
    session.refresh(rol)
    return rol


def crear_permiso(session: Session, **overrides) -> Permiso:
    datos = {"recurso": _siguiente("recurso-"), "accion": "crear"}
    datos.update(overrides)
    permiso = Permiso(**datos)
    session.add(permiso)
    session.commit()
    session.refresh(permiso)
    return permiso


def asignar_permiso(session: Session, rol: Rol, permiso: Permiso) -> RolPermiso:
    rol_permiso = RolPermiso(id_rol=rol.id_rol, id_permiso=permiso.id_permiso)
    session.add(rol_permiso)
    session.commit()
    return rol_permiso


def crear_usuario(session: Session, **overrides) -> Usuario:
    """Inserta un Usuario minimo directamente (sin hashear clave real): para tests que
    solo necesitan un id_usuario valido como FK, no para probar autenticacion."""
    datos = {"nombre_usuario": _siguiente("user-"), "clave": "placeholder"}
    datos.update(overrides)
    usuario = Usuario(**datos)
    session.add(usuario)
    session.commit()
    session.refresh(usuario)
    return usuario


def crear_usuario_admin(session: Session, **overrides) -> Usuario:
    """Usuario con rol ADMIN: bypassa PermisoService.require_permiso() por completo (ver
    la nota de bypass en app/services/permisos.py). Helper para tests que solo necesitan
    un actor autorizado como para poder ejercitar el resto del metodo bajo prueba -- para
    probar la matriz de permisos en si (bloqueo por falta de permiso), usar crear_rol()
    + crear_permiso() + asignar_permiso() como en tests/services/test_permisos.py."""
    rol = session.query(Rol).filter_by(nombre="ADMIN").first()
    if rol is None:
        rol = crear_rol(session, nombre="ADMIN")
    return crear_usuario(session, id_rol=rol.id_rol, **overrides)
