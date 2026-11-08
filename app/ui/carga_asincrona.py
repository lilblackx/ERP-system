"""Carga de listados en un hilo aparte, para que escribir en una barra de busqueda no congele la ventana.

Sin esto, cada pausa al teclear lanzaba la consulta en el hilo de la interfaz: mientras la base respondia, la
ventana no repintaba ni atendia el teclado. Un panel que use CargaAsincronaMixin pide su listado asi:

    self.cargar_async(
        "principal", _tarea_listar, self._poblar_tabla,
        texto_error="No se pudo cargar el listado.", silencioso=True, texto_busqueda=...,
    )

`_tarea_listar(session, **filtros)` corre en el hilo (sin tocar widgets) y devuelve lo que `_poblar_tabla` necesita;
`_poblar_tabla(resultado)` corre ya en el hilo de la interfaz. Si el usuario sigue escribiendo, la respuesta de la
consulta anterior se descarta al llegar (solo se pinta la de lo ultimo que se pidio).

`sincrono=True` mantiene el flujo de siempre en el hilo de la interfaz: lo necesitan los refrescos automaticos
(AutoRefresco vuelve a seleccionar la fila por id justo despues de recargar y espera la tabla ya repoblada).
"""

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QTimer

from app.services.permisos import PermisoDenegadoError
from app.ui.message_box import MessageBox
from app.ui.workers import QueryWorker

logger = logging.getLogger(__name__)


def sesion_para_dialogo(session_factory):
    """Sesion nueva que sobrevive a la tarea (QueryWorker cierra la suya al terminar). La tarea la crea, consulta con
    ella y la devuelve dentro del resultado ({"session": ...}); quien abre el dialogo la usa y la cierra al terminar.
    Si la tarea falla despues de crearla debe cerrarla ella misma. Las sesiones pasan de un hilo a otro solo de forma
    secuencial (primero la tarea, despues la ventana), nunca en paralelo."""
    return session_factory()


def _tarea_carga(session, id_carga: int, clave: str, tarea: Callable[..., Any], filtros: dict) -> dict:
    """Corre en el hilo del QueryWorker. Todo error vuelve como dato: asi el panel decide el mensaje y ninguna
    excepcion se pierde en un slot de Qt."""
    try:
        return {"id_carga": id_carga, "clave": clave, "resultado": tarea(session, **filtros)}
    except PermisoDenegadoError:
        return {"id_carga": id_carga, "clave": clave, "sin_permiso": True}
    except Exception as exc:
        logger.exception("Fallo la carga '%s'", clave)
        return {"id_carga": id_carga, "clave": clave, "error": str(exc)}


class CargaAsincronaMixin:
    """Va ANTES de QWidget/QDialog en las bases del panel: closeEvent espera a los hilos en vuelo."""

    def _estado_carga(self) -> dict:
        return self.__dict__.setdefault("_cargas_async", {"cargas": {}, "workers": set(), "contador": 0})

    def cargar_async(
        self,
        clave: str,
        tarea: Callable[..., Any],
        al_cargar: Callable[[Any], None],
        *,
        texto_error: str,
        texto_sin_permiso: str = "No tienes permiso para consultar esta información.",
        silencioso: bool = False,
        sincrono: bool = False,
        **filtros: Any,
    ) -> None:
        estado = self._estado_carga()
        estado["contador"] += 1
        id_carga = estado["contador"]
        # Una sola carga vigente por clave: lo que llegue con otro id (o de una carga sincrona posterior) se
        # descarta.
        estado["cargas"][clave] = {
            "id": id_carga,
            "al_cargar": al_cargar,
            "texto_error": texto_error,
            "texto_sin_permiso": texto_sin_permiso,
        }
        if sincrono:
            session = self.session_factory()
            try:
                respuesta = _tarea_carga(session, id_carga, clave, tarea, filtros)
            finally:
                session.close()
            self._recibir_carga(respuesta)
            return
        worker = QueryWorker(self.session_factory, _tarea_carga, id_carga, clave, tarea, filtros)
        worker.silencioso = silencioso
        worker.resultado.connect(self._recibir_carga)
        worker.finished.connect(self._liberar_workers_carga)
        estado["workers"].add(worker)  # referencia viva mientras corre (ver workers.py)
        worker.start()

    def _recibir_carga(self, respuesta: dict) -> None:
        carga = self._estado_carga()["cargas"].get(respuesta["clave"])
        if carga is None or respuesta["id_carga"] != carga["id"]:
            # Llego tarde: ya se pidio otra carga. Si traia una sesion abierta para un dialogo (ver
            # sesion_para_dialogo), nadie la va a usar: se cierra aqui.
            sesion = (
                (respuesta.get("resultado") or {}).get("session")
                if isinstance(respuesta.get("resultado"), dict)
                else None
            )
            if sesion is not None:
                sesion.close()
            return
        if respuesta.get("sin_permiso"):
            MessageBox.warning(self, "Sin permiso", carga["texto_sin_permiso"])
            return
        if "error" in respuesta:
            MessageBox.critical(self, "Error de conexión", f"{carga['texto_error']}\n\nError: {respuesta['error']}")
            return
        try:
            carga["al_cargar"](respuesta["resultado"])
        except Exception as exc:
            logger.exception("Fallo al mostrar la carga '%s'", respuesta["clave"])
            MessageBox.critical(self, "Error", f"{carga['texto_error']}\n\nError: {exc}")

    def buscar_con_pausa(self, destino: Callable[[], None], ms: int = 300) -> None:
        """Debounce de la barra de busqueda: `destino` corre cuando el usuario deja de teclear `ms` milisegundos.
        Cada tecla reinicia la cuenta (antes, varios paneles lanzaban una consulta por cada tecla)."""
        estado = self._estado_carga()
        if "timer" not in estado:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._disparar_busqueda_pendiente)
            estado["timer"] = timer
        estado["destino_busqueda"] = destino
        estado["timer"].start(ms)

    def _disparar_busqueda_pendiente(self) -> None:
        self._estado_carga()["destino_busqueda"]()

    def _liberar_workers_carga(self) -> None:
        workers = self._estado_carga()["workers"]
        for worker in [w for w in workers if w.isFinished()]:
            workers.discard(worker)

    def esperar_cargas_async(self) -> None:
        """Un hilo vivo al destruirse el panel haria caer el proceso."""
        for worker in list(self._estado_carga()["workers"]):
            worker.wait(2000)

    def closeEvent(self, event) -> None:
        self.esperar_cargas_async()
        super().closeEvent(event)

    def done(self, resultado: int) -> None:
        """Solo aplica a los QDialog: accept()/reject() cierran por aqui, sin pasar por closeEvent, y un hilo vivo al
        destruirse el dialogo haria caer el proceso."""
        self.esperar_cargas_async()
        super().done(resultado)
