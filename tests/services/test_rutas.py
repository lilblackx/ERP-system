import json

import pytest

from app.services.permisos import PermisoDenegadoError
from app.services.rutas import RutaService
from tests.factories import crear_usuario_admin

# Cuadrado simple alrededor de Caracas -- suficiente para probar el poligono sin
# necesitar coordenadas reales de calles.
_ZONA_EJEMPLO = [[10.40, -67.00], [10.40, -66.80], [10.60, -66.80], [10.60, -67.00]]


def _datos_ruta(**overrides) -> dict:
    datos = {
        "nombre_ruta": "Ruta Centro",
        "zona_geojson": json.dumps(_ZONA_EJEMPLO),
    }
    datos.update(overrides)
    return datos


def test_crear_ruta(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))
    assert ruta.id_ruta is not None
    assert ruta.nombre_ruta == "Ruta Centro"
    assert ruta.estado_ruta == "ACTIVO"


def test_crear_ruta_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        RutaService.crear(db_session, **_datos_ruta())


def test_crear_ruta_requiere_nombre(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="nombre_ruta"):
        RutaService.crear(db_session, **_datos_ruta(nombre_ruta="", creado_por=admin.id_usuario))


def test_crear_ruta_nombre_duplicado(db_session):
    admin = crear_usuario_admin(db_session)
    RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="nombre_ruta"):
        RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))


def test_obtener_ruta(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))
    encontrada = RutaService.obtener(db_session, ruta.id_ruta, id_usuario=admin.id_usuario)
    assert encontrada is not None
    assert encontrada.id_ruta == ruta.id_ruta


def test_obtener_ruta_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    assert RutaService.obtener(db_session, 999999, id_usuario=admin.id_usuario) is None


def test_obtener_ruta_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        RutaService.obtener(db_session, 999999)


def test_listar_rutas_filtra_por_texto(db_session):
    admin = crear_usuario_admin(db_session)
    RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))
    RutaService.crear(db_session, **_datos_ruta(nombre_ruta="Ruta Norte", creado_por=admin.id_usuario))

    resultado = RutaService.listar(db_session, texto_busqueda="Centro", id_usuario=admin.id_usuario)

    assert resultado["total"] == 1
    assert resultado["items"][0].nombre_ruta == "Ruta Centro"


def test_listar_rutas_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        RutaService.listar(db_session)


def test_listar_rutas_pagina_resultados(db_session):
    admin = crear_usuario_admin(db_session)
    for i in range(5):
        RutaService.crear(db_session, **_datos_ruta(nombre_ruta=f"Ruta {i}", creado_por=admin.id_usuario))

    pagina_1 = RutaService.listar(db_session, pagina=1, por_pagina=2, id_usuario=admin.id_usuario)
    pagina_2 = RutaService.listar(db_session, pagina=2, por_pagina=2, id_usuario=admin.id_usuario)

    assert pagina_1["total"] == 5
    assert len(pagina_1["items"]) == 2
    assert len(pagina_2["items"]) == 2
    assert {r.id_ruta for r in pagina_1["items"]}.isdisjoint({r.id_ruta for r in pagina_2["items"]})


def test_listar_rutas_filtra_por_estado(db_session):
    admin = crear_usuario_admin(db_session)
    activa = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))
    inactiva = RutaService.crear(db_session, **_datos_ruta(nombre_ruta="Ruta Norte", creado_por=admin.id_usuario))
    RutaService.cambiar_estado(db_session, inactiva.id_ruta, "INACTIVO", id_usuario=admin.id_usuario)

    resultado = RutaService.listar(db_session, estado_ruta="ACTIVO", id_usuario=admin.id_usuario)

    assert resultado["total"] == 1
    assert resultado["items"][0].id_ruta == activa.id_ruta


def test_actualizar_ruta(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    actualizada = RutaService.actualizar(
        db_session, ruta.id_ruta, id_usuario=admin.id_usuario, nombre_ruta="Ruta Renombrada"
    )

    assert actualizada.nombre_ruta == "Ruta Renombrada"


def test_actualizar_ruta_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    with pytest.raises(PermisoDenegadoError):
        RutaService.actualizar(db_session, ruta.id_ruta, nombre_ruta="X")


def test_actualizar_ruta_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Ruta no encontrada"):
        RutaService.actualizar(db_session, 999999, id_usuario=admin.id_usuario, nombre_ruta="X")


def test_actualizar_ruta_no_permite_vaciar_nombre(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="nombre_ruta"):
        RutaService.actualizar(db_session, ruta.id_ruta, id_usuario=admin.id_usuario, nombre_ruta="")


def test_actualizar_ruta_nombre_duplicado(db_session):
    admin = crear_usuario_admin(db_session)
    RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))
    otra = RutaService.crear(db_session, **_datos_ruta(nombre_ruta="Ruta Norte", creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="nombre_ruta"):
        RutaService.actualizar(db_session, otra.id_ruta, id_usuario=admin.id_usuario, nombre_ruta="Ruta Centro")


def test_actualizar_ruta_permite_conservar_su_propio_nombre(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    actualizada = RutaService.actualizar(
        db_session,
        ruta.id_ruta,
        id_usuario=admin.id_usuario,
        nombre_ruta="Ruta Centro",
        descripcion_ruta="Zona metropolitana",
    )

    assert actualizada.descripcion_ruta == "Zona metropolitana"


def test_eliminar_ruta_siempre_falla_para_proteger_integridad(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="No se puede eliminar"):
        RutaService.eliminar(db_session, ruta.id_ruta, id_usuario=admin.id_usuario)

    assert RutaService.listar(db_session, id_usuario=admin.id_usuario)["total"] == 1


def test_eliminar_ruta_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    with pytest.raises(PermisoDenegadoError):
        RutaService.eliminar(db_session, ruta.id_ruta)


def test_cambiar_estado_ruta_desactiva(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    actualizada = RutaService.cambiar_estado(db_session, ruta.id_ruta, "INACTIVO", id_usuario=admin.id_usuario)

    assert actualizada.estado_ruta == "INACTIVO"


def test_cambiar_estado_ruta_estado_invalido(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="nuevo_estado"):
        RutaService.cambiar_estado(db_session, ruta.id_ruta, "BLOQUEADA", id_usuario=admin.id_usuario)


def test_cambiar_estado_ruta_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Ruta no encontrada"):
        RutaService.cambiar_estado(db_session, 999999, "INACTIVO", id_usuario=admin.id_usuario)


def test_cambiar_estado_ruta_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    with pytest.raises(PermisoDenegadoError):
        RutaService.cambiar_estado(db_session, ruta.id_ruta, "INACTIVO")


# --- zona de cobertura (migrations/0043) -----------------------------------------------


def test_crear_ruta_con_zona(db_session):
    admin = crear_usuario_admin(db_session)

    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    assert json.loads(ruta.zona_geojson) == _ZONA_EJEMPLO


def test_crear_ruta_requiere_zona(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="zona_geojson"):
        RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario, zona_geojson=None))


def test_crear_ruta_zona_con_menos_de_3_vertices_falla(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="al menos 3 vertices"):
        RutaService.crear(
            db_session,
            **_datos_ruta(creado_por=admin.id_usuario, zona_geojson=json.dumps([[10.4, -66.9], [10.5, -66.8]])),
        )


def test_crear_ruta_zona_json_invalido_falla(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="JSON"):
        RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario, zona_geojson="no es json"))


def test_crear_ruta_zona_vertice_latitud_fuera_de_rango_falla(db_session):
    admin = crear_usuario_admin(db_session)
    zona = [[200, -66.9], [10.5, -66.8], [10.6, -66.7]]

    with pytest.raises(ValueError, match="latitud"):
        RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario, zona_geojson=json.dumps(zona)))


def test_crear_ruta_zona_vertice_longitud_fuera_de_rango_falla(db_session):
    admin = crear_usuario_admin(db_session)
    zona = [[10.4, -200], [10.5, -66.8], [10.6, -66.7]]

    with pytest.raises(ValueError, match="longitud"):
        RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario, zona_geojson=json.dumps(zona)))


def test_actualizar_ruta_cambia_zona(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))
    nueva_zona = [[11.0, -67.0], [11.0, -66.9], [11.1, -66.9]]

    actualizada = RutaService.actualizar(
        db_session, ruta.id_ruta, id_usuario=admin.id_usuario, zona_geojson=json.dumps(nueva_zona)
    )

    assert json.loads(actualizada.zona_geojson) == nueva_zona


def test_actualizar_ruta_no_permite_vaciar_zona(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="zona_geojson"):
        RutaService.actualizar(db_session, ruta.id_ruta, id_usuario=admin.id_usuario, zona_geojson=None)


def test_actualizar_ruta_conserva_zona_existente_al_editar_otro_campo(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    actualizada = RutaService.actualizar(
        db_session, ruta.id_ruta, id_usuario=admin.id_usuario, descripcion_ruta="Zona metropolitana"
    )

    assert json.loads(actualizada.zona_geojson) == _ZONA_EJEMPLO


# --- contiene_punto / sugerir_ruta_por_ubicacion ----------------------------------------


def test_contiene_punto_dentro_de_la_zona(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    assert RutaService.contiene_punto(ruta, 10.50, -66.90) is True


def test_contiene_punto_fuera_de_la_zona(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    assert RutaService.contiene_punto(ruta, 20.0, -66.90) is False


def test_contiene_punto_sin_zona_devuelve_false(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))
    ruta.zona_geojson = None

    assert RutaService.contiene_punto(ruta, 10.50, -66.90) is False


def test_sugerir_ruta_por_ubicacion_encuentra_la_zona_correcta(db_session):
    admin = crear_usuario_admin(db_session)
    RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))
    otra_zona = [[20.0, -67.0], [20.0, -66.8], [20.1, -66.8]]
    otra = RutaService.crear(
        db_session,
        **_datos_ruta(nombre_ruta="Ruta Norte", zona_geojson=json.dumps(otra_zona), creado_por=admin.id_usuario),
    )

    sugerida = RutaService.sugerir_ruta_por_ubicacion(db_session, 20.02, -66.9, id_usuario=admin.id_usuario)

    assert sugerida is not None
    assert sugerida.id_ruta == otra.id_ruta


def test_sugerir_ruta_por_ubicacion_sin_zona_que_contenga_el_punto(db_session):
    admin = crear_usuario_admin(db_session)
    RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    sugerida = RutaService.sugerir_ruta_por_ubicacion(db_session, 0.0, 0.0, id_usuario=admin.id_usuario)

    assert sugerida is None


def test_sugerir_ruta_por_ubicacion_ignora_rutas_inactivas(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))
    RutaService.cambiar_estado(db_session, ruta.id_ruta, "INACTIVO", id_usuario=admin.id_usuario)

    sugerida = RutaService.sugerir_ruta_por_ubicacion(db_session, 10.50, -66.90, id_usuario=admin.id_usuario)

    assert sugerida is None


def test_sugerir_ruta_por_ubicacion_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        RutaService.sugerir_ruta_por_ubicacion(db_session, 10.50, -66.90)
