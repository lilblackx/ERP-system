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
    evento = AuditoriaService.registrar_evento(db_session, id_usuario=None, accion="LOGIN", modulo="AUTH", detalle="texto libre")
    assert evento.detalle == "texto libre"


def test_registrar_evento_detalle_dict_se_serializa_json(db_session):
    evento = AuditoriaService.registrar_evento(
        db_session, id_usuario=None, accion="CREAR_CLIENTE", modulo="CLIENTES", detalle={"id_cliente": 5, "nombre": "X"}
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
        db_session, fecha_desde=ahora - timedelta(days=1), id_usuario_actor=admin.id_usuario
    )

    assert resultado["total"] == 1
    assert resultado["items"][0].accion == "LOGOUT"


def test_consultar_auditoria_paginacion(db_session):
    admin = crear_usuario_admin(db_session)
    for i in range(5):
        AuditoriaService.registrar_evento(db_session, id_usuario=None, accion=f"EVENTO_{i}", modulo="AUTH")

    pagina1 = AuditoriaService.consultar_auditoria(db_session, pagina=1, por_pagina=2, id_usuario_actor=admin.id_usuario)
    pagina2 = AuditoriaService.consultar_auditoria(db_session, pagina=2, por_pagina=2, id_usuario_actor=admin.id_usuario)

    assert pagina1["total"] == 5
    assert len(pagina1["items"]) == 2
    assert len(pagina2["items"]) == 2
    ids_pagina1 = {e.id_auditoria for e in pagina1["items"]}
    ids_pagina2 = {e.id_auditoria for e in pagina2["items"]}
    assert ids_pagina1.isdisjoint(ids_pagina2)
