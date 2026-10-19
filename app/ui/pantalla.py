"""
Tamaño de ventanas y diálogos según la pantalla disponible.

Los diálogos se escribieron con tamaño fijo (ej. 920x900 el de cliente) pensando en un monitor
grande: en uno de 1366x768 -- o en uno más grande con la escala de Windows al 125%/150%, que deja
~1100x620 de espacio lógico -- el diálogo no cabe y la barra de tareas se come el pie con los botones
"Guardar"/"Cancelar" (reportado por el usuario). Dos ayudas:

- `ajustar_tamano`: el tamaño deseado acotado al área disponible de la pantalla (esa área ya
  descuenta la barra de tareas). Reemplaza a `setFixedSize`: en pantallas grandes queda igual que
  antes y en las chicas se encoge, sin impedir que el usuario cambie el tamaño.
- `hacer_desplazable`: mete el cuerpo del diálogo en un área con scroll y deja el pie de botones
  fuera de ella, siempre visible. Si el diálogo cabe, no se nota (la barra de scroll solo aparece
  cuando hace falta); si no cabe, se desplaza el contenido en vez de cortarse.
"""

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QFrame, QPushButton, QScrollArea, QVBoxLayout, QWidget

# Lo que la ventana gasta fuera del área de cliente (barra de título, bordes) y un respiro para
# que no quede pegada a los bordes de la pantalla.
MARGEN_HORIZONTAL = 40
MARGEN_VERTICAL = 70
# Por debajo de esto un diálogo deja de ser usable aunque la pantalla sea diminuta.
ANCHO_MINIMO_UTIL = 320
ALTO_MINIMO_UTIL = 240


def geometria_disponible(widget: QWidget | None = None) -> QRect:
    """Área útil de la pantalla donde se mostrará `widget` (sin la barra de tareas)."""
    pantalla = None
    if widget is not None:
        padre = widget.parentWidget()
        pantalla = (padre.screen() if padre is not None else None) or widget.screen()
    pantalla = pantalla or QGuiApplication.primaryScreen()
    return pantalla.availableGeometry() if pantalla is not None else QRect(0, 0, 1366, 728)


def acotar_a_pantalla(ancho: int, alto: int, widget: QWidget | None = None) -> tuple[int, int]:
    area = geometria_disponible(widget)
    max_ancho = max(ANCHO_MINIMO_UTIL, area.width() - MARGEN_HORIZONTAL)
    max_alto = max(ALTO_MINIMO_UTIL, area.height() - MARGEN_VERTICAL)
    return min(ancho, max_ancho), min(alto, max_alto)


def ajustar_tamano(widget: QWidget, ancho: int, alto: int, min_ancho: int = 0, min_alto: int = 0) -> None:
    """Tamaño inicial `ancho`x`alto`, acotado a la pantalla disponible. `min_*` es el mínimo
    que se quiere garantizar, también acotado: un mínimo mayor que la pantalla dejaría la
    ventana cortada sin remedio."""
    ancho_final, alto_final = acotar_a_pantalla(ancho, alto, widget)
    min_ancho_final, min_alto_final = acotar_a_pantalla(min_ancho, min_alto, widget)
    widget.setMinimumSize(min(min_ancho_final, ancho_final), min(min_alto_final, alto_final))
    widget.resize(ancho_final, alto_final)


def _es_pie_de_botones(item) -> bool:
    """El pie de un diálogo es un layout cuyo contenido son botones (Cancelar/Guardar...)."""
    layout = item.layout()
    if layout is None:
        return False
    widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
    return any(isinstance(w, QPushButton) for w in widgets)


def hacer_desplazable(dialogo: QDialog, fijos_al_final: int | None = None) -> None:
    """Mueve el cuerpo del diálogo a un QScrollArea y deja los últimos `fijos_al_final`
    elementos del layout raíz (el pie de botones) fuera, siempre visibles. Con `None` detecta
    solo si el último elemento es un pie de botones (0 o 1). Llamar justo después de armar la UI."""
    raiz = dialogo.layout()
    if not isinstance(raiz, QVBoxLayout) or raiz.count() == 0:
        return
    if fijos_al_final is None:
        fijos_al_final = 1 if _es_pie_de_botones(raiz.itemAt(raiz.count() - 1)) else 0
    cantidad = raiz.count() - fijos_al_final
    if cantidad <= 0:
        return

    contenido = QWidget()
    contenido.setObjectName("DialogoDesplazableContenido")
    contenido.setStyleSheet("QWidget#DialogoDesplazableContenido { background: transparent; }")
    layout = QVBoxLayout(contenido)
    # Margen derecho: espacio para la barra de scroll sin tapar los campos.
    layout.setContentsMargins(0, 0, 6, 0)
    layout.setSpacing(raiz.spacing())
    for _ in range(cantidad):
        item = raiz.takeAt(0)
        if item.widget() is not None:
            layout.addWidget(item.widget())
        elif item.layout() is not None:
            layout.addLayout(item.layout())
        elif item.spacerItem() is not None:
            layout.addSpacerItem(item.spacerItem())

    scroll = QScrollArea()
    scroll.setObjectName("DialogoDesplazable")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setStyleSheet(
        "QScrollArea#DialogoDesplazable { background: transparent; border: none; }"
        " QScrollArea#DialogoDesplazable > QWidget > QWidget { background: transparent; }"
    )
    scroll.setWidget(contenido)
    raiz.insertWidget(0, scroll, 1)  # stretch 1: absorbe todo el alto que sobre
    dialogo.cuerpo_desplazable = scroll


def preparar_dialogo(dialogo: QDialog, ancho: int, alto: int, fijos_al_final: int | None = None) -> None:
    """Atajo para el caso común: tamaño acotado a la pantalla + cuerpo desplazable. Llamar
    DESPUES de armar la UI del diálogo."""
    ajustar_tamano(dialogo, ancho, alto)
    hacer_desplazable(dialogo, fijos_al_final)
