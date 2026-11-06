"""Control de paginacion CENTRAL de la interfaz: lo usan todos los listados paginados.

Antes cada panel armaba su propio `lbl_pagina` + `btn_anterior` + `btn_siguiente` y copiaba la logica de
"ir a la pagina anterior/siguiente" y de habilitar/deshabilitar los botones. Las copias se desviaron: un panel
numeraba las paginas desde 0 y los demas desde 1, otro mostraba solo "Pagina N" sin el total, y algunos dejaban
el indicador en "pagina 3 de 3" con una tabla vacia. Con un solo control el comportamiento es el mismo en toda
la app:

  * Las paginas se numeran SIEMPRE desde 1.
  * El indicador y los botones salen del resultado del servicio (`paginar()` en app/services/paginacion.py:
    `pagina` y `total_paginas` ya vienen corregidos), no de calculos propios del panel.
  * Cambiar un filtro o la busqueda vuelve a la pagina 1 (`reiniciar()`).

Uso en un panel:

    self.paginacion = ControlPaginacion()
    self.paginacion.pagina_cambiada.connect(lambda _pagina: self.cargar())
    ...
    self.cargar():  resultado = servicio.listar(..., pagina=self.paginacion.pagina, ...)
                    self.paginacion.actualizar_desde(resultado)
"""

from __future__ import annotations

from math import ceil

import qtawesome as qta
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from app.ui.styles import BUTTON_SECONDARY_QSS, COLOR_TEXT_DARK, COLOR_TEXT_MUTED


class ControlPaginacion(QWidget):
    """Etiqueta "Página X de Y" + botones anterior/siguiente."""

    # Se emite SOLO cuando el usuario cambia de pagina (botones o `ir_a`), con la pagina nueva (desde 1). Los
    # cambios hechos por `actualizar()`/`reiniciar()` no la emiten: no disparan otra carga.
    pagina_cambiada = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self._pagina = 1
        self._total_paginas = 1
        self._total_registros: int | None = None

        self.lbl_pagina = QLabel()
        self.lbl_pagina.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")

        self.btn_anterior = QPushButton()
        self.btn_anterior.setIcon(qta.icon("fa5s.chevron-left", color=COLOR_TEXT_DARK))
        self.btn_anterior.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_anterior.setFixedWidth(40)
        self.btn_anterior.setToolTip("Página anterior")
        self.btn_anterior.clicked.connect(self.anterior)

        self.btn_siguiente = QPushButton()
        self.btn_siguiente.setIcon(qta.icon("fa5s.chevron-right", color=COLOR_TEXT_DARK))
        self.btn_siguiente.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_siguiente.setFixedWidth(40)
        self.btn_siguiente.setToolTip("Página siguiente")
        self.btn_siguiente.clicked.connect(self.siguiente)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.lbl_pagina)
        layout.addWidget(self.btn_anterior)
        layout.addWidget(self.btn_siguiente)

        self._refrescar()

    # -- estado ---------------------------------------------------------------------------------------
    @property
    def pagina(self) -> int:
        return self._pagina

    @property
    def total_paginas(self) -> int:
        return self._total_paginas

    def actualizar(self, pagina: int, total_paginas: int, total: int | None = None) -> None:
        """Refleja el resultado de una carga (los valores que devolvio el servicio). `total` (opcional) es la
        cantidad de registros: si se da, se muestra junto a la pagina, "Página 1 de 3 (45)"."""
        self._total_registros = total
        self._total_paginas = max(1, int(total_paginas))
        self._pagina = min(max(1, int(pagina)), self._total_paginas)
        self._refrescar()

    def actualizar_desde(self, resultado: dict, mostrar_total: bool = False) -> None:
        """Refleja el diccionario que devuelve un listado paginado ({"pagina", "total_paginas", "total", ...}).
        Es el punto de entrada que usan los paneles. Si `total_paginas` no viene (un resultado armado a mano) se
        calcula a partir de `total` y `por_pagina`."""
        total = resultado.get("total")
        total_paginas = resultado.get("total_paginas")
        if total_paginas is None:
            total_paginas = ceil((total or 0) / max(1, resultado.get("por_pagina") or 1))
        self.actualizar(resultado.get("pagina", 1), total_paginas, total if mostrar_total else None)

    def fijar_pagina(self, pagina: int) -> None:
        """Cambia la pagina a pedir en la proxima carga, sin emitir `pagina_cambiada` (no cargar aun)."""
        self._pagina = max(1, int(pagina))
        self._refrescar()

    def reiniciar(self) -> None:
        """Vuelve a la pagina 1 (cambio de filtro o de busqueda). No emite: el llamador carga a continuacion."""
        self._pagina = 1
        self._refrescar()

    # -- navegacion del usuario -----------------------------------------------------------------------
    def ir_a(self, pagina: int) -> None:
        pagina = min(max(1, int(pagina)), self._total_paginas)
        if pagina != self._pagina:
            self._pagina = pagina
            self._refrescar()
            self.pagina_cambiada.emit(pagina)

    def anterior(self) -> None:
        self.ir_a(self._pagina - 1)

    def siguiente(self) -> None:
        self.ir_a(self._pagina + 1)

    def _refrescar(self) -> None:
        texto = f"Página {self._pagina} de {self._total_paginas}"
        if self._total_registros is not None:
            texto += f" ({self._total_registros})"
        self.lbl_pagina.setText(texto)
        self.btn_anterior.setEnabled(self._pagina > 1)
        self.btn_siguiente.setEnabled(self._pagina < self._total_paginas)


class MixinPaginacion:
    """Para los paneles con un `self.paginacion` (ControlPaginacion): conserva `self.pagina_actual` /
    `self.total_paginas` como atajos de lectura/escritura, para que los filtros sigan haciendo
    `self.pagina_actual = 1` y la carga `pagina=self.pagina_actual` sin duplicar estado en el panel."""

    paginacion: ControlPaginacion

    @property
    def pagina_actual(self) -> int:
        return self.paginacion.pagina

    @pagina_actual.setter
    def pagina_actual(self, valor: int) -> None:
        self.paginacion.fijar_pagina(valor)

    @property
    def total_paginas(self) -> int:
        return self.paginacion.total_paginas


class PaginasPorClave:
    """Para una pantalla con VARIAS listas paginadas (pestañas), cada una con su ControlPaginacion: `paginas["oc"]`
    lee la pagina de ese control y `paginas["oc"] = 1` la fija (sin emitir senal), como el dict de enteros que
    usaban esas pantallas. Con `total=True` expone `total_paginas` en vez de la pagina (solo lectura)."""

    def __init__(self, controles: dict[str, ControlPaginacion], total: bool = False):
        self._controles = controles
        self._total = total

    def __getitem__(self, clave: str) -> int:
        control = self._controles[clave]
        return control.total_paginas if self._total else control.pagina

    def __setitem__(self, clave: str, valor: int) -> None:
        if self._total:
            raise TypeError("total_paginas es de solo lectura: lo fija el servicio via actualizar()")
        self._controles[clave].fijar_pagina(valor)


__all__ = ["ControlPaginacion", "MixinPaginacion", "PaginasPorClave"]
