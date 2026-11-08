"""facturacion_panel.py no tenia ningun test de UI hasta ahora. Cobertura minima: el
guard anti-reentrancia de ver_detalle_factura() agregado en el hallazgo 3.3 (auditoria
2026-09-05) -- ver test_bancos_panel.py para el motivo completo."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.ui.facturacion_panel as fp


def _crear_panel(qtbot, monkeypatch):
    # cargar_facturas() esta diferido via QTimer.singleShot en __init__ -- no corre
    # sincronicamente durante la construccion.
    monkeypatch.setattr(fp.MessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(fp.MessageBox, "warning", lambda *a, **k: None)
    panel = fp.FacturacionPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    return panel


def test_ver_detalle_factura_bloquea_reentrada_pero_no_queda_trabado(qtbot, monkeypatch):
    panel = _crear_panel(qtbot, monkeypatch)
    panel._fila_seleccionada_id = lambda: 1
    monkeypatch.setattr(fp.VentaService, "obtener_factura", staticmethod(lambda *a, **k: {}))

    llamadas_sesion = []

    def session_factory():
        llamadas_sesion.append(1)
        return MagicMock()

    panel.session_factory = session_factory

    dialogo_mock = MagicMock()

    def fake_exec():
        # Simula un segundo doble-click mientras el primero todavia esta abriendo el
        # detalle de la factura -- sin el guard, reentraria y abriria una segunda sesion.
        panel.ver_detalle_factura()
        return 0

    dialogo_mock.exec.side_effect = fake_exec
    monkeypatch.setattr(fp, "FacturaDetalleDialog", lambda *a, **k: dialogo_mock)

    panel.ver_detalle_factura()

    # una sesion para la consulta en el hilo y otra para el dialogo
    assert len(llamadas_sesion) == 2
    assert panel._abriendo_dialogo is False

    panel.ver_detalle_factura()
    assert len(llamadas_sesion) == 4


# -- El listado de facturas se consulta en un hilo aparte, sin congelar la ventana ------------------------


class _WorkerFalso:
    """Reemplaza a QueryWorker: registra con que se lo creo y no lanza ningun hilo."""

    creados: list = []

    def __init__(self, session_factory, tarea, *args, **kwargs):
        self.tarea, self.args, self.kwargs = tarea, args, kwargs
        self.silencioso = False
        self.resultado, self.error, self.finished = MagicMock(), MagicMock(), MagicMock()
        _WorkerFalso.creados.append(self)

    def start(self):
        self.iniciado = True

    def wait(self, _ms):
        return True


def _panel_con_worker_falso(qtbot, monkeypatch):
    _WorkerFalso.creados = []
    monkeypatch.setattr(fp, "QueryWorker", _WorkerFalso)
    monkeypatch.setattr(fp.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    return _crear_panel(qtbot, monkeypatch)


def test_cargar_facturas_consulta_en_un_hilo_con_los_filtros(qtbot, monkeypatch):
    panel = _panel_con_worker_falso(qtbot, monkeypatch)
    panel.buscar_input.setText("  FV-0005 ")

    panel.cargar_facturas()

    worker = _WorkerFalso.creados[-1]
    assert worker.iniciado and worker.tarea is fp._tarea_cargar_facturas
    assert worker.kwargs["texto_busqueda"] == "FV-0005"
    assert worker.kwargs["pagina"] == 1 and worker.kwargs["por_pagina"] == fp.POR_PAGINA
    assert worker.kwargs["id_usuario"] == 1
    assert worker.silencioso is False


def test_la_busqueda_mientras_se_escribe_no_enciende_la_barra_de_carga(qtbot, monkeypatch):
    panel = _panel_con_worker_falso(qtbot, monkeypatch)

    panel._buscar_desde_inicio()

    assert _WorkerFalso.creados[-1].silencioso is True


def test_una_respuesta_vieja_de_facturas_se_descarta(qtbot, monkeypatch):
    panel = _panel_con_worker_falso(qtbot, monkeypatch)
    pintados = []
    panel._poblar_tabla = pintados.append
    panel.cargar_facturas()
    panel.cargar_facturas()

    panel._on_facturas_cargadas({"id_carga": 1, "resultado": "viejo"})
    panel._on_facturas_cargadas({"id_carga": 2, "resultado": "vigente"})

    assert pintados == ["vigente"]


def test_el_refresco_periodico_carga_en_un_hilo_y_avisa_al_terminar_de_repoblar(qtbot, monkeypatch):
    panel = _panel_con_worker_falso(qtbot, monkeypatch)
    monkeypatch.setattr(panel, "_refrescar_estado_caja", lambda: None)
    orden = []
    panel._poblar_tabla = lambda resultado: orden.append(("tabla", resultado))
    # el refresco ya no consulta en el hilo de la interfaz
    monkeypatch.setattr(fp.VentaService, "listar_facturas", staticmethod(lambda *a, **k: pytest.fail("sincrono")))

    panel._refresco_periodico(lambda: orden.append("reseleccion"))

    worker = _WorkerFalso.creados[-1]
    assert worker.iniciado and worker.silencioso is True
    assert orden == []  # nada se pinto todavia: la ventana siguio libre mientras la base respondia
    panel._on_facturas_cargadas({"id_carga": panel._id_carga, "resultado": "listado"})
    assert orden == [("tabla", "listado"), "reseleccion"]  # la fila se vuelve a seleccionar con la tabla ya repoblada


def test_una_respuesta_vieja_no_dispara_la_reseleccion_del_refresco(qtbot, monkeypatch):
    panel = _panel_con_worker_falso(qtbot, monkeypatch)
    panel._poblar_tabla = lambda resultado: None
    llamadas = []
    panel.cargar_facturas(silencioso=True, al_terminar=lambda: llamadas.append(1))
    id_refresco = panel._id_carga
    panel.cargar_facturas()  # el usuario pidio otra cosa (busqueda, pagina) mientras tanto

    panel._on_facturas_cargadas({"id_carga": id_refresco, "resultado": "viejo"})

    assert llamadas == []


def test_el_refresco_periodico_consulta_la_caja_sin_detener_la_ventana(qtbot, monkeypatch):
    panel = _panel_con_worker_falso(qtbot, monkeypatch)
    monkeypatch.setattr(fp, "cajas_de_esta_estacion", lambda cajas: cajas)
    caja = SimpleNamespace(id_caja=3, nombre_caja="Caja 1", fecha_apertura="hoy", fecha_cierre=None)
    monkeypatch.setattr(fp.CajaService, "listar_cajas", staticmethod(lambda session, **k: [caja]))
    monkeypatch.setattr(panel, "_verificar_caja_abierta", lambda **k: pytest.fail("sincrono"))

    panel._refrescar_estado_caja()  # WorkerInmediato (conftest) corre la tarea en el acto

    assert panel.lbl_caja_estado.text() == "Caja abierta: Caja 1"


def test_la_tarea_de_estado_de_caja_ignora_las_cajas_cerradas_y_no_rompe_si_falla(monkeypatch):
    cerrada = SimpleNamespace(fecha_apertura="ayer", fecha_cierre="hoy")
    monkeypatch.setattr(fp, "cajas_de_esta_estacion", lambda cajas: cajas)
    monkeypatch.setattr(fp.CajaService, "listar_cajas", staticmethod(lambda session, **k: [cerrada]))
    assert fp._tarea_estado_caja(None, 1) == {"caja": None}

    def _falla(session, **k):
        raise RuntimeError("sin conexion")

    monkeypatch.setattr(fp.CajaService, "listar_cajas", staticmethod(_falla))
    assert fp._tarea_estado_caja(None, 1) == {"fallo": True}


def test_un_fallo_al_consultar_la_caja_deja_el_badge_como_estaba(qtbot, monkeypatch):
    panel = _panel_con_worker_falso(qtbot, monkeypatch)
    panel._actualizar_estado_caja(SimpleNamespace(nombre_caja="Caja 1", id_caja=3))

    panel._mostrar_estado_caja({"fallo": True})

    assert panel.lbl_caja_estado.text() == "Caja abierta: Caja 1"


def test_una_carga_sincrona_invalida_la_respuesta_asincrona_en_vuelo(qtbot, monkeypatch):
    panel = _panel_con_worker_falso(qtbot, monkeypatch)
    pintados = []
    panel._poblar_tabla = pintados.append
    monkeypatch.setattr(fp.VentaService, "listar_facturas", staticmethod(lambda session, **kw: "nuevo"))
    panel.cargar_facturas()  # en vuelo
    id_en_vuelo = panel._id_carga

    panel.cargar_facturas(sincrono=True)
    panel._on_facturas_cargadas({"id_carga": id_en_vuelo, "resultado": "viejo"})

    assert pintados == ["nuevo"]


def test_la_tarea_convierte_la_falta_de_permiso_en_un_resultado(monkeypatch):
    def _sin_permiso(session, **filtros):
        raise fp.PermisoDenegadoError("ventas", "ver")

    monkeypatch.setattr(fp.VentaService, "listar_facturas", staticmethod(_sin_permiso))

    assert fp._tarea_cargar_facturas(MagicMock(), 3) == {"id_carga": 3, "sin_permiso": True}


# -- El detalle de la factura se consulta en un hilo aparte y su guarda de doble clic se suelta siempre ----


def _panel_para_detalle(qtbot, monkeypatch, error):
    panel = _crear_panel(qtbot, monkeypatch)
    panel._fila_seleccionada_id = lambda: 1
    panel.session_factory = MagicMock

    def obtener(*a, **k):
        if error is not None:
            raise error
        return {}

    monkeypatch.setattr(fp.VentaService, "obtener_factura", staticmethod(obtener))
    return panel


def test_el_detalle_sin_permiso_avisa_y_suelta_la_guarda(qtbot, monkeypatch):
    panel = _panel_para_detalle(qtbot, monkeypatch, fp.PermisoDenegadoError("sin permiso"))
    avisos = []
    monkeypatch.setattr(fp.MessageBox, "warning", lambda *a, **k: avisos.append(a[1]))
    monkeypatch.setattr(fp, "FacturaDetalleDialog", lambda *a, **k: pytest.fail("no debe abrirse"))

    panel.ver_detalle_factura()

    assert avisos == ["Sin permiso"]
    assert panel._abriendo_dialogo is False


def test_el_detalle_de_una_factura_inexistente_avisa_y_suelta_la_guarda(qtbot, monkeypatch):
    panel = _panel_para_detalle(qtbot, monkeypatch, ValueError("Factura no encontrada"))
    avisos = []
    monkeypatch.setattr(fp.MessageBox, "warning", lambda *a, **k: avisos.append((a[1], a[2])))

    panel.ver_detalle_factura()

    assert avisos == [("No se pudo abrir la factura", "Factura no encontrada")]
    assert panel._abriendo_dialogo is False


def test_un_fallo_inesperado_del_detalle_avisa_y_suelta_la_guarda(qtbot, monkeypatch):
    panel = _panel_para_detalle(qtbot, monkeypatch, RuntimeError("se cayo la conexion"))
    errores = []
    monkeypatch.setattr(fp.MessageBox, "critical", lambda *a, **k: errores.append(a[1]))

    panel.ver_detalle_factura()

    assert errores == ["Error"]
    assert panel._abriendo_dialogo is False
