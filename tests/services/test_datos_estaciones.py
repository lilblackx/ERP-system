"""datos_estaciones.txt (trae la clave SQL de la app) se borra solo a las 24 h de creado."""

import os
from datetime import datetime, timedelta

from app.services import datos_estaciones
from app.servicio_licencia import ciclo_correos


def _archivo(tmp_path, antiguedad_horas):
    ruta = tmp_path / datos_estaciones.NOMBRE_ARCHIVO
    ruta.write_text("Contrasena   : Cl4ve-Secreta\n", encoding="utf-8")
    pasado = (datetime.now() - timedelta(hours=antiguedad_horas)).timestamp()
    os.utime(ruta, (pasado, pasado))
    return ruta


def test_no_borra_antes_de_las_24_horas(tmp_path):
    ruta = _archivo(tmp_path, antiguedad_horas=23)

    assert datos_estaciones.borrar_si_vencido(ruta) is False
    assert ruta.exists()


def test_borra_pasadas_las_24_horas(tmp_path):
    ruta = _archivo(tmp_path, antiguedad_horas=25)

    assert datos_estaciones.borrar_si_vencido(ruta) is True
    assert not ruta.exists()


def test_el_limite_son_exactamente_24_horas(tmp_path):
    ruta = _archivo(tmp_path, antiguedad_horas=24)

    assert datos_estaciones.borrar_si_vencido(ruta, ahora=datetime.now() + timedelta(minutes=1)) is True
    assert not ruta.exists()


def test_sobrescribe_el_contenido_antes_de_borrar(tmp_path, monkeypatch):
    ruta = _archivo(tmp_path, antiguedad_horas=30)
    visto = {}
    borrar_original = type(ruta).unlink

    def _unlink(self, *a, **k):
        visto["contenido"] = self.read_text(encoding="utf-8")
        return borrar_original(self, *a, **k)

    monkeypatch.setattr(type(ruta), "unlink", _unlink)

    datos_estaciones.borrar_si_vencido(ruta)

    assert "Cl4ve-Secreta" not in visto["contenido"]


def test_sin_archivo_no_hace_nada_ni_falla(tmp_path):
    assert datos_estaciones.borrar_si_vencido(tmp_path / "no_existe.txt") is False


def test_un_error_al_borrar_no_tumba_al_llamador(tmp_path, monkeypatch):
    ruta = _archivo(tmp_path, antiguedad_horas=30)

    def _falla(self, *a, **k):
        raise PermissionError("en uso")

    monkeypatch.setattr(type(ruta), "unlink", _falla)

    assert datos_estaciones.borrar_si_vencido(ruta) is False  # no lanza


def test_el_servicio_del_servidor_lo_borra_en_su_ciclo(tmp_path, monkeypatch):
    ruta = _archivo(tmp_path, antiguedad_horas=48)
    monkeypatch.setattr(datos_estaciones, "ruta_por_defecto", lambda: ruta)

    ciclo_correos()

    assert not ruta.exists()


def test_una_estacion_no_toca_ese_archivo(tmp_path, monkeypatch):
    from app import config

    ruta = _archivo(tmp_path, antiguedad_horas=48)
    monkeypatch.setattr(datos_estaciones, "ruta_por_defecto", lambda: ruta)
    monkeypatch.setattr(config, "MODO_INSTALACION", "ESTACION")

    assert ciclo_correos() is None
    assert ruta.exists()


def test_la_fecha_de_borrado_anunciada_es_a_las_24_horas():
    desde = datetime(2026, 10, 23, 8, 30)

    assert datos_estaciones.fecha_de_borrado(desde) == datetime(2026, 10, 24, 8, 30)
