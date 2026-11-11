"""Ancho dinamico de columnas de las tablas: ningun texto se corta mientras haya ancho disponible.

Repartir el ancho por igual (`Stretch` en todas las columnas) corta el nombre de un cliente o el de un producto con
"..." aunque la tabla tenga espacio de sobra, porque cada columna recibe la misma parte sin importar lo que
contiene. Aqui el ancho sale del CONTENIDO:

1. Cada columna mide lo que necesita su texto completo (o su widget de celda, como un EstadoBadge) y su encabezado.
2. Si todo cabe, el ancho que sobra se reparte entre las columnas de texto (las numericas, alineadas a la derecha, no
   crecen).
3. Si no cabe, solo se acortan las columnas de texto (hasta un minimo legible) y el resto conserva su ancho. Si aun asi
   no cabe, la tabla queda con barra horizontal, o, si la tabla no la tiene, se reduce todo proporcionalmente.
4. El texto que aun quede cortado muestra su valor completo en un tooltip.

Se recalcula solo cuando cambian los datos o el tamano de la tabla. Las columnas con modo `Fixed` (ancho fijado a mano)
y las ocultas no se tocan. El usuario puede arrastrar el borde de una columna (modo `Interactive`) hasta el siguiente
refresco.
"""

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Slot
from PySide6.QtWidgets import QHeaderView, QTableView, QTableWidget

# Tope del ancho natural de una columna de texto: una observacion de 300 caracteres no debe pedir toda la pantalla.
ANCHO_MAXIMO_TEXTO = 640
# Hasta donde se acorta una columna de texto antes de pasar a barra horizontal (o a reducir las demas).
ANCHO_MINIMO_TEXTO = 120
# Una columna de texto con contenido de mas de este ancho se considera "larga" (nombre, descripcion) y es la ultima
# que se recorta cuando falta espacio.
ANCHO_COLUMNA_LARGA = 150
# Aire que se suma al ancho medido de cada columna (el estilo redondea y el texto en negrita mide un poco mas).
MARGEN = 6
# Filas que se revisan para decidir si una columna es numerica y para poner tooltips.
# Relleno de las celdas segun TABLE_QSS (app/ui/styles.py): `QTableWidget::item { padding: 8px 12px; }`.
_RELLENO_X = 12
_RELLENO_Y = 8
_FILAS_MUESTRA = 25
_FILAS_TOOLTIP = 5000
_TEXTO_CORTO = 10  # un texto de menos de estos caracteres nunca se corta de forma util: sin tooltip


def _recortar(anchos: dict[int, int], columnas: list[int], minimo: dict[int, int], falta: int) -> int:
    """Quita hasta `falta` px a `columnas` (modifica `anchos`), siempre a la mas ancha, sin bajar de su minimo.
    Devuelve lo que aun falta."""
    while falta > 0:
        activas = [c for c in columnas if anchos[c] > minimo[c]]
        if not activas:
            break
        anchos[max(activas, key=lambda c: anchos[c])] -= 1
        falta -= 1
    return falta


class AjusteColumnas(QObject):
    """Recalcula el ancho de las columnas de una tabla cuando cambian sus datos o su tamano."""

    def __init__(
        self,
        tabla: QTableView,
        texto: tuple[int, ...] | None = None,
        omitir: tuple[int, ...] = (),
        filas_a_texto: bool = False,
    ):
        super().__init__(tabla)
        self.tabla = tabla
        self.texto = set(texto) if texto is not None else None  # None: se deduce del contenido
        self.omitir = set(omitir)
        self.filas_a_texto = filas_a_texto
        self._aplicando = False
        self._pendiente = QTimer(self)
        self._pendiente.setSingleShot(True)
        self._pendiente.setInterval(0)  # junta todos los setItem de una carga en un solo calculo
        self._pendiente.timeout.connect(self.aplicar)

        encabezado = tabla.horizontalHeader()
        encabezado.setStretchLastSection(False)
        modelo = tabla.model()
        if modelo is not None:
            for senal in (
                modelo.rowsInserted,
                modelo.rowsRemoved,
                modelo.columnsInserted,
                modelo.modelReset,
                modelo.layoutChanged,
                modelo.dataChanged,
            ):
                senal.connect(self._programar)
        tabla.viewport().installEventFilter(self)
        tabla.installEventFilter(self)

    @Slot()
    def _programar(self) -> None:
        if not self._aplicando:
            self._pendiente.start()

    def eventFilter(self, objeto, evento) -> bool:  # noqa: N802 (nombre de Qt)
        if evento.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._programar()
        return False

    # ------------------------------------------------------------------ calculo
    def _es_numerica(self, columna: int) -> bool:
        modelo = self.tabla.model()
        vistas = 0
        derechas = 0
        for fila in range(min(modelo.rowCount(), _FILAS_MUESTRA)):
            indice = modelo.index(fila, columna)
            if not modelo.data(indice):
                continue
            vistas += 1
            alineacion = modelo.data(indice, Qt.ItemDataRole.TextAlignmentRole)
            if alineacion is not None and int(alineacion) & int(Qt.AlignmentFlag.AlignRight):
                derechas += 1
        return vistas > 0 and derechas == vistas

    def _ancho_natural(self, columna: int) -> int:
        encabezado = self.tabla.horizontalHeader()
        cuerpo = self.tabla.sizeHintForColumn(columna)
        return max(encabezado.sectionSizeHint(columna), cuerpo) + MARGEN

    def calcular(self) -> dict[int, int]:
        """Ancho de cada columna visible no fija, segun el contenido y el ancho disponible."""
        tabla = self.tabla
        encabezado = tabla.horizontalHeader()
        columnas = [c for c in range(tabla.model().columnCount()) if not tabla.isColumnHidden(c)]
        fijas = [
            c for c in columnas if c in self.omitir or encabezado.sectionResizeMode(c) == QHeaderView.ResizeMode.Fixed
        ]
        libres = [c for c in columnas if c not in fijas]
        if not libres:
            return {}

        disponible = tabla.viewport().width() - sum(encabezado.sectionSize(c) for c in fijas)
        if self.texto is not None:
            de_texto = [c for c in libres if c in self.texto]
        else:
            de_texto = [c for c in libres if not self._es_numerica(c)]
        if not de_texto:
            de_texto = list(libres)

        natural = {}
        for columna in libres:
            ancho = self._ancho_natural(columna)
            if columna in de_texto:
                ancho = min(ancho, ANCHO_MAXIMO_TEXTO + MARGEN)
            natural[columna] = ancho
        anchos = dict(natural)
        sobra = disponible - sum(natural.values())

        if sobra >= 0:
            # Todo cabe: el ancho que sobra va a las columnas de texto, en proporcion a lo que ya ocupan.
            total = sum(natural[c] for c in de_texto) or 1
            repartido = 0
            for columna in de_texto:
                extra = sobra * natural[columna] // total
                anchos[columna] += extra
                repartido += extra
            mayor = max(de_texto, key=lambda c: natural[c])
            anchos[mayor] += sobra - repartido  # el resto de la division entera, para no dejar un hueco
            return anchos

        # No cabe: se acortan solo las columnas de texto, hasta su minimo legible. Primero las demas columnas de texto,
        # de la mas ancha a la mas angosta (se pierde menos informacion recortando un correo o una direccion larga que
        # un ID); la primera columna de texto (el nombre, que identifica la fila) se recorta al final.
        falta = -sobra
        minimo = {c: min(natural[c], max(ANCHO_MINIMO_TEXTO, encabezado.sectionSizeHint(c) + MARGEN)) for c in de_texto}
        # La columna principal es la primera de texto con contenido largo (un nombre, no un codigo); si ninguna lo es,
        # la primera.
        principal = next((c for c in de_texto if natural[c] > ANCHO_COLUMNA_LARGA), de_texto[0])
        for grupo in ([c for c in de_texto if c != principal], [principal]):
            falta = _recortar(anchos, grupo, minimo, falta)
        if falta > 0:
            # Ultimo recurso antes de la barra horizontal: tambien las columnas numericas bajan hasta su encabezado.
            minimo_numerico = {c: min(anchos[c], encabezado.sectionSizeHint(c)) for c in libres}
            falta = _recortar(anchos, libres, minimo_numerico, falta)

        if falta > 0 and tabla.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff:
            # Sin barra horizontal no hay donde ver lo que sobra: se reduce todo, proporcionalmente.
            total = sum(anchos.values())
            factor = max(0.0, (total - falta) / total)
            anchos = {c: max(40, int(a * factor)) for c, a in anchos.items()}
        return anchos

    @Slot()
    def aplicar(self) -> None:
        tabla = self.tabla
        if self._aplicando or not tabla.isVisible() or tabla.model() is None:
            return
        self._aplicando = True
        try:
            encabezado = tabla.horizontalHeader()
            anchos = self.calcular()
            for columna, ancho in anchos.items():
                encabezado.setSectionResizeMode(columna, QHeaderView.ResizeMode.Interactive)
                encabezado.resizeSection(columna, ancho)
            self._poner_tooltips(list(anchos))
            if self.filas_a_texto:
                tabla.setWordWrap(True)
                self._ajustar_alto_de_filas()  # el texto largo baja de linea: la fila crece a su contenido
        finally:
            self._aplicando = False

    def _ajustar_alto_de_filas(self) -> None:
        """Alto de cada fila segun cuantas lineas ocupa su texto en el ancho REAL de su celda. `resizeRowsToContents`
        de Qt no descuenta el relleno del estilo (TABLE_QSS: 12 px a los lados, 8 arriba y abajo): mide con el ancho de
        la columna completo, cree que cabe en una linea y deja el texto cortado."""
        tabla = self.tabla
        if not isinstance(tabla, QTableWidget):
            return
        metricas = tabla.fontMetrics()
        minimo = tabla.verticalHeader().defaultSectionSize()
        columnas = [c for c in range(tabla.columnCount()) if not tabla.isColumnHidden(c)]
        for fila in range(tabla.rowCount()):
            alto_texto = 0
            for columna in columnas:
                item = tabla.item(fila, columna)
                if item is None or not item.text():
                    continue
                ancho = max(20, tabla.columnWidth(columna) - 2 * _RELLENO_X - 4)
                area = metricas.boundingRect(0, 0, ancho, 100000, int(Qt.TextFlag.TextWordWrap), item.text())
                alto_texto = max(alto_texto, area.height())
            tabla.setRowHeight(fila, max(minimo, alto_texto + 2 * _RELLENO_Y + 4))

    def _poner_tooltips(self, columnas: list[int]) -> None:
        """El texto que no quepa en su columna se lee completo al pasar el mouse."""
        tabla = self.tabla
        if not isinstance(tabla, QTableWidget):
            return
        for fila in range(min(tabla.rowCount(), _FILAS_TOOLTIP)):
            for columna in columnas:
                item = tabla.item(fila, columna)
                if item is None or item.toolTip():
                    continue
                texto = item.text()
                if len(texto) >= _TEXTO_CORTO:
                    item.setToolTip(texto)


def ajustar_columnas(
    tabla: QTableView,
    texto: tuple[int, ...] | None = None,
    omitir: tuple[int, ...] = (),
    filas_a_texto: bool = False,
) -> None:
    """Instala el ancho dinamico en `tabla` (ver el docstring del modulo).

    `texto`: columnas que reciben el ancho que sobra; por defecto, las que no son numericas. `omitir`: columnas que no
    se tocan (ancho fijo a mano). `filas_a_texto`: el texto largo baja de linea y la fila crece (en vez de cortarse con
    "..."). Llamarla otra vez sobre la misma tabla solo actualiza esos parametros."""
    existente = getattr(tabla, "_ajuste_columnas", None)
    if existente is not None:
        existente.texto = set(texto) if texto is not None else None
        existente.omitir = set(omitir)
        existente.filas_a_texto = filas_a_texto
        existente._programar()
        return
    tabla._ajuste_columnas = AjusteColumnas(tabla, texto, omitir, filas_a_texto)
