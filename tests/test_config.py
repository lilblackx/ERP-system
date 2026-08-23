import pytest

from app import config


def test_validar_configuracion_falla_sin_db_password(monkeypatch):
    """C23: sin esto, DB_PASSWORD vacio solo se nota mas tarde con un error crudo de
    pyodbc en el primer intento de conexion."""
    monkeypatch.setattr(config, "DB_PASSWORD", "")
    monkeypatch.setattr(config, "DB_TRUSTED_CONNECTION", "no")

    with pytest.raises(RuntimeError, match="DB_PASSWORD"):
        config.validar_configuracion()


def test_validar_configuracion_ok_con_db_password(monkeypatch):
    monkeypatch.setattr(config, "DB_PASSWORD", "algo")
    monkeypatch.setattr(config, "DB_TRUSTED_CONNECTION", "no")

    config.validar_configuracion()  # no debe lanzar


def test_validar_configuracion_ok_sin_password_si_es_trusted_connection(monkeypatch):
    monkeypatch.setattr(config, "DB_PASSWORD", "")
    monkeypatch.setattr(config, "DB_TRUSTED_CONNECTION", "yes")

    config.validar_configuracion()  # Trusted_Connection no usa PWD, no deberia exigirla
