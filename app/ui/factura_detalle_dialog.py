"""Dialogo de solo lectura para ver el detalle completo de una factura ya emitida
(cabecera + lineas). Mismo patron visual que cliente_form_dialog.py/
producto_form_dialog.py (paleta y tipografia de app/ui/styles.py)."""

import logging

import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.empresa import EmpresaService
from app.services.permisos import PermisoDenegadoError
from app.ui.devolver_nota_credito_dialog import DevolverNotaCreditoDialog
from app.ui.factura_pdf import generar_pdf_factura
from app.ui.pago_linea_dialog import METODOS_PAGO, MONEDAS
from app.ui.styles import (
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_FIELD_BG,
    COLOR_PRIMARY,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    COLORES_ESTADO_FACTURA,
    FONT_FAMILY,
    TABLE_QSS,
    alinear_encabezados,
    aplicar_sombra,
    color_con_alpha,
)

DIALOG_STYLE = f"""
QDialog {{
    background-color: {COLOR_CONTENT_BG};
    font-family: '{FONT_FAMILY}', Arial, sans-serif;
}}
QWidget#SectionCard {{
    background-color: {COLOR_CARD_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
}}
QWidget#FieldChip {{
    background-color: {COLOR_FIELD_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
}}
QLabel.FormLabel {{
    font-size: 11px;
    font-weight: 600;
    color: {COLOR_TEXT_MUTED};
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
QLabel.FormValue {{
    font-size: 13px;
    font-weight: 600;
    color: {COLOR_TEXT_DARK};
}}
QLabel.SectionTitle {{
    font-size: 11px;
    font-weight: bold;
    color: {COLOR_PRIMARY};
    letter-spacing: 0.8px;
    padding-bottom: 2px;
}}
QPushButton#BtnSecondary {{
    background-color: {COLOR_FIELD_BG};
    color: #475569;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#BtnSecondary:hover {{
    background-color: {COLOR_TABLE_HEADER};
    color: {COLOR_TEXT_DARK};
}}
"""

logger = logging.getLogger(__name__)

_ETIQUETAS_METODO = {valor: etiqueta for etiqueta, valor in METODOS_PAGO}
_ETIQUETAS_MONEDA = {valor: etiqueta for etiqueta, valor in MONEDAS}
# Metodo de VUELTO (cambio), distinto de metodo de pago -- ver METODOS_VUELTO en
# factura_form_dialog.py. Duplicado aca a proposito (3 valores fijos) en vez de importar
# entre dos dialogos de UI que no se relacionan.
_ETIQUETAS_METODO_VUELTO = {
    "efectivo": "Efectivo",
    "pago_movil": "Pago Móvil",
    "transferencia": "Transferencia",
}


class FacturaDetalleDialog(QDialog):
    """Vista de solo lectura de una factura: cabecera + lineas. `datos` es el dict
    devuelto por `VentaService.obtener_factura()` ({"factura": FacturaVenta,
    "detalles": [FacturaDetalle, ...]}). `session`/`id_usuario` se usan solo para poder
    exportar la factura digital a PDF (necesita los datos de la empresa, ver
    EmpresaService.obtener_configuracion)."""

    def __init__(self, datos: dict, session, id_usuario: int | None, parent=None):
        super().__init__(parent)
        self.datos = datos
        self.factura = datos["factura"]
        self.detalles = datos["detalles"]
        self.metodo_pago = datos.get("metodo_pago")
        self.pagos = datos.get("pagos", [])
        self.nota_credito = datos.get("nota_credito")
        self.session = session
        self.id_usuario = id_usuario
        self.setWindowTitle(f"Factura {self.factura.numero_factura}")
        # Alto base +20 por la linea de desglose Subtotal/Descuento/IVA del footer
        # (siempre presente). El resto escala con la cantidad real de datos a mostrar en
        # vez de un numero fijo adivinado -- un estimado plano quedaba corto o largo
        # segun cuantas formas de pago hubiera (ver tambien el fix de
        # _make_card_pagos_vuelto: el alto de la TABLA en si se mide de verdad, esto solo
        # dimensiona la VENTANA para que le entre). setMinimumSize en vez de
        # setFixedSize para que las tarjetas nuevas no queden recortadas.
        alto_pagos_vuelto = 0
        if self.pagos:
            alto_pagos_vuelto = 70 + 40 * len(self.pagos)
        if self.factura.monto_vuelto > 0:
            alto_pagos_vuelto += 40
        hay_nota_disponible = self.nota_credito is not None and self.nota_credito.saldo_disponible > 0
        alto = 580 + alto_pagos_vuelto + (70 if hay_nota_disponible else 0)
        self.resize(720, alto)
        self.setMinimumSize(720, alto)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        root.addWidget(self._make_header())
        root.addWidget(self._make_ficha())
        card_pagos_vuelto = self._make_card_pagos_vuelto()
        if card_pagos_vuelto is not None:
            root.addWidget(card_pagos_vuelto)
        card_nota_credito = self._make_card_nota_credito()
        if card_nota_credito is not None:
            root.addWidget(card_nota_credito)
        root.addWidget(self._make_tabla_items(), stretch=1)
        root.addLayout(self._make_footer())

    def _make_header(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.file-invoice", color=COLOR_PRIMARY).pixmap(QSize(22, 22)))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(38, 38)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titulos = QVBoxLayout()
        titulos.setSpacing(1)
        titulos.setContentsMargins(0, 0, 0, 0)

        lbl_titulo = QLabel(f"Factura {self.factura.numero_factura}")
        lbl_titulo.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        lbl_subtitulo = QLabel("Detalle de la venta")
        lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        titulos.addWidget(lbl_titulo)
        titulos.addWidget(lbl_subtitulo)

        h.addWidget(icon_lbl)
        h.addLayout(titulos)
        h.addStretch()

        estado = self.factura.estado_visual
        color_estado = COLORES_ESTADO_FACTURA.get(estado, COLOR_TEXT_MUTED)
        badge = QLabel(estado.capitalize())
        badge.setStyleSheet(
            f"background-color: {color_con_alpha(color_estado, alpha=45)}; color: {color_estado};"
            f" border: 1px solid {color_estado}; border-radius: 6px;"
            " padding: 4px 12px; font-size: 12px; font-weight: bold;"
        )
        h.addWidget(badge)
        return w

    def _campo_chip(self, etiqueta: str, valor: str) -> QWidget:
        """Envuelve un par etiqueta/valor en su propia tarjeta chica (fondo
        COLOR_FIELD_BG + borde) -- antes eran labels sueltos sin fondo ni borde, lo
        que hacia que "DATOS DE LA FACTURA" se viera como texto plano en vez de
        celdas delimitadas."""
        chip = QWidget()
        chip.setObjectName("FieldChip")
        layout = QVBoxLayout(chip)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        lbl_etq = QLabel(etiqueta)
        lbl_etq.setProperty("class", "FormLabel")
        lbl_val = QLabel(valor)
        lbl_val.setProperty("class", "FormValue")
        lbl_val.setWordWrap(True)
        layout.addWidget(lbl_etq)
        layout.addWidget(lbl_val)
        return chip

    def _make_ficha(self) -> QWidget:
        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(10)

        titulo_row = QHBoxLayout()
        titulo_row.setSpacing(6)
        icono_titulo = QLabel()
        icono_titulo.setPixmap(qta.icon("fa5s.info-circle", color=COLOR_PRIMARY).pixmap(QSize(12, 12)))
        titulo = QLabel("DATOS DE LA FACTURA")
        titulo.setProperty("class", "SectionTitle")
        titulo_row.addWidget(icono_titulo)
        titulo_row.addWidget(titulo)
        titulo_row.addStretch()
        layout.addLayout(titulo_row)

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        cliente = self.factura.cliente
        vendedor = self.factura.vendedor
        fecha = self.factura.fecha_emision.strftime("%d/%m/%Y %H:%M") if self.factura.fecha_emision else "—"
        vencimiento = (
            self.factura.fecha_vencimiento.strftime("%d/%m/%Y") if self.factura.fecha_vencimiento else "Sin definir"
        )
        condicion = "Contado" if self.factura.condicion_pago == "contado" else "Crédito"
        tasa = self.factura.tasa
        tasa_texto = f"{float(tasa.tasa_dolar_bcv):,.2f} Bs/USD" if tasa else "—"

        # Metodo de pago para ventas de contado -- "mixto" (VentaService.obtener_factura)
        # significa que hubo mas de una forma de pago con metodo distinto; el desglose
        # linea por linea esta en la tarjeta de "Formas de pago" (_make_card_pagos_vuelto),
        # aca solo un resumen legible en vez del sentinel crudo.
        if self.factura.condicion_pago != "contado":
            metodo_pago_texto = "N/A"
        elif self.metodo_pago == "mixto":
            metodo_pago_texto = "Mixto (ver desglose abajo)"
        elif self.metodo_pago:
            metodo_pago_texto = _ETIQUETAS_METODO.get(self.metodo_pago, self.metodo_pago)
        else:
            metodo_pago_texto = "—"

        campos = [
            ("N° de Control", self.factura.numero_control),
            ("Cliente", cliente.nombre_razon_social if cliente else "—"),
            ("Fecha de emisión", fecha),
            ("Condición de pago", condicion),
            ("Método de pago", metodo_pago_texto),
            ("Vendedor", vendedor.nombre_vendedor if vendedor else "Sin vendedor"),
            ("Vencimiento", vencimiento if self.factura.condicion_pago == "credito" else "N/A"),
            ("Tasa BCV aplicada", tasa_texto),
            ("Observaciones", self.factura.observaciones_factura or "—"),
        ]
        for i, (etiqueta, valor) in enumerate(campos):
            fila, columna = divmod(i, 3)
            grid.addWidget(self._campo_chip(etiqueta, valor), fila, columna)

        layout.addLayout(grid)
        return card

    def _make_card_pagos_vuelto(self) -> QWidget | None:
        """Desglose de formas de pago (una linea por PagoCobro -- antes invisible: la
        ficha solo mostraba UN metodo de pago, `.first()`/dict que se quedaba con uno
        arbitrario) y del vuelto entregado (antes no se mostraba en ningun lado de la UI,
        aunque `FacturaVenta.monto_vuelto`/`metodo_vuelto`/`referencia_vuelto`/
        `autorizado_por_vuelto` ya estaban persistidos -- ver migrations/0027_vuelto_factura.sql).
        Solo se construye para facturas de contado con algo que mostrar."""
        if not self.pagos and self.factura.monto_vuelto <= 0:
            return None

        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        titulo_row = QHBoxLayout()
        titulo_row.setSpacing(6)
        icono_titulo = QLabel()
        icono_titulo.setPixmap(qta.icon("fa5s.money-bill-wave", color=COLOR_PRIMARY).pixmap(QSize(12, 12)))
        titulo = QLabel("FORMAS DE PAGO")
        titulo.setProperty("class", "SectionTitle")
        titulo_row.addWidget(icono_titulo)
        titulo_row.addWidget(titulo)
        titulo_row.addStretch()
        layout.addLayout(titulo_row)

        if self.pagos:
            tabla = QTableWidget(len(self.pagos), 3)
            tabla.setHorizontalHeaderLabels(["Método", "Moneda", "Monto"])
            alinear_encabezados(
                tabla, {0: Qt.AlignmentFlag.AlignLeft, 1: Qt.AlignmentFlag.AlignLeft, 2: Qt.AlignmentFlag.AlignRight}
            )
            tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            tabla.setAlternatingRowColors(True)
            tabla.setShowGrid(False)
            tabla.verticalHeader().setVisible(False)
            tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            tabla.setStyleSheet(TABLE_QSS)
            aplicar_sombra(tabla)
            for fila, pago in enumerate(self.pagos):
                tabla.setItem(fila, 0, QTableWidgetItem(_ETIQUETAS_METODO.get(pago.metodo_pago, pago.metodo_pago)))
                tabla.setItem(fila, 1, QTableWidgetItem(_ETIQUETAS_MONEDA.get(pago.moneda, pago.moneda)))
                item_monto = QTableWidgetItem(f"{float(pago.monto_moneda_origen or pago.monto):,.2f}")
                item_monto.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                tabla.setItem(fila, 2, item_monto)
            # Alto exacto medido DESPUES de poblar filas/estilo -- un estimado a mano
            # (header/fila con un numero fijo de px) subestimaba el alto real del QSS
            # (padding 10px del header + 2px de borde, padding 8px de cada item), y el
            # resultado quedaba con el header ocupando casi toda la tarjeta y la fila de
            # datos apenas visible, un pixel de alto (reportado por el usuario: "el grid
            # de formas de pago no se ve bien").
            alto_filas = sum(tabla.rowHeight(fila) for fila in range(tabla.rowCount()))
            tabla.setFixedHeight(tabla.horizontalHeader().sizeHint().height() + alto_filas + 2)
            layout.addWidget(tabla)

        if self.factura.monto_vuelto > 0:
            metodo_vuelto_texto = _ETIQUETAS_METODO_VUELTO.get(self.factura.metodo_vuelto, self.factura.metodo_vuelto)
            texto_vuelto = f"Vuelto entregado: ${float(self.factura.monto_vuelto):,.2f} · {metodo_vuelto_texto}"
            if self.factura.metodo_vuelto != "efectivo":
                autorizador = self.factura.autorizador_vuelto
                nombre_autorizador = autorizador.nombre_usuario if autorizador else "—"
                texto_vuelto += f" · Ref. {self.factura.referencia_vuelto or '—'} · Autorizó: {nombre_autorizador}"
            lbl_vuelto = QLabel(texto_vuelto)
            lbl_vuelto.setWordWrap(True)
            lbl_vuelto.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {COLOR_PRIMARY}; padding-top: 4px;")
            layout.addWidget(lbl_vuelto)

        return card

    def _make_card_nota_credito(self) -> QWidget | None:
        """Atajo directo para devolver la nota de credito que ESTA factura genero al
        anularse (si la hubo) -- antes, para devolver esa plata, habia que ir a buscar la
        nota al historial del cliente sin ninguna pista de que existia desde aca. No
        ofrece "aplicar a otra factura": esa accion si necesita ver el resto de facturas
        abiertas del cliente, que este dialogo no conoce (solo los items de ESTA
        factura) -- para eso sigue estando HistorialClienteWindow."""
        if self.nota_credito is None or self.nota_credito.saldo_disponible <= 0:
            return None

        card = QWidget()
        card.setObjectName("SectionCard")
        aplicar_sombra(card)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        icono = QLabel()
        icono.setPixmap(qta.icon("fa5s.hand-holding-usd", color=COLOR_PRIMARY).pixmap(QSize(16, 16)))
        layout.addWidget(icono)

        self.lbl_nota_credito = QLabel(
            f"Esta factura generó la nota de crédito {self.nota_credito.numero_nota_credito} — "
            f"disponible ${float(self.nota_credito.saldo_disponible):,.2f}"
        )
        self.lbl_nota_credito.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {COLOR_TEXT_DARK};")
        layout.addWidget(self.lbl_nota_credito, stretch=1)

        self.btn_devolver_nota = QPushButton("Devolver esta nota")
        self.btn_devolver_nota.setIcon(qta.icon("fa5s.hand-holding-usd", color=COLOR_PRIMARY))
        self.btn_devolver_nota.setObjectName("BtnSecondary")
        self.btn_devolver_nota.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_devolver_nota.setAutoDefault(False)
        self.btn_devolver_nota.clicked.connect(self._devolver_nota_credito)
        layout.addWidget(self.btn_devolver_nota)

        return card

    def _devolver_nota_credito(self) -> None:
        dialogo = DevolverNotaCreditoDialog(self.session, self.id_usuario, [self.nota_credito], parent=self)
        if dialogo.exec() != QDialog.DialogCode.Accepted or dialogo.nota_actualizada is None:
            return

        self.nota_credito = dialogo.nota_actualizada
        if self.nota_credito.saldo_disponible <= 0:
            self.lbl_nota_credito.setText(
                f"Esta factura generó la nota de crédito {self.nota_credito.numero_nota_credito} — ya devuelta"
            )
            self.btn_devolver_nota.setEnabled(False)
        else:
            self.lbl_nota_credito.setText(
                f"Esta factura generó la nota de crédito {self.nota_credito.numero_nota_credito} — "
                f"disponible ${float(self.nota_credito.saldo_disponible):,.2f}"
            )
        QMessageBox.information(self, "Nota de crédito devuelta", "La devolución se registró con éxito.")

    def _make_tabla_items(self) -> QTableWidget:
        columnas = ["Producto", "Cantidad", "Precio Unitario", "Subtotal"]
        tabla = QTableWidget(len(self.detalles), len(columnas))
        tabla.setHorizontalHeaderLabels(columnas)
        alinear_encabezados(
            tabla,
            {
                0: Qt.AlignmentFlag.AlignLeft,
                1: Qt.AlignmentFlag.AlignRight,
                2: Qt.AlignmentFlag.AlignRight,
                3: Qt.AlignmentFlag.AlignRight,
            },
        )
        tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabla.setAlternatingRowColors(True)
        tabla.setShowGrid(False)
        tabla.verticalHeader().setVisible(False)
        tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tabla.setStyleSheet(TABLE_QSS)
        aplicar_sombra(tabla)

        for fila, detalle in enumerate(self.detalles):
            nombre = detalle.producto.nombre_producto if detalle.producto else "Producto eliminado"
            cantidad = float(detalle.cantidad_producto)
            precio = float(detalle.precio_unitario)
            subtotal = cantidad * precio

            item_nombre = QTableWidgetItem(nombre)
            if detalle.observaciones_item:
                item_nombre.setToolTip(detalle.observaciones_item)
            tabla.setItem(fila, 0, item_nombre)
            item_cant = QTableWidgetItem(f"{cantidad:,.2f}")
            item_cant.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tabla.setItem(fila, 1, item_cant)
            item_precio = QTableWidgetItem(f"${precio:,.2f}")
            item_precio.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tabla.setItem(fila, 2, item_precio)
            item_subtotal = QTableWidgetItem(f"${subtotal:,.2f}")
            item_subtotal.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tabla.setItem(fila, 3, item_subtotal)

        return tabla

    def _make_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 4, 0, 0)
        footer.setSpacing(10)

        # Desglose Subtotal/Descuento/IVA -- antes solo se mostraba el total combinado, y
        # habia que exportar a PDF (que si desglosa, ver factura_pdf.py::_filas_totales)
        # para ver si se habia aplicado descuento o cuanto IVA.
        subtotal = float(self.factura.total_venta)
        descuento = float(self.factura.monto_descuento or 0)
        monto_iva = float(self.factura.monto_iva or 0)
        total_a_pagar = subtotal - descuento + monto_iva

        resumen_partes = [f"Subtotal: ${subtotal:,.2f}"]
        if descuento > 0:
            resumen_partes.append(f"Descuento: -${descuento:,.2f}")
        if self.factura.iva_aplicado:
            resumen_partes.append(f"IVA ({float(self.factura.porcentaje_iva_aplicado):g}%): ${monto_iva:,.2f}")

        col_totales = QVBoxLayout()
        col_totales.setSpacing(1)
        lbl_resumen = QLabel("  ·  ".join(resumen_partes))
        lbl_resumen.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_MUTED};")
        col_totales.addWidget(lbl_resumen)
        lbl_total = QLabel(f"Total a pagar: ${total_a_pagar:,.2f}")
        lbl_total.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        col_totales.addWidget(lbl_total)

        btn_exportar = QPushButton("Exportar PDF")
        btn_exportar.setIcon(qta.icon("fa5s.file-pdf", color=COLOR_DANGER))
        btn_exportar.setObjectName("BtnSecondary")
        btn_exportar.setFixedHeight(36)
        btn_exportar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_exportar.setAutoDefault(False)
        btn_exportar.clicked.connect(self.exportar_pdf)

        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setIcon(qta.icon("fa5s.times", color="#475569"))
        btn_cerrar.setObjectName("BtnSecondary")
        btn_cerrar.setFixedHeight(36)
        btn_cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cerrar.setAutoDefault(False)
        btn_cerrar.clicked.connect(self.accept)

        footer.addLayout(col_totales)
        footer.addStretch()
        footer.addWidget(btn_exportar)
        footer.addWidget(btn_cerrar)
        return footer

    def exportar_pdf(self) -> None:
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Exportar factura", f"{self.factura.numero_factura}.pdf", "PDF (*.pdf)"
        )
        if not ruta:
            return

        try:
            config_empresa = EmpresaService.obtener_configuracion(self.session, id_usuario=self.id_usuario)
            generar_pdf_factura(self.datos, config_empresa, ruta)
            QMessageBox.information(self, "Exportación completa", f"Factura exportada a:\n{ruta}")
        except PermisoDenegadoError:
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para consultar la configuración de empresa.")
        except Exception:
            logger.exception("Fallo al exportar la factura %s a PDF", self.factura.numero_factura)
            QMessageBox.critical(self, "Error", "No se pudo exportar la factura a PDF.")
