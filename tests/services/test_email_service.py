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
