"""Tests de AplicarNotaCreditoDialog tras migrar monto_input de QDoubleSpinBox a
NumericLineEdit (NumericFieldType.AMOUNT). El rango es dinamico segun la nota Y la
factura seleccionadas (ver _on_seleccion_cambiada() en
app/ui/aplicar_nota_credito_dialog.py), que ahora asigna `monto_input.min_value`/
`max_value` directo en vez de QDoubleSpinBox.setRange(). No requiere Session real: las
listas de notas/facturas se pasan ya cargadas desde afuera."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.notas_credito import NotaCreditoService
from app.ui.aplicar_nota_credito_dialog import AplicarNotaCreditoDialog


def _nota(saldo="500.00"):
    return SimpleNamespace(
        numero_nota_credito="NC-001",
        saldo_disponible=Decimal(saldo),
        id_nota_credito=1,
        estado="disponible",
    )


def _factura(saldo="300.00"):
    return {"numero_factura": "F-001", "id_factura": 10, "saldo_pendiente": Decimal(saldo)}


def _dar_foco(qtbot, campo):
    # Un campo anidado dentro de un QDialog no shown() nunca resuelve el foco logico de
    # Qt bajo QT_QPA_PLATFORM=offscreen -- hay que exponer tambien la ventana top-level
    # (el dialogo), no solo el campo, antes de pedirle el foco (ver
    # tests/ui/test_proveedor_form_dialog.py, mismo gotcha).
    campo.window().show()
    qtbot.waitExposed(campo.window())
    campo.setFocus()
    qtbot.waitUntil(campo.hasFocus)


def test_monto_input_arranca_en_el_minimo_entre_nota_y_factura(qtbot):
    dialogo = AplicarNotaCreditoDialog(
        MagicMock(), id_usuario=None, notas_disponibles=[_nota("500.00")], facturas_pendientes=[_factura("300.00")]
    )
    qtbot.addWidget(dialogo)
    assert dialogo.monto_input.text() == "300,00"
    assert dialogo.monto_input.get_value() == Decimal("300.00")
    assert dialogo.btn_aplicar.isEnabled()


def test_monto_input_formatea_al_perder_foco(qtbot):
    dialogo = AplicarNotaCreditoDialog(
        MagicMock(), id_usuario=None, notas_disponibles=[_nota("500.00")], facturas_pendientes=[_factura("300.00")]
    )
    qtbot.addWidget(dialogo)
    _dar_foco(qtbot, dialogo.monto_input)
    qtbot.keyClicks(dialogo.monto_input, "150,25")
    dialogo.monto_input.clearFocus()
    assert dialogo.monto_input.get_value() == Decimal("150.25")
    assert dialogo.monto_input.text() == "150,25"


def test_confirmar_pasa_el_monto_tecleado_al_servicio(qtbot, monkeypatch):
    dialogo = AplicarNotaCreditoDialog(
        MagicMock(), id_usuario=None, notas_disponibles=[_nota("500.00")], facturas_pendientes=[_factura("300.00")]
    )
    qtbot.addWidget(dialogo)

    _dar_foco(qtbot, dialogo.monto_input)
    qtbot.keyClicks(dialogo.monto_input, "200")
    dialogo.monto_input.clearFocus()

    llamada = {}

    def fake_aplicar(session, **kwargs):
        llamada.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(NotaCreditoService, "aplicar_nota_credito_cliente", staticmethod(fake_aplicar))

    dialogo._confirmar()

    assert llamada["monto"] == Decimal("200.00")
