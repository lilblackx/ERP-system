"""Modo "Conciliar inventario": la tabla y las exportaciones quedan solo con las columnas del conteo fisico (Nombre,
Categoria, Cantidad, Cajas, A Granel) mas una columna INVENTARIO FISICO vacia donde se anota lo contado."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openpyxl import load_workbook

import app.ui.inventario_panel as inv

# Una fila completa del catalogo, con las 12 columnas de COLS_VISIBLES (id oculto + 11 visibles).
FILA = [7, "COD-1", "Harina PAN", "Alimentos", "120", "10", "0", "$1.00", "$1.50", "$2.00", "$2.50", "Activo"]


def _filas(*args, **kwargs):
    return [
        list(FILA),
        [8, "COD-2", "Aceite", "Alimentos", "5", "0", "5", "$1.00", "$1.50", "$2.00", "$2.50", "Activo"],
    ]


def _contenido(ruta):
    return [
        [c.value for c in fila]
        for fila in load_workbook(ruta).active.iter_rows()
        if any(c.value is not None for c in fila)
    ]


def test_las_columnas_del_conteo_son_las_del_catalogo_en_su_lugar():
    assert [inv.COLS_VISIBLES[i] for i in inv._INDICES_CONCILIACION] == [
        "NOMBRE",
        "CATEGORÍA",
        "CANTIDAD",
        "CAJAS",
        "A GRANEL",
    ]
    assert inv._COLUMNAS_CONCILIACION == [
        *[inv.COLS_VISIBLES[i] for i in inv._INDICES_CONCILIACION],
        "INVENTARIO FÍSICO",
    ]
    assert inv.COL_INV_FISICO == len(inv.COLS_VISIBLES)


def test_la_exportacion_a_excel_en_modo_conciliacion_lleva_solo_las_columnas_del_conteo(monkeypatch, tmp_path):
    monkeypatch.setattr(inv, "_filas_productos_query", _filas)
    ruta = str(tmp_path / "inventario_fisico.xlsx")

    resultado = inv._tarea_exportar_productos_excel(MagicMock(), ruta, None, None, False, 1, conciliar=True)

    assert resultado == (ruta, 2)
    contenido = _contenido(ruta)
    assert contenido[0] == ["Conciliación de Inventario"] or "Conciliación de Inventario" in str(contenido[0])
    assert inv._COLUMNAS_CONCILIACION in contenido
    filas = contenido[contenido.index(inv._COLUMNAS_CONCILIACION) + 1 :]
    assert filas[0][:5] == ["Harina PAN", "Alimentos", "120", "10", "0"]
    assert filas[0][5] in (None, "")  # INVENTARIO FISICO queda vacio para anotar el conteo
    assert all(len(f) >= 6 for f in filas) and "Activo" not in str(filas)  # ni precios ni estado


def test_la_exportacion_a_excel_sin_modo_conciliacion_sigue_igual(monkeypatch, tmp_path):
    monkeypatch.setattr(inv, "_filas_productos_query", _filas)
    ruta = str(tmp_path / "inventario.xlsx")

    resultado = inv._tarea_exportar_productos_excel(MagicMock(), ruta, None, None, False, 1)

    assert resultado == (ruta, 2)
    contenido = _contenido(ruta)
    assert inv.COLS_VISIBLES in contenido and "INVENTARIO FÍSICO" not in str(contenido)


def test_la_exportacion_a_pdf_en_modo_conciliacion_usa_otro_titulo_y_las_columnas_del_conteo(monkeypatch):
    monkeypatch.setattr(inv, "_filas_productos_query", _filas)
    llamadas = []
    monkeypatch.setattr(
        inv, "exportar_pdf", lambda ruta, titulo, columnas, filas, **k: llamadas.append((titulo, columnas, filas))
    )

    resultado = inv._tarea_exportar_productos_pdf(MagicMock(), "x.pdf", None, None, False, 1, conciliar=True)
    inv._tarea_exportar_productos_pdf(MagicMock(), "y.pdf", None, None, False, 1)

    assert resultado == ("x.pdf", 2)
    titulo, columnas, filas = llamadas[0]
    assert titulo == "Conciliación de Inventario" and columnas == inv._COLUMNAS_CONCILIACION
    assert filas[0] == ["Harina PAN", "Alimentos", "120", "10", "0", ""]
    assert llamadas[1][0] == "Inventario" and llamadas[1][1] == inv.COLS_VISIBLES


@pytest.fixture()
def panel(qtbot, monkeypatch):
    monkeypatch.setattr(inv.InventarioPanel, "cargar_productos", lambda self, *a, **k: None)
    monkeypatch.setattr(inv.InventarioPanel, "_cargar_categorias_filtro", lambda self: None)
    panel = inv.InventarioPanel(MagicMock(), SimpleNamespace(id_usuario=1, id_vendedor_usuario=None))
    qtbot.addWidget(panel)
    panel._auto_refresco.timer.stop()
    return panel


def _columnas_visibles(panel):
    return [c for c in range(panel.tabla.columnCount()) if not panel.tabla.isColumnHidden(c)]


def test_por_defecto_la_tabla_muestra_el_catalogo_completo_sin_la_columna_del_conteo(panel):
    assert _columnas_visibles(panel) == list(range(1, len(inv.COLS_VISIBLES)))
    assert panel.tabla.isColumnHidden(inv.COL_INV_FISICO) and panel.tabla.isColumnHidden(inv.COL_ID_INTERNO)


def test_al_marcar_conciliar_la_tabla_muestra_solo_las_columnas_del_conteo(panel):
    panel.conciliar_check.setChecked(True)

    assert _columnas_visibles(panel) == [*inv._INDICES_CONCILIACION, inv.COL_INV_FISICO]


def test_al_desmarcar_conciliar_vuelve_el_catalogo_completo(panel):
    panel.conciliar_check.setChecked(True)
    panel.conciliar_check.setChecked(False)

    assert _columnas_visibles(panel) == list(range(1, len(inv.COLS_VISIBLES)))


def test_una_carga_nueva_reafirma_el_modo_aunque_el_check_se_haya_limpiado_sin_senales(panel):
    panel.conciliar_check.setChecked(True)
    panel.conciliar_check.blockSignals(True)
    panel.conciliar_check.setChecked(False)  # lo que hace "Limpiar filtros": sin avisar a la tabla
    panel.conciliar_check.blockSignals(False)

    panel._alternar_modo_conciliacion()  # la siguiente carga lo reafirma

    assert _columnas_visibles(panel) == list(range(1, len(inv.COLS_VISIBLES)))


def test_el_modo_viaja_con_los_filtros_de_la_exportacion_y_cambia_el_nombre_del_archivo(panel, monkeypatch):
    assert panel._filtros_actuales_exportar()["conciliar"] is False
    panel.conciliar_check.setChecked(True)
    assert panel._filtros_actuales_exportar()["conciliar"] is True

    nombres = []
    monkeypatch.setattr(
        inv.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: nombres.append(a[2]) or ("", ""))
    )
    panel.exportar_excel_productos()
    panel.exportar_pdf_productos()
    panel.conciliar_check.setChecked(False)
    panel.exportar_excel_productos()

    assert nombres == ["inventario_fisico.xlsx", "inventario_fisico.pdf", "inventario.xlsx"]
