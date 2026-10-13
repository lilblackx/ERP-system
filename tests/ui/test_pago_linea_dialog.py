"""Tests de PagoLineaDialog tras migrar monto_input de QDoubleSpinBox a NumericLineEdit
(NumericFieldType.AMOUNT, min_value=Decimal("0.01") -- el rango original era
(0.01, 999999999.99), sin negativos, ver app/ui/pago_linea_dialog.py).

_cargar_origenes() llama CajaService.listar_cajas()/BancoService.listar_cuentas(), que
hacen consultas ORM con joinedload -- se parchean directo en vez de armar la cadena de
mock de session.query(), que no es el objeto de este test (el widget numerico)."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt

from app.ui.pago_linea_dialog import PagoLineaDialog

_CAJA_ABIERTA = SimpleNamespace(
    id_caja=1,
    nombre_caja="Caja Principal",
    fecha_apertura="2026-01-01",
    fecha_cierre=None,
)


def _dar_foco(qtbot, campo):
    campo.window().show()
    qtbot.waitExposed(campo.window())
    campo.setFocus()
    qtbot.waitUntil(campo.hasFocus)


def _escribir_y_perder_foco(qtbot, campo, texto):
    _dar_foco(qtbot, campo)
    qtbot.keyClicks(campo, texto)
    campo.clearFocus()


def _session_con_tasa(tasa_bcv="36.50", tasa_cop="4000.00"):
    """Sesion falsa para _cargar_tasas(): session.query(...).order_by(...).first()."""
    tasa = SimpleNamespace(
        id_tasa=1,
        tasa_dolar_bcv=Decimal(tasa_bcv),
        tasa_dolar_paralelo=None,
        tasa_cop=Decimal(tasa_cop) if tasa_cop else None,
    )
    session = MagicMock()
    session.query.return_value.order_by.return_value.first.return_value = tasa
    return session


def _crear_dialogo(qtbot, monto_sugerido=None, session=None):
    with (
        patch(
            "app.ui.pago_linea_dialog.CajaService.listar_cajas",
            return_value=[_CAJA_ABIERTA],
        ),
        patch("app.ui.pago_linea_dialog.BancoService.listar_cuentas", return_value=[]),
    ):
        dialogo = PagoLineaDialog(session, id_usuario=1, monto_sugerido=monto_sugerido)
    qtbot.addWidget(dialogo)
    return dialogo


def test_monto_input_arranca_en_cero_formateado(qtbot):
    dialogo = _crear_dialogo(qtbot)
    assert dialogo.monto_input.text() == "0,00"
    assert dialogo.monto_input.get_value() == Decimal("0")


def test_monto_input_formatea_miles_al_perder_foco(qtbot):
    dialogo = _crear_dialogo(qtbot)
    _escribir_y_perder_foco(qtbot, dialogo.monto_input, "1500,25")
    assert dialogo.monto_input.get_value() == Decimal("1500.25")
    assert dialogo.monto_input.text() == "1.500,25"


def test_monto_sugerido_precarga_el_valor(qtbot):
    dialogo = _crear_dialogo(qtbot, monto_sugerido=250.5)
    assert dialogo.monto_input.get_value() == Decimal("250.50")


def test_monto_input_no_admite_valores_negativos(qtbot):
    dialogo = _crear_dialogo(qtbot)
    _dar_foco(qtbot, dialogo.monto_input)
    qtbot.keyClicks(dialogo.monto_input, "-5")
    # El "-" se descarta tecla a tecla -- mismo comportamiento que el QDoubleSpinBox
    # original, cuyo rango (0.01, 999999999.99) tampoco admitia signo negativo.
    assert dialogo.monto_input.text() == "5"


def test_monto_input_se_ajusta_al_minimo_de_0_01(qtbot):
    dialogo = _crear_dialogo(qtbot)
    _escribir_y_perder_foco(qtbot, dialogo.monto_input, "0")
    assert dialogo.monto_input.get_value() == Decimal("0.01")


def test_get_data_incluye_monto_decimal(qtbot):
    dialogo = _crear_dialogo(qtbot)
    _escribir_y_perder_foco(qtbot, dialogo.monto_input, "75,40")

    datos = dialogo.get_data()

    assert datos["monto_moneda_origen"] == Decimal("75.40")


def test_enter_en_monto_dispara_validar_con_el_valor_recien_tecleado(qtbot):
    """Regresion: monto_input.returnPressed esta conectado a _validar_y_aceptar (linea
    237, "Agregar forma de pago" + Enter sin mouse). QLineEdit nativo emite
    returnPressed() ANTES que editingFinished() -- sin el fix de
    NumericLineEdit._commit_value (ver app/ui/numeric_inputs.py y el bug identico
    encontrado en factura_form_dialog.py), _validar_y_aceptar habria leido el monto
    VIEJO (el de antes de este tecleo), no el que el cajero acaba de escribir --
    registrando una forma de pago con el importe incorrecto en el primer Enter."""
    valores_vistos = []

    def espia(self):
        valores_vistos.append(self.monto_input.get_value())

    with patch.object(PagoLineaDialog, "_validar_y_aceptar", espia):
        dialogo = _crear_dialogo(qtbot)
        _dar_foco(qtbot, dialogo.monto_input)
        qtbot.keyClicks(dialogo.monto_input, "150,50")
        qtbot.keyClick(dialogo.monto_input, Qt.Key.Key_Return)

    assert valores_vistos == [Decimal("150.50")]


# --- Monto sugerido convertido a la moneda elegida ---------------------------------------
# Caso reportado: factura de $1.50, $1 en efectivo, el resto en Bs -- el dialogo seguia
# sugiriendo 0,50 al elegir Bolivares (y agregado asi contaba como Bs 0,50).


def _elegir(combo, valor):
    combo.setCurrentIndex(combo.findData(valor))


def test_monto_sugerido_se_convierte_a_bs_con_tasa_bcv(qtbot):
    dialogo = _crear_dialogo(qtbot, monto_sugerido=0.5, session=_session_con_tasa())
    _elegir(dialogo.moneda_combo, "VES")
    assert dialogo.monto_input.get_value() == Decimal("18.25")


def test_monto_sugerido_se_convierte_a_cop(qtbot):
    dialogo = _crear_dialogo(qtbot, monto_sugerido=0.5, session=_session_con_tasa())
    _elegir(dialogo.moneda_combo, "COP")
    assert dialogo.monto_input.get_value() == Decimal("2000.00")


def test_volver_a_usd_restaura_el_saldo_en_dolares(qtbot):
    dialogo = _crear_dialogo(qtbot, monto_sugerido=0.5, session=_session_con_tasa())
    _elegir(dialogo.moneda_combo, "VES")
    _elegir(dialogo.moneda_combo, "USD")
    assert dialogo.monto_input.get_value() == Decimal("0.50")


def test_monto_tecleado_no_se_pisa_al_cambiar_moneda(qtbot):
    dialogo = _crear_dialogo(qtbot, monto_sugerido=0.5, session=_session_con_tasa())
    _escribir_y_perder_foco(qtbot, dialogo.monto_input, "10")
    _elegir(dialogo.moneda_combo, "VES")
    assert dialogo.monto_input.get_value() == Decimal("10.00")


def test_sin_tasa_cop_no_sugiere_monto_en_cop(qtbot):
    dialogo = _crear_dialogo(qtbot, monto_sugerido=0.5, session=_session_con_tasa(tasa_cop=None))
    _elegir(dialogo.moneda_combo, "COP")
    # Sin tasa no hay conversion posible: queda el valor anterior, no uno inventado.
    assert dialogo.monto_input.get_value() == Decimal("0.50")


def test_transferencia_preselecciona_bcv_y_calcula_bs_del_saldo(qtbot):
    dialogo = _crear_dialogo(qtbot, monto_sugerido=0.5, session=_session_con_tasa())
    _elegir(dialogo.metodo_combo, "transferencia")
    assert dialogo.tasa_input.get_value() == Decimal("36.50")
    assert dialogo.monto_input.get_value() == Decimal("0.50")
    assert dialogo.bolivares_input.get_value() == Decimal("18.25")
