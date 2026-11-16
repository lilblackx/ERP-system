"""Panel de Pedidos (app/ui/pedidos_panel.py): listado, filtros, revision (aprobar / rechazar / anular), detalle y el
paso a factura. Contra SQL Server real (los pedidos y sus estados son lo que se prueba) con los dialogos modales
reemplazados por dobles: ningun test espera a una persona.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

import app.ui.pedidos_panel as pp
from app.db.models import Pedido
from app.services.pedidos import PedidoService
from app.ui.main_window import MODULO_PERMISO, MODULOS_CONFIG
from app.ui.pedido_detalle_dialog import PedidoDetalleDialog
from app.ui.sidebar import SECCIONES
from tests.factories import asignar_permiso, crear_rol, crear_usuario
from tests.services.test_pedidos import (
    _crear,
    _escenario,
    _items,
    _permiso_pedidos,
    _reservado,
)


@pytest.fixture()
def avisos(monkeypatch):
    """Registra los MessageBox del panel en vez de abrirlos: [(tipo, titulo, texto)]."""
    registro = []
    for tipo in ("information", "warning", "critical"):
        monkeypatch.setattr(
            pp.MessageBox,
            tipo,
            staticmethod(lambda parent, titulo, texto, _t=tipo: registro.append((_t, titulo, texto))),
        )
    return registro


def _fabrica(db):
    return sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False)


def _panel(qtbot, db, usuario):
    panel = pp.PedidosPanel(_fabrica(db), usuario)
    qtbot.addWidget(panel)
    panel.cargar_pedidos(sincrono=True)
    return panel


def _elegir(panel, id_pedido: int) -> None:
    for fila in range(panel.tabla.rowCount()):
        if int(panel.tabla.item(fila, 0).text()) == id_pedido:
            panel.tabla.selectRow(fila)
            return
    raise AssertionError(f"el pedido {id_pedido} no esta en la tabla")


def _estado(db, id_pedido: int) -> str:
    db.expire_all()
    return db.get(Pedido, id_pedido).estado


# -- Registro del modulo -----------------------------------------------------------------------------------------


def test_el_modulo_esta_registrado_en_la_ventana_el_menu_y_el_permiso():
    assert MODULOS_CONFIG["pedidos"][1] is pp.PedidosPanel
    assert MODULO_PERMISO["pedidos"] == ("pedidos", "ver")
    assert "pedidos" in {clave for _seccion, items in SECCIONES for clave, _texto in items}


# -- Listado -----------------------------------------------------------------------------------------------------


def test_el_listado_muestra_cada_pedido_con_su_total_y_su_estado(qtbot, db_session):
    esc = _escenario(db_session)
    lineas = _items(esc, cantidad=2, precio="10.00") + _items(esc, cantidad=1, precio="5.00")
    uno = _crear(db_session, esc, items=lineas)

    panel = _panel(qtbot, db_session, esc.admin)

    assert panel.tabla.rowCount() == 1
    assert panel.lbl_total.text() == "1 pedido"
    assert panel.tabla.item(0, 1).text() == uno.numero_pedido
    assert panel.tabla.item(0, 2).text() == esc.cliente.nombre_razon_social
    assert panel.tabla.item(0, 3).text() == esc.vendedor.nombre_vendedor
    assert panel.tabla.item(0, 5).text() == "Contado"
    assert panel.tabla.item(0, 6).text() == "$25.00"
    assert panel.tabla.item(0, 0).data(Qt.ItemDataRole.UserRole) == "ENVIADO"
    assert panel.tabla.item(0, 7).text() != "—"  # un pedido por revisar muestra hasta cuando aparta stock


def test_un_pedido_aprobado_no_muestra_fecha_de_reserva(qtbot, db_session):
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc)
    PedidoService.aprobar_pedido(db_session, pedido.id_pedido, esc.admin.id_usuario)

    panel = _panel(qtbot, db_session, esc.admin)

    assert panel.tabla.item(0, 7).text() == "—"
    assert panel.tabla.item(0, 0).data(Qt.ItemDataRole.UserRole) == "APROBADO"


def test_el_filtro_de_estado_acota_el_listado(qtbot, db_session):
    esc = _escenario(db_session)
    _crear(db_session, esc, cantidad=1)
    aprobado = _crear(db_session, esc, cantidad=1)
    PedidoService.aprobar_pedido(db_session, aprobado.id_pedido, esc.admin.id_usuario)
    panel = _panel(qtbot, db_session, esc.admin)
    assert panel.tabla.rowCount() == 2

    panel.estado_combo.setCurrentIndex(panel.estado_combo.findData("APROBADO"))

    assert panel.tabla.rowCount() == 1
    assert int(panel.tabla.item(0, 0).text()) == aprobado.id_pedido


def test_un_vendedor_solo_ve_sus_pedidos_en_el_panel(qtbot, db_session):
    esc = _escenario(db_session)
    otro = _escenario(db_session)  # otro vendedor, con su cliente y su producto
    _crear(db_session, esc, cantidad=1)
    _crear(db_session, otro, cantidad=1)

    panel = _panel(qtbot, db_session, esc.usuario)

    assert panel.tabla.rowCount() == 1
    assert panel.tabla.item(0, 3).text() == esc.vendedor.nombre_vendedor


# -- Revisar: aprobar, rechazar, anular ---------------------------------------------------------------------------


def test_sin_elegir_un_pedido_las_acciones_avisan_y_no_hacen_nada(qtbot, db_session, avisos):
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc)
    panel = _panel(qtbot, db_session, esc.admin)
    panel.tabla.clearSelection()

    panel.aprobar_pedido_seleccionado()
    panel.facturar_pedido_seleccionado()

    assert [a[1] for a in avisos] == ["Selección requerida", "Selección requerida"]
    assert _estado(db_session, pedido.id_pedido) == "ENVIADO"


def test_aprobar_el_pedido_elegido_lo_deja_aprobado_y_refresca_la_tabla(qtbot, db_session, avisos):
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc)
    panel = _panel(qtbot, db_session, esc.admin)
    _elegir(panel, pedido.id_pedido)

    panel.aprobar_pedido_seleccionado()

    assert _estado(db_session, pedido.id_pedido) == "APROBADO"
    assert panel.tabla.item(0, 0).data(Qt.ItemDataRole.UserRole) == "APROBADO"
    assert avisos[-1][0] == "information" and pedido.numero_pedido in avisos[-1][2]


def test_aprobar_sin_stock_muestra_el_motivo_y_deja_el_pedido_como_estaba(qtbot, db_session, avisos):
    esc = _escenario(db_session, stock=10)
    vencido = _crear(db_session, esc, cantidad=8)
    db_session.execute(text("UPDATE dbo.pedidos SET estado = 'VENCIDO' WHERE id_pedido = :i"), {"i": vencido.id_pedido})
    db_session.commit()
    _crear(db_session, esc, cantidad=6)  # toma el stock que solto el vencido
    panel = _panel(qtbot, db_session, esc.admin)
    _elegir(panel, vencido.id_pedido)

    panel.aprobar_pedido_seleccionado()

    assert avisos[-1][0] == "warning" and "Stock insuficiente" in avisos[-1][2]
    assert _estado(db_session, vencido.id_pedido) == "VENCIDO"


def test_rechazar_guarda_el_motivo_y_libera_el_stock(qtbot, db_session, avisos, monkeypatch):
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc, cantidad=5)
    monkeypatch.setattr(pp.QInputDialog, "getText", staticmethod(lambda *a, **k: ("Cliente con deuda", True)))
    panel = _panel(qtbot, db_session, esc.admin)
    _elegir(panel, pedido.id_pedido)

    panel.rechazar_pedido_seleccionado()

    db_session.expire_all()
    rechazado = db_session.get(Pedido, pedido.id_pedido)
    assert (rechazado.estado, rechazado.motivo) == ("RECHAZADO", "Cliente con deuda")
    assert _reservado(db_session, esc) == Decimal("0")


@pytest.mark.parametrize("respuesta", [("", True), ("   ", True), ("motivo", False)])
def test_rechazar_sin_motivo_o_cancelando_no_cambia_nada(qtbot, db_session, avisos, monkeypatch, respuesta):
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc)
    monkeypatch.setattr(pp.QInputDialog, "getText", staticmethod(lambda *a, **k: respuesta))
    panel = _panel(qtbot, db_session, esc.admin)
    _elegir(panel, pedido.id_pedido)

    panel.rechazar_pedido_seleccionado()

    assert _estado(db_session, pedido.id_pedido) == "ENVIADO"
    assert avisos == []


def test_anular_libera_el_stock_del_pedido(qtbot, db_session, avisos, monkeypatch):
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc, cantidad=5)
    monkeypatch.setattr(pp.QInputDialog, "getText", staticmethod(lambda *a, **k: ("Se canceló", True)))
    panel = _panel(qtbot, db_session, esc.admin)
    _elegir(panel, pedido.id_pedido)

    panel.anular_pedido_seleccionado()

    assert _estado(db_session, pedido.id_pedido) == "ANULADO"
    assert _reservado(db_session, esc) == Decimal("0")


def test_el_vendedor_anula_su_pedido_desde_el_panel_pero_no_puede_aprobar(qtbot, db_session, avisos, monkeypatch):
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc)
    monkeypatch.setattr(pp.QInputDialog, "getText", staticmethod(lambda *a, **k: ("Me equivoqué", True)))
    panel = _panel(qtbot, db_session, esc.usuario)
    _elegir(panel, pedido.id_pedido)

    panel.aprobar_pedido_seleccionado()  # sin 'pedidos:editar': avisa y no toca nada
    assert avisos[-1][:2] == ("warning", "Sin permiso")
    assert _estado(db_session, pedido.id_pedido) == "ENVIADO"

    panel.anular_pedido_seleccionado()
    assert _estado(db_session, pedido.id_pedido) == "ANULADO"


def test_los_botones_dependen_de_los_permisos_del_usuario(qtbot, db_session):
    esc = _escenario(db_session)  # esc.usuario: vendedor con pedidos ver + crear
    rol_revisor = crear_rol(db_session)
    for accion in ("ver", "editar"):
        asignar_permiso(db_session, rol_revisor, _permiso_pedidos(db_session, accion))
    revisor = crear_usuario(db_session, id_rol=rol_revisor.id_rol)

    vendedor = _panel(qtbot, db_session, esc.usuario)
    caja = _panel(qtbot, db_session, revisor)
    admin = _panel(qtbot, db_session, esc.admin)

    def visibles(panel):
        return {
            nombre
            for nombre in ("btn_detalle", "btn_aprobar", "btn_rechazar", "btn_anular", "btn_facturar")
            if getattr(panel, nombre).parent() is not None
        }

    assert visibles(vendedor) == {"btn_detalle", "btn_anular"}
    assert visibles(caja) == {"btn_detalle", "btn_aprobar", "btn_rechazar", "btn_anular", "btn_facturar"}
    assert visibles(admin) == visibles(caja)


# -- Detalle -----------------------------------------------------------------------------------------------------


def test_ver_detalle_abre_el_dialogo_con_los_datos_del_pedido(qtbot, db_session, monkeypatch):
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc, observaciones="Entregar en la tarde")
    abiertos = []

    class DialogoFalso:
        def __init__(self, datos, parent=None):
            abiertos.append(datos)

        def exec(self):
            return 0

    monkeypatch.setattr(pp, "PedidoDetalleDialog", DialogoFalso)
    panel = _panel(qtbot, db_session, esc.admin)
    _elegir(panel, pedido.id_pedido)

    panel.ver_detalle_pedido()

    assert len(abiertos) == 1
    assert abiertos[0]["numero_pedido"] == pedido.numero_pedido
    assert abiertos[0]["observaciones"] == "Entregar en la tarde"
    assert panel._abriendo_dialogo is False  # no queda trabado para el siguiente


def test_el_dialogo_de_detalle_muestra_las_lineas_el_total_y_el_estado(qtbot, db_session):
    esc = _escenario(db_session, stock=100, cantidad_caja=Decimal("12"))
    pedido = _crear(db_session, esc, items=_items(esc, cantidad=2, tipo_venta="bulto") + _items(esc, cantidad=3))
    datos = PedidoService.detalle_pedido(db_session, pedido.id_pedido, esc.admin.id_usuario)

    dialogo = PedidoDetalleDialog(datos)
    qtbot.addWidget(dialogo)

    assert pedido.numero_pedido in dialogo.windowTitle()
    assert dialogo.tabla.rowCount() == 2
    assert "caja" in dialogo.tabla.item(0, 1).text() and "und" in dialogo.tabla.item(1, 1).text()
    assert dialogo.lbl_total.text() == "Total: $100.00"  # 2 cajas x $20 + 3 und x $20


# -- Facturar ----------------------------------------------------------------------------------------------------


class FormularioFalso:
    """Reemplaza a FacturaFormDialog: guarda con que se lo construyo y no abre nada."""

    creados: list = []

    def __init__(self, session, id_usuario, parent=None, session_factory=None, pedido=None):
        self.pedido = pedido
        self.factura_emitida = None
        self.numero_factura_emitida = None
        FormularioFalso.creados.append(self)

    def exec(self):
        return 0


@pytest.fixture()
def formulario_falso(monkeypatch):
    FormularioFalso.creados = []
    monkeypatch.setattr(pp, "FacturaFormDialog", FormularioFalso)
    return FormularioFalso


def _con_caja_abierta(monkeypatch, abierta: bool):
    caja = SimpleNamespace(fecha_apertura=1, fecha_cierre=None)
    monkeypatch.setattr(pp.CajaService, "listar_cajas", staticmethod(lambda *a, **k: [caja] if abierta else []))
    monkeypatch.setattr(pp, "cajas_de_esta_estacion", lambda cajas: cajas)

    class AperturaFalsa:
        caja_abierta = None

        def __init__(self, *a, **k):
            pass

        def exec(self):
            return 0  # el usuario cierra el dialogo sin abrir turno

    monkeypatch.setattr(pp, "CajaAperturaDialog", AperturaFalsa)


def test_facturar_un_pedido_sin_aprobar_avisa_y_no_abre_el_formulario(qtbot, db_session, avisos, formulario_falso):
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc)
    panel = _panel(qtbot, db_session, esc.admin)
    _elegir(panel, pedido.id_pedido)

    panel.facturar_pedido_seleccionado()

    assert avisos[-1][1] == "Pedido no aprobado"
    assert formulario_falso.creados == []


def test_facturar_abre_el_formulario_con_los_datos_del_pedido(qtbot, db_session, avisos, formulario_falso, monkeypatch):
    _con_caja_abierta(monkeypatch, True)
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc, cantidad=5)
    PedidoService.aprobar_pedido(db_session, pedido.id_pedido, esc.admin.id_usuario)
    panel = _panel(qtbot, db_session, esc.admin)
    _elegir(panel, pedido.id_pedido)

    panel.facturar_pedido_seleccionado()

    assert len(formulario_falso.creados) == 1
    datos = formulario_falso.creados[0].pedido
    assert datos["id_pedido"] == pedido.id_pedido
    assert datos["id_cliente"] == esc.cliente.id_cliente
    assert datos["id_vendedor"] == esc.vendedor.id_vendedor
    assert len(datos["lineas"]) == 1
    assert avisos == []  # el usuario cerro el formulario: nada que contar


def test_un_pedido_de_contado_sin_caja_abierta_no_abre_el_formulario(
    qtbot, db_session, avisos, formulario_falso, monkeypatch
):
    _con_caja_abierta(monkeypatch, False)
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc)
    PedidoService.aprobar_pedido(db_session, pedido.id_pedido, esc.admin.id_usuario)
    panel = _panel(qtbot, db_session, esc.admin)
    _elegir(panel, pedido.id_pedido)

    panel.facturar_pedido_seleccionado()

    assert avisos[-1][1] == "Caja requerida"
    assert formulario_falso.creados == []


def test_un_pedido_a_credito_no_necesita_caja_abierta(qtbot, db_session, avisos, formulario_falso, monkeypatch):
    _con_caja_abierta(monkeypatch, False)
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc, condicion_pago="credito")
    PedidoService.aprobar_pedido(db_session, pedido.id_pedido, esc.admin.id_usuario)
    panel = _panel(qtbot, db_session, esc.admin)
    _elegir(panel, pedido.id_pedido)

    panel.facturar_pedido_seleccionado()

    assert len(formulario_falso.creados) == 1
    assert formulario_falso.creados[0].pedido["condicion_pago"] == "credito"


def test_sin_permiso_de_emitir_facturas_no_se_abre_el_formulario(qtbot, db_session, avisos, formulario_falso):
    """Revisar pedidos (`pedidos:editar`) no alcanza para facturar: tambien hace falta `ventas:crear`."""
    esc = _escenario(db_session)
    rol = crear_rol(db_session)
    asignar_permiso(db_session, rol, _permiso_pedidos(db_session, "ver"))
    asignar_permiso(db_session, rol, _permiso_pedidos(db_session, "editar"))
    revisor = crear_usuario(db_session, id_rol=rol.id_rol)
    pedido = _crear(db_session, esc)
    PedidoService.aprobar_pedido(db_session, pedido.id_pedido, esc.admin.id_usuario)
    panel = _panel(qtbot, db_session, revisor)
    _elegir(panel, pedido.id_pedido)

    panel.facturar_pedido_seleccionado()

    assert avisos[-1][:2] == ("warning", "Sin permiso")
    assert formulario_falso.creados == []
