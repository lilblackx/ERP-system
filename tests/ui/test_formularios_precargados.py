"""Formularios de producto, usuario y cuenta bancaria, y detalle de pagos de Cuentas por pagar: los catalogos de los
combos (categorias, roles, vendedores, bancos) y los datos del registro a editar se piden en un hilo aparte
(carga_asincrona.py) y el formulario se abre al llegar, ya con todo cargado. Sin esos datos el formulario sigue
consultandolos el mismo (otros usos, tests)."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.ui.carga_asincrona as ca
import app.ui.cuenta_bancaria_form_dialog as cbf
import app.ui.cuentas_bancarias_panel as cb
import app.ui.cuentas_por_pagar_panel as cxp
import app.ui.inventario_panel as inv
import app.ui.producto_form_dialog as pf
import app.ui.usuario_form_dialog as uf
import app.ui.usuarios_panel as up


class _WorkerFalso:
    creados: list = []

    def __init__(self, session_factory, tarea, *args, **kwargs):
        self.tarea, self.args = tarea, args
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


def _sesion_que_prohibe_consultas():
    """Sesion que hace fallar cualquier consulta: prueba que el formulario no consulta lo que ya recibio."""
    sesion = MagicMock()
    sesion.query.side_effect = AssertionError("el formulario no debe consultar lo precargado")
    sesion.get.side_effect = AssertionError("el formulario no debe consultar lo precargado")
    return sesion


# -- ProductoFormDialog -----------------------------------------------------------------------------------------


def _categoria(i, nombre):
    return SimpleNamespace(id_categoria=i, nombre=nombre)


def test_el_formulario_de_producto_usa_las_categorias_precargadas(qtbot, monkeypatch):
    monkeypatch.setattr(pf.CategoriaService, "listar", staticmethod(lambda *a, **k: pytest.fail("no debe consultar")))
    dialogo = pf.ProductoFormDialog(
        _sesion_que_prohibe_consultas(),
        1,
        precargado={"categorias": [_categoria(1, "Bebidas"), _categoria(2, "Lacteos")]},
    )
    qtbot.addWidget(dialogo)

    assert [dialogo.categoria_combo.itemText(i) for i in range(dialogo.categoria_combo.count())] == [
        "Bebidas",
        "Lacteos",
    ]


def test_categorias_precargadas_en_none_avisa_que_falta_el_permiso(qtbot, monkeypatch):
    avisos = []
    monkeypatch.setattr(pf.MessageBox, "warning", staticmethod(lambda *a, **k: avisos.append(a[1])))
    dialogo = pf.ProductoFormDialog(MagicMock(), 1, precargado={"categorias": None})
    qtbot.addWidget(dialogo)

    assert avisos == ["Sin permiso"] and not dialogo.categoria_combo.isEnabled()


def test_despues_de_la_primera_carga_las_categorias_se_vuelven_a_consultar(qtbot, monkeypatch):
    consultas = []
    monkeypatch.setattr(
        pf.CategoriaService,
        "listar",
        staticmethod(lambda *a, **k: consultas.append(1) or [_categoria(1, "Bebidas"), _categoria(9, "Nueva")]),
    )
    dialogo = pf.ProductoFormDialog(MagicMock(), 1, precargado={"categorias": [_categoria(1, "Bebidas")]})
    qtbot.addWidget(dialogo)
    assert consultas == []

    dialogo._cargar_categorias(seleccionar_id=9)  # tras crear una categoria nueva

    assert consultas == [1] and dialogo.categoria_combo.currentData() == 9


def test_el_formulario_de_producto_usa_el_precio_precargado_al_editar(qtbot, monkeypatch):
    monkeypatch.setattr(pf.PrecioService, "obtener_precio", staticmethod(lambda *a, **k: pytest.fail("no consultar")))
    producto = SimpleNamespace(
        id_producto=5,
        id_categoria=1,
        cod_producto="P-1",
        nombre_producto="Aceite",
        descripcion_producto=None,
        costo_producto=Decimal("2.00"),
        cantidad_unidad=10,
        cantidad_minima=1,
        cantidad_caja=0,
        cantidad_caja_total=0,
        cantidad_caja_unidad=0,
        articulo_bcv=False,
        fecha_vencimiento=None,
        estado_producto="ACTIVO",
    )
    precio = SimpleNamespace(precio_1=Decimal("19.99"), precio_2=None, precio_3=None)

    dialogo = pf.ProductoFormDialog(
        MagicMock(), 1, producto, precargado={"categorias": [_categoria(1, "Bebidas")], "precio": precio}
    )
    qtbot.addWidget(dialogo)

    assert dialogo.precio_1_input.get_value() == Decimal("19.99")


# -- UsuarioFormDialog ------------------------------------------------------------------------------------------


def test_el_formulario_de_usuario_usa_los_roles_y_vendedores_precargados(qtbot, monkeypatch):
    monkeypatch.setattr(uf.RolService, "listar_roles", staticmethod(lambda *a, **k: pytest.fail("no consultar")))
    monkeypatch.setattr(uf.VendedorService, "listar", staticmethod(lambda *a, **k: pytest.fail("no consultar")))
    precargado = {
        "roles": [SimpleNamespace(id_rol=1, nombre="ADMIN"), SimpleNamespace(id_rol=2, nombre="CAJERO")],
        "vendedores": [SimpleNamespace(id_vendedor=7, nombre_vendedor="Ana")],
    }

    dialogo = uf.UsuarioFormDialog(MagicMock(), 1, precargado=precargado)
    qtbot.addWidget(dialogo)

    assert [dialogo.rol_combo.itemText(i) for i in range(dialogo.rol_combo.count())] == ["ADMIN", "CAJERO"]
    assert [dialogo.vendedor_combo.itemText(i) for i in range(dialogo.vendedor_combo.count())] == [
        "Sin vincular",
        "Ana",
    ]


# -- CuentaBancariaFormDialog -----------------------------------------------------------------------------------


def test_el_formulario_de_cuenta_usa_los_bancos_precargados_sin_consultar(qtbot):
    bancos = [SimpleNamespace(id_banco=1, nombre_banco="Bancamiga", codigo_banco="0172")]

    dialogo = cbf.CuentaBancariaFormDialog(_sesion_que_prohibe_consultas(), precargado={"bancos": bancos})
    qtbot.addWidget(dialogo)

    assert dialogo.banco_combo.itemText(0) == "Bancamiga (0172)"


def test_el_formulario_de_cuenta_usa_si_tiene_movimientos_precargado(qtbot):
    cuenta = SimpleNamespace(
        id_cuenta=7,
        id_banco=1,
        numero_cuenta="0134000000000007",
        tipo_cuenta_banco="CORRIENTE",
        nombre_titular="DJ",
        identificacion_titular="J-1",
        saldo_total_banco=Decimal("10.00"),
        saldo_total_banco_bs=Decimal("0.00"),
        saldo_total_banco_cop=Decimal("0.00"),
        estado_cuenta="ACTIVO",
        moneda="USD",
        fecha_creacion=None,
        creador=None,
    )
    precargado = {"bancos": [], "tiene_movimientos": True}

    dialogo = cbf.CuentaBancariaFormDialog(_sesion_que_prohibe_consultas(), cuenta, precargado=precargado)
    qtbot.addWidget(dialogo)

    assert not dialogo.lbl_aviso_moneda.isHidden()


# -- Paneles: piden en un hilo y abren el formulario al llegar ------------------------------------------------------


class _FormularioFalso:
    """Reemplaza al formulario real: registra con que se lo abrio y no ejecuta nada."""

    abiertos: list = []

    def __init__(self, *args, **kwargs):
        _FormularioFalso.abiertos.append((args, kwargs))

    def exec(self):
        return 0


def test_nuevo_producto_pide_las_categorias_en_un_hilo_y_abre_el_formulario_al_llegar(qtbot, monkeypatch, worker_falso):
    _FormularioFalso.abiertos = []
    monkeypatch.setattr(inv, "ProductoFormDialog", _FormularioFalso)
    monkeypatch.setattr(inv.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    panel = inv.InventarioPanel(MagicMock(), SimpleNamespace(id_usuario=1, id_vendedor_usuario=None))
    qtbot.addWidget(panel)
    panel._exigir_permiso = lambda *a, **k: True

    panel.nuevo_producto()

    assert worker_falso.creados[-1].iniciado and _FormularioFalso.abiertos == []  # todavia no llego
    sesion = MagicMock()
    panel._recibir_carga(
        {
            "id_carga": 1,
            "clave": "form_producto",
            "resultado": {"session": sesion, "producto": None, "precargado": {"categorias": []}},
        }
    )

    ((args, kwargs),) = _FormularioFalso.abiertos
    assert args[0] is sesion and kwargs["precargado"] == {"categorias": []}
    sesion.close.assert_called_once()  # el panel cierra la sesion al terminar


def test_editar_producto_que_ya_no_existe_avisa_y_cierra_la_sesion(qtbot, monkeypatch, worker_falso):
    avisos = []
    monkeypatch.setattr(inv.MessageBox, "warning", staticmethod(lambda *a, **k: avisos.append(a[1])))
    monkeypatch.setattr(inv, "ProductoFormDialog", _FormularioFalso)
    monkeypatch.setattr(inv.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    panel = inv.InventarioPanel(MagicMock(), SimpleNamespace(id_usuario=1, id_vendedor_usuario=None))
    qtbot.addWidget(panel)
    panel._exigir_permiso = lambda *a, **k: True
    panel._fila_seleccionada_id = lambda: 5
    _FormularioFalso.abiertos = []

    panel.editar_producto()
    sesion = MagicMock()
    panel._recibir_carga(
        {"id_carga": 1, "clave": "form_producto", "resultado": {"session": sesion, "producto": None, "precargado": {}}}
    )

    assert avisos == ["No encontrado"] and _FormularioFalso.abiertos == []
    sesion.close.assert_called_once()


def test_una_respuesta_vieja_de_un_formulario_cierra_su_sesion_sin_abrirlo(qtbot, monkeypatch, worker_falso):
    _FormularioFalso.abiertos = []
    monkeypatch.setattr(inv, "ProductoFormDialog", _FormularioFalso)
    monkeypatch.setattr(inv.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    panel = inv.InventarioPanel(MagicMock(), SimpleNamespace(id_usuario=1, id_vendedor_usuario=None))
    qtbot.addWidget(panel)
    panel._exigir_permiso = lambda *a, **k: True
    panel.nuevo_producto()  # id 1
    panel.nuevo_producto()  # id 2: el primer clic queda obsoleto
    sesion_vieja = MagicMock()

    panel._recibir_carga(
        {
            "id_carga": 1,
            "clave": "form_producto",
            "resultado": {"session": sesion_vieja, "producto": None, "precargado": {}},
        }
    )

    assert _FormularioFalso.abiertos == []
    sesion_vieja.close.assert_called_once()


def test_la_tarea_del_formulario_de_producto_trae_categorias_y_marca_la_falta_de_permiso(monkeypatch):
    sesiones = []

    def fabrica():
        sesion = MagicMock()
        sesiones.append(sesion)
        return sesion

    def sin_permiso(*a, **k):
        raise inv.PermisoDenegadoError("categorias", "ver")

    monkeypatch.setattr(inv.CategoriaService, "listar", staticmethod(sin_permiso))

    datos = inv._tarea_form_producto(MagicMock(), fabrica, 1)

    assert datos["precargado"] == {"categorias": None} and datos["producto"] is None
    assert datos["session"] is sesiones[0]
    sesiones[0].close.assert_not_called()  # la cierra quien abre el formulario


def test_si_la_tarea_del_formulario_falla_cierra_la_sesion_que_creo(monkeypatch):
    sesiones = []

    def fabrica():
        sesion = MagicMock()
        sesiones.append(sesion)
        return sesion

    monkeypatch.setattr(inv.CategoriaService, "listar", staticmethod(lambda *a, **k: [1]))
    monkeypatch.setattr(
        inv.PrecioService, "obtener_precio", staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    )

    with pytest.raises(RuntimeError):
        inv._tarea_form_producto(MagicMock(), fabrica, 1, id_producto=5)

    assert sesiones[0].close.called


def test_nuevo_usuario_abre_el_formulario_con_los_catalogos_precargados(qtbot, monkeypatch, worker_falso):
    _FormularioFalso.abiertos = []
    monkeypatch.setattr(up, "UsuarioFormDialog", _FormularioFalso)
    monkeypatch.setattr(up.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    panel = up.UsuariosPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    panel._exigir_permiso = lambda *a, **k: True

    panel.nuevo_usuario()
    sesion = MagicMock()
    panel._recibir_carga(
        {
            "id_carga": 1,
            "clave": "form_usuario",
            "resultado": {"session": sesion, "usuario": None, "precargado": {"roles": [], "vendedores": []}},
        }
    )

    ((args, kwargs),) = _FormularioFalso.abiertos
    assert kwargs["precargado"] == {"roles": [], "vendedores": []}
    sesion.close.assert_called_once()


def test_editar_usuario_que_ya_no_existe_avisa(qtbot, monkeypatch, worker_falso):
    avisos = []
    monkeypatch.setattr(up.MessageBox, "warning", staticmethod(lambda *a, **k: avisos.append(a[1])))
    monkeypatch.setattr(up.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    panel = up.UsuariosPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    panel._exigir_permiso = lambda *a, **k: True
    panel._fila_seleccionada_id = lambda: 9

    panel.editar_usuario()
    sesion = MagicMock()
    panel._recibir_carga(
        {"id_carga": 1, "clave": "form_usuario", "resultado": {"session": sesion, "usuario": None, "precargado": {}}}
    )

    assert avisos == ["No encontrado"]
    sesion.close.assert_called_once()


def test_la_tarea_del_formulario_de_cuenta_trae_bancos_cuenta_y_movimientos():
    banco = SimpleNamespace(id_banco=1)
    cuenta = SimpleNamespace(id_cuenta=7)
    sesion = MagicMock()
    sesion.query.side_effect = lambda modelo: {
        "Banco": MagicMock(**{"filter.return_value.order_by.return_value.all.return_value": [banco]}),
        "CuentaBancaria": MagicMock(**{"filter.return_value.first.return_value": cuenta}),
        "id_movimiento": MagicMock(**{"filter.return_value.first.return_value": (1,)}),
    }[getattr(modelo, "__name__", getattr(modelo, "key", "id_movimiento"))]

    datos = cb._tarea_form_cuenta(MagicMock(), lambda: sesion, id_cuenta=7)

    assert datos["session"] is sesion and datos["cuenta"] is cuenta
    assert datos["precargado"] == {"bancos": [banco], "tiene_movimientos": True}


# -- Detalle de pagos de Cuentas por pagar ----------------------------------------------------------------------------


def _pago(i):
    return SimpleNamespace(
        id_pago_proveedor=i,
        fecha_pago=None,
        monto=Decimal("10.00"),
        monto_bolivares=None,
        tasa_cambio=None,
        metodo_pago="transferencia",
        caja=None,
        cuenta_bancaria=None,
        referencia="REF",
    )


def test_el_dialogo_de_detalle_de_pagos_pinta_los_pagos_precargados_sin_consultar(qtbot, monkeypatch):
    monkeypatch.setattr(
        cxp.PagoService, "listar_pagos_proveedor", staticmethod(lambda *a, **k: pytest.fail("no consultar"))
    )
    cuenta = SimpleNamespace(
        id_cuenta=1,
        saldo_pendiente=Decimal("5.00"),
        fecha_vencimiento=None,
        compra=SimpleNamespace(numero_compra="C-1", proveedor=SimpleNamespace(nombre_razon_social="Prov")),
    )

    dialogo = cxp.DetalleCuentaPorPagarDialog(MagicMock(), cuenta, 1, pagos=[_pago(1), _pago(2)])
    qtbot.addWidget(dialogo)

    assert dialogo.tabla_pagos.rowCount() == 2


def test_el_dialogo_de_detalle_sin_pagos_precargados_los_consulta_como_siempre(qtbot, monkeypatch):
    consultas = []
    monkeypatch.setattr(
        cxp.PagoService, "listar_pagos_proveedor", staticmethod(lambda *a, **k: consultas.append(1) or [_pago(1)])
    )
    cuenta = SimpleNamespace(id_cuenta=1, saldo_pendiente=Decimal("5.00"), fecha_vencimiento=None, compra=None)

    dialogo = cxp.DetalleCuentaPorPagarDialog(MagicMock(), cuenta, 1)
    qtbot.addWidget(dialogo)

    assert consultas == [1] and dialogo.tabla_pagos.rowCount() == 1


def test_ver_detalle_de_pagos_pide_en_un_hilo_y_abre_el_dialogo_al_llegar(qtbot, monkeypatch, worker_falso):
    monkeypatch.setattr(cxp.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    panel = cxp.CuentasPorPagarPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    abiertos = []

    class _Dialogo:
        def __init__(self, session, cuenta, id_usuario, parent=None, pagos=None):
            abiertos.append((cuenta, pagos))

        def exec(self):
            return 0

    monkeypatch.setattr(cxp, "DetalleCuentaPorPagarDialog", _Dialogo)

    panel._ver_detalle_pagos(1)
    assert abiertos == []
    sesion = MagicMock()
    panel._recibir_carga(
        {"id_carga": 1, "clave": "detalle_pagos", "resultado": {"session": sesion, "cuenta": "c", "pagos": ["p"]}}
    )

    assert abiertos == [("c", ["p"])]
    sesion.close.assert_called_once()


def test_ver_detalle_de_una_cuenta_que_ya_no_existe_avisa_y_cierra_la_sesion(qtbot, monkeypatch, worker_falso):
    avisos = []
    monkeypatch.setattr(cxp.MessageBox, "warning", staticmethod(lambda *a, **k: avisos.append(a[1])))
    monkeypatch.setattr(cxp.QTimer, "singleShot", staticmethod(lambda *a, **k: None))
    panel = cxp.CuentasPorPagarPanel(MagicMock(), SimpleNamespace(id_usuario=1))
    qtbot.addWidget(panel)
    panel._ver_detalle_pagos(1)
    sesion = MagicMock()

    panel._recibir_carga(
        {"id_carga": 1, "clave": "detalle_pagos", "resultado": {"session": sesion, "cuenta": None, "pagos": []}}
    )

    assert avisos == ["Cuenta no encontrada"]
    sesion.close.assert_called_once()
