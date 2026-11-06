"""Los selectores (QComboBox) de la app NO son editables: un combo editable deja escribir texto libre ("jjjjj"), muestra
un cursor de texto y abre una lista de autocompletado. Un campo de busqueda con sugerencias es un QLineEdit aparte."""

import re
from pathlib import Path
from unittest.mock import MagicMock

from PySide6.QtWidgets import QLineEdit

from app.ui import reportes_panel as rp
from app.ui.styles import POPUP_COMPLETER_QSS, estilizar_completer

RAIZ_UI = Path(__file__).resolve().parents[2] / "app" / "ui"


def test_ningun_combo_de_la_app_es_editable():
    ofensores = [
        archivo.name
        for archivo in sorted(RAIZ_UI.glob("*.py"))
        if re.search(r"setEditable\(\s*True\s*\)", archivo.read_text(encoding="utf-8"))
    ]

    assert ofensores == []


def test_el_selector_de_reportes_no_es_editable_ni_tiene_autocompletado(qtbot, monkeypatch):
    monkeypatch.setattr(rp.EmpresaService, "obtener_datos_documento", lambda *a, **k: None, raising=False)
    panel = rp.ReportesPanel(MagicMock(return_value=MagicMock()), MagicMock(id_usuario=1))
    qtbot.addWidget(panel)

    combo = panel.tipo_combo

    assert not combo.isEditable()
    assert combo.lineEdit() is None  # sin cuadro de texto: no hay cursor ni se puede teclear texto libre
    assert combo.completer() is None


def test_la_lista_de_sugerencias_de_un_completer_es_legible(qtbot):
    from PySide6.QtWidgets import QCompleter

    campo = QLineEdit()
    qtbot.addWidget(campo)
    completer = QCompleter(["Caracas", "Carabobo"], campo)
    campo.setCompleter(completer)

    estilizar_completer(completer)

    hoja = completer.popup().styleSheet()
    assert hoja == POPUP_COMPLETER_QSS
    assert "background-color: #FFFFFF" in hoja and "color: #1E293B" in hoja  # fondo claro, texto oscuro
