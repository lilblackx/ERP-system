"""Tests del ciclo del servicio de Windows (app/servicio_licencia.py). El servicio en si
(pywin32 / SCM) no se prueba aqui: solo la logica de un ciclo, que es lo que importa y no
requiere privilegios de administrador."""

import pytest

from app import config, servicio_licencia
from app.services.licencia import (
    ESTADO_ACTIVA,
    EstadoLicencia,
    LicenciaRedError,
    LicenciaService,
)


@pytest.fixture()
def como_servidor(monkeypatch):
    monkeypatch.setattr(config, "LICENCIA_URL", "https://licencias.test")
    monkeypatch.setattr(config, "LICENCIA_PUBLIC_KEY_B64", "x")
    monkeypatch.setattr(config, "MODO_INSTALACION", "SERVIDOR")


def test_ciclo_valida_y_devuelve_el_estado(como_servidor, monkeypatch):
    activa = EstadoLicencia(ESTADO_ACTIVA, "ok")
    monkeypatch.setattr(LicenciaService, "validar_en_linea", staticmethod(lambda: activa))
    assert servicio_licencia.ciclo() is activa


def test_ciclo_no_hace_nada_si_el_licenciamiento_esta_apagado(monkeypatch):
    monkeypatch.setattr(config, "LICENCIA_URL", "")
    llamado = []
    monkeypatch.setattr(LicenciaService, "validar_en_linea", staticmethod(lambda: llamado.append(1)))
    assert servicio_licencia.ciclo() is None
    assert llamado == []


def test_ciclo_no_hace_nada_en_una_estacion(como_servidor, monkeypatch):
    monkeypatch.setattr(config, "MODO_INSTALACION", "ESTACION")
    llamado = []
    monkeypatch.setattr(LicenciaService, "validar_en_linea", staticmethod(lambda: llamado.append(1)))
    assert servicio_licencia.ciclo() is None
    assert llamado == []


def test_ciclo_sin_internet_no_lanza_y_devuelve_el_estado_guardado(como_servidor, monkeypatch):
    guardado = EstadoLicencia(ESTADO_ACTIVA, "token guardado")

    def sin_red():
        raise LicenciaRedError("sin internet")

    monkeypatch.setattr(LicenciaService, "validar_en_linea", staticmethod(sin_red))
    monkeypatch.setattr(LicenciaService, "estado_actual", staticmethod(lambda ahora=None: guardado))
    assert servicio_licencia.ciclo() is guardado


def test_ciclo_ante_un_error_inesperado_no_tumba_el_servicio(como_servidor, monkeypatch):
    def roto():
        raise RuntimeError("SQL Server caido")

    monkeypatch.setattr(LicenciaService, "validar_en_linea", staticmethod(roto))
    assert servicio_licencia.ciclo() is None


def test_intervalo_minimo_de_un_minuto():
    assert servicio_licencia.INTERVALO_SEG >= 60


# -- Pedidos vencidos (app/services/pedidos.py) ----------------------------------------------------------------


class _SesionFalsa:
    cerrada = False

    def close(self):
        self.cerrada = True


@pytest.fixture()
def sesion_falsa(monkeypatch):
    from app.db import session as modulo_session

    sesion = _SesionFalsa()
    monkeypatch.setattr(modulo_session, "SessionLocal", lambda: sesion)
    return sesion


def test_ciclo_pedidos_marca_los_vencidos_y_cierra_la_sesion(como_servidor, sesion_falsa, monkeypatch):
    from app.services.pedidos import PedidoService

    recibidas = []
    monkeypatch.setattr(PedidoService, "vencer_pendientes", staticmethod(lambda s: recibidas.append(s) or 3))

    assert servicio_licencia.ciclo_pedidos() == 3
    assert recibidas == [sesion_falsa]
    assert sesion_falsa.cerrada


def test_ciclo_pedidos_no_hace_nada_en_una_estacion(como_servidor, sesion_falsa, monkeypatch):
    from app.services.pedidos import PedidoService

    monkeypatch.setattr(config, "MODO_INSTALACION", "ESTACION")
    llamado = []
    monkeypatch.setattr(PedidoService, "vencer_pendientes", staticmethod(lambda s: llamado.append(1)))

    assert servicio_licencia.ciclo_pedidos() is None
    assert llamado == []


def test_ciclo_pedidos_ante_un_error_no_tumba_el_servicio_y_cierra_la_sesion(como_servidor, sesion_falsa, monkeypatch):
    from app.services.pedidos import PedidoService

    def roto(sesion):
        raise RuntimeError("SQL Server caido")

    monkeypatch.setattr(PedidoService, "vencer_pendientes", staticmethod(roto))

    assert servicio_licencia.ciclo_pedidos() is None
    assert sesion_falsa.cerrada


def test_intervalo_de_pedidos_minimo_de_un_minuto():
    assert servicio_licencia.INTERVALO_PEDIDOS_SEG >= 60
