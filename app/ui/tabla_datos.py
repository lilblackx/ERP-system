"""TablaDatos: la tabla estandar de la app, con el ancho de columnas dinamico ya incluido.

Una pantalla nueva que necesite una tabla solo escribe:

    tabla = TablaDatos(["Producto", "Cantidad", "Precio"], alineaciones={1: DERECHA, 2: DERECHA})

y recibe el estilo comun (solo lectura, sin numeracion ni rejilla, filas alternas, sombra) y el reparto dinamico del
ancho (ver app/ui/columnas.py): ningun nombre ni descripcion se corta mientras haya ancho disponible, y lo que aun no
quepa se lee completo en el tooltip. Las tablas que necesitan algo distinto (editable, con selector de filas...) siguen
siendo QTableWidget y llaman a `dar_ancho_a_texto(tabla)` (app/ui/styles.py) para tener el mismo ancho dinamico.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QTableWidget, QWidget

from app.ui.columnas import ajustar_columnas
from app.ui.styles import TABLE_QSS, alinear_encabezados, aplicar_sombra

IZQUIERDA = Qt.AlignmentFlag.AlignLeft
DERECHA = Qt.AlignmentFlag.AlignRight
CENTRO = Qt.AlignmentFlag.AlignCenter


class TablaDatos(QTableWidget):
    """QTableWidget de solo lectura con el estilo de la app y el ancho de columnas dinamico.

    `columnas`: los encabezados. `alineaciones`: indice de columna -> alineacion del encabezado (y de sus celdas: use la
    misma en los items). `texto`: columnas que reciben el ancho que sobra (por defecto, las no numericas). `omitir`:
    columnas con ancho fijo a mano. `filas_a_texto`: el texto largo baja de linea y la fila crece. `seleccionable`:
    permite elegir una fila (por defecto no). `alto_fila`: alto por defecto de cada fila."""

    def __init__(
        self,
        columnas: list[str],
        *,
        alineaciones: dict[int, Qt.AlignmentFlag] | None = None,
        texto: tuple[int, ...] | None = None,
        omitir: tuple[int, ...] = (),
        filas_a_texto: bool = False,
        seleccionable: bool = False,
        alto_fila: int | None = None,
        sombra: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(0, len(columnas), parent)
        self.setHorizontalHeaderLabels(columnas)
        if alineaciones:
            alinear_encabezados(self, alineaciones)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
            if seleccionable
            else QAbstractItemView.SelectionMode.NoSelection
        )
        if seleccionable:
            self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if seleccionable else Qt.FocusPolicy.NoFocus)
        if alto_fila:
            self.verticalHeader().setDefaultSectionSize(alto_fila)
        self.setStyleSheet(TABLE_QSS)
        if sombra:
            aplicar_sombra(self)
        ajustar_columnas(self, texto, omitir, filas_a_texto)

    def agregar_fila(self, valores: list[str], alineaciones: dict[int, Qt.AlignmentFlag] | None = None) -> int:
        """Agrega una fila de texto; `alineaciones` indica la alineacion de las celdas que no van a la izquierda."""
        from PySide6.QtWidgets import QTableWidgetItem

        fila = self.rowCount()
        self.insertRow(fila)
        for columna, valor in enumerate(valores):
            item = QTableWidgetItem(str(valor))
            alineacion = (alineaciones or {}).get(columna)
            if alineacion is not None:
                item.setTextAlignment(int(alineacion | Qt.AlignmentFlag.AlignVCenter))
            self.setItem(fila, columna, item)
        return fila
