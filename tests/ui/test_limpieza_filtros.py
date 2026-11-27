"""Al salir de un modulo, MainWindow deja sus filtros como estaban al abrirlo (no en un valor fijo).

Se llama a `_limpiar_panel_actual` sin instanciar la ventana (necesita base de datos y arma todos los paneles)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QCheckBox, QDateEdit, QLineEdit, QSpinBox, QVBoxLayout, QWidget

import app.ui.reportes_panel as rp
from app.ui.filtros_iniciales import recordar_filtros_iniciales
from app.ui.main_window import MainWindow


def _salir_del_modulo(panel):
    ventana = SimpleNamespace(stack=SimpleNamespace(currentWidget=lambda: panel))
    MainWindow._limpiar_panel_actual(ventana)


def _fecha(dias_atras: int) -> QDateEdit:
    campo = QDateEdit()
    campo.setDisplayFormat("dd/MM/yyyy")
    campo.setDate(QDate.currentDate().addDays(-dias_atras))
    return campo


@pytest.fixture()
def panel_con_filtros(qtbot):
    panel = QWidget()
    qtbot.addWidget(panel)
    layout = QVBoxLayout(panel)
    panel.buscar = QLineEdit()
    panel.desde = _fecha(30)
    panel.hasta = _fecha(0)
    panel.dias = QSpinBox()
    panel.dias.setValue(15)
    panel.marcado = QCheckBox()
    panel.marcado.setChecked(True)
    for widget in (panel.buscar, panel.desde, panel.hasta, panel.dias, panel.marcado):
        layout.addWidget(widget)
    recordar_filtros_iniciales(panel)
    return panel


def test_las_fechas_vuelven_a_su_valor_inicial_y_no_a_hoy(panel_con_filtros):
    panel = panel_con_filtros
    panel.desde.setDate(QDate.currentDate().addDays(-200))
    panel.hasta.setDate(QDate.currentDate().addDays(-100))

    _salir_del_modulo(panel)

    assert panel.desde.date() == QDate.currentDate().addDays(-30)
    assert panel.hasta.date() == QDate.currentDate()


def test_busqueda_y_checks_quedan_como_al_abrir_sin_vaciar_campos_numericos_ni_fechas(panel_con_filtros):
    panel = panel_con_filtros
    panel.buscar.setText("algo")
    panel.marcado.setChecked(False)
    texto_hasta = panel.hasta.text()

    _salir_del_modulo(panel)

    assert panel.buscar.text() == ""
    assert panel.marcado.isChecked()
    # QDateEdit y QSpinBox tienen un QLineEdit interno: vaciarlo los dejaba en blanco.
    assert panel.dias.text() == "15"
    assert panel.hasta.text() == texto_hasta


def test_una_pagina_de_reportes_creada_despues_del_panel_conserva_sus_valores_iniciales(qtbot, monkeypatch):
    monkeypatch.setattr(rp.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(rp.ReportesPanel, "_generar", lambda self: None)
    panel = rp.ReportesPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    recordar_filtros_iniciales(panel)
    panel._asegurar_pagina("ventas_periodo")
    desde = panel.fecha_desde_vp_input
    desde.setDate(QDate.currentDate().addDays(-200))

    _salir_del_modulo(panel)

    assert desde.date() == QDate.currentDate().addDays(-30)
