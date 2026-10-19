"""Tests de VendedorFormDialog tras migrar meta_activacion_input de QSpinBox a
NumericLineEdit (NumericFieldType.COUNT, max_value=999). El QSpinBox original usaba
setSpecialValueText("Sin meta") para mostrar un texto en vez de "0" -- NumericLineEdit no
tiene un equivalente, asi que se reemplazo por un tooltip fijo ("0 = sin meta de
activacion"); el 0 en si sigue siendo el valor que get_data() traduce a None (mismo
`... or None` que ya existia).

No requiere DB real: RutaService.listar() exige un id_usuario autenticado
(require_permiso) y el dialogo lo llama con id_usuario=None por defecto en estos tests,
asi que siempre cae al branch PermisoDenegadoError -> combo de rutas vacio, sin necesitar
mockear la cadena session.query(...)."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.ui.vendedor_form_dialog import VendedorFormDialog


def _dar_foco(qtbot, campo):
    campo.window().show()
    qtbot.waitExposed(campo.window())
    campo.setFocus()
    qtbot.waitUntil(campo.hasFocus)


def _escribir_y_perder_foco(qtbot, campo, texto):
    _dar_foco(qtbot, campo)
    qtbot.keyClicks(campo, texto)
    campo.clearFocus()


def test_meta_activacion_arranca_en_cero(qtbot):
    dialogo = VendedorFormDialog(MagicMock())
    qtbot.addWidget(dialogo)
    assert dialogo.meta_activacion_input.text() == "0"
    assert dialogo.meta_activacion_input.get_value() == Decimal("0")
    assert dialogo.meta_activacion_input.toolTip() == "0 = sin meta de activación"


def test_meta_activacion_se_ajusta_al_maximo_de_999(qtbot):
    dialogo = VendedorFormDialog(MagicMock())
    qtbot.addWidget(dialogo)
    _escribir_y_perder_foco(qtbot, dialogo.meta_activacion_input, "1500")
    assert dialogo.meta_activacion_input.get_value() == Decimal("999")


def test_precargar_setea_meta_activacion_desde_vendedor(qtbot):
    dialogo = VendedorFormDialog(MagicMock())
    qtbot.addWidget(dialogo)
    vendedor = SimpleNamespace(
        nombre_vendedor="Juan Perez",
        codigo_vendedor="VEN-001",
        identificacion_vendedor="V-1",
        telefono_vendedor=None,
        email_vendedor=None,
        direccion_vendedor=None,
        id_ruta=None,
        meta_activacion=12,
    )
    dialogo._precargar(vendedor)
    assert dialogo.meta_activacion_input.get_value() == Decimal("12")


def test_get_data_convierte_meta_en_cero_a_none(qtbot):
    dialogo = VendedorFormDialog(MagicMock())
    qtbot.addWidget(dialogo)
    datos = dialogo.get_data()
    assert datos["meta_activacion"] is None


def test_get_data_devuelve_entero_cuando_hay_meta(qtbot):
    dialogo = VendedorFormDialog(MagicMock())
    qtbot.addWidget(dialogo)
    _escribir_y_perder_foco(qtbot, dialogo.meta_activacion_input, "25")
    datos = dialogo.get_data()
    assert datos["meta_activacion"] == 25
    assert isinstance(datos["meta_activacion"], int)
