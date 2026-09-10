"""Tests de los campos dias_horizonte_input / dias_horizonte_ppv_input de ReportesPanel
tras migrarlos de QSpinBox a NumericLineEdit (NumericFieldType.COUNT, con
min_value=1 explicito -- el piso de 0 que trae COUNT por defecto no sirve para un
horizonte de dias, que nunca puede ser 0).

ReportesPanel completo (app/ui/reportes_panel.py) es pesado de instanciar en un test:
su __init__ dispara ocho cargas de catalogo contra la Session mas un
QTimer.singleShot(100, self._generar) que a su vez lanza un QueryWorker en un hilo
aparte -- mockear toda esa cadena para cubrir dos campos numericos seria un test fragil
que no aporta mas cobertura real. En su lugar se construyen los dos widgets de filtro
que declaran esos campos (_make_filtros_proximos_vencimientos /
_make_filtros_productos_proximos_vencer) sobre una instancia sin inicializar
(object.__new__), igual que se los construye en _setup_ui() -- ambos metodos son
autocontenidos (solo arman un QWidget con QLabel/QComboBox/NumericLineEdit locales, sin
tocar self.session_factory ni ninguna otra dependencia)."""

from decimal import Decimal

from app.ui.reportes_panel import ReportesPanel


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


def _panel_sin_init() -> ReportesPanel:
    return ReportesPanel.__new__(ReportesPanel)


def test_dias_horizonte_input_arranca_en_30(qtbot):
    panel = _panel_sin_init()
    widget = panel._make_filtros_proximos_vencimientos()
    qtbot.addWidget(widget)
    assert panel.dias_horizonte_input.get_value() == Decimal("30")
    assert panel.dias_horizonte_input.text() == "30"


def test_dias_horizonte_input_no_admite_menos_de_1(qtbot):
    panel = _panel_sin_init()
    widget = panel._make_filtros_proximos_vencimientos()
    qtbot.addWidget(widget)
    _escribir_y_perder_foco(qtbot, panel.dias_horizonte_input, "0")
    assert panel.dias_horizonte_input.get_value() == Decimal("1")


def test_dias_horizonte_input_se_ajusta_al_maximo_365(qtbot):
    panel = _panel_sin_init()
    widget = panel._make_filtros_proximos_vencimientos()
    qtbot.addWidget(widget)
    _escribir_y_perder_foco(qtbot, panel.dias_horizonte_input, "999")
    assert panel.dias_horizonte_input.get_value() == Decimal("365")


def test_dias_horizonte_ppv_input_arranca_en_30(qtbot):
    panel = _panel_sin_init()
    widget = panel._make_filtros_productos_proximos_vencer()
    qtbot.addWidget(widget)
    assert panel.dias_horizonte_ppv_input.get_value() == Decimal("30")
    assert panel.dias_horizonte_ppv_input.text() == "30"


def test_dias_horizonte_ppv_input_no_admite_menos_de_1(qtbot):
    panel = _panel_sin_init()
    widget = panel._make_filtros_productos_proximos_vencer()
    qtbot.addWidget(widget)
    _escribir_y_perder_foco(qtbot, panel.dias_horizonte_ppv_input, "0")
    assert panel.dias_horizonte_ppv_input.get_value() == Decimal("1")


def test_dias_horizonte_ppv_input_se_ajusta_al_maximo_365(qtbot):
    panel = _panel_sin_init()
    widget = panel._make_filtros_productos_proximos_vencer()
    qtbot.addWidget(widget)
    _escribir_y_perder_foco(qtbot, panel.dias_horizonte_ppv_input, "999")
    assert panel.dias_horizonte_ppv_input.get_value() == Decimal("365")
