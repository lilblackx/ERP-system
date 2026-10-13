from datetime import date, timedelta
from decimal import Decimal

from app.services.busqueda_global import (
    LIMITE_POR_TIPO,
    TIPO_ACCION,
    TIPO_BANCO,
    TIPO_CAJA,
    TIPO_CLIENTE,
    TIPO_CUENTA_BANCARIA,
    TIPO_CXC,
    TIPO_FACTURA,
    TIPO_PRODUCTO,
    TIPO_PROVEEDOR,
    TIPO_USUARIO,
    TIPO_VENDEDOR,
    BusquedaGlobalService,
)
from app.services.ventas import VentaService
from tests.factories import (
    asignar_permiso,
    crear_banco,
    crear_caja,
    crear_cliente,
    crear_cuenta_bancaria,
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


# ── Mas entidades y acciones ────────────────────────────────────────────────


def test_encuentra_vendedor_banco_caja_y_usuario(db_session):
    admin = crear_usuario_admin(db_session)
    crear_vendedor(db_session, nombre_vendedor="Zoraida Vendedora")
    crear_banco(db_session, nombre_banco="Banco Zoraida", codigo_banco="0999")
    crear_caja(db_session, nombre_caja="Caja Zoraida")
    crear_usuario(db_session, nombre_usuario="zoraida.cajera", nombre="Zoraida", apellido="Perez", id_rol=admin.id_rol)

    resultados = BusquedaGlobalService.buscar(db_session, admin.id_usuario, "zoraida")

    por_tipo = {r.tipo: r for r in resultados}
    assert {TIPO_VENDEDOR, TIPO_BANCO, TIPO_CAJA, TIPO_USUARIO} <= set(por_tipo)
    assert por_tipo[TIPO_VENDEDOR].modulo == "vendedores"
    assert por_tipo[TIPO_BANCO].modulo == "bancos"
    assert por_tipo[TIPO_CAJA].modulo == "cajas"
    assert por_tipo[TIPO_USUARIO].titulo == "Zoraida Perez"
    assert por_tipo[TIPO_USUARIO].detalle == "zoraida.cajera"


def test_cuenta_bancaria_se_busca_por_titular_y_muestra_el_numero_enmascarado(db_session):
    admin = crear_usuario_admin(db_session)
    banco = crear_banco(db_session, nombre_banco="Banco Unico")
    crear_cuenta_bancaria(db_session, banco=banco, nombre_titular="Inversiones Quiroz", numero_cuenta="01020304050607")

    resultados = BusquedaGlobalService.buscar(db_session, admin.id_usuario, "quiroz")

    cuentas = [r for r in resultados if r.tipo == TIPO_CUENTA_BANCARIA]
    assert len(cuentas) == 1
    assert cuentas[0].modulo == "cuentas_bancarias"
    assert cuentas[0].detalle == "**********0607"
    assert "01020304050607" not in cuentas[0].titulo + cuentas[0].detalle
    # El numero completo no es un criterio de busqueda (mismo criterio que el modulo: va enmascarado).
    assert [
        r
        for r in BusquedaGlobalService.buscar(db_session, admin.id_usuario, "01020304")
        if r.tipo == TIPO_CUENTA_BANCARIA
    ] == []


def test_cuenta_por_cobrar_abierta_se_encuentra_por_cliente_pero_exige_tres_letras(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session)
    crear_precio_producto(db_session, producto, "25.00")
    cliente = crear_cliente(db_session, nombre_razon_social="Xylofonos del Sur", limite_credito=Decimal("1000.00"))
    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "25.00"}],
        fecha_vencimiento=date.today() + timedelta(days=30),
    )

    resultados = BusquedaGlobalService.buscar(db_session, admin.id_usuario, "xylofonos")
    cuentas = [r for r in resultados if r.tipo == TIPO_CXC]
    assert len(cuentas) == 1
    assert cuentas[0].modulo == "cuentas_por_cobrar"
    assert cuentas[0].texto_busqueda == "Xylofonos del Sur"
    assert "saldo $25.00" in cuentas[0].detalle

    # Con 2 letras solo se consultan los tipos "chicos": la cuenta por cobrar no aparece.
    assert [r for r in BusquedaGlobalService.buscar(db_session, admin.id_usuario, "xy") if r.tipo == TIPO_CXC] == []


def test_compras_y_cuentas_por_pagar_se_consultan_sin_error_aunque_no_haya_datos(db_session):
    admin = crear_usuario_admin(db_session)

    assert BusquedaGlobalService._compras(db_session, "%abc%", 4) == []
    assert BusquedaGlobalService._cuentas_por_pagar(db_session, "%abc%", 4) == []
    assert BusquedaGlobalService.buscar(db_session, admin.id_usuario, "abcdef") == []


def test_acciones_aparecen_primero_por_titulo_o_sinonimo(db_session):
    admin = crear_usuario_admin(db_session)
    crear_cliente(db_session, nombre_razon_social="Nueva Factura Ltda")

    por_titulo = BusquedaGlobalService.buscar(db_session, admin.id_usuario, "nueva fact")
    assert por_titulo[0].tipo == TIPO_ACCION
    assert por_titulo[0].accion == "nueva_factura"
    assert por_titulo[0].modulo == "facturacion"

    por_sinonimo = BusquedaGlobalService.buscar(db_session, admin.id_usuario, "facturar")
    assert [r.accion for r in por_sinonimo if r.tipo == TIPO_ACCION] == ["nueva_factura"]

    sin_tilde = BusquedaGlobalService.buscar(db_session, admin.id_usuario, "configuracion")
    assert {r.accion for r in sin_tilde if r.tipo == TIPO_ACCION} == {
        "config_empresa",
        "config_correo",
        "config_licencia",
    }
    smtp = BusquedaGlobalService.buscar(db_session, admin.id_usuario, "smtp")
    assert [r.accion for r in smtp] == ["config_correo"]


def test_una_accion_exige_el_permiso_de_crear(db_session):
    rol = crear_rol(db_session)
    asignar_permiso(db_session, rol, crear_permiso(db_session, recurso="ventas", accion="ver"))
    usuario = crear_usuario(db_session, id_rol=rol.id_rol)

    # Solo puede VER ventas, no crearlas: "Nueva factura" no se le ofrece.
    assert [
        r for r in BusquedaGlobalService.buscar(db_session, usuario.id_usuario, "nueva fact") if r.tipo == TIPO_ACCION
    ] == []

    asignar_permiso(db_session, rol, crear_permiso(db_session, recurso="ventas", accion="crear"))
    resultados = BusquedaGlobalService.buscar(db_session, usuario.id_usuario, "nueva fact")
    assert [r.accion for r in resultados if r.tipo == TIPO_ACCION] == ["nueva_factura"]
