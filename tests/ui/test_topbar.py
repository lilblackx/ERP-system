"""Tests de la TopBar: buscador global y campana de notificaciones.

El servicio de búsqueda se monkeypatchea (misma razón que test_config_empresa_panel.py): acá
se prueba el cableado UI -- debounce, módulos, lista de resultados, navegación -- no las
consultas, que ya cubre tests/services/test_busqueda_global.py. El QueryWorker real se
reemplaza por uno síncrono para no depender de hilos en el test."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from PySide6.QtCore import Qt

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


def _panel(barra):
    panel = barra._construir_panel_notificaciones()
    return panel


def test_panel_lista_las_alertas_y_cada_una_navega_a_su_modulo(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)
    barra.set_notificaciones([_ALTA, _MEDIA])
    capturado = []
    barra.modulo_solicitado.connect(lambda modulo, texto: capturado.append((modulo, texto)))

    panel = _panel(barra)

    assert [f.notificacion for f in panel.filas] == [_ALTA, _MEDIA]
    panel.filas[1].clicked.emit()
    panel.filas[0].clicked.emit()
    assert capturado == [("inventario", ""), ("cuentas_por_cobrar", "")]


def test_abrir_una_alerta_la_marca_leida_y_baja_el_contador(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)
    barra.set_notificaciones([_ALTA, _MEDIA, _INFO])
    assert barra.lbl_contador.text() == "3"

    _panel(barra).filas[1].clicked.emit()

    assert barra.lbl_contador.text() == "2"
    assert [leida for _, leida in barra._filas_panel()] == [False, True, False]


def test_marcar_todas_como_leidas_oculta_el_contador_pero_conserva_las_alertas(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)
    barra.set_notificaciones([_ALTA, _MEDIA])
    panel = _panel(barra)

    panel.btn_marcar_todas.click()

    assert barra.lbl_contador.isHidden()
    assert all(leida for _, leida in barra._filas_panel())
    assert len(panel.filas) == 2  # siguen listadas, ahora como leidas
    assert not panel.btn_marcar_todas.isEnabled()


def test_el_contador_solo_cuenta_las_no_leidas_y_su_color_sale_de_ellas(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)
    barra.set_notificaciones([_ALTA, _MEDIA])
    assert topbar_mod.COLOR_DANGER in barra.lbl_contador.styleSheet()

    _panel(barra).filas[0].clicked.emit()  # se lee la alta

    assert barra.lbl_contador.text() == "1"
    assert topbar_mod.COLOR_WARNING in barra.lbl_contador.styleSheet()


def test_lo_leido_se_conserva_al_reabrir_la_app(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)
    barra.set_notificaciones([_ALTA, _MEDIA])
    _panel(barra).filas[0].clicked.emit()

    otra_sesion = _crear_topbar(qtbot, monkeypatch)
    otra_sesion.set_notificaciones([_ALTA, _MEDIA])

    assert otra_sesion.lbl_contador.text() == "1"


def test_si_cambia_el_detalle_de_una_alerta_vuelve_a_ser_no_leida(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)
    barra.set_notificaciones([_ALTA])
    _panel(barra).filas[0].clicked.emit()
    assert barra.lbl_contador.isHidden()

    mas_vencidas = Notificacion(
        "cxc_vencidas", "Cuentas por cobrar vencidas", "5 facturas vencidas", "cuentas_por_cobrar", SEVERIDAD_ALTA
    )
    barra.set_notificaciones([mas_vencidas])

    assert barra.lbl_contador.text() == "1"


def test_alerta_resuelta_deja_de_estar_leida_si_vuelve_a_aparecer(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)
    barra.set_notificaciones([_ALTA])
    _panel(barra).filas[0].clicked.emit()

    barra.set_notificaciones([])
    barra.set_notificaciones([_ALTA])

    assert barra.lbl_contador.text() == "1"


def test_panel_sin_alertas_dice_que_no_hay(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)

    panel = _panel(barra)

    assert panel.filas == []
    assert not panel.btn_marcar_todas.isVisibleTo(panel)


def test_el_boton_de_la_campana_abre_el_panel(qtbot, monkeypatch):
    barra = _crear_topbar(qtbot, monkeypatch)
    barra.set_notificaciones([_ALTA])
    barra.show()

    barra.btn_notif.click()

    assert barra._panel_notificaciones is not None
    assert barra._panel_notificaciones.isVisible()
    barra._panel_notificaciones.close()


def test_elegir_una_accion_emite_accion_solicitada_y_no_navega(qtbot, monkeypatch):
    accion = ResultadoBusqueda("Acción", "Nueva factura", "Emitir una factura", "facturacion", "", "nueva_factura")
    barra = _crear_topbar(qtbot, monkeypatch, entidades=[accion])
    acciones, modulos = [], []
    barra.accion_solicitada.connect(acciones.append)
    barra.modulo_solicitado.connect(lambda m, t: modulos.append((m, t)))
    _escribir(barra, "nueva fact")

    barra._elegir_item(barra.lista_resultados.item(0))

    assert acciones == ["nueva_factura"]
    assert modulos == []
    assert barra.buscar_input.text() == ""


def test_los_tipos_nuevos_tienen_icono_propio():
    from app.services import busqueda_global as bg

    tipos = [
        bg.TIPO_VENDEDOR, bg.TIPO_COMPRA, bg.TIPO_CXC, bg.TIPO_CXP, bg.TIPO_BANCO,
        bg.TIPO_CUENTA_BANCARIA, bg.TIPO_CAJA, bg.TIPO_USUARIO, bg.TIPO_ACCION,
    ]  # fmt: skip
    assert all(t in topbar_mod._ICONO_TIPO for t in tipos)


# ── Latido del contador: solo cuando llega una alerta nueva ─────────────────


def test_el_contador_late_una_vez_solo_cuando_sube(qtbot, monkeypatch):
    latidos = []
    monkeypatch.setattr(topbar_mod, "rebote", lambda widget: latidos.append(widget))
    barra = _crear_topbar(qtbot, monkeypatch)

    barra.set_notificaciones([_ALTA])  # 0 -> 1: llego una alerta nueva
    assert latidos == [barra.lbl_contador]
    barra.set_notificaciones([_ALTA])  # el refresco automatico trae lo mismo: sin latido
    assert len(latidos) == 1
    barra.set_notificaciones([_ALTA, _MEDIA])  # 1 -> 2
    assert len(latidos) == 2
    barra.set_notificaciones([_MEDIA])  # baja: sin latido
    assert len(latidos) == 2
