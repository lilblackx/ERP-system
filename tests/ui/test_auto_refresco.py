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


def test_refresco_asincrono_reselecciona_cuando_la_tabla_ya_se_repueblo(qtbot):
    panel = QWidget()
    tabla = QTableWidget(0, 1)
    QVBoxLayout(panel).addWidget(tabla)
    qtbot.addWidget(panel)
    pendientes = []

    def repoblar(ids):
        tabla.setRowCount(len(ids))
        for fila, valor in enumerate(ids):
            tabla.setItem(fila, 0, QTableWidgetItem(valor))

    repoblar(["10", "9", "8"])
    auto = AutoRefresco(panel, pendientes.append, lambda: tabla, asincrono=True)
    auto.timer.stop()
    panel.show()
    tabla.selectRow(1)  # id 9

    auto.refrescar()  # lanza la carga y vuelve sin esperar: la ventana sigue libre
    assert len(pendientes) == 1 and _id_seleccionado(tabla) == "9"
    repoblar(["11", "10", "9", "8"])  # llega la respuesta: entra una fila nueva arriba
    pendientes[0]()  # al_terminar

    assert _id_seleccionado(tabla) == "9"
