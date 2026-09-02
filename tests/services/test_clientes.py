import pytest

from app.services import clientes as clientes_service
from app.services.permisos import PermisoDenegadoError
from tests.factories import crear_cliente, crear_ruta, crear_usuario_admin, crear_vendedor


def _datos_cliente(**overrides) -> dict:
    datos = {
        "codigo_cliente": "CLI-001",
        "id_legal": "V",
        "identificacion_cliente": "12345678",
        "nombre_razon_social": "Cliente de Prueba",
        # latitud/longitud son obligatorias (decision de producto, 2026-09-01) -- default
        # aca para no repetirlo en cada test que no le interesa la geolocalizacion en si.
        "latitud": 10.4806,
        "longitud": -66.9036,
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

    assert resultado["total"] == 1
    assert resultado["items"][0].nombre_razon_social == "Cliente de Prueba"


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
        assert resultado["total"] == 1
        assert resultado["items"][0].nombre_razon_social == "Distribuidora Zeta"


def test_list_clientes_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        clientes_service.list_clientes(db_session)


def test_list_clientes_pagina_resultados(db_session):
    """D-01: list_clientes() pagina de verdad (pagina/por_pagina/total), reemplaza el
    viejo `limite` (solo capaba filas sin llevar cuenta de pagina) -- mismo patron que
    ProductoService.buscar()/VentaService.listar_facturas()."""
    admin = crear_usuario_admin(db_session)
    for i in range(5):
        clientes_service.create_cliente(
            db_session,
            **_datos_cliente(
                codigo_cliente=f"CLI-PAG-{i}",
                identificacion_cliente=f"{i:08d}",
                nombre_razon_social=f"Cliente Pagina {i}",
                creado_por=admin.id_usuario,
            ),
        )

    pagina_1 = clientes_service.list_clientes(db_session, pagina=1, por_pagina=2, id_usuario=admin.id_usuario)
    pagina_2 = clientes_service.list_clientes(db_session, pagina=2, por_pagina=2, id_usuario=admin.id_usuario)

    assert pagina_1["total"] == 5
    assert len(pagina_1["items"]) == 2
    assert len(pagina_2["items"]) == 2
    assert {c.id_cliente for c in pagina_1["items"]}.isdisjoint({c.id_cliente for c in pagina_2["items"]})


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


def test_update_cliente_codigo_duplicado(db_session):
    """Hueco de auditoria 2026-08-27: la re-validacion de duplicado al CAMBIAR
    codigo_cliente/identificacion_cliente (clientes.py:111-117) tenia codigo pero
    ningun test la ejercitaba, solo el camino de create_cliente."""
    admin = crear_usuario_admin(db_session)
    clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))
    otro = clientes_service.create_cliente(
        db_session,
        **_datos_cliente(codigo_cliente="CLI-002", identificacion_cliente="87654321", creado_por=admin.id_usuario),
    )

    with pytest.raises(ValueError):
        clientes_service.update_cliente(
            db_session, otro.id_cliente, id_usuario=admin.id_usuario, codigo_cliente="CLI-001"
        )


def test_update_cliente_identificacion_duplicada(db_session):
    admin = crear_usuario_admin(db_session)
    clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))
    otro = clientes_service.create_cliente(
        db_session,
        **_datos_cliente(codigo_cliente="CLI-002", identificacion_cliente="87654321", creado_por=admin.id_usuario),
    )

    with pytest.raises(ValueError):
        clientes_service.update_cliente(
            db_session, otro.id_cliente, id_usuario=admin.id_usuario, identificacion_cliente="12345678"
        )


def test_update_cliente_permite_conservar_su_propio_codigo(db_session):
    """Guardar sin cambiar codigo_cliente/identificacion_cliente no debe chocar contra
    si mismo."""
    admin = crear_usuario_admin(db_session)
    cliente = clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))

    actualizado = clientes_service.update_cliente(
        db_session,
        cliente.id_cliente,
        id_usuario=admin.id_usuario,
        codigo_cliente="CLI-001",
        nombre_razon_social="Nombre Nuevo",
    )

    assert actualizado.nombre_razon_social == "Nombre Nuevo"


def test_update_cliente_inexistente(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError):
        clientes_service.update_cliente(db_session, 999999, id_usuario=admin.id_usuario, nombre_razon_social="X")


def test_delete_cliente_siempre_falla_para_proteger_integridad(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="No se puede eliminar"):
        clientes_service.delete_cliente(db_session, cliente.id_cliente, id_usuario=admin.id_usuario)

    assert clientes_service.list_clientes(db_session, id_usuario=admin.id_usuario)["total"] == 1


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


# --- geolocalizacion (latitud/longitud) -----------------------------------------------


def test_create_cliente_con_coordenadas(db_session):
    admin = crear_usuario_admin(db_session)

    cliente = clientes_service.create_cliente(
        db_session, **_datos_cliente(creado_por=admin.id_usuario, latitud=10.4806, longitud=-66.9036)
    )

    assert float(cliente.latitud) == pytest.approx(10.4806)
    assert float(cliente.longitud) == pytest.approx(-66.9036)


def test_create_cliente_requiere_latitud(db_session):
    """La ubicacion es obligatoria (decision de producto, 2026-09-01) -- no se puede
    crear un cliente sin latitud/longitud."""
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="latitud"):
        clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario, latitud=None))


def test_create_cliente_requiere_longitud(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="longitud"):
        clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario, longitud=None))


def test_create_cliente_latitud_fuera_de_rango_falla(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="latitud"):
        clientes_service.create_cliente(
            db_session, **_datos_cliente(creado_por=admin.id_usuario, latitud=200, longitud=-66.9036)
        )


def test_create_cliente_longitud_fuera_de_rango_falla(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="longitud"):
        clientes_service.create_cliente(
            db_session, **_datos_cliente(creado_por=admin.id_usuario, latitud=10.4806, longitud=200)
        )


def test_update_cliente_cambia_coordenadas(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))

    actualizado = clientes_service.update_cliente(
        db_session, cliente.id_cliente, id_usuario=admin.id_usuario, latitud=11.0, longitud=-67.0
    )

    assert float(actualizado.latitud) == pytest.approx(11.0)


def test_update_cliente_no_permite_vaciar_latitud(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="latitud"):
        clientes_service.update_cliente(db_session, cliente.id_cliente, id_usuario=admin.id_usuario, latitud=None)


def test_update_cliente_no_permite_vaciar_longitud(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = clientes_service.create_cliente(db_session, **_datos_cliente(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="longitud"):
        clientes_service.update_cliente(db_session, cliente.id_cliente, id_usuario=admin.id_usuario, longitud=None)


def test_update_cliente_conserva_coordenadas_existentes_al_editar_otro_campo(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = clientes_service.create_cliente(
        db_session, **_datos_cliente(creado_por=admin.id_usuario, latitud=10.4806, longitud=-66.9036)
    )

    actualizado = clientes_service.update_cliente(
        db_session, cliente.id_cliente, id_usuario=admin.id_usuario, telefono="0212-1234567"
    )

    assert float(actualizado.latitud) == pytest.approx(10.4806)
    assert float(actualizado.longitud) == pytest.approx(-66.9036)


# --- listar_clientes_por_ruta ----------------------------------------------------------


def test_listar_clientes_por_ruta(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = crear_ruta(db_session)
    otra_ruta = crear_ruta(db_session)
    vendedor = crear_vendedor(db_session, ruta=ruta)
    vendedor_otra_ruta = crear_vendedor(db_session, ruta=otra_ruta)

    cliente_con_coords = crear_cliente(
        db_session, vendedor_cliente=vendedor.id_vendedor, latitud=10.4806, longitud=-66.9036
    )
    crear_cliente(db_session, vendedor_cliente=vendedor.id_vendedor)  # sin coordenadas
    crear_cliente(db_session, vendedor_cliente=vendedor_otra_ruta.id_vendedor, latitud=10.0, longitud=-66.0)

    resultado = clientes_service.listar_clientes_por_ruta(db_session, ruta.id_ruta, id_usuario=admin.id_usuario)

    assert [c.id_cliente for c in resultado] == [cliente_con_coords.id_cliente]


def test_listar_clientes_por_ruta_sin_usuario_autorizado_falla(db_session):
    ruta = crear_ruta(db_session)
    with pytest.raises(PermisoDenegadoError):
        clientes_service.listar_clientes_por_ruta(db_session, ruta.id_ruta)
