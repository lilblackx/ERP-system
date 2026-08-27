import pytest

from app.services import clientes as clientes_service
from app.services.permisos import PermisoDenegadoError
from tests.factories import crear_usuario_admin


def _datos_cliente(**overrides) -> dict:
    datos = {
        "codigo_cliente": "CLI-001",
        "id_legal": "V",
        "identificacion_cliente": "12345678",
        "nombre_razon_social": "Cliente de Prueba",
    }
    datos.update(overrides)
    return datos


def test_create_cliente(db_session):
    admin = crear_usuario_admin(db_session)

    cliente = clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))

    assert cliente.id_cliente is not None
    assert cliente.codigo_cliente == "CLI-001"
    assert cliente.id_legal == "V"
    assert cliente.identificacion_cliente == "12345678"


def test_create_cliente_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        clientes_service.create_cliente(db_session, **_datos_cliente())


def test_create_cliente_requiere_codigo(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError):
        clientes_service.create_cliente(db_session, **_datos_cliente(codigo_cliente="", creado_por=admin.id_usuario))


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
            **_datos_cliente(identificacion_cliente="99999999", creado_por=admin.id_usuario),
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
            identificacion_cliente="87654321",
            nombre_razon_social="Otro",
            creado_por=admin.id_usuario,
        ),
    )

    resultado = clientes_service.list_clientes(db_session, texto_busqueda="Prueba", id_usuario=admin.id_usuario)

    assert len(resultado) == 1
    assert resultado[0].nombre_razon_social == "Cliente de Prueba"


def test_list_clientes_texto_busqueda_matchea_identificacion_email_o_telefono(db_session):
    """Barra de busqueda unica de ClientesPanel: un solo termino debe matchear tambien
    identificacion/email/telefono, no solo nombre/codigo -- antes eran dos cajas
    separadas (nombre / identificacion) que se combinaban con AND."""
    admin = crear_usuario_admin(db_session)
    clientes_service.create_cliente(
        db_session,
        **_datos_cliente(
            codigo_cliente="CLI-UNICO",
            identificacion_cliente="99887766",
            nombre_razon_social="Distribuidora Zeta",
            email="contacto@zeta-unico.com",
            telefono="04121234567",
            creado_por=admin.id_usuario,
        ),
    )

    por_identificacion = clientes_service.list_clientes(
        db_session, texto_busqueda="99887766", id_usuario=admin.id_usuario
    )
    por_email = clientes_service.list_clientes(db_session, texto_busqueda="zeta-unico", id_usuario=admin.id_usuario)
    por_telefono = clientes_service.list_clientes(db_session, texto_busqueda="1234567", id_usuario=admin.id_usuario)

    for resultado in (por_identificacion, por_email, por_telefono):
        assert len(resultado) == 1
        assert resultado[0].nombre_razon_social == "Distribuidora Zeta"


def test_list_clientes_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        clientes_service.list_clientes(db_session)


def test_list_clientes_respeta_limite(db_session):
    admin = crear_usuario_admin(db_session)
    for i in range(5):
        clientes_service.create_cliente(
            db_session,
            **_datos_cliente(
                codigo_cliente=f"CLI-LIM-{i}",
                identificacion_cliente=f"{i:08d}",
                nombre_razon_social=f"Cliente Limite {i}",
                creado_por=admin.id_usuario,
            ),
        )

    resultado = clientes_service.list_clientes(db_session, id_usuario=admin.id_usuario, limite=3)

    assert len(resultado) == 3


def test_list_clientes_sin_limite_devuelve_todos(db_session):
    admin = crear_usuario_admin(db_session)
    for i in range(3):
        clientes_service.create_cliente(
            db_session,
            **_datos_cliente(
                codigo_cliente=f"CLI-SL-{i}",
                identificacion_cliente=f"{i:08d}9",
                nombre_razon_social=f"Cliente Sin Limite {i}",
                creado_por=admin.id_usuario,
            ),
        )

    resultado = clientes_service.list_clientes(db_session, id_usuario=admin.id_usuario)

    assert len(resultado) >= 3


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
        clientes_service.cambiar_estado_cliente(
            db_session, cliente.id_cliente, "BLOQUEADO", id_usuario=admin.id_usuario
        )


def test_cambiar_estado_cliente_inexistente(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="Cliente no encontrado"):
        clientes_service.cambiar_estado_cliente(db_session, 999999, "INACTIVO", id_usuario=admin.id_usuario)


def test_cambiar_estado_cliente_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))

    with pytest.raises(PermisoDenegadoError):
        clientes_service.cambiar_estado_cliente(db_session, cliente.id_cliente, "INACTIVO")
