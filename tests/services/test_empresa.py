from decimal import Decimal

import pytest

from app.services.empresa import EmpresaService
from app.services.permisos import PermisoDenegadoError
from tests.factories import crear_usuario_admin


def test_obtener_configuracion_sin_datos(db_session):
    admin = crear_usuario_admin(db_session)
    assert EmpresaService.obtener_configuracion(db_session, id_usuario=admin.id_usuario) is None


def test_obtener_configuracion_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        EmpresaService.obtener_configuracion(db_session)


def test_guardar_configuracion_crea_si_no_existe(db_session):
    admin = crear_usuario_admin(db_session)
    config = EmpresaService.guardar_configuracion(
        db_session,
        rif="J-12345678-9",
        razon_social="Distribuidora DJ",
        direccion="Calle 1",
        telefono="0212-1234567",
        modificado_por=admin.id_usuario,
    )

    assert config.id_config is not None
    assert config.razon_social_empresa == "Distribuidora DJ"


def test_guardar_configuracion_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        EmpresaService.guardar_configuracion(
            db_session, rif="J-12345678-9", razon_social="Distribuidora DJ", direccion=None, telefono=None
        )


def test_guardar_configuracion_actualiza_registro_singleton(db_session):
    admin = crear_usuario_admin(db_session)
    primero = EmpresaService.guardar_configuracion(
        db_session,
        rif="J-11111111-1",
        razon_social="Nombre Original",
        direccion=None,
        telefono=None,
        modificado_por=admin.id_usuario,
    )

    segundo = EmpresaService.guardar_configuracion(
        db_session,
        rif="J-11111111-1",
        razon_social="Nombre Actualizado",
        direccion=None,
        telefono=None,
        modificado_por=admin.id_usuario,
    )

    assert segundo.id_config == primero.id_config
    assert segundo.razon_social_empresa == "Nombre Actualizado"

    todas = db_session.query(type(primero)).all()
    assert len(todas) == 1


def test_guardar_configuracion_logo_sentinel_no_toca_logo(db_session):
    admin = crear_usuario_admin(db_session)
    EmpresaService.guardar_configuracion(
        db_session,
        rif=None,
        razon_social=None,
        direccion=None,
        telefono=None,
        logo_bytes=b"logo-original",
        modificado_por=admin.id_usuario,
    )

    actualizado = EmpresaService.guardar_configuracion(
        db_session,
        rif=None,
        razon_social="Nuevo nombre",
        direccion=None,
        telefono=None,
        modificado_por=admin.id_usuario,
    )

    assert actualizado.logotipo_empresa == b"logo-original"


def test_guardar_configuracion_logo_none_lo_borra(db_session):
    admin = crear_usuario_admin(db_session)
    EmpresaService.guardar_configuracion(
        db_session,
        rif=None,
        razon_social=None,
        direccion=None,
        telefono=None,
        logo_bytes=b"logo-original",
        modificado_por=admin.id_usuario,
    )

    actualizado = EmpresaService.guardar_configuracion(
        db_session,
        rif=None,
        razon_social=None,
        direccion=None,
        telefono=None,
        logo_bytes=None,
        modificado_por=admin.id_usuario,
    )

    assert actualizado.logotipo_empresa is None


def test_guardar_configuracion_registra_modificado_por(db_session):
    admin = crear_usuario_admin(db_session)

    config = EmpresaService.guardar_configuracion(
        db_session, rif=None, razon_social=None, direccion=None, telefono=None, modificado_por=admin.id_usuario
    )

    assert config.modificado_por == admin.id_usuario


def test_guardar_configuracion_default_iva_desactivado(db_session):
    admin = crear_usuario_admin(db_session)
    config = EmpresaService.guardar_configuracion(
        db_session, rif=None, razon_social=None, direccion=None, telefono=None, modificado_por=admin.id_usuario
    )

    assert config.iva_activo is False


def test_guardar_configuracion_iva_activo_y_porcentaje_y_pie_pagina(db_session):
    admin = crear_usuario_admin(db_session)
    config = EmpresaService.guardar_configuracion(
        db_session,
        rif=None,
        razon_social=None,
        direccion=None,
        telefono=None,
        pie_pagina="Gracias por su compra",
        iva_activo=True,
        iva_porcentaje="16.00",
        modificado_por=admin.id_usuario,
    )

    assert config.iva_activo is True
    assert config.iva_porcentaje == Decimal("16.00")
    assert config.pie_pagina_empresa == "Gracias por su compra"


def test_guardar_configuracion_iva_porcentaje_fuera_de_rango_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="entre 0 y 100"):
        EmpresaService.guardar_configuracion(
            db_session,
            rif=None,
            razon_social=None,
            direccion=None,
            telefono=None,
            iva_porcentaje="150.00",
            modificado_por=admin.id_usuario,
        )
