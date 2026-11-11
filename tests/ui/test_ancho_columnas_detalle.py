"""Las tablas de detalle dan el ancho sobrante a la columna de texto largo (producto, descripcion) en vez de repartirlo
por igual: antes el nombre de un producto quedaba en una cuarta parte del dialogo y se cortaba."""

from PySide6.QtWidgets import QTableWidget, QTableWidgetItem

from app.ui.styles import ajustar_filas_a_texto, dar_ancho_a_texto, item_con_tooltip

NOMBRE_LARGO = "Aceite de girasol refinado premium botella de 900 ml, caja con 12 unidades"


def _tabla(qtbot, columnas=4):
    tabla = QTableWidget(2, columnas)
    qtbot.addWidget(tabla)
    return tabla


def test_el_nombre_largo_baja_de_linea_y_la_fila_crece(qtbot):
    tabla = _tabla(qtbot, columnas=2)
    dar_ancho_a_texto(tabla, 0)
    tabla.setItem(0, 0, QTableWidgetItem(NOMBRE_LARGO))
    tabla.setItem(0, 1, QTableWidgetItem("12.00"))
    tabla.setItem(1, 0, QTableWidgetItem("Sal"))
    tabla.setItem(1, 1, QTableWidgetItem("1.00"))
    tabla.setColumnWidth(1, 80)
    tabla.resize(260, 200)
    tabla.show()
    ajustar_filas_a_texto(tabla)
    assert tabla.wordWrap()
    assert tabla.rowHeight(0) > tabla.rowHeight(1)


def test_el_item_con_tooltip_muestra_el_texto_completo(qtbot):
    assert item_con_tooltip(NOMBRE_LARGO).toolTip() == NOMBRE_LARGO
    assert item_con_tooltip("Sal", "Sal fina").toolTip() == "Sal fina"
