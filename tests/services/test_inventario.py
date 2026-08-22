from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services.inventario import PrecioService, ProductoService
from tests.factories import crear_categoria, crear_producto


def _datos_producto(id_categoria: int, **overrides) -> dict:
    datos = {
        "id_categoria": id_categoria,
        "cod_producto": "SKU-001",
        "nombre_producto": "Producto de Prueba",
        "cantidad_unidad": Decimal("10.00"),
        "costo_producto": Decimal("5.00"),
    }
    datos.update(overrides)
    return datos


# --- ProductoService -----------------------------------------------------------


def test_crear_producto(db_session):
    categoria = crear_categoria(db_session)
    producto = ProductoService.crear(db_session, **_datos_producto(categoria.id_categoria))

    assert producto.id_producto is not None
    assert producto.cod_producto == "SKU-001"


def test_crear_producto_requiere_codigo(db_session):
    categoria = crear_categoria(db_session)
    with pytest.raises(ValueError, match="cod_producto"):
        ProductoService.crear(db_session, **_datos_producto(categoria.id_categoria, cod_producto=""))


def test_crear_producto_codigo_duplicado(db_session):
    categoria = crear_categoria(db_session)
    ProductoService.crear(db_session, **_datos_producto(categoria.id_categoria))

    with pytest.raises(ValueError, match="ya esta en uso"):
        ProductoService.crear(db_session, **_datos_producto(categoria.id_categoria, nombre_producto="Otro"))


def test_obtener_producto(db_session):
    producto = crear_producto(db_session)
    encontrado = ProductoService.obtener(db_session, producto.id_producto)
    assert encontrado is not None
    assert encontrado.id_producto == producto.id_producto


def test_obtener_producto_inexistente(db_session):
    assert ProductoService.obtener(db_session, 999999) is None


def test_actualizar_producto(db_session):
    producto = crear_producto(db_session)

    actualizado = ProductoService.actualizar(db_session, producto.id_producto, nombre_producto="Nuevo Nombre")

    assert actualizado.nombre_producto == "Nuevo Nombre"


def test_actualizar_producto_inexistente(db_session):
    with pytest.raises(ValueError, match="Producto no encontrado"):
        ProductoService.actualizar(db_session, 999999, nombre_producto="X")


def test_actualizar_producto_codigo_duplicado(db_session):
    categoria = crear_categoria(db_session)
    ProductoService.crear(db_session, **_datos_producto(categoria.id_categoria, cod_producto="SKU-001"))
    otro = ProductoService.crear(
        db_session, **_datos_producto(categoria.id_categoria, cod_producto="SKU-002", nombre_producto="Otro")
    )

    with pytest.raises(ValueError, match="ya esta en uso"):
        ProductoService.actualizar(db_session, otro.id_producto, cod_producto="SKU-001")


def test_actualizar_producto_mismo_codigo_no_falla(db_session):
    producto = crear_producto(db_session, cod_producto="SKU-999")

    actualizado = ProductoService.actualizar(db_session, producto.id_producto, cod_producto="SKU-999", nombre_producto="X")

    assert actualizado.cod_producto == "SKU-999"


def test_eliminar_producto(db_session):
    producto = crear_producto(db_session)

    ProductoService.eliminar(db_session, producto.id_producto)

    assert ProductoService.obtener(db_session, producto.id_producto) is None


def test_eliminar_producto_inexistente_no_falla(db_session):
    ProductoService.eliminar(db_session, 999999)


def test_buscar_por_codigo(db_session):
    crear_producto(db_session, cod_producto="ABC-123")
    crear_producto(db_session, cod_producto="XYZ-999")

    resultado = ProductoService.buscar(db_session, codigo="ABC")

    assert len(resultado) == 1
    assert resultado[0].cod_producto == "ABC-123"


def test_buscar_por_nombre(db_session):
    crear_producto(db_session, nombre_producto="Refresco Cola")
    crear_producto(db_session, nombre_producto="Agua Mineral")

    resultado = ProductoService.buscar(db_session, nombre="Cola")

    assert len(resultado) == 1
    assert resultado[0].nombre_producto == "Refresco Cola"


def test_buscar_por_categoria(db_session):
    categoria_a = crear_categoria(db_session)
    categoria_b = crear_categoria(db_session)
    crear_producto(db_session, categoria=categoria_a)
    crear_producto(db_session, categoria=categoria_b)

    resultado = ProductoService.buscar(db_session, id_categoria=categoria_a.id_categoria)

    assert len(resultado) == 1


def test_buscar_solo_con_stock(db_session):
    crear_producto(db_session, cantidad_unidad=0)
    crear_producto(db_session, cantidad_unidad=5)

    resultado = ProductoService.buscar(db_session, solo_con_stock=True)

    assert len(resultado) == 1
    assert resultado[0].cantidad_unidad == Decimal("5.00")


def test_obtener_alertas_stock_bajo(db_session):
    crear_producto(db_session, cantidad_unidad=3)
    crear_producto(db_session, cantidad_unidad=50)

    alertas = ProductoService.obtener_alertas_stock(db_session, limite_minimo=10)

    assert len(alertas["bajo_stock"]) == 1
    assert alertas["bajo_stock"][0].cantidad_unidad == Decimal("3.00")


def test_obtener_alertas_proximos_vencer(db_session):
    hoy = date.today()
    crear_producto(db_session, fecha_vencimiento=hoy + timedelta(days=5))
    crear_producto(db_session, fecha_vencimiento=hoy + timedelta(days=90))
    crear_producto(db_session, fecha_vencimiento=None)

    alertas = ProductoService.obtener_alertas_stock(db_session, dias_vencimiento=30)

    assert len(alertas["proximos_vencer"]) == 1


# --- PrecioService --------------------------------------------------------------


def test_establecer_precio_crea(db_session):
    producto = crear_producto(db_session, costo_producto=Decimal("10.00"))

    precio = PrecioService.establecer_precio(db_session, producto.id_producto, "DETAL", "15.00")

    assert precio.precio_venta == Decimal("15.00")
    assert precio.porcentaje_ganancia == Decimal("50.00")


def test_establecer_precio_actualiza_existente(db_session):
    producto = crear_producto(db_session, costo_producto=Decimal("10.00"))
    PrecioService.establecer_precio(db_session, producto.id_producto, "DETAL", "15.00")

    actualizado = PrecioService.establecer_precio(db_session, producto.id_producto, "DETAL", "20.00")

    assert actualizado.precio_venta == Decimal("20.00")
    precios = PrecioService.listar_precios(db_session, producto.id_producto)
    assert len(precios) == 1


def test_establecer_precio_tipo_invalido(db_session):
    producto = crear_producto(db_session)
    with pytest.raises(ValueError, match="tipo_precio invalido"):
        PrecioService.establecer_precio(db_session, producto.id_producto, "OTRO", "10.00")


def test_establecer_precio_producto_inexistente(db_session):
    with pytest.raises(ValueError, match="Producto no encontrado"):
        PrecioService.establecer_precio(db_session, 999999, "DETAL", "10.00")


def test_establecer_precio_costo_cero_margen_cero(db_session):
    producto = crear_producto(db_session, costo_producto=Decimal("0.00"))

    precio = PrecioService.establecer_precio(db_session, producto.id_producto, "DETAL", "10.00")

    assert precio.porcentaje_ganancia == Decimal("0.00")


def test_listar_precios_multiples_tipos(db_session):
    producto = crear_producto(db_session, costo_producto=Decimal("10.00"))
    PrecioService.establecer_precio(db_session, producto.id_producto, "DETAL", "15.00")
    PrecioService.establecer_precio(db_session, producto.id_producto, "MAYOR", "12.00")

    precios = PrecioService.listar_precios(db_session, producto.id_producto)

    assert len(precios) == 2
    assert {p.tipo_precio for p in precios} == {"DETAL", "MAYOR"}


def test_eliminar_precio(db_session):
    producto = crear_producto(db_session, costo_producto=Decimal("10.00"))
    precio = PrecioService.establecer_precio(db_session, producto.id_producto, "DETAL", "15.00")

    PrecioService.eliminar_precio(db_session, precio.id_producto_precio)

    assert PrecioService.listar_precios(db_session, producto.id_producto) == []


def test_eliminar_precio_inexistente_no_falla(db_session):
    PrecioService.eliminar_precio(db_session, 999999)
