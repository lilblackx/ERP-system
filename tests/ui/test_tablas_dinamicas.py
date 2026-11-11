"""Toda tabla de la app reparte su ancho segun el contenido (app/ui/columnas.py): un nombre de cliente o de producto no
se corta con "..." mientras haya ancho disponible. Estas pruebas cubren el calculo, el componente TablaDatos y, con
una prueba de codigo, que ninguna tabla nueva vuelva a repartir el ancho por igual."""

import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem

from app.ui.columnas import ANCHO_MAXIMO_TEXTO, ajustar_columnas
from app.ui.tabla_datos import DERECHA, TablaDatos

NOMBRE_LARGO = "CARNICERIA LOS HERMANOS, C.A. (SUCURSAL CENTRO)"
CARPETA_UI = Path(__file__).resolve().parents[2] / "app" / "ui"


def _mostrar(qtbot, tabla, ancho=900):
    qtbot.addWidget(tabla)
    tabla.resize(ancho, 300)
    tabla.show()
    tabla._ajuste_columnas.aplicar()


def _tabla_clientes(qtbot, ancho=900):
    tabla = TablaDatos(["Nombre completo", "Identificación", "Email", "Saldo"], alineaciones={3: DERECHA})
    for nombre in (NOMBRE_LARGO, "E&A CARNICERIA, C.A (BCV)"):
        tabla.agregar_fila([nombre, "J-4070712201", "", "10.00"], {3: DERECHA})
    _mostrar(qtbot, tabla, ancho)
    return tabla


def test_el_nombre_largo_cabe_completo_si_hay_ancho(qtbot):
    tabla = _tabla_clientes(qtbot, ancho=1100)
    necesario = min(tabla.sizeHintForColumn(0), ANCHO_MAXIMO_TEXTO)
    assert tabla.columnWidth(0) >= necesario  # el nombre no se corta con "..."


def test_las_columnas_ocupan_todo_el_ancho_sin_hueco(qtbot):
    tabla = _tabla_clientes(qtbot, ancho=1100)
    total = sum(tabla.columnWidth(c) for c in range(tabla.columnCount()))
    assert abs(total - tabla.viewport().width()) <= 2


def test_las_numericas_no_crecen_y_el_texto_si(qtbot):
    angosta = _tabla_clientes(qtbot, ancho=700)
    ancha = _tabla_clientes(qtbot, ancho=1400)
    assert ancha.columnWidth(3) == angosta.columnWidth(3)  # el saldo (derecha) conserva su ancho
    assert ancha.columnWidth(0) > angosta.columnWidth(0)  # el nombre aprovecha el espacio


def test_sin_espacio_solo_se_acortan_las_columnas_de_texto_y_hay_tooltip(qtbot):
    tabla = _tabla_clientes(qtbot, ancho=500)
    assert tabla.columnWidth(3) >= tabla.horizontalHeader().sectionSizeHint(3)  # el numero no se toca
    assert tabla.item(0, 0).toolTip() == NOMBRE_LARGO  # lo cortado se lee completo con el mouse


def test_se_recalcula_al_cambiar_los_datos(qtbot):
    tabla = _tabla_clientes(qtbot, ancho=1100)
    antes = tabla.columnWidth(1)
    tabla.setItem(0, 1, QTableWidgetItem("IDENTIFICACION EXTREMADAMENTE LARGA DE PRUEBA 0001"))
    tabla._ajuste_columnas.aplicar()
    assert tabla.columnWidth(1) > antes


def test_no_toca_las_columnas_fijas_ni_las_ocultas(qtbot):
    tabla = TablaDatos(["Nombre", "Estado", "ID"])
    tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
    tabla.setColumnWidth(1, 120)
    tabla.setColumnHidden(2, True)
    tabla.agregar_fila([NOMBRE_LARGO, "Pendiente", "7"])
    _mostrar(qtbot, tabla, 800)
    assert tabla.columnWidth(1) == 120
    assert tabla.horizontalHeader().sectionResizeMode(1) == QHeaderView.ResizeMode.Fixed


def test_sin_barra_horizontal_todo_se_reduce_para_caber(qtbot):
    tabla = TablaDatos(["A", "B", "C", "D"])
    tabla.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    tabla.agregar_fila([NOMBRE_LARGO] * 4)
    _mostrar(qtbot, tabla, 500)
    assert sum(tabla.columnWidth(c) for c in range(4)) <= tabla.viewport().width() + 2


def test_filas_a_texto_hace_crecer_la_fila(qtbot):
    tabla = TablaDatos(["Campo", "Valor"], filas_a_texto=True)
    tabla.agregar_fila(["Descripción", NOMBRE_LARGO * 3])
    tabla.agregar_fila(["Código", "A1"])
    _mostrar(qtbot, tabla, 400)
    assert tabla.rowHeight(0) > tabla.rowHeight(1)


def test_ajustar_columnas_en_un_qtablewidget_normal(qtbot):
    tabla = QTableWidget(1, 2)
    tabla.setHorizontalHeaderLabels(["Producto", "Cantidad"])
    item = QTableWidgetItem("5.00")
    item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight))
    tabla.setItem(0, 0, QTableWidgetItem(NOMBRE_LARGO))
    tabla.setItem(0, 1, item)
    ajustar_columnas(tabla)
    ajustar_columnas(tabla)  # llamarla otra vez no instala un segundo ajuste
    assert len(tabla.findChildren(type(tabla._ajuste_columnas))) == 1
    qtbot.addWidget(tabla)
    tabla.resize(900, 200)
    tabla.show()
    tabla._ajuste_columnas.aplicar()
    assert tabla.columnWidth(0) >= min(tabla.sizeHintForColumn(0), ANCHO_MAXIMO_TEXTO)


def test_ninguna_tabla_de_la_app_reparte_el_ancho_por_igual():
    """Guardia: `Stretch` en TODAS las columnas corta los nombres con "..." aunque sobre espacio. Toda tabla usa
    TablaDatos o `dar_ancho_a_texto`/`ajustar_columnas` (app/ui/columnas.py)."""
    reparto_igual = re.compile(
        r"horizontalHeader\(\)\.(setSectionResizeMode\(QHeaderView\.ResizeMode\.Stretch\)|setStretchLastSection\(True\))"
    )
    ajuste = re.compile(r"dar_ancho_a_texto\(|ajustar_columnas\(|TablaDatos\(")
    infractores = []
    for archivo in sorted(CARPETA_UI.glob("*.py")):
        if archivo.name in ("columnas.py", "tabla_datos.py"):
            continue
        codigo = archivo.read_text(encoding="utf-8")
        if reparto_igual.search(codigo):
            infractores.append(f"{archivo.name}: Stretch en todas las columnas")
        tablas = len(re.findall(r"\bQTableWidget\(", codigo))
        if tablas and len(ajuste.findall(codigo)) < tablas:
            infractores.append(f"{archivo.name}: {tablas} tablas, {len(ajuste.findall(codigo))} con ancho dinamico")
    assert not infractores, "\n".join(infractores)
