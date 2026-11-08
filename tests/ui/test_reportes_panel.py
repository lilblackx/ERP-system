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

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QLabel

import app.ui.exportacion_completa as ec
import app.ui.reportes_panel as rp
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


# ── Reporte "Ventas a Clientes por Producto" ─────────────────────────────────


@pytest.fixture()
def panel(qtbot, monkeypatch):
    # Sin el QTimer.singleShot(100, ...) del constructor: correria (ya sin el parche) contra la
    # Session mockeada en medio de otro test y pytest-qt lo reportaria como falla de ese test.
    monkeypatch.setattr(rp.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(rp.ReportesPanel, "_generar", lambda self: None)
    panel = rp.ReportesPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    return panel


def _cliente(nombre, monto, cantidad="1", bultos="0"):
    return {
        "cliente": nombre,
        "identificacion_cliente": f"V-{nombre}",
        "bultos": Decimal(bultos),
        "unidades": Decimal(cantidad),
        "monto_total": Decimal(monto),
    }


def _fila(producto, codigo, clientes):
    return {
        "producto": producto,
        "cod_producto": codigo,
        "bultos": sum((c["bultos"] for c in clientes), Decimal("0")),
        "unidades": sum((c["unidades"] for c in clientes), Decimal("0")),
        "monto_total": sum((c["monto_total"] for c in clientes), Decimal("0")),
        "clientes": clientes,
    }


def _resultado(filas, id_producto=None):
    return {
        "fecha_desde": date(2026, 10, 1),
        "fecha_hasta": date(2026, 10, 16),
        "id_vendedor": None,
        "id_producto": id_producto,
        "filas": filas,
        "total_general": sum((f["monto_total"] for f in filas), Decimal("0")),
        "bultos_general": sum((f["bultos"] for f in filas), Decimal("0")),
        "unidades_general": sum((f["unidades"] for f in filas), Decimal("0")),
    }


def _construir_todas_las_paginas(panel):
    """Las paginas de filtros se construyen al elegir su reporte; estas pruebas miran combos de varias a la vez."""
    for modo in panel._filtros_fabricas:
        panel._asegurar_pagina(modo)


def _chips(panel):
    widgets = [panel.resumen_layout.itemAt(i).widget() for i in range(panel.resumen_layout.count())]
    return [w.text() for w in widgets if isinstance(w, QLabel)]


def _celdas_tabla(panel, fila):
    return [panel.tabla.item(fila, c).text() for c in range(panel.tabla.columnCount())]


def test_el_tipo_de_reporte_aparece_en_el_combo_con_sus_filtros(panel):
    _construir_todas_las_paginas(panel)
    indice = panel.tipo_combo.findData(rp.REPORTE_VENTAS_PRODUCTOS_CLIENTES)

    assert indice >= 0
    assert panel.tipo_combo.itemText(indice) == "Ventas a Clientes por Producto"
    assert panel.producto_combo_vpc.itemText(0) == "Todos los productos"
    assert panel.vendedor_combo_vpc.itemText(0) == "Todos los vendedores"
    assert panel.producto_combo_vpc.currentData() is None
    assert panel.vendedor_combo_vpc.currentData() is None


def test_vista_general_lista_un_producto_por_fila_con_sus_clientes(panel):
    panel._ultimo_modo = rp.REPORTE_VENTAS_PRODUCTOS_CLIENTES
    filas = [
        _fila("Harina", "H-1", [_cliente("Ana", "50.00")]),
        _fila("Aceite", "A-1", [_cliente("Ana", "20.00", "2"), _cliente("Beto", "10.00")]),
    ]

    panel._mostrar_ventas_productos_clientes(_resultado(filas))

    assert [panel.tabla.horizontalHeaderItem(c).text() for c in range(6)] == rp.COLS_VENTAS_PRODUCTOS_CLIENTES
    assert _celdas_tabla(panel, 0) == ["Harina", "H-1", "0.00", "1.00", "$50.00", "Ana ($50.00)"]
    assert _celdas_tabla(panel, 1) == ["Aceite", "A-1", "0.00", "3.00", "$30.00", "Ana ($20.00), Beto ($10.00)"]
    assert panel.lbl_total.text() == "2 productos"
    assert _chips(panel) == ["Productos: 2", "Bultos: 0.00", "Unidades: 4.00", "Monto total: $80.00"]


def test_vista_general_con_un_solo_producto_usa_singular(panel):
    panel._mostrar_ventas_productos_clientes(_resultado([_fila("Harina", "H-1", [_cliente("Ana", "50.00")])]))

    assert panel.lbl_total.text() == "1 producto"


def test_vista_general_limita_a_cinco_clientes_y_resume_el_resto(panel):
    clientes = [_cliente(f"C{i}", f"{100 - i}.00") for i in range(1, 8)]

    panel._mostrar_ventas_productos_clientes(_resultado([_fila("Aceite", "A-1", clientes)]))

    texto = panel.tabla.item(0, 5).text()
    assert "C5 ($95.00)" in texto
    assert "C6" not in texto
    assert texto.endswith("(+2 más)")


def test_vista_de_un_producto_lista_los_clientes_con_la_cantidad_vendida(panel):
    filas = [_fila("Aceite", "A-1", [_cliente("Ana", "20.00", "2", bultos="1"), _cliente("Beto", "10.00")])]

    panel._mostrar_ventas_productos_clientes(_resultado(filas, id_producto=5))

    assert [panel.tabla.horizontalHeaderItem(c).text() for c in range(4)] == [
        "Cliente",
        "Identificación",
        "Bultos",
        "Unidades",
    ]
    assert _celdas_tabla(panel, 0) == ["Ana", "V-Ana", "1.00", "2.00"]
    assert _celdas_tabla(panel, 1) == ["Beto", "V-Beto", "0.00", "1.00"]
    assert panel.lbl_total.text() == "2 clientes"


def test_vista_de_un_producto_sin_ventas_en_el_periodo_dice_cero_clientes(panel):
    panel._mostrar_ventas_productos_clientes(_resultado([], id_producto=5))

    assert panel.lbl_total.text() == "0 clientes"


def test_vista_general_sin_ventas_deja_la_tabla_vacia(panel):
    panel._mostrar_ventas_productos_clientes(_resultado([]))

    assert panel.tabla.rowCount() == 0
    assert panel.lbl_total.text() == "0 productos"
    assert _chips(panel)[0] == "Productos: 0"


def test_exportar_arma_filas_del_reporte(panel):
    panel._ultimo_modo = rp.REPORTE_VENTAS_PRODUCTOS_CLIENTES
    panel._ultimo_resultado = _resultado(
        [_fila("Aceite", "A-1", [_cliente("Ana", "20.00", "2"), _cliente("Beto", "10.00")])]
    )

    nombre, columnas, filas = panel._filas_para_exportar()

    assert nombre == "ventas_productos_clientes"
    assert columnas == rp.COLS_VENTAS_PRODUCTOS_CLIENTES_EXPORT
    # Una fila por producto y cliente: la pantalla resume a 5 clientes, el archivo trae a todos.
    assert filas == [
        ["Aceite", "A-1", "Ana", "V-Ana", 0.0, 2.0, 20.0],
        ["Aceite", "A-1", "Beto", "V-Beto", 0.0, 1.0, 10.0],
    ]


def test_exportar_pdf_incluye_vendedor_y_total_general(panel):
    _construir_todas_las_paginas(panel)
    panel._ultimo_modo = rp.REPORTE_VENTAS_PRODUCTOS_CLIENTES
    panel._ultimo_resultado = _resultado([_fila("Aceite", "A-1", [_cliente("Ana", "20.00", "2")])])

    titulo, filtros, anchos = panel._info_pdf()

    assert titulo == "Ventas a Clientes por Producto"
    assert filtros["Desde"] == "01/10/2026"
    assert filtros["Hasta"] == "16/10/2026"
    assert filtros["Vendedor"] == "Todos los vendedores"
    assert filtros["Total general"] == "$20.00"
    assert len(anchos) == len(rp.COLS_VENTAS_PRODUCTOS_CLIENTES_EXPORT)


@pytest.fixture()
def panel_con_generar_real(qtbot, monkeypatch):
    """_generar real, pero sin el QTimer.singleShot(100, self._generar) del constructor: dispararia
    una consulta con la Session mockeada en medio de otro test."""
    monkeypatch.setattr(rp.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    panel = rp.ReportesPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    return panel


def test_generar_con_rango_invertido_avisa_y_no_lanza_la_consulta(panel_con_generar_real, monkeypatch):
    panel = panel_con_generar_real
    avisos = []
    monkeypatch.setattr(rp.MessageBox, "warning", lambda *a, **k: avisos.append(a[1]))
    monkeypatch.setattr(rp, "QueryWorker", lambda *a, **k: pytest.fail("no debe consultar"))
    panel.tipo_combo.setCurrentIndex(panel.tipo_combo.findData(rp.REPORTE_VENTAS_PRODUCTOS_CLIENTES))
    panel.fecha_desde_vpc_input.setDate(QDate(2026, 10, 20))
    panel.fecha_hasta_vpc_input.setDate(QDate(2026, 10, 1))

    panel._generar()

    assert avisos == ["Rango inválido"]


def test_generar_pasa_los_filtros_de_vendedor_y_producto_a_la_tarea(panel_con_generar_real, monkeypatch):
    panel = panel_con_generar_real
    lanzados = {}

    class _WorkerFalso:
        def __init__(self, session_factory, tarea, **kwargs):
            lanzados["tarea"] = tarea
            lanzados.update(kwargs)
            self.resultado = MagicMock()
            self.error = MagicMock()

        def start(self):
            lanzados["iniciado"] = True

        def wait(self, _ms):
            return True

    monkeypatch.setattr(rp, "QueryWorker", _WorkerFalso)
    panel.tipo_combo.setCurrentIndex(panel.tipo_combo.findData(rp.REPORTE_VENTAS_PRODUCTOS_CLIENTES))
    panel.vendedor_combo_vpc.addItem("Vendedor Uno", 7)
    panel.producto_combo_vpc.addItem("A-1 - Aceite", 42)
    panel.vendedor_combo_vpc.setCurrentIndex(panel.vendedor_combo_vpc.findData(7))
    panel.producto_combo_vpc.setCurrentIndex(panel.producto_combo_vpc.findData(42))

    panel._generar()

    assert lanzados["tarea"] is rp._tarea_ventas_productos_clientes
    assert lanzados["id_vendedor"] == 7
    assert lanzados["id_producto"] == 42
    assert lanzados["id_usuario"] == 1
    assert lanzados["iniciado"] is True


# ── Libro de ventas: cantidad de facturas ────────────────────────────────────


def test_resumen_del_libro_de_ventas_empieza_con_la_cantidad_de_ventas(panel):
    resultado = {
        "cantidad_facturas": 12,
        "cantidad_anuladas": 0,
        "total_exento": Decimal("0.00"),
        "total_base_imponible": Decimal("100.00"),
        "total_iva": Decimal("16.00"),
        "total_general": Decimal("116.00"),
        "total_bs": Decimal("0.00"),
        "notas_credito": [],
        "total_notas_credito": Decimal("0.00"),
    }

    panel._mostrar_resumen_libro_ventas(resultado)

    assert _chips(panel)[0] == "Ventas: 12"
    assert _chips(panel)[1] == "Base imponible: $100.00"


# ── Auditoria de reportes: exportacion completa y filtros congelados ─────────────────────────


def _resultado_libro(**extra):
    fila = {
        "fecha_emision": datetime(2026, 10, 3, 10, 0),
        "numero_control": "00-000001",
        "numero_factura": "FV-000001",
        "estado": "EMITIDA",
        "cliente": "Ana",
        "identificacion_cliente": "V-1",
        "monto_exento": Decimal("0.00"),
        "base_imponible": Decimal("100.00"),
        "porcentaje_iva": Decimal("16.00"),
        "monto_iva": Decimal("16.00"),
        "total": Decimal("116.00"),
        "tasa_cambio": Decimal("40.00"),
        "total_bs": Decimal("4640.00"),
    }
    resultado = {
        "fecha_desde": date(2026, 10, 1),
        "fecha_hasta": date(2026, 10, 31),
        "filas": [fila],
        "cantidad_facturas": 1,
        "cantidad_anuladas": 0,
        "total_base_imponible": Decimal("100.00"),
        "total_exento": Decimal("0.00"),
        "total_iva": Decimal("16.00"),
        "total_general": Decimal("116.00"),
        "total_bs": Decimal("4640.00"),
        "notas_credito": [],
        "total_notas_credito": Decimal("0.00"),
    }
    resultado.update(extra)
    return resultado


def test_libro_de_ventas_exporta_tantas_celdas_como_encabezados(panel):
    _construir_todas_las_paginas(panel)
    panel._ultimo_modo = rp.REPORTE_LIBRO_VENTAS
    panel._ultimo_resultado = _resultado_libro()

    _nombre, columnas, filas = panel._filas_para_exportar()
    _titulo, _filtros, anchos = panel._info_pdf()

    assert len(columnas) == len(filas[0]) == len(anchos) == 13
    assert filas[0][3] == "Emitida" and filas[0][12] == 4640.0


def test_libro_de_ventas_exporta_las_notas_de_credito_como_seccion_aparte(panel):
    panel._ultimo_modo = rp.REPORTE_LIBRO_VENTAS
    nota = {
        "fecha_creacion": datetime(2026, 10, 5, 9, 0),
        "numero_nota_credito": "NC-000001",
        "cliente": "Ana",
        "identificacion_cliente": "V-1",
        "monto": Decimal("30.00"),
        "motivo": "Sobreabono",
    }
    panel._ultimo_resultado = _resultado_libro(notas_credito=[nota], total_notas_credito=Decimal("30.00"))

    secciones = panel._secciones_para_exportar()

    assert [s["titulo"] for s in secciones] == ["Notas de crédito del período"]
    assert secciones[0]["encabezados"] == rp.COLS_LIBRO_VENTAS_NC
    assert secciones[0]["filas"] == [[nota["fecha_creacion"], "NC-000001", "Ana", "V-1", 30.0, "Sobreabono"]]
    assert len(secciones[0]["col_widths"]) == len(rp.COLS_LIBRO_VENTAS_NC)


def test_libro_de_ventas_sin_notas_de_credito_no_agrega_secciones(panel):
    panel._ultimo_modo = rp.REPORTE_LIBRO_VENTAS
    panel._ultimo_resultado = _resultado_libro()

    assert panel._secciones_para_exportar() is None


def test_los_reportes_anchos_salen_en_hoja_horizontal():
    assert rp.REPORTE_LIBRO_VENTAS in rp.REPORTES_APAISADOS
    assert rp.REPORTE_CIERRE_CAJERO in rp.REPORTES_APAISADOS
    assert rp.REPORTE_VENTAS_PERIODO not in rp.REPORTES_APAISADOS


def test_el_arqueo_exporta_saldos_y_diferencia(panel):
    panel._ultimo_modo = rp.REPORTE_ARQUEO_CAJA
    panel._ultimo_resultado = {
        "nombre_caja": "Caja 1",
        "fecha_apertura": datetime(2026, 10, 1, 8, 0),
        "fecha_cierre": datetime(2026, 10, 1, 18, 0),
        "saldo_apertura": Decimal("100.00"),
        "total_entradas": Decimal("50.00"),
        "total_salidas": Decimal("20.00"),
        "saldo_esperado": Decimal("130.00"),
        "saldo_cierre": Decimal("125.00"),
        "diferencia": Decimal("-5.00"),
        "movimientos": [],
    }

    _titulo, filtros, _anchos = panel._info_pdf()

    assert filtros["Saldo apertura"] == "$100.00"
    assert filtros["Entradas"] == "$50.00" and filtros["Salidas"] == "$20.00"
    assert filtros["Diferencia"] == "$-5.00"


def test_los_filtros_del_archivo_son_los_del_momento_de_generar_no_los_del_combo_actual(panel):
    panel._ultimo_modo = rp.REPORTE_AGING_CXC
    panel._ultimo_resultado = {
        "fecha_corte": date(2026, 10, 16),
        "total_general": Decimal("10.00"),
        "filas": [],
        "totales_por_bucket": {},
    }
    panel.cliente_combo.addItem("Cliente A", 1)
    panel.cliente_combo.addItem("Cliente B", 2)
    panel.cliente_combo.setCurrentIndex(panel.cliente_combo.findData(1))
    panel._combos_snapshot = panel._capturar_combos()  # lo que hace _generar() al lanzar la consulta

    panel.cliente_combo.setCurrentIndex(panel.cliente_combo.findData(2))  # cambia el filtro DESPUES de generar
    _titulo, filtros, _anchos = panel._info_pdf()

    assert filtros["Cliente"] == "Cliente A"


def test_los_productos_proximos_a_vencer_exportan_la_fecha_como_fecha(panel):
    panel._ultimo_modo = rp.REPORTE_PRODUCTOS_PROXIMOS_VENCER
    panel._ultimo_resultado = {
        "filas": [
            {
                "cod_producto": "A-1",
                "producto": "Aceite",
                "categoria": None,
                "cantidad_unidad": Decimal("5"),
                "fecha_vencimiento": date(2026, 11, 20),
                "dias_para_vencer": 13,
            }
        ]
    }

    _nombre, _columnas, filas = panel._filas_para_exportar()

    assert filas[0][4] == date(2026, 11, 20)


def test_facturas_anuladas_exporta_la_fecha_de_anulacion(panel):
    panel._ultimo_modo = rp.REPORTE_FACTURAS_ANULADAS
    anulacion = datetime(2026, 11, 2, 15, 30)
    panel._ultimo_resultado = {
        "filas": [
            {
                "numero_factura": "FV-000001",
                "cliente": "Ana",
                "vendedor": "Pedro",
                "fecha_emision": datetime(2026, 10, 1, 9, 0),
                "fecha_anulacion": anulacion,
                "motivo": "error",
            }
        ]
    }

    _nombre, columnas, filas = panel._filas_para_exportar()

    assert columnas == rp.COLS_FACTURAS_ANULADAS
    assert filas[0][4] == anulacion and len(filas[0]) == len(columnas)


def test_cobros_exporta_la_cartera(panel):
    panel._ultimo_modo = rp.REPORTE_COBROS_PERIODO
    panel._ultimo_resultado = {
        "filas": [
            {
                "fecha_pago": datetime(2026, 10, 3, 9, 0),
                "cliente": "Ana",
                "numero_factura": "FV-000001",
                "cartera": "BCV",
                "metodo_pago": "efectivo",
                "moneda": "USD",
                "monto": Decimal("20.00"),
            }
        ]
    }

    _nombre, columnas, filas = panel._filas_para_exportar()

    assert columnas[3] == "Cartera" and filas[0][3] == "BCV" and len(filas[0]) == len(columnas)


# ── Catalogos de los combos de filtros ───────────────────────────────────────


def _catalogos(**extra):
    base = {
        "clientes": [(1, "Ana"), (2, "Beto")],
        "proveedores": [(5, "Prov Uno")],
        "cajas": [(3, "Caja 1")],
        "vendedores": [(9, "Vende Uno")],
        "cajeros": [(4, "cajero1")],
        "productos": [(42, "A-1 - Aceite")],
        "categorias": [(8, "Bebidas")],
        "cuentas": [(6, "Banco X - 0001")],
    }
    base.update(extra)
    return base


def test_los_combos_de_cliente_comparten_un_modelo_con_la_opcion_todos(panel):
    _construir_todas_las_paginas(panel)
    panel._llenar_catalogos(_catalogos())

    assert panel.cliente_combo.model() is panel.cliente_combo_lv.model()
    assert [panel.cliente_combo.itemText(i) for i in range(panel.cliente_combo.count())] == [
        "Todos los clientes",
        "Ana",
        "Beto",
    ]
    assert panel.cliente_combo.currentData() is None
    panel.cliente_combo_lv.setCurrentIndex(panel.cliente_combo_lv.findData(2))
    assert panel.cliente_combo_lv.currentData() == 2
    assert panel.cliente_combo.currentData() is None  # cada combo conserva su propia seleccion


def test_los_combos_de_producto_puntual_no_llevan_opcion_todos(panel):
    _construir_todas_las_paginas(panel)
    panel._llenar_catalogos(_catalogos())

    assert panel.producto_combo_kardex.count() == 1
    assert panel.producto_combo_kardex.currentData() == 42
    assert panel.producto_combo_vpc.count() == 2
    assert panel.producto_combo_vpc.currentData() is None
    assert panel.caja_combo.currentData() == 3
    assert panel.caja_combo_mcp.currentData() is None
    assert panel.cuenta_bancaria_combo_mcb.currentData() == 6


def test_un_catalogo_vacio_deja_solo_la_opcion_todos(panel):
    _construir_todas_las_paginas(panel)
    panel._llenar_catalogos(_catalogos(clientes=[], cajas=[]))

    assert panel.cliente_combo.count() == 1
    assert panel.cliente_combo.currentData() is None
    assert panel.caja_combo.count() == 0
    assert panel.caja_combo.currentData() is None


def test_la_tarea_de_catalogos_devuelve_tuplas_simples_de_la_base(db_session):
    from tests.factories import crear_cliente

    crear_cliente(db_session, nombre_razon_social="Zeta SA")
    crear_cliente(db_session, nombre_razon_social="Alfa SA")

    datos = rp._tarea_catalogos_filtros(db_session)

    nombres = [nombre for _id, nombre in datos["clientes"]]
    assert nombres == sorted(nombres)
    assert "Alfa SA" in nombres and "Zeta SA" in nombres
    assert set(datos) == {
        "clientes",
        "proveedores",
        "cajas",
        "vendedores",
        "cajeros",
        "productos",
        "categorias",
        "cuentas",
    }


# --- Productos mas/menos vendidos: bultos y unidades en columnas separadas ---------------------


def _resultado_vendidos():
    filas = [
        {"producto": "Harina", "bultos": Decimal("3.00"), "unidades": Decimal("5.00"), "total": Decimal("78.00")},
        {"producto": "Aceite", "bultos": Decimal("0.00"), "unidades": Decimal("2.00"), "total": Decimal("4.00")},
    ]
    return {
        "fecha_desde": date(2026, 10, 1),
        "fecha_hasta": date(2026, 10, 16),
        "orden": "desc",
        "filas": filas,
        "total_general": Decimal("82.00"),
    }


def test_productos_vendidos_muestra_bultos_y_unidades_en_columnas_separadas(panel):
    panel._mostrar_productos_vendidos(_resultado_vendidos())

    assert [panel.tabla.horizontalHeaderItem(c).text() for c in range(4)] == ["Producto", "Bultos", "Unidades", "Total"]
    assert _celdas_tabla(panel, 0) == ["Harina", "3.00", "5.00", "$78.00"]
    assert _celdas_tabla(panel, 1) == ["Aceite", "0.00", "2.00", "$4.00"]
    assert panel.lbl_total.text() == "2 filas"
    assert _chips(panel) == ["Total general: $82.00"]


def test_productos_vendidos_exporta_las_cuatro_columnas_y_el_pdf_tiene_cuatro_anchos(panel):
    panel._ultimo_modo = rp.REPORTE_PRODUCTOS_VENDIDOS
    panel._ultimo_resultado = _resultado_vendidos()

    nombre, columnas, filas = panel._filas_para_exportar()
    _titulo, _filtros, anchos = panel._info_pdf()

    assert nombre == "productos_vendidos"
    assert columnas == ["Producto", "Bultos", "Unidades", "Total"]
    assert filas[0] == ["Harina", 3.0, 5.0, 78.0]
    assert len(anchos) == len(columnas)


def test_margen_utilidad_muestra_y_exporta_bultos_y_unidades_por_separado(panel):
    panel._ultimo_modo = rp.REPORTE_MARGEN_UTILIDAD
    panel._ultimo_resultado = {
        "fecha_desde": date(2026, 10, 1),
        "fecha_hasta": date(2026, 10, 16),
        "filas": [
            {
                "producto": "Harina",
                "bultos": Decimal("2.00"),
                "unidades": Decimal("3.00"),
                "ingreso": Decimal("60.00"),
                "costo": Decimal("54.00"),
                "margen": Decimal("6.00"),
                "margen_pct": Decimal("10.00"),
            }
        ],
        "total_ingreso": Decimal("60.00"),
        "total_costo": Decimal("54.00"),
        "total_margen": Decimal("6.00"),
    }

    panel._mostrar_margen_utilidad(panel._ultimo_resultado)
    nombre, columnas, filas = panel._filas_para_exportar()
    _titulo, _filtros, anchos = panel._info_pdf()

    assert _celdas_tabla(panel, 0) == ["Harina", "2.00", "3.00", "$60.00", "$54.00", "$6.00", "10.0%"]
    assert nombre == "margen_utilidad"
    assert columnas[:3] == ["Producto", "Bultos", "Unidades"]
    assert filas[0] == ["Harina", 2.0, 3.0, 60.0, 54.0, 6.0, 10.0]
    assert len(anchos) == len(columnas) == panel.tabla.columnCount()


def test_un_pdf_con_demasiadas_filas_avisa_y_no_pide_el_destino(panel, monkeypatch):
    panel._ultimo_modo = rp.REPORTE_PRODUCTOS_VENDIDOS
    panel._ultimo_resultado = {"fecha_desde": date(2026, 1, 1), "fecha_hasta": date(2026, 12, 31), "orden": "desc"}
    monkeypatch.setattr(panel, "_filas_para_exportar", lambda: ("x", ["A"], [["fila"]] * (rp.LIMITE_FILAS_PDF + 1)))
    avisos = []
    monkeypatch.setattr(rp.MessageBox, "information", lambda *a, **k: avisos.append(a[1]))
    monkeypatch.setattr(
        rp.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: pytest.fail("no debe pedir ruta"))
    )

    panel._exportar_pdf()

    assert avisos == ["Demasiadas filas para un PDF"]


def test_los_combos_comparten_un_modelo_ligero_con_id_y_texto(panel):
    _construir_todas_las_paginas(panel)
    datos = {
        "clientes": [(7, "Ana"), (9, "Beto")],
        "proveedores": [],
        "cajas": [],
        "vendedores": [],
        "cajeros": [],
        "productos": [(1, "P-1 - Harina")],
        "categorias": [],
        "cuentas": [],
    }

    panel._llenar_catalogos(datos)

    combo = panel.cliente_combo
    assert [combo.itemText(i) for i in range(combo.count())] == ["Todos los clientes", "Ana", "Beto"]
    assert combo.itemData(0) is None and combo.itemData(2) == 9
    combo.setCurrentIndex(1)
    assert combo.currentData() == 7
    assert panel.cliente_combo_nc.model() is combo.model()  # todos los combos de clientes comparten el modelo
    assert panel.producto_combo_vpc.itemText(0) == "Todos los productos"
    assert panel.producto_combo_kardex.itemText(0) == "P-1 - Harina"


def test_al_abrir_solo_se_construye_la_pagina_de_filtros_del_primer_reporte(panel):
    assert list(panel._filtros_paginas) == [rp.REPORTE_AGING_CXC]
    assert panel._filtros_paginas[rp.REPORTE_AGING_CXC].isVisibleTo(panel)


def test_elegir_un_reporte_construye_su_pagina_una_sola_vez_y_oculta_la_anterior(panel):
    indice = panel.tipo_combo.findData(rp.REPORTE_KARDEX)

    panel.tipo_combo.setCurrentIndex(indice)
    pagina = panel._filtros_paginas[rp.REPORTE_KARDEX]
    panel.tipo_combo.setCurrentIndex(0)
    panel.tipo_combo.setCurrentIndex(indice)

    assert panel._filtros_paginas[rp.REPORTE_KARDEX] is pagina
    assert pagina.isVisibleTo(panel)
    assert not panel._filtros_paginas[rp.REPORTE_AGING_CXC].isVisibleTo(panel)
    assert panel.filtros_container.layout().count() == 2


def test_una_pagina_construida_despues_recibe_los_catalogos_ya_cargados(panel):
    panel._llenar_catalogos(_catalogos())
    assert not hasattr(panel, "producto_combo_kardex")

    panel._asegurar_pagina(rp.REPORTE_KARDEX)

    assert panel.producto_combo_kardex.currentData() == 42
    # y una pagina que ya tenia el catalogo no lo recibe de nuevo (conserva lo que eligio el usuario)
    panel.cliente_combo.setCurrentIndex(1)
    panel._asegurar_pagina(rp.REPORTE_LIBRO_VENTAS)
    assert panel.cliente_combo.currentData() == 1
    assert panel.cliente_combo_lv.model() is panel.cliente_combo.model()


def test_generar_construye_la_pagina_aunque_el_combo_no_haya_emitido_senal(panel_con_generar_real, monkeypatch):
    panel = panel_con_generar_real
    monkeypatch.setattr(rp, "QueryWorker", lambda *a, **k: MagicMock())
    panel.tipo_combo.blockSignals(True)
    panel.tipo_combo.setCurrentIndex(panel.tipo_combo.findData(rp.REPORTE_VALORIZACION))
    panel.tipo_combo.blockSignals(False)

    panel._generar()

    assert rp.REPORTE_VALORIZACION in panel._filtros_paginas


def test_un_reporte_enorme_dibuja_solo_las_primeras_filas_pero_exporta_todas(panel, monkeypatch):
    monkeypatch.setattr(rp, "LIMITE_FILAS_PANTALLA", 50)
    base = _resultado_libro()
    total = 130
    resultado = _resultado_libro(filas=base["filas"] * total, cantidad_facturas=total)
    panel._ultimo_modo = rp.REPORTE_LIBRO_VENTAS

    panel._mostrar_resultado(resultado)

    assert panel.tabla.rowCount() == 50
    assert "130 facturas" in panel.lbl_total.text()  # el conteo es el real, no el de la pantalla
    assert "primeras 50" in panel.lbl_total.text() and "exportación incluye todas" in panel.lbl_total.text()
    _nombre, _columnas, filas = panel._filas_para_exportar()
    assert len(filas) == total


def test_un_reporte_que_cabe_en_pantalla_no_agrega_aviso(panel):
    panel._ultimo_modo = rp.REPORTE_LIBRO_VENTAS

    panel._mostrar_resultado(_resultado_libro())

    assert panel.tabla.rowCount() == 1
    assert "exportación incluye todas" not in panel.lbl_total.text()


# -- Reportes de listado paginados (Libro de Ventas): pantalla por paginas, exportacion con todas las filas ----------


class _WorkerRegistrado:
    """Reemplaza a QueryWorker: registra con que se lo creo, no lanza ningun hilo y deja que el test entregue la
    respuesta."""

    creados: list = []

    def __init__(self, session_factory, tarea, *args, **kwargs):
        self.tarea, self.args, self.kwargs = tarea, args, kwargs
        self.silencioso = False
        self.resultado, self.error, self.finished = MagicMock(), MagicMock(), MagicMock()
        _WorkerRegistrado.creados.append(self)

    def start(self):
        self.iniciado = True

    def isRunning(self):
        return False

    def wait(self, _ms):
        return True


def _con_libro_de_ventas(panel):
    panel.tipo_combo.setCurrentIndex(panel.tipo_combo.findData(rp.REPORTE_LIBRO_VENTAS))
    panel._ultimo_modo = rp.REPORTE_LIBRO_VENTAS


def _pagina_libro(filas, pagina=1, total=250, por_pagina=100):
    resultado = _resultado_libro(filas=filas)
    resultado["paginacion"] = {
        "pagina": pagina,
        "por_pagina": por_pagina,
        "total": total,
        "total_paginas": -(-total // por_pagina),
    }
    return resultado


def test_el_libro_de_ventas_pide_una_pagina_y_muestra_el_control_de_paginacion(panel_con_generar_real, monkeypatch):
    panel = panel_con_generar_real
    _WorkerRegistrado.creados = []
    monkeypatch.setattr(rp, "QueryWorker", _WorkerRegistrado)
    assert panel.pie_paginacion.isHidden()
    _con_libro_de_ventas(panel)
    assert not panel.pie_paginacion.isHidden()

    panel._generar()

    pedido = _WorkerRegistrado.creados[-1]
    assert pedido.tarea is rp._tarea_libro_ventas
    assert pedido.kwargs["pagina"] == 1 and pedido.kwargs["por_pagina"] == rp.POR_PAGINA_REPORTE


def test_la_respuesta_actualiza_el_control_y_cambiar_de_pagina_pide_esa_pagina(panel_con_generar_real, monkeypatch):
    panel = panel_con_generar_real
    _WorkerRegistrado.creados = []
    monkeypatch.setattr(rp, "QueryWorker", _WorkerRegistrado)
    _con_libro_de_ventas(panel)
    panel._generar()

    panel._mostrar_resultado(_pagina_libro(_resultado_libro()["filas"] * 100, total=250))
    assert panel.paginacion.total_paginas == 3
    assert panel.paginacion.lbl_pagina.text() == "Página 1 de 3 (250)"

    panel.paginacion.siguiente()

    assert _WorkerRegistrado.creados[-1].kwargs["pagina"] == 2


def test_generar_de_nuevo_vuelve_a_la_primera_pagina(panel_con_generar_real, monkeypatch):
    panel = panel_con_generar_real
    _WorkerRegistrado.creados = []
    monkeypatch.setattr(rp, "QueryWorker", _WorkerRegistrado)
    _con_libro_de_ventas(panel)
    panel.paginacion.actualizar(pagina=3, total_paginas=3, total=250)

    panel._generar_desde_inicio()

    assert _WorkerRegistrado.creados[-1].kwargs["pagina"] == 1 and panel.paginacion.pagina == 1


def test_cambiar_a_otro_reporte_oculta_la_paginacion_y_vuelve_a_la_pagina_1(panel):
    _con_libro_de_ventas(panel)
    panel.paginacion.actualizar(pagina=2, total_paginas=3, total=250)

    panel.tipo_combo.setCurrentIndex(panel.tipo_combo.findData(rp.REPORTE_VENTAS_PERIODO))

    assert panel.pie_paginacion.isHidden() and panel.paginacion.pagina == 1


def test_exportar_un_reporte_paginado_vuelve_a_pedirlo_completo_con_los_filtros_de_lo_que_se_ve(
    panel_con_generar_real, monkeypatch
):
    panel = panel_con_generar_real
    _WorkerRegistrado.creados = []
    monkeypatch.setattr(rp, "QueryWorker", _WorkerRegistrado)
    monkeypatch.setattr(ec, "QueryWorker", _WorkerRegistrado)
    monkeypatch.setattr(ec, "ocupar_boton", lambda *a, **k: None)
    monkeypatch.setattr(rp.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("/tmp/libro.xlsx", "")))
    _con_libro_de_ventas(panel)
    panel._generar()
    pagina = _pagina_libro(_resultado_libro()["filas"] * 2, total=5)
    panel._mostrar_resultado(pagina)
    filtros_del_reporte = dict(panel._consulta_completa[1])
    panel.cliente_combo_lv.setCurrentIndex(-1)  # el usuario toca un filtro DESPUES de generar
    _WorkerRegistrado.creados.clear()

    panel._exportar_excel()

    assert len(_WorkerRegistrado.creados) == 1  # un solo hilo: pide el reporte completo, arma las filas y escribe
    exportacion = _WorkerRegistrado.creados[0]
    assert exportacion.tarea is rp._tarea_exportar_reporte
    assert exportacion.kwargs["formato"] == "excel" and exportacion.kwargs["ruta"] == "/tmp/libro.xlsx"
    assert exportacion.kwargs["resultado"] is None  # lo que hay en pantalla es una pagina: no sirve para exportar
    assert exportacion.kwargs["consulta"] == (rp._tarea_libro_ventas, filtros_del_reporte)
    assert panel._ultimo_resultado is pagina  # la pantalla conserva su pagina


def test_un_pdf_de_un_reporte_paginado_se_rechaza_por_el_total_no_por_la_pagina(panel_con_generar_real, monkeypatch):
    panel = panel_con_generar_real
    _WorkerRegistrado.creados = []
    monkeypatch.setattr(rp, "QueryWorker", _WorkerRegistrado)
    _con_libro_de_ventas(panel)
    panel._generar()
    panel._mostrar_resultado(_pagina_libro(_resultado_libro()["filas"], total=rp.LIMITE_FILAS_PDF + 1))
    avisos = []
    monkeypatch.setattr(rp.MessageBox, "information", lambda *a, **k: avisos.append(a[1]))
    monkeypatch.setattr(
        rp.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: pytest.fail("no debe pedir ruta"))
    )
    _WorkerRegistrado.creados.clear()

    panel._exportar_pdf()

    assert avisos == ["Demasiadas filas para un PDF"]
    assert _WorkerRegistrado.creados == []  # ni siquiera se pide el reporte completo


def test_exportar_un_reporte_no_paginado_usa_el_resultado_en_pantalla_sin_volver_a_pedirlo(
    panel_con_generar_real, monkeypatch
):
    panel = panel_con_generar_real
    _WorkerRegistrado.creados = []
    monkeypatch.setattr(ec, "QueryWorker", _WorkerRegistrado)
    monkeypatch.setattr(ec, "ocupar_boton", lambda *a, **k: None)
    monkeypatch.setattr(rp.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("/tmp/v.xlsx", "")))
    panel._ultimo_modo = rp.REPORTE_PRODUCTOS_VENDIDOS
    panel._ultimo_resultado = _resultado_vendidos()

    panel._exportar_excel()

    assert [w.tarea for w in _WorkerRegistrado.creados] == [rp._tarea_exportar_reporte]
    kwargs = _WorkerRegistrado.creados[0].kwargs
    assert kwargs["resultado"] is panel._ultimo_resultado and kwargs["consulta"] is None


# -- Los demas listados: el resultado completo se corta en paginas en el hilo de la consulta -----------------------


def test_tarea_paginada_devuelve_solo_la_pagina_y_conserva_los_totales():
    resultado = {"filas": list(range(250)), "total_general": 999}

    pagina = rp._tarea_paginada(None, lambda session, **f: {**resultado, **f}, 2, 100, id_usuario=1)

    assert pagina["filas"] == list(range(100, 200))
    assert pagina["total_general"] == 999 and pagina["id_usuario"] == 1
    assert pagina["paginacion"] == {"total": 250, "pagina": 2, "por_pagina": 100, "total_paginas": 3}


def test_tarea_paginada_lleva_una_pagina_pasada_la_ultima_a_la_ultima():
    pagina = rp._tarea_paginada(None, lambda session: {"filas": list(range(120))}, 9, 100)

    assert pagina["paginacion"]["pagina"] == 2 and pagina["filas"] == list(range(100, 120))


MODOS_PAGINADOS_EN_LA_TAREA = sorted(rp.REPORTES_PAGINADOS - rp.REPORTES_PAGINADOS_EN_SQL)


def test_los_listados_grandes_estan_paginados_en_la_base_o_en_la_tarea():
    assert {
        rp.REPORTE_LIBRO_VENTAS,
        rp.REPORTE_MOV_CAJA_PERIODO,
        rp.REPORTE_MOV_CUENTA_BANCARIA,
        rp.REPORTE_COBROS_PERIODO,
        rp.REPORTE_PAGOS_PERIODO,
        rp.REPORTE_NC_EMITIDAS,
        rp.REPORTE_NC_PROVEEDOR,
        rp.REPORTE_DEVOLUCIONES_PROVEEDOR,
    } <= rp.REPORTES_PAGINADOS_EN_SQL
    assert {
        rp.REPORTE_KARDEX,
        rp.REPORTE_FACTURAS_ANULADAS,
        rp.REPORTE_AGING_CXC,
        rp.REPORTE_ESTADO_CTA_CLIENTE,
    } <= set(MODOS_PAGINADOS_EN_LA_TAREA)
    assert not rp.REPORTES_PAGINADOS_EN_SQL & set(MODOS_PAGINADOS_EN_LA_TAREA)
    assert rp.REPORTE_VENTAS_PERIODO not in rp.REPORTES_PAGINADOS  # los que agrupan ya devuelven pocas filas


@pytest.mark.parametrize("modo", MODOS_PAGINADOS_EN_LA_TAREA)
def test_un_listado_paginado_en_la_tarea_pide_la_pagina_cortando_el_reporte_completo(
    panel_con_generar_real, monkeypatch, modo
):
    panel = panel_con_generar_real
    _WorkerRegistrado.creados = []
    monkeypatch.setattr(rp, "QueryWorker", _WorkerRegistrado)
    panel.tipo_combo.setCurrentIndex(panel.tipo_combo.findData(modo))  # construye la pagina de filtros del reporte
    panel._llenar_catalogos(_catalogos())
    # los estados de cuenta exigen elegir a alguien (el primer item de esos combos es "Todos")
    for nombre in ("cliente_combo_ecc", "proveedor_combo_ecp"):
        combo = getattr(panel, nombre, None)
        if combo is not None:
            combo.setCurrentIndex(1)
    panel._ultimo_modo = modo

    panel._generar()

    pedido = _WorkerRegistrado.creados[-1]
    tarea_completa, filtros = panel._consulta_pendiente
    assert pedido.tarea is rp._tarea_paginada, modo
    assert pedido.args[0] is tarea_completa  # corta el reporte completo...
    assert pedido.args[1:] == (1, rp.POR_PAGINA_REPORTE)  # ...en la pagina 1
    assert pedido.kwargs == filtros  # con los mismos filtros con que despues se exporta


def test_el_aviso_de_total_de_un_listado_paginado_en_la_tarea_usa_el_conteo_real(panel):
    panel.tipo_combo.setCurrentIndex(panel.tipo_combo.findData(rp.REPORTE_COBROS_PERIODO))
    panel._ultimo_modo = rp.REPORTE_COBROS_PERIODO
    fila = {
        "fecha_pago": datetime(2026, 10, 3, 10, 0),
        "cliente": "Ana",
        "numero_factura": "FV-1",
        "cartera": "Normal",
        "metodo_pago": "efectivo",
        "moneda": "USD",
        "monto": Decimal("10.00"),
    }
    resultado = {
        "fecha_desde": date(2026, 10, 1),
        "fecha_hasta": date(2026, 10, 31),
        "filas": [fila] * 100,
        "totales_por_metodo": {"efectivo": Decimal("2500.00")},
        "total_general": Decimal("2500.00"),
        "paginacion": {"pagina": 1, "por_pagina": 100, "total": 250, "total_paginas": 3},
    }

    panel._mostrar_resultado(resultado)

    assert panel.tabla.rowCount() == 100
    assert panel.lbl_total.text() == "250 cobros"
    assert not panel.pie_paginacion.isHidden()


def test_con_una_sola_pagina_el_control_de_paginacion_se_oculta(panel_con_generar_real, monkeypatch):
    panel = panel_con_generar_real
    _WorkerRegistrado.creados = []
    monkeypatch.setattr(rp, "QueryWorker", _WorkerRegistrado)
    _con_libro_de_ventas(panel)
    panel._generar()

    panel._mostrar_resultado(_pagina_libro(_resultado_libro()["filas"], total=1))

    assert panel.pie_paginacion.isHidden()


def test_exportar_un_listado_paginado_en_la_tarea_vuelve_a_pedir_el_reporte_completo_sin_cortar(
    panel_con_generar_real, monkeypatch
):
    panel = panel_con_generar_real
    _WorkerRegistrado.creados = []
    monkeypatch.setattr(rp, "QueryWorker", _WorkerRegistrado)
    monkeypatch.setattr(ec, "QueryWorker", _WorkerRegistrado)
    monkeypatch.setattr(ec, "ocupar_boton", lambda *a, **k: None)
    monkeypatch.setattr(rp.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("/tmp/c.xlsx", "")))
    _construir_todas_las_paginas(panel)
    panel.tipo_combo.setCurrentIndex(panel.tipo_combo.findData(rp.REPORTE_COBROS_PERIODO))
    panel._ultimo_modo = rp.REPORTE_COBROS_PERIODO
    panel._generar()
    tarea_completa, filtros = panel._consulta_pendiente
    panel._consulta_completa = panel._consulta_pendiente
    fila = {
        "fecha_pago": datetime(2026, 10, 3, 10, 0),
        "cliente": "Ana",
        "numero_factura": "FV-1",
        "cartera": "Normal",
        "metodo_pago": "efectivo",
        "moneda": "USD",
        "monto": Decimal("10.00"),
    }
    panel._ultimo_resultado = {
        "fecha_desde": date(2026, 10, 1),
        "fecha_hasta": date(2026, 10, 31),
        "filas": [fila] * 2,
        "totales_por_metodo": {},
        "total_general": Decimal("20.00"),
        "paginacion": {"pagina": 1, "por_pagina": 2, "total": 5, "total_paginas": 3},
    }
    _WorkerRegistrado.creados.clear()

    panel._exportar_excel()

    pedido = _WorkerRegistrado.creados[-1]
    assert pedido.tarea is rp._tarea_exportar_reporte
    assert pedido.kwargs["consulta"] == (tarea_completa, filtros)  # el reporte entero, sin cortar en paginas


@pytest.mark.parametrize(
    "modo", sorted(rp.REPORTES_PAGINADOS_EN_SQL - {rp.REPORTE_LIBRO_VENTAS, rp.REPORTE_MOV_CUENTA_BANCARIA})
)
def test_un_listado_paginado_en_la_base_pide_la_pagina_directo_al_servicio(panel_con_generar_real, monkeypatch, modo):
    panel = panel_con_generar_real
    _WorkerRegistrado.creados = []
    monkeypatch.setattr(rp, "QueryWorker", _WorkerRegistrado)
    panel.tipo_combo.setCurrentIndex(panel.tipo_combo.findData(modo))
    panel._ultimo_modo = modo

    panel._generar()

    pedido = _WorkerRegistrado.creados[-1]
    tarea_completa, filtros = panel._consulta_pendiente
    assert pedido.tarea is tarea_completa, modo  # el servicio pagina; no se corta nada en el hilo
    assert pedido.kwargs == {**filtros, "pagina": 1, "por_pagina": rp.POR_PAGINA_REPORTE}


# -- La tarea de exportacion unica: pide el reporte completo (si hace falta), arma las filas y escribe el archivo ----


def test_la_tarea_de_exportacion_de_un_reporte_paginado_escribe_todas_las_filas(tmp_path, monkeypatch):
    from openpyxl import load_workbook

    monkeypatch.setattr(rp.EmpresaService, "obtener_datos_documento", lambda session: None)
    completo = _resultado_libro(filas=_resultado_libro()["filas"] * 7)
    completo["paginacion"] = None
    pedidos = []

    def tarea_completa(session, **filtros):
        pedidos.append(filtros)
        return completo

    ruta = str(tmp_path / "libro.xlsx")
    ruta_devuelta, cantidad = rp._tarea_exportar_reporte(
        None,
        ruta,
        "excel",
        rp.REPORTE_LIBRO_VENTAS,
        None,
        (tarea_completa, {"id_usuario": 1}),
        "Libro de Ventas",
        {},
        None,
        True,
    )

    assert pedidos == [{"id_usuario": 1}]  # sin `pagina`: el reporte completo
    assert (ruta_devuelta, cantidad) == (ruta, 7)
    filas_excel = [f for f in load_workbook(ruta).active.iter_rows(values_only=True) if any(c is not None for c in f)]
    assert sum(1 for f in filas_excel if f[0] == "FV-000001" or "FV-000001" in f) >= 7


def test_la_tarea_de_exportacion_de_un_reporte_no_paginado_no_consulta_nada(tmp_path, monkeypatch):
    monkeypatch.setattr(rp.EmpresaService, "obtener_datos_documento", lambda session: None)
    ruta = str(tmp_path / "vendidos.pdf")

    ruta_devuelta, cantidad = rp._tarea_exportar_reporte(
        None,
        ruta,
        "pdf",
        rp.REPORTE_PRODUCTOS_VENDIDOS,
        _resultado_vendidos(),
        None,
        "Productos vendidos",
        {},
        [2.0, 1.0, 1.0, 1.0],
        False,
    )

    assert ruta_devuelta == ruta and cantidad >= 1 and (tmp_path / "vendidos.pdf").stat().st_size > 500
