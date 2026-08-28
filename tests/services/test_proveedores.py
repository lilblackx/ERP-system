from decimal import Decimal

import pytest

from app.services.permisos import PermisoDenegadoError
from app.services.proveedores import ProveedorService
from tests.factories import crear_usuario_admin


def _datos_proveedor(**overrides) -> dict:
    datos = {
        "codigo_proveedor": "PROV-001",
        "identificacion_proveedor": "J-12345678",
        "nombre_razon_social": "Proveedor de Prueba",
    }
    datos.update(overrides)
    return datos


def test_crear_proveedor(db_session):
    admin = crear_usuario_admin(db_session)

    proveedor = ProveedorService.crear(db_session, **_datos_proveedor(creado_por=admin.id_usuario))

    assert proveedor.id_proveedor is not None
    assert proveedor.codigo_proveedor == "PROV-001"
    assert proveedor.identificacion_proveedor == "J-12345678"


def test_crear_proveedor_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ProveedorService.crear(db_session, **_datos_proveedor())


def test_crear_proveedor_requiere_codigo(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="codigo_proveedor"):
        ProveedorService.crear(db_session, **_datos_proveedor(codigo_proveedor="", creado_por=admin.id_usuario))


def test_crear_proveedor_requiere_identificacion(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="identificacion_proveedor"):
        ProveedorService.crear(db_session, **_datos_proveedor(identificacion_proveedor="", creado_por=admin.id_usuario))


def test_crear_proveedor_codigo_duplicado(db_session):
    admin = crear_usuario_admin(db_session)
    ProveedorService.crear(db_session, **_datos_proveedor(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="codigo_proveedor"):
        ProveedorService.crear(
            db_session, **_datos_proveedor(identificacion_proveedor="J-99999999", creado_por=admin.id_usuario)
        )


def test_crear_proveedor_identificacion_duplicada(db_session):
    admin = crear_usuario_admin(db_session)
    ProveedorService.crear(db_session, **_datos_proveedor(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="identificacion_proveedor"):
        ProveedorService.crear(db_session, **_datos_proveedor(codigo_proveedor="PROV-002", creado_por=admin.id_usuario))


def test_obtener_proveedor(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = ProveedorService.crear(db_session, **_datos_proveedor(creado_por=admin.id_usuario))
    encontrado = ProveedorService.obtener(db_session, proveedor.id_proveedor, id_usuario=admin.id_usuario)
    assert encontrado is not None
    assert encontrado.id_proveedor == proveedor.id_proveedor


def test_obtener_proveedor_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    assert ProveedorService.obtener(db_session, 999999, id_usuario=admin.id_usuario) is None


def test_obtener_proveedor_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ProveedorService.obtener(db_session, 999999)


def test_listar_proveedores_filtra_por_texto(db_session):
    admin = crear_usuario_admin(db_session)
    ProveedorService.crear(db_session, **_datos_proveedor(creado_por=admin.id_usuario))
    ProveedorService.crear(
        db_session,
        **_datos_proveedor(
            codigo_proveedor="PROV-002",
            identificacion_proveedor="J-87654321",
            nombre_razon_social="Otro",
            creado_por=admin.id_usuario,
        ),
    )

    resultado = ProveedorService.listar(db_session, texto_busqueda="Prueba", id_usuario=admin.id_usuario)

    assert resultado["total"] == 1
    assert resultado["items"][0].nombre_razon_social == "Proveedor de Prueba"


def test_listar_proveedores_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        ProveedorService.listar(db_session)


def test_listar_proveedores_pagina_resultados(db_session):
    admin = crear_usuario_admin(db_session)
    for i in range(5):
        ProveedorService.crear(
            db_session,
            **_datos_proveedor(
                codigo_proveedor=f"PROV-{i:03d}",
                identificacion_proveedor=f"J-{i:08d}",
                creado_por=admin.id_usuario,
            ),
        )

    pagina1 = ProveedorService.listar(db_session, pagina=1, por_pagina=2, id_usuario=admin.id_usuario)
    pagina2 = ProveedorService.listar(db_session, pagina=2, por_pagina=2, id_usuario=admin.id_usuario)

    assert pagina1["total"] == 5
    assert len(pagina1["items"]) == 2
    assert len(pagina2["items"]) == 2
    ids_pagina1 = {p.id_proveedor for p in pagina1["items"]}
    ids_pagina2 = {p.id_proveedor for p in pagina2["items"]}
    assert ids_pagina1.isdisjoint(ids_pagina2)


def test_listar_proveedores_filtra_por_estado(db_session):
    admin = crear_usuario_admin(db_session)
    activo = ProveedorService.crear(db_session, **_datos_proveedor(creado_por=admin.id_usuario))
    inactivo = ProveedorService.crear(
        db_session,
        **_datos_proveedor(
            codigo_proveedor="PROV-002", identificacion_proveedor="J-87654321", creado_por=admin.id_usuario
        ),
    )
    ProveedorService.cambiar_estado(db_session, inactivo.id_proveedor, "INACTIVO", id_usuario=admin.id_usuario)

    resultado = ProveedorService.listar(db_session, estado_proveedor="ACTIVO", id_usuario=admin.id_usuario)

    assert resultado["total"] == 1
    assert resultado["items"][0].id_proveedor == activo.id_proveedor


def test_actualizar_proveedor(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = ProveedorService.crear(db_session, **_datos_proveedor(creado_por=admin.id_usuario))

    actualizado = ProveedorService.actualizar(
        db_session, proveedor.id_proveedor, id_usuario=admin.id_usuario, nombre_razon_social="Nombre Actualizado"
    )

    assert actualizado.nombre_razon_social == "Nombre Actualizado"


def test_actualizar_proveedor_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = ProveedorService.crear(db_session, **_datos_proveedor(creado_por=admin.id_usuario))

    with pytest.raises(PermisoDenegadoError):
        ProveedorService.actualizar(db_session, proveedor.id_proveedor, nombre_razon_social="X")


def test_actualizar_proveedor_no_permite_vaciar_codigo(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = ProveedorService.crear(db_session, **_datos_proveedor(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="codigo_proveedor"):
        ProveedorService.actualizar(
            db_session, proveedor.id_proveedor, id_usuario=admin.id_usuario, codigo_proveedor=""
        )


def test_actualizar_proveedor_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Proveedor no encontrado"):
        ProveedorService.actualizar(db_session, 999999, id_usuario=admin.id_usuario, nombre_razon_social="X")


def test_actualizar_proveedor_codigo_duplicado(db_session):
    admin = crear_usuario_admin(db_session)
    ProveedorService.crear(db_session, **_datos_proveedor(creado_por=admin.id_usuario))
    otro = ProveedorService.crear(
        db_session,
        **_datos_proveedor(
            codigo_proveedor="PROV-002", identificacion_proveedor="J-87654321", creado_por=admin.id_usuario
        ),
    )

    with pytest.raises(ValueError, match="codigo_proveedor"):
        ProveedorService.actualizar(
            db_session, otro.id_proveedor, id_usuario=admin.id_usuario, codigo_proveedor="PROV-001"
        )


def test_actualizar_credito(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = ProveedorService.crear(db_session, **_datos_proveedor(creado_por=admin.id_usuario))

    actualizado = ProveedorService.actualizar_credito(
        db_session,
        proveedor.id_proveedor,
        limite_credito=Decimal("5000.00"),
        dias_credito=30,
        id_usuario=admin.id_usuario,
    )

    assert actualizado.limite_credito == Decimal("5000.00")
    assert actualizado.dias_credito == 30


def test_actualizar_credito_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = ProveedorService.crear(db_session, **_datos_proveedor(creado_por=admin.id_usuario))

    with pytest.raises(PermisoDenegadoError):
        ProveedorService.actualizar_credito(db_session, proveedor.id_proveedor, limite_credito=Decimal("5000.00"))


def test_actualizar_credito_solo_campos_provistos(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = ProveedorService.crear(
        db_session, **_datos_proveedor(limite_credito=Decimal("1000.00"), dias_credito=15, creado_por=admin.id_usuario)
    )

    actualizado = ProveedorService.actualizar_credito(
        db_session, proveedor.id_proveedor, dias_credito=45, id_usuario=admin.id_usuario
    )

    assert actualizado.limite_credito == Decimal("1000.00")
    assert actualizado.dias_credito == 45


def test_actualizar_credito_proveedor_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Proveedor no encontrado"):
        ProveedorService.actualizar_credito(
            db_session, 999999, limite_credito=Decimal("100.00"), id_usuario=admin.id_usuario
        )


def test_eliminar_proveedor_siempre_falla_para_proteger_integridad(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = ProveedorService.crear(db_session, **_datos_proveedor(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="No se puede eliminar"):
        ProveedorService.eliminar(db_session, proveedor.id_proveedor, id_usuario=admin.id_usuario)

    assert ProveedorService.listar(db_session, id_usuario=admin.id_usuario)["total"] == 1


def test_eliminar_proveedor_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = ProveedorService.crear(db_session, **_datos_proveedor(creado_por=admin.id_usuario))

    with pytest.raises(PermisoDenegadoError):
        ProveedorService.eliminar(db_session, proveedor.id_proveedor)


def test_cambiar_estado_proveedor_desactiva(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = ProveedorService.crear(db_session, **_datos_proveedor(creado_por=admin.id_usuario))

    actualizado = ProveedorService.cambiar_estado(
        db_session, proveedor.id_proveedor, "INACTIVO", id_usuario=admin.id_usuario
    )

    assert actualizado.estado_proveedor == "INACTIVO"


def test_cambiar_estado_proveedor_estado_invalido(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = ProveedorService.crear(db_session, **_datos_proveedor(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="nuevo_estado"):
        ProveedorService.cambiar_estado(db_session, proveedor.id_proveedor, "BLOQUEADO", id_usuario=admin.id_usuario)


def test_cambiar_estado_proveedor_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Proveedor no encontrado"):
        ProveedorService.cambiar_estado(db_session, 999999, "INACTIVO", id_usuario=admin.id_usuario)


def test_cambiar_estado_proveedor_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = ProveedorService.crear(db_session, **_datos_proveedor(creado_por=admin.id_usuario))

    with pytest.raises(PermisoDenegadoError):
        ProveedorService.cambiar_estado(db_session, proveedor.id_proveedor, "INACTIVO")
