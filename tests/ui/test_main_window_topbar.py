"""Cableado MainWindow <-> TopBar: lo que hace MainWindow cuando la barra superior pide
abrir un destino (resultado de la búsqueda global o alerta de la campana).

MainWindow real necesita base de datos y arma todos los paneles, así que acá se llama el
método sin instanciar la ventana, con un `self` mínimo -- lo que se prueba es su lógica de
navegación, no el armado de la UI."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from PySide6.QtWidgets import QLineEdit

from app.ui.main_window import MODULOS_CONFIG, MainWindow


def _ventana_falsa(paneles=None):
    return SimpleNamespace(navegar_a=MagicMock(), _paneles=paneles or {})


def test_abrir_un_modulo_navega_sin_tocar_la_busqueda(qtbot):
    campo = QLineEdit()
    qtbot.addWidget(campo)
    ventana = _ventana_falsa({"clientes": SimpleNamespace(buscar_input=campo)})

    MainWindow._abrir_desde_topbar(ventana, "clientes", "")

    ventana.navegar_a.assert_called_once_with("clientes")
    assert campo.text() == ""


def test_abrir_un_resultado_deja_su_texto_en_la_busqueda_del_modulo(qtbot):
    campo = QLineEdit()
    qtbot.addWidget(campo)
    ventana = _ventana_falsa({"clientes": SimpleNamespace(buscar_input=campo)})

    MainWindow._abrir_desde_topbar(ventana, "clientes", "Alimentos Andinos")

    ventana.navegar_a.assert_called_once_with("clientes")
    assert campo.text() == "Alimentos Andinos"


def test_modulo_sin_caja_de_busqueda_no_falla():
    ventana = _ventana_falsa({"bancos": SimpleNamespace()})

    MainWindow._abrir_desde_topbar(ventana, "bancos", "algo")

    ventana.navegar_a.assert_called_once_with("bancos")


def test_modulo_desconocido_se_ignora():
    ventana = _ventana_falsa()

    MainWindow._abrir_desde_topbar(ventana, "no_existe", "x")

    ventana.navegar_a.assert_not_called()


def test_todos_los_destinos_de_busqueda_y_alertas_son_modulos_reales():
    """Los modulos a los que lleva la busqueda global y la campana tienen que existir en
    MODULOS_CONFIG, o el click no haria nada (_abrir_desde_topbar los ignora)."""
    destinos = {
        "clientes", "inventario", "proveedores", "facturacion",  # busqueda_global.py
        "cuentas_por_cobrar", "cuentas_por_pagar", "control_tasas", "config_empresa",  # notificaciones.py
    }  # fmt: skip
    assert destinos <= set(MODULOS_CONFIG)


def test_la_caja_de_busqueda_de_cuentas_bancarias_tambien_se_filtra(qtbot):
    """CuentasBancariasPanel llama a su caja `search_input`, no `buscar_input`."""
    campo = QLineEdit()
    qtbot.addWidget(campo)
    ventana = _ventana_falsa({"cuentas_bancarias": SimpleNamespace(search_input=campo)})

    MainWindow._abrir_desde_topbar(ventana, "cuentas_bancarias", "Inversiones Quiroz")

    assert campo.text() == "Inversiones Quiroz"


def test_todos_los_destinos_de_la_busqueda_ampliada_son_modulos_reales():
    destinos = {
        "vendedores", "compras", "cuentas_por_cobrar", "cuentas_por_pagar",  # busqueda_global.py
        "bancos", "cuentas_bancarias", "cajas", "usuarios",
    }  # fmt: skip
    assert destinos <= set(MODULOS_CONFIG)


def test_ejecutar_una_accion_lleva_al_modulo_y_abre_su_formulario(qtbot):
    abrir = MagicMock()
    ventana = _ventana_falsa({"facturacion": SimpleNamespace(nueva_factura=abrir)})

    MainWindow._ejecutar_accion(ventana, "nueva_factura")
    ventana.navegar_a.assert_called_once_with("facturacion")
    qtbot.waitUntil(lambda: abrir.called, timeout=1000)  # se abre con singleShot(0)


def test_ejecutar_una_accion_de_configuracion_selecciona_su_pestana():
    tabs = MagicMock()
    ventana = _ventana_falsa({"config_empresa": SimpleNamespace(tabs=tabs)})

    MainWindow._ejecutar_accion(ventana, "config_correo")

    ventana.navegar_a.assert_called_once_with("config_empresa")
    tabs.setCurrentIndex.assert_called_once_with(1)


def test_accion_desconocida_no_hace_nada():
    ventana = _ventana_falsa()

    MainWindow._ejecutar_accion(ventana, "no_existe")

    ventana.navegar_a.assert_not_called()


def test_todas_las_acciones_de_la_busqueda_estan_cableadas_a_un_panel_real():
    """Cada clave de busqueda_global.ACCIONES debe saber abrirse, y su metodo existir en el panel."""
    from app.services.busqueda_global import ACCIONES
    from app.ui.main_window import ACCIONES_CONFIG, ACCIONES_PANEL

    for accion in ACCIONES:
        assert accion.clave in ACCIONES_PANEL or accion.clave in ACCIONES_CONFIG, accion.clave
    for modulo, metodo in ACCIONES_PANEL.values():
        _, clase_panel = MODULOS_CONFIG[modulo]
        assert callable(getattr(clase_panel, metodo, None)), f"{clase_panel.__name__}.{metodo}"
