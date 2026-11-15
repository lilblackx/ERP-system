"""Ventanas emergentes de las barras de herramientas (Filtrar / Exportar): sin esquinas negras."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QComboBox

from app.ui.toolbar_popups import BotonExportar, BotonFiltros, _PopupAnclado


@pytest.fixture()
def exportar(qtbot):
    boton = BotonExportar(lambda: None, lambda: None)
    qtbot.addWidget(boton)
    boton.show()
    qtbot.waitExposed(boton)
    return boton


def _combo():
    combo = QComboBox()
    combo.addItems(["Todos", "Uno"])
    return combo


@pytest.mark.parametrize("fabrica", ["exportar", "filtros"])
def test_el_popup_es_translucido_y_sin_sombra_nativa_para_que_las_esquinas_redondeadas_no_salgan_negras(qtbot, fabrica):
    boton = BotonExportar(lambda: None, lambda: None) if fabrica == "exportar" else BotonFiltros([("Estado", _combo())])
    qtbot.addWidget(boton)
    popup = boton._popup

    assert popup.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert popup.windowFlags() & Qt.WindowType.Popup
    assert popup.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert popup.windowFlags() & Qt.WindowType.NoDropShadowWindowHint


def test_las_cuatro_esquinas_de_la_ventana_del_popup_son_transparentes(exportar, qtbot):
    exportar._alternar_popup()
    qtbot.waitUntil(exportar._popup.isVisible, timeout=2000)

    imagen = exportar._popup.grab().toImage()
    ancho, alto = imagen.width(), imagen.height()

    for x, y in ((0, 0), (ancho - 1, 0), (0, alto - 1), (ancho - 1, alto - 1)):
        assert QColor.fromRgba(imagen.pixel(x, y)).alpha() == 0, (x, y)
    exportar._popup.hide()


def test_la_tarjeta_del_popup_queda_alineada_con_el_boton_aunque_la_ventana_lleve_margen_de_sombra(exportar, qtbot):
    exportar._alternar_popup()
    qtbot.waitUntil(exportar._popup.isVisible, timeout=2000)

    x_tarjeta = exportar._popup.card.mapToGlobal(exportar._popup.card.rect().topLeft()).x()
    x_boton = exportar.mapToGlobal(exportar.rect().topLeft()).x()

    assert abs(x_tarjeta - x_boton) <= 1
    exportar._popup.hide()


def test_el_popup_se_cierra_con_un_segundo_clic_en_el_boton(exportar, qtbot):
    exportar._alternar_popup()
    qtbot.waitUntil(exportar._popup.isVisible, timeout=2000)

    exportar._alternar_popup()

    assert not exportar._popup.isVisible()
    assert QApplication.activePopupWidget() is None


def test_el_margen_de_sombra_alcanza_para_el_desenfoque_de_la_tarjeta():
    # aplicar_sombra() usa blur=18 por defecto: el margen lateral debe cubrir la mitad del desenfoque
    assert _PopupAnclado.MARGEN_SOMBRA >= 18 // 2


def test_toda_ventana_emergente_propia_de_la_app_es_translucida():
    """Guarda para la app completa: una ventana Popup/ToolTip propia con tarjeta de esquinas redondeadas sin fondo
    translucido deja las esquinas negras. Si aparece una nueva, debe pedir WA_TranslucentBackground."""
    from pathlib import Path

    carpeta = Path(__file__).resolve().parents[2] / "app"
    sin_translucidez = []
    for archivo in sorted(carpeta.rglob("*.py")):
        texto = archivo.read_text(encoding="utf-8")
        crea_popup = (
            "Qt.WindowType.Popup |" in texto or "Qt.WindowType.Popup," in texto or "Qt.WindowType.ToolTip" in texto
        )
        if crea_popup and "WA_TranslucentBackground" not in texto:
            sin_translucidez.append(archivo.name)

    assert sin_translucidez == []
