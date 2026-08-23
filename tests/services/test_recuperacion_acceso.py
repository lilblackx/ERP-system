from datetime import datetime, timedelta

import pytest

from app.db.models import CodigoVerificacion
from app.services import recuperacion_acceso as ra
from app.services.auth import MAX_INTENTOS_FALLIDOS, authenticate, hash_password
from app.services.recuperacion_acceso import MAX_INTENTOS_VERIFICACION, RecuperacionAccesoService
from tests.factories import crear_usuario


def _crear_usuario_con_email(session, **overrides):
    datos = {
        "nombre_usuario": "jperez",
        "clave": hash_password("Secreta123!"),
        "email": "jperez@example.com",
        "estado": "ACTIVO",
    }
    datos.update(overrides)
    return crear_usuario(session, **datos)


@pytest.fixture
def codigos_capturados(monkeypatch):
    """Intercepta el envio real de correo -- los tests nunca deben tocar SMTP real."""
    enviados = []

    def _fake_enviar(destinatario, asunto, cuerpo):
        enviados.append({"destinatario": destinatario, "asunto": asunto, "cuerpo": cuerpo})

    monkeypatch.setattr(ra, "enviar_correo", _fake_enviar)
    return enviados


def _extraer_codigo(cuerpo: str) -> str:
    primera_linea = cuerpo.splitlines()[0]
    return primera_linea.split(":")[-1].strip()


def _bloquear_usuario(session, nombre_usuario="jperez") -> None:
    for _ in range(MAX_INTENTOS_FALLIDOS):
        authenticate(session, nombre_usuario, "ClaveIncorrecta")


# --- solicitar_codigo_* --------------------------------------------------------------


def test_solicitar_codigo_desbloqueo_envia_correo(db_session, codigos_capturados):
    _crear_usuario_con_email(db_session)

    RecuperacionAccesoService.solicitar_codigo_desbloqueo(db_session, "jperez")

    assert len(codigos_capturados) == 1
    assert codigos_capturados[0]["destinatario"] == "jperez@example.com"


def test_solicitar_codigo_usuario_inexistente_no_envia_y_responde_generico(db_session, codigos_capturados):
    mensaje = RecuperacionAccesoService.solicitar_codigo_desbloqueo(db_session, "no_existe")

    assert codigos_capturados == []
    assert "correo" in mensaje.lower()


def test_solicitar_codigo_usuario_sin_email_no_envia(db_session, codigos_capturados):
    _crear_usuario_con_email(db_session, email=None)

    RecuperacionAccesoService.solicitar_codigo_desbloqueo(db_session, "jperez")

    assert codigos_capturados == []


# --- verificar_codigo_desbloqueo ------------------------------------------------------


def test_verificar_codigo_desbloqueo_correcto_desbloquea(db_session, codigos_capturados):
    usuario = _crear_usuario_con_email(db_session)
    _bloquear_usuario(db_session)
    db_session.refresh(usuario)
    assert usuario.bloqueado_desde is not None

    RecuperacionAccesoService.solicitar_codigo_desbloqueo(db_session, "jperez")
    codigo = _extraer_codigo(codigos_capturados[0]["cuerpo"])

    RecuperacionAccesoService.verificar_codigo_desbloqueo(db_session, "jperez", codigo)

    db_session.refresh(usuario)
    assert usuario.bloqueado_desde is None
    assert usuario.intentos_fallidos == 0


def test_verificar_codigo_desbloqueo_no_cambia_la_clave(db_session, codigos_capturados):
    _crear_usuario_con_email(db_session)
    _bloquear_usuario(db_session)
    RecuperacionAccesoService.solicitar_codigo_desbloqueo(db_session, "jperez")
    codigo = _extraer_codigo(codigos_capturados[0]["cuerpo"])

    RecuperacionAccesoService.verificar_codigo_desbloqueo(db_session, "jperez", codigo)

    assert authenticate(db_session, "jperez", "Secreta123!") is not None


def test_verificar_codigo_incorrecto_no_desbloquea(db_session, codigos_capturados):
    usuario = _crear_usuario_con_email(db_session)
    _bloquear_usuario(db_session)
    RecuperacionAccesoService.solicitar_codigo_desbloqueo(db_session, "jperez")

    with pytest.raises(ValueError):
        RecuperacionAccesoService.verificar_codigo_desbloqueo(db_session, "jperez", "000000")

    db_session.refresh(usuario)
    assert usuario.bloqueado_desde is not None


def test_verificar_codigo_agota_intentos_e_invalida(db_session, codigos_capturados):
    _crear_usuario_con_email(db_session)
    RecuperacionAccesoService.solicitar_codigo_desbloqueo(db_session, "jperez")
    codigo_real = _extraer_codigo(codigos_capturados[0]["cuerpo"])

    for _ in range(MAX_INTENTOS_VERIFICACION):
        with pytest.raises(ValueError):
            RecuperacionAccesoService.verificar_codigo_desbloqueo(db_session, "jperez", "000000")

    with pytest.raises(ValueError):
        RecuperacionAccesoService.verificar_codigo_desbloqueo(db_session, "jperez", codigo_real)


def test_verificar_codigo_expirado_falla(db_session, codigos_capturados):
    _crear_usuario_con_email(db_session)
    RecuperacionAccesoService.solicitar_codigo_desbloqueo(db_session, "jperez")
    codigo = _extraer_codigo(codigos_capturados[0]["cuerpo"])

    registro = db_session.query(CodigoVerificacion).order_by(CodigoVerificacion.id_codigo.desc()).first()
    registro.fecha_expiracion = datetime.now() - timedelta(minutes=1)
    db_session.commit()

    with pytest.raises(ValueError):
        RecuperacionAccesoService.verificar_codigo_desbloqueo(db_session, "jperez", codigo)


def test_verificar_codigo_sin_solicitud_previa_falla(db_session):
    _crear_usuario_con_email(db_session)

    with pytest.raises(ValueError):
        RecuperacionAccesoService.verificar_codigo_desbloqueo(db_session, "jperez", "123456")


# --- solicitar_codigo_recuperacion / verificar_codigo_y_cambiar_clave -----------------


def test_recuperar_clave_flujo_completo(db_session, codigos_capturados):
    usuario = _crear_usuario_con_email(db_session)

    RecuperacionAccesoService.solicitar_codigo_recuperacion(db_session, "jperez")
    codigo = _extraer_codigo(codigos_capturados[0]["cuerpo"])

    RecuperacionAccesoService.verificar_codigo_y_cambiar_clave(db_session, "jperez", codigo, "NuevaClave123!")

    db_session.refresh(usuario)
    assert authenticate(db_session, "jperez", "NuevaClave123!") is not None
    assert usuario.bloqueado_desde is None
    assert usuario.intentos_fallidos == 0


def test_recuperar_clave_rechaza_clave_debil_sin_quemar_el_codigo(db_session, codigos_capturados):
    _crear_usuario_con_email(db_session)
    RecuperacionAccesoService.solicitar_codigo_recuperacion(db_session, "jperez")
    codigo = _extraer_codigo(codigos_capturados[0]["cuerpo"])

    with pytest.raises(ValueError, match="politica de seguridad"):
        RecuperacionAccesoService.verificar_codigo_y_cambiar_clave(db_session, "jperez", codigo, "debil")

    # El codigo sigue vigente: rechazar la clave no debe quemarlo.
    RecuperacionAccesoService.verificar_codigo_y_cambiar_clave(db_session, "jperez", codigo, "NuevaClave123!")
    assert authenticate(db_session, "jperez", "NuevaClave123!") is not None


def test_recuperar_clave_desbloquea_cuenta_bloqueada(db_session, codigos_capturados):
    usuario = _crear_usuario_con_email(db_session)
    _bloquear_usuario(db_session)
    db_session.refresh(usuario)
    assert usuario.bloqueado_desde is not None

    RecuperacionAccesoService.solicitar_codigo_recuperacion(db_session, "jperez")
    codigo = _extraer_codigo(codigos_capturados[0]["cuerpo"])
    RecuperacionAccesoService.verificar_codigo_y_cambiar_clave(db_session, "jperez", codigo, "NuevaClave123!")

    db_session.refresh(usuario)
    assert usuario.bloqueado_desde is None


def test_recuperar_clave_codigo_de_desbloqueo_no_sirve_para_cambiar_clave(db_session, codigos_capturados):
    """Los dos tipos de codigo son independientes: uno de DESBLOQUEO no debe poder
    usarse en el flujo de RECUPERAR_CLAVE ni viceversa."""
    _crear_usuario_con_email(db_session)
    RecuperacionAccesoService.solicitar_codigo_desbloqueo(db_session, "jperez")
    codigo_desbloqueo = _extraer_codigo(codigos_capturados[0]["cuerpo"])

    with pytest.raises(ValueError):
        RecuperacionAccesoService.verificar_codigo_y_cambiar_clave(
            db_session, "jperez", codigo_desbloqueo, "NuevaClave123!"
        )
