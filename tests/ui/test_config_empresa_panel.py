"""Tests de ConfigEmpresaPanel tras migrar iva_porcentaje_input de QDoubleSpinBox a
NumericLineEdit (NumericFieldType.PERCENTAGE, suffix=" %"). Caso particular de este
campo: su default real es 16.00 (no 0, el default generico de NumericLineEdit) -- se
preserva con un set_value(Decimal("16.00")) explicito justo despues de construirlo, y
cargar_datos() lo pisa con el valor de la BD si existe una fila de configuracion.

EmpresaService.obtener_configuracion()/guardar_configuracion() se monkeypatchean
directo en vez de armar la cadena require_permiso()/session.query(...).first() con un
Session mockeado: son metodos estaticos con gate de permiso propio (require_permiso
exige id_usuario autenticado contra la BD), y lo que este archivo necesita cubrir es el
mapeo de datos NumericLineEdit <-> Decimal en cargar_datos()/guardar_cambios(), no la
logica de autorizacion de EmpresaService (ya cubierta en tests/services)."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.ui.config_empresa_panel import ConfigEmpresaPanel


def _dar_foco(qtbot, campo):
    campo.window().show()
    qtbot.waitExposed(campo.window())
    campo.setFocus()
    qtbot.waitUntil(campo.hasFocus)


def _escribir_y_perder_foco(qtbot, campo, texto):
    _dar_foco(qtbot, campo)
    campo.selectAll()
    qtbot.keyClicks(campo, texto)
    campo.clearFocus()


def _crear_panel(qtbot, monkeypatch, config=None):
    monkeypatch.setattr(
        "app.ui.config_empresa_panel.EmpresaService.obtener_configuracion",
        lambda session, id_usuario=None: config,
    )
    panel = ConfigEmpresaPanel(MagicMock(return_value=MagicMock()), MagicMock(id_usuario=1))
    qtbot.addWidget(panel)
    return panel


def test_iva_porcentaje_arranca_en_16_por_defecto(qtbot, monkeypatch):
    # Sin fila de configuracion en la "BD" (None): cargar_datos() no encuentra nada que
    # sobreescriba el 16.00 puesto justo tras construir el campo.
    panel = _crear_panel(qtbot, monkeypatch, config=None)
    assert panel.iva_porcentaje_input.get_value() == Decimal("16.00")
    assert panel.iva_porcentaje_input.text() == "16,00 %"


def test_cargar_datos_pisa_el_default_con_el_valor_guardado(qtbot, monkeypatch):
    config = SimpleNamespace(
        rif_empresa=None,
        razon_social_empresa=None,
        direccion_empresa=None,
        telefono_empresa=None,
        pie_pagina_empresa=None,
        iva_activo=True,
        iva_porcentaje=Decimal("8.00"),
        impresora_predeterminada=None,
        logotipo_empresa=None,
    )
    panel = _crear_panel(qtbot, monkeypatch, config=config)
    assert panel.iva_porcentaje_input.get_value() == Decimal("8.00")
    assert panel.iva_porcentaje_input.text() == "8,00 %"


def test_editar_y_guardar_pasa_decimal_al_servicio(qtbot, monkeypatch):
    panel = _crear_panel(qtbot, monkeypatch, config=None)
    panel.iva_activo_check.setChecked(True)  # el campo arranca deshabilitado (IVA inactivo)
    _escribir_y_perder_foco(qtbot, panel.iva_porcentaje_input, "12,5")
    assert panel.iva_porcentaje_input.get_value() == Decimal("12.50")

    llamada = {}

    def fake_guardar(**kwargs):
        llamada.update(kwargs)

    monkeypatch.setattr("app.ui.config_empresa_panel.EmpresaService.guardar_configuracion", fake_guardar)
    # guardar_cambios() exitoso muestra un MessageBox.information() modal (QDialog.exec())
    # -- sin mockearlo el test queda colgado esperando que alguien lo cierre a mano.
    monkeypatch.setattr("app.ui.config_empresa_panel.MessageBox.information", lambda *a, **k: None)

    panel.guardar_cambios()

    assert llamada["iva_porcentaje"] == Decimal("12.50")
    assert isinstance(llamada["iva_porcentaje"], Decimal)


def test_porcentaje_se_ajusta_a_100_si_excede(qtbot, monkeypatch):
    panel = _crear_panel(qtbot, monkeypatch, config=None)
    panel.iva_activo_check.setChecked(True)
    _escribir_y_perder_foco(qtbot, panel.iva_porcentaje_input, "150")
    assert panel.iva_porcentaje_input.get_value() == Decimal("100")
