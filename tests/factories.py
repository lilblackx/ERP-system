"""Helpers para crear datos base en los tests de servicios.

Insertan directamente contra los modelos (sin pasar por la capa de
servicios) para mantener cada test enfocado en el servicio bajo prueba.
"""

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
    Proveedor,
    Rol,
    RolPermiso,
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


def crear_cliente(session: Session, limite_credito: Decimal | int = 0, **overrides) -> Cliente:
    datos = {
        "codigo_cliente": _siguiente("CLI-"),
        "identificacion_cliente": _siguiente("V-"),
        "nombre_razon_social": "Cliente de prueba",
        "limite_credito": Decimal(str(limite_credito)),
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


def crear_caja(session: Session, **overrides) -> Caja:
    datos = {"nombre_caja": _siguiente("Caja-")}
    datos.update(overrides)
    caja = Caja(**datos)
    session.add(caja)
    session.commit()
    session.refresh(caja)
    return caja


def crear_vendedor(session: Session, **overrides) -> Vendedor:
    datos = {
        "codigo_vendedor": _siguiente("VEN-"),
        "identificacion_vendedor": _siguiente("V-"),
        "nombre_vendedor": "Vendedor de prueba",
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
