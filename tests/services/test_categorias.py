import pytest

from app.services.categorias import CategoriaService
from app.services.permisos import PermisoDenegadoError
from tests.factories import crear_categoria, crear_producto, crear_usuario_admin


def test_crear_categoria(db_session):
    admin = crear_usuario_admin(db_session)

    categoria = CategoriaService.crear(db_session, nombre="Bebidas", creado_por=admin.id_usuario)
    assert categoria.id_categoria is not None
    assert categoria.nombre == "Bebidas"


def test_crear_categoria_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        CategoriaService.crear(db_session, nombre="Bebidas")


def test_obtener_categoria(db_session):
    admin = crear_usuario_admin(db_session)
    categoria = CategoriaService.crear(db_session, nombre="Bebidas", creado_por=admin.id_usuario)

    encontrada = CategoriaService.obtener(db_session, categoria.id_categoria, id_usuario=admin.id_usuario)
    assert encontrada is not None
    assert encontrada.id_categoria == categoria.id_categoria


def test_obtener_categoria_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    assert CategoriaService.obtener(db_session, 999999, id_usuario=admin.id_usuario) is None


def test_obtener_categoria_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        CategoriaService.obtener(db_session, 999999)


def test_listar_categorias_ordenadas_por_nombre(db_session):
    admin = crear_usuario_admin(db_session)
    CategoriaService.crear(db_session, nombre="Zapatos", creado_por=admin.id_usuario)
    CategoriaService.crear(db_session, nombre="Abarrotes", creado_por=admin.id_usuario)

    resultado = CategoriaService.listar(db_session, id_usuario=admin.id_usuario)

    assert [c.nombre for c in resultado] == ["Abarrotes", "Zapatos"]


def test_listar_categorias_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        CategoriaService.listar(db_session)


def test_contar_productos(db_session):
    categoria = crear_categoria(db_session, nombre="Lacteos")
    crear_producto(db_session, categoria=categoria)
    crear_producto(db_session, categoria=categoria)

    assert CategoriaService.contar_productos(db_session, categoria.id_categoria) == 2


def test_contar_productos_sin_productos(db_session):
    categoria = crear_categoria(db_session)
    assert CategoriaService.contar_productos(db_session, categoria.id_categoria) == 0


def test_listar_con_conteo(db_session):
    admin = crear_usuario_admin(db_session)
    categoria = crear_categoria(db_session, nombre="Snacks")
    crear_producto(db_session, categoria=categoria)

    resultado = CategoriaService.listar_con_conteo(db_session, id_usuario=admin.id_usuario)

    fila = next(f for f in resultado if f["categoria"].id_categoria == categoria.id_categoria)
    assert fila["total_productos"] == 1


def test_listar_con_conteo_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        CategoriaService.listar_con_conteo(db_session)


def test_listar_con_conteo_categoria_sin_productos(db_session):
    admin = crear_usuario_admin(db_session)
    categoria = crear_categoria(db_session, nombre="Vacia")

    resultado = CategoriaService.listar_con_conteo(db_session, id_usuario=admin.id_usuario)

    fila = next(f for f in resultado if f["categoria"].id_categoria == categoria.id_categoria)
    assert fila["total_productos"] == 0


def test_actualizar_categoria(db_session):
    admin = crear_usuario_admin(db_session)
    categoria = CategoriaService.crear(db_session, nombre="Bebidas", creado_por=admin.id_usuario)

    actualizada = CategoriaService.actualizar(
        db_session, categoria.id_categoria, id_usuario=admin.id_usuario, nombre="Bebidas y Snacks"
    )

    assert actualizada.nombre == "Bebidas y Snacks"


def test_actualizar_categoria_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    categoria = CategoriaService.crear(db_session, nombre="Bebidas", creado_por=admin.id_usuario)

    with pytest.raises(PermisoDenegadoError):
        CategoriaService.actualizar(db_session, categoria.id_categoria, nombre="X")


def test_actualizar_categoria_inexistente(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="Categoria no encontrada"):
        CategoriaService.actualizar(db_session, 999999, id_usuario=admin.id_usuario, nombre="X")


def test_eliminar_categoria(db_session):
    admin = crear_usuario_admin(db_session)
    categoria = CategoriaService.crear(db_session, nombre="Bebidas", creado_por=admin.id_usuario)

    CategoriaService.eliminar(db_session, categoria.id_categoria, id_usuario=admin.id_usuario)

    assert CategoriaService.obtener(db_session, categoria.id_categoria, id_usuario=admin.id_usuario) is None


def test_eliminar_categoria_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    categoria = CategoriaService.crear(db_session, nombre="Bebidas", creado_por=admin.id_usuario)

    with pytest.raises(PermisoDenegadoError):
        CategoriaService.eliminar(db_session, categoria.id_categoria)


def test_eliminar_categoria_inexistente_no_falla(db_session):
    admin = crear_usuario_admin(db_session)
    CategoriaService.eliminar(db_session, 999999, id_usuario=admin.id_usuario)


def test_eliminar_categoria_con_productos_falla(db_session):
    admin = crear_usuario_admin(db_session)
    categoria = crear_categoria(db_session)
    crear_producto(db_session, categoria=categoria)

    with pytest.raises(ValueError, match="productos asociados"):
        CategoriaService.eliminar(db_session, categoria.id_categoria, id_usuario=admin.id_usuario)

    assert CategoriaService.obtener(db_session, categoria.id_categoria, id_usuario=admin.id_usuario) is not None
