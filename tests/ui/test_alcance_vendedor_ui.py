"""Pantallas: filtro de vendedor en Facturacion y en los reportes que le sirven al vendedor, y un usuario vendedor ve el
combo fijo en lo suyo (el servicio igual solo le devuelve lo suyo: ver tests/services/test_alcance_vendedor.py)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QComboBox

import app.ui.carga_asincrona as ca
import app.ui.clientes_panel as cp
import app.ui.cuentas_por_cobrar_bcv_panel as bcv
import app.ui.cuentas_por_cobrar_panel as cxc
import app.ui.facturacion_panel as fp
import app.ui.reportes_panel as rp
from app.ui.filtros_catalogo import fijar_vendedor_propio, llenar_combo_vendedores

ADMIN = SimpleNamespace(id_usuario=1, id_vendedor_usuario=None)
VENDEDOR = SimpleNamespace(id_usuario=2, id_vendedor_usuario=5)
VENDEDORES = [(3, "Ana"), (5, "Beto"), (9, "Carla")]


# ── Combo fijo para un vendedor ───────────────────────────────────────────────────────────────


def test_el_combo_de_un_vendedor_queda_fijo_en_el_y_deshabilitado(qtbot):
    combo = QComboBox()
    qtbot.addWidget(combo)
    cambios = []
    combo.currentIndexChanged.connect(cambios.append)

    llenar_combo_vendedores(combo, VENDEDORES, VENDEDOR)

    assert combo.currentData() == 5 and combo.currentText() == "Beto"
    assert not combo.isEnabled() and combo.toolTip() == "Solo ves lo tuyo"
    assert cambios == []  # no es un cambio del usuario: no repite la busqueda


def test_el_combo_de_un_admin_sigue_libre(qtbot):
    combo = QComboBox()
    qtbot.addWidget(combo)

    llenar_combo_vendedores(combo, VENDEDORES, ADMIN)

    assert combo.isEnabled() and combo.currentData() is None and combo.count() == 4


def test_sin_usuario_el_combo_tampoco_se_bloquea(qtbot):
    combo = QComboBox()
    qtbot.addWidget(combo)

    assert fijar_vendedor_propio(combo, None) is False
    assert fijar_vendedor_propio(combo, SimpleNamespace(id_usuario=1)) is False  # un usuario sin el atributo
    assert combo.isEnabled()


def test_si_el_vendedor_ya_no_esta_en_la_lista_el_combo_igual_se_deshabilita(qtbot):
    combo = QComboBox()
    qtbot.addWidget(combo)

    llenar_combo_vendedores(combo, [(3, "Ana")], VENDEDOR)  # su vendedor (5) no vino

    assert not combo.isEnabled()  # no puede elegir a otro


# ── Facturacion ───────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def facturacion(qtbot, monkeypatch):
    monkeypatch.setattr(fp.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(fp.FacturacionPanel, "cargar_facturas", lambda self, *a, **k: None)

    def crear(usuario=ADMIN):
        panel = fp.FacturacionPanel(MagicMock(), usuario)
        qtbot.addWidget(panel)
        panel._auto_refresco.timer.stop()
        return panel

    return crear


def test_facturacion_tiene_el_filtro_de_vendedor_y_lo_manda_al_listado_y_a_la_exportacion(facturacion):
    panel = facturacion()
    panel._llenar_vendedores(VENDEDORES)
    panel.vendedor_combo.setCurrentIndex(panel.vendedor_combo.findData(9))

    assert panel._filtros_listado()["id_vendedor"] == 9
    assert panel._filtros_actuales_exportar()["id_vendedor"] == 9


def test_facturacion_sin_elegir_vendedor_no_filtra(facturacion):
    panel = facturacion()
    panel._llenar_vendedores(VENDEDORES)

    assert panel._filtros_listado()["id_vendedor"] is None


def test_facturacion_de_un_vendedor_tiene_el_combo_fijo(facturacion):
    panel = facturacion(VENDEDOR)

    panel._llenar_vendedores(VENDEDORES)

    assert panel.vendedor_combo.currentData() == 5 and not panel.vendedor_combo.isEnabled()
    assert panel._filtros_listado()["id_vendedor"] == 5


def test_facturacion_pide_los_vendedores_en_un_hilo_al_abrirse(qtbot, monkeypatch):
    monkeypatch.setattr(fp.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(fp.FacturacionPanel, "cargar_facturas", lambda self, *a, **k: None)
    pedidos = []
    monkeypatch.setattr(ca, "QueryWorker", lambda *a, **k: pedidos.append(a) or MagicMock(silencioso=False))
    sesiones = MagicMock()

    panel = fp.FacturacionPanel(sesiones, ADMIN)
    qtbot.addWidget(panel)
    panel._auto_refresco.timer.stop()

    sesiones.assert_not_called()  # ninguna consulta en el hilo de la ventana
    assert any(a[1] is ca._tarea_carga for a in pedidos)


def test_las_tareas_de_exportacion_de_facturas_pasan_el_vendedor_al_servicio(monkeypatch, tmp_path):
    recibido = []

    def listar(session, **kwargs):
        recibido.append(kwargs)
        return {"items": []}

    monkeypatch.setattr(fp.VentaService, "listar_facturas", staticmethod(listar))
    monkeypatch.setattr(fp, "exportar_excel", lambda *a, **k: None)
    monkeypatch.setattr(fp, "exportar_pdf", lambda *a, **k: None)

    fp._tarea_exportar_facturas_excel(MagicMock(), str(tmp_path / "a.xlsx"), None, None, None, 1, id_vendedor=9)
    fp._tarea_exportar_facturas_pdf(MagicMock(), str(tmp_path / "a.pdf"), None, None, None, 1, id_vendedor=9)

    assert [k["id_vendedor"] for k in recibido] == [9, 9]


# ── Clientes y Cuentas por Cobrar ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("modulo, clase", [(cxc, "CuentasPorCobrarPanel"), (bcv, "CuentasPorCobrarBCVPanel")])
def test_cuentas_por_cobrar_de_un_vendedor_tiene_el_combo_fijo(qtbot, monkeypatch, modulo, clase):
    monkeypatch.setattr(getattr(modulo, clase), "cargar_cuentas", lambda self, *a, **k: None)
    panel = getattr(modulo, clase)(MagicMock(), VENDEDOR)
    qtbot.addWidget(panel)

    panel._llenar_vendedores(VENDEDORES)

    assert panel.vendedor_combo.currentData() == 5 and not panel.vendedor_combo.isEnabled()


def test_clientes_de_un_vendedor_tiene_el_combo_fijo_y_no_consulta_al_abrirse(qtbot, monkeypatch):
    monkeypatch.setattr(cp.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(cp.ClientesPanel, "cargar_clientes", lambda self, *a, **k: None)
    trabajos = []

    class _Hilo:
        def __init__(self, session_factory, tarea, *a, **k):
            trabajos.append(tarea)
            self.resultado, self.finished, self.error = MagicMock(), MagicMock(), MagicMock()
            self.silencioso = False

        def start(self):
            pass

        def isRunning(self):
            return False

        def wait(self, _ms):
            return True

    monkeypatch.setattr(cp, "QueryWorker", _Hilo)
    sesiones = MagicMock()

    panel = cp.ClientesPanel(sesiones, VENDEDOR)
    qtbot.addWidget(panel)
    sesiones.assert_not_called()  # antes consultaba los vendedores en el hilo de la ventana
    assert cp.tarea_vendedores_para_filtro in trabajos and cp.tarea_categorias_cliente_para_filtro in trabajos

    panel._llenar_vendedores(VENDEDORES)
    panel._llenar_categorias([(1, "Mayorista")])
    assert panel.vendedor_combo.currentData() == 5 and not panel.vendedor_combo.isEnabled()
    assert panel._filtros_actuales_exportar()["id_vendedor"] == 5
    assert panel.categoria_combo.itemText(1) == "Mayorista" and panel.categoria_combo.currentData() is None


# ── Reportes ──────────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def reportes(qtbot, monkeypatch):
    monkeypatch.setattr(rp.QTimer, "singleShot", staticmethod(lambda *a, **k: None))

    def crear(usuario=ADMIN):
        panel = rp.ReportesPanel(MagicMock(), usuario)
        qtbot.addWidget(panel)
        return panel

    return crear


CON_FILTRO_DE_VENDEDOR = {
    rp.REPORTE_LIBRO_VENTAS: "vendedor_combo_lv",
    rp.REPORTE_VENTAS_PERIODO: "vendedor_combo_vp",
    rp.REPORTE_PRODUCTOS_VENDIDOS: "vendedor_combo_pv",
    rp.REPORTE_CLIENTES_MOROSOS: "vendedor_combo_mor",
    rp.REPORTE_COBROS_PERIODO: "vendedor_combo_cbp",
}


@pytest.mark.parametrize("modo, nombre", sorted(CON_FILTRO_DE_VENDEDOR.items()))
def test_los_reportes_de_ventas_y_cobranza_tienen_el_filtro_de_vendedor(reportes, modo, nombre):
    panel = reportes()
    panel._asegurar_pagina(modo)

    combo = getattr(panel, nombre)

    assert combo.parent() is not None
    panel._llenar_catalogos(_catalogos())
    assert [combo.itemText(i) for i in range(combo.count())] == ["Todos los vendedores", "Ana", "Beto", "Carla"]


@pytest.mark.parametrize("modo, nombre", sorted(CON_FILTRO_DE_VENDEDOR.items()))
def test_elegir_un_vendedor_lo_manda_a_la_consulta_del_reporte(reportes, monkeypatch, modo, nombre):
    registro = []

    class _Hilo:
        def __init__(self, session_factory, tarea, *a, **k):
            registro.append((tarea, a, k))
            self.resultado, self.error, self.finished = MagicMock(), MagicMock(), MagicMock()
            self.silencioso = False

        def start(self):
            pass

        def isRunning(self):
            return False

        def wait(self, _ms):
            return True

    monkeypatch.setattr(rp, "QueryWorker", _Hilo)
    panel = reportes()
    panel.tipo_combo.setCurrentIndex(panel.tipo_combo.findData(modo))
    panel._llenar_catalogos(_catalogos())
    combo = getattr(panel, nombre)
    combo.setCurrentIndex(combo.findData(5))
    registro.clear()

    panel._generar()

    _tarea, args, kwargs = registro[-1]
    # en los paginados la tarea corta el reporte completo (`_tarea_paginada(tarea, pagina, por_pagina, **filtros)`)
    assert kwargs["id_vendedor"] == 5, (modo, kwargs)


def test_un_usuario_vendedor_solo_ve_los_reportes_acotados_a_lo_suyo(reportes):
    panel = reportes(VENDEDOR)

    modos = {panel.tipo_combo.itemData(i) for i in range(panel.tipo_combo.count())}

    assert modos and modos <= rp.REPORTES_DE_VENDEDOR
    assert rp.REPORTE_LIBRO_VENTAS in modos and rp.REPORTE_COBROS_PERIODO in modos
    for ajeno in (
        rp.REPORTE_COMPRAS_PERIODO,
        rp.REPORTE_ARQUEO_CAJA,
        rp.REPORTE_MOV_CUENTA_BANCARIA,
        rp.REPORTE_VALORIZACION,
    ):
        assert ajeno not in modos


def test_un_admin_sigue_viendo_todos_los_reportes(reportes):
    panel = reportes(ADMIN)

    assert panel.tipo_combo.count() > len(rp.REPORTES_DE_VENDEDOR)
    assert panel.tipo_combo.findData(rp.REPORTE_COMPRAS_PERIODO) >= 0


def test_en_los_reportes_el_combo_de_vendedor_de_un_vendedor_queda_fijo(reportes):
    panel = reportes(VENDEDOR)
    panel._asegurar_pagina(rp.REPORTE_LIBRO_VENTAS)
    panel._asegurar_pagina(rp.REPORTE_AGING_CXC)

    panel._llenar_catalogos(_catalogos())

    for nombre in ("vendedor_combo_lv", "vendedor_combo_aging"):
        combo = getattr(panel, nombre)
        assert combo.currentData() == 5 and not combo.isEnabled(), nombre


def _catalogos():
    return {
        "clientes": [(1, "Cliente")],
        "proveedores": [],
        "cajas": [],
        "vendedores": VENDEDORES,
        "cajeros": [],
        "productos": [],
        "categorias": [],
        "cuentas": [],
    }
