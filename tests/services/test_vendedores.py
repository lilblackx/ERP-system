from datetime import date
from decimal import Decimal

import pytest

from app.services.permisos import PermisoDenegadoError
from app.services.vendedores import VendedorService
from app.services.ventas import VentaService
from tests.factories import crear_cliente, crear_producto, crear_usuario_admin, pago_contado


def _datos_vendedor(**overrides) -> dict:
    datos = {
        "codigo_vendedor": "VEN-001",
        "identificacion_vendedor": "V-11111111",
        "nombre_vendedor": "Vendedor de Prueba",
    }
    datos.update(overrides)
    return datos


def test_crear_vendedor(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(creado_por=admin.id_usuario))
    assert vendedor.id_vendedor is not None
    assert vendedor.nombre_vendedor == "Vendedor de Prueba"


def test_crear_vendedor_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        VendedorService.crear(db_session, **_datos_vendedor())


def test_obtener_vendedor(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(creado_por=admin.id_usuario))
    encontrado = VendedorService.obtener(db_session, vendedor.id_vendedor, id_usuario=admin.id_usuario)
    assert encontrado is not None
    assert encontrado.id_vendedor == vendedor.id_vendedor


def test_obtener_vendedor_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    assert VendedorService.obtener(db_session, 999999, id_usuario=admin.id_usuario) is None


def test_obtener_vendedor_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        VendedorService.obtener(db_session, 999999)


def test_listar_vendedores_filtra_por_texto(db_session):
    admin = crear_usuario_admin(db_session)
    VendedorService.crear(db_session, **_datos_vendedor(creado_por=admin.id_usuario))
    VendedorService.crear(
        db_session,
        **_datos_vendedor(
            codigo_vendedor="VEN-002",
            identificacion_vendedor="V-22222222",
            nombre_vendedor="Otro",
            creado_por=admin.id_usuario,
        ),
    )

    resultado = VendedorService.listar(db_session, texto_busqueda="Prueba", id_usuario=admin.id_usuario)

    assert len(resultado) == 1
    assert resultado[0].nombre_vendedor == "Vendedor de Prueba"


def test_listar_vendedores_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        VendedorService.listar(db_session)


def test_actualizar_vendedor(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(creado_por=admin.id_usuario))

    actualizado = VendedorService.actualizar(
        db_session, vendedor.id_vendedor, id_usuario=admin.id_usuario, nombre_vendedor="Nombre Nuevo"
    )

    assert actualizado.nombre_vendedor == "Nombre Nuevo"


def test_actualizar_vendedor_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(creado_por=admin.id_usuario))

    with pytest.raises(PermisoDenegadoError):
        VendedorService.actualizar(db_session, vendedor.id_vendedor, nombre_vendedor="X")


def test_actualizar_vendedor_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Vendedor no encontrado"):
        VendedorService.actualizar(db_session, 999999, id_usuario=admin.id_usuario, nombre_vendedor="X")


def test_eliminar_vendedor_siempre_falla_para_proteger_integridad(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="No se puede eliminar"):
        VendedorService.eliminar(db_session, vendedor.id_vendedor, id_usuario=admin.id_usuario)

    assert len(VendedorService.listar(db_session, id_usuario=admin.id_usuario)) == 1


def test_eliminar_vendedor_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(creado_por=admin.id_usuario))

    with pytest.raises(PermisoDenegadoError):
        VendedorService.eliminar(db_session, vendedor.id_vendedor)


def test_cambiar_estado_vendedor_desactiva(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(creado_por=admin.id_usuario))

    actualizado = VendedorService.cambiar_estado(
        db_session, vendedor.id_vendedor, "INACTIVO", id_usuario=admin.id_usuario
    )

    assert actualizado.estado_vendedor == "INACTIVO"


def test_cambiar_estado_vendedor_estado_invalido(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="nuevo_estado"):
        VendedorService.cambiar_estado(db_session, vendedor.id_vendedor, "BLOQUEADO", id_usuario=admin.id_usuario)


def test_cambiar_estado_vendedor_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Vendedor no encontrado"):
        VendedorService.cambiar_estado(db_session, 999999, "INACTIVO", id_usuario=admin.id_usuario)


def test_cambiar_estado_vendedor_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(creado_por=admin.id_usuario))

    with pytest.raises(PermisoDenegadoError):
        VendedorService.cambiar_estado(db_session, vendedor.id_vendedor, "INACTIVO")


# --- obtener_desempeno_mes -----------------------------------------------------


def test_desempeno_mes_vendedor_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Vendedor no encontrado"):
        VendedorService.obtener_desempeno_mes(db_session, 999999, anio=2026, mes=8, id_usuario=admin.id_usuario)


def test_desempeno_mes_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        VendedorService.obtener_desempeno_mes(db_session, 999999, anio=2026, mes=8)


def test_desempeno_mes_suma_ventas_y_excluye_anuladas(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(creado_por=admin.id_usuario))
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, vendedor_cliente=vendedor.id_vendedor)

    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "10.00"}],
        pagos=pago_contado(db_session),
    )
    factura_anulada = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
        pagos=pago_contado(db_session),
    )
    VentaService.anular_factura(
        db_session, factura_anulada.id_factura, id_usuario=admin.id_usuario, motivo="Error de carga"
    )

    hoy = date.today()
    resultado = VendedorService.obtener_desempeno_mes(
        db_session, vendedor.id_vendedor, anio=hoy.year, mes=hoy.month, id_usuario=admin.id_usuario
    )

    assert resultado["total_vendido"] == Decimal("20.00")
    assert resultado["cantidad_facturas"] == 1
    assert resultado["total_clientes_asignados"] == 1


def test_desempeno_mes_sin_ventas_en_el_periodo(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(creado_por=admin.id_usuario))

    resultado = VendedorService.obtener_desempeno_mes(
        db_session, vendedor.id_vendedor, anio=2020, mes=1, id_usuario=admin.id_usuario
    )

    assert resultado["total_vendido"] == 0
    assert resultado["cantidad_facturas"] == 0
    assert resultado["total_clientes_asignados"] == 0
