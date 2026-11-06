"""Novedades de cada version y mensaje de bienvenida al entrar a la app (logica pura, sin Qt ni base de datos).

Al abrir la app despues del login se muestra UNA de estas cosas:
  * primer ingreso de ese usuario  -> saludo de bienvenida ("¡Bienvenido, Luis!");
  * version nueva desde la ultima vez que ese usuario entro en ESTA estacion -> ventana "Novedades" con lo de ESA
    version solamente (no se suman las de versiones intermedias), filtrado por los modulos que su rol puede ver;
  * cualquier otro caso -> saludo breve que se quita solo ("Buenos días, Luis · Bienvenido de nuevo").

Las novedades viven en app/assets/novedades.json (se empaquetan con la app). Lo ultimo visto se guarda por estacion y
usuario (app/utils/novedades_local.py).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.rutas import DIR_ASSETS

logger = logging.getLogger(__name__)

ARCHIVO_NOVEDADES = DIR_ASSETS / "novedades.json"

# Criterio editorial: las novedades son DISCRETAS. Se cuenta lo util y visible para el usuario (algo nuevo o que se
# usa distinto); los arreglos de cosas que no debieron fallar NO se anuncian, se resumen en una sola linea "general"
# ("Mejoras de estabilidad y funcionamiento"). Por eso no existe el tipo "corregido".
TIPOS_DE_CAMBIO = ("nuevo", "mejorado", "general")
ETIQUETAS_TIPO = {"nuevo": "NUEVO", "mejorado": "MEJORADO"}
MAX_CAMBIOS_POR_ENTREGA = 6  # incluye la linea general; mas que eso deja de ser una novedad y pasa a ser una lista
MAX_LARGO_TEXTO = 140


@dataclass(frozen=True)
class Cambio:
    tipo: str  # nuevo | mejorado | general (la linea de "mejoras de estabilidad", sin etiqueta)
    texto: str
    modulos: tuple[
        str, ...
    ] = ()  # claves de modulo del sidebar a las que afecta; vacio = general (lo ve todo el mundo)
    destacado: bool = False  # lo mas util de la entrega: se resalta en la ventana


@dataclass(frozen=True)
class Entrega:
    version: str
    fecha: str  # AAAA-MM-DD
    titulo: str
    cambios: tuple[Cambio, ...] = field(default_factory=tuple)

    @property
    def fecha_legible(self) -> str:
        try:
            return datetime.strptime(self.fecha, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return self.fecha


class TipoBienvenida(Enum):
    PRIMER_INGRESO = "primer_ingreso"
    NOVEDADES = "novedades"
    SALUDO = "saludo"


@dataclass(frozen=True)
class Bienvenida:
    tipo: TipoBienvenida
    titulo: str
    subtitulo: str
    entregas: tuple[Entrega, ...] = ()  # solo con tipo NOVEDADES

    @property
    def mostrar_novedades(self) -> bool:
        return self.tipo is TipoBienvenida.NOVEDADES and bool(self.entregas)


# -- versiones ----------------------------------------------------------------------------------------------------


def clave_version(version: str) -> tuple[int, ...]:
    """ "1.10.2" -> (1, 10, 2); tolera sufijos ("1.2.0-prueba"). Compara numericamente: "1.10.0" > "1.9.0"."""
    numeros = re.findall(r"\d+", (version or "").split("-")[0])
    return tuple(int(n) for n in numeros) or (0,)


# -- carga del archivo ----------------------------------------------------------------------------------------------


def cargar_entregas(ruta=ARCHIVO_NOVEDADES) -> list[Entrega]:
    """Entregas del archivo de novedades, de la mas nueva a la mas vieja. Un archivo ausente o danado NUNCA debe
    impedir abrir la app: se registra y se devuelve una lista vacia."""
    try:
        crudo = json.loads(ruta.read_text(encoding="utf-8"))
        entregas = [
            Entrega(
                version=str(e["version"]),
                fecha=str(e.get("fecha", "")),
                titulo=str(e.get("titulo", "")),
                cambios=tuple(
                    Cambio(
                        tipo=str(c.get("tipo", "mejorado")),
                        texto=str(c["texto"]),
                        modulos=tuple(c.get("modulos", ())),
                        destacado=bool(c.get("destacado", False)),
                    )
                    for c in e.get("cambios", [])
                ),
            )
            for e in crudo["entregas"]
        ]
    except (OSError, ValueError, KeyError, TypeError):
        logger.exception("No se pudo leer el archivo de novedades %s", ruta)
        return []
    return sorted(entregas, key=lambda e: clave_version(e.version), reverse=True)


# -- seleccion y filtrado ---------------------------------------------------------------------------------------------


def entregas_a_mostrar(entregas: list[Entrega], actual: str) -> list[Entrega]:
    """Solo las novedades de la version que esta instalada. NO se acumulan: quien se salto versiones (1.0 -> 1.3) ve
    unicamente lo de la 1.3, nunca las intermedias."""
    tope = clave_version(actual)
    return [e for e in entregas if clave_version(e.version) == tope]


def filtrar_por_modulos(entregas: list[Entrega], modulos_visibles: set[str] | None) -> list[Entrega]:
    """Deja solo los cambios que importan al usuario: los generales (sin modulos) y los de modulos que su rol puede
    ver. Una entrega sin cambios visibles se omite. `modulos_visibles=None` = sin filtrar."""
    if modulos_visibles is None:
        return list(entregas)
    resultado = []
    for entrega in entregas:
        visibles = tuple(c for c in entrega.cambios if not c.modulos or set(c.modulos) & modulos_visibles)
        # La linea "general" sola no justifica abrir una ventana: si a este rol no le aplica nada concreto, se omite.
        if any(c.tipo != "general" for c in visibles):
            resultado.append(Entrega(entrega.version, entrega.fecha, entrega.titulo, visibles))
    return resultado


# -- saludo ------------------------------------------------------------------------------------------------------


def primer_nombre(nombre: str | None, nombre_usuario: str) -> str:
    """ "luis fernando" -> "Luis"; sin nombre registrado, el nombre de usuario ("admin" -> "Admin")."""
    base = (nombre or "").strip().split(" ")[0] or nombre_usuario
    return base[:1].upper() + base[1:]


def saludo_segun_hora(ahora: datetime) -> str:
    if 5 <= ahora.hour < 12:
        return "Buenos días"
    if 12 <= ahora.hour < 19:
        return "Buenas tardes"
    return "Buenas noches"


def preparar_bienvenida(
    *,
    nombre: str,
    ultima_vista: str | None,
    version_actual: str,
    primer_ingreso: bool,
    modulos_visibles: set[str] | None,
    entregas: list[Entrega],
    ahora: datetime | None = None,
) -> Bienvenida:
    """Decide que se le muestra al usuario al entrar y con que texto."""
    ahora = ahora or datetime.now()
    if primer_ingreso:
        return Bienvenida(TipoBienvenida.PRIMER_INGRESO, f"¡Bienvenido, {nombre}!", "Qué gusto tenerte en Nexo ERP")

    version_nueva = ultima_vista is None or clave_version(ultima_vista) < clave_version(version_actual)
    if version_nueva:
        nuevas = filtrar_por_modulos(entregas_a_mostrar(entregas, version_actual), modulos_visibles)
        if nuevas:
            return Bienvenida(
                TipoBienvenida.NOVEDADES,
                f"Hola, {nombre}",
                f"Esto es lo nuevo en Nexo ERP {version_actual}",
                tuple(nuevas),
            )
    return Bienvenida(TipoBienvenida.SALUDO, f"{saludo_segun_hora(ahora)}, {nombre}", "Bienvenido de nuevo")
