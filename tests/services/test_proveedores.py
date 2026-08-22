from decimal import Decimal

import pytest

from app.services.proveedores import ProveedorService


def _datos_proveedor(**overrides) -> dict:
    datos = {
        "codigo_proveedor": "PROV-001",
        "identificacion_proveedor": "J-12345678",
        "nombre_razon_social": "Proveedor de Prueba",
    }
    datos.update(overrides)
    return datos


def test_crear_proveedor(db_session):
    proveedor = ProveedorService.crear(db_session, **_datos_proveedor())

    assert proveedor.id_proveedor is not None
    assert proveedor.codigo_proveedor == "PROV-001"
    assert proveedor.identificacion_proveedor == "J-12345678"


def test_crear_proveedor_requiere_codigo(db_session):
    with pytest.raises(ValueError, match="codigo_proveedor"):
        ProveedorService.crear(db_session, **_datos_proveedor(codigo_proveedor=""))


def test_crear_proveedor_requiere_identificacion(db_session):
    with pytest.raises(ValueError, match="identificacion_proveedor"):
        ProveedorService.crear(db_session, **_datos_proveedor(identificacion_proveedor=""))


def test_crear_proveedor_codigo_duplicado(db_session):
    ProveedorService.crear(db_session, **_datos_proveedor())

    with pytest.raises(ValueError, match="codigo_proveedor"):
        ProveedorService.crear(db_session, **_datos_proveedor(identificacion_proveedor="J-99999999"))


def test_crear_proveedor_identificacion_duplicada(db_session):
    ProveedorService.crear(db_session, **_datos_proveedor())

    with pytest.raises(ValueError, match="identificacion_proveedor"):
        ProveedorService.crear(db_session, **_datos_proveedor(codigo_proveedor="PROV-002"))


def test_obtener_proveedor(db_session):
    proveedor = ProveedorService.crear(db_session, **_datos_proveedor())
    encontrado = ProveedorService.obtener(db_session, proveedor.id_proveedor)
    assert encontrado is not None
    assert encontrado.id_proveedor == proveedor.id_proveedor


def test_obtener_proveedor_inexistente(db_session):
    assert ProveedorService.obtener(db_session, 999999) is None


def test_listar_proveedores_filtra_por_texto(db_session):
    ProveedorService.crear(db_session, **_datos_proveedor())
    ProveedorService.crear(
        db_session,
        **_datos_proveedor(codigo_proveedor="PROV-002", identificacion_proveedor="J-87654321", nombre_razon_social="Otro"),
    )

    resultado = ProveedorService.listar(db_session, texto_busqueda="Prueba")

    assert len(resultado) == 1
    assert resultado[0].nombre_razon_social == "Proveedor de Prueba"


def test_actualizar_proveedor(db_session):
    proveedor = ProveedorService.crear(db_session, **_datos_proveedor())

    actualizado = ProveedorService.actualizar(
        db_session, proveedor.id_proveedor, nombre_razon_social="Nombre Actualizado"
    )

    assert actualizado.nombre_razon_social == "Nombre Actualizado"


def test_actualizar_proveedor_no_permite_vaciar_codigo(db_session):
    proveedor = ProveedorService.crear(db_session, **_datos_proveedor())

    with pytest.raises(ValueError, match="codigo_proveedor"):
        ProveedorService.actualizar(db_session, proveedor.id_proveedor, codigo_proveedor="")


def test_actualizar_proveedor_inexistente(db_session):
    with pytest.raises(ValueError, match="Proveedor no encontrado"):
        ProveedorService.actualizar(db_session, 999999, nombre_razon_social="X")


def test_actualizar_proveedor_codigo_duplicado(db_session):
    ProveedorService.crear(db_session, **_datos_proveedor())
    otro = ProveedorService.crear(db_session, **_datos_proveedor(codigo_proveedor="PROV-002", identificacion_proveedor="J-87654321"))

    with pytest.raises(ValueError, match="codigo_proveedor"):
        ProveedorService.actualizar(db_session, otro.id_proveedor, codigo_proveedor="PROV-001")


def test_actualizar_credito(db_session):
    proveedor = ProveedorService.crear(db_session, **_datos_proveedor())

    actualizado = ProveedorService.actualizar_credito(
        db_session, proveedor.id_proveedor, limite_credito=Decimal("5000.00"), dias_credito=30
    )

    assert actualizado.limite_credito == Decimal("5000.00")
    assert actualizado.dias_credito == 30


def test_actualizar_credito_solo_campos_provistos(db_session):
    proveedor = ProveedorService.crear(
        db_session, **_datos_proveedor(limite_credito=Decimal("1000.00"), dias_credito=15)
    )

    actualizado = ProveedorService.actualizar_credito(db_session, proveedor.id_proveedor, dias_credito=45)

    assert actualizado.limite_credito == Decimal("1000.00")
    assert actualizado.dias_credito == 45


def test_actualizar_credito_proveedor_inexistente(db_session):
    with pytest.raises(ValueError, match="Proveedor no encontrado"):
        ProveedorService.actualizar_credito(db_session, 999999, limite_credito=Decimal("100.00"))


def test_eliminar_proveedor(db_session):
    proveedor = ProveedorService.crear(db_session, **_datos_proveedor())

    ProveedorService.eliminar(db_session, proveedor.id_proveedor)

    assert ProveedorService.listar(db_session) == []


def test_eliminar_proveedor_inexistente_no_falla(db_session):
    ProveedorService.eliminar(db_session, 999999)
