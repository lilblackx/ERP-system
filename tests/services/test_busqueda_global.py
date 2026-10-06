from datetime import date, timedelta
from decimal import Decimal

from app.services.busqueda_global import (
    LIMITE_POR_TIPO,
    TIPO_CLIENTE,
    TIPO_FACTURA,
    TIPO_PRODUCTO,
    TIPO_PROVEEDOR,
    BusquedaGlobalService,
)
from app.services.ventas import VentaService
from tests.factories import (
    asignar_permiso,
    crear_cliente,
    crear_permiso,
    crear_precio_producto,
    crear_producto,
    crear_proveedor,
    crear_rol,
    crear_usuario,
    crear_usuario_admin,
    crear_vendedor,
)


def _tipos(resultados):
    return {r.tipo for r in resultados}


def test_texto_muy_corto_no_busca(db_session):
    admin = crear_usuario_admin(db_session)
    crear_cliente(db_session, nombre_razon_social="Alimentos Andinos")

    assert BusquedaGlobalService.buscar(db_session, admin.id_usuario, "") == []
    assert BusquedaGlobalService.buscar(db_session, admin.id_usuario, "A") == []
    assert BusquedaGlobalService.buscar(db_session, admin.id_usuario, "  ") == []


def test_encuentra_cliente_por_nombre_sin_importar_mayusculas(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(
        db_session, nombre_razon_social="Alimentos Andinos C.A.", id_legal="J", identificacion_cliente="30489713"
    )

    resultados = BusquedaGlobalService.buscar(db_session, admin.id_usuario, "andinos")

    assert len(resultados) == 1
    r = resultados[0]
    assert r.tipo == TIPO_CLIENTE
    assert r.titulo == "Alimentos Andinos C.A."
    assert r.detalle == "J-30489713"
    assert r.modulo == "clientes"
    assert r.texto_busqueda == cliente.nombre_razon_social


def test_encuentra_cliente_por_identificacion(db_session):
    admin = crear_usuario_admin(db_session)
    crear_cliente(db_session, nombre_razon_social="Otro Cliente", identificacion_cliente="12345678")

    resultados = BusquedaGlobalService.buscar(db_session, admin.id_usuario, "12345678")

    assert [r.titulo for r in resultados] == ["Otro Cliente"]


def test_encuentra_producto_por_codigo_o_nombre(db_session):
    admin = crear_usuario_admin(db_session)
    crear_producto(db_session, cod_producto="ARR-001", nombre_producto="Arroz Blanco 1kg")

    por_nombre = BusquedaGlobalService.buscar(db_session, admin.id_usuario, "arroz")
    por_codigo = BusquedaGlobalService.buscar(db_session, admin.id_usuario, "ARR-0")

    for resultados in (por_nombre, por_codigo):
        assert len(resultados) == 1
        assert resultados[0].tipo == TIPO_PRODUCTO
        assert resultados[0].modulo == "inventario"
        assert resultados[0].texto_busqueda == "ARR-001"


def test_encuentra_proveedor(db_session):
    admin = crear_usuario_admin(db_session)
    crear_proveedor(db_session, nombre_razon_social="Distribuidora Central")

    resultados = BusquedaGlobalService.buscar(db_session, admin.id_usuario, "central")

    assert len(resultados) == 1
    assert resultados[0].tipo == TIPO_PROVEEDOR
    assert resultados[0].modulo == "proveedores"


def test_encuentra_factura_por_numero(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=100)
    crear_precio_producto(db_session, producto, "25.00")
    cliente = crear_cliente(db_session, nombre_razon_social="Cliente Facturado", limite_credito=Decimal("1000.00"))
    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "25.00"}],
        fecha_vencimiento=date.today() + timedelta(days=30),
    )

    resultados = BusquedaGlobalService.buscar(db_session, admin.id_usuario, factura.numero_factura)

    facturas = [r for r in resultados if r.tipo == TIPO_FACTURA]
    assert len(facturas) == 1
    assert facturas[0].modulo == "facturacion"
    assert facturas[0].texto_busqueda == factura.numero_factura
    assert "Cliente Facturado" in facturas[0].detalle


def test_comodines_de_like_se_buscan_literalmente(db_session):
    admin = crear_usuario_admin(db_session)
    crear_cliente(db_session, nombre_razon_social="Cliente Normal")

    # Sin escape, '%%' coincidiria con todo.
    assert BusquedaGlobalService.buscar(db_session, admin.id_usuario, "%%") == []
    assert BusquedaGlobalService.buscar(db_session, admin.id_usuario, "__") == []


def test_limita_resultados_por_tipo(db_session):
    admin = crear_usuario_admin(db_session)
    for i in range(LIMITE_POR_TIPO + 3):
        crear_cliente(db_session, nombre_razon_social=f"Mayorista {i:02d}")

    resultados = BusquedaGlobalService.buscar(db_session, admin.id_usuario, "mayorista")

    assert len(resultados) == LIMITE_POR_TIPO


def test_sin_permiso_de_un_modulo_no_aparecen_sus_resultados(db_session):
    rol = crear_rol(db_session)
    asignar_permiso(db_session, rol, crear_permiso(db_session, recurso="clientes", accion="ver"))
    usuario = crear_usuario(db_session, id_rol=rol.id_rol)
    crear_cliente(db_session, nombre_razon_social="Comercial Sur")
    crear_proveedor(db_session, nombre_razon_social="Comercial Norte")
    crear_producto(db_session, nombre_producto="Comercial Producto")

    resultados = BusquedaGlobalService.buscar(db_session, usuario.id_usuario, "comercial")

    assert _tipos(resultados) == {TIPO_CLIENTE}


def test_usuario_sin_ningun_permiso_no_ve_nada(db_session):
    rol = crear_rol(db_session)
    usuario = crear_usuario(db_session, id_rol=rol.id_rol)
    crear_cliente(db_session, nombre_razon_social="Comercial Sur")

    assert BusquedaGlobalService.buscar(db_session, usuario.id_usuario, "comercial") == []
