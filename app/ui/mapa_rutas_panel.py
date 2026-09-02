"""Tercera pestaña del módulo Vendedores: mapa general que pinta, para la ruta
seleccionada, su trazado (origen -> destino por calles, migrations/0040) junto con los
clientes geolocalizados que atiende -- el vinculo es indirecto (Cliente -> Vendedor ->
Ruta), ver ClienteService.listar_clientes_por_ruta. Solo lectura (MapaWidget(editable=
False)); fijar coordenadas se hace desde el formulario de cada cliente/ruta, no desde
aca.

Agrega, por pedido del usuario (2026-09-01, "la ruta debemos poderla ver con y sin
clientes... barra de busqueda donde el usuario pueda buscar X cliente"):
- Un checkbox "Mostrar clientes" que oculta/muestra los puntos sin volver a consultar la
  BD (se cachea la ultima lista en self._ultimos_clientes).
- Una barra de busqueda de clientes (server-side, mismo patron que
  factura_form_dialog.py::_buscar_clientes) que, al elegir uno, cambia el combo a la
  ruta de su vendedor (si tiene) y centra el mapa en el.
"""

import json
import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from app.db.models import Usuario
from app.services.clientes import list_clientes, listar_clientes_por_ruta
from app.services.permisos import PermisoDenegadoError
from app.services.rutas import RutaService
from app.ui.mapa_widget import MapaWidget
from app.ui.styles import (
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_TEXT_MUTED,
)

logger = logging.getLogger(__name__)

LIMITE_BUSQUEDA_CLIENTES = 8


class MapaRutasPanel(QWidget):
    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")
        self._setup_ui()

    def cargar(self) -> None:
        self._cargar_rutas_combo()

    # ── Construcción de la UI ─────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 12, 4, 4)
        root.setSpacing(12)

        root.addWidget(self._make_toolbar())

        self.mapa = MapaWidget(editable=False)
        root.addWidget(self.mapa, stretch=1)

        # Cache de la ultima consulta de clientes de la ruta seleccionada -- el checkbox
        # "Mostrar clientes" repinta desde aca en vez de volver a golpear la BD.
        self._ultimos_clientes: list[tuple[float, float, str]] = []
        self._ultimos_puntos_ruta: list[tuple[float, float, str]] = []
        self._ultimo_trazado: list[tuple[float, float]] | None = None

    def _make_toolbar(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(
            f"background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 8px; padding: 4px;"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)

        lbl = QLabel("Ruta:")

        self.ruta_combo = QComboBox()
        self.ruta_combo.setFixedWidth(220)
        self.ruta_combo.currentIndexChanged.connect(self._cargar_mapa)

        self.chk_mostrar_clientes = QCheckBox("Mostrar clientes")
        self.chk_mostrar_clientes.setChecked(True)
        self.chk_mostrar_clientes.toggled.connect(self._repintar_mapa)

        self.busqueda_cliente_input = QLineEdit()
        self.busqueda_cliente_input.setPlaceholderText("Buscar cliente…")
        self.busqueda_cliente_input.setFixedWidth(200)
        self.busqueda_cliente_input.setFixedHeight(28)
        self.busqueda_cliente_input.returnPressed.connect(self._buscar_cliente)

        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")

        h.addWidget(lbl)
        h.addWidget(self.ruta_combo)
        h.addWidget(self.chk_mostrar_clientes)
        h.addWidget(self.busqueda_cliente_input)
        h.addWidget(self.lbl_info)
        h.addStretch()
        return w

    # ── Lógica de datos ───────────────────────────────────────────────────

    def _cargar_rutas_combo(self) -> None:
        session = self.session_factory()
        try:
            ruta_actual = self.ruta_combo.currentData()
            resultado = RutaService.listar(session, id_usuario=self.usuario.id_usuario, por_pagina=1_000_000)
            self.ruta_combo.blockSignals(True)
            self.ruta_combo.clear()
            for ruta in resultado["items"]:
                self.ruta_combo.addItem(ruta.nombre_ruta, ruta.id_ruta)
            idx = self.ruta_combo.findData(ruta_actual)
            self.ruta_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.ruta_combo.blockSignals(False)
            self._cargar_mapa()
        except PermisoDenegadoError:
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar rutas.")
        except Exception:
            logger.exception("Fallo al cargar el combo de rutas del mapa")
            QMessageBox.critical(self, "Error de conexión", "No se pudo cargar la lista de rutas.")
        finally:
            session.close()

    def _cargar_mapa(self) -> None:
        id_ruta = self.ruta_combo.currentData()
        if id_ruta is None:
            self._ultimos_clientes = []
            self._ultimos_puntos_ruta = []
            self._ultimo_trazado = None
            self.mapa.mostrar_puntos([])
            self.mapa.limpiar_trazado()
            self.lbl_info.setText("No hay rutas registradas todavía.")
            return

        session = self.session_factory()
        try:
            ruta = RutaService.obtener(session, id_ruta, id_usuario=self.usuario.id_usuario)
            if ruta is None:
                return
            clientes = listar_clientes_por_ruta(session, id_ruta, id_usuario=self.usuario.id_usuario)

            self._ultimos_clientes = [
                (float(c.latitud), float(c.longitud), c.nombre_razon_social)
                for c in clientes
                if c.latitud is not None and c.longitud is not None
            ]
            self._ultimos_puntos_ruta = []
            if ruta.latitud is not None and ruta.longitud is not None:
                self._ultimos_puntos_ruta.append((float(ruta.latitud), float(ruta.longitud), "Origen"))
            if ruta.destino_latitud is not None and ruta.destino_longitud is not None:
                self._ultimos_puntos_ruta.append(
                    (float(ruta.destino_latitud), float(ruta.destino_longitud), f"Destino: {ruta.nombre_ruta}")
                )
            self._ultimo_trazado = json.loads(ruta.trazado_geojson) if ruta.trazado_geojson else None

            self._repintar_mapa()

            total_clientes_ruta = len(clientes)
            if not self._ultimos_puntos_ruta:
                self.lbl_info.setText(f"{total_clientes_ruta} cliente(s) geolocalizado(s). La ruta no tiene trazado.")
            else:
                self.lbl_info.setText(f"{total_clientes_ruta} cliente(s) geolocalizado(s).")
        except PermisoDenegadoError:
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar clientes o rutas.")
        except Exception:
            logger.exception("Fallo al cargar el mapa de la ruta %s", id_ruta)
            QMessageBox.critical(self, "Error de conexión", "No se pudo cargar el mapa.")
        finally:
            session.close()

    def _repintar_mapa(self) -> None:
        """Redibuja desde la cache (self._ultimos_*) sin volver a consultar la BD -- usado
        tanto al cargar una ruta como al togglear "Mostrar clientes"."""
        clientes = self._ultimos_clientes if self.chk_mostrar_clientes.isChecked() else []
        self.mapa.mostrar_puntos(clientes, self._ultimos_puntos_ruta)
        if self._ultimo_trazado:
            self.mapa.dibujar_trazado(self._ultimo_trazado)
        else:
            self.mapa.limpiar_trazado()

    def _buscar_cliente(self) -> None:
        texto = self.busqueda_cliente_input.text().strip()
        if not texto:
            return
        session = self.session_factory()
        try:
            resultado = list_clientes(
                session, texto, id_usuario=self.usuario.id_usuario, por_pagina=LIMITE_BUSQUEDA_CLIENTES
            )
            candidatos = [c for c in resultado["items"] if c.latitud is not None and c.longitud is not None]
            if not candidatos:
                QMessageBox.information(
                    self, "Sin resultados", "Ningún cliente geolocalizado coincide con esa búsqueda."
                )
                return
            cliente = candidatos[0]
            id_ruta_cliente = cliente.vendedor.id_ruta if cliente.vendedor else None
            if id_ruta_cliente is not None:
                idx = self.ruta_combo.findData(id_ruta_cliente)
                if idx >= 0 and idx != self.ruta_combo.currentIndex():
                    self.ruta_combo.setCurrentIndex(idx)  # dispara _cargar_mapa() via currentIndexChanged
            self.mapa.centrar(float(cliente.latitud), float(cliente.longitud), zoom=16)
        except PermisoDenegadoError:
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar clientes.")
        except Exception:
            logger.exception("Fallo al buscar cliente '%s' en el mapa de rutas", texto)
            QMessageBox.critical(self, "Error de conexión", "No se pudo buscar el cliente.")
        finally:
            session.close()
