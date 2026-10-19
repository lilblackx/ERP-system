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

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QLabel

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


def _cliente(nombre, monto, cantidad="1"):
    return {
        "cliente": nombre,
        "identificacion_cliente": f"V-{nombre}",
        "cantidad_total": Decimal(cantidad),
        "monto_total": Decimal(monto),
    }


def _fila(producto, codigo, clientes):
    return {
        "producto": producto,
        "cod_producto": codigo,
        "cantidad_total": sum((c["cantidad_total"] for c in clientes), Decimal("0")),
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
        "cantidad_general": sum((f["cantidad_total"] for f in filas), Decimal("0")),
    }


def _chips(panel):
    widgets = [panel.resumen_layout.itemAt(i).widget() for i in range(panel.resumen_layout.count())]
    return [w.text() for w in widgets if isinstance(w, QLabel)]


def _celdas_tabla(panel, fila):
    return [panel.tabla.item(fila, c).text() for c in range(panel.tabla.columnCount())]


def test_el_tipo_de_reporte_aparece_en_el_combo_con_sus_filtros(panel):
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

    assert [panel.tabla.horizontalHeaderItem(c).text() for c in range(5)] == rp.COLS_VENTAS_PRODUCTOS_CLIENTES
    assert _celdas_tabla(panel, 0) == ["Harina", "H-1", "1.00", "$50.00", "Ana ($50.00)"]
    assert _celdas_tabla(panel, 1) == ["Aceite", "A-1", "3.00", "$30.00", "Ana ($20.00), Beto ($10.00)"]
    assert panel.lbl_total.text() == "2 productos"
    assert _chips(panel) == ["Productos: 2", "Cantidad total: 4.00", "Monto total: $80.00"]


def test_vista_general_con_un_solo_producto_usa_singular(panel):
    panel._mostrar_ventas_productos_clientes(_resultado([_fila("Harina", "H-1", [_cliente("Ana", "50.00")])]))

    assert panel.lbl_total.text() == "1 producto"


def test_vista_general_limita_a_cinco_clientes_y_resume_el_resto(panel):
    clientes = [_cliente(f"C{i}", f"{100 - i}.00") for i in range(1, 8)]

    panel._mostrar_ventas_productos_clientes(_resultado([_fila("Aceite", "A-1", clientes)]))

    texto = panel.tabla.item(0, 4).text()
    assert "C5 ($95.00)" in texto
    assert "C6" not in texto
    assert texto.endswith("(+2 más)")


def test_vista_de_un_producto_lista_los_clientes_con_la_cantidad_vendida(panel):
    filas = [_fila("Aceite", "A-1", [_cliente("Ana", "20.00", "2"), _cliente("Beto", "10.00")])]

    panel._mostrar_ventas_productos_clientes(_resultado(filas, id_producto=5))

    assert [panel.tabla.horizontalHeaderItem(c).text() for c in range(3)] == [
        "Cliente",
        "Identificación",
        "Cantidad Vendida",
    ]
    assert _celdas_tabla(panel, 0) == ["Ana", "V-Ana", "2.00"]
    assert _celdas_tabla(panel, 1) == ["Beto", "V-Beto", "1.00"]
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
    assert columnas == rp.COLS_VENTAS_PRODUCTOS_CLIENTES
    assert filas == [["Aceite", "A-1", 3.0, 30.0, "Ana, Beto"]]


def test_exportar_pdf_incluye_vendedor_y_total_general(panel):
    panel._ultimo_modo = rp.REPORTE_VENTAS_PRODUCTOS_CLIENTES
    panel._ultimo_resultado = _resultado([_fila("Aceite", "A-1", [_cliente("Ana", "20.00", "2")])])

    titulo, filtros, anchos = panel._info_pdf()

    assert titulo == "Ventas a Clientes por Producto"
    assert filtros["Desde"] == "01/10/2026"
    assert filtros["Hasta"] == "16/10/2026"
    assert filtros["Vendedor"] == "Todos los vendedores"
    assert filtros["Total general"] == "$20.00"
    assert len(anchos) == len(rp.COLS_VENTAS_PRODUCTOS_CLIENTES)


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
        "total_base_imponible": Decimal("100.00"),
        "total_iva": Decimal("16.00"),
        "total_general": Decimal("116.00"),
        "notas_credito": [],
        "total_notas_credito": Decimal("0.00"),
    }

    panel._mostrar_resumen_libro_ventas(resultado)

    assert _chips(panel)[0] == "Ventas: 12"
    assert _chips(panel)[1] == "Base imponible: $100.00"
