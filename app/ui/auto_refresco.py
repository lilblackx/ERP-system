"""Recarga periodica de un listado mientras su panel esta a la vista.

MainWindow cachea cada panel en un QStackedWidget y solo lo recarga en showEvent (al
entrar al modulo). Con varias estaciones trabajando sobre la misma base, un listado que
el usuario deja abierto (Facturacion, Compras, Inventario) quedaba mostrando datos viejos
hasta salir y volver a entrar: una factura emitida en otra caja, el stock que bajo con
esa venta, una recepcion registrada en el deposito. Mismo criterio que el auto-refresh de
CuentasBancariasPanel (30 s).

La recarga se salta si el panel no esta visible o si hay un dialogo modal abierto (un
formulario a medio llenar, una confirmacion, un mensaje de error) -- recargar debajo de
un dialogo no aporta nada y, si la recarga falla, apilaria un segundo mensaje de error.

Las tablas se repueblan por posicion de fila: si entra una factura nueva arriba, la fila
seleccionada pasaria a ser otra factura y "Anular" actuaria sobre la equivocada. Por eso
se guarda el id de la fila seleccionada (columna oculta de id) y se vuelve a seleccionar
esa misma fila por id despues de recargar; si ya no esta en la pagina, se limpia la
seleccion. Tambien se conserva la posicion del scroll.
"""

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication, QTableWidget, QWidget

INTERVALO_AUTO_REFRESCO_MS = 30_000


class AutoRefresco(QObject):
    """`obtener_tabla` devuelve la tabla que `recargar` repuebla en este momento (puede
    cambiar, ej. la pestana activa de Compras); `columna_id` es la columna con el id."""

    def __init__(
        self,
        panel: QWidget,
        recargar: Callable[[], None],
        obtener_tabla: Callable[[], QTableWidget],
        columna_id: int = 0,
        intervalo_ms: int = INTERVALO_AUTO_REFRESCO_MS,
    ):
        super().__init__(panel)
        self._panel = panel
        self._recargar = recargar
        self._obtener_tabla = obtener_tabla
        self._columna_id = columna_id
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refrescar)
        self.timer.start(intervalo_ms)

    def refrescar(self) -> None:
        if not self._panel.isVisible():
            return
        if QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None:
            return

        tabla = self._obtener_tabla()
        id_seleccionado = self._id_seleccionado(tabla)
        scroll = tabla.verticalScrollBar().value()

        self._recargar()

        tabla.clearSelection()
        if id_seleccionado is not None:
            for fila in range(tabla.rowCount()):
                item = tabla.item(fila, self._columna_id)
                if item is not None and item.text() == id_seleccionado:
                    tabla.selectRow(fila)
                    break
        tabla.verticalScrollBar().setValue(scroll)

    def _id_seleccionado(self, tabla: QTableWidget) -> str | None:
        filas = tabla.selectionModel().selectedRows()
        if not filas:
            return None
        item = tabla.item(filas[0].row(), self._columna_id)
        return item.text() if item is not None else None
