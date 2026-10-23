from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from app.ui.auto_refresco import AutoRefresco


def _panel_con_tabla(qtbot, ids: list[str]):
    panel = QWidget()
    tabla = QTableWidget(0, 1)
    QVBoxLayout(panel).addWidget(tabla)
    qtbot.addWidget(panel)
    datos = {"ids": ids}

    def recargar():
        tabla.setRowCount(len(datos["ids"]))
        for fila, valor in enumerate(datos["ids"]):
            tabla.setItem(fila, 0, QTableWidgetItem(valor))

    recargar()
    auto = AutoRefresco(panel, recargar, lambda: tabla)
    auto.timer.stop()  # el test dispara refrescar() a mano
    return panel, tabla, datos, auto


def _id_seleccionado(tabla: QTableWidget) -> str | None:
    filas = tabla.selectionModel().selectedRows()
    return tabla.item(filas[0].row(), 0).text() if filas else None


def test_refresco_mantiene_la_misma_fila_seleccionada_aunque_cambie_de_posicion(qtbot):
    panel, tabla, datos, auto = _panel_con_tabla(qtbot, ["10", "9", "8"])
    panel.show()
    tabla.selectRow(1)  # id 9

    datos["ids"] = ["11", "10", "9", "8"]  # entra una fila nueva arriba
    auto.refrescar()

    assert _id_seleccionado(tabla) == "9"


def test_refresco_limpia_la_seleccion_si_la_fila_ya_no_esta(qtbot):
    panel, tabla, datos, auto = _panel_con_tabla(qtbot, ["10", "9"])
    panel.show()
    tabla.selectRow(0)

    datos["ids"] = ["9"]
    auto.refrescar()

    assert _id_seleccionado(tabla) is None


def test_refresco_no_recarga_si_el_panel_no_esta_visible(qtbot):
    panel, tabla, datos, auto = _panel_con_tabla(qtbot, ["1"])

    datos["ids"] = ["1", "2"]
    auto.refrescar()

    assert tabla.rowCount() == 1
