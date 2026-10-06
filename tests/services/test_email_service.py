"""Pruebas de email_service.enviar_correo. No requieren db_session -- son unitarias,
sin tocar SQL Server. El envio real se monkeypatchea (smtplib.SMTP) para no golpear un
servidor SMTP real, igual que se hace en tests/services/test_recuperacion_acceso.py al
monkeypatchear enviar_correo() completa; aca se prueba la funcion en si.
"""

import pytest

from app import config
from app.services import email_service


def test_enviar_correo_sin_smtp_user_ni_password_lanza(monkeypatch):
    monkeypatch.setattr(config, "SMTP_USER", "")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "")

    with pytest.raises(RuntimeError, match="SMTP no esta configurado"):
        email_service.enviar_correo("destino@example.com", "Asunto", "Cuerpo")


def test_enviar_correo_sin_smtp_password_lanza(monkeypatch):
    monkeypatch.setattr(config, "SMTP_USER", "bot@example.com")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "")

    with pytest.raises(RuntimeError, match="SMTP no esta configurado"):
        email_service.enviar_correo("destino@example.com", "Asunto", "Cuerpo")


def test_enviar_correo_sin_smtp_user_lanza(monkeypatch):
    monkeypatch.setattr(config, "SMTP_USER", "")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "clave-app")

    with pytest.raises(RuntimeError, match="SMTP no esta configurado"):
        email_service.enviar_correo("destino@example.com", "Asunto", "Cuerpo")


class _FakeSMTP:
    """Reemplaza smtplib.SMTP: registra las llamadas en vez de abrir un socket real."""

    instancias = []

    def __init__(self, host, port, timeout=10):
        self.host = host
        self.port = port
        self.iniciado_tls = False
        self.login_args = None
        self.mensaje_enviado = None
        _FakeSMTP.instancias.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self):
        self.iniciado_tls = True

    def login(self, usuario, clave):
        self.login_args = (usuario, clave)

    def send_message(self, msg):
        self.mensaje_enviado = msg


def test_enviar_correo_configurado_envia_via_smtp(monkeypatch):
    _FakeSMTP.instancias = []
    monkeypatch.setattr(config, "SMTP_USER", "bot@example.com")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "clave-app")
    monkeypatch.setattr(config, "SMTP_FROM", "no-responder@example.com")
    monkeypatch.setattr(config, "SMTP_USE_TLS", True)
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTP)

    email_service.enviar_correo("destino@example.com", "Asunto de prueba", "Cuerpo de prueba")

    assert len(_FakeSMTP.instancias) == 1
    servidor = _FakeSMTP.instancias[0]
    assert servidor.iniciado_tls is True
    assert servidor.login_args == ("bot@example.com", "clave-app")
    assert servidor.mensaje_enviado["To"] == "destino@example.com"
    assert servidor.mensaje_enviado["From"] == "no-responder@example.com"
    assert servidor.mensaje_enviado["Subject"] == "Asunto de prueba"


def test_enviar_correo_sin_smtp_from_usa_smtp_user(monkeypatch):
    _FakeSMTP.instancias = []
    monkeypatch.setattr(config, "SMTP_USER", "bot@example.com")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "clave-app")
    monkeypatch.setattr(config, "SMTP_FROM", "")
    monkeypatch.setattr(config, "SMTP_USE_TLS", False)
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTP)

    email_service.enviar_correo("destino@example.com", "Asunto", "Cuerpo")

    servidor = _FakeSMTP.instancias[0]
    assert servidor.iniciado_tls is False
    assert servidor.mensaje_enviado["From"] == "bot@example.com"


def test_enviar_correo_sin_cuerpo_html_es_texto_plano_simple(monkeypatch):
    """Sin cuerpo_html (comportamiento de siempre, cualquier caller que no lo pase), el
    mensaje sigue siendo un unico part de texto plano -- no se vuelve multipart porque no
    hay ninguna alternativa que ofrecer."""
    _FakeSMTP.instancias = []
    monkeypatch.setattr(config, "SMTP_USER", "bot@example.com")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "clave-app")
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTP)

    email_service.enviar_correo("destino@example.com", "Asunto", "Cuerpo")

    mensaje = _FakeSMTP.instancias[0].mensaje_enviado
    assert not mensaje.is_multipart()
    assert mensaje.get_content().strip() == "Cuerpo"


def test_enviar_correo_con_cuerpo_html_arma_multipart_alternative(monkeypatch):
    """Con cuerpo_html, el mensaje debe traer AMBAS versiones (RFC 2046 multipart/
    alternative) -- el texto plano como fallback y el HTML como la version 'linda' que la
    mayoria de los clientes de correo van a preferir mostrar."""
    _FakeSMTP.instancias = []
    monkeypatch.setattr(config, "SMTP_USER", "bot@example.com")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "clave-app")
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTP)

    email_service.enviar_correo(
        "destino@example.com",
        "Asunto",
        "Cuerpo plano",
        cuerpo_html="<html><body>Cuerpo HTML</body></html>",
    )

    mensaje = _FakeSMTP.instancias[0].mensaje_enviado
    assert mensaje.is_multipart()
    assert mensaje.get_content_type() == "multipart/alternative"
    partes = list(mensaje.iter_parts())
    assert any(p.get_content_type() == "text/plain" and "Cuerpo plano" in p.get_content() for p in partes)
    assert any(p.get_content_type() == "text/html" and "Cuerpo HTML" in p.get_content() for p in partes)


class _FakeSMTPSSL(_FakeSMTP):
    """Como _FakeSMTP, pero no debe llamar a starttls(): SMTP_SSL ya viene cifrado."""

    def starttls(self):
        raise AssertionError("SMTP_SSL no debe hacer STARTTLS")


def test_enviar_correo_con_ajustes_explicitos_ignora_el_env(monkeypatch):
    _FakeSMTP.instancias = []
    monkeypatch.setattr(config, "SMTP_USER", "env@example.com")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "clave-env")
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTP)
    ajustes = email_service.AjustesSmtp("smtp.db.com", 2525, "db@example.com", "clave-db", "yo@db.com", True)

    email_service.enviar_correo("destino@example.com", "Asunto", "Cuerpo", ajustes=ajustes)

    servidor = _FakeSMTP.instancias[0]
    assert (servidor.host, servidor.port) == ("smtp.db.com", 2525)
    assert servidor.login_args == ("db@example.com", "clave-db")
    assert servidor.mensaje_enviado["From"] == "yo@db.com"


def test_enviar_correo_ajustes_sin_credenciales_lanza():
    ajustes = email_service.AjustesSmtp("smtp.db.com", 587, "", "", "", True)
    with pytest.raises(RuntimeError, match="SMTP no esta configurado"):
        email_service.enviar_correo("destino@example.com", "Asunto", "Cuerpo", ajustes=ajustes)


def test_enviar_correo_puerto_465_usa_ssl_directo_sin_starttls(monkeypatch):
    _FakeSMTP.instancias = []
    monkeypatch.setattr(email_service.smtplib, "SMTP_SSL", _FakeSMTPSSL)
    ajustes = email_service.AjustesSmtp("smtp.db.com", 465, "db@example.com", "clave-db", "", True)

    email_service.enviar_correo("destino@example.com", "Asunto", "Cuerpo", ajustes=ajustes)

    servidor = _FakeSMTP.instancias[0]
    assert servidor.port == 465
    assert servidor.login_args == ("db@example.com", "clave-db")
    assert servidor.mensaje_enviado is not None


def test_probar_conexion_autentica_sin_enviar(monkeypatch):
    _FakeSMTP.instancias = []
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTP)
    ajustes = email_service.AjustesSmtp("smtp.db.com", 587, "db@example.com", "clave-db", "", True)

    email_service.probar_conexion(ajustes)

    servidor = _FakeSMTP.instancias[0]
    assert servidor.iniciado_tls is True
    assert servidor.login_args == ("db@example.com", "clave-db")
    assert servidor.mensaje_enviado is None


class _FakeSMTPCierraAlAutenticar(_FakeSMTP):
    """Como Gmail ante una clave mala: corta la conexion en vez de contestar 535."""

    def login(self, usuario, clave):
        raise email_service.smtplib.SMTPServerDisconnected("Connection unexpectedly closed")


def test_desconexion_durante_el_login_se_reporta_como_credenciales_rechazadas(monkeypatch):
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTPCierraAlAutenticar)
    ajustes = email_service.AjustesSmtp("smtp.gmail.com", 587, "db@example.com", "mala", "", True)

    with pytest.raises(email_service.smtplib.SMTPAuthenticationError):
        email_service.probar_conexion(ajustes)
