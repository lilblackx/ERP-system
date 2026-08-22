import pytest

from app.services import clientes as clientes_service


def _datos_cliente(**overrides) -> dict:
    datos = {
        "codigo_cliente": "CLI-001",
        "identificacion_cliente": "V-12345678",
        "nombre_razon_social": "Cliente de Prueba",
    }
    datos.update(overrides)
    return datos


def test_create_cliente(db_session):
    cliente = clientes_service.create_cliente(db_session, **_datos_cliente())

    assert cliente.id_cliente is not None
    assert cliente.codigo_cliente == "CLI-001"
    assert cliente.identificacion_cliente == "V-12345678"


def test_create_cliente_requiere_codigo(db_session):
    with pytest.raises(ValueError):
        clientes_service.create_cliente(db_session, **_datos_cliente(codigo_cliente=""))


def test_create_cliente_requiere_identificacion(db_session):
    with pytest.raises(ValueError):
        clientes_service.create_cliente(db_session, **_datos_cliente(identificacion_cliente=""))


def test_create_cliente_codigo_duplicado(db_session):
    clientes_service.create_cliente(db_session, **_datos_cliente())

    with pytest.raises(ValueError):
        clientes_service.create_cliente(
            db_session, **_datos_cliente(identificacion_cliente="V-99999999")
        )


def test_create_cliente_identificacion_duplicada(db_session):
    clientes_service.create_cliente(db_session, **_datos_cliente())

    with pytest.raises(ValueError):
        clientes_service.create_cliente(db_session, **_datos_cliente(codigo_cliente="CLI-002"))


def test_list_clientes_filtra_por_texto(db_session):
    clientes_service.create_cliente(db_session, **_datos_cliente())
    clientes_service.create_cliente(
        db_session,
        **_datos_cliente(codigo_cliente="CLI-002", identificacion_cliente="V-87654321", nombre_razon_social="Otro"),
    )

    resultado = clientes_service.list_clientes(db_session, texto_busqueda="Prueba")

    assert len(resultado) == 1
    assert resultado[0].nombre_razon_social == "Cliente de Prueba"


def test_update_cliente(db_session):
    cliente = clientes_service.create_cliente(db_session, **_datos_cliente())

    actualizado = clientes_service.update_cliente(
        db_session, cliente.id_cliente, nombre_razon_social="Nombre Actualizado"
    )

    assert actualizado.nombre_razon_social == "Nombre Actualizado"


def test_update_cliente_no_permite_vaciar_codigo(db_session):
    cliente = clientes_service.create_cliente(db_session, **_datos_cliente())

    with pytest.raises(ValueError):
        clientes_service.update_cliente(db_session, cliente.id_cliente, codigo_cliente="")


def test_update_cliente_inexistente(db_session):
    with pytest.raises(ValueError):
        clientes_service.update_cliente(db_session, 999999, nombre_razon_social="X")


def test_delete_cliente(db_session):
    cliente = clientes_service.create_cliente(db_session, **_datos_cliente())

    clientes_service.delete_cliente(db_session, cliente.id_cliente)

    assert clientes_service.list_clientes(db_session) == []
