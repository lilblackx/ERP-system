"""La impresora es por estacion (QSettings), no parte de la configuracion compartida de la BD."""

from types import SimpleNamespace

from app.utils import impresora_local
from app.utils.impresora_local import guardar_impresora_local, obtener_impresora_local


def _instaladas(monkeypatch, nombres):
    monkeypatch.setattr(
        impresora_local.QPrinterInfo,
        "availablePrinters",
        staticmethod(lambda: [SimpleNamespace(printerName=lambda n=n: n) for n in nombres]),
    )


def test_sin_nada_guardado_no_hay_impresora(monkeypatch):
    _instaladas(monkeypatch, ["HP"])
    assert obtener_impresora_local(None) is None


def test_guardar_y_leer_ida_y_vuelta(monkeypatch):
    _instaladas(monkeypatch, ["HP"])
    guardar_impresora_local("HP")
    assert obtener_impresora_local(None) == "HP"


def test_valor_heredado_de_la_bd_se_usa_si_esta_instalado_en_este_equipo(monkeypatch):
    _instaladas(monkeypatch, ["HP"])
    assert obtener_impresora_local(SimpleNamespace(impresora_predeterminada="HP")) == "HP"


def test_valor_heredado_de_la_bd_se_ignora_si_no_existe_en_este_equipo(monkeypatch):
    _instaladas(monkeypatch, ["Epson"])
    assert obtener_impresora_local(SimpleNamespace(impresora_predeterminada="HP")) is None


def test_la_eleccion_local_manda_sobre_el_valor_heredado(monkeypatch):
    _instaladas(monkeypatch, ["HP", "Epson"])
    guardar_impresora_local("Epson")
    assert obtener_impresora_local(SimpleNamespace(impresora_predeterminada="HP")) == "Epson"


def test_ninguna_elegida_a_proposito_no_cae_al_valor_heredado(monkeypatch):
    _instaladas(monkeypatch, ["HP"])
    guardar_impresora_local(None)
    assert obtener_impresora_local(SimpleNamespace(impresora_predeterminada="HP")) is None
