"""Exportacion de TODAS las filas de un listado paginado (no solo la pagina que se ve en pantalla).

Los paneles paginados muestran 20 filas por pagina. Exportar "lo que dice la tabla" entregaba solo esas 20: el
archivo salia incompleto sin avisar. Aqui la exportacion vuelve a pedir el listado completo al servicio, con los
mismos filtros de la pantalla (`por_pagina=POR_PAGINA_EXPORTACION`), y escribe el archivo en un hilo aparte para no
congelar la ventana.

Cada panel aporta una funcion `tarea(session, ruta, **kwargs) -> (ruta, cantidad_de_filas)`; este mixin solo se
ocupa del hilo, del boton ocupado y de los avisos.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.ui.animaciones import liberar_boton, ocupar_boton
from app.ui.message_box import MessageBox
from app.ui.workers import QueryWorker

logger = logging.getLogger(__name__)

# Mas filas de las que cualquier listado de la app llegara a tener: la exportacion no pagina.
POR_PAGINA_EXPORTACION = 1_000_000


class ExportacionCompletaMixin:
    """Para paneles con `session_factory`. `_exportar_listado_completo` corre la tarea en un QueryWorker."""

    def _exportar_listado_completo(
        self,
        tarea: Callable[..., tuple[str, int]],
        ruta: str,
        boton: Any,
        nombre_filas: str = "filas",
        **kwargs: Any,
    ) -> None:
        # Reasignar self._worker_export a un QThread nuevo mientras el viejo sigue corriendo lo destruye a mitad
        # de ejecucion: un segundo clic durante una exportacion se ignora.
        worker_anterior = getattr(self, "_worker_export", None)
        if worker_anterior is not None and worker_anterior.isRunning():
            return
        ocupar_boton(boton)
        self._worker_export = QueryWorker(self.session_factory, tarea, ruta=ruta, **kwargs)
        self._worker_export.resultado.connect(lambda resultado: self._exportacion_lista(boton, nombre_filas, resultado))
        self._worker_export.error.connect(lambda mensaje: self._exportacion_fallida(boton, mensaje))
        self._worker_export.start()

    def _exportacion_lista(self, boton: Any, nombre_filas: str, resultado: tuple[str, int]) -> None:
        liberar_boton(boton)
        ruta, cantidad = resultado
        MessageBox.information(
            self,
            "Exportación exitosa",
            f"Se exportaron {cantidad} {nombre_filas} a:\n{ruta}",
        )

    def _exportacion_fallida(self, boton: Any, mensaje: str) -> None:
        liberar_boton(boton)
        logger.error("Fallo al exportar el listado: %s", mensaje)
        MessageBox.critical(self, "Error", "No se pudo completar la exportación.")
