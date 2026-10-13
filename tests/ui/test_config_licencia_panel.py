"""Logica de presentacion de la pestana Licencia (app/ui/config_licencia_panel.py): como se
describe el vencimiento y cuando se muestra un aviso. Las fechas se pasan explicitas (`hoy`)."""

from datetime import date, datetime

from app.services.licencia import EstadoLicencia
from app.ui.config_licencia_panel import (
    NIVEL_ADVERTENCIA,
    NIVEL_OK,
    NIVEL_PELIGRO,
    describir_vencimiento,
    texto_aviso,
)

HOY = date(2026, 10, 9)


def test_sin_vencimiento():
    assert describir_vencimiento(None, HOY) == ("Sin vencimiento", NIVEL_OK)


def test_vence_manana_es_advertencia():
    assert describir_vencimiento(datetime(2026, 10, 10), HOY) == ("Vence mañana", NIVEL_ADVERTENCIA)


def test_vence_hoy_es_peligro():
    assert describir_vencimiento(datetime(2026, 10, 9, 23, 0), HOY) == ("Vence hoy", NIVEL_PELIGRO)


def test_dentro_del_umbral_de_aviso_es_advertencia_y_fuera_es_ok():
    assert describir_vencimiento(date(2026, 10, 24), HOY) == ("Vence en 15 días", NIVEL_ADVERTENCIA)
    assert describir_vencimiento(date(2026, 10, 25), HOY) == ("Faltan 16 días", NIVEL_OK)


def test_vencida_hace_dias_es_peligro():
    assert describir_vencimiento(date(2026, 10, 8), HOY) == ("Vencida hace 1 día", NIVEL_PELIGRO)
    assert describir_vencimiento(date(2026, 10, 1), HOY) == ("Vencida hace 8 días", NIVEL_PELIGRO)


def _activa(expira, mensaje="Licencia activa."):
    return EstadoLicencia("ACTIVA", mensaje, "estandar", "Cliente", expira, None, 1)


def test_licencia_activa_y_lejos_no_muestra_aviso_aunque_el_servicio_diga_licencia_activa():
    assert texto_aviso(_activa(datetime(2027, 1, 1)), HOY) == ("", NIVEL_OK)
    assert texto_aviso(_activa(None), HOY) == ("", NIVEL_OK)


def test_licencia_activa_con_un_mensaje_distinto_lo_conserva():
    texto, nivel = texto_aviso(_activa(datetime(2027, 1, 1), "Validación en línea pendiente."), HOY)
    assert texto == "Validación en línea pendiente."
    assert nivel == NIVEL_OK


def test_licencia_activa_por_vencer_avisa_con_la_fecha():
    texto, nivel = texto_aviso(_activa(datetime(2026, 10, 10)), HOY)
    assert texto.startswith("Vence mañana.")
    assert nivel == NIVEL_ADVERTENCIA


def test_licencia_no_activa_muestra_el_mensaje_del_servicio_en_su_nivel():
    vencida = EstadoLicencia("VENCIDA", "La licencia venció el 01/10/2026.", "estandar", "Cliente", None, None, 1)
    assert texto_aviso(vencida, HOY) == ("La licencia venció el 01/10/2026.", NIVEL_PELIGRO)

    sin = EstadoLicencia("SIN_LICENCIA", "", None, None, None, None, None)
    assert texto_aviso(sin, HOY) == ("Sin licencia", NIVEL_ADVERTENCIA)
