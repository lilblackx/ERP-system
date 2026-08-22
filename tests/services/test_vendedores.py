from datetime import date
from decimal import Decimal

import pytest

from app.services.vendedores import VendedorService
from app.services.ventas import VentaService
from tests.factories import crear_cliente, crear_producto


def _datos_vendedor(**overrides) -> dict:
    datos = {
        "codigo_vendedor": "VEN-001",
        "identificacion_vendedor": "V-11111111",
        "nombre_vendedor": "Vendedor de Prueba",
    }
    datos.update(overrides)
    return datos


def test_crear_vendedor(db_session):
    vendedor = VendedorService.crear(db_session, **_datos_vendedor())
    assert vendedor.id_vendedor is not None
    assert vendedor.nombre_vendedor == "Vendedor de Prueba"


def test_obtener_vendedor(db_session):
    vendedor = VendedorService.crear(db_session, **_datos_vendedor())
    encontrado = VendedorService.obtener(db_session, vendedor.id_vendedor)
    assert encontrado is not None
    assert encontrado.id_vendedor == vendedor.id_vendedor


def test_obtener_vendedor_inexistente(db_session):
    assert VendedorService.obtener(db_session, 999999) is None


def test_listar_vendedores_filtra_por_texto(db_session):
    VendedorService.crear(db_session, **_datos_vendedor())
    VendedorService.crear(
        db_session, **_datos_vendedor(codigo_vendedor="VEN-002", identificacion_vendedor="V-22222222", nombre_vendedor="Otro")
    )

    resultado = VendedorService.listar(db_session, texto_busqueda="Prueba")

    assert len(resultado) == 1
    assert resultado[0].nombre_vendedor == "Vendedor de Prueba"


def test_actualizar_vendedor(db_session):
    vendedor = VendedorService.crear(db_session, **_datos_vendedor())

    actualizado = VendedorService.actualizar(db_session, vendedor.id_vendedor, nombre_vendedor="Nombre Nuevo")

    assert actualizado.nombre_vendedor == "Nombre Nuevo"


def test_actualizar_vendedor_inexistente(db_session):
    with pytest.raises(ValueError, match="Vendedor no encontrado"):
        VendedorService.actualizar(db_session, 999999, nombre_vendedor="X")


def test_eliminar_vendedor(db_session):
    vendedor = VendedorService.crear(db_session, **_datos_vendedor())

    VendedorService.eliminar(db_session, vendedor.id_vendedor)

    assert VendedorService.listar(db_session) == []


def test_eliminar_vendedor_inexistente_no_falla(db_session):
    VendedorService.eliminar(db_session, 999999)


# --- obtener_desempeno_mes -----------------------------------------------------


def test_desempeno_mes_vendedor_inexistente(db_session):
    with pytest.raises(ValueError, match="Vendedor no encontrado"):
        VendedorService.obtener_desempeno_mes(db_session, 999999, anio=2026, mes=8)


def test_desempeno_mes_suma_ventas_y_excluye_anuladas(db_session):
    vendedor = VendedorService.crear(db_session, **_datos_vendedor())
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, vendedor_cliente=vendedor.id_vendedor)

    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=None,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "10.00"}],
    )
    factura_anulada = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=None,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
    )
    VentaService.anular_factura(db_session, factura_anulada.id_factura, id_usuario=None, motivo="Error de carga")

    hoy = date.today()
    resultado = VendedorService.obtener_desempeno_mes(db_session, vendedor.id_vendedor, anio=hoy.year, mes=hoy.month)

    assert resultado["total_vendido"] == Decimal("20.00")
    assert resultado["cantidad_facturas"] == 1
    assert resultado["total_clientes_asignados"] == 1


def test_desempeno_mes_sin_ventas_en_el_periodo(db_session):
    vendedor = VendedorService.crear(db_session, **_datos_vendedor())

    resultado = VendedorService.obtener_desempeno_mes(db_session, vendedor.id_vendedor, anio=2020, mes=1)

    assert resultado["total_vendido"] == 0
    assert resultado["cantidad_facturas"] == 0
    assert resultado["total_clientes_asignados"] == 0
