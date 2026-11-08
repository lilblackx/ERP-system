"""Conciliacion de bancos segun la moneda de la cuenta: una cuenta en USD solo habla de dolares; una en bolivares
(o pesos), solo de su moneda local. Nada de la otra moneda se muestra ni se pide (ni saldos, ni tasa, ni columnas)."""

from decimal import Decimal

import pytest

import app.ui.conciliacion_bancos_dialog as cb
from app.db.models import BancoMovimiento
from app.services.banco_movimientos import BancoMovimientoService
from tests.factories import crear_cuenta_bancaria, crear_usuario_admin


@pytest.fixture()
def avisos(monkeypatch):
    registro = {"warning": [], "information": [], "critical": []}
    for nivel, lista in registro.items():
        monkeypatch.setattr(cb.MessageBox, nivel, lambda parent, titulo, texto, _l=lista: _l.append((titulo, texto)))
    return registro


@pytest.fixture()
def escenario(db_session):
    """Una cuenta en USD con un abono de $100 y otra en VES con un abono de Bs 4.000 (el mismo dia)."""
    admin = crear_usuario_admin(db_session)
    usd = crear_cuenta_bancaria(db_session, moneda="USD")
    ves = crear_cuenta_bancaria(db_session, moneda="VES")
    BancoMovimientoService.crear(
        db_session, usd.id_cuenta, "abono", 100.0, referencia="Z-1", id_usuario=admin.id_usuario
    )
    BancoMovimientoService.crear(
        db_session,
        ves.id_cuenta,
        "abono",
        100.0,
        referencia="T-1",
        id_usuario=admin.id_usuario,
        monto_bolivares=4000.0,
        tasa_cambio=40.0,
    )
    return admin, usd, ves


def _dialogo(qtbot, db_session, admin, cuenta):
    dlg = cb.ConciliacionBancosDialog(db_session, admin)
    qtbot.addWidget(dlg)
    dlg.cuenta_combo.setCurrentIndex(dlg.cuenta_combo.findData(cuenta.id_cuenta))
    return dlg


def _visible(dlg, widget) -> bool:
    return widget.isVisibleTo(dlg)


def _columnas_visibles(dlg) -> list[str]:
    tabla = dlg.table
    return [tabla.horizontalHeaderItem(c).text() for c in range(tabla.columnCount()) if not tabla.isColumnHidden(c)]


def _texto_resumen(dlg) -> str:
    return " | ".join(
        w.text() for w in (dlg.lbl_saldo_inicial, dlg.lbl_total_entradas, dlg.lbl_total_salidas, dlg.lbl_diferencia)
    )


# -- Cuenta en USD ------------------------------------------------------------------------------------------------


def test_cuenta_en_usd_solo_muestra_dolares(qtbot, db_session, escenario):
    admin, usd, _ves = escenario

    dlg = _dialogo(qtbot, db_session, admin, usd)

    assert _visible(dlg, dlg.saldo_final_input) and not _visible(dlg, dlg.saldo_final_bs_input)
    assert _visible(dlg, dlg.lbl_saldo_final) and not _visible(dlg, dlg.lbl_saldo_final_bs)
    assert _columnas_visibles(dlg) == ["Fecha", "Tipo", "Monto", "Origen", "Referencia", "Descripción"]
    texto = _texto_resumen(dlg)
    assert "$100.00" in texto and "BS" not in texto.upper().replace("DIFERENCIA", "")
    assert "Tasa" not in " ".join(
        dlg.table.horizontalHeaderItem(c).text()
        for c in range(dlg.table.columnCount())
        if not dlg.table.isColumnHidden(c)
    )


def test_cuenta_en_usd_concilia_en_dolares_sin_pedir_tasa(qtbot, db_session, escenario, avisos):
    admin, usd, _ves = escenario
    dlg = _dialogo(qtbot, db_session, admin, usd)

    dlg.saldo_final_input.set_value(Decimal("100.00"))
    dlg._calcular_conciliacion()
    assert dlg.lbl_estado_texto.text() == "Estado: Cuadrado"

    dlg._marcar_conciliado()

    assert avisos["warning"] == []
    assert avisos["information"][0][0] == "Conciliación Exitosa"
    assert "Saldo Final USD: 100.00" in avisos["information"][0][1]


def test_cuenta_en_usd_con_diferencia_no_se_puede_conciliar(qtbot, db_session, escenario, avisos):
    admin, usd, _ves = escenario
    dlg = _dialogo(qtbot, db_session, admin, usd)
    dlg.saldo_final_input.set_value(Decimal("90.00"))

    dlg._calcular_conciliacion()
    dlg._marcar_conciliado()

    assert dlg.lbl_estado_texto.text() == "Estado: Desbalanceado"
    assert dlg.lbl_diferencia.text() == "Diferencia: $10.00"
    assert avisos["warning"][0][0] == "No se puede conciliar" and "USD" in avisos["warning"][0][1]


# -- Cuenta en bolivares ------------------------------------------------------------------------------------------


def test_cuenta_en_bolivares_solo_muestra_bolivares(qtbot, db_session, escenario):
    admin, _usd, ves = escenario

    dlg = _dialogo(qtbot, db_session, admin, ves)

    assert _visible(dlg, dlg.saldo_final_bs_input) and not _visible(dlg, dlg.saldo_final_input)
    assert _visible(dlg, dlg.lbl_saldo_final_bs) and not _visible(dlg, dlg.lbl_saldo_final)
    assert _columnas_visibles(dlg) == ["Fecha", "Tipo", "Monto BS", "Origen", "Referencia", "Descripción"]
    texto = _texto_resumen(dlg)
    assert "BS 4,000.00" in texto and "$" not in texto
    assert dlg.lbl_saldo_final_bs.text() == "Saldo Final BS:"


def test_cuenta_en_bolivares_concilia_en_bolivares_sin_pedir_tasa(qtbot, db_session, escenario, avisos):
    admin, _usd, ves = escenario
    dlg = _dialogo(qtbot, db_session, admin, ves)

    dlg.saldo_final_bs_input.set_value(Decimal("4000.00"))
    dlg._calcular_conciliacion()
    dlg._marcar_conciliado()

    assert dlg.lbl_estado_texto.text() == "Estado: Cuadrado"
    assert avisos["warning"] == []  # antes pedia "Tasa requerida" y comparaba el saldo en bolivares con dolares
    assert "Saldo Final BS: 4,000.00" in avisos["information"][0][1] and "USD" not in avisos["information"][0][1]


def test_cuenta_en_pesos_habla_de_pesos(qtbot, db_session):
    admin = crear_usuario_admin(db_session)
    cop = crear_cuenta_bancaria(db_session, moneda="COP")
    BancoMovimientoService.crear(
        db_session,
        cop.id_cuenta,
        "abono",
        10.0,
        id_usuario=admin.id_usuario,
        monto_bolivares=40000.0,
        tasa_cambio=4000.0,
    )

    dlg = _dialogo(qtbot, db_session, admin, cop)

    assert dlg.lbl_saldo_final_bs.text() == "Saldo Final COP:"
    assert "COP 40,000.00" in _texto_resumen(dlg) and "BS" not in _texto_resumen(dlg).replace("DIFERENCIA", "")
    assert "Monto COP" in _columnas_visibles(dlg)


def test_cambiar_de_cuenta_cambia_la_moneda_que_se_muestra(qtbot, db_session, escenario):
    admin, usd, ves = escenario
    dlg = _dialogo(qtbot, db_session, admin, usd)

    dlg.cuenta_combo.setCurrentIndex(dlg.cuenta_combo.findData(ves.id_cuenta))
    assert _visible(dlg, dlg.saldo_final_bs_input) and not _visible(dlg, dlg.saldo_final_input)
    dlg.cuenta_combo.setCurrentIndex(dlg.cuenta_combo.findData(usd.id_cuenta))
    assert _visible(dlg, dlg.saldo_final_input) and not _visible(dlg, dlg.saldo_final_bs_input)


# -- Movimientos manuales -----------------------------------------------------------------------------------------


def test_movimiento_manual_de_cuenta_usd_solo_pide_el_monto_en_dolares(qtbot, avisos):
    dlg = cb.MovimientoManualDialog("abono", moneda="USD")
    qtbot.addWidget(dlg)

    assert dlg.monto_input.isEnabled()
    assert dlg.monto_input.isVisibleTo(dlg)
    assert not dlg.monto_bs_input.isVisibleTo(dlg) and not dlg.tasa_input.isVisibleTo(dlg)

    dlg.referencia_input.setText("Z-2")
    dlg._validar_y_aceptar()
    assert avisos["warning"][0][1] == "El monto USD debe ser mayor a 0."

    dlg.monto_input.set_value(Decimal("25.50"))
    assert dlg.get_data()["monto"] == 25.5 and dlg.get_data()["monto_bs"] == 0.0 and dlg.get_data()["tasa"] == 0.0


def test_movimiento_manual_de_cuenta_en_bolivares_no_muestra_dolares(qtbot, avisos):
    dlg = cb.MovimientoManualDialog("cargo", tasa_inicial=40.0, moneda="VES")
    qtbot.addWidget(dlg)

    assert dlg.monto_bs_input.isVisibleTo(dlg) and dlg.tasa_input.isVisibleTo(dlg)
    assert not dlg.monto_input.isVisibleTo(dlg)
    dlg.monto_bs_input.set_value(Decimal("400.00"))
    dlg.monto_bs_input.valueChanged.emit(dlg.monto_bs_input.get_value())
    assert dlg.get_data() == {
        "monto": 10.0,  # el equivalente en dolares se calcula (400 / 40) aunque no se muestre
        "monto_bs": 400.0,
        "tasa": 40.0,
        "referencia": "",
        "descripcion": "",
    }


def _guardar_manual(dlg, **movimiento):
    dlg._movimientos_manuales.append(
        {"tipo": "abono", "referencia": "M-1", "descripcion": "ajuste", "id_cuenta": dlg.cuenta_combo.currentData()}
        | movimiento
    )
    dlg._guardar_movimientos()


def test_guardar_manual_en_cuenta_usd_no_guarda_bolivares_ni_tasa(qtbot, db_session, escenario, avisos):
    admin, usd, _ves = escenario
    dlg = _dialogo(qtbot, db_session, admin, usd)

    _guardar_manual(dlg, monto=15.0, monto_bs=0.0, tasa=0.0)

    mov = db_session.query(BancoMovimiento).filter_by(id_cuenta=usd.id_cuenta, referencia_movimiento="M-1").one()
    assert mov.monto_movimiento == Decimal("15.00")
    assert mov.monto_bolivares is None and mov.tasa_cambio is None
    assert avisos["critical"] == []


def test_guardar_manual_en_cuenta_en_bolivares_guarda_el_monto_local_y_su_tasa(qtbot, db_session, escenario, avisos):
    admin, _usd, ves = escenario
    dlg = _dialogo(qtbot, db_session, admin, ves)

    _guardar_manual(dlg, monto=10.0, monto_bs=400.0, tasa=40.0)

    mov = db_session.query(BancoMovimiento).filter_by(id_cuenta=ves.id_cuenta, referencia_movimiento="M-1").one()
    assert mov.monto_movimiento == Decimal("10.00")
    assert mov.monto_bolivares == Decimal("400.00") and mov.tasa_cambio == Decimal("40.0000")
    assert avisos["critical"] == []


def test_un_manual_pendiente_suma_en_la_moneda_de_la_cuenta(qtbot, db_session, escenario):
    admin, usd, ves = escenario
    dlg = _dialogo(qtbot, db_session, admin, ves)
    dlg._movimientos_manuales.append(
        {"tipo": "cargo", "monto": 5.0, "monto_bs": 200.0, "tasa": 40.0, "referencia": "M", "descripcion": "x"}
    )

    dlg._calcular_conciliacion()

    assert dlg.lbl_total_salidas.text() == "Total Salidas: BS 200.00"
    dlg.cuenta_combo.setCurrentIndex(dlg.cuenta_combo.findData(usd.id_cuenta))
    # al cambiar de cuenta se descartan los manuales sin guardar: eran de otra cuenta y de otra moneda
    assert dlg._movimientos_manuales == []
    assert dlg.lbl_total_salidas.text() == "Total Salidas: $0.00"
