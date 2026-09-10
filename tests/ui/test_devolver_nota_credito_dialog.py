"""Tests de DevolverNotaCreditoDialog tras migrar monto_input de QDoubleSpinBox a
NumericLineEdit (NumericFieldType.AMOUNT, min_value=Decimal("0.01") fijo -- el maximo
sigue siendo dinamico segun la nota seleccionada, ver _on_nota_cambiada() en
app/ui/devolver_nota_credito_dialog.py, que ahora asigna `monto_input.max_value`
directo en vez de QDoubleSpinBox.setRange()).

id_usuario=None hace que CajaService.listar_cajas()/BancoService.listar_cuentas()
(llamadas por _cargar_origenes() al construir) fallen con PermisoDenegadoError de
entrada (require_permiso trata id_usuario=None como no autorizado) -- el dialogo ya
atrapa ese caso y deja las listas de origen vacias, asi que no hace falta simular
Session real ni cajas/cuentas para probar el campo de monto."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from PySide6.QtWidgets import QDialog

from app.services.notas_credito import NotaCreditoService
from app.ui.devolver_nota_credito_dialog import DevolverNotaCreditoDialog


def _nota(saldo="500.00"):
    return SimpleNamespace(
        numero_nota_credito="NC-001",
        saldo_disponible=Decimal(saldo),
        id_nota_credito=1,
        estado="disponible",
    )


def _dar_foco(qtbot, campo):
    # Un campo anidado dentro de un QDialog no shown() nunca resuelve el foco logico de
    # Qt bajo QT_QPA_PLATFORM=offscreen -- hay que exponer tambien la ventana top-level
    # (el dialogo), no solo el campo, antes de pedirle el foco (ver
    # tests/ui/test_proveedor_form_dialog.py, mismo gotcha).
    campo.window().show()
    qtbot.waitExposed(campo.window())
    campo.setFocus()
    qtbot.waitUntil(campo.hasFocus)


def test_monto_input_arranca_en_el_saldo_disponible_de_la_nota(qtbot):
    dialogo = DevolverNotaCreditoDialog(MagicMock(), id_usuario=None, notas_disponibles=[_nota()])
    qtbot.addWidget(dialogo)
    assert dialogo.monto_input.text() == "500,00"
    assert dialogo.monto_input.get_value() == Decimal("500.00")


def test_monto_input_formatea_al_perder_foco(qtbot):
    dialogo = DevolverNotaCreditoDialog(MagicMock(), id_usuario=None, notas_disponibles=[_nota()])
    qtbot.addWidget(dialogo)
    _dar_foco(qtbot, dialogo.monto_input)
    qtbot.keyClicks(dialogo.monto_input, "300,5")
    dialogo.monto_input.clearFocus()
    assert dialogo.monto_input.get_value() == Decimal("300.50")
    assert dialogo.monto_input.text() == "300,50"


def test_confirmar_pasa_el_monto_tecleado_al_servicio(qtbot, monkeypatch):
    dialogo = DevolverNotaCreditoDialog(MagicMock(), id_usuario=None, notas_disponibles=[_nota()])
    qtbot.addWidget(dialogo)

    _dar_foco(qtbot, dialogo.monto_input)
    qtbot.keyClicks(dialogo.monto_input, "150,25")
    dialogo.monto_input.clearFocus()

    # _cargar_origenes() dejo el combo de origen sin cajas/cuentas reales (permiso
    # denegado con id_usuario=None) -- se fuerza un origen valido para llegar al llamado
    # al servicio, que es lo que este test quiere verificar.
    monkeypatch.setattr(dialogo.origen_combo, "currentData", lambda: ("caja", 1))

    class DummyAutorizacionDialog:
        def __init__(self, *args, **kwargs):
            self.usuario_autorizador = SimpleNamespace(id_usuario=9)
            self.motivo = "autorizado en test"

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr("app.ui.devolver_nota_credito_dialog.AutorizacionDialog", DummyAutorizacionDialog)

    llamada = {}

    def fake_devolver(session, **kwargs):
        llamada.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(NotaCreditoService, "devolver_nota_credito_cliente", staticmethod(fake_devolver))

    dialogo._confirmar()

    assert llamada["monto"] == Decimal("150.25")
