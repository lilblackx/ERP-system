"""Guardia: la paginacion es CENTRAL. Estas pruebas fallan si alguien vuelve a escribir su propia paginacion en un
servicio o en una pantalla (lo que causaba errores "en unos modulos y en otros no")."""

import ast
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent / "app"


def _py(sub: str):
    return [p for p in (RAIZ / sub).rglob("*.py") if "__pycache__" not in p.parts]


def test_ningun_servicio_arma_su_propio_offset_limit():
    """Todo `.offset(` vive en app/services/paginacion.py (paginar())."""
    ofensores = [
        p.name for p in _py("services") if p.name != "paginacion.py" and ".offset(" in p.read_text(encoding="utf-8")
    ]

    assert ofensores == []


def test_todo_listado_paginado_de_servicio_usa_el_helper_central():
    """Cada funcion de servicio con `por_pagina` que devuelve paginas debe llamar a paginar()/paginar_lista():
    normaliza la pagina, lleva una pagina excedida a la ultima y exige desempate en el orden."""
    sin_helper = []
    for archivo in _py("services"):
        if archivo.name == "paginacion.py":
            continue
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for fn in ast.walk(arbol):
            if not isinstance(fn, ast.FunctionDef):
                continue
            if not any(a.arg == "por_pagina" for a in fn.args.args + fn.args.kwonlyargs):
                continue
            llamadas = {n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
            # `_pagina_o_todo` (reportes.py) solo envuelve paginar(): pagina, o devuelve todo si no se pide pagina.
            if not llamadas & {"paginar", "paginar_lista", "_pagina_o_todo"}:
                sin_helper.append(f"{archivo.name}::{fn.name}")

    assert sin_helper == []


def test_ninguna_pantalla_arma_su_propia_etiqueta_de_pagina_ni_botones():
    """La etiqueta "Página X de Y" y los botones anterior/siguiente son el ControlPaginacion central."""
    ofensores = []
    for archivo in _py("ui"):
        if archivo.name == "paginacion.py":
            continue
        texto = archivo.read_text(encoding="utf-8")
        if re.search(r'["\']Página \{|f"Página', texto) or re.search(r"def _?pagina_(anterior|siguiente)\b", texto):
            ofensores.append(archivo.name)

    assert ofensores == []


def test_toda_tabla_de_la_interfaz_es_de_solo_lectura():
    """Una QTableWidget/QTableView sin `setEditTriggers(NoEditTriggers)` deja escribir dentro de las celdas (se vio
    en la auditoria de productos: la gente tecleaba texto en la tabla). Toda tabla debe bloquearlo."""
    editables = []
    for archivo in _py("ui"):
        texto = archivo.read_text(encoding="utf-8")
        for n in ast.walk(ast.parse(texto)):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
                f = n.value.func
                if (f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)) in ("QTableWidget", "QTableView"):
                    for t in n.targets:
                        var = ast.unparse(t)
                        if not re.search(re.escape(var) + r"\.setEditTriggers\(", texto):
                            editables.append(f"{archivo.name}:{n.lineno} {var}")

    assert editables == []


def test_ningun_contenedor_usa_reglas_sin_selector_que_se_hereden_a_sus_textos():
    """`tarjeta.setStyleSheet("background-color: ...; border: ...")` SIN selector se aplica a la tarjeta Y a todos sus
    hijos: cada texto se dibuja en una caja propia. Los contenedores se estilizan por objectName/selector
    (`QWidget#SectionCard {...}`) o con aplicar_fondo_panel()."""
    ofensores = []
    for archivo in _py("ui"):
        texto = archivo.read_text(encoding="utf-8")
        if re.search(r'self\.setStyleSheet\(f?"background-color: [^"{]*\{?COLOR_CONTENT_BG\}?;"\)', texto):
            ofensores.append(f"{archivo.name}: fondo de panel sin selector (usar aplicar_fondo_panel)")
    assert ofensores == []
