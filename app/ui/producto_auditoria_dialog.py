"""Diálogo de auditoría para productos: muestra cambios de cantidades, precios, usuario y fecha."""

import json
import logging
from datetime import datetime

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QGridLayout,
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

from app.db.models import Auditoria, Usuario
from app.ui.message_box import MessageBox
from app.ui.styles import (
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_DANGER,
    COLOR_INFO_BG,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MEDIUM,
    COLOR_TEXT_MUTED,
    TABLE_QSS,
    alinear_encabezados,
)

logger = logging.getLogger(__name__)


class ProductoAuditoriaDialog(QDialog):
    """Diálogo para ver el historial de auditoría de un producto."""

    def __init__(self, session: Session, usuario: Usuario, producto_id: int | None = None, parent=None):
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
        self.setMinimumSize(1000, 600)
        self.resize(1200, 700)
        self.setStyleSheet(TABLE_QSS)
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        header = QWidget()
        header.setStyleSheet("background: transparent;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.history", color=COLOR_PRIMARY).pixmap(28, 28))
        icon_lbl.setStyleSheet(
            f"background-color: {COLOR_INFO_BG}; border: 2px solid {COLOR_PRIMARY}; border-radius: 10px; padding: 8px;"
        )
        icon_lbl.setMinimumSize(44, 44)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_titulo = QLabel("Auditoría de Productos")
        lbl_titulo.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        header_layout.addWidget(icon_lbl)
        header_layout.addWidget(lbl_titulo)
        header_layout.addStretch()

        layout.addWidget(header)

        # Filtros
        filtros_card = QWidget()
        filtros_card.setStyleSheet(
            f"background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 8px; padding: 12px;"
        )
        filtros_layout = QGridLayout(filtros_card)
        filtros_layout.setSpacing(12)

        # Filtro por acción
        lbl_accion = QLabel("Acción:")
        lbl_accion.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {COLOR_TEXT_DARK};")
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
        self.accion_combo.setMinimumHeight(32)
        self.accion_combo.currentIndexChanged.connect(self._aplicar_filtros)

        # Filtro por nombre de producto
        lbl_nombre = QLabel("Nombre Producto:")
        lbl_nombre.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        self.nombre_input = QLineEdit()
        self.nombre_input.setPlaceholderText("Filtrar por nombre...")
        self.nombre_input.setMinimumHeight(32)
        self.nombre_input.textChanged.connect(self._aplicar_filtros)

        # Filtro por rango de fechas
        lbl_fecha_inicio = QLabel("Desde:")
        lbl_fecha_inicio.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        self.fecha_inicio = QDateEdit()
        self.fecha_inicio.setCalendarPopup(True)
        self.fecha_inicio.setDate(self.fecha_inicio.date().addDays(-30))
        self.fecha_inicio.setMinimumHeight(32)
        self.fecha_inicio.dateChanged.connect(self._aplicar_filtros)

        lbl_fecha_fin = QLabel("Hasta:")
        lbl_fecha_fin.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        self.fecha_fin = QDateEdit()
        self.fecha_fin.setCalendarPopup(True)
        self.fecha_fin.setDate(self.fecha_fin.date().currentDate())
        self.fecha_fin.setMinimumHeight(32)
        self.fecha_fin.dateChanged.connect(self._aplicar_filtros)

        # Botón limpiar filtros
        btn_limpiar = QPushButton("Limpiar Filtros")
        btn_limpiar.setIcon(qta.icon("fa5s.times", color=COLOR_TEXT_MEDIUM))
        btn_limpiar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_limpiar.setMinimumHeight(32)
        btn_limpiar.clicked.connect(self._limpiar_filtros)

        filtros_layout.addWidget(lbl_accion, 0, 0)
        filtros_layout.addWidget(self.accion_combo, 0, 1)
        filtros_layout.addWidget(lbl_nombre, 0, 2)
        filtros_layout.addWidget(self.nombre_input, 0, 3)
        filtros_layout.addWidget(lbl_fecha_inicio, 0, 4)
        filtros_layout.addWidget(self.fecha_inicio, 0, 5)
        filtros_layout.addWidget(lbl_fecha_fin, 0, 6)
        filtros_layout.addWidget(self.fecha_fin, 0, 7)
        filtros_layout.addWidget(btn_limpiar, 0, 8)
        filtros_layout.setColumnStretch(1, 1)
        filtros_layout.setColumnStretch(3, 1)
        filtros_layout.setColumnStretch(5, 1)
        filtros_layout.setColumnStretch(7, 1)

        layout.addWidget(filtros_card)

        # Tabla de auditoría
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            ["Fecha", "Usuario", "Acción", "Módulo", "Detalle", "Categoría", "Nombre", "ID Producto"]
        )
        self.table.setMinimumHeight(350)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 140)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 130)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(4, 350)
        self.table.setColumnWidth(5, 100)
        self.table.setColumnWidth(6, 150)
        self.table.setColumnWidth(7, 90)

        alinear_encabezados(
            self.table,
            {
                0: Qt.AlignmentFlag.AlignLeft,
                1: Qt.AlignmentFlag.AlignLeft,
                2: Qt.AlignmentFlag.AlignLeft,
                3: Qt.AlignmentFlag.AlignLeft,
                4: Qt.AlignmentFlag.AlignLeft,
                5: Qt.AlignmentFlag.AlignCenter,
                6: Qt.AlignmentFlag.AlignLeft,
                7: Qt.AlignmentFlag.AlignCenter,
            },
        )

        layout.addWidget(self.table, stretch=1)

        # Resumen
        resumen_card = QWidget()
        resumen_card.setStyleSheet(
            f"background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 8px; padding: 12px;"
        )
        resumen_layout = QHBoxLayout(resumen_card)
        resumen_layout.setSpacing(20)

        self.lbl_total_registros = QLabel("Total registros: 0")
        self.lbl_total_registros.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_MEDIUM};")

        self.lbl_cambios_precio = QLabel("Cambios de precio: 0")
        self.lbl_cambios_precio.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_SUCCESS};")

        self.lbl_movimientos_stock = QLabel("Cambios de estado: 0")
        self.lbl_movimientos_stock.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_PRIMARY};")

        self.lbl_ediciones = QLabel("Ediciones: 0")
        self.lbl_ediciones.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLOR_TEXT_MUTED};")

        resumen_layout.addWidget(self.lbl_total_registros)
        resumen_layout.addWidget(self.lbl_cambios_precio)
        resumen_layout.addWidget(self.lbl_movimientos_stock)
        resumen_layout.addWidget(self.lbl_ediciones)
        resumen_layout.addStretch()

        layout.addWidget(resumen_card)

        # Footer
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 8, 0, 0)
        footer_layout.setSpacing(10)

        footer_layout.addStretch()

        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setIcon(qta.icon("fa5s.times", color=COLOR_TEXT_DARK))
        btn_cerrar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_cerrar.setMinimumHeight(32)
        btn_cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cerrar.clicked.connect(self.accept)
        footer_layout.addWidget(btn_cerrar)

        layout.addLayout(footer_layout)

    def _cargar_datos(self):
        """Carga los datos de auditoría desde la base de datos."""
        try:
            query = self.session.query(Auditoria).filter(Auditoria.modulo == "INVENTARIO")

            # Filtrar por producto específico si se proporcionó
            if self.producto_id:
                # Buscar en el JSON del detalle usando LIKE con el formato JSON correcto
                query = query.filter(Auditoria.detalle.like(f'%"id_producto": {self.producto_id}%'))

            # Aplicar filtros actuales
            accion = self.accion_combo.currentData()
            if accion:
                query = query.filter(Auditoria.accion == accion)

            # Convertir QDate a datetime.date usando métodos directos
            from datetime import date

            fecha_inicio = date(
                self.fecha_inicio.date().year(),
                self.fecha_inicio.date().month(),
                self.fecha_inicio.date().day(),
            )
            fecha_fin = date(
                self.fecha_fin.date().year(),
                self.fecha_fin.date().month(),
                self.fecha_fin.date().day(),
            )
            query = query.filter(
                Auditoria.fecha_evento >= datetime.combine(fecha_inicio, datetime.min.time()),
                Auditoria.fecha_evento <= datetime.combine(fecha_fin, datetime.max.time()),
            )

            # Ordenar por fecha descendente
            query = query.order_by(Auditoria.fecha_evento.desc())

            resultados = query.all()

            # Aplicar filtro por nombre de producto (client-side filtering)
            nombre_filtro = self.nombre_input.text().strip()
            if nombre_filtro:
                resultados_filtrados = []
                for aud in resultados:
                    nombre_producto = self._extraer_nombre_producto(aud.detalle)
                    if nombre_producto and nombre_filtro.lower() in nombre_producto.lower():
                        resultados_filtrados.append(aud)
                resultados = resultados_filtrados

            self._poblar_tabla(resultados)
            self._actualizar_resumen(resultados)

        except Exception as e:
            logger.exception("Error al cargar datos de auditoría")
            MessageBox.critical(self, "Error", f"No se pudieron cargar los datos de auditoría: {str(e)}")

    def _poblar_tabla(self, resultados):
        """Puebla la tabla con los resultados de auditoría."""
        self.table.setRowCount(0)

        for row, aud in enumerate(resultados):
            self.table.insertRow(row)

            # Fecha
            fecha_item = QTableWidgetItem(aud.fecha_evento.strftime("%d/%m/%Y %H:%M:%S"))
            fecha_item.setData(Qt.ItemDataRole.UserRole, aud.fecha_evento)
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
            self.table.setItem(row, 3, modulo_item)

            # Detalle (formateado para mejor legibilidad)
            detalle_formateado = self._formatear_detalle(aud.detalle)
            detalle_item = QTableWidgetItem(detalle_formateado)
            self.table.setItem(row, 4, detalle_item)

            # Tipo (extraído del detalle)
            tipo = self._extraer_tipo(aud.accion, aud.detalle)
            tipo_item = QTableWidgetItem(tipo)
            self.table.setItem(row, 5, tipo_item)

            # Nombre del producto (extraído del detalle)
            nombre_producto = self._extraer_nombre_producto(aud.detalle)
            nombre_item = QTableWidgetItem(nombre_producto if nombre_producto else "N/A")
            self.table.setItem(row, 6, nombre_item)

            # ID relacionado (extraído del detalle)
            id_relacionado = self._extraer_id_relacionado(aud.detalle)
            id_item = QTableWidgetItem(str(id_relacionado) if id_relacionado else "N/A")
            self.table.setItem(row, 7, id_item)

    def _colorear_accion(self, row, accion, item):
        """Colorea la celda de acción según el tipo."""
        if accion == "CREAR_PRODUCTO":
            item.setBackground(QColor(COLOR_SUCCESS))
            item.setForeground(Qt.GlobalColor.white)
        elif accion == "ELIMINAR_PRECIO":
            item.setBackground(QColor(COLOR_DANGER))
            item.setForeground(Qt.GlobalColor.white)
        elif accion == "CAMBIO_PRECIO":
            item.setBackground(QColor("#FEF3C7"))
            item.setForeground(QColor("#D97706"))
        elif accion == "CAMBIAR_ESTADO_PRODUCTO":
            item.setBackground(QColor(COLOR_INFO_BG))
            item.setForeground(QColor(COLOR_PRIMARY))
        elif accion == "MOVIMIENTO_STOCK":
            item.setBackground(QColor("#ECFDF5"))
            item.setForeground(QColor("#059669"))
        elif accion == "CAMBIO_DESCRIPCION":
            item.setBackground(QColor("#F3E8FF"))
            item.setForeground(QColor("#7C3AED"))
        elif accion == "CAMBIO_NOMBRE":
            item.setBackground(QColor("#FFEDD5"))
            item.setForeground(QColor("#C2410C"))
        elif accion == "ACTUALIZAR_PRODUCTO":
            item.setBackground(QColor("#E0E7FF"))
            item.setForeground(QColor("#4338CA"))

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
        }
        return mapeo.get(accion, accion)

    def _formatear_detalle(self, detalle):
        """Formatea el detalle JSON para hacerlo más legible."""
        if not detalle:
            return "Sin detalle"

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
        """Extrae el ID relacionado del detalle JSON."""
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
        return None

    def _extraer_nombre_producto(self, detalle):
        """Extrae el nombre del producto del detalle JSON."""
        if not detalle:
            return None

        try:
            datos = json.loads(detalle)
            if "nombre_producto" in datos:
                return datos["nombre_producto"]
        except (json.JSONDecodeError, Exception):
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

    def _actualizar_resumen(self, resultados):
        """Actualiza el resumen de estadísticas."""
        total = len(resultados)
        cambios_precio = sum(1 for r in resultados if r.accion == "CAMBIO_PRECIO")
        movimientos_stock = sum(1 for r in resultados if r.accion == "MOVIMIENTO_STOCK")
        cambios_descripcion = sum(1 for r in resultados if r.accion == "CAMBIO_DESCRIPCION")
        cambios_nombre = sum(1 for r in resultados if r.accion == "CAMBIO_NOMBRE")
        cambios_estado = sum(1 for r in resultados if r.accion == "CAMBIAR_ESTADO_PRODUCTO")
        ediciones = sum(1 for r in resultados if r.accion == "ACTUALIZAR_PRODUCTO")
        creaciones = sum(1 for r in resultados if r.accion == "CREAR_PRODUCTO")

        self.lbl_total_registros.setText(f"Total registros: {total}")
        self.lbl_cambios_precio.setText(f"Cambios de precio: {cambios_precio}")
        self.lbl_movimientos_stock.setText(f"Movimientos de stock: {movimientos_stock}")
        resumen_texto = (
            f"Descripción: {cambios_descripcion} | Nombre: {cambios_nombre} | "
            f"Estado: {cambios_estado} | Ediciones: {ediciones} | Creaciones: {creaciones}"
        )
        self.lbl_ediciones.setText(resumen_texto)

    def _aplicar_filtros(self):
        """Aplica los filtros seleccionados y recarga los datos."""
        self._cargar_datos()

    def _limpiar_filtros(self):
        """Limpia todos los filtros y recarga los datos."""
        self.accion_combo.setCurrentIndex(0)
        self.nombre_input.clear()
        self.fecha_inicio.setDate(self.fecha_inicio.date().addDays(-30))
        self.fecha_fin.setDate(self.fecha_fin.date().currentDate())
        self._cargar_datos()
