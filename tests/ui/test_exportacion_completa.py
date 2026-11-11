"""La exportacion de los listados paginados lleva TODAS las filas, no solo la pagina que se ve en pantalla.

Antes Cuentas por Cobrar, Cuentas por Pagar y las tres pestanas de Compras exportaban lo que decia la tabla: con 20
filas por pagina el archivo salia con 20 filas aunque hubiera cientos. Ahora la tarea vuelve a pedir el listado
completo al servicio con los filtros de la pantalla.
"""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openpyxl import load_workbook

from app.services.exportacion import valor_para_exportar
from app.ui import compras as cmp
from app.ui import cuentas_por_cobrar_panel as cxc
from app.ui import cuentas_por_pagar_panel as cxp
from app.ui import exportacion_completa as ec

TOTAL_FILAS = 45  # mas que dos paginas de 20


def _filas_del_archivo(ruta):
    hoja = load_workbook(ruta).active
    return [[c.value for c in fila] for fila in hoja.iter_rows()]


class _PedidoRegistrado:
    """Reemplaza al servicio de listado: devuelve TOTAL_FILAS items y recuerda con que filtros se le pidio."""

    def __init__(self, items):
        self.items = items
        self.llamadas = []

    def __call__(self, session, **kwargs):
        self.llamadas.append(kwargs)
        return {"items": self.items, "total": len(self.items), "pagina": 1, "por_pagina": 1, "total_paginas": 1}


# ── Cuentas por cobrar ───────────────────────────────────────────────────────


def _cliente_data(i):
    return {
        "cliente": SimpleNamespace(id_cliente=i, nombre_razon_social=f"Cliente {i:03d}"),
        "saldo_total": Decimal("10.50") * i,
        "saldo_favor": Decimal("0.00"),
        "saldo_vencido": Decimal("1.25"),
        "cuentas": [SimpleNamespace(estado="pendiente", fecha_vencimiento=date(2020, 1, 1))],
        "fecha_emision_mas_antigua_pendiente": date(2026, 10, 1),
        "dias_transcurridos": i,
    }


def test_cxc_exporta_todos_los_clientes_con_los_filtros_de_la_pantalla(monkeypatch, tmp_path):
    pedido = _PedidoRegistrado([_cliente_data(i) for i in range(1, TOTAL_FILAS + 1)])
    monkeypatch.setattr(cxc.PagoService, "listar_cuentas_por_cobrar_por_cliente", pedido)
    monkeypatch.setattr(cxc.EmpresaService, "obtener_datos_documento", lambda session: None)
    ruta = str(tmp_path / "cxc.xlsx")

    resultado = cxc._tarea_exportar_cuentas_cobrar(
        MagicMock(),
        ruta=ruta,
        formato="excel",
        id_usuario=7,
        estado="vencida",
        id_vendedor=3,
        texto_busqueda="ana",
        filtros_pdf={},
    )

    assert resultado == (ruta, TOTAL_FILAS)
    filtros = pedido.llamadas[0]
    assert filtros["por_pagina"] == ec.POR_PAGINA_EXPORTACION and filtros["pagina"] == 1
    assert (filtros["estado"], filtros["id_vendedor"], filtros["texto_busqueda"]) == ("vencida", 3, "ana")
    filas = _filas_del_archivo(ruta)
    # titulo/encabezados + una fila por cliente: todas, no solo 20
    assert sum(1 for f in filas if f[0] and str(f[0]).startswith("Cliente ")) == TOTAL_FILAS


def test_cxc_las_filas_del_archivo_son_las_celdas_de_la_tabla(qtbot, monkeypatch):
    monkeypatch.setattr(cxc.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(cxc.CuentasPorCobrarPanel, "cargar_cuentas", lambda self: None)
    panel = cxc.CuentasPorCobrarPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    items = [_cliente_data(i) for i in (1, 2, 3)]
    panel._poblar_tabla({"items": items, "total": 3, "pagina": 1, "por_pagina": 20, "total_paginas": 1})

    esperado = []
    for fila in range(panel.tabla.rowCount()):
        celdas = [valor_para_exportar(panel.tabla.item(fila, c).text()) for c in range(1, 7)]
        celdas.append(panel.tabla.cellWidget(fila, 7).findChild(type(panel.lbl_total)).text())
        esperado.append(celdas)

    assert cxc.filas_exportacion_cuentas_cobrar(items) == esperado


def test_cxc_el_boton_pide_la_exportacion_completa_con_los_filtros(qtbot, monkeypatch):
    monkeypatch.setattr(cxc.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(cxc.CuentasPorCobrarPanel, "cargar_cuentas", lambda self: None)
    panel = cxc.CuentasPorCobrarPanel(MagicMock(), SimpleNamespace(id_usuario=9))
    qtbot.addWidget(panel)
    panel._poblar_tabla({"items": [_cliente_data(1)], "total": 100, "pagina": 1, "por_pagina": 20, "total_paginas": 5})
    # Sin disparar la busqueda diferida: correria despues, contra una Session de mentira, y abriria un aviso modal.
    panel.buscar_input.blockSignals(True)
    panel.buscar_input.setText("  ana ")
    monkeypatch.setattr(cxc.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("x.xlsx", "")))
    pedidos = []
    monkeypatch.setattr(panel, "_exportar_listado_completo", lambda *a, **k: pedidos.append((a, k)))

    panel._exportar_excel()

    (tarea, ruta, boton), kwargs = pedidos[0]
    assert tarea is cxc._tarea_exportar_cuentas_cobrar and ruta == "x.xlsx" and boton is panel.btn_exportar
    assert kwargs["formato"] == "excel" and kwargs["id_usuario"] == 9 and kwargs["texto_busqueda"] == "ana"


# ── Cuentas por pagar ────────────────────────────────────────────────────────


def _cuenta_pagar(i):
    return SimpleNamespace(
        id_cuenta=i,
        compra=SimpleNamespace(
            numero_compra=f"C-{i:04d}", proveedor=SimpleNamespace(nombre_razon_social=f"Proveedor {i}"), oc=None
        ),
        saldo_pendiente=Decimal("20.00"),
        fecha_emision=date(2026, 10, 1),
        fecha_vencimiento=date(2026, 11, 1),
        estado="pendiente",
    )


def test_cxp_exporta_todas_las_cuentas_y_suma_el_total_de_todas(monkeypatch, tmp_path):
    pedido = _PedidoRegistrado([_cuenta_pagar(i) for i in range(1, TOTAL_FILAS + 1)])
    monkeypatch.setattr(cxp.PagoService, "listar_cuentas_por_pagar", pedido)
    monkeypatch.setattr(cxp.EmpresaService, "obtener_datos_documento", lambda session: None)
    ruta = str(tmp_path / "cxp.xlsx")

    resultado = cxp._tarea_exportar_cuentas_pagar(
        MagicMock(), ruta=ruta, formato="excel", id_usuario=7, estado="pendiente", texto_busqueda="prov", filtros_pdf={}
    )

    assert resultado == (ruta, TOTAL_FILAS)
    filtros = pedido.llamadas[0]
    assert filtros["por_pagina"] == ec.POR_PAGINA_EXPORTACION
    assert (filtros["estado"], filtros["texto_busqueda"]) == ("pendiente", "prov")
    filas = _filas_del_archivo(ruta)
    assert sum(1 for f in filas if f[0] and str(f[0]).startswith("C-")) == TOTAL_FILAS
    fila_total = next(f for f in filas if f[0] == "TOTAL:")
    assert Decimal(str(fila_total[2])) == Decimal("20.00") * TOTAL_FILAS


def test_cxp_las_filas_del_archivo_son_las_celdas_de_la_tabla(qtbot, monkeypatch):
    monkeypatch.setattr(cxp.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(cxp.CuentasPorPagarPanel, "cargar_cuentas", lambda self: None)
    panel = cxp.CuentasPorPagarPanel(MagicMock(), SimpleNamespace(id_usuario=5))
    qtbot.addWidget(panel)
    cuentas = [_cuenta_pagar(i) for i in (1, 2)]
    panel._poblar_tabla({"items": cuentas, "total": 2, "pagina": 1, "por_pagina": 20, "total_paginas": 1})

    esperado = []
    for fila in range(panel.tabla.rowCount()):
        celdas = [valor_para_exportar(panel.tabla.item(fila, c).text()) for c in range(1, 7)]
        celdas.append(panel.tabla.cellWidget(fila, 7).findChild(type(panel.lbl_total)).text())
        esperado.append(celdas)

    assert cxp.filas_exportacion_cuentas_pagar(cuentas) == esperado


# ── Compras: las tres pestanas ───────────────────────────────────────────────


def _oc(i):
    return SimpleNamespace(
        numero_oc=f"OC-{i:04d}",
        proveedor=SimpleNamespace(nombre_razon_social="Proveedor"),
        fecha_oc=datetime(2026, 10, 1),
        cantidad_solicitada=Decimal("10"),
        cantidad_recibida=Decimal("4"),
        total_oc=Decimal("100.00"),
        estado="PENDIENTE",
    )


def _nr(i):
    return SimpleNamespace(
        numero_nr=f"NR-{i:04d}",
        oc=SimpleNamespace(numero_oc="OC-1", proveedor=SimpleNamespace(nombre_razon_social="Proveedor")),
        fecha_recepcion=datetime(2026, 10, 1),
        usuario_recepcion=SimpleNamespace(nombre="Ana"),
        estado="COMPLETA",
    )


def _compra(i):
    return SimpleNamespace(
        numero_compra=f"FC-{i:04d}",
        oc=SimpleNamespace(numero_oc="OC-1"),
        proveedor=SimpleNamespace(nombre_razon_social="Proveedor"),
        fecha_emision=date(2026, 10, 1),
        condicion_pago="credito",
        total_compra=Decimal("55.00"),
        estado_compra="EMITIDA",
    )


@pytest.mark.parametrize(
    ("tipo", "fabrica", "prefijo", "servicio"),
    [
        ("oc", _oc, "OC-", "CompraOCService.listar_ocs"),
        ("nr", _nr, "NR-", "NotaRecepcionService.listar_notas_recepcion"),
        ("compra", _compra, "FC-", "CompraService.listar_compras"),
    ],
)
def test_compras_cada_pestana_exporta_todas_sus_filas(monkeypatch, tmp_path, tipo, fabrica, prefijo, servicio):
    clase, metodo = servicio.split(".")
    pedido = _PedidoRegistrado([fabrica(i) for i in range(1, TOTAL_FILAS + 1)])
    monkeypatch.setattr(getattr(cmp, clase), metodo, pedido)
    monkeypatch.setattr(cmp.EmpresaService, "obtener_datos_documento", lambda session: None)
    ruta = str(tmp_path / "compras.xlsx")

    resultado = cmp._tarea_exportar_compras(
        MagicMock(),
        ruta=ruta,
        tipo=tipo,
        formato="excel",
        id_usuario=7,
        filtros_servicio={"texto_busqueda": "abc", "estado": "X"},
        filtros_pdf={},
    )

    assert resultado == (ruta, TOTAL_FILAS)
    filtros = pedido.llamadas[0]
    assert filtros["por_pagina"] == ec.POR_PAGINA_EXPORTACION and filtros["id_usuario"] == 7
    assert (filtros["texto_busqueda"], filtros["estado"]) == ("abc", "X")
    filas = _filas_del_archivo(ruta)
    assert sum(1 for f in filas if f[0] and str(f[0]).startswith(prefijo)) == TOTAL_FILAS


# ── El mixin: hilo, boton ocupado y avisos ───────────────────────────────────


class _WorkerInmediato:
    def __init__(self, session_factory, tarea, *args, **kwargs):
        self._session_factory, self._tarea, self._kwargs = session_factory, tarea, kwargs
        self.resultado, self.error = _Senal(), _Senal()

    def isRunning(self):
        return False

    def start(self):
        try:
            valor = self._tarea(self._session_factory(), **self._kwargs)
        except Exception as exc:  # noqa: BLE001 - el worker real tambien entrega el error como texto
            self.error.emit(str(exc))
        else:
            self.resultado.emit(valor)


class _Senal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, valor):
        for slot in self._slots:
            slot(valor)


class _PanelFalso(ec.ExportacionCompletaMixin):
    def __init__(self):
        self.session_factory = MagicMock


def test_el_mixin_ocupa_el_boton_y_avisa_la_cantidad_exportada(monkeypatch):
    monkeypatch.setattr(ec, "QueryWorker", _WorkerInmediato)
    eventos = []
    monkeypatch.setattr(ec, "ocupar_boton", lambda boton: eventos.append(("ocupar", boton)))
    monkeypatch.setattr(ec, "liberar_boton", lambda boton: eventos.append(("liberar", boton)))
    monkeypatch.setattr(ec.MessageBox, "information", lambda *a, **k: eventos.append(("aviso", a[1], a[2])))
    panel, boton = _PanelFalso(), object()

    panel._exportar_listado_completo(lambda session, ruta: (ruta, 45), "a.xlsx", boton, nombre_filas="clientes")

    assert eventos == [
        ("ocupar", boton),
        ("liberar", boton),
        ("aviso", "Exportación exitosa", "Se exportaron 45 clientes a:\na.xlsx"),
    ]


def test_el_mixin_libera_el_boton_y_avisa_si_la_exportacion_falla(monkeypatch):
    monkeypatch.setattr(ec, "QueryWorker", _WorkerInmediato)
    eventos = []
    monkeypatch.setattr(ec, "ocupar_boton", lambda boton: eventos.append("ocupar"))
    monkeypatch.setattr(ec, "liberar_boton", lambda boton: eventos.append("liberar"))
    monkeypatch.setattr(ec.MessageBox, "critical", lambda *a, **k: eventos.append(("error", a[2])))

    def tarea_que_falla(session, ruta):
        raise OSError("disco lleno")

    _PanelFalso()._exportar_listado_completo(tarea_que_falla, "a.xlsx", object())

    assert eventos == ["ocupar", "liberar", ("error", "No se pudo completar la exportación.")]


def test_el_mixin_ignora_un_segundo_clic_mientras_exporta(monkeypatch):
    monkeypatch.setattr(ec, "QueryWorker", _WorkerInmediato)
    panel = _PanelFalso()
    panel._worker_export = SimpleNamespace(isRunning=lambda: True)
    lanzadas = []

    panel._exportar_listado_completo(lambda session, ruta: lanzadas.append(ruta), "a.xlsx", object())

    assert lanzadas == []


# ── Fila de TOTALES y filtro de vendedor en las exportaciones de Cuentas por Cobrar ──────────────────────────────


def test_cxc_la_fila_de_totales_suma_saldo_pendiente_favor_y_vencido():
    filas = cxc.filas_exportacion_cuentas_cobrar([_cliente_data(1), _cliente_data(2)])

    totales = cxc._fila_totales_cuentas_cobrar(filas)

    assert totales[0] is None and totales[4:] == [None, None, None]  # solo suma las tres columnas de montos
    assert totales[1:4] == [Decimal("31.50"), Decimal("0.00"), Decimal("2.50")]  # 10.50 + 21.00 | 0 | 1.25 + 1.25


def test_cxc_la_fila_de_totales_ignora_celdas_que_no_son_numeros():
    filas = [
        ["A", Decimal("5.00"), "n/a", Decimal("1.00"), "1", "x", "y"],
        ["B", Decimal("2.50"), 4, None, "1", "x", "y"],
    ]

    assert cxc._fila_totales_cuentas_cobrar(filas)[1:4] == [Decimal("7.50"), Decimal("4"), Decimal("1.00")]


@pytest.mark.parametrize("formato", ["excel", "pdf"])
def test_cxc_la_exportacion_agrega_la_fila_de_totales(monkeypatch, tmp_path, formato):
    monkeypatch.setattr(
        cxc.PagoService,
        "listar_cuentas_por_cobrar_por_cliente",
        _PedidoRegistrado([_cliente_data(1), _cliente_data(2)]),
    )
    monkeypatch.setattr(cxc.EmpresaService, "obtener_datos_documento", lambda session: None)
    recibido = {}
    monkeypatch.setattr(cxc, "exportar_excel", lambda *a, **k: recibido.update(k))
    monkeypatch.setattr(cxc, "exportar_pdf", lambda *a, **k: recibido.update(k))

    cxc._tarea_exportar_cuentas_cobrar(
        MagicMock(),
        ruta=str(tmp_path / "x"),
        formato=formato,
        id_usuario=1,
        estado=None,
        id_vendedor=None,
        texto_busqueda=None,
        filtros_pdf={},
    )

    assert recibido["total_label"] == "TOTALES"
    assert recibido["total_row"][1:4] == [Decimal("31.50"), Decimal("0.00"), Decimal("2.50")]


def test_cxc_el_excel_trae_los_totales_en_la_ultima_fila(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cxc.PagoService,
        "listar_cuentas_por_cobrar_por_cliente",
        _PedidoRegistrado([_cliente_data(1), _cliente_data(2)]),
    )
    monkeypatch.setattr(cxc.EmpresaService, "obtener_datos_documento", lambda session: None)
    ruta = str(tmp_path / "cxc.xlsx")

    cxc._tarea_exportar_cuentas_cobrar(
        MagicMock(),
        ruta=ruta,
        formato="excel",
        id_usuario=1,
        estado=None,
        id_vendedor=None,
        texto_busqueda=None,
        filtros_pdf={},
    )

    ultima = [f for f in _filas_del_archivo(ruta) if any(c is not None for c in f)][-1]
    assert ultima[0] == "TOTALES" and ultima[1:4] == [31.5, 0, 2.5]


# ── CxC BCV: totales y filtros del encabezado ──


def _item_bcv(pendiente, favor, vencido):
    return SimpleNamespace(saldo_pendiente=pendiente, saldo_favor=favor, saldo_vencido_bcv=vencido)


def test_bcv_la_fila_de_totales_suma_las_tres_columnas_de_saldo():
    from app.ui import cuentas_por_cobrar_bcv_panel as bcv

    items = [
        _item_bcv(Decimal("10.00"), Decimal("1.00"), Decimal("4.00")),
        _item_bcv(Decimal("5.50"), Decimal("0"), Decimal("0")),
    ]

    fila = bcv.CuentasPorCobrarBCVPanel._fila_totales_cuentas_bcv(items, 6)

    assert fila == ["", 15.5, 1.0, 4.0, "", ""]  # el resto de las columnas queda vacio


def test_bcv_la_fila_de_totales_sin_clientes_es_cero():
    from app.ui import cuentas_por_cobrar_bcv_panel as bcv

    assert bcv.CuentasPorCobrarBCVPanel._fila_totales_cuentas_bcv([], 4) == ["", 0.0, 0.0, 0.0]


def _panel_bcv(qtbot, monkeypatch):
    from app.ui import cuentas_por_cobrar_bcv_panel as bcv

    monkeypatch.setattr(bcv.CuentasPorCobrarBCVPanel, "cargar_cuentas", lambda self, *a, **k: None)
    panel = bcv.CuentasPorCobrarBCVPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    panel._llenar_vendedores([(3, "Ana Vendedora")])
    return panel


def test_bcv_los_filtros_del_encabezado_dicen_estado_y_vendedor_solo_si_hay(qtbot, monkeypatch):
    from app.ui import cuentas_por_cobrar_bcv_panel as bcv

    panel = _panel_bcv(qtbot, monkeypatch)
    assert panel._filtros_exportacion_cuentas_bcv() == {}

    panel.estado_combo.setCurrentIndex(panel.estado_combo.findData("vencida"))  # como lo elige el usuario
    panel.vendedor_combo.setCurrentIndex(panel.vendedor_combo.findData(3))
    filtros = panel._filtros_exportacion_cuentas_bcv()

    assert filtros == {
        "Estado": next(etiqueta for etiqueta, valor in bcv.ESTADOS_FILTRO if valor == "vencida"),  # la etiqueta legible
        "Vendedor": "Ana Vendedora",
    }
