"""Paginacion CENTRAL de la app: un solo punto para todos los listados paginados.

Antes cada servicio repetia `total = query.count(); query.offset((pagina - 1) * por_pagina).limit(...)`, y cada
copia arrastraba los mismos defectos:

  * `pagina < 1` (o `por_pagina < 1`) llegaba tal cual al SQL: `OFFSET` negativo -> error de SQL Server.
  * Pedir una pagina mas alla de la ultima devolvia una pagina VACIA mientras la pantalla ya mostraba "pagina
    N de N".
  * El `ORDER BY` no tenia desempate: con valores repetidos (una fecha de vencimiento, un nombre) SQL Server no
    garantiza el orden entre filas iguales y, al pasar de pagina, algunas filas salian repetidas y otras nunca.

`paginar()` corrige las tres cosas en un unico lugar y devuelve siempre el mismo diccionario. Los listados NO
deben volver a armar su propio `offset/limit`.
"""

from __future__ import annotations

from collections.abc import Sequence
from math import ceil
from typing import Any

POR_PAGINA_DEFECTO = 20


def normalizar_paginacion(
    pagina: Any, por_pagina: Any, por_pagina_defecto: int = POR_PAGINA_DEFECTO
) -> tuple[int, int]:
    """(pagina, por_pagina) validos: enteros >= 1. Un valor ausente, no numerico o menor que 1 se corrige (la
    pagina a 1; por_pagina al defecto si falta y a 1 si es menor que 1)."""
    try:
        pagina = int(pagina)
    except (TypeError, ValueError):
        pagina = 1
    try:
        por_pagina = int(por_pagina)
    except (TypeError, ValueError):
        por_pagina = por_pagina_defecto
    return max(1, pagina), max(1, por_pagina)


def total_paginas(total: int, por_pagina: int) -> int:
    """Cantidad de paginas para `total` filas (siempre >= 1: una lista vacia es la pagina 1 de 1)."""
    return max(1, ceil(max(0, total) / max(1, por_pagina)))


def _resultado(items: list, total: int, pagina: int, por_pagina: int) -> dict:
    return {
        "items": items,
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "total_paginas": total_paginas(total, por_pagina),
    }


def paginar(query, pagina: Any, por_pagina: Any, *orden) -> dict:
    """Ejecuta `query` paginada y devuelve {"items", "total", "pagina", "por_pagina", "total_paginas"}.

    `orden` es OBLIGATORIO y debe terminar en una columna unica (la clave primaria) como desempate:
    `paginar(query, pagina, por_pagina, Banco.nombre_banco, Banco.id_banco)`. Sin desempate el orden entre
    filas iguales no es estable y las paginas pueden repetir o saltarse filas.

    `pagina` se normaliza (>= 1) y, si excede la ultima, se lleva a la ultima: el `pagina` devuelto es el que
    realmente se cargo y es el que la pantalla debe mostrar.
    """
    if not orden:
        raise ValueError("paginar() exige un orden con desempate (termina en la clave primaria)")
    pagina, por_pagina = normalizar_paginacion(pagina, por_pagina)

    def _pagina(numero: int) -> list:
        return query.order_by(*orden).offset((numero - 1) * por_pagina).limit(por_pagina).all()

    items = _pagina(pagina)
    desplazamiento = (pagina - 1) * por_pagina
    # Una pagina a medias (o la primera, vacia) ya dice cuantas filas hay: el COUNT(*) seria otro recorrido
    # completo de la consulta -- en una busqueda con pocos resultados es casi la mitad del tiempo.
    if 0 < len(items) < por_pagina or (not items and pagina == 1):
        return _resultado(items, desplazamiento + len(items), pagina, por_pagina)

    total = query.order_by(None).count()
    ultima = total_paginas(total, por_pagina)
    if pagina > ultima:  # pagina vacia pasada la ultima: se lleva a la ultima
        pagina = ultima
        items = _pagina(pagina)
    return _resultado(items, total, pagina, por_pagina)


def paginar_lista(elementos: Sequence, pagina: Any, por_pagina: Any) -> dict:
    """Misma paginacion para una lista ya armada en memoria (agrupaciones calculadas en Python). El llamador es
    responsable de entregarla ordenada de forma DETERMINISTA (con desempate)."""
    pagina, por_pagina = normalizar_paginacion(pagina, por_pagina)
    total = len(elementos)
    pagina = min(pagina, total_paginas(total, por_pagina))
    inicio = (pagina - 1) * por_pagina
    return _resultado(list(elementos[inicio : inicio + por_pagina]), total, pagina, por_pagina)
