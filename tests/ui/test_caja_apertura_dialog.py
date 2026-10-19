"""Tests de CajaAperturaDialog tras migrar saldo_input de QDoubleSpinBox a
NumericLineEdit (NumericFieldType.AMOUNT). Sigue los patrones de
tests/ui/test_numeric_inputs.py para show()+waitExposed()+waitUntil() antes de
setFocus()/blur bajo QT_QPA_PLATFORM=offscreen."""

from decimal import Decimal
from unittest.mock import MagicMock

from app.ui.caja_apertura_dialog import CajaAperturaDialog


def _dar_foco(qtbot, campo):
    # Un campo anidado dentro de un QDialog no shown() nunca resuelve el foco logico de
    # Qt bajo QT_QPA_PLATFORM=offscreen -- hay que exponer tambien la ventana top-level
    # (el dialogo), no solo el campo, antes de pedirle el foco (ver
    # tests/ui/test_proveedor_form_dialog.py, mismo gotcha).
    campo.window().show()
    qtbot.waitExposed(campo.window())
    campo.setFocus()
    qtbot.waitUntil(campo.hasFocus)


def _revelar_card_apertura(dialogo):
    # saldo_input vive en card_apertura, que arranca oculta (self.card_apertura.hide() en
    # _build_ui) hasta que _verificar_identidad() la revela tras un login exitoso -- un
    # widget oculto nunca puede tomar foco, asi que los tests que interactuan con
    # saldo_input sin pasar por el login real necesitan revelarla a mano primero.
    dialogo.card_apertura.show()


def test_saldo_input_arranca_en_cero_formateado(qtbot):
    dialogo = CajaAperturaDialog(MagicMock())
    qtbot.addWidget(dialogo)
    assert dialogo.saldo_input.text() == "$ 0,00"
    assert dialogo.saldo_input.get_value() == Decimal("0")


def test_saldo_input_formatea_al_perder_foco(qtbot):
    dialogo = CajaAperturaDialog(MagicMock())
    qtbot.addWidget(dialogo)
    _revelar_card_apertura(dialogo)
    _dar_foco(qtbot, dialogo.saldo_input)
    qtbot.keyClicks(dialogo.saldo_input, "150000,5")
    dialogo.saldo_input.clearFocus()
    assert dialogo.saldo_input.get_value() == Decimal("150000.50")
    assert dialogo.saldo_input.text() == "$ 150.000,50"


def test_abrir_pasa_el_saldo_tecleado_al_servicio(qtbot, monkeypatch):
    dialogo = CajaAperturaDialog(MagicMock())
    qtbot.addWidget(dialogo)
    _revelar_card_apertura(dialogo)

    _dar_foco(qtbot, dialogo.saldo_input)
    qtbot.keyClicks(dialogo.saldo_input, "2500,75")
    dialogo.saldo_input.clearFocus()

    dialogo.usuario_autenticado = MagicMock(id_usuario=7)
    dialogo.caja_combo.addItem("Caja 1", 1)

    llamada = {}

    def fake_abrir_caja(session, id_caja, id_usuario, saldo_apertura):
        llamada["saldo_apertura"] = saldo_apertura
        return MagicMock()

    monkeypatch.setattr("app.ui.caja_apertura_dialog.CajaService.abrir_caja", fake_abrir_caja)

    dialogo._abrir()

    assert llamada["saldo_apertura"] == Decimal("2500.75")
