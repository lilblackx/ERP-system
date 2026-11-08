"""Panel de cuentas bancarias: la columna MONEDA (listado y exportacion) y que el resto de las columnas sigan en su
lugar tras insertarla."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.ui.cuentas_bancarias_panel as cb


def _cuenta(id_cuenta, moneda, saldo="100.00", saldo_bs="0.00", estado="ACTIVO", saldo_cop="0.00"):
    return SimpleNamespace(
        id_cuenta=id_cuenta,
        banco=SimpleNamespace(nombre_banco=f"Banco {id_cuenta}"),
        numero_cuenta=f"0102000000{id_cuenta:04d}",
        tipo_cuenta_banco="CORRIENTE",
        moneda=moneda,
        nombre_titular="Distribuidora DJ",
        identificacion_titular="J-1",
        saldo_total_banco=Decimal(saldo),
        saldo_total_banco_bs=Decimal(saldo_bs),
        saldo_total_banco_cop=Decimal(saldo_cop),
        estado_cuenta=estado,
    )


@pytest.fixture()
def panel(qtbot, monkeypatch):
    monkeypatch.setattr(cb.CuentasBancariasPanel, "_cargar_bancos", lambda self: None)
    monkeypatch.setattr(cb.CuentasBancariasPanel, "_cargar_datos", lambda self, *a, **k: None)
    panel = cb.CuentasBancariasPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    panel._refresh_timer.stop()
    return panel


def test_la_columna_moneda_esta_despues_del_tipo():
    assert cb.COLS_VISIBLES.index("MONEDA") == cb.COLS_VISIBLES.index("TIPO") + 1


def test_el_listado_muestra_la_moneda_de_cada_cuenta_y_las_demas_columnas_siguen_en_su_lugar(panel):
    cuentas = [
        _cuenta(1, "VES", saldo="0.00", saldo_bs="5000.00"),
        _cuenta(2, "USD", saldo="250.50"),
        _cuenta(3, "COP"),
    ]

    panel._mostrar_cuentas({"items": cuentas, "total": 3, "pagina": 1, "total_paginas": 1})

    tabla = panel.table
    columna = {nombre: i for i, nombre in enumerate(cb.COLS_VISIBLES)}
    assert [tabla.item(f, columna["MONEDA"]).text() for f in range(3)] == ["VES", "USD", "COP"]
    assert tabla.item(1, columna["TITULAR"]).text() == "Distribuidora DJ"
    assert tabla.item(1, columna["SALDO"]).text() == "$250.50"
    assert tabla.item(0, columna["MONTO EN BS"]).text() == "5,000.00"
    assert tabla.cellWidget(1, columna["ESTADO"]) is not None
    assert tabla.item(1, 0).text() == "2"  # el id sigue en la columna oculta 0


def test_una_cuenta_sin_moneda_se_muestra_como_bolivares(panel):
    panel._mostrar_cuentas({"items": [_cuenta(1, None)], "total": 1, "pagina": 1, "total_paginas": 1})

    assert panel.table.item(0, cb.COLS_VISIBLES.index("MONEDA")).text() == "VES"


def test_la_exportacion_incluye_la_moneda_en_su_columna(monkeypatch):
    monkeypatch.setattr(
        cb.CuentaBancariaService,
        "listar",
        staticmethod(lambda *a, **k: {"items": [_cuenta(1, "USD", saldo="75.00")]}),
    )

    filas = cb._filas_cuentas_bancarias_query(MagicMock(), None, None, None, 1)

    assert len(filas) == 1 and len(filas[0]) == len(cb.COLS_VISIBLES)
    assert filas[0][cb.COLS_VISIBLES.index("MONEDA")] == "USD"
    assert filas[0][cb.COLS_VISIBLES.index("SALDO")] == 75.0


# -- Filtro por moneda: las columnas de saldo aparecen segun la moneda --------------------------------------------


def _columna(nombre):
    return cb.COLS_VISIBLES.index(nombre)


def _elegir_moneda(panel, moneda):
    panel.moneda_combo.setCurrentIndex(panel.moneda_combo.findData(moneda))


def test_el_filtro_de_moneda_ofrece_todas_y_las_tres_monedas(panel):
    assert [panel.moneda_combo.itemData(i) for i in range(panel.moneda_combo.count())] == [None, "VES", "USD", "COP"]


COLUMNAS_DE_SALDO = ("SALDO", "MONTO EN BS", "SALDO COP")


def _saldos_visibles(panel):
    return [nombre for nombre in COLUMNAS_DE_SALDO if not panel.table.isColumnHidden(_columna(nombre))]


def test_con_todas_las_monedas_se_ven_las_tres_columnas_de_saldo(panel):
    assert _saldos_visibles(panel) == ["SALDO", "MONTO EN BS", "SALDO COP"]


def test_cada_moneda_muestra_solo_su_columna_de_saldo(panel):
    esperado = {"VES": ["MONTO EN BS"], "USD": ["SALDO"], "COP": ["SALDO COP"]}

    visibles = {}
    for moneda in esperado:
        _elegir_moneda(panel, moneda)
        visibles[moneda] = _saldos_visibles(panel)

    assert visibles == esperado


def test_volver_a_todas_las_monedas_restaura_las_tres_columnas(panel):
    _elegir_moneda(panel, "COP")
    _elegir_moneda(panel, "VES")
    _elegir_moneda(panel, None)

    assert _saldos_visibles(panel) == ["SALDO", "MONTO EN BS", "SALDO COP"]


def test_las_otras_columnas_nunca_se_ocultan(panel):
    for moneda in ("VES", "USD", "COP"):
        _elegir_moneda(panel, moneda)
        ocultas = [nombre for nombre in cb.COLS_VISIBLES if panel.table.isColumnHidden(_columna(nombre))]
        assert set(ocultas) <= set(COLUMNAS_DE_SALDO), moneda


def test_el_listado_muestra_el_saldo_en_pesos_de_una_cuenta_cop(panel):
    cuenta = _cuenta(4, "COP", saldo="0.00", saldo_cop="1500000.50")

    panel._mostrar_cuentas({"items": [cuenta], "total": 1, "pagina": 1, "total_paginas": 1})

    assert panel.table.item(0, _columna("SALDO COP")).text() == "1,500,000.50"
    assert panel.table.cellWidget(0, _columna("ESTADO")) is not None


def test_cambiar_la_moneda_vuelve_a_la_primera_pagina_y_pide_ese_filtro(panel, monkeypatch):
    pedidos = []
    monkeypatch.setattr(
        cb.CuentasBancariasPanel, "_cargar_datos", lambda self, *a, **k: pedidos.append(self._filtro_moneda)
    )
    panel.pagina_actual = 3

    _elegir_moneda(panel, "USD")

    assert panel.pagina_actual == 1
    assert pedidos == ["USD"]


def test_la_exportacion_respeta_el_filtro_de_moneda(monkeypatch):
    recibidos = {}

    def listar(session, **kwargs):
        recibidos.update(kwargs)
        return {"items": [_cuenta(1, "USD", saldo="75.00", saldo_bs="9.00")]}

    monkeypatch.setattr(cb.CuentaBancariaService, "listar", staticmethod(listar))

    filas = cb._filas_cuentas_bancarias_query(MagicMock(), None, None, None, 1, "USD")

    assert recibidos["moneda"] == "USD"
    assert len(filas) == 1


@pytest.mark.parametrize(
    ("moneda", "visible"),
    [("VES", "MONTO EN BS"), ("USD", "SALDO"), ("COP", "SALDO COP"), (None, None)],
)
def test_las_columnas_exportadas_coinciden_con_las_visibles(moneda, visible):
    nombres = [cb.COLS_VISIBLES[i] for i in cb._indices_columnas_visibles(moneda)]

    if visible:
        assert [n for n in COLUMNAS_DE_SALDO if n in nombres] == [visible]
        assert len(nombres) == len(cb.COLS_VISIBLES) - 2
    else:
        assert nombres == cb.COLS_VISIBLES


# -- Confirmacion al cambiar la moneda de una cuenta con historial ----------------------------------------------


@pytest.mark.parametrize(("respuesta", "esperado"), [("Yes", True), ("No", False)])
def test_la_confirmacion_del_cambio_de_moneda_devuelve_lo_que_elige_el_usuario(panel, monkeypatch, respuesta, esperado):
    mostrados = []

    def question(parent, titulo, texto):
        mostrados.append((titulo, texto))
        return getattr(cb.QMessageBox.StandardButton, respuesta)

    monkeypatch.setattr(cb.MessageBox, "question", staticmethod(question))
    cuenta = _cuenta(7, "VES")

    resultado = panel._confirmar_cambio_de_moneda(
        cuenta, "USD", {"movimientos": 12, "por_metodo": {"zelle": 5, "transferencia": 7}}
    )

    assert resultado is esperado
    titulo, texto = mostrados[0]
    assert "moneda" in titulo.lower()
    assert "12 movimiento" in texto and "5 por Zelle" in texto and "7 por transferencia" in texto
    assert "bolívares (VES)" in texto and "dólares (USD)" in texto
    assert "auditoría" in texto and "no modifica el historial" in texto


def test_la_confirmacion_sin_pagos_registrados_no_inventa_el_detalle(panel, monkeypatch):
    mostrados = []
    monkeypatch.setattr(
        cb.MessageBox,
        "question",
        staticmethod(lambda parent, titulo, texto: mostrados.append(texto) or cb.QMessageBox.StandardButton.No),
    )

    panel._confirmar_cambio_de_moneda(_cuenta(7, "VES"), "USD", {"movimientos": 2, "por_metodo": {}})

    assert "Pagos registrados" not in mostrados[0]


class _DialogoFalso:
    """Reemplaza al formulario: acepta de inmediato y devuelve los datos que se le indiquen."""

    datos: dict = {}

    def __init__(self, session, cuenta=None, parent=None, precargado=None):
        pass

    def exec(self):
        return cb.QDialog.DialogCode.Accepted

    def get_data(self):
        return dict(_DialogoFalso.datos)


def _editar_con(panel, monkeypatch, cuenta, datos, resumen, confirma):
    """Ejecuta _on_editar con la fila de `cuenta` seleccionada; devuelve (llamadas a actualizar, confirmaciones)."""
    llamadas, confirmaciones = [], []
    sesion = MagicMock()
    sesion.query.return_value.filter.return_value.first.return_value = cuenta
    panel.session_factory = lambda: sesion
    panel._exigir_permiso = lambda *a, **k: True
    panel._cargar_datos = lambda *a, **k: None
    panel._mostrar_cuentas({"items": [cuenta], "total": 1, "pagina": 1, "total_paginas": 1})
    panel.table.setCurrentCell(0, 1)
    _DialogoFalso.datos = datos
    monkeypatch.setattr(cb, "CuentaBancariaFormDialog", _DialogoFalso)
    monkeypatch.setattr(cb.CuentaBancariaService, "resumen_uso", staticmethod(lambda *a, **k: resumen))
    monkeypatch.setattr(cb.CuentaBancariaService, "actualizar", staticmethod(lambda *a, **k: llamadas.append(k)))
    monkeypatch.setattr(
        panel,
        "_confirmar_cambio_de_moneda",
        lambda *a: confirmaciones.append(a) or confirma,
    )
    panel._on_editar()
    return llamadas, confirmaciones


def test_editar_cambiando_la_moneda_de_una_cuenta_con_historial_pide_confirmar_y_lo_envia(panel, monkeypatch):
    cuenta = _cuenta(7, "VES")

    llamadas, confirmaciones = _editar_con(
        panel, monkeypatch, cuenta, {"moneda": "USD"}, {"movimientos": 4, "por_metodo": {"zelle": 4}}, confirma=True
    )

    assert len(confirmaciones) == 1
    assert llamadas[0]["confirmar_cambio_moneda"] is True and llamadas[0]["moneda"] == "USD"


def test_si_no_se_confirma_el_cambio_de_moneda_no_se_guarda_nada(panel, monkeypatch):
    cuenta = _cuenta(7, "VES")

    llamadas, confirmaciones = _editar_con(
        panel, monkeypatch, cuenta, {"moneda": "USD"}, {"movimientos": 4, "por_metodo": {}}, confirma=False
    )

    assert len(confirmaciones) == 1
    assert llamadas == []


def test_cambiar_la_moneda_de_una_cuenta_sin_historial_no_pide_confirmacion(panel, monkeypatch):
    cuenta = _cuenta(7, "VES")

    llamadas, confirmaciones = _editar_con(
        panel, monkeypatch, cuenta, {"moneda": "USD"}, {"movimientos": 0, "por_metodo": {}}, confirma=False
    )

    assert confirmaciones == []
    assert llamadas[0]["confirmar_cambio_moneda"] is False


def test_editar_sin_cambiar_la_moneda_no_consulta_el_uso_ni_pide_confirmacion(panel, monkeypatch):
    cuenta = _cuenta(7, "USD")

    llamadas, confirmaciones = _editar_con(
        panel,
        monkeypatch,
        cuenta,
        {"moneda": "USD", "nombre_titular": "Otro"},
        {"movimientos": 9, "por_metodo": {}},
        True,
    )

    assert confirmaciones == []
    assert llamadas[0]["confirmar_cambio_moneda"] is False and llamadas[0]["nombre_titular"] == "Otro"


# -- Movimientos de una cuenta: el monto local es en pesos para una cuenta COP ---------------------------------


@pytest.mark.parametrize(("moneda", "unidad"), [("COP", "COP"), ("VES", "BS"), ("USD", "BS")])
def test_el_dialogo_de_movimientos_rotula_el_monto_local_segun_la_moneda_de_la_cuenta(
    qtbot, monkeypatch, moneda, unidad
):
    import app.ui.movimientos_cuenta_dialog as mc

    monkeypatch.setattr(
        mc.BancoMovimientoService,
        "listar_paginado",
        staticmethod(
            lambda *a, **k: {
                "items": [],
                "total": 0,
                "pagina": 1,
                "total_paginas": 1,
                "totales": {"entradas": 0.0, "salidas": 0.0, "entradas_bs": 1500.0, "salidas_bs": 250.0},
            }
        ),
    )
    cuenta = SimpleNamespace(
        id_cuenta=1,
        numero_cuenta="0102000000001",
        moneda=moneda,
        banco=SimpleNamespace(nombre_banco="Banco"),
        saldo_total_banco=Decimal("0"),
    )
    dialogo = mc.MovimientosCuentaDialog(MagicMock(), cuenta, SimpleNamespace(id_usuario=1))
    qtbot.addWidget(dialogo)

    assert dialogo.table.horizontalHeaderItem(3).text() == f"Monto {unidad}"
    assert dialogo.lbl_total_entradas_bs.text() == f"Total Entradas {unidad}: 1,500.00"
    assert dialogo.lbl_total_salidas_bs.text() == f"Total Salidas {unidad}: 250.00"
