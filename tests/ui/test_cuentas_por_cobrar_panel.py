"""Tests de PagoCobroDialog (app/ui/cuentas_por_cobrar_panel.py) tras migrar
monto_input/bolivares_input/tasa_input de QDoubleSpinBox a NumericLineEdit:
- monto_input: NumericFieldType.AMOUNT, min_value=0.01, prefix "$ " (min original), con
  el saldo_pendiente de la cuenta como valor inicial (no 0 -- ver set_value tras
  construir el campo).
- bolivares_input: NumericFieldType.AMOUNT, max_value=999999999999 (rango original).
- tasa_input: NumericFieldType.RATE (0.01-999999, igual al rango original).

Se prueba el dialogo completo, no el panel: CuentasPorCobrarPanel dispara un
QueryWorker en un hilo aparte al construirse (QTimer.singleShot(100,
self.cargar_cuentas)), que no aporta cobertura sobre estos 3 campos y complica el test
sin necesidad. PagoCobroDialog en cambio solo necesita una Session mockeada -- sus
_cargar_origenes()/_cargar_tasas() ya manejan tanto PermisoDenegadoError (id_usuario=None
cae ahi, ver require_permiso en app/services/permisos.py) como cualquier excepcion de la
consulta de tasas, pero *no* validan el tipo de lo que devuelve `session.query(...).first()`
-- con un MagicMock() liso eso devuelve otro MagicMock "verdadero" que revienta el
formateo de tasas (`f"{...:,.2f}"`), asi que hay que fijar ese `.first()` a None a mano.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.ui.cuentas_por_cobrar_panel as cxc
from app.ui.cuentas_por_cobrar_panel import PagoCobroDialog


def _dar_foco(qtbot, campo):
    campo.window().show()
    qtbot.waitExposed(campo.window(), timeout=15000)
    campo.setFocus()
    qtbot.waitUntil(campo.hasFocus, timeout=15000)


def _escribir_y_perder_foco(qtbot, campo, texto):
    _dar_foco(qtbot, campo)
    campo.selectAll()
    qtbot.keyClicks(campo, texto)
    campo.clearFocus()


def _crear_sesion() -> MagicMock:
    session = MagicMock()
    # _cargar_tasas() hace session.query(ControlDeTasa).order_by(...).first(): sin fijar
    # esto a None devuelve un MagicMock "verdadero" que revienta el f"{...:,.2f}" de mas
    # abajo en ese metodo.
    session.query.return_value.order_by.return_value.first.return_value = None
    return session


def _crear_cuenta(saldo=Decimal("1250.75")) -> SimpleNamespace:
    factura = SimpleNamespace(
        numero_factura="F-001",
        cliente=SimpleNamespace(nombre_razon_social="Cliente Uno"),
    )
    return SimpleNamespace(
        id_cuenta_por_cobrar=1,
        factura=factura,
        saldo_pendiente=saldo,
        saldo_favor=Decimal("0.00"),
    )


def test_monto_input_arranca_en_saldo_pendiente(qtbot):
    dialogo = PagoCobroDialog(_crear_sesion(), None, _crear_cuenta(Decimal("1250.75")))
    qtbot.addWidget(dialogo)
    dialogo.show()
    qtbot.waitExposed(dialogo, timeout=15000)
    assert dialogo.monto_input.get_value() == Decimal("1250.75")
    assert dialogo.monto_input.text() == "$ 1.250,75"


def test_monto_input_respeta_minimo_de_0_01(qtbot):
    dialogo = PagoCobroDialog(_crear_sesion(), None, _crear_cuenta())
    qtbot.addWidget(dialogo)
    dialogo.show()
    qtbot.waitExposed(dialogo, timeout=15000)
    _escribir_y_perder_foco(qtbot, dialogo.monto_input, "0")
    assert dialogo.monto_input.get_value() == Decimal("0.01")


def _mostrar_campos_bolivares(dialogo, qtbot) -> None:
    # bolivares_input/tasa_input viven en campos_bolivares_widget, oculto salvo que el
    # metodo de pago sea "transferencia" (_toggle_campos_bolivares) -- un campo oculto
    # nunca puede recibir foco, hay que seleccionar ese metodo primero.
    idx = dialogo.metodo_combo.findData("transferencia")
    assert idx >= 0
    dialogo.metodo_combo.setCurrentIndex(idx)
    # Also need to set a bank origin to show bolivares fields
    dialogo._cuentas_activas = [
        SimpleNamespace(
            id_cuenta=1,
            banco=SimpleNamespace(nombre_banco="Banco Test"),
            numero_cuenta="1234567890123456",
        )
    ]
    dialogo._toggle_origen()
    # Select the first bank account
    dialogo.origen_combo.setCurrentIndex(0)

    # Wait for the bolivares fields to be visible and enabled
    qtbot.waitUntil(
        lambda: dialogo.bolivares_input is not None and dialogo.bolivares_input.isEnabled(),
        timeout=15000,
    )
    qtbot.wait(50)  # Small delay to ensure UI is ready


def test_bolivares_input_arranca_en_cero_y_admite_rango_amplio(qtbot):
    dialogo = PagoCobroDialog(_crear_sesion(), None, _crear_cuenta())
    qtbot.addWidget(dialogo)
    dialogo.show()
    qtbot.waitExposed(dialogo, timeout=15000)

    dialogo._cuentas_activas = [
        SimpleNamespace(
            id_cuenta=1,
            banco=SimpleNamespace(nombre_banco="Banco Test"),
            numero_cuenta="1234567890123456",
        )
    ]
    dialogo._toggle_origen()
    dialogo.origen_combo.setCurrentIndex(0)

    # Wait for the widget to be fully initialized and enabled
    qtbot.waitUntil(
        lambda: dialogo.bolivares_input is not None and dialogo.bolivares_input.isEnabled(),
        timeout=15000,
    )
    qtbot.wait(50)  # Small delay to ensure UI is ready

    assert dialogo.bolivares_input.get_value() == Decimal("0")
    _escribir_y_perder_foco(qtbot, dialogo.bolivares_input, "999999999999")
    assert dialogo.bolivares_input.get_value() == Decimal("999999999999.00")


def test_tasa_input_es_de_tipo_rate(qtbot):
    dialogo = PagoCobroDialog(_crear_sesion(), None, _crear_cuenta())
    qtbot.addWidget(dialogo)
    dialogo.show()
    qtbot.waitExposed(dialogo, timeout=15000)

    dialogo._cuentas_activas = [
        SimpleNamespace(
            id_cuenta=1,
            banco=SimpleNamespace(nombre_banco="Banco Test"),
            numero_cuenta="1234567890123456",
        )
    ]
    dialogo._toggle_origen()
    dialogo.origen_combo.setCurrentIndex(0)

    # Wait for the widget to be fully initialized and enabled
    qtbot.waitUntil(
        lambda: dialogo.tasa_input is not None and dialogo.tasa_input.isEnabled(),
        timeout=15000,
    )
    qtbot.wait(50)  # Small delay to ensure UI is ready
    _escribir_y_perder_foco(qtbot, dialogo.tasa_input, "0")
    # RATE tiene min_value=0.01 por defecto -- un 0 tecleado se ajusta al piso.
    assert dialogo.tasa_input.get_value() == Decimal("0.01")


def test_calcular_monto_usd_divide_bolivares_entre_tasa(qtbot):
    dialogo = PagoCobroDialog(_crear_sesion(), None, _crear_cuenta())
    qtbot.addWidget(dialogo)
    dialogo.show()
    qtbot.waitExposed(dialogo, timeout=15000)
    _mostrar_campos_bolivares(dialogo, qtbot)  # tambien fuerza metodo "transferencia"

    _escribir_y_perder_foco(qtbot, dialogo.tasa_input, "50")
    _escribir_y_perder_foco(qtbot, dialogo.bolivares_input, "500")

    # 500 bolivares / 50 tasa = 10 USD
    assert dialogo.monto_input.get_value() == Decimal("10")


def test_validar_y_aceptar_pasa_decimal_al_servicio(qtbot, monkeypatch):
    dialogo = PagoCobroDialog(_crear_sesion(), 1, _crear_cuenta(Decimal("300")))
    qtbot.addWidget(dialogo)
    dialogo.show()
    qtbot.waitExposed(dialogo, timeout=15000)
    dialogo._cajas_abiertas = [SimpleNamespace(id_caja=1, nombre_caja="Caja 1", fecha_apertura=1, fecha_cierre=None)]
    dialogo._toggle_origen()
    dialogo.origen_combo.setCurrentIndex(0)

    llamada = {}

    def fake_registrar(*args, **kwargs):
        llamada.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(
        "app.ui.cuentas_por_cobrar_panel.PagoService.registrar_pago_cobro",
        fake_registrar,
    )
    monkeypatch.setattr(
        "app.ui.cuentas_por_cobrar_panel.reintentar_en_deadlock",
        lambda fn: fn(),
    )

    dialogo._validar_y_aceptar()

    assert llamada["monto"] == Decimal("300")
    assert isinstance(llamada["monto"], Decimal)


def _capturar_cobro(monkeypatch):
    llamada = {}

    def fake_registrar(*args, **kwargs):
        llamada.update(kwargs)
        return MagicMock()

    monkeypatch.setattr("app.ui.cuentas_por_cobrar_panel.PagoService.registrar_pago_cobro", fake_registrar)
    monkeypatch.setattr("app.ui.cuentas_por_cobrar_panel.reintentar_en_deadlock", lambda fn: fn())
    return llamada


def test_cobro_en_bolivares_se_envia_con_moneda_ves(qtbot, monkeypatch):
    """Bs 500 a tasa 50 = $10. `monto` va en USD (lo que descuenta el saldo) y el monto en Bs
    se guarda como `monto_moneda_origen`: su moneda tiene que ser VES. Antes se mandaba
    moneda='USD' con el monto en Bs, y la factura mostraba '500 USD' para un cobro de $10."""
    dialogo = PagoCobroDialog(_crear_sesion(), 1, _crear_cuenta(Decimal("300")))
    qtbot.addWidget(dialogo)
    dialogo.show()
    qtbot.waitExposed(dialogo, timeout=15000)
    _mostrar_campos_bolivares(dialogo, qtbot)
    _escribir_y_perder_foco(qtbot, dialogo.tasa_input, "50")
    _escribir_y_perder_foco(qtbot, dialogo.bolivares_input, "500")
    llamada = _capturar_cobro(monkeypatch)

    dialogo._validar_y_aceptar()

    assert llamada["monto"] == Decimal("10")
    assert llamada["moneda"] == "VES"
    assert llamada["monto_moneda_origen"] == Decimal("500")
    assert llamada["monto_bolivares"] == Decimal("500")
    assert llamada["tasa_cambio"] == Decimal("50")


def test_cobro_en_efectivo_se_envia_en_usd(qtbot, monkeypatch):
    dialogo = PagoCobroDialog(_crear_sesion(), 1, _crear_cuenta(Decimal("300")))
    qtbot.addWidget(dialogo)
    dialogo.show()
    qtbot.waitExposed(dialogo, timeout=15000)
    dialogo._cajas_abiertas = [SimpleNamespace(id_caja=1, nombre_caja="Caja 1", fecha_apertura=1, fecha_cierre=None)]
    dialogo._toggle_origen()
    dialogo.origen_combo.setCurrentIndex(0)
    llamada = _capturar_cobro(monkeypatch)

    dialogo._validar_y_aceptar()

    assert llamada["moneda"] == "USD"
    assert llamada["monto_moneda_origen"] is None


# -- Saldo vencido en el listado por cliente --------------------------------------------


@pytest.fixture()
def panel_cxc(qtbot, monkeypatch):
    """CuentasPorCobrarPanel sin la carga inicial (QTimer + showEvent llaman cargar_cuentas,
    que hace consultas reales): aca solo se prueba el armado de la tabla con datos dados."""
    # Sin el QTimer.singleShot(100, ...) del constructor: correria (ya sin el parche) contra la
    # Session mockeada en medio de otro test y pytest-qt lo reportaria como falla de ese test.
    monkeypatch.setattr(cxc.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(cxc.CuentasPorCobrarPanel, "cargar_cuentas", lambda self: None)
    panel = cxc.CuentasPorCobrarPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    return panel


def _cliente_data(saldo_total, saldo_vencido, id_cliente=1, nombre="Cliente Uno"):
    return {
        "cliente": SimpleNamespace(id_cliente=id_cliente, nombre_razon_social=nombre),
        "saldo_total": Decimal(saldo_total),
        "saldo_favor": Decimal("0.00"),
        "saldo_vencido": Decimal(saldo_vencido),
        "cuentas": [],
        "fecha_emision_mas_antigua_pendiente": None,
        "dias_transcurridos": 0,
    }


def _encabezados(tabla):
    return [tabla.horizontalHeaderItem(c).text() for c in range(tabla.columnCount())]


def test_tabla_de_clientes_tiene_columna_saldo_vencido_entre_saldo_a_favor_y_dias(panel_cxc):
    assert _encabezados(panel_cxc.tabla) == [
        "ID",
        "Cliente",
        "Saldo Pendiente",
        "Saldo a Favor",
        "Saldo Vencido",
        "Días",
        "Fecha Factura",
        "Estado",
    ]


def test_poblar_tabla_muestra_saldo_vencido_y_deja_el_resto_de_columnas_en_su_lugar(panel_cxc):
    datos = _cliente_data("300.00", "120.50")
    datos["fecha_emision_mas_antigua_pendiente"] = date(2026, 10, 1)
    datos["dias_transcurridos"] = 16

    panel_cxc._poblar_tabla({"items": [datos], "total": 1, "pagina": 1, "por_pagina": 20})

    tabla = panel_cxc.tabla
    assert tabla.item(0, 1).text() == "Cliente Uno"
    assert tabla.item(0, 2).text() == "$300.00"
    assert tabla.item(0, 4).text() == "$120.50"
    assert tabla.item(0, 5).text() == "16"
    assert tabla.item(0, 6).text() == "01/10/2026"
    assert tabla.cellWidget(0, 7) is not None


def test_saldo_vencido_positivo_va_en_color_de_peligro_y_cero_en_color_atenuado(panel_cxc):
    panel_cxc._poblar_tabla(
        {
            "items": [_cliente_data("300.00", "120.50", 1), _cliente_data("50.00", "0.00", 2, "Cliente Dos")],
            "total": 2,
            "pagina": 1,
            "por_pagina": 20,
        }
    )

    vencido, sin_vencido = panel_cxc.tabla.item(0, 4), panel_cxc.tabla.item(1, 4)
    assert sin_vencido.text() == "$0.00"
    assert vencido.foreground().color() != sin_vencido.foreground().color()


def test_poblar_tabla_tolera_cliente_sin_clave_saldo_vencido(panel_cxc):
    datos = _cliente_data("300.00", "0.00")
    del datos["saldo_vencido"]

    panel_cxc._poblar_tabla({"items": [datos], "total": 1, "pagina": 1, "por_pagina": 20})

    assert panel_cxc.tabla.item(0, 4).text() == "$0.00"


# -- DetalleClienteDialog: ver todas, paginacion y doble clic -----------------------------


def _cuenta(id_cuenta, estado, saldo="10.00", vence_en=5, numero=None):
    return SimpleNamespace(
        id_cuenta_por_cobrar=id_cuenta,
        estado=estado,
        saldo_pendiente=Decimal(saldo),
        fecha_vencimiento=date.today() + timedelta(days=vence_en),
        factura=SimpleNamespace(
            numero_factura=numero or f"F-{id_cuenta:03d}",
            fecha_emision=datetime.now() - timedelta(days=3),
        ),
    )


def _detalle(qtbot, cuentas, tasa_paralelo=None):
    session = MagicMock()
    session.query.return_value.join.return_value.filter.return_value.first.return_value = None
    cliente = SimpleNamespace(id_cliente=1, nombre_razon_social="Cliente Uno")
    dialogo = cxc.DetalleClienteDialog(session, cliente, cuentas, tasa_paralelo, 1)
    qtbot.addWidget(dialogo)
    return dialogo


def _facturas_visibles(dialogo):
    return [dialogo.tabla.item(f, 1).text() for f in range(dialogo.tabla.rowCount())]


def test_detalle_por_defecto_oculta_las_cuentas_pagadas(qtbot):
    cuentas = [_cuenta(1, "pendiente"), _cuenta(2, "pagada"), _cuenta(3, "parcial"), _cuenta(4, "vencida")]

    dialogo = _detalle(qtbot, cuentas)

    assert _facturas_visibles(dialogo) == ["F-001", "F-003", "F-004"]


def test_detalle_ver_todas_las_facturas_incluye_pagadas_y_cambia_el_titulo(qtbot):
    dialogo = _detalle(qtbot, [_cuenta(1, "pendiente"), _cuenta(2, "pagada")])

    dialogo.chk_ver_todas.setChecked(True)

    assert _facturas_visibles(dialogo) == ["F-001", "F-002"]
    assert dialogo.windowTitle().endswith("(Todas las facturas)")

    dialogo.chk_ver_todas.setChecked(False)

    assert _facturas_visibles(dialogo) == ["F-001"]
    assert "(Todas las facturas)" not in dialogo.windowTitle()


def test_detalle_pagina_de_a_20_facturas_y_navega(qtbot):
    dialogo = _detalle(qtbot, [_cuenta(i, "pendiente") for i in range(1, 46)])

    assert dialogo.tabla.rowCount() == 20
    assert dialogo.lbl_paginacion.text() == "Página 1 de 3"
    assert not dialogo.btn_anterior.isEnabled()
    assert dialogo.btn_siguiente.isEnabled()

    dialogo.btn_siguiente.click()
    dialogo.btn_siguiente.click()

    assert dialogo.tabla.rowCount() == 5
    assert dialogo.lbl_paginacion.text() == "Página 3 de 3"
    assert dialogo.btn_anterior.isEnabled()
    assert not dialogo.btn_siguiente.isEnabled()
    assert _facturas_visibles(dialogo)[0] == "F-041"

    dialogo.btn_anterior.click()

    assert dialogo.lbl_paginacion.text() == "Página 2 de 3"


def test_detalle_al_marcar_ver_todas_vuelve_a_la_primera_pagina(qtbot):
    dialogo = _detalle(qtbot, [_cuenta(i, "pendiente") for i in range(1, 46)])
    dialogo.btn_siguiente.click()
    assert dialogo.pagina_actual == 1

    dialogo.chk_ver_todas.setChecked(True)

    assert dialogo.pagina_actual == 0
    assert dialogo.lbl_paginacion.text() == "Página 1 de 3"


def test_detalle_sin_facturas_pendientes_muestra_pagina_1_de_1(qtbot):
    dialogo = _detalle(qtbot, [_cuenta(1, "pagada")])

    assert dialogo.tabla.rowCount() == 0
    assert dialogo.lbl_paginacion.text() == "Página 1 de 1"
    assert not dialogo.btn_anterior.isEnabled()
    assert not dialogo.btn_siguiente.isEnabled()


def test_detalle_doble_clic_en_una_factura_abre_el_cobro_de_esa_cuenta(qtbot, monkeypatch):
    dialogo = _detalle(qtbot, [_cuenta(7, "pendiente"), _cuenta(8, "pendiente")])
    cobradas = []
    monkeypatch.setattr(dialogo, "_cobrar_cuenta", cobradas.append)

    dialogo.tabla.selectRow(1)
    dialogo._on_double_click_factura_detalle()

    assert cobradas == [8]


def test_detalle_doble_clic_sin_seleccion_no_hace_nada(qtbot, monkeypatch):
    dialogo = _detalle(qtbot, [_cuenta(7, "pendiente")])
    cobradas = []
    monkeypatch.setattr(dialogo, "_cobrar_cuenta", cobradas.append)

    dialogo._on_double_click_factura_detalle()

    assert cobradas == []


def test_detalle_cobrar_pasa_la_tasa_paralelo_al_dialogo_de_pago(qtbot, monkeypatch):
    dialogo = _detalle(qtbot, [_cuenta(7, "pendiente")], tasa_paralelo=62.5)
    dialogo.session.get.return_value = _cuenta(7, "pendiente")
    creados = {}

    class DialogoFalso:
        pago_creado = None

        def __init__(self, session, id_usuario, cuenta, tasa_bcv=None, parent=None):
            creados["tasa_bcv"] = tasa_bcv
            creados["cuenta"] = cuenta

        def exec(self):
            return 0

    monkeypatch.setattr(cxc, "PagoCobroDialog", DialogoFalso)

    dialogo._cobrar_cuenta(7)

    assert creados["tasa_bcv"] == 62.5


def test_detalle_cobrar_cuenta_ya_pagada_avisa_y_no_abre_el_dialogo(qtbot, monkeypatch):
    dialogo = _detalle(qtbot, [_cuenta(7, "pendiente")])
    dialogo.session.get.return_value = _cuenta(7, "pagada")
    avisos = []
    monkeypatch.setattr(cxc.MessageBox, "information", lambda *a, **k: avisos.append(a[1]))
    monkeypatch.setattr(cxc, "PagoCobroDialog", lambda *a, **k: pytest.fail("no debe abrir el cobro"))

    dialogo._cobrar_cuenta(7)

    assert avisos == ["Ya pagada"]


def test_detalle_recargar_tras_un_cobro_trae_todas_las_facturas_y_no_solo_la_primera_pagina(qtbot, monkeypatch):
    """_recargar_cuentas() usa el mismo listado que el panel; sin por_pagina explicito
    PagoService.listar_cuentas_por_cobrar devuelve solo 20, y un cliente con mas facturas las
    perderia del detalle despues de cobrar una."""
    dialogo = _detalle(qtbot, [_cuenta(1, "pendiente")])
    llamadas = []

    def fake_listar(session, **kwargs):
        llamadas.append(kwargs)
        return {"items": [_cuenta(i, "pendiente") for i in range(1, 26)]}

    monkeypatch.setattr(cxc.PagoService, "listar_cuentas_por_cobrar", staticmethod(fake_listar))

    dialogo._recargar_cuentas()

    assert llamadas[0].get("por_pagina", 20) > 20
    assert dialogo.lbl_paginacion.text() == "Página 1 de 2"
