"""Boton "..." de las filas de cuentas por cobrar: abre el detalle de la factura (VerFacturaDesdeFilaMixin)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QDialog, QPushButton

import app.ui.factura_detalle_dialog as fd
from app.services.permisos import PermisoDenegadoError


class _Dialogo(fd.VerFacturaDesdeFilaMixin, QDialog):
    def __init__(self):
        super().__init__()
        self.session_factory = MagicMock(name="session_factory")
        self.id_usuario = 9


@pytest.fixture()
def dialogo(qtbot):
    d = _Dialogo()
    qtbot.addWidget(d)
    return d


def _capturar_cargas(dialogo):
    llamadas = []
    dialogo.cargar_async = lambda *a, **k: llamadas.append((a, k))
    return llamadas


def test_el_boton_de_la_fila_pide_la_factura_de_su_cuenta(dialogo, qtbot):
    llamadas = _capturar_cargas(dialogo)
    contenedor = dialogo._boton_ver_factura(SimpleNamespace(id_factura=7))
    qtbot.addWidget(contenedor)
    boton = contenedor.findChild(QPushButton)

    assert boton.toolTip() == "Ver detalle de la factura"
    boton.click()

    ((args, filtros),) = llamadas
    assert args[0] == "detalle_factura" and args[1] is fd.tarea_cargar_factura
    assert filtros["id_factura"] == 7 and filtros["id_usuario"] == 9
    assert filtros["session_factory"] is dialogo.session_factory


def test_toma_el_id_de_la_factura_de_la_relacion_si_la_cuenta_no_lo_trae(dialogo):
    llamadas = _capturar_cargas(dialogo)

    dialogo._ver_detalle_factura_cuenta(SimpleNamespace(factura=SimpleNamespace(id_factura=12)))

    assert llamadas[0][1]["id_factura"] == 12


def test_una_cuenta_sin_factura_no_consulta_nada(dialogo):
    llamadas = _capturar_cargas(dialogo)

    dialogo._ver_detalle_factura_cuenta(SimpleNamespace())

    assert llamadas == []


@pytest.mark.parametrize(
    ("error", "metodo", "titulo"),
    [
        (PermisoDenegadoError("x"), "warning", "Sin permiso"),
        (ValueError("La factura no existe"), "warning", "No se pudo abrir la factura"),
        (RuntimeError("boom"), "critical", "Error"),
    ],
)
def test_si_la_carga_falla_avisa_segun_el_error_y_cierra_la_sesion(dialogo, monkeypatch, error, metodo, titulo):
    mensajes = []
    for nombre in ("warning", "critical"):
        monkeypatch.setattr(fd.MessageBox, nombre, staticmethod(lambda *a, _n=nombre, **k: mensajes.append((_n, a[1]))))
    monkeypatch.setattr(fd, "FacturaDetalleDialog", MagicMock(side_effect=AssertionError("no debe abrirse")))
    sesion = MagicMock()

    dialogo._abrir_detalle_factura({"session": sesion, "error": error})

    assert mensajes == [(metodo, titulo)]
    sesion.close.assert_called_once()


def test_al_llegar_la_factura_abre_su_detalle_y_cierra_la_sesion_al_salir(dialogo, monkeypatch):
    abiertos = []

    class _Detalle:
        def __init__(self, datos, session, id_usuario, parent=None):
            abiertos.append((datos, session, id_usuario, parent))

        def exec(self):
            return 0

    monkeypatch.setattr(fd, "FacturaDetalleDialog", _Detalle)
    sesion = MagicMock()

    dialogo._abrir_detalle_factura({"session": sesion, "datos": {"factura": 1}})

    assert abiertos == [({"factura": 1}, sesion, 9, dialogo)]
    sesion.close.assert_called_once()


def test_si_el_dialogo_de_detalle_revienta_avisa_y_cierra_la_sesion(dialogo, monkeypatch):
    avisos = []
    monkeypatch.setattr(fd.MessageBox, "critical", staticmethod(lambda *a, **k: avisos.append(a[1])))
    monkeypatch.setattr(fd, "FacturaDetalleDialog", MagicMock(side_effect=RuntimeError("boom")))
    sesion = MagicMock()

    dialogo._abrir_detalle_factura({"session": sesion, "datos": {}})

    assert avisos == ["Error"]
    sesion.close.assert_called_once()
