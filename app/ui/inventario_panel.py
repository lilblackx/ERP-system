"""
Panel completo del módulo Inventario.
Mismo patrón visual y de interacción que app/ui/clientes_panel.py (paleta y tipografía
de app/ui/styles.py) para mantener consistencia entre módulos: barra de herramientas,
tabla estilizada, paginación (D-01) y exportación a Excel (R-02/R-10).
"""

import logging

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import IntegrityError

from app.db.models import Inventario, ProductoPrecio, Usuario
from app.services.categorias import CategoriaService
from app.services.exportacion import exportar_excel
from app.services.inventario import PrecioService, ProductoService
from app.ui.producto_form_dialog import ProductoFormDialog
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
    SEARCH_QSS,
    TABLE_QSS,
)

logger = logging.getLogger(__name__)

COLS_VISIBLES = ["ID", "Código", "Nombre", "Categoría", "Cantidad", "Costo", "Precio Venta", "Estado"]
COL_ID_INTERNO = 0  # oculto
POR_PAGINA = 20


class BadgeItem(QWidget):
    """Widget badge para mostrar estado ACTIVO / INACTIVO -- mismo patron visual que
    app/ui/clientes_panel.py::BadgeItem."""

    def __init__(self, estado: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        activo = estado.upper() == "ACTIVO"
        bg_color = "#DCFCE7" if activo else "#FEF2F2"
        text_color = COLOR_SUCCESS if activo else COLOR_DANGER
        icon_name = "fa5s.check-circle" if activo else "fa5s.times-circle"

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon(icon_name, color=text_color).pixmap(12, 12))
        icon_lbl.setStyleSheet("background: transparent;")

        lbl = QLabel(estado.capitalize())
        lbl.setStyleSheet(f"background-color: transparent; color: {text_color}; font-size: 11px; font-weight: bold;")

        container = QWidget()
        container.setStyleSheet(f"background-color: {bg_color}; border-radius: 10px; padding: 2px 8px;")
        c_layout = QHBoxLayout(container)
        c_layout.setContentsMargins(6, 2, 6, 2)
        c_layout.setSpacing(4)
        c_layout.addWidget(icon_lbl)
        c_layout.addWidget(lbl)

        layout.addWidget(container)


class InventarioPanel(QWidget):
    """Panel principal del módulo Inventario: catálogo de productos con búsqueda,
    filtro por categoría, paginación, alta/edición (con precio de venta) y export."""

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.pagina_actual = 1
        self.total_paginas = 1
        self.setObjectName("ContentArea")
        self._setup_ui()
        QTimer.singleShot(100, self._cargar_categorias_filtro)
        QTimer.singleShot(100, self.cargar_productos)

    # ── Construcción de la UI ─────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        root.addWidget(self._make_header())
        root.addWidget(self._make_toolbar())
        root.addWidget(self._make_table())
        root.addWidget(self._make_footer())

        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

    def _make_header(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("Catálogo de Inventario")
        lbl.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        self.lbl_total = QLabel("Cargando…")
        self.lbl_total.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 13px;"
            f" background-color: {COLOR_TABLE_HEADER}; border-radius: 10px;"
            " padding: 3px 10px;"
        )

        self.lbl_alertas = QLabel()
        self.lbl_alertas.setStyleSheet(
            f"color: {COLOR_WARNING}; font-size: 13px; font-weight: bold;"
            " background-color: #FEF3C7; border-radius: 10px; padding: 3px 10px;"
        )
        self.lbl_alertas.setVisible(False)

        h.addWidget(lbl)
        h.addWidget(self.lbl_total)
        h.addWidget(self.lbl_alertas)
        h.addStretch()
        return w

    def _make_toolbar(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(
            f"background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 8px; padding: 4px;"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)

        self.buscar_input = QLineEdit()
        self.buscar_input.setPlaceholderText("Buscar por código o nombre…")
        self.buscar_input.addAction(qta.icon("fa5s.search", color="#94A3B8"), QLineEdit.ActionPosition.LeadingPosition)
        self.buscar_input.setObjectName("SearchInput")
        self.buscar_input.setStyleSheet(SEARCH_QSS)
        self.buscar_input.setFixedWidth(220)
        self.buscar_input.returnPressed.connect(self._buscar_desde_inicio)
        self.buscar_input.textChanged.connect(self._busqueda_dinamica)

        self.categoria_filtro_combo = QComboBox()
        self.categoria_filtro_combo.setFixedHeight(34)
        self.categoria_filtro_combo.addItem("Todas las categorías", None)
        self.categoria_filtro_combo.currentIndexChanged.connect(self._buscar_desde_inicio)

        self.solo_stock_check = QCheckBox("Solo con stock")
        self.solo_stock_check.toggled.connect(self._buscar_desde_inicio)

        self.btn_nuevo = QPushButton("Nuevo Producto")
        self.btn_nuevo.setIcon(qta.icon("fa5s.plus", color="white"))
        self.btn_nuevo.setStyleSheet(BUTTON_PRIMARY_QSS)
        self.btn_nuevo.clicked.connect(self.nuevo_producto)

        btn_exportar = QPushButton("Exportar")
        btn_exportar.setIcon(qta.icon("fa5s.file-export", color=COLOR_TEXT_DARK))
        btn_exportar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_exportar.clicked.connect(self.exportar_productos)

        h.addWidget(self.buscar_input)
        h.addWidget(self.categoria_filtro_combo)
        h.addWidget(self.solo_stock_check)
        h.addSpacerItem(QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        h.addWidget(self.btn_nuevo)
        h.addWidget(btn_exportar)
        return w

    def _make_table(self) -> QTableWidget:
        self.tabla = QTableWidget(0, len(COLS_VISIBLES))
        self.tabla.setHorizontalHeaderLabels(COLS_VISIBLES)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setShowGrid(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        self.tabla.setColumnWidth(7, 110)
        self.tabla.setStyleSheet(
            TABLE_QSS
            + """
            QTableWidget { alternate-background-color: #F8FAFC; }
        """
        )
        self.tabla.setColumnHidden(COL_ID_INTERNO, True)
        self.tabla.verticalHeader().setDefaultSectionSize(48)
        return self.tabla

    def _make_footer(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        self.lbl_pagina = QLabel("Página 1")
        self.lbl_pagina.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")

        self.btn_anterior = QPushButton()
        self.btn_anterior.setIcon(qta.icon("fa5s.chevron-left", color=COLOR_TEXT_DARK))
        self.btn_anterior.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_anterior.setFixedWidth(40)
        self.btn_anterior.clicked.connect(self._pagina_anterior)

        self.btn_siguiente = QPushButton()
        self.btn_siguiente.setIcon(qta.icon("fa5s.chevron-right", color=COLOR_TEXT_DARK))
        self.btn_siguiente.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_siguiente.setFixedWidth(40)
        self.btn_siguiente.clicked.connect(self._pagina_siguiente)

        btn_editar = QPushButton("Editar seleccionado")
        btn_editar.setIcon(qta.icon("fa5s.edit", color=COLOR_TEXT_DARK))
        btn_editar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_editar.clicked.connect(self.editar_producto)

        btn_estado = QPushButton("Cambiar estado")
        btn_estado.setIcon(qta.icon("fa5s.sync-alt", color=COLOR_TEXT_DARK))
        btn_estado.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_estado.clicked.connect(self.cambiar_estado_producto_seleccionado)

        h.addWidget(self.lbl_pagina)
        h.addWidget(self.btn_anterior)
        h.addWidget(self.btn_siguiente)
        h.addStretch()
        h.addWidget(btn_editar)
        h.addWidget(btn_estado)
        return w

    # ── Timer para búsqueda dinámica (300 ms debounce) ────────────────────

    def _busqueda_dinamica(self) -> None:
        if not hasattr(self, "_timer_busqueda"):
            self._timer_busqueda = QTimer()
            self._timer_busqueda.setSingleShot(True)
            self._timer_busqueda.timeout.connect(self._buscar_desde_inicio)
        self._timer_busqueda.start(300)

    def _buscar_desde_inicio(self) -> None:
        self.pagina_actual = 1
        self.cargar_productos()

    def _pagina_anterior(self) -> None:
        if self.pagina_actual > 1:
            self.pagina_actual -= 1
            self.cargar_productos()

    def _pagina_siguiente(self) -> None:
        if self.pagina_actual < self.total_paginas:
            self.pagina_actual += 1
            self.cargar_productos()

    # ── Lógica de datos ───────────────────────────────────────────────────

    def _cargar_categorias_filtro(self) -> None:
        session = self.session_factory()
        try:
            actual = self.categoria_filtro_combo.currentData()
            self.categoria_filtro_combo.blockSignals(True)
            self.categoria_filtro_combo.clear()
            self.categoria_filtro_combo.addItem("Todas las categorías", None)
            for categoria in CategoriaService.listar(session, id_usuario=self.usuario.id_usuario):
                self.categoria_filtro_combo.addItem(categoria.nombre, categoria.id_categoria)
            idx = self.categoria_filtro_combo.findData(actual)
            self.categoria_filtro_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.categoria_filtro_combo.blockSignals(False)
        except Exception:
            logger.exception("Fallo al cargar categorías para el filtro de inventario")
        finally:
            session.close()

    def cargar_productos(self) -> None:
        session = self.session_factory()
        try:
            resultado = ProductoService.buscar(
                session,
                texto=self.buscar_input.text().strip() or None,
                id_categoria=self.categoria_filtro_combo.currentData(),
                solo_con_stock=self.solo_stock_check.isChecked(),
                pagina=self.pagina_actual,
                por_pagina=POR_PAGINA,
                id_usuario=self.usuario.id_usuario,
            )
            precios = self._obtener_precios(session, [p.id_producto for p in resultado["items"]])
            self._poblar_tabla(resultado, precios)
            self._actualizar_alertas(session)
        except Exception:
            logger.exception("Fallo al cargar el catálogo de inventario")
            QMessageBox.critical(self, "Error de conexión", "No se pudo cargar el catálogo de inventario.")
        finally:
            session.close()

    @staticmethod
    def _obtener_precios(session, ids_producto: list[int]) -> dict[int, float]:
        """Lookup de solo-lectura directo (mismo criterio que cliente_form_dialog.py
        consultando Vendedor/CategoriaCliente sin pasar por un servicio): evita N
        consultas de PrecioService.obtener_precio(), una por fila de la tabla."""
        if not ids_producto:
            return {}
        filas = session.query(ProductoPrecio).filter(ProductoPrecio.id_producto.in_(ids_producto)).all()
        return {fila.id_producto: float(fila.precio_venta) for fila in filas}

    def _actualizar_alertas(self, session) -> None:
        alertas = ProductoService.obtener_alertas_stock(session, id_usuario=self.usuario.id_usuario)
        total_alertas = len(alertas["bajo_stock"]) + len(alertas["proximos_vencer"])
        if total_alertas:
            self.lbl_alertas.setText(f"⚠ {total_alertas} producto{'s' if total_alertas != 1 else ''} con alerta")
            self.lbl_alertas.setVisible(True)
        else:
            self.lbl_alertas.setVisible(False)

    def _poblar_tabla(self, resultado: dict, precios: dict[int, float]) -> None:
        productos: list[Inventario] = resultado["items"]
        self.tabla.setRowCount(len(productos))
        for fila, p in enumerate(productos):
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(p.id_producto)))
            self.tabla.setItem(fila, 1, QTableWidgetItem(p.cod_producto or ""))
            self.tabla.setItem(fila, 2, QTableWidgetItem(p.nombre_producto or ""))
            self.tabla.setItem(fila, 3, QTableWidgetItem(p.categoria.nombre if p.categoria else ""))

            item_cant = QTableWidgetItem(f"{float(p.cantidad_unidad):,.2f}")
            item_cant.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 4, item_cant)

            item_costo = QTableWidgetItem(f"${float(p.costo_producto):,.2f}")
            item_costo.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 5, item_costo)

            precio_venta = precios.get(p.id_producto)
            item_precio = QTableWidgetItem(f"${precio_venta:,.2f}" if precio_venta is not None else "Sin precio")
            item_precio.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(fila, 6, item_precio)

            badge = BadgeItem(p.estado_producto or "ACTIVO")
            self.tabla.setCellWidget(fila, 7, badge)

        total = resultado["total"]
        self.total_paginas = max(1, -(-total // POR_PAGINA))  # ceil sin importar math
        self.pagina_actual = min(self.pagina_actual, self.total_paginas)

        self.lbl_total.setText(f"{total} producto{'s' if total != 1 else ''}")
        self.lbl_pagina.setText(f"Página {self.pagina_actual} de {self.total_paginas}")
        self.btn_anterior.setEnabled(self.pagina_actual > 1)
        self.btn_siguiente.setEnabled(self.pagina_actual < self.total_paginas)

    def _fila_seleccionada_id(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            QMessageBox.information(self, "Selección requerida", "Selecciona un producto de la lista.")
            return None
        return int(self.tabla.item(filas[0].row(), 0).text())

    def nuevo_producto(self) -> None:
        session = self.session_factory()
        try:
            dialogo = ProductoFormDialog(session, self.usuario.id_usuario, parent=self)
            if dialogo.exec():
                datos = dialogo.get_data()
                datos["creado_por"] = self.usuario.id_usuario
                producto = ProductoService.crear(session, **datos)
                precio_venta = dialogo.get_precio_venta()
                if precio_venta > 0:
                    PrecioService.establecer_precio(
                        session, producto.id_producto, precio_venta, id_usuario=self.usuario.id_usuario
                    )
                self._cargar_categorias_filtro()
                self.cargar_productos()
        except IntegrityError:
            session.rollback()
            QMessageBox.warning(self, "Dato duplicado", "El código de producto ya está registrado.")
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "Dato inválido", str(exc))
        except Exception:
            session.rollback()
            logger.exception("Fallo al crear producto")
            QMessageBox.critical(self, "Error", "No se pudo crear el producto.")
        finally:
            session.close()

    def editar_producto(self) -> None:
        id_producto = self._fila_seleccionada_id()
        if id_producto is None:
            return

        session = self.session_factory()
        try:
            producto = session.get(Inventario, id_producto)
            dialogo = ProductoFormDialog(session, self.usuario.id_usuario, producto, parent=self)
            if dialogo.exec():
                datos = dialogo.get_data()
                ProductoService.actualizar(session, id_producto, id_usuario=self.usuario.id_usuario, **datos)
                precio_venta = dialogo.get_precio_venta()
                if precio_venta > 0:
                    PrecioService.establecer_precio(
                        session, id_producto, precio_venta, id_usuario=self.usuario.id_usuario
                    )
                self._cargar_categorias_filtro()
                self.cargar_productos()
        except IntegrityError:
            session.rollback()
            QMessageBox.warning(self, "Dato duplicado", "El código de producto ya está registrado.")
        except ValueError as exc:
            session.rollback()
            QMessageBox.warning(self, "Dato inválido", str(exc))
        except Exception:
            session.rollback()
            logger.exception("Fallo al editar producto")
            QMessageBox.critical(self, "Error", "No se pudo guardar los cambios del producto.")
        finally:
            session.close()

    def cambiar_estado_producto_seleccionado(self) -> None:
        id_producto = self._fila_seleccionada_id()
        if id_producto is None:
            return

        session = self.session_factory()
        try:
            producto = session.get(Inventario, id_producto)
            estado_actual = producto.estado_producto or "ACTIVO"
            nuevo_estado = "INACTIVO" if estado_actual == "ACTIVO" else "ACTIVO"

            respuesta = QMessageBox.question(
                self, "Confirmar", f"¿Cambiar el estado del producto '{producto.nombre_producto}' a {nuevo_estado}?"
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return

            ProductoService.cambiar_estado(session, id_producto, nuevo_estado, id_usuario=self.usuario.id_usuario)
            self.cargar_productos()
        except Exception:
            session.rollback()
            logger.exception("Fallo al cambiar el estado del producto %s", id_producto)
            QMessageBox.critical(self, "Error", "No se pudo cambiar el estado del producto.")
        finally:
            session.close()

    def exportar_productos(self) -> None:
        # R-09: se pide el destino ANTES de generar el archivo -- se escribe directo ahi,
        # nunca a un temporal.
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar inventario", "inventario.xlsx", "Excel (*.xlsx)")
        if not ruta:
            return

        session = self.session_factory()
        try:
            resultado = ProductoService.buscar(
                session,
                texto=self.buscar_input.text().strip() or None,
                id_categoria=self.categoria_filtro_combo.currentData(),
                solo_con_stock=self.solo_stock_check.isChecked(),
                pagina=1,
                por_pagina=1_000_000,
                id_usuario=self.usuario.id_usuario,
            )
            precios = self._obtener_precios(session, [p.id_producto for p in resultado["items"]])
            filas = [
                [
                    p.id_producto,
                    p.cod_producto,
                    p.nombre_producto,
                    p.categoria.nombre if p.categoria else None,
                    float(p.cantidad_unidad),
                    float(p.costo_producto),
                    precios.get(p.id_producto),
                    p.estado_producto,
                ]
                for p in resultado["items"]
            ]
            exportar_excel(ruta, COLS_VISIBLES, filas)
            QMessageBox.information(self, "Exportación completa", f"Se exportaron {len(filas)} productos a:\n{ruta}")
        except Exception:
            logger.exception("Fallo al exportar el catálogo de inventario")
            QMessageBox.critical(self, "Error", "No se pudo exportar el catálogo de inventario.")
        finally:
            session.close()
