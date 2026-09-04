"""Widget de mapa reutilizable (Leaflet + OpenStreetMap, sin costo ni API key) para fijar
o visualizar coordenadas de clientes y rutas. Usa QWebEngineView (motor Chromium
embebido, ya incluido en el wheel completo de PySide6 -- no agrega una dependencia
nueva). Las tiles de OpenStreetMap siempre vienen de internet (no se pueden vendorizar,
son imagenes dinamicas por zoom/posicion), pero Leaflet en si (leaflet.js/leaflet.css +
los iconos de marcador) esta vendorizado en app/ui/web/leaflet/ y se carga desde disco
(`QUrl.fromLocalFile`) -- cargarlo desde su CDN publico (unpkg) en cada apertura de
dialogo sumaba 1-2 round-trips de red (DNS+TLS+descarga) SOLO para la libreria, antes de
poder pintar nada; en disco es practicamente instantaneo (hallazgo de rendimiento,
2026-09-01, "la vista del mapa tarda en cargar"). Las tiles en si siguen requiriendo
conexion a internet para verse -- decision aceptada por el usuario a cambio de no pagar
ni gestionar API keys.

Comunicacion JS -> Python sin QWebChannel (evita tener que vendorizar qwebchannel.js): un
click en el mapa dispara una navegacion a un esquema de URL ficticio
(mapaclick://set?lat=..&lng=..) que _MapaPage intercepta y cancela en
acceptNavigationRequest, leyendo los parametros de la URL en vez de dejar navegar. Esa
navegacion se hace en un <iframe> oculto (`#canal-click`), no en el frame principal:
navegar el frame principal y cancelarlo (return False) dispara loadFinished(ok=False) de
la *pagina completa*, y _on_load_finished lo trataba como fallo de carga real -- el mapa
mostraba "No se pudo cargar el mapa" tras cada click aunque la coordenada ya se hubiera
guardado, forzando a pulsar "Reintentar" y perder la vista/zoom (reportado por el
usuario, 2026-09-01). loadFinished solo reporta el frame principal, asi que cancelar la
navegacion de un iframe no lo dispara.
Comunicacion Python -> JS: runJavaScript() invocando funciones ya definidas en la pagina.

En modo editable agrega ademas, por comodidad de UX (2026-09-01):
- Un centrado inicial automatico en la ubicacion aproximada del dispositivo (geo por IP,
  ver app/ui/geo_http.py) para no arrancar siempre en un punto fijo lejano al usuario --
  nunca fija un marcador solo, solo centra/hace zoom.
- Una barra de busqueda de lugares por nombre (Nominatim/OpenStreetMap, mismo modulo) con
  sugerencias en vivo (debounce de 450ms mientras se escribe, sin mover el marcador hasta
  que el usuario elige una) ademas de busqueda explicita (boton/Enter, que si aplica el
  primer resultado de una vez). Seleccionar una sugerencia funciona igual que un click en
  el mapa: mueve el marcador y emite `coordenadas_cambiadas`.
- Un boton "Usar mi ubicacion" que pide la posicion precisa del dispositivo y coloca el
  marcador (o agrega un vertice, en modo "zona") ahi mismo -- accion explicita del
  usuario, a diferencia del centrado por IP que es automatico y nunca fija nada. Usa el
  Geolocator nativo de Windows (`app/ui/geo_windows.py`), NO `navigator.geolocation` de
  Chromium (2026-09-03, hallazgo del usuario "el boton no esta funcionando bien"): los
  builds de QtWebEngine no traen la clave de API de Google que ese API necesita en
  desktop para su proveedor de ubicacion por red, asi que fallaba casi siempre con
  POSITION_UNAVAILABLE. El Geolocator de Windows consulta al proveedor de ubicacion del
  propio sistema operativo en cambio (GPS si el equipo lo tiene, o WiFi/red que Windows
  ya resuelve) -- ver el docstring de geo_windows.py para el detalle completo.

Ademas, `setHtml()` (lo unico lento del widget: crea la pagina de Chromium) se dispara
con `QTimer.singleShot(0, ...)` en vez de en `__init__` -- el dialogo que contiene el
mapa (ClienteFormDialog/RutaFormDialog) queda visible de inmediato con el area del mapa
en blanco un instante, en vez de bloquear la apertura completa del dialogo hasta que
Chromium termine de inicializar la pagina.
"""

import functools
import json
import logging
from pathlib import Path

from PySide6.QtCore import QStringListModel, Qt, QTimer, QUrl, QUrlQuery, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEnginePermission, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QCompleter,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.geo_http import HttpWorker, buscar_lugares, obtener_ubicacion_dispositivo
from app.ui.geo_windows import obtener_ubicacion_precisa_windows

logger = logging.getLogger(__name__)

_LEAFLET_DIR = Path(__file__).resolve().parent / "web" / "leaflet"
_LEAFLET_BASE_URL = QUrl.fromLocalFile(_LEAFLET_DIR.as_posix() + "/")

_CENTRO_DEFAULT_LAT = 10.4806
_CENTRO_DEFAULT_LNG = -66.9036
_ZOOM_DEFAULT = 6
_ZOOM_MARCADOR = 15

# Bounding box aproximado de Venezuela (continental, sin islas remotas como Aves) --
# la app opera solo en Venezuela, asi que un centrado automatico por IP que resuelva
# fuera de este rango (VPN, proxy, geolocalizacion imprecisa del proveedor) se descarta
# en vez de abrir el mapa en otro continente (reportado por el usuario, 2026-09-03: el
# mapa abria centrado en Europa). No aplica a la busqueda de lugares (Nominatim), que ya
# restringe por `countrycodes=ve` en app/ui/geo_http.py::buscar_lugares().
_VE_LAT_MIN, _VE_LAT_MAX = 0.6, 12.6
_VE_LNG_MIN, _VE_LNG_MAX = -73.4, -59.5


def _dentro_de_venezuela(lat: float, lng: float) -> bool:
    return _VE_LAT_MIN <= lat <= _VE_LAT_MAX and _VE_LNG_MIN <= lng <= _VE_LNG_MAX


_HTML_BASE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<link rel="stylesheet" href="leaflet.css" />
<script src="leaflet.js"></script>
<style>
html, body, #mapa {{ height: 100%; margin: 0; padding: 0; }}
/* Numero de orden sobre cada vertice de la zona (redibujarZona) -- tooltip permanente
   en vez del globo con flecha que Leaflet dibuja por defecto, para que se lea como una
   etiqueta numerada, no como un mensaje emergente. */
.zona-vertice-tooltip {{
    background: #1D4ED8;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 0px 5px;
    font-size: 11px;
    font-weight: bold;
    box-shadow: none;
}}
.zona-vertice-tooltip::before {{ display: none; }}
</style>
</head>
<body>
<div id="mapa"></div>
<iframe id="canal-click" style="display:none"></iframe>
<script>
    var map = L.map('mapa').setView([{centro_lat}, {centro_lng}], {zoom});
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 19
    }}).addTo(map);

    // map.invalidateSize() antes de cada setView/fitBounds mas abajo (no una sola vez
    // aca al inicio): esta pagina se sirve dentro de una pestaña (ej. "Mapa" del modulo
    // Vendedores) que puede recien estar volviendose visible/con su tamaño final de
    // pixeles justo cuando se pide centrar/ajustar el mapa -- sin invalidateSize()
    // Leaflet sigue usando el tamaño de contenedor que tenia cuando se inicializo (a
    // veces 0x0), y fitBounds() calcula un zoom degenerado (todo el mundo visible)
    // aunque el centro este bien calculado -- reportado por el usuario, 2026-09-01
    // ("el mapa abre con el mundo entero, sin zoom").

    var marcadores = [];
    var poligonoZona = null;
    var verticesZona = [];
    var marcadoresZona = [];

    function limpiarMarcadores() {{
        marcadores.forEach(function(m) {{ map.removeLayer(m); }});
        marcadores = [];
    }}

    function establecerMarcadorUnico(lat, lng) {{
        limpiarMarcadores();
        var m = L.marker([lat, lng]).addTo(map);
        marcadores.push(m);
        map.invalidateSize();
        map.setView([lat, lng], Math.max(map.getZoom(), {zoom_marcador}));
    }}

    function agregarMarcadorCliente(lat, lng, etiqueta) {{
        var m = L.marker([lat, lng]).addTo(map);
        if (etiqueta) {{ m.bindPopup(etiqueta); }}
        marcadores.push(m);
    }}

    // Zona de cobertura de una ruta (poligono de vertices marcados por click, migrations/
    // 0043 -- reemplaza el antiguo par origen/destino + trazado por calles). El poligono
    // se redibuja entero en cada cambio (agregar/deshacer/limpiar/establecer vertice) en
    // vez de mutarse incrementalmente -- son listas cortas (una zona de reparto real no
    // tiene cientos de vertices), no vale la pena la complejidad de un diff.
    function redibujarZona() {{
        if (poligonoZona) {{ map.removeLayer(poligonoZona); poligonoZona = null; }}
        marcadoresZona.forEach(function(m) {{ map.removeLayer(m); }});
        marcadoresZona = [];

        // Un marcador numerado por vertice (1, 2, 3...) para identificarlos en vivo a
        // medida que se marcan -- pedido del usuario, 2026-09-03: sin esto solo se veia
        // el contorno del poligono, sin forma de distinguir el orden ni el punto exacto
        // de cada click.
        verticesZona.forEach(function(v, i) {{
            var m = L.circleMarker(v, {{
                radius: 6, color: '#1D4ED8', fillColor: '#3B82F6', fillOpacity: 1, weight: 2
            }}).bindTooltip(String(i + 1), {{
                permanent: true, direction: 'top', offset: [0, -6], className: 'zona-vertice-tooltip'
            }}).addTo(map);
            marcadoresZona.push(m);
        }});

        if (verticesZona.length >= 3) {{
            poligonoZona = L.polygon(verticesZona, {{
                color: '#2563EB', weight: 3, fillColor: '#3B82F6', fillOpacity: 0.25
            }}).addTo(map);
        }} else if (verticesZona.length === 2) {{
            // Menos de 3 vertices todavia no es un poligono valido -- se muestra como
            // linea punteada mientras el usuario sigue marcando, en vez de no mostrar
            // nada (sin feedback visual de los primeros clicks). Con 1 solo vertice no
            // hay linea que trazar -- el marcador numerado de arriba ya es suficiente
            // feedback.
            poligonoZona = L.polyline(verticesZona, {{ color: '#2563EB', weight: 3, dashArray: '6 6' }}).addTo(map);
        }}
    }}

    function limpiarZona() {{
        verticesZona = [];
        redibujarZona();
    }}

    function establecerZona(vertices) {{
        verticesZona = vertices.slice();
        redibujarZona();
        ajustarVista();
    }}

    function centrarSinMarcador(lat, lng, zoom) {{
        map.invalidateSize();
        map.setView([lat, lng], zoom);
    }}

    function ajustarVista() {{
        // Une marcadores (clientes/punto unico), los marcadores numerados de la zona y
        // el poligono de zona (si hay) en un solo encuadre -- MapaRutasPanel pinta
        // clientes+zona juntos, y esto permite centrar ya desde el primer vertice
        // marcado (antes de que exista poligono/linea que dibujar).
        var capas = marcadores.concat(marcadoresZona);
        if (poligonoZona) {{ capas.push(poligonoZona); }}
        if (capas.length === 0) {{ return; }}
        map.invalidateSize();
        if (capas.length === 1) {{
            var capa = capas[0];
            if (capa.getLatLng) {{
                map.setView(capa.getLatLng(), {zoom_marcador});
            }} else {{
                map.fitBounds(capa.getBounds().pad(0.15));
            }}
            return;
        }}
        map.fitBounds(L.featureGroup(capas).getBounds().pad(0.2));
    }}

    if ({editable}) {{
        map.on('click', function(e) {{
            document.getElementById('canal-click').src =
                'mapaclick://set?lat=' + e.latlng.lat + '&lng=' + e.latlng.lng;
        }});
    }}
</script>
</body>
</html>
"""


class _MapaPage(QWebEnginePage):
    """QWebEnginePage que intercepta el esquema `mapaclick://` para recibir clicks del
    mapa sin necesitar QWebChannel (ver docstring del modulo). `mapaclick://set?...`
    (solo clicks -- la geolocalizacion precisa del boton "Mi ubicacion" ya NO pasa por
    esta pagina, ver `app/ui/geo_windows.py`) llama on_click."""

    def __init__(self, on_click, parent=None):
        super().__init__(parent)
        self._on_click = on_click
        # La pagina se sirve desde file:// (Leaflet vendorizado en disco, ver docstring
        # del modulo) -- por defecto Chromium bloquea que una pagina file:// pida
        # recursos a un host remoto, asi que sin esto las tiles de OpenStreetMap
        # (https://*.tile.openstreetmap.org/...) nunca llegaban a cargar aunque Leaflet
        # en si (ya local) funcionaba perfecto: diagnosticado 2026-09-01 con un test
        # standalone que mostro los controles de Leaflet pintando bien pero las tiles en
        # blanco/gris.
        self.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        # Nada en esta pagina pide permisos de navegador hoy (la geolocalizacion precisa
        # se resuelve nativamente en Python, no via navigator.geolocation -- ver
        # geo_windows.py); se deniega cualquier solicitud por defecto como resguardo.
        self.permissionRequested.connect(self._on_permission_requested)

    def _on_permission_requested(self, permission: QWebEnginePermission) -> None:
        permission.deny()

    def acceptNavigationRequest(self, url: QUrl, tipo, es_frame_principal: bool) -> bool:  # noqa: N802 (override de Qt)
        if url.scheme() == "mapaclick":
            query = QUrlQuery(url)
            try:
                lat = float(query.queryItemValue("lat"))
                lng = float(query.queryItemValue("lng"))
            except ValueError:
                return False
            # Diferido a la siguiente vuelta del event loop (QTimer.singleShot(0, ...)),
            # no invocado en el momento: on_click termina emitiendo una señal que un
            # dialogo (ClienteFormDialog/RutaFormDialog) escucha para llamar de vuelta a
            # runJavaScript() en esta misma pagina (dibujar el marcador) -- hacerlo
            # sincronicamente, todavia dentro del callback de acceptNavigationRequest de
            # ESTA navegacion (que ademas se esta cancelando con `return False`), hacia
            # que QtWebEngine ignorara silenciosamente ese runJavaScript reentrante: las
            # coordenadas llegaban a los inputs del formulario pero el mapa no se
            # actualizaba (reportado por el usuario, 2026-09-01, con el boton "Mi
            # ubicación" -- mismo mecanismo que un click normal, ver docstring de la
            # clase). Diferir un tick deja que Chromium termine de resolver esta
            # navegacion antes de que corra cualquier JS nuevo.
            QTimer.singleShot(0, lambda: self._on_click(lat, lng))
            return False
        return super().acceptNavigationRequest(url, tipo, es_frame_principal)


class MapaWidget(QWidget):
    """Mapa Leaflet embebido.

    En modo editable con `modo="punto"` (default; `ClienteFormDialog`): un click emite
    `coordenadas_cambiadas` -- el llamador es quien dibuja el marcador con
    `set_coordenadas()`, tambien usado para moverlo programaticamente (ej. el usuario
    tipea lat/lng a mano en vez de hacer click). Buscar un lugar o pedir la ubicacion
    precisa SI dibujan el marcador ellos mismos ademas de emitir la señal -- mismo
    resultado final, solo cambia quien lo dispara.

    En modo editable con `modo="zona"` (`RutaFormDialog`, migrations/0043): cada click
    acumula un vertice del poligono de la zona de cobertura de la ruta en vez de mover un
    marcador unico, y emite `vertice_zona_agregado(lat, lng)` en vez de
    `coordenadas_cambiadas` -- el llamador mantiene la lista de vertices y llama
    `establecer_zona()`/`limpiar_zona()` para reflejarla en el mapa (mismo criterio que
    modo "punto": el dialogo es dueño del estado, MapaWidget solo dibuja lo que se le
    pide). `establecer_zona()` reemplaza el poligono COMPLETO en cada llamada -- no hay
    un "agregar un vertice" incremental: RutaFormDialog reordena los vertices por angulo
    antes de cada redibujado para que el poligono nunca quede auto-intersectado (ver
    ruta_form_dialog.py::_ordenar_por_angulo), asi que la lista entera puede cambiar de
    orden con cada click, no solo crecer. Buscar un lugar en este modo solo re-centra el
    mapa (no agrega un vertice): con varios vertices en juego, no hay "el punto activo"
    al que aplicarle un resultado de busqueda.

    En modo solo-lectura (`editable=False`, mapa general de rutas): `mostrar_puntos()`
    pinta muchos clientes de una vez; `establecer_zona()` pinta la zona de cobertura de la
    ruta seleccionada junto con ellos (`ajustarVista()` encuadra la union de ambos).
    """

    coordenadas_cambiadas = Signal(float, float)
    vertice_zona_agregado = Signal(float, float)

    def __init__(
        self,
        editable: bool = True,
        centrar_en_dispositivo: bool = False,
        modo: str = "punto",
        parent=None,
    ):
        super().__init__(parent)
        self.editable = editable
        self.modo = modo
        self._cargado = False
        self._pendientes: list[str] = []
        self._worker_ubicacion = None
        self._worker_busqueda = None
        self._worker_ubicacion_precisa = None

        # Debounce de 450ms para las sugerencias en vivo mientras el usuario escribe (ver
        # _on_texto_busqueda_cambiado): sin esto cada tecla dispararia una llamada a
        # Nominatim, muy por encima de su politica de uso (~1 req/seg) y sin necesidad --
        # pedido del usuario, 2026-09-01, "que a medida que el usuario vaya escribiendo
        # vaya mostrando sugerencias".
        self._debounce_busqueda = QTimer(self)
        self._debounce_busqueda.setSingleShot(True)
        self._debounce_busqueda.setInterval(450)
        self._debounce_busqueda.timeout.connect(self._buscar_lugar_automatico)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        if editable:
            # stretch=0 a proposito: esta barra debe quedar lo mas chica posible (una
            # sola fila angosta) para que el mapa (stretch=1, mas abajo) se quede con
            # todo el espacio vertical sobrante -- reportado por el usuario, 2026-09-01,
            # "la barra de busqueda... dificulta la visualizacion del mapa".
            layout.addWidget(self._make_barra_busqueda(), 0)

        # Contenedor de estado en el mismo lugar que el mapa (visibility-toggle, NO
        # QStackedWidget -- ver la nota de estilo del proyecto sobre el borde fantasma de
        # un QStackedWidget anidado): mientras el mapa esta oculto (recien construido, o
        # si termino de cargar en False / el proceso de Chromium murio) se ve este texto
        # en vez de un rectangulo en blanco sin ninguna explicacion -- reportado por el
        # usuario, 2026-09-01, "el mapa no carga" sin mas pista que esa. El boton
        # "Reintentar" (oculto salvo en error) evita tener que cerrar y reabrir todo el
        # dialogo ante una carga que falla de forma transitoria -- tambien reportado por
        # el usuario el mismo dia, en un caso distinto al del border-radius/sombra.
        self.status_container = QWidget()
        status_layout = QVBoxLayout(self.status_container)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)
        status_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.status_label = QLabel("Cargando mapa…")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(
            "color: #64748B; font-size: 12px; background-color: #F1F5F9; border-radius: 6px; padding: 12px;"
        )
        status_layout.addWidget(self.status_label)

        self.btn_reintentar = QPushButton("Reintentar")
        self.btn_reintentar.setFixedWidth(120)
        self.btn_reintentar.setVisible(False)
        self.btn_reintentar.clicked.connect(self._reintentar_carga)
        status_layout.addWidget(self.btn_reintentar, 0, Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.status_container, 1)

        self.view = QWebEngineView()
        self.view.setVisible(False)
        # QWebEngineView pinta via una ventana nativa del SO (no un QWidget pintado por
        # Qt) -- un ancestro con `border-radius` por stylesheet (ej. la tarjeta
        # "SectionCard" de ClienteFormDialog/RutaFormDialog) puede hacer que esa ventana
        # nativa no se componga nunca sobre pantalla en Windows (bug conocido de Qt/
        # Chromium, no exclusivo de este proyecto). Este atributo evita que Qt fuerce a
        # los ancestros a volverse ventanas nativas tambien, que es lo que dispara el
        # problema -- confirmado en 2026-09-01: loadFinished(ok=True) en el log pero el
        # mapa seguia sin pintarse en pantalla.
        self.view.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        pagina = _MapaPage(self._on_click_js, self.view)
        pagina.renderProcessTerminated.connect(self._on_render_process_terminated)
        self.view.setPage(pagina)
        self.view.loadFinished.connect(self._on_load_finished)
        layout.addWidget(self.view, 1)

        # Diferido a 0ms: crear la pagina de Chromium (setHtml) es lo unico lento de
        # este widget -- con esto el dialogo que lo contiene queda visible de inmediato
        # (el area del mapa aparece en blanco un instante) en vez de bloquear su apertura
        # completa. set_coordenadas()/centrar() llamados antes de que termine ya se
        # encolan solos via _ejecutar(), asi que el orden es seguro de cualquier forma.
        QTimer.singleShot(0, self._cargar_pagina)

        if editable and centrar_en_dispositivo:
            self._centrar_en_dispositivo()

    def _cargar_pagina(self) -> None:
        html = _HTML_BASE.format(
            centro_lat=_CENTRO_DEFAULT_LAT,
            centro_lng=_CENTRO_DEFAULT_LNG,
            zoom=_ZOOM_DEFAULT,
            zoom_marcador=_ZOOM_MARCADOR,
            editable="true" if self.editable else "false",
        )
        self.view.setHtml(html, _LEAFLET_BASE_URL)

    def _make_barra_busqueda(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)

        fila = QHBoxLayout()
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(6)

        # 32px, misma altura que el resto de los inputs del formulario (codigo_input,
        # latitud_input, etc.) -- 28px quedaba mas bajo de lo que el padding/borde del
        # QSS global necesita para el texto, y se veia "cortado" (reportado por el
        # usuario, 2026-09-01). Ancho del boton NO fijo (min-width en vez de
        # setFixedWidth): un ancho fijo mas chico que "Buscar" + el padding del QSS
        # tambien recortaba el texto del boton.
        self.busqueda_input = QLineEdit()
        self.busqueda_input.setPlaceholderText("Buscar lugar…")
        self.busqueda_input.setFixedHeight(32)
        self.busqueda_input.returnPressed.connect(self._buscar_lugar)
        self.busqueda_input.textChanged.connect(self._on_texto_busqueda_cambiado)

        self.btn_buscar = QPushButton("Buscar")
        self.btn_buscar.setFixedHeight(32)
        self.btn_buscar.setMinimumWidth(64)
        self.btn_buscar.clicked.connect(self._buscar_lugar)

        # Con texto (no solo el emoji) e icono en el propio texto -- un boton de solo 36px
        # con un emoji chiquito se leia como decoracion, no como accion (reportado por el
        # usuario, 2026-09-01, "debe ser mas intuitivo"). min-width en vez de fixed, mismo
        # criterio que "Buscar": un ancho fijo recortaba el texto.
        self.btn_ubicacion_precisa = QPushButton("📍 Mi ubicación")
        self.btn_ubicacion_precisa.setFixedHeight(32)
        self.btn_ubicacion_precisa.setMinimumWidth(120)
        self.btn_ubicacion_precisa.setToolTip("Usar mi ubicación actual (GPS/WiFi del dispositivo)")
        self.btn_ubicacion_precisa.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ubicacion_precisa.clicked.connect(self._usar_ubicacion_precisa)

        fila.addWidget(self.busqueda_input, 1)
        fila.addWidget(self.btn_buscar)
        v.addLayout(fila)
        v.addWidget(self.btn_ubicacion_precisa)

        # QCompleter en vez de un QComboBox mostrado a mano (`showPopup()`): un combobox
        # emergente le roba el foco a busqueda_input apenas se abre (QComboBox.showPopup
        # hace foco en su propia vista internamente) -- el usuario reportaba que el foco
        # se le salia de la barra con cada letra que escribia (2026-09-01). QCompleter esta
        # pensado exactamente para este patron (sugerencias mientras se escribe en un
        # QLineEdit que nunca pierde el foco); UnfilteredPopupCompletion porque los
        # resultados ya vienen filtrados por Nominatim -- que Qt los vuelva a filtrar por
        # substring localmente podria ocultar resultados validos.
        self._resultados_busqueda: list[dict] = []
        self.completer = QCompleter(self)
        self.completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.activated[str].connect(self._on_sugerencia_seleccionada)
        self.busqueda_input.setCompleter(self.completer)

        # Feedback transitorio (errores de geolocalizacion precisa) -- oculto salvo
        # cuando hay algo que mostrar, se auto-oculta solo (ver _mostrar_estado_temporal).
        self.lbl_estado = QLabel()
        self.lbl_estado.setWordWrap(True)
        self.lbl_estado.setStyleSheet("color: #B45309; font-size: 11px;")
        self.lbl_estado.setVisible(False)
        v.addWidget(self.lbl_estado)

        return w

    def _buscar_lugar(self) -> None:
        """Busqueda explicita (boton "Buscar" o Enter): aplica el primer resultado de
        inmediato ademas de listar el resto -- el usuario ya expreso intencion de buscar
        justo eso, a diferencia de las sugerencias en vivo mientras escribe."""
        texto = self.busqueda_input.text().strip()
        if not texto:
            return
        self._debounce_busqueda.stop()
        self._ejecutar_busqueda(texto, aplicar_primero=True)

    def _on_texto_busqueda_cambiado(self, texto: str) -> None:
        self._debounce_busqueda.stop()
        if len(texto.strip()) < 3:
            return
        self._debounce_busqueda.start()

    def _buscar_lugar_automatico(self) -> None:
        """Disparado por el debounce mientras el usuario escribe: solo muestra
        sugerencias, no mueve el marcador -- eso se decide al seleccionar una (ver
        _on_sugerencia_seleccionada), para no saltar el mapa en cada tecla."""
        texto = self.busqueda_input.text().strip()
        if len(texto) < 3:
            return
        self._ejecutar_busqueda(texto, aplicar_primero=False)

    def _ejecutar_busqueda(self, texto: str, aplicar_primero: bool) -> None:
        self.btn_buscar.setEnabled(False)
        self._worker_busqueda = HttpWorker(functools.partial(buscar_lugares, texto))
        self._worker_busqueda.resultado.connect(
            functools.partial(self._on_resultados_busqueda, aplicar_primero=aplicar_primero)
        )
        self._worker_busqueda.start()

    def _on_resultados_busqueda(self, resultados: list[dict], aplicar_primero: bool) -> None:
        self.btn_buscar.setEnabled(True)
        self._resultados_busqueda = resultados
        self.completer.setModel(QStringListModel([r["nombre"] for r in resultados], self.completer))
        if not resultados:
            return

        if aplicar_primero:
            lat, lng = resultados[0]["lat"], resultados[0]["lng"]
            self._aplicar_punto(lat, lng)
        else:
            # Reabre el popup con el modelo recien actualizado -- busqueda_input nunca
            # pierde el foco (ver nota de QCompleter arriba), el usuario puede seguir
            # escribiendo para refinar sin interrupcion.
            self.completer.complete()

    def _on_sugerencia_seleccionada(self, texto: str) -> None:
        for r in self._resultados_busqueda:
            if r["nombre"] == texto:
                self._aplicar_punto(r["lat"], r["lng"])
                return

    def _aplicar_punto(self, lat: float, lng: float) -> None:
        """Punto de entrada comun para busqueda (aplicar_primero) y seleccion de
        sugerencia: en modo "punto" dibuja el marcador unico y emite
        `coordenadas_cambiadas` (igual que siempre); en modo "zona" solo re-centra el
        mapa ahi -- con varios vertices en juego no hay "el punto activo" al que
        aplicarle un resultado de busqueda, a diferencia de un click (que si acumula un
        vertice, ver _on_click_js)."""
        if self.modo == "zona":
            self.centrar(lat, lng, zoom=_ZOOM_MARCADOR)
        else:
            self.set_coordenadas(lat, lng)
            self.coordenadas_cambiadas.emit(lat, lng)

    def _centrar_en_dispositivo(self) -> None:
        self._worker_ubicacion = HttpWorker(obtener_ubicacion_dispositivo)
        self._worker_ubicacion.resultado.connect(self._on_ubicacion_dispositivo)
        self._worker_ubicacion.start()

    def _on_ubicacion_dispositivo(self, resultado) -> None:
        if resultado is None:
            return
        lat, lng = resultado
        if not _dentro_de_venezuela(lat, lng):
            # Se mantiene el centro Venezuela por defecto del HTML base en vez de saltar
            # a donde haya resuelto la IP -- ver _VE_LAT_MIN/etc. arriba.
            return
        self.centrar(lat, lng, zoom=12)

    def _usar_ubicacion_precisa(self) -> None:
        self.btn_ubicacion_precisa.setEnabled(False)
        self.lbl_estado.setVisible(False)
        # Geolocator nativo de Windows (app/ui/geo_windows.py), no navigator.geolocation
        # de Chromium -- ver docstring del modulo y de geo_windows.py para el porque.
        self._worker_ubicacion_precisa = HttpWorker(obtener_ubicacion_precisa_windows)
        self._worker_ubicacion_precisa.resultado.connect(self._on_ubicacion_precisa)
        self._worker_ubicacion_precisa.start()

    def _on_ubicacion_precisa(self, resultado: dict) -> None:
        self.btn_ubicacion_precisa.setEnabled(True)
        error = resultado.get("error")
        if error:
            logger.info("MapaWidget: geolocalización precisa falló (%s)", error)
            textos_error = {
                "denied": "Ubicación denegada. Habilítala en Configuración de Windows > Privacidad > Ubicación.",
                "timeout": "No se pudo obtener tu ubicación a tiempo. Intenta de nuevo.",
                "unavailable": "No se pudo obtener tu ubicación precisa.",
            }
            self._mostrar_estado_temporal(textos_error.get(error, textos_error["unavailable"]), color="#B45309")
            return

        lat, lng, precision_m = resultado["lat"], resultado["lng"], resultado["accuracy"]
        # setEnabled(True) ya ocurrio arriba; _on_click_js es el mismo camino que un click
        # real en el mapa (dibuja el marcador o agrega un vertice de zona segun el modo,
        # ver su docstring) -- asi el resultado de "Mi ubicacion" se comporta igual que si
        # el usuario hubiera clickeado ahi mismo.
        self._on_click_js(lat, lng)
        self._mostrar_estado_temporal(f"Ubicación fijada (precisión: ±{precision_m:,.0f} m).", color="#15803D")

    def _mostrar_estado_temporal(self, texto: str, color: str = "#B45309") -> None:
        self.lbl_estado.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.lbl_estado.setText(texto)
        self.lbl_estado.setVisible(True)
        QTimer.singleShot(6000, lambda: self.lbl_estado.setVisible(False))

    def _on_load_finished(self, ok: bool) -> None:
        logger.info("MapaWidget: carga de pagina %s", "OK" if ok else "FALLO")
        self._cargado = ok
        self.view.setVisible(ok)
        self.status_container.setVisible(not ok)
        if not ok:
            self.status_label.setText("No se pudo cargar el mapa. Verifica la conexión a internet e intenta de nuevo.")
            self.btn_reintentar.setVisible(True)
            return
        if self._pendientes:
            pendientes, self._pendientes = self._pendientes, []
            for js in pendientes:
                self.view.page().runJavaScript(js)

    def _on_render_process_terminated(self, status, exit_code: int) -> None:
        # Si el subproceso QtWebEngineProcess.exe muere (crash, bloqueado por antivirus,
        # falla de GPU irrecuperable) loadFinished() puede no llegar a dispararse nunca --
        # esta señal es la unica forma de enterarse de que el mapa quedo colgado.
        logger.error("MapaWidget: el proceso de renderizado terminó (status=%s, exit_code=%s)", status, exit_code)
        self._cargado = False
        self.view.setVisible(False)
        self.status_label.setText("El mapa dejó de responder.")
        self.status_container.setVisible(True)
        self.btn_reintentar.setVisible(True)

    def _reintentar_carga(self) -> None:
        self.status_label.setText("Cargando mapa…")
        self.btn_reintentar.setVisible(False)
        self._cargar_pagina()

    def _ejecutar(self, js: str) -> None:
        # La pagina carga de forma asincronica (setHtml -> loadFinished): si algun
        # llamador actua antes de que termine, se encola y se corre en orden al terminar.
        # Encolar TODAS (no solo la ultima) importa desde que empezaron a existir
        # secuencias de varias llamadas seguidas para una sola accion -- ej.
        # MapaRutasPanel dibuja marcadores y despues el trazado de la ruta,
        # RutaFormDialog._precargar fija origen, destino y trazado en tres llamadas
        # separadas. Con un solo slot (el diseño original, cuando cada accion
        # correspondia a una unica llamada) la ultima pisaba en silencio a las
        # anteriores: el mapa terminaba cargando sin marcadores y con el zoom sin
        # ajustar -- reportado por el usuario, 2026-09-01 ("el mapa abre con el mundo
        # entero, sin zoom").
        if self._cargado:
            self.view.page().runJavaScript(js)
        else:
            self._pendientes.append(js)

    def _on_click_js(self, lat: float, lng: float) -> None:
        # Tambien llamado directamente (no solo desde un click real en el mapa) por
        # _on_ubicacion_precisa() al resolver la geolocalizacion nativa -- mismo efecto
        # que si el usuario hubiera clickeado ahi mismo.
        if self.modo == "zona":
            # A diferencia de _aplicar_punto() (busqueda), el click NO dibuja el vertice
            # aca -- mismo criterio que el modo "punto": es el formulario (RutaFormDialog)
            # quien mantiene la lista de vertices y llama establecer_zona() al recibir
            # esta señal.
            self.vertice_zona_agregado.emit(lat, lng)
        else:
            self.coordenadas_cambiadas.emit(lat, lng)

    def set_coordenadas(self, lat: float, lng: float) -> None:
        self._ejecutar(f"establecerMarcadorUnico({lat}, {lng});")

    def limpiar_zona(self) -> None:
        self._ejecutar("limpiarZona();")

    def establecer_zona(self, vertices: list[tuple[float, float]]) -> None:
        """Reemplaza el poligono de zona completo -- unico punto de entrada para
        dibujarla (RutaFormDialog llama esto en cada click, no solo al precargar una
        ruta existente: los vertices se reordenan por angulo antes de cada redibujado
        para que el poligono nunca quede auto-intersectado, ver
        ruta_form_dialog.py::_ordenar_por_angulo -- asi que la lista completa cambia en
        cada paso, no solo el ultimo punto). Tambien usado por MapaRutasPanel (mapa
        general, modo solo-lectura)."""
        self._ejecutar(f"establecerZona({json.dumps(vertices)});")

    def centrar(self, lat: float, lng: float, zoom: int = _ZOOM_DEFAULT) -> None:
        """Centra/hace zoom sin tocar marcadores -- para el centrado por ubicacion del
        dispositivo, que nunca debe fijar una coordenada por si solo."""
        self._ejecutar(f"centrarSinMarcador({lat}, {lng}, {zoom});")

    def mostrar_puntos(self, clientes: list[tuple[float, float, str]]) -> None:
        """Modo solo-lectura (mapa general de rutas): pinta muchos clientes de una vez."""
        partes = ["limpiarMarcadores();"]
        for lat, lng, etiqueta in clientes:
            partes.append(f"agregarMarcadorCliente({lat}, {lng}, {json.dumps(etiqueta)});")
        partes.append("ajustarVista();")
        self._ejecutar(" ".join(partes))
