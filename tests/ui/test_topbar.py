"""Tests de la TopBar: buscador global y campana de notificaciones.

El servicio de búsqueda se monkeypatchea (misma razón que test_config_empresa_panel.py): acá
se prueba el cableado UI -- debounce, módulos, lista de resultados, navegación -- no las
consultas, que ya cubre tests/services/test_busqueda_global.py. El QueryWorker real se
reemplaza por uno síncrono para no depender de hilos en el test."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from PySide6.QtCore import QSize, Qt

from app.services.busqueda_global import ResultadoBusqueda
from app.services.notificaciones import (
    SEVERIDAD_ALTA,
    SEVERIDAD_INFO,
    SEVERIDAD_MEDIA,
    Notificacion,
)
from app.ui import topbar as topbar_mod
from app.ui.topbar import TopBar


class _WorkerSincrono:
    """Ejecuta la tarea en start(), en el mismo hilo, y emite como lo haria QueryWorker."""

    class _Senal:
        def __init__(self):
            self._slots = []

        def connect(self, slot):
            self._slots.append(slot)

        def emit(self, *args):
            for slot in self._slots:
                slot(*args)

    def __init__(self, session_factory, tarea, *args, **kwargs):
        self._tarea = tarea
        self.resultado = self._Senal()
        self.error = self._Senal()
        self.finished = self._Senal()

    def start(self):
        try:
            valor = self._tarea(MagicMock())
        except Exception as exc:
            self.error.emit(str(exc))
        else:
            self.resultado.emit(valor)
        self.finished.emit()

    def isRunning(self):
        return False


def _crear_topbar(qtbot, monkeypatch, entidades=(), modulos_visibles=None, con_sesion=True):
    llamadas = []

    def _buscar(session, id_usuario, texto):
        llamadas.append(texto)
        return list(entidades)

    monkeypatch.setattr(topbar_mod.BusquedaGlobalService, "buscar", staticmethod(_buscar))
    monkeypatch.setattr(topbar_mod, "QueryWorker", _WorkerSincrono)
    barra = TopBar(
        SimpleNamespace(id_usuario=1),
        session_factory=MagicMock() if con_sesion else None,
        modulos_visibles=modulos_visibles,
    )
    qtbot.addWidget(barra)
    barra.llamadas_busqueda = llamadas
    return barra


def _escribir(barra, texto):
    barra.buscar_input.setText(texto)
    barra._timer_busqueda.stop()
    barra._lanzar_busqueda()  # sin esperar el debounce real


def _textos(barra):
    return [barra.lista_resultados.item(i).text() for i in range(barra.lista_resultados.count())]


_CLIENTE = ResultadoBusqueda("Cliente", "Alimentos Andinos", "J-30489713", "clientes", "Alimentos Andinos")


# ── Buscador ────────────────────────────────────────────────────────────────


def test_texto_corto_no_dispara_busqueda_ni_muestra_lista(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch, entidades=[_CLIENTE])

    barra.buscar_input.setText("a")

    assert not barra._timer_busqueda.isActive()
    assert barra.llamadas_busqueda == []
    assert barra.lista_resultados.count() == 0


def test_escribir_arranca_el_debounce_y_no_consulta_de_inmediato(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch, entidades=[_CLIENTE])

    barra.buscar_input.setText("andi")

    assert barra._timer_busqueda.isActive()
    assert barra.llamadas_busqueda == []


def test_resultados_traen_entidades_con_tipo_y_detalle(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch, entidades=[_CLIENTE])

    _escribir(barra, "andinos")

    assert barra.llamadas_busqueda == ["andinos"]
    assert _textos(barra) == ["Alimentos Andinos\nCliente · J-30489713"]


def test_los_modulos_aparecen_primero_y_sin_tildes(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch, entidades=[_CLIENTE])

    _escribir(barra, "facturacion")  # sin tilde, el titulo es "Facturación / Ventas"

    assert _textos(barra)[0].startswith("Facturación / Ventas")


def test_los_modulos_respetan_los_permisos_del_usuario(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch, modulos_visibles={"clientes"})

    _escribir(barra, "factura")

    assert _textos(barra) == ["Sin resultados"]


def test_sin_session_factory_igual_encuentra_modulos(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch, con_sesion=False)

    _escribir(barra, "clientes")

    assert _textos(barra) == ["Clientes\nMódulo · Ir al módulo"]
    assert barra.llamadas_busqueda == []


def test_sin_resultados_muestra_aviso_no_seleccionable(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)

    _escribir(barra, "zzzzzz")

    assert _textos(barra) == ["Sin resultados"]
    item = barra.lista_resultados.item(0)
    assert not item.flags() & Qt.ItemFlag.ItemIsEnabled
    capturado = []
    barra.modulo_solicitado.connect(lambda *args: capturado.append(args))
    barra._elegir_item(item)
    assert capturado == []


def test_resultado_tardio_de_una_busqueda_vieja_se_descarta(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)
    barra.buscar_input.setText("clientes")
    barra._id_busqueda = 5

    barra._mostrar_resultados(4, [], [_CLIENTE])  # llega con el id de una busqueda anterior

    assert barra.lista_resultados.count() == 0


def test_elegir_un_resultado_emite_modulo_y_texto_y_limpia_la_caja(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch, entidades=[_CLIENTE])
    capturado = []
    barra.modulo_solicitado.connect(lambda modulo, texto: capturado.append((modulo, texto)))
    _escribir(barra, "andinos")

    barra._elegir_item(barra.lista_resultados.item(0))

    assert capturado == [("clientes", "Alimentos Andinos")]
    assert barra.buscar_input.text() == ""
    assert barra.lista_resultados.count() == 0


def test_elegir_un_modulo_navega_sin_texto(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)
    capturado = []
    barra.modulo_solicitado.connect(lambda modulo, texto: capturado.append((modulo, texto)))
    _escribir(barra, "proveedores")

    barra._elegir_item(barra.lista_resultados.item(0))

    assert capturado == [("proveedores", "")]


def test_vaciar_la_caja_limpia_la_lista(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch, entidades=[_CLIENTE])
    _escribir(barra, "andinos")

    barra.buscar_input.clear()

    assert barra.lista_resultados.count() == 0
    assert not barra.lista_resultados.isVisible()


def test_error_en_la_consulta_deja_al_menos_los_modulos(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)

    def _revienta(session, id_usuario, texto):
        raise RuntimeError("sin base de datos")

    monkeypatch.setattr(topbar_mod.BusquedaGlobalService, "buscar", staticmethod(_revienta))

    _escribir(barra, "clientes")

    assert _textos(barra) == ["Clientes\nMódulo · Ir al módulo"]


# ── Campana ─────────────────────────────────────────────────────────────────

_ALTA = Notificacion(
    "cxc_vencidas", "Cuentas por cobrar vencidas", "2 facturas vencidas", "cuentas_por_cobrar", SEVERIDAD_ALTA
)
_MEDIA = Notificacion("stock_bajo", "Stock bajo", "1 producto por debajo de su mínimo", "inventario", SEVERIDAD_MEDIA)
_INFO = Notificacion(
    "tasa", "Tasa de cambio", "La tasa de hoy todavía no está registrada", "control_tasas", SEVERIDAD_INFO
)


def test_sin_notificaciones_no_hay_contador(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)

    barra.set_notificaciones([])

    assert not barra.lbl_contador.isVisible()
    assert barra.lbl_contador.isHidden()


def test_contador_muestra_la_cantidad(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)

    barra.set_notificaciones([_ALTA, _MEDIA, _INFO])

    assert not barra.lbl_contador.isHidden()
    assert barra.lbl_contador.text() == "3"


def test_contador_con_muchas_alertas_se_trunca(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)

    barra.set_notificaciones([_MEDIA] * 12)

    assert barra.lbl_contador.text() == "9+"


def test_el_contador_es_rojo_con_alerta_alta_y_naranja_sin_ella(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)

    barra.set_notificaciones([_MEDIA])
    naranja = barra.lbl_contador.styleSheet()
    barra.set_notificaciones([_ALTA])
    rojo = barra.lbl_contador.styleSheet()

    assert naranja != rojo
    assert topbar_mod.COLOR_WARNING in naranja
    assert topbar_mod.COLOR_DANGER in rojo


def test_resolver_alertas_oculta_el_contador(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)
    barra.set_notificaciones([_ALTA])

    barra.set_notificaciones([])

    assert barra.lbl_contador.isHidden()


def test_menu_lista_las_alertas_y_cada_una_navega_a_su_modulo(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)
    barra.set_notificaciones([_ALTA, _MEDIA])
    capturado = []
    barra.modulo_solicitado.connect(lambda modulo, texto: capturado.append((modulo, texto)))

    menu = barra._construir_menu_notificaciones()
    acciones = menu.actions()

    assert [a.text() for a in acciones] == [
        "Cuentas por cobrar vencidas: 2 facturas vencidas",
        "Stock bajo: 1 producto por debajo de su mínimo",
    ]
    acciones[1].trigger()
    acciones[0].trigger()
    assert capturado == [("inventario", ""), ("cuentas_por_cobrar", "")]


def test_menu_sin_alertas_dice_que_no_hay(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)

    acciones = barra._construir_menu_notificaciones().actions()

    assert [a.text() for a in acciones] == ["No hay alertas por ahora"]
    assert not acciones[0].isEnabled()


class _MenuFalso:
    """Reemplaza al QMenu real: exec() abre un bucle de eventos modal (cuelga el test)."""

    def __init__(self):
        self.abierto_en = None
        self.liberado = False

    def sizeHint(self):
        return QSize(200, 50)

    def exec(self, posicion):
        self.abierto_en = posicion

    def deleteLater(self):
        self.liberado = True


def test_el_boton_de_la_campana_abre_el_menu(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)
    menu = _MenuFalso()
    monkeypatch.setattr(barra, "_construir_menu_notificaciones", lambda: menu)

    barra.btn_notif.click()

    assert menu.abierto_en is not None
    assert menu.liberado
