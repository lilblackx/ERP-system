import smtplib
import socket

import pytest

from app import config
from app.db.models import Auditoria
from app.services.email_service import AjustesSmtp
from app.services.permisos import PermisoDenegadoError
from app.services.smtp_config import (
    PROVEEDOR_OTRO,
    PROVEEDORES,
    SmtpConfigService,
    proveedor_de_servidor,
    proveedor_por_clave,
)
from tests.factories import crear_usuario_admin


def _guardar(db_session, admin, **overrides):
    datos = {
        "host": "smtp.example.com",
        "puerto": 587,
        "usuario": "bot@example.com",
        "password": "clave-app",
        "remitente": "no-responder@example.com",
        "usar_tls": True,
        "modificado_por": admin.id_usuario,
    }
    datos.update(overrides)
    return SmtpConfigService.guardar_configuracion(db_session, **datos)


def test_obtener_configuracion_sin_datos(db_session):
    admin = crear_usuario_admin(db_session)
    assert SmtpConfigService.obtener_configuracion(db_session, id_usuario=admin.id_usuario) is None


def test_obtener_configuracion_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        SmtpConfigService.obtener_configuracion(db_session)


def test_guardar_configuracion_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        SmtpConfigService.guardar_configuracion(db_session, host="smtp.example.com", puerto=587, usuario="a@b.com")


def test_guardar_crea_y_luego_actualiza_el_mismo_registro(db_session):
    admin = crear_usuario_admin(db_session)
    primero = _guardar(db_session, admin)
    segundo = _guardar(db_session, admin, host="otro.example.com", puerto=465)

    assert primero.id_config == segundo.id_config
    assert segundo.host == "otro.example.com"
    assert segundo.puerto == 465


def test_guardar_sin_password_conserva_la_guardada(db_session):
    admin = crear_usuario_admin(db_session)
    _guardar(db_session, admin, password="clave-original")

    fila = SmtpConfigService.guardar_configuracion(
        db_session,
        host="smtp.example.com",
        puerto=587,
        usuario="bot@example.com",
        modificado_por=admin.id_usuario,
    )

    assert fila.password == "clave-original"


def test_guardar_con_password_vacia_la_borra(db_session):
    admin = crear_usuario_admin(db_session)
    _guardar(db_session, admin, password="clave-original")

    fila = _guardar(db_session, admin, password="")

    assert fila.password is None


@pytest.mark.parametrize("host", ["", "   ", None])
def test_guardar_host_vacio_falla(db_session, host):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="servidor SMTP"):
        _guardar(db_session, admin, host=host)


@pytest.mark.parametrize("puerto", [0, 65536, -1, "abc", None])
def test_guardar_puerto_invalido_falla(db_session, puerto):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="puerto"):
        _guardar(db_session, admin, puerto=puerto)


def test_guardar_registra_auditoria_sin_la_clave(db_session):
    admin = crear_usuario_admin(db_session)
    _guardar(db_session, admin, password="secreta-123")

    eventos = db_session.query(Auditoria).filter_by(accion="ACTUALIZAR_CONFIGURACION_SMTP").all()
    assert len(eventos) == 1
    assert "secreta-123" not in eventos[0].detalle
    assert "tiene_password" in eventos[0].detalle


def test_efectiva_sin_fila_usa_el_env(db_session, monkeypatch):
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.env.com")
    monkeypatch.setattr(config, "SMTP_PORT", 25)
    monkeypatch.setattr(config, "SMTP_USER", "env@example.com")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "clave-env")
    monkeypatch.setattr(config, "SMTP_FROM", "")
    monkeypatch.setattr(config, "SMTP_USE_TLS", False)

    ajustes = SmtpConfigService.obtener_efectiva(db_session)

    assert ajustes == AjustesSmtp("smtp.env.com", 25, "env@example.com", "clave-env", "", False)


def test_efectiva_con_fila_completa_gana_sobre_el_env(db_session, monkeypatch):
    monkeypatch.setattr(config, "SMTP_USER", "env@example.com")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "clave-env")
    admin = crear_usuario_admin(db_session)
    _guardar(db_session, admin)

    ajustes = SmtpConfigService.obtener_efectiva(db_session)

    assert ajustes == AjustesSmtp(
        "smtp.example.com", 587, "bot@example.com", "clave-app", "no-responder@example.com", True
    )


def test_efectiva_con_fila_sin_password_cae_al_env(db_session, monkeypatch):
    monkeypatch.setattr(config, "SMTP_USER", "env@example.com")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "clave-env")
    admin = crear_usuario_admin(db_session)
    _guardar(db_session, admin, password=None)

    ajustes = SmtpConfigService.obtener_efectiva(db_session)

    assert ajustes.usuario == "env@example.com"
    assert ajustes.password == "clave-env"


# ── probar_conexion: traduccion de errores de smtplib ───────────────────────

_AJUSTES = AjustesSmtp("smtp.example.com", 587, "bot@example.com", "clave-app", "", True)


def _probar_lanzando(monkeypatch, excepcion):
    def _falla(ajustes):
        raise excepcion

    monkeypatch.setattr("app.services.smtp_config.probar_conexion", _falla)
    return SmtpConfigService.probar_conexion(_AJUSTES)


def test_probar_conexion_sin_credenciales_falla_sin_conectar(monkeypatch):
    def _no_deberia_llamarse(ajustes):
        raise AssertionError("no debe abrir conexion sin usuario/clave")

    monkeypatch.setattr("app.services.smtp_config.probar_conexion", _no_deberia_llamarse)
    with pytest.raises(ValueError, match="usuario y la contraseña"):
        SmtpConfigService.probar_conexion(AjustesSmtp("h", 587, "", "", "", True))


def test_probar_conexion_ok(monkeypatch):
    monkeypatch.setattr("app.services.smtp_config.probar_conexion", lambda ajustes: None)
    SmtpConfigService.probar_conexion(_AJUSTES)


def test_probar_conexion_auth_rechazada(monkeypatch):
    with pytest.raises(ValueError, match="rechazó el usuario o la contraseña"):
        _probar_lanzando(monkeypatch, smtplib.SMTPAuthenticationError(535, b"bad credentials"))


def test_probar_conexion_servidor_cierra(monkeypatch):
    with pytest.raises(ValueError, match="cerró la conexión"):
        _probar_lanzando(monkeypatch, smtplib.SMTPServerDisconnected("closed"))


@pytest.mark.parametrize("excepcion", [socket.gaierror("no host"), TimeoutError(), ConnectionRefusedError()])
def test_probar_conexion_sin_red(monkeypatch, excepcion):
    with pytest.raises(ValueError, match=r"No se pudo conectar a smtp\.example\.com:587"):
        _probar_lanzando(monkeypatch, excepcion)


def test_probar_conexion_otro_error_smtp_no_se_confunde_con_falta_de_red(monkeypatch):
    # SMTPException hereda de OSError: este caso protege el orden de los except.
    with pytest.raises(ValueError, match="Error del servidor de correo"):
        _probar_lanzando(monkeypatch, smtplib.SMTPException("algo raro"))


# ── Catalogo de proveedores ─────────────────────────────────────────────────


def test_catalogo_de_proveedores_es_consistente():
    claves = [p.clave for p in PROVEEDORES]
    assert len(claves) == len(set(claves))
    assert PROVEEDOR_OTRO not in claves
    for p in PROVEEDORES:
        assert p.host and 1 <= p.puerto <= 65535, p.clave
        assert p.ayuda, p.clave
    assert {"gmail", "outlook"} <= set(claves)


def test_proveedor_por_clave():
    assert proveedor_por_clave("gmail").host == "smtp.gmail.com"
    assert proveedor_por_clave("gmail").puerto == 587
    assert proveedor_por_clave(PROVEEDOR_OTRO) is None
    assert proveedor_por_clave(None) is None


def test_proveedor_de_servidor_reconoce_el_catalogo_y_cae_a_otro():
    assert proveedor_de_servidor("smtp.gmail.com", 587, True) == "gmail"
    assert proveedor_de_servidor(" SMTP.Gmail.com ", 587, True) == "gmail"
    # Mismo servidor pero con otro puerto/TLS ya es una configuracion manual.
    assert proveedor_de_servidor("smtp.gmail.com", 465, True) == PROVEEDOR_OTRO
    assert proveedor_de_servidor("smtp.gmail.com", 587, False) == PROVEEDOR_OTRO
    assert proveedor_de_servidor("mail.miempresa.com", 587, True) == PROVEEDOR_OTRO
    assert proveedor_de_servidor(None, None, None) == PROVEEDOR_OTRO
