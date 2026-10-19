"""Tests de ProveedorFormDialog tras migrar limite_credito_input/dias_credito_input de
QDoubleSpinBox/QSpinBox a NumericLineEdit -- mismo patron que ClienteFormDialog
(app/ui/cliente_form_dialog.py), sin mapa ni combos de vendedor/categoria (Proveedor no
los tiene). No requiere DB real: la Session se mockea, _build_ui() de este dialogo no
hace ninguna consulta contra ella."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.ui.proveedor_form_dialog import ProveedorFormDialog


def _dar_foco(qtbot, campo):
    # A diferencia de un NumericLineEdit suelto (tests/ui/test_numeric_inputs.py), un
    # campo anidado dentro de un QDialog no shown() nunca resuelve el foco logico de Qt
    # bajo QT_QPA_PLATFORM=offscreen -- hay que exponer tambien la ventana top-level
    # (el dialogo), no solo el campo, antes de pedirle el foco.
    campo.window().show()
    qtbot.waitExposed(campo.window())
    campo.setFocus()
    qtbot.waitUntil(campo.hasFocus)


def _escribir_y_perder_foco(qtbot, campo, texto):
    _dar_foco(qtbot, campo)
    qtbot.keyClicks(campo, texto)
    campo.clearFocus()


def test_campos_arrancan_en_default(qtbot):
    dialogo = ProveedorFormDialog(MagicMock())
    qtbot.addWidget(dialogo)
    assert dialogo.limite_credito_input.text() == "$ 0,00"
    assert dialogo.limite_credito_input.get_value() == Decimal("0")
    assert dialogo.dias_credito_input.text() == "0 días"
    assert dialogo.dias_credito_input.get_value() == Decimal("0")


def test_limite_credito_formatea_miles_al_perder_foco(qtbot):
    dialogo = ProveedorFormDialog(MagicMock())
    qtbot.addWidget(dialogo)
    _escribir_y_perder_foco(qtbot, dialogo.limite_credito_input, "1500000,25")
    assert dialogo.limite_credito_input.get_value() == Decimal("1500000.25")
    assert dialogo.limite_credito_input.text() == "$ 1.500.000,25"


def test_dias_credito_se_ajusta_al_maximo_de_365(qtbot):
    dialogo = ProveedorFormDialog(MagicMock())
    qtbot.addWidget(dialogo)
    _escribir_y_perder_foco(qtbot, dialogo.dias_credito_input, "400")
    assert dialogo.dias_credito_input.get_value() == Decimal("365")
    assert dialogo.dias_credito_input.toolTip() != ""


def test_precargar_setea_valores_desde_proveedor(qtbot):
    dialogo = ProveedorFormDialog(MagicMock())
    qtbot.addWidget(dialogo)
    proveedor = SimpleNamespace(
        codigo_proveedor="PROV-001",
        id_legal="J",
        identificacion_proveedor="12345678",
        nombre_razon_social="Suministros SA",
        telefono=None,
        email=None,
        direccion=None,
        limite_credito=Decimal("2500.50"),
        dias_credito=45,
    )
    dialogo._precargar(proveedor)
    assert dialogo.limite_credito_input.get_value() == Decimal("2500.50")
    assert dialogo.dias_credito_input.get_value() == Decimal("45")


def test_get_data_devuelve_decimal_y_entero(qtbot):
    dialogo = ProveedorFormDialog(MagicMock())
    qtbot.addWidget(dialogo)
    dialogo.codigo_input.setText("PROV-002")
    dialogo.identificacion_input.setText("87654321")
    dialogo.nombre_input.setText("Otro Proveedor")
    _escribir_y_perder_foco(qtbot, dialogo.limite_credito_input, "999,99")
    _escribir_y_perder_foco(qtbot, dialogo.dias_credito_input, "30")

    datos = dialogo.get_data()

    assert datos["limite_credito"] == Decimal("999.99")
    assert datos["dias_credito"] == 30
    assert isinstance(datos["dias_credito"], int)
