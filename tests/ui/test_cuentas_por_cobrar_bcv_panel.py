"""Columna SALDO VENCIDO BCV del listado agrupado por cliente de CuentasPorCobrarBCVPanel
(app/ui/cuentas_por_cobrar_bcv_panel.py). Se prueba el armado de la tabla con datos dados,
sin la carga inicial (QTimer + showEvent consultan la base)."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.ui.cuentas_por_cobrar_bcv_panel as bcv


@pytest.fixture()
def panel(qtbot, monkeypatch):
    # Sin el QTimer.singleShot(100, ...) del constructor: correria (ya sin el parche) contra la
    # Session mockeada en medio de otro test y pytest-qt lo reportaria como falla de ese test.
    monkeypatch.setattr(bcv.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(bcv.CuentasPorCobrarBCVPanel, "cargar_cuentas", lambda self: None)
    monkeypatch.setattr(bcv.CuentasPorCobrarBCVPanel, "_cargar_tasa_bcv", lambda self: None)
    panel = bcv.CuentasPorCobrarBCVPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    return panel


def _item(saldo="100.00", vencido="40.00", **extra):
    datos = {
        "id_cliente": 1,
        "nombre_cliente": "Cliente BCV",
        "saldo_pendiente": Decimal(saldo),
        "saldo_favor": Decimal("0.00"),
        "dias_credito": 30,
        "fecha_emision": date(2026, 10, 1),
        "estado": "pendiente",
    }
    if vencido is not None:
        datos["saldo_vencido_bcv"] = Decimal(vencido)
    datos.update(extra)
    return SimpleNamespace(**datos)


def _mostrar(panel, *items):
    panel._mostrar_datos({"items": list(items), "total": len(items), "pagina": 1, "por_pagina": 20})


def test_tabla_tiene_columna_saldo_vencido_bcv_entre_saldo_a_favor_y_dias(panel):
    encabezados = [panel.tabla.horizontalHeaderItem(c).text() for c in range(panel.tabla.columnCount())]

    assert encabezados == [
        "ID Cliente",
        "CLIENTE",
        "SALDO PENDIENTE",
        "SALDO A FAVOR",
        "SALDO VENCIDO BCV",
        "DÍAS",
        "FECHA FACTURA",
        "ESTADO",
    ]


def test_muestra_saldo_vencido_y_mantiene_las_demas_columnas_alineadas(panel):
    _mostrar(panel, _item())

    tabla = panel.tabla
    assert tabla.item(0, 1).text() == "Cliente BCV"
    assert tabla.item(0, 2).text() == "$100.00"
    assert tabla.item(0, 4).text() == "$40.00"
    assert tabla.item(0, 5).text() == "30"
    assert tabla.item(0, 6).text() == "01/10/2026"
    assert tabla.cellWidget(0, 7) is not None


def test_con_tasa_bcv_el_saldo_vencido_tambien_se_muestra_en_bolivares(panel):
    panel._tasa_bcv = 40.0

    _mostrar(panel, _item(vencido="40.00"))

    assert panel.tabla.item(0, 4).text() == "$40.00 / Bs 1,600.00"


def test_item_sin_saldo_vencido_bcv_se_muestra_en_cero(panel):
    _mostrar(panel, _item(vencido=None))

    assert panel.tabla.item(0, 4).text() == "$0.00"


def test_varios_clientes_cada_uno_con_su_saldo_vencido(panel):
    _mostrar(
        panel,
        _item(id_cliente=1, nombre_cliente="Uno", vencido="40.00"),
        _item(id_cliente=2, nombre_cliente="Dos", vencido="0.00"),
    )

    assert [panel.tabla.item(f, 4).text() for f in range(2)] == ["$40.00", "$0.00"]
    assert [panel.tabla.item(f, 1).text() for f in range(2)] == ["Uno", "Dos"]


# -- Texto cortado: badge de estado y titulo del abono general ---------------------------


from PySide6.QtWidgets import QHeaderView, QLabel  # noqa: E402

from app.ui.styles import ANCHO_COLUMNA_ESTADO, EstadoBadge  # noqa: E402


def _ancho_necesario_badge(texto: str) -> int:
    """Ancho que el badge necesita para mostrar `texto` completo (label + margenes del layout)."""
    badge = EstadoBadge(texto, "#F59E0B")
    return badge.sizeHint().width()


@pytest.mark.parametrize("estado", ["pendiente", "parcial", "vencida", "pagada"])
def test_la_columna_estado_alcanza_para_el_texto_completo_del_badge(estado):
    assert ANCHO_COLUMNA_ESTADO >= _ancho_necesario_badge(estado)


def _cuenta_bcv(id_cuenta, factura, estado="pendiente", saldo="10.00"):
    return SimpleNamespace(
        id_cuenta_por_cobrar=id_cuenta,
        factura=SimpleNamespace(numero_factura=factura),
        porcentaje=Decimal("10"),
        saldo_pendiente=Decimal(saldo),
        saldo_favor=Decimal("0.00"),
        fecha_emision=date(2026, 10, 17),
        fecha_vencimiento=None,
        estado=estado,
    )


def _dialogo_detalle(qtbot, cuentas):
    cliente = SimpleNamespace(id_cliente=1, nombre_razon_social="Distribuciones del Sur Demo, C.A.")
    dialogo = bcv.DetalleCuentasBCVDialog(MagicMock(), cliente, cuentas, 871.36, 1)
    qtbot.addWidget(dialogo)
    return dialogo


def test_detalle_bcv_columna_estado_tiene_ancho_fijo_para_el_badge(qtbot):
    dialogo = _dialogo_detalle(qtbot, [_cuenta_bcv(1, "FV-000018"), _cuenta_bcv(2, "FV-000012", estado="parcial")])

    tabla = dialogo.tabla
    assert tabla.horizontalHeader().sectionResizeMode(6) == QHeaderView.ResizeMode.Fixed
    assert tabla.columnWidth(6) >= _ancho_necesario_badge("pendiente")
    assert tabla.cellWidget(0, 6) is not None
    assert tabla.cellWidget(1, 6) is not None


def test_tabla_principal_bcv_columna_estado_tiene_ancho_fijo_para_el_badge(panel):
    tabla = panel.tabla

    assert tabla.horizontalHeader().sectionResizeMode(7) == QHeaderView.ResizeMode.Fixed
    assert tabla.columnWidth(7) >= _ancho_necesario_badge("pendiente")


def test_titulo_del_abono_general_pasa_a_otra_linea_en_vez_de_cortarse(qtbot, monkeypatch):
    monkeypatch.setattr(bcv.AbonoGeneralBCVDialog, "_cargar_origenes", lambda self: None)
    monkeypatch.setattr(bcv.AbonoGeneralBCVDialog, "_cargar_tasas", lambda self: None)
    cliente = SimpleNamespace(id_cliente=1, nombre_razon_social="Distribuciones del Sur Demo, C.A.")
    sesion = MagicMock()
    sesion.query.return_value.join.return_value.filter.return_value.first.return_value = None
    dialogo = bcv.AbonoGeneralBCVDialog(lambda: sesion, cliente, 1, 871.36)
    qtbot.addWidget(dialogo)

    titulos = [
        lbl
        for lbl in dialogo.findChildren(QLabel)
        if lbl.text() == "Abono General BCV - Distribuciones del Sur Demo, C.A."
    ]

    assert len(titulos) == 1
    assert titulos[0].wordWrap()
