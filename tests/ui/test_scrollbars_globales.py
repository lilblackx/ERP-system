"""Las barras de desplazamiento son un componente GLOBAL (SCROLLBAR_QSS en GLOBAL_QSS): iguales en toda la app."""

import re
from pathlib import Path

from app.ui.styles import GLOBAL_QSS, SCROLLBAR_QSS

RAIZ_UI = Path(__file__).resolve().parents[2] / "app" / "ui"


def test_el_estilo_global_cubre_vertical_horizontal_y_las_zonas_de_pagina():
    """Sin las zonas `page` Windows dibuja su patron rayado junto al asa; sin la horizontal queda la barra nativa."""
    for regla in (
        "QScrollBar:vertical",
        "QScrollBar:horizontal",
        "QScrollBar::handle:vertical",
        "QScrollBar::handle:horizontal",
        "QScrollBar::add-page",
        "QScrollBar::sub-page",
        "QScrollBar::add-line",
        "QScrollBar::sub-line",
        "QAbstractScrollArea::corner",
    ):
        assert regla in SCROLLBAR_QSS, regla


def test_el_estilo_de_las_barras_forma_parte_del_estilo_global_de_la_app():
    assert SCROLLBAR_QSS.strip() in GLOBAL_QSS


def test_ninguna_pantalla_define_sus_propias_barras_de_desplazamiento():
    """Una sola definicion para todos. Excepcion: la barra lateral, que es oscura y necesita colores propios."""
    ofensores = [
        archivo.name
        for archivo in sorted(RAIZ_UI.glob("*.py"))
        if archivo.name not in ("styles.py", "sidebar.py")
        and re.search(r"QScrollBar", archivo.read_text(encoding="utf-8"))
    ]

    assert ofensores == []
