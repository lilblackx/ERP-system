from app.services.empresa import EmpresaService


def test_obtener_configuracion_sin_datos(db_session):
    assert EmpresaService.obtener_configuracion(db_session) is None


def test_guardar_configuracion_crea_si_no_existe(db_session):
    config = EmpresaService.guardar_configuracion(
        db_session, rif="J-12345678-9", razon_social="Distribuidora DJ", direccion="Calle 1", telefono="0212-1234567"
    )

    assert config.id_config is not None
    assert config.razon_social_empresa == "Distribuidora DJ"


def test_guardar_configuracion_actualiza_registro_singleton(db_session):
    primero = EmpresaService.guardar_configuracion(
        db_session, rif="J-11111111-1", razon_social="Nombre Original", direccion=None, telefono=None
    )

    segundo = EmpresaService.guardar_configuracion(
        db_session, rif="J-11111111-1", razon_social="Nombre Actualizado", direccion=None, telefono=None
    )

    assert segundo.id_config == primero.id_config
    assert segundo.razon_social_empresa == "Nombre Actualizado"

    todas = db_session.query(type(primero)).all()
    assert len(todas) == 1


def test_guardar_configuracion_logo_sentinel_no_toca_logo(db_session):
    EmpresaService.guardar_configuracion(
        db_session, rif=None, razon_social=None, direccion=None, telefono=None, logo_bytes=b"logo-original"
    )

    actualizado = EmpresaService.guardar_configuracion(
        db_session, rif=None, razon_social="Nuevo nombre", direccion=None, telefono=None
    )

    assert actualizado.logotipo_empresa == b"logo-original"


def test_guardar_configuracion_logo_none_lo_borra(db_session):
    EmpresaService.guardar_configuracion(
        db_session, rif=None, razon_social=None, direccion=None, telefono=None, logo_bytes=b"logo-original"
    )

    actualizado = EmpresaService.guardar_configuracion(
        db_session, rif=None, razon_social=None, direccion=None, telefono=None, logo_bytes=None
    )

    assert actualizado.logotipo_empresa is None


def test_guardar_configuracion_registra_modificado_por(db_session):
    from tests.factories import crear_usuario

    usuario = crear_usuario(db_session)

    config = EmpresaService.guardar_configuracion(
        db_session, rif=None, razon_social=None, direccion=None, telefono=None, modificado_por=usuario.id_usuario
    )

    assert config.modificado_por == usuario.id_usuario
