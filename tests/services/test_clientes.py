import pytest

from app.services import clientes as clientes_service
from app.services.permisos import PermisoDenegadoError
from tests.factories import crear_usuario_admin


def _datos_cliente(**overrides) -> dict:
    datos = {
        "codigo_cliente": "CLI-001",
        "identificacion_cliente": "V-12345678",
        "nombre_razon_social": "Cliente de Prueba",
    }
    datos.update(overrides)
    return datos


def test_create_cliente(db_session):
    admin = crear_usuario_admin(db_session)

    cliente = clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))

    assert cliente.id_cliente is not None
    assert cliente.codigo_cliente == "CLI-001"
    assert cliente.identificacion_cliente == "V-12345678"


def test_create_cliente_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        clientes_service.create_cliente(db_session, **_datos_cliente())


def test_create_cliente_requiere_codigo(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError):
        clientes_service.create_cliente(
            db_session, **_datos_cliente(codigo_cliente="", creado_por=admin.id_usuario)
        )


def test_create_cliente_requiere_identificacion(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError):
        clientes_service.create_cliente(
            db_session, **_datos_cliente(identificacion_cliente="", creado_por=admin.id_usuario)
        )


def test_create_cliente_codigo_duplicado(db_session):
    admin = crear_usuario_admin(db_session)
    clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))

    with pytest.raises(ValueError):
        clientes_service.create_cliente(
            db_session,
            **_datos_cliente(identificacion_cliente="V-99999999", creado_por=admin.id_usuario),
        )


def test_create_cliente_identificacion_duplicada(db_session):
    admin = crear_usuario_admin(db_session)
    clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))

    with pytest.raises(ValueError):
        clientes_service.create_cliente(
            db_session, **_datos_cliente(codigo_cliente="CLI-002", creado_por=admin.id_usuario)
        )


def test_list_clientes_filtra_por_texto(db_session):
    admin = crear_usuario_admin(db_session)
    clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))
    clientes_service.create_cliente(
        db_session,
        **_datos_cliente(
            codigo_cliente="CLI-002",
            identificacion_cliente="V-87654321",
            nombre_razon_social="Otro",
            creado_por=admin.id_usuario,
        ),
    )

    resultado = clientes_service.list_clientes(db_session, texto_busqueda="Prueba", id_usuario=admin.id_usuario)

    assert len(resultado) == 1
    assert resultado[0].nombre_razon_social == "Cliente de Prueba"


def test_list_clientes_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        clientes_service.list_clientes(db_session)


def test_update_cliente(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))

    actualizado = clientes_service.update_cliente(
        db_session, cliente.id_cliente, id_usuario=admin.id_usuario, nombre_razon_social="Nombre Actualizado"
    )

    assert actualizado.nombre_razon_social == "Nombre Actualizado"


def test_update_cliente_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))

    with pytest.raises(PermisoDenegadoError):
        clientes_service.update_cliente(db_session, cliente.id_cliente, nombre_razon_social="X")


def test_update_cliente_no_permite_vaciar_codigo(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))

    with pytest.raises(ValueError):
        clientes_service.update_cliente(db_session, cliente.id_cliente, id_usuario=admin.id_usuario, codigo_cliente="")


def test_update_cliente_inexistente(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError):
        clientes_service.update_cliente(db_session, 999999, id_usuario=admin.id_usuario, nombre_razon_social="X")


def test_delete_cliente_siempre_falla_para_proteger_integridad(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="No se puede eliminar"):
        clientes_service.delete_cliente(db_session, cliente.id_cliente, id_usuario=admin.id_usuario)

    assert len(clientes_service.list_clientes(db_session, id_usuario=admin.id_usuario)) == 1


def test_delete_cliente_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))

    with pytest.raises(PermisoDenegadoError):
        clientes_service.delete_cliente(db_session, cliente.id_cliente)


def test_cambiar_estado_cliente_desactiva(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))

    actualizado = clientes_service.cambiar_estado_cliente(
        db_session, cliente.id_cliente, "INACTIVO", id_usuario=admin.id_usuario
    )

    assert actualizado.estado_cliente == "INACTIVO"


def test_cambiar_estado_cliente_estado_invalido(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="nuevo_estado"):
        clientes_service.cambiar_estado_cliente(db_session, cliente.id_cliente, "BLOQUEADO", id_usuario=admin.id_usuario)


def test_cambiar_estado_cliente_inexistente(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="Cliente no encontrado"):
        clientes_service.cambiar_estado_cliente(db_session, 999999, "INACTIVO", id_usuario=admin.id_usuario)


def test_cambiar_estado_cliente_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))

    with pytest.raises(PermisoDenegadoError):
        clientes_service.cambiar_estado_cliente(db_session, cliente.id_cliente, "INACTIVO")
