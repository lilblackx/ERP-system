"""Tests del encabezado del Sidebar: el logo se ve expandido y colapsado; colapsado cede su
lugar a la flecha de expandir mientras el mouse esta sobre el encabezado (58 px no alcanzan
para ambos)."""

from types import SimpleNamespace

from app.ui.sidebar import SIDEBAR_COLLAPSED, Sidebar


def _crear_sidebar(qtbot):
    usuario = SimpleNamespace(
        id_usuario=1,
        nombre="Luis Fernandez",
        nombre_usuario="lfernandez",
        rol=SimpleNamespace(nombre="Administrador"),
    )
    sidebar = Sidebar("Distribuidora DJ", usuario)
    qtbot.addWidget(sidebar)
    sidebar.show()
    return sidebar


def test_logo_visible_expandido_y_colapsado(qtbot):
    sidebar = _crear_sidebar(qtbot)
    assert sidebar._lbl_logo.isVisible()

    sidebar._colapsar()
    assert sidebar._lbl_logo.isVisible()
    assert not sidebar.btn_toggle.isVisible()


def test_colapsado_hover_en_encabezado_cambia_logo_por_flecha(qtbot):
    sidebar = _crear_sidebar(qtbot)
    sidebar._colapsar()

    sidebar._actualizar_header_colapsado(hover=True)
    assert sidebar.btn_toggle.isVisible()
    assert not sidebar._lbl_logo.isVisible()

    sidebar._actualizar_header_colapsado(hover=False)
    assert sidebar._lbl_logo.isVisible()
    assert not sidebar.btn_toggle.isVisible()


def test_logo_y_flecha_caben_centrados_en_el_ancho_colapsado(qtbot):
    sidebar = _crear_sidebar(qtbot)
    sidebar._colapsar()
    for hover, ancho in ((False, sidebar._lbl_logo.width()), (True, sidebar.btn_toggle.width())):
        sidebar._actualizar_header_colapsado(hover=hover)
        margenes = sidebar._header_layout.contentsMargins()
        assert margenes.left() + ancho + margenes.right() == SIDEBAR_COLLAPSED


def test_reexpandir_restaura_margenes_del_encabezado(qtbot):
    sidebar = _crear_sidebar(qtbot)
    sidebar._colapsar()
    sidebar._expandir()
    assert sidebar._lbl_logo.isVisible()
    assert sidebar._header_layout.contentsMargins().left() == 14


def test_encabezado_muestra_la_marca_y_la_empresa_como_subtitulo(qtbot):
    sidebar = _crear_sidebar(qtbot)
    assert sidebar._lbl_empresa.text() == "Nexo ERP"
    assert sidebar._lbl_subtitulo_header.text() == "Distribuidora DJ"

    sidebar.actualizar_empresa("Otra Empresa C.A.")
    assert sidebar._lbl_empresa.text() == "Nexo ERP"
    assert sidebar._lbl_subtitulo_header.text() == "Otra Empresa C.A."


def test_el_texto_seleccionado_usa_el_azul_de_la_app_y_no_el_acento_de_windows():
    from PySide6.QtGui import QColor, QPalette

    from app.ui.styles import COLOR_PRIMARY_LIGHT, aplicar_colores_de_marca

    paleta = QPalette()
    paleta.setColor(QPalette.ColorRole.Highlight, QColor("#FF8800"))  # acento naranja del sistema

    aplicar_colores_de_marca(paleta)

    assert paleta.color(QPalette.ColorRole.Highlight) == QColor(COLOR_PRIMARY_LIGHT)
    assert paleta.color(QPalette.ColorRole.HighlightedText) == QColor("white")


# ── Animacion de colapso: respeta el interruptor de animaciones ─────────────


def test_colapsar_sin_animaciones_cambia_el_ancho_de_inmediato(qtbot):
    sidebar = _crear_sidebar(qtbot)
    sidebar.toggle()
    assert sidebar.minimumWidth() == SIDEBAR_COLLAPSED
    assert sidebar.maximumWidth() == SIDEBAR_COLLAPSED
