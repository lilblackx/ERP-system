"""Quien puede ver el historial de un cliente (app/services/historial_cliente.py).

El historial trae facturas, pagos y saldos de un cliente. Antes el servicio no recibia al usuario ni pedia ningun
permiso: lo protegia solo que el boton estuviera en el panel de Clientes, pero cualquier llamada directa devolvia todo
(el estado de cuenta del reporte, en cambio, si pide permiso y bloquea a los vendedores). Ahora pide `clientes:ver` y, a
un usuario vendedor, solo le deja ver el historial de los clientes que tiene asignados.
"""

from decimal import Decimal

import pytest

from app.services.historial_cliente import (
    obtener_historial_cliente,
    obtener_saldo_total_pendiente,
    obtener_saldo_total_positivo,
)
from app.services.permisos import PermisoDenegadoError
from app.services.ventas import VentaService
from tests.factories import (
    asignar_permiso,
    crear_cliente,
    crear_permiso,
    crear_precio_producto,
    crear_producto,
    crear_rol,
    crear_usuario,
    crear_usuario_admin,
    crear_vendedor,
)

CONSULTAS = [obtener_historial_cliente, obtener_saldo_total_pendiente, obtener_saldo_total_positivo]


def _usuario_con(db, *permisos, **datos_usuario):
    """Usuario con un rol que solo tiene los permisos (recurso, accion) indicados."""
    rol = crear_rol(db)
    for recurso, accion in permisos:
        asignar_permiso(db, rol, crear_permiso(db, recurso=recurso, accion=accion))
    return crear_usuario(db, id_rol=rol.id_rol, **datos_usuario)


def _cliente_con_factura(db, admin, vendedor_cliente=None):
    vendedor = crear_vendedor(db)
    producto = crear_producto(db, cantidad_unidad=50)
    crear_precio_producto(db, producto, "20.00")
    cliente = crear_cliente(
        db,
        limite_credito=Decimal("1000.00"),
        vendedor_cliente=vendedor_cliente.id_vendedor if vendedor_cliente else None,
    )
    VentaService.emitir_factura(
        db,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "20.00"}],
    )
    return cliente


@pytest.mark.parametrize("consulta", CONSULTAS)
def test_sin_usuario_no_se_ve_el_historial_ni_los_saldos(db_session, consulta):
    admin = crear_usuario_admin(db_session)
    cliente = _cliente_con_factura(db_session, admin)

    with pytest.raises(PermisoDenegadoError):
        consulta(db_session, cliente.id_cliente, None)


@pytest.mark.parametrize("consulta", CONSULTAS)
def test_un_usuario_sin_clientes_ver_no_ve_el_historial_ni_los_saldos(db_session, consulta):
    admin = crear_usuario_admin(db_session)
    cliente = _cliente_con_factura(db_session, admin)
    sin_permiso = _usuario_con(db_session, ("ventas", "ver"), ("pagos", "ver"))  # ver ventas y pagos no alcanza

    with pytest.raises(PermisoDenegadoError):
        consulta(db_session, cliente.id_cliente, sin_permiso.id_usuario)


def test_un_usuario_con_clientes_ver_ve_el_historial_de_cualquier_cliente(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = _cliente_con_factura(db_session, admin)
    cajero = _usuario_con(db_session, ("clientes", "ver"))

    historial = obtener_historial_cliente(db_session, cliente.id_cliente, cajero.id_usuario)

    assert [i["tipo_transaccion"] for i in historial] == ["factura"]
    assert obtener_saldo_total_pendiente(db_session, cliente.id_cliente, cajero.id_usuario) == Decimal("40.00")


def test_un_administrador_ve_el_historial_de_cualquier_cliente(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = _cliente_con_factura(db_session, admin)

    assert obtener_historial_cliente(db_session, cliente.id_cliente, admin.id_usuario)


@pytest.mark.parametrize("consulta", CONSULTAS)
def test_un_vendedor_solo_ve_el_historial_de_sus_clientes(db_session, consulta):
    admin = crear_usuario_admin(db_session)
    mio, otro = crear_vendedor(db_session), crear_vendedor(db_session)
    usuario = _usuario_con(db_session, ("clientes", "ver"), id_vendedor_usuario=mio.id_vendedor)
    cliente_mio = _cliente_con_factura(db_session, admin, vendedor_cliente=mio)
    cliente_ajeno = _cliente_con_factura(db_session, admin, vendedor_cliente=otro)
    cliente_sin_vendedor = _cliente_con_factura(db_session, admin)

    consulta(db_session, cliente_mio.id_cliente, usuario.id_usuario)  # el suyo: sin error
    with pytest.raises(PermisoDenegadoError, match="no esta asignado"):
        consulta(db_session, cliente_ajeno.id_cliente, usuario.id_usuario)
    with pytest.raises(PermisoDenegadoError, match="no esta asignado"):
        consulta(db_session, cliente_sin_vendedor.id_cliente, usuario.id_usuario)


def test_un_vendedor_sin_clientes_ver_no_ve_ni_el_de_sus_clientes(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    usuario = _usuario_con(db_session, ("ventas", "ver"), id_vendedor_usuario=vendedor.id_vendedor)
    cliente = _cliente_con_factura(db_session, admin, vendedor_cliente=vendedor)

    with pytest.raises(PermisoDenegadoError):
        obtener_historial_cliente(db_session, cliente.id_cliente, usuario.id_usuario)
