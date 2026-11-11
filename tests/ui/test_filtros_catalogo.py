"""Combo de vendedores de los paneles de Cuentas por Cobrar (normal y BCV): se llena en un hilo aparte, no con una
consulta en el hilo de la ventana al abrirse."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QComboBox

import app.ui.carga_asincrona as ca
import app.ui.cuentas_por_cobrar_bcv_panel as bcv
import app.ui.cuentas_por_cobrar_panel as cxc
from app.ui.filtros_catalogo import llenar_combo_vendedores, tarea_vendedores_para_filtro


def test_la_tarea_devuelve_tuplas_simples_ordenadas_por_nombre():
    sesion = MagicMock()
    sesion.query.return_value.order_by.return_value.all.return_value = [(2, "Ana"), (5, "Beto")]

    assert tarea_vendedores_para_filtro(sesion) == [(2, "Ana"), (5, "Beto")]


def test_llenar_el_combo_pone_todos_primero_sin_emitir_senales(qtbot):
    combo = QComboBox()
    qtbot.addWidget(combo)
    cambios = []
    combo.currentIndexChanged.connect(cambios.append)

    llenar_combo_vendedores(combo, [(2, "Ana"), (5, "Beto")])

    assert [combo.itemText(i) for i in range(combo.count())] == ["Todos los vendedores", "Ana", "Beto"]
    assert combo.currentData() is None and combo.itemData(2) == 5
    assert cambios == []  # no es un cambio del usuario: no debe repetir la busqueda


def test_llenar_el_combo_conserva_lo_que_el_usuario_ya_habia_elegido(qtbot):
    combo = QComboBox()
    qtbot.addWidget(combo)
    llenar_combo_vendedores(combo, [(2, "Ana"), (5, "Beto")])
    combo.setCurrentIndex(combo.findData(5))  # eligio antes de que llegara la lista nueva

    llenar_combo_vendedores(combo, [(1, "Zoe"), (2, "Ana"), (5, "Beto")])

    assert combo.currentData() == 5 and combo.currentText() == "Beto"


class _WorkerFalso:
    creados: list = []

    def __init__(self, session_factory, tarea, *args, **kwargs):
        self.tarea = tarea
        self.silencioso = False
        self.resultado, self.finished = MagicMock(), MagicMock()
        _WorkerFalso.creados.append(self)

    def start(self):
        self.iniciado = True

    def isFinished(self):
        return True

    def wait(self, _ms):
        return True


@pytest.mark.parametrize("modulo, clase", [(cxc, "CuentasPorCobrarPanel"), (bcv, "CuentasPorCobrarBCVPanel")])
def test_el_panel_pide_los_vendedores_en_un_hilo_y_no_consulta_al_abrirse(qtbot, monkeypatch, modulo, clase):
    _WorkerFalso.creados = []
    monkeypatch.setattr(ca, "QueryWorker", _WorkerFalso)
    monkeypatch.setattr(getattr(modulo, clase), "cargar_cuentas", lambda self, *a, **k: None)
    sesiones = MagicMock()  # si el panel consultara en el hilo de la ventana, quedaria registrado aqui

    panel = getattr(modulo, clase)(sesiones, SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)

    sesiones.assert_not_called()  # session_factory ni se invoco: no hubo consulta sincronica
    pedido = _WorkerFalso.creados[-1]
    assert pedido.tarea is ca._tarea_carga and pedido.iniciado and pedido.silencioso is True


@pytest.mark.parametrize("modulo, clase", [(cxc, "CuentasPorCobrarPanel"), (bcv, "CuentasPorCobrarBCVPanel")])
def test_al_llegar_la_lista_el_panel_llena_el_combo(qtbot, monkeypatch, modulo, clase):
    monkeypatch.setattr(getattr(modulo, clase), "cargar_cuentas", lambda self, *a, **k: None)
    panel = getattr(modulo, clase)(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)

    panel._llenar_vendedores([(2, "Ana"), (5, "Beto")])

    assert panel.vendedor_combo.count() == 3 and panel.vendedor_combo.itemData(1) == 2
