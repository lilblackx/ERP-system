from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.db.models import ControlDeTasa
from app.services.permisos import PermisoDenegadoError
from app.services.tasas import TasaService
from tests.factories import crear_usuario_admin


def _insertar_tasa(session, fecha_tasa, tasa_bcv, tasa_paralelo=None, tasa_cop=None) -> ControlDeTasa:
    tasa = ControlDeTasa(
        fecha_tasa=fecha_tasa,
        tasa_dolar_bcv=Decimal(str(tasa_bcv)),
        tasa_dolar_paralelo=Decimal(str(tasa_paralelo)) if tasa_paralelo is not None else None,
        tasa_cop=Decimal(str(tasa_cop)) if tasa_cop is not None else None,
    )
    session.add(tasa)
    session.commit()
    session.refresh(tasa)
    return tasa


def test_registrar_tasa(db_session):
    admin = crear_usuario_admin(db_session)
    tasa = TasaService.registrar_tasa(
        db_session, tasa_bcv=Decimal("40.00"), tasa_paralelo=Decimal("42.00"), creado_por=admin.id_usuario
    )

    assert tasa.id_tasa is not None
    assert tasa.tasa_dolar_bcv == Decimal("40.00")
    assert tasa.tasa_dolar_paralelo == Decimal("42.00")


def test_registrar_tasa_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        TasaService.registrar_tasa(db_session, tasa_bcv=Decimal("40.00"))


def test_registrar_tasa_bcv_invalida(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="tasa_bcv debe ser mayor a cero"):
        TasaService.registrar_tasa(db_session, tasa_bcv=Decimal("0.00"), creado_por=admin.id_usuario)


def test_registrar_tasa_bcv_negativa(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="tasa_bcv debe ser mayor a cero"):
        TasaService.registrar_tasa(db_session, tasa_bcv=Decimal("-1.00"), creado_por=admin.id_usuario)


def test_obtener_tasa_actual_sin_tasas(db_session):
    admin = crear_usuario_admin(db_session)
    assert TasaService.obtener_tasa_actual(db_session, id_usuario=admin.id_usuario) is None


def test_obtener_tasa_actual_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        TasaService.obtener_tasa_actual(db_session)


def test_obtener_tasa_actual_sin_tasa_anterior(db_session):
    admin = crear_usuario_admin(db_session)
    TasaService.registrar_tasa(db_session, tasa_bcv=Decimal("40.00"), creado_por=admin.id_usuario)

    actual = TasaService.obtener_tasa_actual(db_session, id_usuario=admin.id_usuario)

    assert actual["tasa_bcv"] == Decimal("40.00")
    assert actual["porcentaje_vs_ayer_bcv"] is None


def test_obtener_tasa_actual_calcula_porcentaje_vs_ayer(db_session):
    admin = crear_usuario_admin(db_session)
    ayer = datetime.now() - timedelta(days=1)
    _insertar_tasa(db_session, ayer, tasa_bcv=Decimal("100.00"))

    TasaService.registrar_tasa(db_session, tasa_bcv=Decimal("110.00"), creado_por=admin.id_usuario)

    actual = TasaService.obtener_tasa_actual(db_session, id_usuario=admin.id_usuario)

    assert actual["tasa_bcv"] == Decimal("110.00")
    assert actual["porcentaje_vs_ayer_bcv"] == 10.0


def test_obtener_tasa_actual_devuelve_la_mas_reciente(db_session):
    admin = crear_usuario_admin(db_session)
    ayer = datetime.now() - timedelta(days=1)
    _insertar_tasa(db_session, ayer, tasa_bcv=Decimal("100.00"))
    TasaService.registrar_tasa(db_session, tasa_bcv=Decimal("105.00"), creado_por=admin.id_usuario)
    mas_reciente = TasaService.registrar_tasa(db_session, tasa_bcv=Decimal("110.00"), creado_por=admin.id_usuario)

    actual = TasaService.obtener_tasa_actual(db_session, id_usuario=admin.id_usuario)

    assert actual["id_tasa"] == mas_reciente.id_tasa


def test_obtener_historico_tasas_orden_cronologico_ascendente(db_session):
    admin = crear_usuario_admin(db_session)
    base = datetime.now() - timedelta(days=3)
    t1 = _insertar_tasa(db_session, base, tasa_bcv=Decimal("100.00"))
    t2 = _insertar_tasa(db_session, base + timedelta(days=1), tasa_bcv=Decimal("101.00"))
    t3 = _insertar_tasa(db_session, base + timedelta(days=2), tasa_bcv=Decimal("102.00"))

    historico = TasaService.obtener_historico_tasas(db_session, id_usuario=admin.id_usuario)

    assert [h["id_tasa"] for h in historico] == [t1.id_tasa, t2.id_tasa, t3.id_tasa]


def test_obtener_historico_tasas_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        TasaService.obtener_historico_tasas(db_session)


def test_obtener_historico_tasas_respeta_limite(db_session):
    admin = crear_usuario_admin(db_session)
    base = datetime.now() - timedelta(days=5)
    for i in range(5):
        _insertar_tasa(db_session, base + timedelta(days=i), tasa_bcv=Decimal("100.00") + i)

    historico = TasaService.obtener_historico_tasas(db_session, limite=2, id_usuario=admin.id_usuario)

    assert len(historico) == 2


def test_obtener_historico_tasas_calcula_brecha(db_session):
    admin = crear_usuario_admin(db_session)
    _insertar_tasa(db_session, datetime.now(), tasa_bcv=Decimal("100.00"), tasa_paralelo=Decimal("120.00"))

    historico = TasaService.obtener_historico_tasas(db_session, id_usuario=admin.id_usuario)

    assert historico[0]["brecha_porcentual"] == 20.0


def test_obtener_historico_tasas_sin_paralelo_brecha_none(db_session):
    admin = crear_usuario_admin(db_session)
    _insertar_tasa(db_session, datetime.now(), tasa_bcv=Decimal("100.00"))

    historico = TasaService.obtener_historico_tasas(db_session, id_usuario=admin.id_usuario)

    assert historico[0]["brecha_porcentual"] is None
