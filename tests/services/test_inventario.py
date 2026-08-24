from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.db.models import ProductoPrecio
from app.services.inventario import PrecioService, ProductoService
from app.services.permisos import PermisoDenegadoError
from tests.factories import crear_categoria, crear_producto, crear_usuario_admin


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
    admin = crear_usuario_admin(db_session)
    categoria = crear_categoria(db_session)
    producto = ProductoService.crear(db_session, **_datos_producto(categoria.id_categoria, creado_por=admin.id_usuario))

    assert producto.id_producto is not None
    assert producto.cod_producto == "SKU-001"


def test_crear_producto_sin_usuario_autorizado_falla(db_session):
    categoria = crear_categoria(db_session)
    with pytest.raises(PermisoDenegadoError):
        ProductoService.crear(db_session, **_datos_producto(categoria.id_categoria))


def test_crear_producto_requiere_codigo(db_session):
    admin = crear_usuario_admin(db_session)
    categoria = crear_categoria(db_session)
    with pytest.raises(ValueError, match="cod_producto"):
        ProductoService.crear(
            db_session, **_datos_producto(categoria.id_categoria, cod_producto="", creado_por=admin.id_usuario)
        )


def test_crear_producto_codigo_duplicado(db_session):
    admin = crear_usuario_admin(db_session)
    categoria = crear_categoria(db_session)
    ProductoService.crear(db_session, **_datos_producto(categoria.id_categoria, creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="ya esta en uso"):
        ProductoService.crear(
            db_session, **_datos_producto(categoria.id_categoria, nombre_producto="Otro", creado_por=admin.id_usuario)
        )


def test_obtener_producto(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    encontrado = ProductoService.obtener(db_session, producto.id_producto, id_usuario=admin.id_usuario)
    assert encontrado is not None
    assert encontrado.id_producto == producto.id_producto


def test_obtener_producto_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    assert ProductoService.obtener(db_session, 999999, id_usuario=admin.id_usuario) is None


def test_obtener_producto_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ProductoService.obtener(db_session, 999999)


def test_actualizar_producto(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)

    actualizado = ProductoService.actualizar(
        db_session, producto.id_producto, id_usuario=admin.id_usuario, nombre_producto="Nuevo Nombre"
    )

    assert actualizado.nombre_producto == "Nuevo Nombre"


def test_actualizar_producto_sin_usuario_autorizado_falla(db_session):
    producto = crear_producto(db_session)
    with pytest.raises(PermisoDenegadoError):
        ProductoService.actualizar(db_session, producto.id_producto, nombre_producto="Nuevo Nombre")


def test_actualizar_producto_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Producto no encontrado"):
        ProductoService.actualizar(db_session, 999999, id_usuario=admin.id_usuario, nombre_producto="X")


def test_actualizar_producto_codigo_duplicado(db_session):
    admin = crear_usuario_admin(db_session)
    categoria = crear_categoria(db_session)
    ProductoService.crear(
        db_session, **_datos_producto(categoria.id_categoria, cod_producto="SKU-001", creado_por=admin.id_usuario)
    )
    otro = ProductoService.crear(
        db_session,
        **_datos_producto(
            categoria.id_categoria, cod_producto="SKU-002", nombre_producto="Otro", creado_por=admin.id_usuario
        ),
    )

    with pytest.raises(ValueError, match="ya esta en uso"):
        ProductoService.actualizar(db_session, otro.id_producto, id_usuario=admin.id_usuario, cod_producto="SKU-001")


def test_actualizar_producto_mismo_codigo_no_falla(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cod_producto="SKU-999")

    actualizado = ProductoService.actualizar(
        db_session, producto.id_producto, id_usuario=admin.id_usuario, cod_producto="SKU-999", nombre_producto="X"
    )

    assert actualizado.cod_producto == "SKU-999"


def test_eliminar_producto_siempre_falla_para_proteger_integridad(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)

    with pytest.raises(ValueError, match="No se puede eliminar"):
        ProductoService.eliminar(db_session, producto.id_producto, id_usuario=admin.id_usuario)

    assert ProductoService.obtener(db_session, producto.id_producto, id_usuario=admin.id_usuario) is not None


def test_eliminar_producto_sin_usuario_autorizado_falla(db_session):
    producto = crear_producto(db_session)
    with pytest.raises(PermisoDenegadoError):
        ProductoService.eliminar(db_session, producto.id_producto)


def test_cambiar_estado_producto_desactiva(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)

    actualizado = ProductoService.cambiar_estado(
        db_session, producto.id_producto, "INACTIVO", id_usuario=admin.id_usuario
    )

    assert actualizado.estado_producto == "INACTIVO"


def test_cambiar_estado_producto_estado_invalido(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)

    with pytest.raises(ValueError, match="nuevo_estado"):
        ProductoService.cambiar_estado(db_session, producto.id_producto, "BLOQUEADO", id_usuario=admin.id_usuario)


def test_cambiar_estado_producto_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Producto no encontrado"):
        ProductoService.cambiar_estado(db_session, 999999, "INACTIVO", id_usuario=admin.id_usuario)


def test_cambiar_estado_producto_sin_usuario_autorizado_falla(db_session):
    producto = crear_producto(db_session)
    with pytest.raises(PermisoDenegadoError):
        ProductoService.cambiar_estado(db_session, producto.id_producto, "INACTIVO")


def test_buscar_por_codigo(db_session):
    admin = crear_usuario_admin(db_session)
    crear_producto(db_session, cod_producto="ABC-123")
    crear_producto(db_session, cod_producto="XYZ-999")

    resultado = ProductoService.buscar(db_session, codigo="ABC", id_usuario=admin.id_usuario)

    assert resultado["total"] == 1
    assert resultado["items"][0].cod_producto == "ABC-123"


def test_buscar_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ProductoService.buscar(db_session, codigo="ABC")


def test_buscar_por_nombre(db_session):
    admin = crear_usuario_admin(db_session)
    crear_producto(db_session, nombre_producto="Refresco Cola")
    crear_producto(db_session, nombre_producto="Agua Mineral")

    resultado = ProductoService.buscar(db_session, nombre="Cola", id_usuario=admin.id_usuario)

    assert resultado["total"] == 1
    assert resultado["items"][0].nombre_producto == "Refresco Cola"


def test_buscar_por_texto_incluye_codigo_o_nombre(db_session):
    admin = crear_usuario_admin(db_session)
    crear_producto(db_session, cod_producto="COLA-001", nombre_producto="Refresco Cola")
    crear_producto(db_session, cod_producto="AGUA-002", nombre_producto="Agua Mineral")

    por_codigo = ProductoService.buscar(db_session, texto="COLA-001", id_usuario=admin.id_usuario)
    por_nombre = ProductoService.buscar(db_session, texto="Mineral", id_usuario=admin.id_usuario)

    assert por_codigo["total"] == 1
    assert por_codigo["items"][0].nombre_producto == "Refresco Cola"
    assert por_nombre["total"] == 1
    assert por_nombre["items"][0].cod_producto == "AGUA-002"


def test_buscar_por_categoria(db_session):
    admin = crear_usuario_admin(db_session)
    categoria_a = crear_categoria(db_session)
    categoria_b = crear_categoria(db_session)
    crear_producto(db_session, categoria=categoria_a)
    crear_producto(db_session, categoria=categoria_b)

    resultado = ProductoService.buscar(db_session, id_categoria=categoria_a.id_categoria, id_usuario=admin.id_usuario)

    assert resultado["total"] == 1


def test_buscar_solo_con_stock(db_session):
    admin = crear_usuario_admin(db_session)
    crear_producto(db_session, cantidad_unidad=0)
    crear_producto(db_session, cantidad_unidad=5)

    resultado = ProductoService.buscar(db_session, solo_con_stock=True, id_usuario=admin.id_usuario)

    assert resultado["total"] == 1
    assert resultado["items"][0].cantidad_unidad == Decimal("5.00")


def test_buscar_pagina_resultados(db_session):
    admin = crear_usuario_admin(db_session)
    for i in range(5):
        crear_producto(db_session, cod_producto=f"PAG-{i:03d}", nombre_producto=f"Producto {i}")

    pagina_1 = ProductoService.buscar(db_session, pagina=1, por_pagina=2, id_usuario=admin.id_usuario)
    pagina_2 = ProductoService.buscar(db_session, pagina=2, por_pagina=2, id_usuario=admin.id_usuario)

    assert pagina_1["total"] == 5
    assert len(pagina_1["items"]) == 2
    assert len(pagina_2["items"]) == 2
    assert {p.cod_producto for p in pagina_1["items"]}.isdisjoint({p.cod_producto for p in pagina_2["items"]})


def test_obtener_alertas_stock_bajo(db_session):
    admin = crear_usuario_admin(db_session)
    crear_producto(db_session, cantidad_unidad=3)
    crear_producto(db_session, cantidad_unidad=50)

    alertas = ProductoService.obtener_alertas_stock(db_session, limite_minimo=10, id_usuario=admin.id_usuario)

    assert len(alertas["bajo_stock"]) == 1
    assert alertas["bajo_stock"][0].cantidad_unidad == Decimal("3.00")


def test_obtener_alertas_stock_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ProductoService.obtener_alertas_stock(db_session, limite_minimo=10)


def test_obtener_alertas_stock_bajo_excluye_inactivos(db_session):
    """C21: un producto descontinuado (INACTIVO) no deberia seguir generando alerta de
    stock bajo para siempre."""
    admin = crear_usuario_admin(db_session)
    crear_producto(db_session, cantidad_unidad=3)
    crear_producto(db_session, cantidad_unidad=3, estado_producto="INACTIVO")

    alertas = ProductoService.obtener_alertas_stock(db_session, limite_minimo=10, id_usuario=admin.id_usuario)

    assert len(alertas["bajo_stock"]) == 1
    assert alertas["bajo_stock"][0].estado_producto == "ACTIVO"


def test_obtener_alertas_proximos_vencer(db_session):
    admin = crear_usuario_admin(db_session)
    hoy = date.today()
    crear_producto(db_session, fecha_vencimiento=hoy + timedelta(days=5))
    crear_producto(db_session, fecha_vencimiento=hoy + timedelta(days=90))
    crear_producto(db_session, fecha_vencimiento=None)

    alertas = ProductoService.obtener_alertas_stock(db_session, dias_vencimiento=30, id_usuario=admin.id_usuario)

    assert len(alertas["proximos_vencer"]) == 1


def test_obtener_alertas_proximos_vencer_excluye_inactivos(db_session):
    admin = crear_usuario_admin(db_session)
    hoy = date.today()
    crear_producto(db_session, fecha_vencimiento=hoy + timedelta(days=5), estado_producto="INACTIVO")

    alertas = ProductoService.obtener_alertas_stock(db_session, dias_vencimiento=30, id_usuario=admin.id_usuario)

    assert len(alertas["proximos_vencer"]) == 0


# --- PrecioService --------------------------------------------------------------


def test_establecer_precio_crea(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, costo_producto=Decimal("10.00"))

    precio = PrecioService.establecer_precio(db_session, producto.id_producto, "15.00", id_usuario=admin.id_usuario)

    assert precio.precio_venta == Decimal("15.00")
    assert precio.porcentaje_ganancia == Decimal("50.00")
    assert precio.tipo_precio == "UNICO"


def test_establecer_precio_sin_usuario_autorizado_falla(db_session):
    producto = crear_producto(db_session, costo_producto=Decimal("10.00"))
    with pytest.raises(PermisoDenegadoError):
        PrecioService.establecer_precio(db_session, producto.id_producto, "15.00")


def test_establecer_precio_actualiza_existente(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, costo_producto=Decimal("10.00"))
    PrecioService.establecer_precio(db_session, producto.id_producto, "15.00", id_usuario=admin.id_usuario)

    actualizado = PrecioService.establecer_precio(
        db_session, producto.id_producto, "20.00", id_usuario=admin.id_usuario
    )

    assert actualizado.precio_venta == Decimal("20.00")
    precio = PrecioService.obtener_precio(db_session, producto.id_producto, id_usuario=admin.id_usuario)
    assert precio.precio_venta == Decimal("20.00")


def test_establecer_precio_segunda_vez_actualiza_no_duplica(db_session):
    """C14: un solo precio por producto -- establecer_precio() dos veces no crea una
    segunda fila (invariante que ademas garantiza UQ_producto_tipo_precio a nivel de BD,
    ver migrations/0011_consolidar_producto_precios.sql)."""
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, costo_producto=Decimal("10.00"))
    PrecioService.establecer_precio(db_session, producto.id_producto, "15.00", id_usuario=admin.id_usuario)
    PrecioService.establecer_precio(db_session, producto.id_producto, "18.00", id_usuario=admin.id_usuario)

    total = db_session.query(ProductoPrecio).filter(ProductoPrecio.id_producto == producto.id_producto).count()

    assert total == 1


def test_establecer_precio_producto_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Producto no encontrado"):
        PrecioService.establecer_precio(db_session, 999999, "10.00", id_usuario=admin.id_usuario)


def test_establecer_precio_producto_inactivo_falla(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, costo_producto=Decimal("10.00"), estado_producto="INACTIVO")
    with pytest.raises(ValueError, match="inactivo"):
        PrecioService.establecer_precio(db_session, producto.id_producto, "15.00", id_usuario=admin.id_usuario)


def test_establecer_precio_costo_cero_margen_cero(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, costo_producto=Decimal("0.00"))

    precio = PrecioService.establecer_precio(db_session, producto.id_producto, "10.00", id_usuario=admin.id_usuario)

    assert precio.porcentaje_ganancia == Decimal("0.00")


def test_obtener_precio_sin_precio_configurado_es_none(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, costo_producto=Decimal("10.00"))

    assert PrecioService.obtener_precio(db_session, producto.id_producto, id_usuario=admin.id_usuario) is None


def test_obtener_precio_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, costo_producto=Decimal("10.00"))
    PrecioService.establecer_precio(db_session, producto.id_producto, "15.00", id_usuario=admin.id_usuario)

    with pytest.raises(PermisoDenegadoError):
        PrecioService.obtener_precio(db_session, producto.id_producto)


def test_eliminar_precio(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, costo_producto=Decimal("10.00"))
    precio = PrecioService.establecer_precio(db_session, producto.id_producto, "15.00", id_usuario=admin.id_usuario)

    PrecioService.eliminar_precio(db_session, precio.id_producto_precio, id_usuario=admin.id_usuario)

    assert PrecioService.obtener_precio(db_session, producto.id_producto, id_usuario=admin.id_usuario) is None


def test_eliminar_precio_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, costo_producto=Decimal("10.00"))
    precio = PrecioService.establecer_precio(db_session, producto.id_producto, "15.00", id_usuario=admin.id_usuario)

    with pytest.raises(PermisoDenegadoError):
        PrecioService.eliminar_precio(db_session, precio.id_producto_precio)


def test_eliminar_precio_inexistente_no_falla(db_session):
    admin = crear_usuario_admin(db_session)
    PrecioService.eliminar_precio(db_session, 999999, id_usuario=admin.id_usuario)
