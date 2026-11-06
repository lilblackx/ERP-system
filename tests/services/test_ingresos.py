"""Primer ingreso de un usuario: se deduce de los eventos LOGIN de la auditoria (el actual ya esta registrado)."""

from app.db.models import Auditoria
from app.services.auth import contar_ingresos, es_primer_ingreso
from tests.factories import crear_usuario


def _login(session, usuario, accion="LOGIN", modulo="AUTH"):
    session.add(Auditoria(id_usuario=usuario.id_usuario, accion=accion, modulo=modulo, detalle="x"))
    session.commit()


def test_con_un_solo_login_es_su_primer_ingreso(db_session):
    u = crear_usuario(db_session)
    _login(db_session, u)  # el de la sesion actual

    assert contar_ingresos(db_session, u.id_usuario) == 1
    assert es_primer_ingreso(db_session, u.id_usuario)


def test_con_logins_anteriores_ya_no_es_el_primer_ingreso(db_session):
    u = crear_usuario(db_session)
    _login(db_session, u)
    _login(db_session, u)

    assert contar_ingresos(db_session, u.id_usuario) == 2
    assert not es_primer_ingreso(db_session, u.id_usuario)


def test_solo_cuentan_los_eventos_login_del_propio_usuario(db_session):
    u1, u2 = crear_usuario(db_session), crear_usuario(db_session)
    _login(db_session, u1)
    _login(db_session, u2)
    _login(db_session, u2)
    _login(db_session, u1, accion="LOGIN_FALLIDO")  # un intento fallido no es un ingreso
    _login(db_session, u1, accion="AUTORIZACION_DESCUENTO")  # tampoco la autorizacion de un descuento

    assert contar_ingresos(db_session, u1.id_usuario) == 1
    assert contar_ingresos(db_session, u2.id_usuario) == 2
