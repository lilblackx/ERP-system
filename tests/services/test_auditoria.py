from datetime import datetime, timedelta

import pytest

from app.services.auditoria import AuditoriaService
from app.services.permisos import PermisoDenegadoError
from tests.factories import crear_usuario, crear_usuario_admin


def test_registrar_evento_requiere_accion(db_session):
    with pytest.raises(ValueError, match="accion es requerida"):
        AuditoriaService.registrar_evento(db_session, id_usuario=None, accion="", modulo="AUTH")


def test_registrar_evento_requiere_modulo(db_session):
    with pytest.raises(ValueError, match="modulo es requerido"):
        AuditoriaService.registrar_evento(db_session, id_usuario=None, accion="LOGIN", modulo="")


def test_registrar_evento_detalle_string(db_session):
    evento = AuditoriaService.registrar_evento(
        db_session,
        id_usuario=None,
        accion="LOGIN",
        modulo="AUTH",
        detalle="texto libre",
    )
    assert evento.detalle == "texto libre"


def test_registrar_evento_detalle_dict_se_serializa_json(db_session):
    evento = AuditoriaService.registrar_evento(
        db_session,
        id_usuario=None,
        accion="CREAR_CLIENTE",
        modulo="CLIENTES",
        detalle={"id_cliente": 5, "nombre": "X"},
    )
    assert evento.detalle == '{"id_cliente": 5, "nombre": "X"}'


def test_registrar_evento_detalle_none(db_session):
    evento = AuditoriaService.registrar_evento(db_session, id_usuario=None, accion="LOGIN", modulo="AUTH")
    assert evento.detalle is None


def test_registrar_evento_con_usuario(db_session):
    usuario = crear_usuario(db_session)
    evento = AuditoriaService.registrar_evento(db_session, id_usuario=usuario.id_usuario, accion="LOGIN", modulo="AUTH")
    assert evento.id_usuario == usuario.id_usuario


def test_consultar_auditoria_filtra_por_modulo(db_session):
    admin = crear_usuario_admin(db_session)
    AuditoriaService.registrar_evento(db_session, id_usuario=None, accion="LOGIN", modulo="AUTH")
    AuditoriaService.registrar_evento(db_session, id_usuario=None, accion="CREAR_CLIENTE", modulo="CLIENTES")

    resultado = AuditoriaService.consultar_auditoria(db_session, modulo="AUTH", id_usuario_actor=admin.id_usuario)

    assert resultado["total"] == 1
    assert resultado["items"][0].modulo == "AUTH"


def test_consultar_auditoria_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        AuditoriaService.consultar_auditoria(db_session)


def test_consultar_auditoria_filtra_por_accion(db_session):
    admin = crear_usuario_admin(db_session)
    AuditoriaService.registrar_evento(db_session, id_usuario=None, accion="LOGIN", modulo="AUTH")
    AuditoriaService.registrar_evento(db_session, id_usuario=None, accion="LOGOUT", modulo="AUTH")

    resultado = AuditoriaService.consultar_auditoria(db_session, accion="LOGOUT", id_usuario_actor=admin.id_usuario)

    assert resultado["total"] == 1
    assert resultado["items"][0].accion == "LOGOUT"


def test_consultar_auditoria_texto_busqueda_coincide_parcial_en_accion(db_session):
    admin = crear_usuario_admin(db_session)
    AuditoriaService.registrar_evento(db_session, id_usuario=None, accion="CREAR_CLIENTE", modulo="CLIENTES")
    AuditoriaService.registrar_evento(db_session, id_usuario=None, accion="LOGIN", modulo="AUTH")

    resultado = AuditoriaService.consultar_auditoria(
        db_session, texto_busqueda="cliente", id_usuario_actor=admin.id_usuario
    )

    assert resultado["total"] == 1
    assert resultado["items"][0].accion == "CREAR_CLIENTE"


def test_consultar_auditoria_texto_busqueda_coincide_en_modulo(db_session):
    admin = crear_usuario_admin(db_session)
    AuditoriaService.registrar_evento(db_session, id_usuario=None, accion="REGISTRAR_COMPRA", modulo="COMPRAS")
    AuditoriaService.registrar_evento(db_session, id_usuario=None, accion="LOGIN", modulo="AUTH")

    resultado = AuditoriaService.consultar_auditoria(
        db_session, texto_busqueda="COMPRAS", id_usuario_actor=admin.id_usuario
    )

    assert resultado["total"] == 1
    assert resultado["items"][0].modulo == "COMPRAS"


def test_consultar_auditoria_texto_busqueda_coincide_en_detalle(db_session):
    admin = crear_usuario_admin(db_session)
    AuditoriaService.registrar_evento(
        db_session,
        id_usuario=None,
        accion="CREAR_OC",
        modulo="COMPRAS",
        detalle={"numero_oc": "ODC-000001"},
    )
    AuditoriaService.registrar_evento(db_session, id_usuario=None, accion="LOGIN", modulo="AUTH")

    resultado = AuditoriaService.consultar_auditoria(
        db_session, texto_busqueda="ODC-000001", id_usuario_actor=admin.id_usuario
    )

    assert resultado["total"] == 1
    assert resultado["items"][0].accion == "CREAR_OC"


def test_consultar_auditoria_texto_busqueda_coincide_en_nombre_usuario(db_session):
    admin = crear_usuario_admin(db_session)
    usuario = crear_usuario(db_session)
    AuditoriaService.registrar_evento(db_session, id_usuario=usuario.id_usuario, accion="LOGIN", modulo="AUTH")
    # Evento de sistema sin usuario asociado -- no debe reventar el filtro por nombre de
    # usuario (Auditoria.usuario.has(...) sobre id_usuario NULL debe resolver a False, no
    # a un error, ver comentario en AuditoriaService.consultar_auditoria).
    AuditoriaService.registrar_evento(db_session, id_usuario=None, accion="LOGOUT", modulo="AUTH")

    resultado = AuditoriaService.consultar_auditoria(
        db_session,
        texto_busqueda=usuario.nombre_usuario,
        id_usuario_actor=admin.id_usuario,
    )

    assert resultado["total"] == 1
    assert resultado["items"][0].id_usuario == usuario.id_usuario


def test_consultar_auditoria_texto_busqueda_sin_coincidencias(db_session):
    admin = crear_usuario_admin(db_session)
    AuditoriaService.registrar_evento(db_session, id_usuario=None, accion="LOGIN", modulo="AUTH")

    resultado = AuditoriaService.consultar_auditoria(
        db_session,
        texto_busqueda="algo_que_no_existe",
        id_usuario_actor=admin.id_usuario,
    )

    assert resultado["total"] == 0


def test_consultar_auditoria_filtra_por_usuario(db_session):
    admin = crear_usuario_admin(db_session)
    usuario_a = crear_usuario(db_session)
    usuario_b = crear_usuario(db_session)
    AuditoriaService.registrar_evento(db_session, id_usuario=usuario_a.id_usuario, accion="LOGIN", modulo="AUTH")
    AuditoriaService.registrar_evento(db_session, id_usuario=usuario_b.id_usuario, accion="LOGIN", modulo="AUTH")

    resultado = AuditoriaService.consultar_auditoria(
        db_session, id_usuario=usuario_a.id_usuario, id_usuario_actor=admin.id_usuario
    )

    assert resultado["total"] == 1
    assert resultado["items"][0].id_usuario == usuario_a.id_usuario


def test_consultar_auditoria_filtra_por_rango_de_fechas(db_session):
    admin = crear_usuario_admin(db_session)
    ahora = datetime.now()

    reciente = AuditoriaService.registrar_evento(db_session, id_usuario=None, accion="LOGIN", modulo="AUTH")
    reciente.fecha_evento = ahora - timedelta(days=10)
    db_session.commit()

    AuditoriaService.registrar_evento(db_session, id_usuario=None, accion="LOGOUT", modulo="AUTH")

    resultado = AuditoriaService.consultar_auditoria(
        db_session,
        fecha_desde=ahora - timedelta(days=1),
        id_usuario_actor=admin.id_usuario,
    )

    assert resultado["total"] == 1
    assert resultado["items"][0].accion == "LOGOUT"


def test_consultar_auditoria_paginacion(db_session):
    admin = crear_usuario_admin(db_session)
    for i in range(5):
        AuditoriaService.registrar_evento(db_session, id_usuario=None, accion=f"EVENTO_{i}", modulo="AUTH")

    pagina1 = AuditoriaService.consultar_auditoria(
        db_session, pagina=1, por_pagina=2, id_usuario_actor=admin.id_usuario
    )
    pagina2 = AuditoriaService.consultar_auditoria(
        db_session, pagina=2, por_pagina=2, id_usuario_actor=admin.id_usuario
    )

    assert pagina1["total"] == 5
    assert len(pagina1["items"]) == 2
    assert len(pagina2["items"]) == 2
    ids_pagina1 = {e.id_auditoria for e in pagina1["items"]}
    ids_pagina2 = {e.id_auditoria for e in pagina2["items"]}
    assert ids_pagina1.isdisjoint(ids_pagina2)


# -- Auditoria de productos: paginada, con conteos de todo el filtro --------------------------------------


def _evento_inventario(db_session, accion, id_producto, **extra):
    detalle = {"id_producto": id_producto, "nombre_producto": extra.pop("nombre", "Aceite"), **extra}
    return AuditoriaService.registrar_evento(db_session, None, accion, "INVENTARIO", detalle)


def test_auditoria_de_producto_no_mezcla_el_12_con_el_123(db_session):
    _evento_inventario(db_session, "CAMBIO_PRECIO", 12)
    _evento_inventario(db_session, "CAMBIO_PRECIO", 123)
    _evento_inventario(db_session, "CAMBIO_PRECIO", 1234)

    resultado = AuditoriaService.consultar_auditoria_producto(db_session, producto_id=12)

    assert resultado["total"] == 1
    assert '"id_producto": 12,' in resultado["items"][0].detalle


def test_auditoria_de_producto_encuentra_las_recepciones_por_su_id_en_texto(db_session):
    AuditoriaService.registrar_evento(
        db_session, None, "RECEPCION_MERCANCIA", "INVENTARIO", "Recibido Aceite (ID: 12) cantidad 5"
    )
    AuditoriaService.registrar_evento(
        db_session, None, "RECEPCION_MERCANCIA", "INVENTARIO", "Recibido Harina (ID: 123) cantidad 5"
    )

    resultado = AuditoriaService.consultar_auditoria_producto(db_session, producto_id=12)

    assert resultado["total"] == 1


def test_auditoria_de_producto_pagina_y_cuenta_todo_el_filtro(db_session):
    for _ in range(7):
        _evento_inventario(db_session, "CAMBIO_PRECIO", 5)
    for _ in range(3):
        _evento_inventario(db_session, "MOVIMIENTO_STOCK", 5)

    p1 = AuditoriaService.consultar_auditoria_producto(db_session, producto_id=5, pagina=1, por_pagina=4)
    p3 = AuditoriaService.consultar_auditoria_producto(db_session, producto_id=5, pagina=3, por_pagina=4)

    assert (p1["total"], p1["total_paginas"], len(p1["items"])) == (10, 3, 4)
    assert len(p3["items"]) == 2
    assert p1["por_accion"] == {"CAMBIO_PRECIO": 7, "MOVIMIENTO_STOCK": 3}  # de todo el filtro, no de la pagina
    ids = [e.id_auditoria for e in p1["items"]] + [e.id_auditoria for e in p3["items"]]
    assert len(set(ids)) == len(ids)


def test_auditoria_de_producto_filtra_por_accion_y_texto_en_la_base(db_session):
    _evento_inventario(db_session, "CAMBIO_PRECIO", 5, nombre="Aceite Girasol")
    _evento_inventario(db_session, "CAMBIO_PRECIO", 6, nombre="Harina")
    _evento_inventario(db_session, "MOVIMIENTO_STOCK", 5, nombre="Aceite Girasol")

    por_texto = AuditoriaService.consultar_auditoria_producto(db_session, texto="girasol")
    por_accion = AuditoriaService.consultar_auditoria_producto(db_session, accion="CAMBIO_PRECIO")

    assert por_texto["total"] == 2  # sin distinguir mayusculas
    assert por_accion["total"] == 2


def test_auditoria_de_producto_solo_trae_eventos_de_inventario(db_session):
    _evento_inventario(db_session, "CAMBIO_PRECIO", 5)
    AuditoriaService.registrar_evento(db_session, None, "CREAR_CLIENTE", "CLIENTES", {"id_producto": 5})

    assert AuditoriaService.consultar_auditoria_producto(db_session, producto_id=5)["total"] == 1


def test_auditoria_de_producto_respeta_el_rango_de_fechas(db_session):
    evento = _evento_inventario(db_session, "CAMBIO_PRECIO", 5)
    evento.fecha_evento = datetime.now() - timedelta(days=40)
    db_session.commit()
    _evento_inventario(db_session, "CAMBIO_PRECIO", 5)

    reciente = AuditoriaService.consultar_auditoria_producto(
        db_session, producto_id=5, fecha_desde=datetime.now() - timedelta(days=7)
    )
    todo = AuditoriaService.consultar_auditoria_producto(db_session, producto_id=5)

    assert (reciente["total"], todo["total"]) == (1, 2)


# -- Bitacora: la busqueda ya no usa comodines del usuario ni un EXISTS por fila ---------------------------


def test_la_busqueda_de_la_bitacora_trata_el_guion_bajo_como_texto(db_session):
    admin = crear_usuario_admin(db_session)
    AuditoriaService.registrar_evento(db_session, None, "CREAR_CLIENTE", "CLIENTES")
    AuditoriaService.registrar_evento(db_session, None, "CREARXCLIENTE", "CLIENTES")

    resultado = AuditoriaService.consultar_auditoria(
        db_session, texto_busqueda="CREAR_CLIENTE", id_usuario_actor=admin.id_usuario
    )

    assert [e.accion for e in resultado["items"]] == ["CREAR_CLIENTE"]


def test_la_busqueda_de_la_bitacora_encuentra_por_nombre_de_usuario_y_no_pierde_eventos_de_sistema(db_session):
    admin = crear_usuario_admin(db_session)
    otro = crear_usuario(db_session, nombre_usuario="zeta_unico")
    AuditoriaService.registrar_evento(db_session, otro.id_usuario, "LOGIN", "AUTH")
    AuditoriaService.registrar_evento(db_session, None, "ARRANQUE", "SISTEMA")

    por_usuario = AuditoriaService.consultar_auditoria(
        db_session, texto_busqueda="zeta_unico", id_usuario_actor=admin.id_usuario
    )
    por_accion = AuditoriaService.consultar_auditoria(
        db_session, texto_busqueda="ARRANQUE", id_usuario_actor=admin.id_usuario
    )

    assert [e.accion for e in por_usuario["items"]] == ["LOGIN"]
    assert [e.accion for e in por_accion["items"]] == ["ARRANQUE"]
