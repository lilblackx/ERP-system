"""Ajuste de ventanas/diálogos a la pantalla disponible (app/ui/pantalla.py).

Reporte del usuario: en un monitor chico el diálogo de cliente (920x900 fijo) se salía de la
pantalla y la barra de tareas tapaba los botones de abajo. La pantalla se simula parcheando
`geometria_disponible` (la del equipo de pruebas no es controlable)."""

from decimal import Decimal
from unittest.mock import patch

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout

from app.ui import pantalla
from app.ui.pago_linea_dialog import PagoLineaDialog
from app.ui.pantalla import (
    ALTO_MINIMO_UTIL,
    ANCHO_MINIMO_UTIL,
    MARGEN_HORIZONTAL,
    MARGEN_VERTICAL,
    acotar_a_pantalla,
    ajustar_tamano,
    hacer_desplazable,
)


@pytest.fixture
def pantalla_de(monkeypatch):
    def _simular(ancho: int, alto: int) -> None:
        monkeypatch.setattr(pantalla, "geometria_disponible", lambda widget=None: QRect(0, 0, ancho, alto))

    return _simular


def _pie_visible(dialogo, boton) -> bool:
    """El botón entero está dentro del área del diálogo (no cortado por el borde)."""
    esquina = boton.mapTo(dialogo, QPoint(boton.width(), boton.height()))
    return 0 <= esquina.y() <= dialogo.height() and 0 <= esquina.x() <= dialogo.width()


def _dialogo_alto(alto_contenido: int = 2000):
    dialogo = QDialog()
    raiz = QVBoxLayout(dialogo)
    cuerpo = QLabel("contenido")
    cuerpo.setFixedHeight(alto_contenido)
    raiz.addWidget(cuerpo)
    pie = QHBoxLayout()
    boton = QPushButton("Guardar")
    pie.addStretch()
    pie.addWidget(boton)
    raiz.addLayout(pie)
    return dialogo, boton


# ── acotar_a_pantalla / ajustar_tamano ──────────────────────────────────────


def test_en_pantalla_grande_el_tamano_no_cambia(pantalla_de):
    pantalla_de(1920, 1040)
    assert acotar_a_pantalla(920, 900) == (920, 900)


def test_en_pantalla_chica_se_acota_descontando_margenes(pantalla_de):
    pantalla_de(1366, 728)
    assert acotar_a_pantalla(920, 900) == (920, 728 - MARGEN_VERTICAL)
    assert acotar_a_pantalla(1500, 500) == (1366 - MARGEN_HORIZONTAL, 500)


def test_nunca_baja_del_minimo_util(pantalla_de):
    pantalla_de(200, 100)
    assert acotar_a_pantalla(920, 900) == (ANCHO_MINIMO_UTIL, ALTO_MINIMO_UTIL)


def test_ajustar_tamano_acota_tamano_y_minimo(qtbot, pantalla_de):
    pantalla_de(1366, 728)
    dialogo = QDialog()
    qtbot.addWidget(dialogo)

    ajustar_tamano(dialogo, 1200, 900, 1100, 750)

    assert dialogo.width() == 1200
    assert dialogo.height() == 728 - MARGEN_VERTICAL
    # Un minimo mayor que la pantalla dejaria la ventana cortada: tambien se acota.
    assert dialogo.minimumHeight() == 728 - MARGEN_VERTICAL
    assert dialogo.minimumWidth() == 1100


def test_ajustar_tamano_deja_redimensionar(qtbot, pantalla_de):
    """A diferencia de setFixedSize, el usuario puede agrandar/achicar el diálogo."""
    pantalla_de(1920, 1040)
    dialogo = QDialog()
    qtbot.addWidget(dialogo)

    ajustar_tamano(dialogo, 800, 600)

    assert dialogo.minimumSize().width() < dialogo.width()
    assert dialogo.maximumWidth() > dialogo.width()


# ── hacer_desplazable ───────────────────────────────────────────────────────


def test_el_pie_queda_visible_aunque_el_cuerpo_no_quepa(qtbot, pantalla_de):
    pantalla_de(1366, 600)
    dialogo, boton = _dialogo_alto(alto_contenido=2000)
    qtbot.addWidget(dialogo)
    hacer_desplazable(dialogo)
    ajustar_tamano(dialogo, 800, 900)

    dialogo.show()
    qtbot.waitExposed(dialogo)

    assert dialogo.height() <= 600 - MARGEN_VERTICAL
    assert _pie_visible(dialogo, boton)
    scroll = dialogo.findChild(QScrollArea, "DialogoDesplazable")
    assert scroll is not None
    assert scroll.verticalScrollBar().maximum() > 0  # el contenido que no cabe se desplaza


def test_el_pie_no_queda_dentro_del_scroll(qtbot):
    dialogo, boton = _dialogo_alto()
    qtbot.addWidget(dialogo)

    hacer_desplazable(dialogo)

    scroll = dialogo.findChild(QScrollArea, "DialogoDesplazable")
    assert not scroll.isAncestorOf(boton)


def test_con_espacio_de_sobra_no_hay_barra_de_scroll(qtbot, pantalla_de):
    pantalla_de(1920, 1040)
    dialogo, _ = _dialogo_alto(alto_contenido=100)
    qtbot.addWidget(dialogo)
    hacer_desplazable(dialogo)
    ajustar_tamano(dialogo, 600, 500)

    dialogo.show()
    qtbot.waitExposed(dialogo)

    scroll = dialogo.findChild(QScrollArea, "DialogoDesplazable")
    assert scroll.verticalScrollBar().maximum() == 0


def test_sin_pie_todo_el_contenido_va_al_scroll(qtbot):
    dialogo = QDialog()
    raiz = QVBoxLayout(dialogo)
    etiqueta = QLabel("solo contenido")
    raiz.addWidget(etiqueta)
    qtbot.addWidget(dialogo)

    hacer_desplazable(dialogo)

    scroll = dialogo.findChild(QScrollArea, "DialogoDesplazable")
    assert scroll.isAncestorOf(etiqueta)


def test_es_idempotente_con_layout_vacio_o_ajeno(qtbot):
    sin_layout = QDialog()
    qtbot.addWidget(sin_layout)
    hacer_desplazable(sin_layout)  # no debe lanzar
    assert sin_layout.findChild(QScrollArea, "DialogoDesplazable") is None


# ── Un diálogo real ─────────────────────────────────────────────────────────


def test_pago_linea_dialog_cabe_en_una_pantalla_chica(qtbot, pantalla_de):
    pantalla_de(1280, 560)
    with (
        patch("app.ui.pago_linea_dialog.CajaService.listar_cajas", return_value=[]),
        patch("app.ui.pago_linea_dialog.BancoService.listar_cuentas", return_value=[]),
    ):
        dialogo = PagoLineaDialog(None, id_usuario=1)
    qtbot.addWidget(dialogo)

    dialogo.show()
    qtbot.waitExposed(dialogo)

    assert dialogo.height() <= 560 - MARGEN_VERTICAL
    assert _pie_visible(dialogo, dialogo.btn_agregar)
    assert _pie_visible(dialogo, dialogo.btn_cancelar)


# ── Pago en Bs desde el diálogo de pago de factura (doble conversión) ───────


def _dialogo_pago_con_banco(qtbot):
    from types import SimpleNamespace

    cuenta = SimpleNamespace(
        id_cuenta=1,
        banco=SimpleNamespace(nombre_banco="Banco"),
        numero_cuenta="12345678",
        estado_cuenta="ACTIVO",
    )
    with (
        patch("app.ui.pago_linea_dialog.CajaService.listar_cajas", return_value=[]),
        patch("app.ui.pago_linea_dialog.BancoService.listar_cuentas", return_value=[cuenta]),
    ):
        dialogo = PagoLineaDialog(None, id_usuario=1)
    qtbot.addWidget(dialogo)
    return dialogo


@pytest.mark.parametrize("metodo", ["transferencia", "punto_de_venta"])
def test_pago_en_bs_envia_usd_y_no_se_convierte_dos_veces(qtbot, metodo):
    """Bs 4.000 a tasa 40 = $100. El dialogo mostraba $100 en 'Monto' pero devolvia
    moneda='VES' con monto_moneda_origen=100, y el servicio lo dividia otra vez entre la tasa
    ($2,50)."""
    from types import SimpleNamespace

    from app.services.ventas import _convertir_a_usd

    dialogo = _dialogo_pago_con_banco(qtbot)
    dialogo.metodo_combo.setCurrentIndex(dialogo.metodo_combo.findData(metodo))
    dialogo.tasa_input.set_value(Decimal("40"))
    dialogo.bolivares_input.set_value(Decimal("4000"))
    dialogo._calcular_monto_usd()  # lo que dispara la edicion del campo Bs

    datos = dialogo.get_data()

    assert datos["moneda"] == "USD"
    assert datos["monto_moneda_origen"] == Decimal("100.00")
    assert datos["monto_bolivares"] == Decimal("4000.00")
    assert datos["tasa_cambio"] == Decimal("40.00")
    tasa = SimpleNamespace(tasa_dolar_bcv=Decimal("40"), tasa_cop=None)
    assert _convertir_a_usd(datos["monto_moneda_origen"], datos["moneda"], tasa) == Decimal("100.00")


def test_con_bloque_bs_la_moneda_queda_fija_en_usd(qtbot):
    dialogo = _dialogo_pago_con_banco(qtbot)

    dialogo.metodo_combo.setCurrentIndex(dialogo.metodo_combo.findData("transferencia"))

    assert dialogo.moneda_combo.currentData() == "USD"
    assert not dialogo.moneda_combo.isEnabled()
    assert "USD" in dialogo.lbl_monto.text()


def test_otros_metodos_siguen_eligiendo_moneda(qtbot):
    dialogo = _dialogo_pago_con_banco(qtbot)

    dialogo.metodo_combo.setCurrentIndex(dialogo.metodo_combo.findData("transferencia"))
    dialogo.metodo_combo.setCurrentIndex(dialogo.metodo_combo.findData("zelle"))

    assert dialogo.moneda_combo.isEnabled()
    assert dialogo.moneda_combo.currentData() == "USD"
    assert "USD" not in dialogo.lbl_monto.text()

    dialogo.metodo_combo.setCurrentIndex(dialogo.metodo_combo.findData("binance"))
    assert dialogo.moneda_combo.currentData() == "USDT"
