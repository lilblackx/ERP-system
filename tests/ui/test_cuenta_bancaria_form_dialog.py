"""Tests de CuentaBancariaFormDialog tras migrar saldo_input de QDoubleSpinBox a
NumericLineEdit (NumericFieldType.AMOUNT, prefix="$ "). La Session se mockea (no se
golpea la base real) -- _cargar_bancos() hace
session.query(Banco).filter(...).order_by(...).all() al construir el dialogo, asi que
esa cadena se deja vacia en el mock."""

from decimal import Decimal
from unittest.mock import MagicMock

from app.ui.cuenta_bancaria_form_dialog import CuentaBancariaFormDialog


def _session_vacia() -> MagicMock:
    session = MagicMock()
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    return session


def _dar_foco(qtbot, campo):
    # Un campo anidado dentro de un QDialog no shown() nunca resuelve el foco logico de
    # Qt bajo QT_QPA_PLATFORM=offscreen -- hay que exponer tambien la ventana top-level
    # (el dialogo), no solo el campo, antes de pedirle el foco (ver
    # tests/ui/test_proveedor_form_dialog.py, mismo gotcha).
    campo.window().show()
    qtbot.waitExposed(campo.window())
    campo.setFocus()
    qtbot.waitUntil(campo.hasFocus)


def test_saldo_input_arranca_en_cero_formateado(qtbot):
    dialogo = CuentaBancariaFormDialog(_session_vacia())
    qtbot.addWidget(dialogo)
    assert dialogo.saldo_input.text() == "$ 0,00"
    assert dialogo.saldo_input.get_value() == Decimal("0")


def test_saldo_input_formatea_al_perder_foco(qtbot):
    dialogo = CuentaBancariaFormDialog(_session_vacia())
    qtbot.addWidget(dialogo)
    dialogo.moneda_combo.setCurrentIndex(dialogo.moneda_combo.findData("USD"))  # el saldo USD solo se ve en USD
    _dar_foco(qtbot, dialogo.saldo_input)
    qtbot.keyClicks(dialogo.saldo_input, "12345,6")
    dialogo.saldo_input.clearFocus()
    assert dialogo.saldo_input.get_value() == Decimal("12345.60")
    assert dialogo.saldo_input.text() == "$ 12.345,60"


def test_get_data_incluye_saldo_tecleado_al_crear(qtbot):
    dialogo = CuentaBancariaFormDialog(_session_vacia())
    qtbot.addWidget(dialogo)
    dialogo.moneda_combo.setCurrentIndex(dialogo.moneda_combo.findData("USD"))  # el saldo USD solo se ve en USD
    _dar_foco(qtbot, dialogo.saldo_input)
    qtbot.keyClicks(dialogo.saldo_input, "999,99")
    dialogo.saldo_input.clearFocus()

    datos = dialogo.get_data()

    assert datos["saldo_total_banco"] == Decimal("999.99")


def test_precargar_deshabilita_saldo_y_no_lo_incluye_en_get_data(qtbot):
    session = _session_vacia()
    cuenta = MagicMock()
    cuenta.numero_cuenta = "0134-0001-123456789"
    cuenta.nombre_titular = "Juan Perez"
    cuenta.identificacion_titular = "V-12345678"
    cuenta.saldo_total_banco = Decimal("1000.00")
    cuenta.saldo_total_banco_bs = Decimal("5000.00")
    cuenta.id_banco = None
    cuenta.tipo_cuenta_banco = "CORRIENTE"
    cuenta.fecha_creacion = None
    cuenta.creador = None

    dialogo = CuentaBancariaFormDialog(session, cuenta=cuenta)
    qtbot.addWidget(dialogo)

    assert dialogo.saldo_input.get_value() == Decimal("1000.00")
    assert dialogo.saldo_input.text() == "$ 1.000,00"
    assert not dialogo.saldo_input.isEnabled()

    datos = dialogo.get_data()
    assert "saldo_total_banco" not in datos


def test_saldo_bs_input_arranca_en_cero_formateado(qtbot):
    dialogo = CuentaBancariaFormDialog(_session_vacia())
    qtbot.addWidget(dialogo)
    assert dialogo.saldo_bs_input.text() == "0,00"
    assert dialogo.saldo_bs_input.get_value() == Decimal("0")


def test_saldo_bs_input_formatea_al_perder_foco(qtbot):
    dialogo = CuentaBancariaFormDialog(_session_vacia())
    qtbot.addWidget(dialogo)
    _dar_foco(qtbot, dialogo.saldo_bs_input)
    qtbot.keyClicks(dialogo.saldo_bs_input, "12345,6")
    dialogo.saldo_bs_input.clearFocus()
    assert dialogo.saldo_bs_input.get_value() == Decimal("12345.60")
    assert dialogo.saldo_bs_input.text() == "12.345,60"


def test_get_data_incluye_saldo_bs_tecleado_al_crear(qtbot):
    dialogo = CuentaBancariaFormDialog(_session_vacia())
    qtbot.addWidget(dialogo)
    _dar_foco(qtbot, dialogo.saldo_bs_input)
    qtbot.keyClicks(dialogo.saldo_bs_input, "999,99")
    dialogo.saldo_bs_input.clearFocus()

    datos = dialogo.get_data()

    assert datos["saldo_total_banco_bs"] == Decimal("999.99")


def test_precargar_deshabilita_saldo_bs_y_no_lo_incluye_en_get_data(qtbot):
    session = _session_vacia()
    cuenta = MagicMock()
    cuenta.numero_cuenta = "0134-0001-123456789"
    cuenta.nombre_titular = "Juan Perez"
    cuenta.identificacion_titular = "V-12345678"
    cuenta.saldo_total_banco = Decimal("1000.00")
    cuenta.saldo_total_banco_bs = Decimal("5000.00")
    cuenta.id_banco = None
    cuenta.tipo_cuenta_banco = "CORRIENTE"
    cuenta.fecha_creacion = None
    cuenta.creador = None

    dialogo = CuentaBancariaFormDialog(session, cuenta=cuenta)
    qtbot.addWidget(dialogo)

    assert dialogo.saldo_bs_input.get_value() == Decimal("5000.00")
    assert dialogo.saldo_bs_input.text() == "5.000,00"
    assert not dialogo.saldo_bs_input.isEnabled()

    datos = dialogo.get_data()
    assert "saldo_total_banco_bs" not in datos


# -- Moneda de la cuenta ---------------------------------------------------------------------------------------


def _cuenta_existente(moneda="USD"):
    from types import SimpleNamespace

    return SimpleNamespace(
        id_cuenta=7,
        id_banco=1,
        numero_cuenta="0134000000000007",
        tipo_cuenta_banco="CORRIENTE",
        nombre_titular="Distribuidora DJ",
        identificacion_titular="J-1",
        saldo_total_banco=Decimal("10.00"),
        saldo_total_banco_bs=Decimal("0.00"),
        saldo_total_banco_cop=Decimal("0.00"),
        estado_cuenta="ACTIVO",
        moneda=moneda,
        fecha_creacion=None,
        creador=None,
    )


def test_el_formulario_ofrece_las_tres_monedas_y_abre_en_bolivares(qtbot):
    dialogo = CuentaBancariaFormDialog(_session_vacia())
    qtbot.addWidget(dialogo)

    monedas = [dialogo.moneda_combo.itemData(i) for i in range(dialogo.moneda_combo.count())]

    etiquetas = [dialogo.moneda_combo.itemText(i) for i in range(dialogo.moneda_combo.count())]

    assert monedas == ["VES", "USD", "COP"]
    assert etiquetas == ["Bolívares (VES)", "Dólares (USD)", "Pesos colombianos (COP)"]
    assert dialogo.moneda_combo.currentData() == "VES"
    assert dialogo.get_data()["moneda"] == "VES"


def test_la_moneda_elegida_viaja_en_los_datos(qtbot):
    dialogo = CuentaBancariaFormDialog(_session_vacia())
    qtbot.addWidget(dialogo)

    dialogo.moneda_combo.setCurrentIndex(dialogo.moneda_combo.findData("COP"))

    assert dialogo.get_data()["moneda"] == "COP"


def test_al_editar_se_precarga_la_moneda_y_se_puede_cambiar_si_no_hay_movimientos(qtbot):
    session = _session_vacia()
    session.query.return_value.filter.return_value.first.return_value = None  # sin movimientos
    dialogo = CuentaBancariaFormDialog(session, cuenta=_cuenta_existente("USD"))
    qtbot.addWidget(dialogo)

    assert dialogo.moneda_combo.currentData() == "USD"
    assert dialogo.moneda_combo.isEnabled()


def test_con_movimientos_la_moneda_sigue_editable_y_se_avisa_que_pide_confirmacion(qtbot):
    session = _session_vacia()
    session.query.return_value.filter.return_value.first.return_value = (1,)  # tiene movimientos
    dialogo = CuentaBancariaFormDialog(session, cuenta=_cuenta_existente("USD"))
    qtbot.addWidget(dialogo)

    assert dialogo.moneda_combo.currentData() == "USD"
    assert dialogo.moneda_combo.isEnabled()
    assert not dialogo.lbl_aviso_moneda.isHidden()
    assert "confirmación" in dialogo.lbl_aviso_moneda.text()
    dialogo.moneda_combo.setCurrentIndex(dialogo.moneda_combo.findData("VES"))
    assert dialogo.get_data()["moneda"] == "VES"


def test_sin_movimientos_no_se_muestra_el_aviso_de_confirmacion(qtbot):
    session = _session_vacia()
    session.query.return_value.filter.return_value.first.return_value = None
    dialogo = CuentaBancariaFormDialog(session, cuenta=_cuenta_existente("USD"))
    qtbot.addWidget(dialogo)

    assert dialogo.lbl_aviso_moneda.isHidden()


def test_al_crear_una_cuenta_nunca_se_muestra_el_aviso(qtbot):
    dialogo = CuentaBancariaFormDialog(_session_vacia())
    qtbot.addWidget(dialogo)

    assert dialogo.lbl_aviso_moneda.isHidden()


# -- Saldos segun la moneda ------------------------------------------------------------------------------------


def _elegir_moneda(dialogo, moneda):
    dialogo.moneda_combo.setCurrentIndex(dialogo.moneda_combo.findData(moneda))


def test_en_bolivares_solo_se_pide_el_saldo_en_bs(qtbot):
    dialogo = CuentaBancariaFormDialog(_session_vacia())
    qtbot.addWidget(dialogo)

    assert dialogo.moneda_combo.currentData() == "VES"
    assert dialogo.saldo_usd_widget.isHidden()
    assert not dialogo.saldo_bs_widget.isHidden()


def test_en_dolares_solo_se_pide_el_saldo_en_usd(qtbot):
    dialogo = CuentaBancariaFormDialog(_session_vacia())
    qtbot.addWidget(dialogo)

    _elegir_moneda(dialogo, "USD")

    assert not dialogo.saldo_usd_widget.isHidden()
    assert dialogo.saldo_bs_widget.isHidden()


def test_los_campos_cambian_solos_al_cambiar_la_moneda_y_el_oculto_se_limpia(qtbot):
    dialogo = CuentaBancariaFormDialog(_session_vacia())
    qtbot.addWidget(dialogo)
    dialogo.saldo_bs_input.set_value(Decimal("5000.00"))  # en bolivares

    _elegir_moneda(dialogo, "USD")
    assert dialogo.saldo_bs_input.get_value() == Decimal("0")  # no queda un monto en la moneda equivocada
    dialogo.saldo_input.set_value(Decimal("250.00"))

    _elegir_moneda(dialogo, "VES")
    datos = dialogo.get_data()

    assert datos["saldo_total_banco"] == Decimal("0")
    assert datos["saldo_total_banco_bs"] == Decimal("0")
    assert dialogo.saldo_usd_widget.isHidden() and not dialogo.saldo_bs_widget.isHidden()


def test_el_saldo_visible_viaja_en_los_datos(qtbot):
    dialogo = CuentaBancariaFormDialog(_session_vacia())
    qtbot.addWidget(dialogo)
    _elegir_moneda(dialogo, "USD")
    dialogo.saldo_input.set_value(Decimal("250.00"))

    datos = dialogo.get_data()

    assert datos["moneda"] == "USD"
    assert datos["saldo_total_banco"] == Decimal("250.00")
    assert datos["saldo_total_banco_bs"] == Decimal("0")


def test_en_pesos_solo_se_pide_el_saldo_en_cop(qtbot):
    dialogo = CuentaBancariaFormDialog(_session_vacia())
    qtbot.addWidget(dialogo)

    _elegir_moneda(dialogo, "COP")

    assert not dialogo.saldo_cop_widget.isHidden()
    assert dialogo.saldo_usd_widget.isHidden() and dialogo.saldo_bs_widget.isHidden()
    assert dialogo.lbl_saldo_cop.text() == "Saldo Inicial COP"


def test_el_saldo_en_cop_viaja_en_los_datos_y_los_otros_quedan_en_cero(qtbot):
    dialogo = CuentaBancariaFormDialog(_session_vacia())
    qtbot.addWidget(dialogo)
    _elegir_moneda(dialogo, "COP")
    dialogo.saldo_cop_input.set_value(Decimal("1500000.50"))

    datos = dialogo.get_data()

    assert datos["moneda"] == "COP"
    assert datos["saldo_total_banco_cop"] == Decimal("1500000.50")
    assert datos["saldo_total_banco"] == Decimal("0") and datos["saldo_total_banco_bs"] == Decimal("0")


def test_cambiar_de_pesos_a_otra_moneda_limpia_el_saldo_en_cop(qtbot):
    dialogo = CuentaBancariaFormDialog(_session_vacia())
    qtbot.addWidget(dialogo)
    _elegir_moneda(dialogo, "COP")
    dialogo.saldo_cop_input.set_value(Decimal("900000"))

    _elegir_moneda(dialogo, "USD")

    assert dialogo.saldo_cop_input.get_value() == Decimal("0")
    assert dialogo.get_data()["saldo_total_banco_cop"] == Decimal("0")


def test_cada_moneda_muestra_exactamente_un_saldo(qtbot):
    dialogo = CuentaBancariaFormDialog(_session_vacia())
    qtbot.addWidget(dialogo)

    visibles = {}
    for moneda in ("VES", "USD", "COP"):
        _elegir_moneda(dialogo, moneda)
        visibles[moneda] = [
            nombre
            for nombre, widget in (
                ("usd", dialogo.saldo_usd_widget),
                ("bs", dialogo.saldo_bs_widget),
                ("cop", dialogo.saldo_cop_widget),
            )
            if not widget.isHidden()
        ]

    assert visibles == {"VES": ["bs"], "USD": ["usd"], "COP": ["cop"]}


def test_al_editar_una_cuenta_cop_se_muestra_su_saldo_en_pesos(qtbot):
    session = _session_vacia()
    session.query.return_value.filter.return_value.first.return_value = (1,)
    cuenta = _cuenta_existente("COP")
    cuenta.saldo_total_banco_cop = Decimal("2500000.00")
    dialogo = CuentaBancariaFormDialog(session, cuenta=cuenta)
    qtbot.addWidget(dialogo)

    assert not dialogo.saldo_cop_widget.isHidden()
    assert dialogo.saldo_cop_input.get_value() == Decimal("2500000.00")
    assert not dialogo.saldo_cop_input.isEnabled()
    assert "saldo_total_banco_cop" not in dialogo.get_data()


def test_al_editar_se_muestra_solo_el_saldo_de_la_moneda_de_la_cuenta_sin_borrar_nada(qtbot):
    session = _session_vacia()
    session.query.return_value.filter.return_value.first.return_value = (1,)
    dialogo = CuentaBancariaFormDialog(session, cuenta=_cuenta_existente("USD"))
    qtbot.addWidget(dialogo)

    assert not dialogo.saldo_usd_widget.isHidden()
    assert dialogo.saldo_bs_widget.isHidden()
    assert dialogo.saldo_input.get_value() == Decimal("10.00")
    assert "saldo_total_banco" not in dialogo.get_data()
