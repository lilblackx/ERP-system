"""bancos_panel.py no tenia ningun test de UI hasta ahora. Cobertura minima: el guard
anti-reentrancia de editar_banco() agregado en el hallazgo 3.3 (auditoria 2026-09-05) --
sin el, dos doble-clicks rapidos en la tabla (antes de que el primer modal capture el
foco) abren dos BancoFormDialog apilados contra la misma fila."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import app.ui.bancos_panel as bp


def _crear_panel(qtbot, monkeypatch):
    monkeypatch.setattr(bp.BancoService, "listar_bancos", staticmethod(lambda *a, **k: []))
    monkeypatch.setattr(bp.MessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(bp.MessageBox, "warning", lambda *a, **k: None)
    panel = bp.BancosPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    return panel


def test_editar_banco_bloquea_reentrada_pero_no_queda_trabado(qtbot, monkeypatch):
    panel = _crear_panel(qtbot, monkeypatch)
    panel._id_seleccionado = lambda: 1

    llamadas_sesion = []

    def session_factory():
        llamadas_sesion.append(1)
        return MagicMock()

    panel.session_factory = session_factory

    dialogo_mock = MagicMock()

    def fake_exec():
        # Simula un segundo doble-click mientras el primero todavia esta abriendo el
        # dialogo -- sin el guard, esto reentraria editar_banco() y abriria una segunda
        # sesion/dialogo apilado antes de que el primero termine.
        panel.editar_banco()
        return 0

    dialogo_mock.exec.side_effect = fake_exec
    monkeypatch.setattr(bp, "BancoFormDialog", lambda *a, **k: dialogo_mock)

    panel.editar_banco()

    assert len(llamadas_sesion) == 1
    assert panel._abriendo_dialogo is False

    # Una segunda llamada genuinamente secuencial (despues de que la primera termino)
    # si debe abrir su propia sesion -- el guard no debe quedar trabado en True.
    panel.editar_banco()
    assert len(llamadas_sesion) == 2
