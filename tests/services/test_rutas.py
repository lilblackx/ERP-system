import json

import pytest

from app.services.permisos import PermisoDenegadoError
from app.services.rutas import RutaService
from tests.factories import crear_usuario_admin


def _datos_ruta(**overrides) -> dict:
    datos = {
        "nombre_ruta": "Ruta Centro",
        # latitud/longitud (origen) y destino_latitud/destino_longitud son obligatorias
        # (decision de producto, 2026-09-01; destino agregado en migrations/0040) --
        # default aca para no repetirlo en cada test que no le interesa la geolocalizacion
        # en si.
        "latitud": 10.4806,
        "longitud": -66.9036,
        "destino_latitud": 10.5000,
        "destino_longitud": -66.8500,
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


# --- geolocalizacion (latitud/longitud) -----------------------------------------------


def test_crear_ruta_con_coordenadas(db_session):
    admin = crear_usuario_admin(db_session)

    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario, latitud=10.4806, longitud=-66.9036))

    assert float(ruta.latitud) == pytest.approx(10.4806)
    assert float(ruta.longitud) == pytest.approx(-66.9036)


def test_crear_ruta_requiere_latitud(db_session):
    """La ubicacion es obligatoria (decision de producto, 2026-09-01) -- no se puede
    crear una ruta sin latitud/longitud."""
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="latitud"):
        RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario, latitud=None))


def test_crear_ruta_requiere_longitud(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="longitud"):
        RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario, longitud=None))


def test_crear_ruta_latitud_fuera_de_rango_falla(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="latitud"):
        RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario, latitud=200, longitud=-66.9036))


def test_crear_ruta_longitud_fuera_de_rango_falla(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="longitud"):
        RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario, latitud=10.4806, longitud=200))


def test_actualizar_ruta_cambia_coordenadas(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    actualizada = RutaService.actualizar(
        db_session, ruta.id_ruta, id_usuario=admin.id_usuario, latitud=11.0, longitud=-67.0
    )

    assert float(actualizada.latitud) == pytest.approx(11.0)


def test_actualizar_ruta_no_permite_vaciar_latitud(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="latitud"):
        RutaService.actualizar(db_session, ruta.id_ruta, id_usuario=admin.id_usuario, latitud=None)


def test_actualizar_ruta_no_permite_vaciar_longitud(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="longitud"):
        RutaService.actualizar(db_session, ruta.id_ruta, id_usuario=admin.id_usuario, longitud=None)


def test_actualizar_ruta_conserva_coordenadas_existentes_al_editar_otro_campo(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario, latitud=10.4806, longitud=-66.9036))

    actualizada = RutaService.actualizar(
        db_session, ruta.id_ruta, id_usuario=admin.id_usuario, descripcion_ruta="Zona metropolitana"
    )

    assert float(actualizada.latitud) == pytest.approx(10.4806)
    assert float(actualizada.longitud) == pytest.approx(-66.9036)


# --- destino / trazado (migrations/0040) ----------------------------------------------


def test_crear_ruta_con_destino(db_session):
    admin = crear_usuario_admin(db_session)

    ruta = RutaService.crear(
        db_session, **_datos_ruta(creado_por=admin.id_usuario, destino_latitud=11.0, destino_longitud=-67.0)
    )

    assert float(ruta.destino_latitud) == pytest.approx(11.0)
    assert float(ruta.destino_longitud) == pytest.approx(-67.0)


def test_crear_ruta_requiere_destino_latitud(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="destino_latitud"):
        RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario, destino_latitud=None))


def test_crear_ruta_requiere_destino_longitud(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="destino_longitud"):
        RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario, destino_longitud=None))


def test_crear_ruta_destino_latitud_fuera_de_rango_falla(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="latitud"):
        RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario, destino_latitud=200))


def test_crear_ruta_destino_longitud_fuera_de_rango_falla(db_session):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="longitud"):
        RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario, destino_longitud=200))


def test_actualizar_ruta_no_permite_vaciar_destino_latitud(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="destino_latitud"):
        RutaService.actualizar(db_session, ruta.id_ruta, id_usuario=admin.id_usuario, destino_latitud=None)


def test_actualizar_ruta_no_permite_vaciar_destino_longitud(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="destino_longitud"):
        RutaService.actualizar(db_session, ruta.id_ruta, id_usuario=admin.id_usuario, destino_longitud=None)


def test_distancia_a_trazado_sin_trazado_devuelve_none(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))

    assert RutaService.distancia_a_trazado(ruta, 10.4806, -66.9036) is None


def test_distancia_a_trazado_punto_sobre_el_trazado_es_cercano(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))
    ruta.trazado_geojson = json.dumps([[10.4806, -66.9036], [10.5000, -66.8500]])

    distancia = RutaService.distancia_a_trazado(ruta, 10.4806, -66.9036)

    assert distancia == pytest.approx(0.0, abs=1e-6)


def test_distancia_a_trazado_punto_lejano_devuelve_distancia_grande(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = RutaService.crear(db_session, **_datos_ruta(creado_por=admin.id_usuario))
    ruta.trazado_geojson = json.dumps([[10.4806, -66.9036], [10.5000, -66.8500]])

    # ~1100km al norte -- lejos de cualquier vertice del trazado de arriba.
    distancia = RutaService.distancia_a_trazado(ruta, 20.0, -66.9036)

    assert distancia > 100
