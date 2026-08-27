# Guía de estilo UI

Estándar visual y de patrones de código para `app/ui/`. Objetivo: que cualquier
pantalla/diálogo nuevo se vea y se comporte como si lo hubiera hecho la misma persona
que hizo el resto de la app, sin tener que redescubrir estas decisiones cada vez.

**Fuente de verdad de colores y QSS globales**: `app/ui/styles.py`. Todo lo de esta
guía que sea un color o una hoja de estilo compartida vive ahí — si un valor que citás
acá y el archivo no coinciden, gana el archivo (esta guía puede quedar desactualizada,
`styles.py` no).

---

## 1. Paleta de colores

| Constante | Hex | Uso |
|---|---|---|
| `COLOR_PRIMARY` | `#0D47A1` | Azul corporativo — botones primarios, acentos, íconos activos, sidebar |
| `COLOR_PRIMARY_DARK` | `#0A3A83` | Estado `:pressed` de elementos primarios |
| `COLOR_PRIMARY_LIGHT` | `#1565C0` | Estado `:hover` de elementos primarios |
| `COLOR_CONTENT_BG` | `#F8FAFC` | Fondo de página/diálogo (el gris casi blanco de toda la app) |
| `COLOR_CARD_BG` | `#FFFFFF` | Fondo de tarjetas, tablas, inputs |
| `COLOR_BORDER` | `#CBD5E1` | Borde estándar de tarjetas/tablas/inputs |
| `COLOR_FIELD_BG` | `#F1F5F9` | Fondo de "chips" de campo individuales dentro de una tarjeta |
| `COLOR_TABLE_HEADER` | `#E2E8F0` | Fondo de encabezado de tabla / hover de botón secundario |
| `COLOR_TABLE_ALT_ROW` | `#F8FAFC` | Fila alterna de tabla |
| `COLOR_TABLE_SELECTED` | `#E2E8F0` | Fila/ítem seleccionado (gris neutro — antes `#DBEAFE` azul, se notaba ajeno a la paleta gris/blanco intercalada del resto de la tabla, 2026-08-27) |
| `COLOR_TABLE_HOVER` | `#EFF6FF` | Hover de fila de tabla |
| `COLOR_TEXT_DARK` | `#1E293B` | Texto principal |
| `COLOR_TEXT_MUTED` | `#64748B` | Texto secundario/subtítulos/placeholders |
| `COLOR_TEXT_LIGHT` | `#94A3B8` | Texto deshabilitado / iconografía muy sutil |
| `COLOR_SUCCESS` | `#16A34A` | Éxito, positivo, Excel |
| `COLOR_WARNING` | `#D97706` | Advertencia, estado intermedio |
| `COLOR_DANGER` | `#DC2626` | Error, eliminar, PDF, negativo |
| `COLOR_INFO` | `#0284C7` | Informativo neutro (ni éxito ni error) |

Nunca hardcodees un hex nuevo para uno de estos significados — importá la constante de
`app/ui/styles.py`. Si hace falta una variante translúcida (fondo de badge/ícono), usá
`color_con_alpha(color_hex, alpha=26)` — Qt QSS no soporta `#RRGGBBAA`, solo
`rgba(...)` o `#AARRGGBB`, y `color_con_alpha` ya resuelve eso.

## 2. Tipografía y dimensiones

- Fuente: `FONT_FAMILY = "Segoe UI"` (fallback `Arial, sans-serif`), fijada una vez en
  `GLOBAL_QSS` (aplicado en `MainWindow`) y repetida en el `DIALOG_STYLE` de cada
  diálogo (los diálogos son ventanas top-level, no heredan el QSS de `MainWindow`).
- Tamaños de fuente típicos: `22px`/`17px`/`15px` bold para títulos de panel/diálogo/
  tarjeta, `13px` para texto de body y controles, `12px` para labels de formulario y
  subtítulos, `11px` para badges y encabezados de tabla (mayúsculas,
  `letter-spacing: 0.5px`).
- Alturas de control estándar: `32px` (inputs de diálogo densos), `34px`–`36px`
  (botones). Elegí una y usala consistente dentro de la misma pantalla.
- Márgenes de layout raíz: `(24, 20, 24, 20)` en paneles de módulo completo (los que
  cuelgan directo de `MainWindow`, ej. `facturacion_panel.py`), `(20, 16, 20, 16)` en
  diálogos modales.
- Padding de tarjeta (`SectionCard`/`Card`): `(16, 14, 16, 14)`.
- `SIDEBAR_WIDTH = 230` (58 colapsado), `TOPBAR_HEIGHT = 60`.

## 3. Botones

Cuatro variantes con nombre fijo, todas en `app/ui/styles.py` como constantes QSS
listas para `widget.setStyleSheet(...)` **directo sobre el botón** (no en un
ancestro — ver gotcha en la sección 8):

| Constante | Aspecto | Uso |
|---|---|---|
| `BUTTON_PRIMARY_QSS` | Fondo `COLOR_PRIMARY`, texto blanco | Acción principal de la pantalla ("Nueva Factura", "Guardar") |
| `BUTTON_SECONDARY_QSS` | Fondo blanco, borde `COLOR_BORDER`, texto oscuro | Acciones secundarias ("Cancelar", "Exportar", "Ver detalle") |
| `BUTTON_DANGER_QSS` | Fondo `COLOR_DANGER`, texto blanco | Acciones destructivas explícitas (poco usada — la mayoría de "eliminar" en esta app son cambios de estado, no deletes reales) |
| `BotonFiltros`/`BotonExportar` | Botón secundario + popup desplegable | Filtros y exportación de un listado (ver 3.2/3.3) — `app/ui/toolbar_popups.py` |

Dentro de diálogos con `DIALOG_STYLE` local (ver sección 7) las mismas dos primeras
variantes existen como selectores por `objectName`: `#BtnPrimary` / `#BtnSecondary`
(más `#BtnAgregar` / `#BtnQuitar` para filas de carrito/lista editable — fondo/texto
azul o rojo muy claro, ver `factura_form_dialog.py`).

**Texto del botón: Sentence case, nunca `MAYÚSCULAS` a mano** (`"Editar seleccionado"`,
no `"EDITAR SELECCIONADO"`) — la app no transforma el texto por QSS, lo que se tipea en
el `QPushButton(...)` es lo que se ve. Bug real encontrado (`clientes_panel.py`,
2026-08-27): tres botones del footer quedaron en mayúsculas fijas, inconsistentes con
el resto de la app (`facturacion_panel.py`/`vendedores_panel.py`/`usuarios_panel.py`,
todos en sentence case).

Checklist para **cualquier** botón nuevo:

```python
btn = QPushButton("Texto")
btn.setIcon(qta.icon("fa5s.icono", color=COLOR_QUE_CORRESPONDA))
btn.setObjectName("BtnPrimary")  # o setStyleSheet(BUTTON_SECONDARY_QSS), etc.
btn.setFixedHeight(34)  # o 36 -- consistente con el resto de la pantalla
btn.setCursor(Qt.CursorShape.PointingHandCursor)
btn.setAutoDefault(False)  # SIEMPRE en diálogos con más de un botón -- ver sección 8
btn.clicked.connect(self.accion)
```

`setAutoDefault(False)` no es cosmético: sin él, Qt puede promover el botón a "default"
del diálogo y el renderizado del `background-color` con estilo por `objectName` se
vuelve poco confiable en Windows (ver el gotcha de la sección 8, causa real de un bug
visual encontrado en producción).

### 3.1 Íconos — convención de color

Todos los íconos son [qtawesome](https://github.com/spyder-ide/qtawesome), familia
`fa5s.*` (Font Awesome 5 Solid), tamaño típico `18–22px`. El color del ícono **no** es
libre — sigue el significado semántico de la paleta:

- `COLOR_PRIMARY` (azul): acción neutra/principal — cerrar, ver, agregar, confirmar.
- `COLOR_SUCCESS` (verde): Excel, guardar/aprobar, positivo.
- `COLOR_DANGER` (rojo): PDF, eliminar/anular, negativo.
- `COLOR_TEXT_DARK` / `#475569`: acción secundaria genérica sin carga semántica
  (ej. "Exportar" genérico, "Ver detalle").
- Blanco (`#FFFFFF`): ícono sobre un botón de fondo sólido (`BtnPrimary`,
  `BUTTON_DANGER_QSS`).

### 3.2 Botones de exportación — `BotonExportar`

Cualquier pantalla que exporte un listado usa un único botón "Exportar" (no dos
botones lado a lado) que despliega un popup para elegir Excel o PDF — `BotonExportar`
en `app/ui/toolbar_popups.py`:

```python
from app.ui.toolbar_popups import BotonExportar

self.btn_exportar = BotonExportar(on_excel=self.exportar_excel_x, on_pdf=self.exportar_pdf_x)
h.addWidget(self.btn_exportar)
```

`on_excel`/`on_pdf` son callbacks sin argumentos (los métodos ya existentes que arman
las filas y llaman a `exportar_excel`/`exportar_pdf`). Patrón interno recomendado —
un helper `_filas_para_exportar(session)` compartido, para no duplicar la consulta:

```python
def _filas_para_exportar(self, session) -> list[list]:
    items = MiServicio.listar(session, ...)
    return [[...] for item in items]


def exportar_excel_x(self) -> None:
    ruta, _ = QFileDialog.getSaveFileName(self, "Exportar X", "x.xlsx", "Excel (*.xlsx)")
    if not ruta:
        return
    session = self.session_factory()
    try:
        exportar_excel(ruta, COLS_VISIBLES, self._filas_para_exportar(session))
    finally:
        session.close()
```

Backend: `app.services.exportacion.exportar_excel(ruta, encabezados, filas)` y
`exportar_pdf(ruta, titulo, encabezados, filas, cliente_nombre=None)` — genéricos,
reusables con cualquier cantidad de columnas (el ancho de columna del PDF se calcula
dinámicamente). La ruta de destino siempre se pide **antes** de generar el archivo
(`QFileDialog.getSaveFileName`), nunca se escribe a un temporal.

Excepción: un botón que exporta un solo registro puntual a un único formato (ej. PDF de
una factura individual en `factura_detalle_dialog.py`) no necesita el popup — ahí sigue
siendo un botón secundario simple ("Exportar PDF"), porque no hay nada entre qué elegir.

### 3.3 Filtros — `BotonFiltros`

Ningún filtro va como dropdown suelto directo en la barra de herramientas, ni siquiera
uno solo — todos (uno o varios: `QComboBox`, `QCheckBox`) se agrupan detrás de un único
botón "Filtrar" que los despliega en un popup, con contador de filtros activos en el
propio texto del botón ("Filtrar (2)") — `BotonFiltros` en `app/ui/toolbar_popups.py`:

```python
from app.ui.toolbar_popups import BotonFiltros

self.estado_combo = QComboBox()
for etiqueta, valor in ESTADOS_FILTRO:  # la primera opcion ("Todos...") es el default
    self.estado_combo.addItem(etiqueta, valor)
self.estado_combo.currentIndexChanged.connect(self._buscar_desde_inicio)

self.btn_filtrar = BotonFiltros([("Estado", self.estado_combo), ("", self.solo_x_check)])
h.addWidget(self.btn_filtrar)
```

Los widgets de filtro se crean y conectan exactamente igual que si fueran a la barra
directo (mismo `currentIndexChanged`/`toggled` contra el método de recarga de siempre)
-- `BotonFiltros` no cambia esa lógica, solo los sabe agrupar. La etiqueta de un
`QCheckBox` se deja vacía (`""`) porque el propio checkbox ya trae su texto. Incluye un
link "Limpiar filtros" que resetea todos los controles a su valor por defecto (índice 0
/ sin marcar). Ver `facturacion_panel.py` (3 filtros), `inventario_panel.py` (categoría
+ checkbox) o `clientes_panel.py` (1 filtro) como referencia.

### 3.4 Orden de los botones en la barra de herramientas

Fijo, sin excepciones — búsqueda a la izquierda sola, el resto agrupado a la derecha en
este orden exacto:

```
[Buscar…]  ────────(stretch)────────  [Nuevo X]  [Filtrar]  [Exportar]
```

`Filtrar`/`Exportar` van **pegados al grupo de la derecha junto a "Nuevo X"**, nunca al
lado del cuadro de búsqueda — es un error común ponerlos ahí "porque son filtros de la
búsqueda", pero visualmente rompe la agrupación búsqueda-vs-acciones. Si el panel no
tiene botón de creación (p. ej. una vista de solo lectura), el grupo de la derecha
simplemente empieza en `Filtrar`.

## 4. Tarjetas (`SectionCard` / `Card`)

Dos nombres para el mismo patrón visual (blanco, borde `COLOR_BORDER`, radio `10px`,
sombra sutil), según contexto:

- **`#SectionCard`**: definido dentro del `DIALOG_STYLE` local de cada diálogo (ver
  sección 7) — agrupa un bloque de campos de formulario.
- **`#Card`** (`CARD_QSS` en `styles.py`): tarjetas sueltas en paneles (KPIs del
  dashboard, resúmenes).

```python
card = QWidget()
card.setObjectName("SectionCard")  # o "Card" + widget.setStyleSheet(CARD_QSS)
aplicar_sombra(card)  # obligatorio -- ver mas abajo
layout = QVBoxLayout(card)
layout.setContentsMargins(16, 14, 16, 14)
layout.setSpacing(8)
```

`aplicar_sombra(widget, blur=18, y_offset=3, alpha=35)` (en `styles.py`) aplica un
`QGraphicsDropShadowEffect` — es la única forma de tener sombra en Qt (QSS no soporta
`box-shadow` sobre widgets normales). Se usa en toda tarjeta y en toda `QTableWidget`.

## 5. Tablas

`TABLE_QSS` (en `styles.py`) es el único estilo de tabla de la app. Setup estándar,
copiado tal cual en todos los paneles con listado:

```python
self.tabla = QTableWidget(0, len(COLUMNAS))
self.tabla.setHorizontalHeaderLabels(COLUMNAS)
self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
self.tabla.setAlternatingRowColors(True)
self.tabla.setShowGrid(False)
self.tabla.verticalHeader().setVisible(False)
self.tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
self.tabla.setStyleSheet(TABLE_QSS)
aplicar_sombra(self.tabla)
self.tabla.verticalHeader().setDefaultSectionSize(45)  # 48 en listados mas densos
```

Columnas que deben ajustarse al contenido (IDs, montos, badges de estado) usan
`setSectionResizeMode(indice, QHeaderView.ResizeMode.ResizeToContents)` +
`setColumnWidth` puntual en vez de `Stretch`.

**`self.tabla.setStyleSheet(TABLE_QSS)` solo — nunca `TABLE_QSS + "..."` con reglas
propias encima.** Bug real encontrado (`clientes_panel.py`, 2026-08-27): un panel tenía
QSS local agregado sobre `TABLE_QSS` con su propio color de fila no-alterna y su propio
`item:selected`, una versión vieja que quedó divergiendo en silencio del resto de la
app — las filas sin seleccionar se veían con un tinte azul en vez de blanco/gris, y el
color de selección no reflejaba cambios futuros a `COLOR_TABLE_SELECTED`. Si una tabla
necesita algo que `TABLE_QSS` no cubre, el ajuste va **en `TABLE_QSS` mismo**
(`app/ui/styles.py`), no duplicado y parcheado en el panel.

## 6. Formularios (inputs)

Todo diálogo con campos define, dentro de su `DIALOG_STYLE` local, estas reglas
(copiadas literal entre diálogos — no hay una constante compartida porque cada diálogo
la declara junto al resto de su QSS, ver sección 7):

```css
QLabel.FormLabel {
    font-size: 12px;
    font-weight: 600;
    color: #334155;
    margin-bottom: 2px;
}
QLineEdit, QComboBox, QDoubleSpinBox, QDateEdit {
    background-color: #FFFFFF;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
    min-height: 20px;
}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QDateEdit:focus {
    border: 1.5px solid {COLOR_PRIMARY};
}
```

Label de campo obligatorio: `QLabel("Campo <span style='color: #DC2626;'>*</span>")`
con `lbl.setProperty("class", "FormLabel")`. Fuera de diálogos (paneles con barra de
búsqueda), el input usa `SEARCH_QSS` en vez de lo de arriba.

**Combos dentro de un formulario con scroll (pestañas largas, `QScrollArea`) usan
`ComboBoxSinScroll` (`app/ui/styles.py`) en vez de `QComboBox` a secas.** Por defecto
Qt cambia el valor seleccionado con solo pasar el mouse por encima y girar la rueda
mientras se hace scroll de la pantalla que lo contiene — sin foco previo, sin haber
hecho click. `ComboBoxSinScroll` ignora la rueda salvo que el combo ya tenga foco (un
click previo), y el evento se propaga normal al padre para que el scroll de la pantalla
siga funcionando. Reportado por el usuario en el combo de método de vuelto de
`factura_form_dialog.py` (2026-08-27), aplicado ahí y en los combos de
`aplicar_nota_credito_dialog.py`/`devolver_nota_credito_dialog.py`/
`usuario_form_dialog.py`. Es un default de Qt en **todo** `QComboBox`, no solo esos —
usar `ComboBoxSinScroll` para cualquier combo nuevo dentro de un formulario largo, no
solo cuando alguien lo reporte.

**`QTabWidget` (pestañas dentro de un diálogo o un panel) usa `TABS_QSS`
(`app/ui/styles.py`)**, nunca el tema nativo de Windows (una caja gris sólida en la
pestaña activa, no se nota que son clickeables). `self.tabs.setStyleSheet(TABS_QSS)` —
subrayado de `2px` en `COLOR_PRIMARY` bajo la pestaña activa, sin relleno. Antes vivía
solo, local, dentro del `DIALOG_STYLE` de `factura_form_dialog.py`; se promovió a
`styles.py` cuando `usuarios_panel.py` necesitó el mismo `QTabWidget` fuera de un
diálogo (2026-08-27) — mismo criterio que `TABLE_QSS`/`EstadoBadge`: un patrón que se
repite en un segundo lugar se centraliza, no se copia.

## 7. Patrón de diálogo estándar

Todo diálogo modal (`QDialog`) nuevo sigue esta estructura, sin excepciones:

1. **`DIALOG_STYLE` local** (constante en el propio archivo, no importada de
   `styles.py`): `QDialog` con `background-color: COLOR_CONTENT_BG`, más
   `#SectionCard`, inputs (sección 6), `#BtnPrimary`/`#BtnSecondary` (sección 3). Cada
   diálogo repite este bloque porque son ventanas top-level independientes — no
   heredan el stylesheet de `MainWindow`. Ver `caja_apertura_dialog.py` o
   `pago_linea_dialog.py` como plantilla mínima, `factura_form_dialog.py` como la más
   completa (agrega `TABS_QSS`, ver más abajo).
2. **Encabezado**: ícono en badge (`34–38px`, fondo `#EFF6FF`, borde `1.5px solid
   #BFDBFE`, radio `8px`) + columna de título (`17px` bold) y subtítulo (`12px`,
   `COLOR_TEXT_MUTED`).

   ```python
   icon_lbl = QLabel()
   icon_lbl.setPixmap(qta.icon("fa5s.algo", color=COLOR_PRIMARY).pixmap(QSize(22, 22)))
   icon_lbl.setStyleSheet("background-color: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 8px; padding: 6px;")
   icon_lbl.setFixedSize(38, 38)
   icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
   ```
3. **Footer**: `QHBoxLayout` (¡no `QWidget`! — ver gotcha en sección 8) con
   `addStretch()` primero, después botón(es) secundario(s)/cancelar y por último el
   primario, en ese orden de izquierda a derecha.
4. **`setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)`**
   — saca el botón "?" de la barra de título en Windows.
5. **`showEvent` con repintado diferido** (ver 8.1) si el diálogo tiene tarjetas con
   sombra (casi todos).

## 8. Gotchas conocidos (código real, no teoría)

### 8.1 Artefacto de primer pintado (Windows/DWM)

Diálogos densos (varias tarjetas con `QGraphicsDropShadowEffect` + tabla) pueden
mostrar texto/bordes con apariencia "cortada" o traslúcida en el primer pintado, antes
de que DWM termine de componer. Se autocorrige con cualquier repintado (mover/
redimensionar), así que se fuerza uno apenas se muestra el diálogo:

```python
def showEvent(self, event: QShowEvent) -> None:
    super().showEvent(event)
    QTimer.singleShot(0, self.update)
```

Aplicado hoy en `factura_form_dialog.py` y `historial_cliente_window.py`.

### 8.2 Un botón con `objectName` puede quedar sin fondo — evitar el wrapper

**Bug real encontrado y corregido** (`historial_cliente_window.py`, agosto 2026): un
`QPushButton` con `#BtnPrimary` (fondo por `background-color` vía selector de
`objectName`, cascada desde el `DIALOG_STYLE` del diálogo) puede renderizarse **sin su
`background-color`** en Windows — el borde y el texto sí se pintan, el fondo no —
cuando el botón está dentro de un `QWidget` contenedor que tiene su **propio**
`setStyleSheet(...)` (incluso algo tan inocuo como `"background: transparent;"`).

❌ **No hacer** (rompe la cascada del fondo del botón):
```python
def _make_footer(self) -> QWidget:
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    h = QHBoxLayout(w)
    ...
    return w  # root.addWidget(self._make_footer())
```

✅ **Hacer** (patrón usado en todos los diálogos que sí renderizan bien):
```python
def _make_footer(self) -> QHBoxLayout:
    h = QHBoxLayout()
    h.setContentsMargins(0, 4, 0, 0)
    h.setSpacing(10)
    ...
    return h  # root.addLayout(self._make_footer())
```

Regla general: un footer/toolbar que contenga botones estilizados por `objectName`
se agrega como **`QLayout` directo** al layout padre (`addLayout`), nunca envuelto en
un `QWidget` con stylesheet propio. Si de verdad necesitás un `QWidget` contenedor ahí
(por ejemplo para agruparlo con otra cosa), verificá visualmente que el fondo del botón
se siga pintando — no asumas que sí.

Si un botón necesita background garantizado sin depender de esta cascada (caso límite,
poco común), fijale el QSS completo directo en el propio widget en vez de vía
`objectName` + `DIALOG_STYLE` del ancestro:

```python
btn.setStyleSheet(f"""
    QPushButton {{ background-color: {COLOR_PRIMARY}; color: white; ... }}
    QPushButton:hover {{ background-color: {COLOR_PRIMARY_LIGHT}; }}
""")
```

### 8.3 `setFixedSize` en diálogos con contenido dinámico

Un diálogo cuyo contenido cambia según el estado (ej. aparece un aviso + botón extra
cuando cierta condición no se cumple) **no debe** usar `setFixedSize(w, h)` calculado
para el estado "común" — el estado alto queda con widgets solapados. Usar
`setMinimumWidth(w)` + `resize(w, h_para_el_peor_caso)` en su lugar (dialog
redimensionable, sin hard-fijar el alto). Bug real encontrado en `pago_linea_dialog.py`
/ `caja_apertura_dialog.py` cuando no había ninguna caja abierta.

### 8.4 Selector por propiedad (`Widget.clase`) dentro de un popup `Qt.WindowType.Popup`

**Bug real encontrado** (`toolbar_popups.py`, agosto 2026): el patrón
`lbl.setProperty("class", "FormLabel")` + selector `QLabel.FormLabel { ... }` (usado sin
problema en todos los `DIALOG_STYLE` de diálogos normales, ver sección 6) renderizaba
con un borde/fondo espurio de `QComboBox`/`QCheckBox` cuando el label vivía dentro de
un widget mostrado como `Qt.WindowType.Popup` (el popup de `BotonFiltros`). El mismo
problema afectó a un `QCheckBox` sin ningún selector por propiedad de por medio —
sugiere un problema de la cascada de estilos en ventanas `Popup` en vez del selector en
sí. **Se resolvió** cambiando a `objectName` (`lbl.setObjectName("FiltroLabel")` +
`QLabel#FiltroLabel { ... }`) y agregando `border: none; background: transparent;`
explícito a ese selector y al de `QCheckBox`. Regla practica: dentro de un widget
`Qt.WindowType.Popup`, preferí siempre `objectName` sobre selectores por propiedad, y
declará `border`/`background` explícitos en cada regla en vez de confiar en que un
widget sin esas propiedades declaradas quede realmente sin fondo/borde.

### 8.5 Popup anclado a un botón (`Qt.WindowType.Popup`) puede salirse de la pantalla

**Bug real encontrado** (`toolbar_popups.py::_PopupAnclado.mostrar_bajo`, 2026-08-27):
anclar un popup (`BotonFiltros`/`BotonExportar`) alineando su borde izquierdo con el
borde izquierdo del botón (`boton.mapToGlobal(boton.rect().bottomLeft())`) asume que
siempre hay espacio de sobra a la derecha. Con la ventana maximizada y el botón cerca
del borde derecho de una pantalla ancha, el popup (ancho fijo, `setFixedWidth`) queda
cortado por el borde de la pantalla. **Se resolvió** calculando la geometría disponible
de la pantalla real (`QGuiApplication.screenAt(punto)`/`.primaryScreen()`,
`.availableGeometry()`) y recortando la posición X para que el popup completo quede
dentro de esa geometría, corriéndose a la izquierda si hace falta. Cualquier popup
nuevo anclado a un widget (no solo `Qt.WindowType.Popup`) debe validar contra la
geometría de pantalla real, nunca asumir que hay espacio infinito a la derecha/abajo.

### 8.6 Contenido dentro de un `QTabWidget` necesita su propio margen — nunca `(0, x, 0, 0)`

**Bug real encontrado** (`roles_permisos_panel.py`/`factura_form_dialog.py`, 2026-08-27):
la página de una pestaña (`self.tabs.addTab(page, "...")`) es su **propio** contenedor de
clipping — el margen del panel/diálogo que envuelve al `QTabWidget` (sección 2, típico
`24,20,24,20`) no se hereda hacia adentro de cada pestaña. Un layout de página con
`setContentsMargins(0, 12, 0, 0)` (patrón usado hasta ahora para tabs) deja las tarjetas
con `aplicar_sombra()` pegadas al borde de la pestaña sin lugar para pintar su sombra o
su borde redondeado — se ven cortadas, más notorio todavía con dos tarjetas lado a lado
(quedan también pegadas entre sí). **Se resolvió** usando `(4, 12, 4, 4)` — margen chico
pero no-cero en los cuatro lados — en toda página de pestaña que contenga una tarjeta o
tabla con sombra. Al agregar una pestaña nueva a cualquier `QTabWidget`, nunca dejar el
margen izquierdo/derecho/inferior en `0`.

### 8.7 Esquina superior izquierda de `QTableWidget` "cortada" pese al `border-radius`

**Bug real encontrado** (`TABLE_QSS`, 2026-08-27, reportado en Facturación/Clientes/etc.
— cualquier tabla de la app): con `verticalHeader().setVisible(False)` (todas las tablas
de esta app lo hacen, no muestran número de fila), Qt igual sigue reservando y pintando
el widget interno `QTableCornerButton` en la esquina superior izquierda — la pequeña
"celda" donde se cruzarían el encabezado de fila y el de columna. Sin QSS propio, ese
widget se pinta con el estilo nativo de botón de Windows (plano, esquinas cuadradas, un
gris distinto al `COLOR_TABLE_HEADER` del resto del encabezado) — un cuadradito que
rompe visualmente el arco redondeado de `QHeaderView::section:first`, se ve como si la
esquina estuviera "cortada". **Se resolvió** estilando `QTableCornerButton::section`
igual que el encabezado (mismo `background-color`, mismo `border-top-left-radius: 8px`)
para que se funda con el resto en vez de destacarse. Selector poco conocido — si una
tabla nueva usa `TABLE_QSS` ya viene resuelto, pero si alguna vez se arma un QSS de
tabla desde cero, no olvidar este selector.

### 8.8 QSS **sin selector** se hereda a los hijos y no pinta el borde del propio widget

**Bug real encontrado** (`tasa_ticker.py`, 2026-08-27 — costó varias rondas porque los
síntomas parecían de contraste): el `border-bottom` de la franja de tasas se veía **solo
debajo de los bloques de texto**, con huecos en el espacio vacío del medio. Subir el
color y el grosor solo hacía más notorios esos fragmentos, nunca continuo.

La causa no era el color: era el QSS **sin selector**.

```python
# ❌ MAL -- regla sin selector
self.setStyleSheet(f"background-color: white; border-bottom: 1px solid {COLOR_BORDER};")
```

Una regla QSS sin selector Qt la trata como heredable y **se la pasa a todos los widgets
hijos**. Cada hijo que no declare su propio `border` (los bloques con
`background: transparent`, los `QLabel` de texto) dibuja entonces *su* borde inferior —
de ahí los segmentos de línea debajo del contenido y los huecos donde no hay hijos. De
paso, ese mismo cascade le imponía `background-color: white` al separador vertical, que
peleaba contra su propio color de fondo y lo hacía parecer invisible.

```python
# ✅ BIEN -- objectName + selector, igual que TOPBAR_QSS (`QWidget#TopBar {...}`)
self.setObjectName("TasaTicker")
self.setStyleSheet(f"QWidget#TasaTicker {{ background-color: white; border-bottom: 1px solid {COLOR_BORDER}; }}")
```

**Regla práctica**: todo contenedor que defina `background`/`border` propios usa
`setObjectName(...)` + selector `QWidget#Nombre {...}`, nunca una regla suelta. `TopBar`
(`TOPBAR_QSS` en `styles.py`) es el ejemplo de referencia que siempre funcionó. Las
barras de herramientas de los paneles usan regla suelta y *parecen* andar solo porque
todos sus hijos (`QLineEdit`, botones) traen QSS propio completo que pisa lo heredado —
no es garantía, es coincidencia.

**Corolario para separadores**: usar `QLabel` con `background-color`, no `QFrame` —
`QFrame` + `setFrameShape(QFrame.Shape.VLine)` + `setStyleSheet("color: ...")` no pinta
nada (con stylesheet propio Qt deja de usar `qDrawShadeLine()`, y `color` es propiedad de
*texto*, no controla el trazo). 1px con `COLOR_BORDER` alcanza y sobra:

```python
sep = QLabel()
sep.setFixedWidth(1)
sep.setFixedHeight(20)  # o la altura que corresponda al contexto
sep.setStyleSheet(f"background-color: {COLOR_BORDER};")
```

Antes de subir grosor o saturar un color porque "no se ve", descartar primero que el
problema sea de cascade/selector — subir contraste sobre un bug estructural lo tapa a
medias y deja la UI más fea.

## 9. Badges de estado

**Un solo widget para toda la app: `EstadoBadge` (`app/ui/styles.py`).** Antes había 4
clases casi idénticas repetidas por panel (`BadgeItem` en `clientes_panel.py`/
`inventario_panel.py`, `BadgeEstado` en `vendedores_panel.py`/`usuarios_panel.py`, más
`EstadoFacturaBadge` en `facturacion_panel.py`) — se consolidaron en una sola clase
(2026-08-27, a pedido del usuario) porque habían divergido: la versión con ícono dentro
de un contenedor de ancho fijo quedaba con el texto cortado en columnas angostas (p. ej.
"Act" en vez de "Activo" en Usuarios). `EstadoBadge` es la versión simple que ya usaba
Facturación — `QLabel` sobre fondo translúcido del mismo color, sin ícono, sin
contenedor aparte:

```python
from app.ui.styles import EstadoBadge, COLOR_SUCCESS, COLOR_DANGER

# Caso binario (Activo/Inactivo) -- clientes, productos, vendedores, usuarios, bancos...
activo = (estado or "").upper() == "ACTIVO"
color = COLOR_SUCCESS if activo else COLOR_DANGER
badge = EstadoBadge((estado or "Activo").capitalize(), color)
self.tabla.setCellWidget(fila, columna, badge)
```

Para un estado multi-valor no binario (como facturas: `EMITIDA`/`PAGADA`/`PARCIAL`/
`VENCIDA`/`ANULADA`), armar un diccionario `estado -> color` junto a
`COLORES_ESTADO_FACTURA` en `styles.py` (no uno suelto en el panel) y resolver el color
antes de construir el badge:

```python
color = COLORES_ESTADO_FACTURA.get(estado, COLOR_TEXT_MUTED)  # fallback gris
badge = EstadoBadge(estado.capitalize(), color)
```

| Estado (facturas) | Color |
|---|---|
| `EMITIDA` | `COLOR_INFO` |
| `PAGADA` | `COLOR_SUCCESS` |
| `PARCIAL` | `COLOR_WARNING` |
| `VENCIDA` | `COLOR_DANGER` |
| `ANULADA` | `COLOR_TEXT_MUTED` |

**Nunca crear una clase Badge nueva por panel** — si `EstadoBadge` no alcanza para un
caso nuevo (ej. necesita un ícono de verdad), extenderla en `styles.py`, no clonarla.

## 10. Tarjetas KPI (dashboard)

`KpiCard` (`dashboard_panel.py`): título + ícono + valor grande + detalle/delta
coloreado (`COLOR_SUCCESS`/`COLOR_DANGER` según sea positivo o negativo). Usa
`objectName("Card")` + `CARD_QSS`, no `SectionCard`. Reservado para filas de
indicadores tipo dashboard — un formulario normal usa `SectionCard`, no `KpiCard`.

## 11. Checklist para una pantalla/diálogo nuevo

- [ ] Colores: solo constantes de `app/ui/styles.py`, ningún hex nuevo salvo que sea
      realmente un color nuevo (y en ese caso, se agrega a la paleta ahí, no inline).
- [ ] Diálogo: `DIALOG_STYLE` local + encabezado ícono/título/subtítulo + footer como
      `QHBoxLayout` (nunca `QWidget` con stylesheet — sección 8.2) +
      `setWindowFlags(...WindowContextHelpButtonHint)` + `showEvent` con repintado
      diferido si hay tarjetas con sombra.
- [ ] Botones: variante correcta (`BtnPrimary`/`BtnSecondary`/danger), ícono con color
      semántico, `setCursor(PointingHandCursor)`, `setAutoDefault(False)`, texto en
      Sentence case (nunca mayúsculas a mano — sección 3).
- [ ] Tablas: `TABLE_QSS` solo (sin reglas propias encima, sección 5) + `aplicar_sombra`
      + setup estándar de la sección 5. Columna de estado: `EstadoBadge` (sección 9),
      nunca una clase Badge nueva por panel. Listado que puede crecer sin cota: paginado
      real (`pagina`/`por_pagina`/`total`, mismo patrón que `VentaService.listar_facturas()`/
      `ProductoService.buscar()`), no un `.all()` sin límite.
- [ ] Combos dentro de un formulario con scroll: `ComboBoxSinScroll` (sección 6), no
      `QComboBox` a secas.
- [ ] Página dentro de un `QTabWidget`: margen `(4, 12, 4, 4)`, nunca `(0, x, 0, 0)`, si
      contiene una tarjeta/tabla con sombra (sección 8.6).
- [ ] Toolbar de panel: orden fijo `Buscar — (stretch) — Nuevo X — Filtrar — Exportar`
      (sección 3.4). Dos o más filtros (o incluso uno) van dentro de `BotonFiltros`, no
      como dropdowns sueltos en la barra (sección 3.3).
- [ ] Exportación: si hay listado exportable, `BotonExportar` (sección 3.2), no dos
      botones "Exportar Excel"/"Exportar PDF" separados.
- [ ] Sizing: `setMinimumWidth` + `resize`, no `setFixedSize`, si el contenido puede
      cambiar de alto según el estado.
- [ ] Verificación visual real (no solo lint): abrir la pantalla en la app y mirarla,
      idealmente en los estados "raros" (listas vacías, validaciones fallidas, sin
      permisos) además del camino feliz.
