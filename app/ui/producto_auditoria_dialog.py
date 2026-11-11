"""Diálogo de auditoría para productos: muestra cambios de cantidades, precios, usuario y fecha."""

import json
import logging
from datetime import datetime, time

import qtawesome as qta
from PySide6.QtCore import QDate, QSignalBlocker, QSize, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from app.db.models import Usuario
from app.services.auditoria import AuditoriaService
from app.ui.auditoria_detalle_dialog import DetalleAuditoriaDialog
from app.ui.auditoria_detalle_dialog import filas_de_cambios as _filas_de_cambios
from app.ui.message_box import MessageBox
from app.ui.paginacion import ControlPaginacion, MixinPaginacion
from app.ui.pantalla import ajustar_tamano
from app.ui.styles import (
    COLOR_BLUE_LIGHTER,
    COLOR_DANGER,
    COLOR_INFO_BG,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MEDIUM,
    COLOR_TEXT_MUTED,
    DIALOGO_QSS,
    SEARCH_QSS,
    TABLE_QSS,
    alinear_encabezados,
    aplicar_sombra,
    dar_ancho_a_texto,
    estilizar_campo_fecha,
)

logger = logging.getLogger(__name__)

COLUMNAS = ["Fecha", "Usuario", "Acción", "Módulo", "Detalle", "Categoría", "Nombre", "ID Producto"]
COL_DETALLE = 4

ETIQUETAS_CAMPO = {
    "cantidad_unidad": "Cantidad (unidades)",
    "cantidad_caja": "Cantidad (cajas)",
    "costo_producto": "Costo",
    "descripcion_producto": "Descripción",
    "nombre_producto": "Nombre",
    "cod_producto": "Código",
    "id_categoria": "Categoría",
    "estado_producto": "Estado",
    "cantidad_minima": "Cantidad mínima",
}


def _etiqueta_campo(campo: str) -> str:
    return ETIQUETAS_CAMPO.get(campo, campo.replace("_", " ").capitalize())


def filas_de_cambios(detalle: str | None) -> list[tuple[str, str, str]]:
    """Cambios (campo, antes, despues) de un registro de producto, con las etiquetas de los campos de producto.
    La logica esta en auditoria_detalle_dialog.filas_de_cambios (compartida con la auditoria general)."""
    return _filas_de_cambios(detalle, _etiqueta_campo)


POR_PAGINA = 50
PAUSA_FILTRO_MS = 300  # espera tras la ultima tecla antes de consultar


class ProductoAuditoriaDialog(MixinPaginacion, QDialog):
    """Diálogo para ver el historial de auditoría de un producto."""

    def __init__(
        self,
        session: Session,
        usuario: Usuario,
        producto_id: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.session = session
        self.usuario = usuario
        self.producto_id = producto_id
        self.producto_nombre = self._obtener_nombre_producto()

        if self.producto_id:
            titulo = (
                f"Auditoría de Producto: {self.producto_nombre}" if self.producto_nombre else "Auditoría de Producto"
            )
        else:
            titulo = "Auditoría General de Productos"

        self.setWindowTitle(titulo)
        ajustar_tamano(self, 1200, 700, 1000, 600)
        self.setStyleSheet(DIALOGO_QSS)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()
        self._cargar_datos()

    def _obtener_nombre_producto(self) -> str | None:
        """Obtiene el nombre del producto si se proporcionó un ID."""
        if not self.producto_id:
            return None

        try:
            from app.db.models import Inventario

            producto = self.session.get(Inventario, self.producto_id)
            return producto.nombre_producto if producto else None
        except Exception:
            return None

    def _build_ui(self):
        # Misma plantilla que el historial de clientes: encabezado con icono, tarjetas SectionCard (sin reglas sin
        # selector: antes `border/padding` en la tarjeta se heredaban a cada texto y cada uno se dibujaba en una caja),
        # tabla estandar de solo lectura y botones secundarios.
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        root.addWidget(self._make_header())
        root.addWidget(self._make_filtros())
        root.addWidget(self._make_tabla(), stretch=1)
        root.addWidget(self._make_resumen())
        root.addLayout(self._make_footer())

    def _make_header(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.history", color=COLOR_PRIMARY).pixmap(QSize(22, 22)))
        icon_lbl.setStyleSheet(
            f"background-color: {COLOR_INFO_BG}; border: 1.5px solid {COLOR_BLUE_LIGHTER}; "
            "border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(38, 38)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titulos = QVBoxLayout()
        titulos.setSpacing(1)
        titulos.setContentsMargins(0, 0, 0, 0)
        lbl_titulo = QLabel("Auditoría de Productos")
        lbl_titulo.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        lbl_subtitulo = QLabel(self.producto_nombre or "Todos los productos")
        lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        titulos.addWidget(lbl_titulo)
        titulos.addWidget(lbl_subtitulo)

        h.addWidget(icon_lbl)
        h.addLayout(titulos)
        h.addStretch()
        return w

    @staticmethod
    def _etiqueta(texto: str) -> QLabel:
        lbl = QLabel(texto)
        lbl.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {COLOR_TEXT_MEDIUM};")
        return lbl

    def _make_filtros(self) -> QWidget:
        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        h = QHBoxLayout(card)
        h.setContentsMargins(16, 12, 16, 12)
        h.setSpacing(10)

        self.accion_combo = QComboBox()
        self.accion_combo.addItem("Todas las acciones")
        self.accion_combo.addItem("Creación", "CREAR_PRODUCTO")
        self.accion_combo.addItem("Actualización", "ACTUALIZAR_PRODUCTO")
        self.accion_combo.addItem("Cambio de Estado", "CAMBIAR_ESTADO_PRODUCTO")
        self.accion_combo.addItem("Cambio de Precio", "CAMBIO_PRECIO")
        self.accion_combo.addItem("Movimiento de Stock", "MOVIMIENTO_STOCK")
        self.accion_combo.addItem("Cambio de Descripción", "CAMBIO_DESCRIPCION")
        self.accion_combo.addItem("Cambio de Nombre", "CAMBIO_NOMBRE")
        self.accion_combo.addItem("Eliminación de Precio", "ELIMINAR_PRECIO")
        self.accion_combo.addItem("Recepción de Mercancía", "RECEPCION_MERCANCIA")
        self.accion_combo.setFixedHeight(34)
        self.accion_combo.setMinimumWidth(190)
        self.accion_combo.currentIndexChanged.connect(self._aplicar_filtros)

        self.nombre_input = QLineEdit()
        self.nombre_input.setPlaceholderText("Filtrar por nombre...")
        self.nombre_input.setStyleSheet(SEARCH_QSS)
        self.nombre_input.setFixedHeight(34)
        self.nombre_input.setMinimumWidth(180)
        self.nombre_input.textChanged.connect(self._filtrar_con_pausa)

        self.fecha_inicio = QDateEdit()
        estilizar_campo_fecha(self.fecha_inicio)
        self.fecha_inicio.setDisplayFormat("dd/MM/yyyy")
        self.fecha_inicio.setDate(self._fecha_desde_defecto())
        self.fecha_inicio.setFixedSize(130, 34)
        self.fecha_inicio.dateChanged.connect(self._aplicar_filtros)

        self.fecha_fin = QDateEdit()
        estilizar_campo_fecha(self.fecha_fin)
        self.fecha_fin.setDisplayFormat("dd/MM/yyyy")
        self.fecha_fin.setDate(QDate.currentDate())
        self.fecha_fin.setFixedSize(130, 34)
        self.fecha_fin.dateChanged.connect(self._aplicar_filtros)

        btn_limpiar = QPushButton("Limpiar filtros")
        btn_limpiar.setIcon(qta.icon("fa5s.times", color=COLOR_TEXT_MEDIUM))
        btn_limpiar.setObjectName("BtnSecondary")
        btn_limpiar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_limpiar.setFixedHeight(34)
        btn_limpiar.clicked.connect(self._limpiar_filtros)

        h.addWidget(self._etiqueta("Acción"))
        h.addWidget(self.accion_combo)
        h.addSpacing(8)
        h.addWidget(self._etiqueta("Producto"))
        h.addWidget(self.nombre_input, stretch=1)
        h.addSpacing(8)
        h.addWidget(self._etiqueta("Desde"))
        h.addWidget(self.fecha_inicio)
        h.addWidget(self._etiqueta("Hasta"))
        h.addWidget(self.fecha_fin)
        h.addSpacing(8)
        h.addWidget(btn_limpiar)
        return card

    def _make_tabla(self) -> QTableWidget:
        self.table = QTableWidget()
        self.table.setColumnCount(len(COLUMNAS))
        self.table.setHorizontalHeaderLabels(COLUMNAS)
        # Estandar de las tablas de la app: SOLO LECTURA (antes se podia escribir dentro de las celdas), sin
        # numeracion de filas, sin rejilla, filas alternas y sin barra de desplazamiento horizontal.
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setMinimumHeight(300)
        self.table.doubleClicked.connect(self._ver_detalle)  # el detalle completo, en su propia ventana
        self._resultados: list = []

        dar_ancho_a_texto(self.table, COL_DETALLE)  # absorbe el ancho que sobra

        alinear_encabezados(
            self.table,
            {
                0: Qt.AlignmentFlag.AlignCenter,
                1: Qt.AlignmentFlag.AlignLeft,
                2: Qt.AlignmentFlag.AlignLeft,
                3: Qt.AlignmentFlag.AlignCenter,
                4: Qt.AlignmentFlag.AlignLeft,
                5: Qt.AlignmentFlag.AlignCenter,
                6: Qt.AlignmentFlag.AlignLeft,
                7: Qt.AlignmentFlag.AlignCenter,
            },
        )
        self.table.setStyleSheet(TABLE_QSS)
        aplicar_sombra(self.table)
        return self.table

    @staticmethod
    def _chip(color: str) -> QLabel:
        """Etiqueta tipo "chip" del resumen: fondo y radio PROPIOS, para no heredar nada del contenedor."""
        lbl = QLabel()
        lbl.setStyleSheet(
            f"background-color: {COLOR_TABLE_HEADER}; color: {color}; border-radius: 10px; "
            "padding: 3px 12px; font-size: 12px; font-weight: 600;"
        )
        return lbl

    def _make_resumen(self) -> QWidget:
        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        h = QHBoxLayout(card)
        h.setContentsMargins(16, 10, 16, 10)
        h.setSpacing(10)

        self.lbl_total_registros = self._chip(COLOR_TEXT_MEDIUM)
        self.lbl_total_registros.setText("Total registros: 0")
        self.lbl_cambios_precio = self._chip(COLOR_SUCCESS)
        self.lbl_cambios_precio.setText("Cambios de precio: 0")
        self.lbl_movimientos_stock = self._chip(COLOR_PRIMARY)
        self.lbl_movimientos_stock.setText("Movimientos de stock: 0")
        self.lbl_ediciones = self._chip(COLOR_TEXT_MUTED)
        self.lbl_ediciones.setText("Ediciones: 0")

        for lbl in (
            self.lbl_total_registros,
            self.lbl_cambios_precio,
            self.lbl_movimientos_stock,
            self.lbl_ediciones,
        ):
            h.addWidget(lbl)
        h.addStretch()
        return card

    def _make_footer(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setContentsMargins(0, 4, 0, 0)
        btn_detalle = QPushButton("Ver detalle")
        btn_detalle.setIcon(qta.icon("fa5s.eye", color=COLOR_TEXT_DARK))
        btn_detalle.setObjectName("BtnSecondary")
        btn_detalle.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_detalle.setAutoDefault(False)
        btn_detalle.clicked.connect(self._ver_detalle)
        h.addWidget(btn_detalle)
        h.addStretch()
        self.paginacion = ControlPaginacion()
        self.paginacion.pagina_cambiada.connect(lambda _pagina: self._cargar_datos())
        h.addWidget(self.paginacion)
        h.addStretch()
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setIcon(qta.icon("fa5s.times", color=COLOR_PRIMARY))
        btn_cerrar.setObjectName("BtnSecondary")
        btn_cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cerrar.setAutoDefault(False)
        btn_cerrar.clicked.connect(self.accept)
        h.addWidget(btn_cerrar)
        return h

    def _cargar_datos(self):
        """Carga UNA pagina de la auditoria con los filtros actuales (la paginacion y el filtro por nombre se
        resuelven en la base: antes se traia toda la historia del rango y se filtraba en Python)."""
        try:
            resultado = AuditoriaService.consultar_auditoria_producto(
                self.session,
                producto_id=self.producto_id,
                accion=self.accion_combo.currentData(),
                texto=self.nombre_input.text().strip() or None,
                fecha_desde=datetime.combine(self.fecha_inicio.date().toPython(), time.min),
                fecha_hasta=datetime.combine(self.fecha_fin.date().toPython(), time.max),
                pagina=self.pagina_actual,
                por_pagina=POR_PAGINA,
            )
            self._poblar_tabla(resultado["items"])
            self._actualizar_resumen(resultado["por_accion"], resultado["total"])
            self.paginacion.actualizar_desde(resultado)
        except Exception as e:
            logger.exception("Error al cargar datos de auditoría")
            MessageBox.critical(self, "Error", f"No se pudieron cargar los datos de auditoría: {str(e)}")

    def _poblar_tabla(self, resultados):
        """Puebla la tabla con los resultados de auditoría."""
        self.table.setRowCount(0)
        self._resultados = list(resultados)

        for row, aud in enumerate(resultados):
            self.table.insertRow(row)

            # Fecha
            fecha_item = QTableWidgetItem(aud.fecha_evento.strftime("%d/%m/%Y %H:%M:%S"))
            fecha_item.setData(Qt.ItemDataRole.UserRole, aud.fecha_evento)
            fecha_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, fecha_item)

            # Usuario
            usuario_nombre = aud.usuario.nombre_usuario if aud.usuario else "Sistema"
            usuario_item = QTableWidgetItem(usuario_nombre)
            self.table.setItem(row, 1, usuario_item)

            # Acción
            accion_texto = aud.accion if aud.accion else "Desconocido"
            accion_formateada = self._formatear_accion(accion_texto)
            accion_item = QTableWidgetItem(accion_formateada)
            self._colorear_accion(row, aud.accion if aud.accion else "", accion_item)
            self.table.setItem(row, 2, accion_item)

            # Módulo
            modulo_item = QTableWidgetItem(aud.modulo)
            modulo_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, modulo_item)

            # Detalle (formateado para mejor legibilidad)
            detalle_formateado = self._formatear_detalle(aud.detalle)
            detalle_item = QTableWidgetItem(detalle_formateado)
            # El texto completo (la columna lo corta al ancho): al pasar el mouse, o doble clic para la ventana.
            detalle_item.setToolTip(detalle_formateado.replace(" | ", "\n"))
            self.table.setItem(row, 4, detalle_item)

            # Tipo (extraído del detalle)
            tipo = self._extraer_tipo(aud.accion, aud.detalle)
            tipo_item = QTableWidgetItem(tipo)
            tipo_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 5, tipo_item)

            # Nombre del producto (extraído del detalle)
            nombre_producto = self._extraer_nombre_producto(aud.detalle)
            nombre_item = QTableWidgetItem(nombre_producto if nombre_producto else "N/A")
            self.table.setItem(row, 6, nombre_item)

            # ID relacionado (extraído del detalle)
            id_relacionado = self._extraer_id_relacionado(aud.detalle)
            id_item = QTableWidgetItem(str(id_relacionado) if id_relacionado else "N/A")
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 7, id_item)

    def _colorear_accion(self, row, accion, item):
        """Color del TEXTO de la accion segun su tipo (en negrita). Antes se pintaba la celda entera con colores
        saturados (verde/rojo con texto blanco), que desentonaban con el resto de tablas de la app."""
        colores = {
            "CREAR_PRODUCTO": COLOR_SUCCESS,
            "ELIMINAR_PRECIO": COLOR_DANGER,
            "CAMBIO_PRECIO": "#D97706",
            "CAMBIAR_ESTADO_PRODUCTO": COLOR_PRIMARY,
            "MOVIMIENTO_STOCK": "#059669",
            "CAMBIO_DESCRIPCION": "#7C3AED",
            "CAMBIO_NOMBRE": "#C2410C",
            "ACTUALIZAR_PRODUCTO": "#4338CA",
            "RECEPCION_MERCANCIA": "#047857",
        }
        color = colores.get(accion)
        if color:
            item.setForeground(QColor(color))
            fuente = item.font()
            fuente.setBold(True)
            item.setFont(fuente)

    def _formatear_accion(self, accion: str | None) -> str:
        """Formatea la acción para mostrarla de forma legible."""
        if not accion:
            return "Desconocido"
        mapeo = {
            "CREAR_PRODUCTO": "Creación",
            "ACTUALIZAR_PRODUCTO": "Actualización",
            "CAMBIAR_ESTADO_PRODUCTO": "Cambio Estado",
            "CAMBIO_PRECIO": "Cambio Precio",
            "MOVIMIENTO_STOCK": "Movimiento Stock",
            "CAMBIO_DESCRIPCION": "Cambio Descripción",
            "CAMBIO_NOMBRE": "Cambio Nombre",
            "ELIMINAR_PRECIO": "Eliminar Precio",
            "RECEPCION_MERCANCIA": "Recepción Mercancía",
        }
        return mapeo.get(accion, accion)

    def _formatear_detalle(self, detalle):
        """Formatea el detalle JSON para hacerlo más legible."""
        if not detalle:
            return "Sin detalle"

        # Si el detalle es texto plano (como en RECEPCION_MERCANCIA), retornarlo tal cual
        if not detalle.strip().startswith("{"):
            return detalle

        try:
            datos = json.loads(detalle)
            partes = []

            # Manejar específicamente movimientos de stock
            if "movimientos" in datos and datos["movimientos"]:
                movimientos = []
                for mov in datos["movimientos"]:
                    campo = mov.get("campo", "")
                    valor_anterior = mov.get("valor_anterior", "")
                    valor_nuevo = mov.get("valor_nuevo", "")
                    diferencia = mov.get("diferencia", "")
                    tipo_movimiento = mov.get("tipo_movimiento", "")

                    # Formatear nombres de campos más legibles
                    campo_legible = campo.replace("_", " ").title()
                    if campo == "cantidad_unidad":
                        campo_legible = "Cantidad Unidad"
                    elif campo == "cantidad_caja":
                        campo_legible = "Cantidad Caja"

                    # Formatear el movimiento de manera clara
                    diff_num = float(diferencia) if diferencia else 0
                    diff_str = f"+{diff_num}" if diff_num > 0 else str(diff_num)
                    movimientos.append(
                        f"{campo_legible}: {valor_anterior} → {valor_nuevo} ({tipo_movimiento}: {diff_str})"
                    )

                if movimientos:
                    partes.append(f"Stock: {', '.join(movimientos)}")

            # Manejar cambios de descripción
            if "cambios" in datos and datos["cambios"]:
                cambios = []
                for cambio in datos["cambios"]:
                    campo = cambio.get("campo", "")
                    valor_anterior = cambio.get("valor_anterior", "")
                    valor_nuevo = cambio.get("valor_nuevo", "")

                    if campo == "descripcion_producto":
                        campo_legible = "Descripción"
                        # Truncar descripciones largas para el display
                        valor_anterior_short = (
                            (valor_anterior[:50] + "...") if len(valor_anterior) > 50 else valor_anterior
                        )
                        valor_nuevo_short = (valor_nuevo[:50] + "...") if len(valor_nuevo) > 50 else valor_nuevo
                        cambios.append(f"{campo_legible}: '{valor_anterior_short}' → '{valor_nuevo_short}'")
                    elif campo == "nombre_producto":
                        campo_legible = "Nombre"
                        cambios.append(f"{campo_legible}: '{valor_anterior}' → '{valor_nuevo}'")
                    else:
                        campo_legible = campo.replace("_", " ").title()
                        cambios.append(f"{campo_legible}: {valor_anterior} → {valor_nuevo}")

                if cambios:
                    partes.append(f"Cambios: {', '.join(cambios)}")

            if "id_producto" in datos:
                partes.append(f"Producto ID: {datos['id_producto']}")

            if "cod_producto" in datos:
                partes.append(f"Código: {datos['cod_producto']}")

            if "cambios_precio" in datos and datos["cambios_precio"]:
                cambios_precio = datos["cambios_precio"]
                for precio_key, cambio in cambios_precio.items():
                    campo_legible = precio_key.replace("_", " ").title()
                    valor_anterior = cambio.get("anterior")
                    valor_nuevo = cambio.get("nuevo")
                    if valor_anterior is not None:
                        partes.append(f"{campo_legible}: ${valor_anterior} → ${valor_nuevo}")
                    else:
                        partes.append(f"{campo_legible}: ${valor_nuevo} (nuevo)")
            else:
                # Compatibilidad con formato antiguo
                if "precio_nuevo" in datos:
                    partes.append(f"Precio Nuevo: ${datos['precio_nuevo']}")
                if "precio_anterior" in datos:
                    partes.append(f"Precio Anterior: ${datos['precio_anterior']}")
                if "precio_venta" in datos:
                    partes.append(f"Precio: ${datos['precio_venta']}")

            if "margen_nuevo" in datos:
                partes.append(f"Ganancia Nueva: {datos['margen_nuevo']}%")
            if "margen_anterior" in datos:
                partes.append(f"Ganancia Anterior: {datos['margen_anterior']}%")
            if "porcentaje_ganancia" in datos:
                partes.append(f"Ganancia: {datos['porcentaje_ganancia']}%")

            if "nuevo_estado" in datos:
                partes.append(f"Estado: {datos['nuevo_estado']}")

            if "campos" in datos:
                campos = ", ".join(datos["campos"])
                partes.append(f"Campos: {campos}")

            if "cambios_relevantes" in datos and datos["cambios_relevantes"]:
                cambios = []
                for cambio in datos["cambios_relevantes"]:
                    campo = cambio.get("campo", "")
                    valor_anterior = cambio.get("valor_anterior", "")
                    valor_nuevo = cambio.get("valor_nuevo", "")

                    # Formatear nombres de campos más legibles
                    campo_legible = campo.replace("_", " ").title()
                    if campo == "cantidad_unidad":
                        campo_legible = "Cantidad Unidad"
                    elif campo == "cantidad_caja":
                        campo_legible = "Cantidad Caja"
                    elif campo == "costo_producto":
                        campo_legible = "Costo"
                    elif campo == "descripcion_producto":
                        campo_legible = "Descripción"
                    elif campo == "nombre_producto":
                        campo_legible = "Nombre"

                    cambios.append(f"{campo_legible}: {valor_anterior} → {valor_nuevo}")
                if cambios:
                    partes.append(f"Cambios: {', '.join(cambios)}")

            return " | ".join(partes) if partes else detalle
        except (json.JSONDecodeError, Exception):
            return detalle

    def _extraer_tipo(self, accion, detalle):
        """Extrae el tipo de cambio de la acción y detalle."""
        if accion == "CAMBIO_PRECIO":
            return "Precio"
        elif accion == "CAMBIAR_ESTADO_PRODUCTO":
            return "Estado"
        elif accion == "CREAR_PRODUCTO":
            return "Creación"
        elif accion == "ACTUALIZAR_PRODUCTO":
            return "Edición"
        elif accion == "MOVIMIENTO_STOCK":
            return "Stock"
        elif accion == "CAMBIO_DESCRIPCION":
            return "Descripción"
        elif accion == "CAMBIO_NOMBRE":
            return "Nombre"
        elif accion == "ELIMINAR_PRECIO":
            return "Precio"
        elif accion == "RECEPCION_MERCANCIA":
            return "Recepción"

        # Fallback: buscar en el detalle
        if detalle and isinstance(detalle, str):
            detalle_lower = detalle.lower()
            if "precio" in detalle_lower:
                return "Precio"
            elif "cantidad" in detalle_lower or "stock" in detalle_lower:
                return "Stock"
            elif "costo" in detalle_lower:
                return "Costo"
            elif "categoria" in detalle_lower:
                return "Categoría"
            elif "estado" in detalle_lower:
                return "Estado"
            elif "descripcion" in detalle_lower:
                return "Descripción"
            elif "nombre" in detalle_lower:
                return "Nombre"

        return "General"

    def _extraer_id_relacionado(self, detalle):
        """Extrae el ID relacionado del detalle JSON o texto plano."""
        if not detalle:
            return None

        try:
            datos = json.loads(detalle)
            if "id_producto" in datos:
                return datos["id_producto"]
        except (json.JSONDecodeError, Exception):
            # Fallback para formato antiguo
            if "id_producto:" in detalle:
                try:
                    inicio = detalle.index("id_producto:") + len("id_producto:")
                    fin = detalle.find(",", inicio)
                    if fin == -1:
                        fin = len(detalle)
                    return int(detalle[inicio:fin].strip())
                except (ValueError, IndexError):
                    pass

            # Para formato texto plano (RECEPCION_MERCANCIA):
            # "Recepción OC ODC-000004 - NR NR-000017: 1.0000 unidades de HARINA DE TRIGO PRINCESA 45Kg (ID: 1)"
            if "(ID:" in detalle:
                try:
                    inicio = detalle.index("(ID:") + len("(ID:")
                    fin = detalle.index(")", inicio)
                    return int(detalle[inicio:fin].strip())
                except (ValueError, IndexError):
                    pass
            # Para formato anterior:
            # "Recepción de X unidades de [PRODUCTO] de la OC [OC] en la NR [NR], id_detalle: [ID]"
            if "id_detalle:" in detalle:
                try:
                    inicio = detalle.index("id_detalle:") + len("id_detalle:")
                    fin = len(detalle)
                    return int(detalle[inicio:fin].strip())
                except (ValueError, IndexError):
                    pass

        return None

    def _extraer_nombre_producto(self, detalle):
        """Extrae el nombre del producto del detalle JSON o texto plano."""
        if not detalle:
            return None

        try:
            datos = json.loads(detalle)
            if "nombre_producto" in datos:
                return datos["nombre_producto"]
        except (json.JSONDecodeError, Exception):
            pass

        # Para formato texto plano con motivo: "Motivo: ... - Stock: ... | Nombre del producto: XXX"
        if detalle and "Nombre del producto:" in detalle:
            try:
                inicio = detalle.index("Nombre del producto:") + len("Nombre del producto:")
                return detalle[inicio:].strip()
            except (ValueError, IndexError):
                pass

        # Para formato texto plano (RECEPCION_MERCANCIA):
        # "Recepción OC ODC-000004 - NR NR-000017: 1.0000 unidades de HARINA DE TRIGO PRINCESA 45Kg (ID: 1)"
        if detalle and " unidades de " in detalle:
            try:
                inicio = detalle.index(" unidades de ") + len(" unidades de ")
                # Buscar el patrón "(ID: X)" al final
                if "(ID:" in detalle:
                    fin = detalle.index("(ID:", inicio)
                    return detalle[inicio:fin].strip()
                else:
                    # Fallback: buscar " de la OC" o " - NR"
                    if " de la OC" in detalle:
                        fin = detalle.index(" de la OC", inicio)
                    elif " - NR" in detalle:
                        fin = detalle.index(" - NR", inicio)
                    else:
                        fin = len(detalle)
                    if fin > inicio:
                        return detalle[inicio:fin].strip()
            except (ValueError, IndexError):
                pass

        # Si no está en el detalle, intentar obtenerlo del ID del producto
        producto_id = self._extraer_id_relacionado(detalle)
        if producto_id:
            try:
                from app.db.models import Inventario

                producto = self.session.get(Inventario, producto_id)
                return producto.nombre_producto if producto else None
            except Exception:
                pass

        return None

    def _actualizar_resumen(self, por_accion: dict, total: int):
        """Estadisticas de TODO lo que cumple los filtros (no solo de la pagina visible)."""
        self.lbl_total_registros.setText(f"Total registros: {total}")
        self.lbl_cambios_precio.setText(f"Cambios de precio: {por_accion.get('CAMBIO_PRECIO', 0)}")
        self.lbl_movimientos_stock.setText(f"Movimientos de stock: {por_accion.get('MOVIMIENTO_STOCK', 0)}")
        self.lbl_ediciones.setText(
            f"Recepciones: {por_accion.get('RECEPCION_MERCANCIA', 0)} | "
            f"Descripción: {por_accion.get('CAMBIO_DESCRIPCION', 0)} | "
            f"Nombre: {por_accion.get('CAMBIO_NOMBRE', 0)} | "
            f"Estado: {por_accion.get('CAMBIAR_ESTADO_PRODUCTO', 0)} | "
            f"Ediciones: {por_accion.get('ACTUALIZAR_PRODUCTO', 0)} | "
            f"Creaciones: {por_accion.get('CREAR_PRODUCTO', 0)}"
        )

    def _datos_de_detalle(self, aud) -> dict:
        """Todo lo que muestra la ventana de detalle de un registro de auditoria."""
        id_prod = self._extraer_id_relacionado(aud.detalle)
        return {
            "fecha": aud.fecha_evento.strftime("%d/%m/%Y %H:%M:%S"),
            "usuario": aud.usuario.nombre_usuario if aud.usuario else "Sistema",
            "accion": self._formatear_accion(aud.accion),
            "modulo": aud.modulo,
            "extras": [
                ("Producto", self._extraer_nombre_producto(aud.detalle) or "N/A"),
                ("ID producto", id_prod if id_prod else "N/A"),
            ],
            "cambios": filas_de_cambios(aud.detalle),
            "detalle": self._formatear_detalle(aud.detalle).replace(" | ", "\n"),
        }

    def _ver_detalle(self, *_args):
        filas = self.table.selectionModel().selectedRows()
        if not filas:
            MessageBox.information(self, "Selección requerida", "Selecciona un registro de la lista.")
            return
        fila = filas[0].row()
        if not 0 <= fila < len(self._resultados):
            return
        DetalleAuditoriaDialog(self._datos_de_detalle(self._resultados[fila]), parent=self).exec()

    def _aplicar_filtros(self):
        """Aplica los filtros seleccionados y recarga los datos desde la pagina 1."""
        self.pagina_actual = 1
        self._cargar_datos()

    def _filtrar_con_pausa(self):
        """Filtro por nombre mientras se escribe: una consulta por pausa, no una por tecla."""
        if not hasattr(self, "_timer_filtro"):
            self._timer_filtro = QTimer(self)
            self._timer_filtro.setSingleShot(True)
            self._timer_filtro.timeout.connect(self._aplicar_filtros)
        self._timer_filtro.start(PAUSA_FILTRO_MS)

    @staticmethod
    def _fecha_desde_defecto() -> QDate:
        """Inicio del rango por defecto: los ultimos 12 meses desde HOY. Antes se restaban 30 dias a
        `QDateEdit().date()`, que arranca en 01/01/2000: salia "02/12/1999" (todo el historial) y cada
        "Limpiar filtros" retrocedia otros 30 dias."""
        return QDate.currentDate().addYears(-1)

    def _limpiar_filtros(self):
        """Limpia todos los filtros y recarga los datos."""
        # Sin señales: cada cambio dispararia su propia consulta y aqui se necesita una sola.
        bloqueos = [
            QSignalBlocker(w) for w in (self.accion_combo, self.nombre_input, self.fecha_inicio, self.fecha_fin)
        ]
        self.accion_combo.setCurrentIndex(0)
        self.nombre_input.clear()
        self.fecha_inicio.setDate(self._fecha_desde_defecto())
        self.fecha_fin.setDate(QDate.currentDate())
        del bloqueos
        self._aplicar_filtros()
