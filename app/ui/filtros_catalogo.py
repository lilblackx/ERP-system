"""Listas de los combos de filtro que varios paneles comparten, cargadas en un hilo aparte.

Un panel que llenaba su combo de vendedores con una consulta en el hilo de la ventana al abrirse la dejaba sin
responder mientras la base contestaba (y con la base en otra red, cada apertura esperaba la red). La tarea corre en un
QueryWorker (ver carga_asincrona.py: `cargar_async`) y devuelve tuplas simples, sin entidades ORM.
"""

from PySide6.QtWidgets import QComboBox

from app.db.models import CategoriaCliente, Vendedor


def tarea_vendedores_para_filtro(session) -> list[tuple[int, str]]:
    """Corre en un hilo aparte: (id, nombre) de los vendedores, por nombre."""
    filas = session.query(Vendedor.id_vendedor, Vendedor.nombre_vendedor).order_by(Vendedor.nombre_vendedor).all()
    return [(id_vendedor, nombre) for id_vendedor, nombre in filas]


def tarea_categorias_cliente_para_filtro(session) -> list[tuple[int, str]]:
    """Corre en un hilo aparte: (id, nombre) de las categorias de cliente, por nombre."""
    filas = session.query(CategoriaCliente.id_categoria_cliente, CategoriaCliente.nombre).order_by(
        CategoriaCliente.nombre
    )
    return [(id_categoria, nombre) for id_categoria, nombre in filas]


def llenar_combo_vendedores(combo: QComboBox, vendedores: list[tuple[int, str]], usuario=None) -> None:
    """Llena el combo de "Todos los vendedores" mas los vendedores, sin emitir senales (no es un cambio del usuario) y
    conservando lo que el usuario ya hubiera elegido mientras llegaba la lista. Si `usuario` es un vendedor (tiene
    `id_vendedor_usuario`) el combo queda fijo en el: solo ve lo suyo (ver app/services/alcance_vendedor.py)."""
    elegido = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    combo.addItem("Todos los vendedores")
    for id_vendedor, nombre in vendedores:
        combo.addItem(nombre, id_vendedor)
    if elegido is not None:
        indice = combo.findData(elegido)
        if indice >= 0:
            combo.setCurrentIndex(indice)
    combo.blockSignals(False)
    fijar_vendedor_propio(combo, usuario)


def fijar_vendedor_propio(combo: QComboBox, usuario) -> bool:
    """Si `usuario` es un vendedor, deja el combo fijo en su vendedor y lo deshabilita (el servicio igual solo le
    devuelve lo suyo; esto evita que la pantalla ofrezca filtros que no puede usar). Devuelve True si lo fijo."""
    id_vendedor = getattr(usuario, "id_vendedor_usuario", None)
    if id_vendedor is None:
        return False
    indice = combo.findData(id_vendedor)
    if indice >= 0:
        combo.blockSignals(True)
        combo.setCurrentIndex(indice)
        combo.blockSignals(False)
    combo.setEnabled(False)
    combo.setToolTip("Solo ves lo tuyo")
    return True
