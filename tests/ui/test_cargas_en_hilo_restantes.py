"""Cajas, Comisiones, historial de cliente, detalles de CxC/CxC BCV y la busqueda del formulario de factura: las
consultas corren en un hilo aparte (carga_asincrona.py) y la ventana solo pinta lo que llega.

Los tests usan el worker inmediato de tests/ui/conftest.py (la tarea corre en el acto) salvo los que prueban el
camino asincrono en si, que lo cambian por un worker falso que no ejecuta nada."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.ui.cajas_panel as cp
import app.ui.carga_asincrona as ca
import app.ui.comisiones_panel as comp
import app.ui.cuentas_por_cobrar_bcv_panel as bcv
import app.ui.cuentas_por_cobrar_panel as cxc
import app.ui.factura_form_dialog as ffd
import app.ui.historial_cliente_window as hw


class _WorkerFalso:
    """No lanza ningun hilo ni ejecuta la tarea: el test entrega la respuesta a mano."""

    creados: list = []

    def __init__(self, session_factory, tarea, *args, **kwargs):
        self.tarea, self.args, self.kwargs = tarea, args, kwargs
        self.silencioso = False
        self.resultado, self.finished = MagicMock(), MagicMock()
        _WorkerFalso.creados.append(self)

    def start(self):
        self.iniciado = True

    def isFinished(self):
        return True

    def wait(self, _ms):
        return True


@pytest.fixture()
def worker_falso(monkeypatch):
    _WorkerFalso.creados = []
    monkeypatch.setattr(ca, "QueryWorker", _WorkerFalso)
    return _WorkerFalso


# -- Cajas --------------------------------------------------------------------------------------------------------


def _estado(id_caja, estado="ABIERTA"):
    return {
        "id_caja": id_caja,
        "nombre_caja": f"Caja {id_caja}",
        "estado": estado,
        "cajero": "ana",
        "fecha_apertura": datetime(2026, 11, 7, 8, 30),
        "saldo_apertura": Decimal("100.00"),
        "saldo_cierre": None,
        "cantidad_movimientos": 3,
    }


def test_el_panel_de_cajas_pide_el_estado_en_un_hilo_y_lo_pinta_al_llegar(qtbot, monkeypatch, worker_falso):
    monkeypatch.setattr(cp.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    panel = cp.CajasPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)

    panel.cargar_cajas()

    worker = worker_falso.creados[-1]
    assert worker.iniciado and worker.tarea is ca._tarea_carga
    assert panel.tabla.rowCount() == 0  # todavia no llego
    panel._recibir_carga({"id_carga": 1, "clave": "cajas", "resultado": [_estado(1), _estado(2, "CERRADA")]})
    assert panel.tabla.rowCount() == 2
    assert panel.lbl_total.text() == "2 cajas"


def test_el_panel_de_cajas_con_el_worker_inmediato_deja_la_tabla_poblada(qtbot, monkeypatch):
    monkeypatch.setattr(cp.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(cp.CajaService, "obtener_estado_cajas", staticmethod(lambda *a, **k: [_estado(7)]))
    panel = cp.CajasPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)

    panel.cargar_cajas()

    assert panel.tabla.item(0, 1).text() == "Caja 7"


def _movimiento(i, tipo, monto):
    return SimpleNamespace(
        fecha_registro=datetime(2026, 11, 7, 9, i),
        tipo_movimiento=tipo,
        descripcion_movimiento=f"Mov {i}",
        monto_movimiento=Decimal(monto),
        id_pago_cobro=None,
        id_pago_cobro_bcv=None,
        id_pago_proveedor=None,
        id_pago_comision=None,
    )


@pytest.fixture()
def historial_caja(qtbot, monkeypatch):
    monkeypatch.setattr(cp.HistorialMovimientosDialog, "_cargar_historial", lambda self, *a, **k: None)
    dialogo = cp.HistorialMovimientosDialog(MagicMock(), 1, "Caja 1", SimpleNamespace(id_usuario=1))
    qtbot.addWidget(dialogo)
    return dialogo


def test_el_historial_de_caja_pinta_la_pagina_y_los_totales_de_todo_el_rango(historial_caja):
    resultado = {
        "items": [_movimiento(1, "entrada", "80.00"), _movimiento(2, "salida", "30.00")],
        "total": 120,
        "pagina": 1,
        "total_paginas": 3,
        "total_entradas": Decimal("5000.00"),
        "total_salidas": Decimal("1250.50"),
    }

    historial_caja._mostrar_historial(resultado)

    assert historial_caja.tabla.rowCount() == 2
    # los totales son de TODO el rango (120 movimientos), no de las 2 filas de la pagina
    assert "5,000.00" in historial_caja.lbl_total_entradas.text()
    assert "1,250.50" in historial_caja.lbl_total_salidas.text()
    assert "3,749.50" in historial_caja.lbl_saldo.text()
    assert "3" in historial_caja.paginacion.lbl_pagina.text()


def test_cambiar_el_rango_vuelve_a_la_primera_pagina(historial_caja, monkeypatch):
    pedidos = []
    monkeypatch.setattr(
        cp.HistorialMovimientosDialog, "_cargar_historial", lambda self, *a, **k: pedidos.append(self.paginacion.pagina)
    )
    historial_caja.paginacion.fijar_pagina(4)

    historial_caja._aplicar_filtro()

    assert pedidos == [1]


def test_la_tarea_del_historial_de_caja_pagina_y_suma_en_la_base(db_session):
    from datetime import date

    from app.db.models import CajaMovimiento
    from tests.factories import crear_caja, crear_usuario_admin

    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)
    cp.CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)
    for i in range(7):
        db_session.add(
            CajaMovimiento(
                id_caja=caja.id_caja,
                tipo_movimiento="entrada",
                descripcion_movimiento=f"E{i}",
                monto_movimiento=Decimal("10.00"),
                fecha_registro=datetime.now(),
            )
        )
    for i in range(3):
        db_session.add(
            CajaMovimiento(
                id_caja=caja.id_caja,
                tipo_movimiento="salida",
                descripcion_movimiento=f"S{i}",
                monto_movimiento=Decimal("4.00"),
                fecha_registro=datetime.now(),
            )
        )
    db_session.commit()
    hoy = date.today()

    pagina_1 = cp._tarea_historial_caja(db_session, caja.id_caja, hoy, hoy, 1)

    assert pagina_1["total"] == 10
    assert len(pagina_1["items"]) == 10 and pagina_1["total_paginas"] == 1
    assert pagina_1["total_entradas"] == Decimal("70.00")
    assert pagina_1["total_salidas"] == Decimal("12.00")
    otro_dia = date(2020, 1, 1)
    vacio = cp._tarea_historial_caja(db_session, caja.id_caja, otro_dia, otro_dia, 1)
    assert vacio["total"] == 0 and vacio["total_entradas"] == Decimal("0")


# -- Comisiones ---------------------------------------------------------------------------------------------------


def _panel_comisiones(qtbot, monkeypatch, gestion):
    monkeypatch.setattr(comp.UsuarioService, "verificar_permiso", staticmethod(lambda *a, **k: gestion))
    monkeypatch.setattr(comp.MessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(comp.MessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(comp.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    panel = comp.ComisionesPanel(MagicMock(), SimpleNamespace(id_usuario=1, id_vendedor_usuario=None))
    qtbot.addWidget(panel)
    return panel


def test_comisiones_en_gestion_llena_los_vendedores_y_pide_las_comisiones_del_primero(qtbot, monkeypatch):
    pedidas = []
    vendedores = [
        SimpleNamespace(id_vendedor=7, nombre_vendedor="Ana"),
        SimpleNamespace(id_vendedor=9, nombre_vendedor="Beto"),
    ]
    monkeypatch.setattr(comp.VendedorService, "listar", staticmethod(lambda *a, **k: {"items": vendedores}))
    monkeypatch.setattr(
        comp.ComisionService,
        "listar_comisiones_vendedor",
        staticmethod(lambda session, id_vendedor, **k: pedidas.append(id_vendedor) or []),
    )
    panel = _panel_comisiones(qtbot, monkeypatch, gestion=True)

    panel.cargar_datos()

    assert [panel.vendedor_combo.itemText(i) for i in range(panel.vendedor_combo.count())] == ["Ana", "Beto"]
    assert pedidas == [7]
    assert panel.id_vendedor_actual == 7


def test_comisiones_sin_vendedores_activos_no_pide_comisiones(qtbot, monkeypatch):
    monkeypatch.setattr(comp.VendedorService, "listar", staticmethod(lambda *a, **k: {"items": []}))
    espia = MagicMock(return_value=[])
    monkeypatch.setattr(comp.ComisionService, "listar_comisiones_vendedor", staticmethod(espia))
    panel = _panel_comisiones(qtbot, monkeypatch, gestion=True)

    panel.cargar_datos()

    assert panel.vendedor_combo.itemText(0) == "Sin vendedores activos"
    espia.assert_not_called()


def test_mis_comisiones_se_piden_en_un_hilo_y_se_pintan_al_llegar(qtbot, monkeypatch, worker_falso):
    panel = _panel_comisiones(qtbot, monkeypatch, gestion=False)
    pintadas = []
    panel._poblar_tabla = pintadas.append

    panel.cargar_datos()

    worker = worker_falso.creados[-1]
    assert worker.iniciado and pintadas == []  # todavia no llego
    panel._recibir_carga({"id_carga": 1, "clave": "comisiones", "resultado": ["c1", "c2"]})
    assert pintadas == [["c1", "c2"]] and panel.comisiones_cargadas == ["c1", "c2"]


def test_una_respuesta_vieja_de_comisiones_no_pisa_a_la_nueva(qtbot, monkeypatch, worker_falso):
    panel = _panel_comisiones(qtbot, monkeypatch, gestion=False)
    pintadas = []
    panel._poblar_tabla = pintadas.append
    panel.cargar_datos()
    panel.chk_sin_porcentaje_bcv.setChecked(True)  # pide otra vez con el filtro

    panel._recibir_carga({"id_carga": 1, "clave": "comisiones", "resultado": ["vieja"]})
    panel._recibir_carga({"id_carga": 2, "clave": "comisiones", "resultado": ["nueva"]})

    assert pintadas == [["nueva"]]


def test_el_filtro_de_estado_no_vuelve_a_consultar_la_base(qtbot, monkeypatch, worker_falso):
    panel = _panel_comisiones(qtbot, monkeypatch, gestion=False)
    panel.comisiones_cargadas = [SimpleNamespace(estado_pago="pendiente"), SimpleNamespace(estado_pago="pagada")]
    pintadas = []
    panel._poblar_tabla = pintadas.append
    panel.estado_combo.addItem("Pagadas", "pagada")

    panel.estado_combo.setCurrentIndex(panel.estado_combo.findData("pagada"))

    assert worker_falso.creados == []
    assert [c.estado_pago for c in pintadas[-1]] == ["pagada"]


# -- Historial de cliente -----------------------------------------------------------------------------------------


def test_el_historial_de_cliente_trae_todo_en_una_pasada_y_sin_permiso_de_notas_no_falla(monkeypatch):
    monkeypatch.setattr(hw, "obtener_historial_cliente", lambda session, id_cliente: ["h"])
    monkeypatch.setattr(hw, "obtener_saldo_total_pendiente", lambda session, id_cliente: Decimal("10.00"))
    monkeypatch.setattr(hw, "obtener_saldo_total_positivo", lambda session, id_cliente: Decimal("2.00"))

    def sin_permiso(*a, **k):
        raise hw.PermisoDenegadoError("notas_credito", "ver")

    monkeypatch.setattr(hw.NotaCreditoService, "listar_notas_credito_cliente", sin_permiso)

    datos = hw._tarea_historial_cliente(MagicMock(), 5, 1)

    assert datos == {
        "historial": ["h"],
        "saldo_total": Decimal("10.00"),
        "saldo_positivo": Decimal("2.00"),
        "notas": [],
    }


def test_el_historial_de_cliente_avisa_si_la_carga_falla_en_vez_de_dejar_la_tabla_vacia(qtbot, monkeypatch):
    avisos = []
    monkeypatch.setattr(hw.MessageBox, "critical", staticmethod(lambda *a, **k: avisos.append(a[1:])))

    def falla(session, id_cliente):
        raise RuntimeError("sin red")

    monkeypatch.setattr(hw, "obtener_historial_cliente", falla)
    win = hw.HistorialClienteWindow(
        MagicMock(return_value=MagicMock()), 1, SimpleNamespace(nombre_razon_social="X"), id_usuario=1
    )
    qtbot.addWidget(win)

    assert avisos and avisos[0][0] == "Error de conexión" and "sin red" in avisos[0][1]


# -- Detalle de CxC / CxC BCV ---------------------------------------------------------------------------------------


def _fabrica_de_sesiones():
    sesiones = []

    def fabrica():
        sesion = MagicMock()
        sesiones.append(sesion)
        return sesion

    return fabrica, sesiones


def test_el_detalle_de_cxc_se_consulta_en_un_hilo_y_el_dialogo_cierra_la_sesion(qtbot, monkeypatch):
    fabrica, sesiones = _fabrica_de_sesiones()
    cuenta = SimpleNamespace(factura=SimpleNamespace(cliente=SimpleNamespace(nombre_razon_social="Ana")))
    monkeypatch.setattr(cxc.PagoService, "listar_cuentas_por_cobrar", staticmethod(lambda *a, **k: {"items": [cuenta]}))
    abiertos = []

    class _Dialogo:
        se_realizo_cobro = False

        def __init__(self, session, cliente, cuentas, tasa, id_usuario, parent=None):
            abiertos.append((session, cliente, cuentas))

        def exec(self):
            return 0

    monkeypatch.setattr(cxc, "DetalleClienteDialog", _Dialogo)
    monkeypatch.setattr(cxc.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    panel = cxc.CuentasPorCobrarPanel(fabrica, SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    sesiones.clear()

    panel._mostrar_detalle_cliente(5)

    assert len(abiertos) == 1
    sesion_del_dialogo, cliente, cuentas = abiertos[0]
    assert cliente.nombre_razon_social == "Ana" and cuentas == [cuenta]
    # la sesion con la que se consulto es la que usa el dialogo, y se cierra al salir de el
    assert sesion_del_dialogo in sesiones
    sesion_del_dialogo.close.assert_called()


def test_el_detalle_de_cxc_sin_cuentas_avisa_y_cierra_la_sesion(qtbot, monkeypatch):
    fabrica, sesiones = _fabrica_de_sesiones()
    monkeypatch.setattr(cxc.PagoService, "listar_cuentas_por_cobrar", staticmethod(lambda *a, **k: {"items": []}))
    avisos = []
    monkeypatch.setattr(cxc.MessageBox, "information", staticmethod(lambda *a, **k: avisos.append(a[1])))
    monkeypatch.setattr(cxc, "DetalleClienteDialog", MagicMock(side_effect=AssertionError("no debe abrirse")))
    monkeypatch.setattr(cxc.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    panel = cxc.CuentasPorCobrarPanel(fabrica, SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    sesiones.clear()

    panel._mostrar_detalle_cliente(5)

    assert avisos == ["Sin detalle"]
    assert sesiones and all(s.close.called for s in sesiones)


def test_si_la_consulta_del_detalle_falla_la_sesion_que_creo_la_tarea_se_cierra(monkeypatch):
    fabrica, sesiones = _fabrica_de_sesiones()

    def falla(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(cxc.PagoService, "listar_cuentas_por_cobrar", staticmethod(falla))

    with pytest.raises(RuntimeError):
        cxc._tarea_detalle_cliente(MagicMock(), fabrica, 5, 1)

    assert len(sesiones) == 1 and sesiones[0].close.called


def test_una_respuesta_vieja_del_detalle_cierra_su_sesion_sin_abrir_el_dialogo(qtbot, monkeypatch, worker_falso):
    monkeypatch.setattr(cxc.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    panel = cxc.CuentasPorCobrarPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    abiertos = []
    panel._abrir_detalle_cliente = abiertos.append
    panel._mostrar_detalle_cliente(5)  # id 1
    panel._mostrar_detalle_cliente(6)  # id 2: el doble clic anterior queda obsoleto
    sesion_vieja = MagicMock()

    panel._recibir_carga(
        {
            "id_carga": 1,
            "clave": "detalle_cliente",
            "resultado": {"session": sesion_vieja, "cuentas": [], "cliente": None},
        }
    )

    assert abiertos == []
    sesion_vieja.close.assert_called_once()


def test_el_detalle_bcv_se_consulta_en_un_hilo_y_abre_el_dialogo_al_llegar(qtbot, monkeypatch, worker_falso):
    monkeypatch.setattr(bcv.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    panel = bcv.CuentasPorCobrarBCVPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    abiertos = []

    class _Dialogo:
        se_realizo_cobro = False

        def __init__(self, session_factory, cliente, cuentas, tasa, id_usuario, parent=None):
            abiertos.append((cliente, cuentas))

        def exec(self):
            return 0

    monkeypatch.setattr(bcv, "DetalleCuentasBCVDialog", _Dialogo)
    panel._mostrar_cuentas_cliente(SimpleNamespace(id_cliente=3, nombre_cliente="Ana"))
    assert abiertos == []  # todavia no llego

    sesion = MagicMock()
    # El panel ya pidio otras cargas al abrirse (la lista de vendedores): el id de la del detalle no es el 1.
    id_carga = panel._estado_carga()["cargas"]["detalle_cliente"]["id"]
    panel._recibir_carga(
        {
            "id_carga": id_carga,
            "clave": "detalle_cliente",
            "resultado": {"session": sesion, "cuentas": ["c"], "cliente": "cl"},
        }
    )

    assert abiertos == [("cl", ["c"])]
    sesion.close.assert_called_once()


# -- Busqueda del formulario de factura -----------------------------------------------------------------------------


def _servicios_del_formulario(monkeypatch):
    monkeypatch.setattr(ffd, "list_clientes", lambda *a, **k: {"items": []})
    monkeypatch.setattr(ffd.VendedorService, "listar", staticmethod(lambda *a, **k: {"items": []}))
    monkeypatch.setattr(ffd.ProductoService, "buscar", staticmethod(lambda *a, **k: {"items": []}))
    monkeypatch.setattr(ffd.PrecioService, "obtener_precio", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(ffd.TasaService, "obtener_tasa_actual", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(ffd.EmpresaService, "obtener_iva_vigente", staticmethod(lambda *a: (False, Decimal("0"))))
    monkeypatch.setattr(ffd.CajaService, "listar_cajas", staticmethod(lambda *a, **k: []))
    monkeypatch.setattr(ffd.BancoService, "listar_cuentas", staticmethod(lambda *a, **k: []))


@pytest.fixture()
def formulario(qtbot, monkeypatch):
    _servicios_del_formulario(monkeypatch)
    monkeypatch.setattr(ffd.MessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(ffd.MessageBox, "critical", staticmethod(lambda *a, **k: None))
    session = MagicMock()
    session.get.return_value = None
    dialogo = ffd.FacturaFormDialog(session, id_usuario=1, session_factory=MagicMock())
    qtbot.addWidget(dialogo)
    return dialogo


def test_la_busqueda_de_clientes_al_teclear_va_en_un_hilo_y_pinta_al_llegar(formulario, worker_falso):
    formulario.cliente_buscar_input.setText("Ana")

    formulario._buscar_clientes_tras_debounce()

    assert worker_falso.creados[-1].silencioso is True  # no enciende la barra de carga
    ana = SimpleNamespace(
        id_cliente=3,
        nombre_razon_social="Ana SA",
        id_legal="J",
        identificacion_cliente="1",
        estado_cliente="ACTIVO",
        dias_credito=0,
        limite_credito=0,
    )
    formulario._recibir_carga({"id_carga": 1, "clave": "clientes", "resultado": [ana]})
    assert formulario._clientes == [ana]
    assert formulario.cliente_combo.findData(3) >= 0


def test_enter_en_clientes_sigue_siendo_inmediato_y_anula_la_busqueda_en_vuelo(formulario, worker_falso, monkeypatch):
    formulario.cliente_buscar_input.setText("Ana")
    formulario._buscar_clientes_tras_debounce()  # en vuelo (id 1)
    ana = SimpleNamespace(
        id_cliente=3,
        nombre_razon_social="Ana SA",
        id_legal="J",
        identificacion_cliente="1",
        estado_cliente="ACTIVO",
        dias_credito=0,
        limite_credito=0,
    )
    monkeypatch.setattr(ffd, "list_clientes", lambda *a, **k: {"items": [ana]})

    formulario._on_cliente_buscar_return_pressed()

    assert formulario._clientes == [ana]  # ya esta, sin esperar al hilo
    formulario._recibir_carga({"id_carga": 1, "clave": "clientes", "resultado": []})  # la respuesta vieja llega tarde
    assert formulario._clientes == [ana]  # no repuebla el combo ni deshace la eleccion


def test_la_busqueda_de_productos_al_teclear_va_en_un_hilo(formulario, worker_falso):
    formulario.producto_buscar_input.setText("aceite")

    formulario._buscar_productos_tras_debounce()

    worker = worker_falso.creados[-1]
    assert worker.silencioso is True and worker.args[3]["texto"] == "aceite"
    producto = SimpleNamespace(
        id_producto=8,
        cod_producto="A-1",
        nombre_producto="Aceite",
        cantidad_unidad=10,
        cantidad_caja_total=0,
        articulo_bcv=False,
    )
    formulario._on_producto_cambiado = lambda: None  # el calculo de precios no es lo que se prueba aqui
    formulario._recibir_carga({"id_carga": 1, "clave": "productos", "resultado": [producto]})
    assert formulario._productos == [producto]


def test_sin_session_factory_la_busqueda_sigue_en_el_hilo_de_la_ventana(qtbot, monkeypatch, worker_falso):
    _servicios_del_formulario(monkeypatch)
    session = MagicMock()
    session.get.return_value = None
    dialogo = ffd.FacturaFormDialog(session, id_usuario=1)
    qtbot.addWidget(dialogo)
    worker_falso.creados.clear()

    dialogo._buscar_clientes_tras_debounce()
    dialogo._buscar_productos_tras_debounce()

    assert worker_falso.creados == []


# -- Mixin: dialogos y sesiones huerfanas ---------------------------------------------------------------------------


def test_cerrar_un_dialogo_espera_a_los_hilos_en_vuelo(qtbot, worker_falso):
    from PySide6.QtWidgets import QDialog

    class _Dialogo(ca.CargaAsincronaMixin, QDialog):
        session_factory = MagicMock()

    dialogo = _Dialogo()
    qtbot.addWidget(dialogo)
    dialogo.cargar_async("x", lambda s: 1, lambda r: None, texto_error="e")
    esperas = []
    worker_falso.creados[-1].wait = lambda ms: esperas.append(ms) or True

    dialogo.accept()

    assert esperas == [2000]
