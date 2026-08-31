"""
Panel del módulo Configuración. Hoy solo cubre los datos de la empresa (RIF, Nombre,
Dirección, Teléfono, Logo) -- pensado para crecer con mas pestañas de configuración de
la app (ver docs/ESTADO_DEL_PROYECTO.md).
"""

import logging
from decimal import Decimal

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtPrintSupport import QPrinterInfo
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.db.models import Usuario
from app.services.empresa import _SENTINEL, EmpresaService
from app.services.permisos import PermisoDenegadoError
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_PRIMARY,
    COLOR_TEXT_DARK,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_MUTED,
    ICON_CHEVRON_DOWN_URL,
    ICON_CHEVRON_UP_URL,
)

logger = logging.getLogger(__name__)


class ConfigEmpresaPanel(QWidget):
    """Panel para gestionar los datos de configuración de la empresa."""

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self.setObjectName("ContentArea")

        self.logo_bytes: bytes | None = _SENTINEL

        self._build_ui()
        self.cargar_datos()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(20)

        # Tarjeta principal. Selector acotado a #SectionCard (mismo patron que el resto
        # de la app, ver usuario_form_dialog.py y las otras 18 pantallas con esta misma
        # tarjeta) -- un "QWidget {...}" sin ID aca se aplicaba a CUALQUIER widget hijo sin
        # estilo propio mas especifico, no solo a la tarjeta: iva_activo_check (QCheckBox
        # mas abajo, solo define color/font-size, sin "border: none") heredaba el borde +
        # fondo + esquinas redondeadas de la tarjeta en vez de verse como un checkbox plano
        # (hallazgo del usuario, 2026-08-28).
        card = QWidget()
        card.setObjectName("SectionCard")
        card.setStyleSheet(f"""
            QWidget#SectionCard {{
                background-color: {COLOR_CARD_BG};
                border: 1px solid {COLOR_BORDER};
                border-radius: 12px;
            }}
        """)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 32, 32, 32)
        card_layout.setSpacing(24)

        # Título
        lbl_titulo = QLabel("Datos de la Empresa")
        # "background: transparent" explicito, no solo "border: none": un QLabel con
        # stylesheet propio puede terminar pintando el fondo de su paleta en vez de quedar
        # realmente transparente si no se lo decimos -- mismo hallazgo que las etiquetas
        # Desde/Hasta de AuditoriaPanel (2026-08-28), aca se veia como una barra gris
        # detras del titulo.
        lbl_titulo.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {COLOR_TEXT_DARK}; border: none; background: transparent;"
        )
        card_layout.addWidget(lbl_titulo)

        # Sección de Logo
        logo_layout = QHBoxLayout()
        logo_layout.setSpacing(20)

        self.lbl_logo_preview = QLabel("Sin Logo")
        self.lbl_logo_preview.setFixedSize(120, 120)
        self.lbl_logo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_logo_preview.setStyleSheet(f"""
            QLabel {{
                background-color: {COLOR_CONTENT_BG};
                border: 2px dashed {COLOR_BORDER};
                border-radius: 8px;
                color: {COLOR_TEXT_MUTED};
            }}
        """)

        logo_btn_layout = QVBoxLayout()
        logo_btn_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        lbl_logo_hint = QLabel("Formatos soportados: PNG, JPG")
        lbl_logo_hint.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; border: none; background: transparent;")

        btn_seleccionar_logo = QPushButton("Seleccionar Logo")
        btn_seleccionar_logo.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_seleccionar_logo.setFixedWidth(150)
        btn_seleccionar_logo.clicked.connect(self.seleccionar_logo)

        btn_borrar_logo = QPushButton("Borrar Logo")
        btn_borrar_logo.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_borrar_logo.setFixedWidth(150)
        btn_borrar_logo.clicked.connect(self.borrar_logo)

        logo_btn_layout.addWidget(btn_seleccionar_logo)
        logo_btn_layout.addWidget(btn_borrar_logo)
        logo_btn_layout.addWidget(lbl_logo_hint)

        logo_layout.addWidget(self.lbl_logo_preview)
        logo_layout.addLayout(logo_btn_layout)
        logo_layout.addStretch()

        card_layout.addLayout(logo_layout)

        # Formulario
        form = QFormLayout()
        form.setSpacing(16)

        def _crear_input(placeholder: str) -> QLineEdit:
            inp = QLineEdit()
            inp.setPlaceholderText(placeholder)
            inp.setMinimumHeight(38)
            inp.setStyleSheet(f"""
                QLineEdit {{
                    border: 1px solid {COLOR_BORDER};
                    border-radius: 6px;
                    padding: 0 12px;
                    font-size: 14px;
                }}
                QLineEdit:focus {{
                    border: 1px solid {COLOR_PRIMARY};
                }}
            """)
            return inp

        self.rif_input = _crear_input("Ej: J-12345678-9")
        self.nombre_input = _crear_input("Razón Social")
        self.direccion_input = _crear_input("Dirección principal")
        self.telefono_input = _crear_input("Ej: +58 412 1234567")

        lbl_style = (
            f"font-weight: bold; color: {COLOR_TEXT_DARK}; font-size: 14px; border: none; background: transparent;"
        )

        lbl_rif = QLabel("RF Empresa:")
        lbl_rif.setStyleSheet(lbl_style)

        lbl_nombre = QLabel("Nombre Empresa:")
        lbl_nombre.setStyleSheet(lbl_style)

        lbl_direccion = QLabel("Dirección:")
        lbl_direccion.setStyleSheet(lbl_style)

        lbl_telefono = QLabel("Teléfono:")
        lbl_telefono.setStyleSheet(lbl_style)

        self.footer_input = QTextEdit()
        self.footer_input.setPlaceholderText("Texto libre al pie de cada factura (ej. datos bancarios, garantía)")
        self.footer_input.setMaximumHeight(70)
        self.footer_input.setStyleSheet(f"""
            QTextEdit {{
                border: 1px solid {COLOR_BORDER};
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 14px;
            }}
            QTextEdit:focus {{
                border: 1px solid {COLOR_PRIMARY};
            }}
        """)

        lbl_footer = QLabel("Pie de factura:")
        lbl_footer.setStyleSheet(lbl_style)

        form.addRow(lbl_rif, self.rif_input)
        form.addRow(lbl_nombre, self.nombre_input)
        form.addRow(lbl_direccion, self.direccion_input)
        form.addRow(lbl_telefono, self.telefono_input)
        form.addRow(lbl_footer, self.footer_input)

        card_layout.addLayout(form)

        # IVA: activable por empresa, con porcentaje ajustable -- se snapshotea en cada
        # factura al emitirla (VentaService.emitir_factura), un cambio aca no altera
        # retroactivamente facturas ya emitidas.
        iva_layout = QHBoxLayout()
        iva_layout.setSpacing(12)

        self.iva_activo_check = QCheckBox("Aplicar IVA en las facturas")
        self.iva_activo_check.setStyleSheet(f"color: {COLOR_TEXT_DARK}; font-size: 14px; background: transparent;")

        self.iva_porcentaje_input = QDoubleSpinBox()
        self.iva_porcentaje_input.setRange(0, 100)
        self.iva_porcentaje_input.setDecimals(2)
        self.iva_porcentaje_input.setSuffix(" %")
        self.iva_porcentaje_input.setValue(16.00)
        self.iva_porcentaje_input.setFixedWidth(110)
        self.iva_porcentaje_input.setMinimumHeight(38)
        # Estilo propio (no confiar en heredar GLOBAL_QSS, ver comentario de
        # impresora_combo mas abajo -- el mismo problema aplica aca): recuadro normal
        # habilitado, atenuado/sin interaccion cuando "Aplicar IVA" esta desmarcado --
        # antes el campo quedaba siempre editable con el mismo aspecto sin importar el
        # estado del check, lo que no dejaba claro si el porcentaje aplicaba o no
        # (hallazgo del usuario, 2026-08-28).
        self.iva_porcentaje_input.setStyleSheet(f"""
            QDoubleSpinBox {{
                background-color: #FFFFFF;
                border: 1px solid {COLOR_BORDER};
                border-radius: 6px;
                padding: 0 4px;
                font-size: 14px;
                color: {COLOR_TEXT_DARK};
            }}
            QDoubleSpinBox:focus {{
                border: 1px solid {COLOR_PRIMARY};
            }}
            QDoubleSpinBox:disabled {{
                background-color: {COLOR_CONTENT_BG};
                color: {COLOR_TEXT_LIGHT};
            }}
            QDoubleSpinBox::up-button {{
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 18px;
                border: none;
                border-left: 1px solid {COLOR_BORDER};
                border-top-right-radius: 6px;
                background: transparent;
            }}
            QDoubleSpinBox::down-button {{
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 18px;
                border: none;
                border-left: 1px solid {COLOR_BORDER};
                border-bottom-right-radius: 6px;
                background: transparent;
            }}
            QDoubleSpinBox::up-arrow {{
                image: url({ICON_CHEVRON_UP_URL});
                width: 10px;
                height: 10px;
            }}
            QDoubleSpinBox::down-arrow {{
                image: url({ICON_CHEVRON_DOWN_URL});
                width: 10px;
                height: 10px;
            }}
        """)
        self.iva_porcentaje_input.setEnabled(self.iva_activo_check.isChecked())
        self.iva_activo_check.toggled.connect(self.iva_porcentaje_input.setEnabled)

        iva_layout.addWidget(self.iva_activo_check)
        iva_layout.addWidget(self.iva_porcentaje_input)
        iva_layout.addStretch()

        card_layout.addLayout(iva_layout)

        # Impresora predeterminada: a donde se envia la factura digital automaticamente
        # al presionar "Facturar" (ver FacturacionPanel.nueva_factura /
        # app/ui/factura_pdf.py::imprimir_factura). Elegir "Microsoft Print to PDF" (u
        # otra impresora virtual) aca cubre tambien el caso de guardarla automaticamente
        # sin necesitar una ruta separada.
        impresora_layout = QHBoxLayout()
        impresora_layout.setSpacing(12)

        lbl_impresora = QLabel("Impresora predeterminada:")
        lbl_impresora.setStyleSheet(lbl_style)

        # Estilo propio (copiado literal del bloque QComboBox de GLOBAL_QSS en styles.py,
        # mismos valores de padding/flecha): antes este combo NO tenia stylesheet propio a
        # proposito, para heredar GLOBAL_QSS -- pero al acotar el selector de `card` a
        # #SectionCard (2026-08-28, ver comentario mas arriba) dejo de heredar ese fondo/
        # borde de ningun lado y quedo sin caja visible. En vez de volver a depender de la
        # cascada (fragil, ya genero un bug de padding-right encimando la flecha con el
        # texto la primera vez que se intento), se fija el estilo aca mismo.
        self.impresora_combo = QComboBox()
        self.impresora_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: #FFFFFF;
                border: 1px solid {COLOR_BORDER};
                border-radius: 6px;
                padding: 6px 28px 6px 12px;
                color: {COLOR_TEXT_DARK};
            }}
            QComboBox:hover {{
                border-color: {COLOR_TEXT_MUTED};
            }}
            QComboBox:focus {{
                border-color: {COLOR_PRIMARY};
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 28px;
                border: none;
                background: transparent;
            }}
            QComboBox::down-arrow {{
                image: url({ICON_CHEVRON_DOWN_URL});
                width: 12px;
                height: 12px;
                margin-right: 8px;
            }}
        """)
        self.impresora_combo.setMinimumHeight(38)
        self.impresora_combo.setMinimumWidth(260)
        self._cargar_impresoras_disponibles()

        impresora_layout.addWidget(lbl_impresora)
        impresora_layout.addWidget(self.impresora_combo)
        impresora_layout.addStretch()

        card_layout.addLayout(impresora_layout)

        # Footer con botón Guardar
        footer_layout = QHBoxLayout()
        btn_guardar = QPushButton("Guardar Cambios")
        btn_guardar.setStyleSheet(BUTTON_PRIMARY_QSS)
        btn_guardar.setMinimumWidth(200)
        btn_guardar.setMinimumHeight(44)
        btn_guardar.clicked.connect(self.guardar_cambios)

        footer_layout.addStretch()
        footer_layout.addWidget(btn_guardar)

        card_layout.addLayout(footer_layout)

        # Scroll en vez de agregar `card` directo a `root`: sin esto, en una ventana mas
        # baja que el contenido (titulo + logo + 5 filas de formulario + IVA + impresora +
        # boton) el layout no tiene donde recortar y termina comprimiendo filas por debajo
        # de su alto natural -- footer_input (QTextEdit, el unico campo sin
        # setMinimumHeight) era el que mas se notaba, con su texto superpuesto a la fila de
        # arriba (hallazgo del usuario, 2026-08-28). Mismo patron que
        # roles_permisos_panel.py: NoFrame + fondo transparente para que no se note como un
        # widget aparte.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.setWidget(card)
        root.addWidget(scroll, stretch=1)

        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

    def _cargar_impresoras_disponibles(self, seleccionada: str | None = None) -> None:
        """Puebla el combo con las impresoras que Qt detecta instaladas en el sistema
        (QPrinterInfo.availablePrinters()). Si `seleccionada` (el valor guardado en BD)
        ya no esta entre ellas -- se desconecto, se reinstalo con otro nombre -- se
        agrega igual como opcion (marcada "no disponible") para no perderla de vista ni
        pisarla con None solo por abrir y guardar esta pantalla sin tocar el combo."""
        self.impresora_combo.blockSignals(True)
        self.impresora_combo.clear()
        self.impresora_combo.addItem("Ninguna (no imprimir automáticamente)", None)

        nombres_disponibles = [p.printerName() for p in QPrinterInfo.availablePrinters()]
        for nombre in nombres_disponibles:
            self.impresora_combo.addItem(nombre, nombre)

        if seleccionada and seleccionada not in nombres_disponibles:
            self.impresora_combo.addItem(f"{seleccionada} (no disponible)", seleccionada)

        idx = self.impresora_combo.findData(seleccionada)
        self.impresora_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.impresora_combo.blockSignals(False)

    def cargar_datos(self) -> None:
        session = self.session_factory()
        try:
            config = EmpresaService.obtener_configuracion(session, self.usuario.id_usuario)
            if config:
                self.rif_input.setText(config.rif_empresa or "")
                self.nombre_input.setText(config.razon_social_empresa or "")
                self.direccion_input.setText(config.direccion_empresa or "")
                self.telefono_input.setText(config.telefono_empresa or "")
                self.footer_input.setPlainText(config.pie_pagina_empresa or "")
                self.iva_activo_check.setChecked(bool(config.iva_activo))
                # Explicito ademas de la conexion toggled->setEnabled en _build_ui():
                # setChecked() solo emite toggled si el valor cambia, y si lo cargado
                # coincide con el default (desmarcado) del constructor no dispararia nada.
                self.iva_porcentaje_input.setEnabled(self.iva_activo_check.isChecked())
                self.iva_porcentaje_input.setValue(float(config.iva_porcentaje))
                self._cargar_impresoras_disponibles(config.impresora_predeterminada)

                if config.logotipo_empresa:
                    self._mostrar_logo(config.logotipo_empresa)
                else:
                    self.lbl_logo_preview.clear()
                    self.lbl_logo_preview.setText("Sin Logo")
        except Exception:
            logger.exception("Fallo al cargar la configuración de empresa")
        finally:
            session.close()

    def seleccionar_logo(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Seleccionar Logo", "", "Images (*.png *.jpg *.jpeg)")
        if not file_path:
            return

        try:
            with open(file_path, "rb") as f:
                img_data = f.read()

            # Validar tamaño (opcional, por ej 2MB max)
            if len(img_data) > 2 * 1024 * 1024:
                QMessageBox.warning(self, "Error", "La imagen es muy pesada. Máximo 2MB.")
                return

            # Validar que sea una imagen decodificable ANTES de asignarla a self.logo_bytes
            # -- sin esto, un archivo no-imagen (ej. un .txt renombrado a .png) quedaba
            # asignado igual y se guardaba en la base al pulsar "Guardar", porque
            # _mostrar_logo() solo aborta el *preview* si QImage.fromData() falla, sin
            # impedir el guardado (hallazgo de auditoria, 2026-09-01).
            if QImage.fromData(QByteArray(img_data)).isNull():
                QMessageBox.warning(self, "Archivo inválido", "El archivo seleccionado no es una imagen válida.")
                return

            self.logo_bytes = img_data
            self._mostrar_logo(img_data)
        except Exception:
            logger.exception("Fallo al cargar el archivo de logo '%s'", file_path)
            QMessageBox.warning(self, "Error al cargar logo", "No se pudo leer el archivo seleccionado.")

    def borrar_logo(self) -> None:
        self.logo_bytes = None
        self.lbl_logo_preview.clear()
        self.lbl_logo_preview.setText("Sin Logo")

    def _mostrar_logo(self, img_data: bytes) -> None:
        ba = QByteArray(img_data)
        img = QImage.fromData(ba)
        if not img.isNull():
            pix = QPixmap.fromImage(img).scaled(
                120, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            self.lbl_logo_preview.setPixmap(pix)
            self.lbl_logo_preview.setText("")

    def guardar_cambios(self) -> None:
        session = self.session_factory()
        try:
            EmpresaService.guardar_configuracion(
                session=session,
                rif=self.rif_input.text().strip() or None,
                razon_social=self.nombre_input.text().strip() or None,
                direccion=self.direccion_input.text().strip() or None,
                telefono=self.telefono_input.text().strip() or None,
                logo_bytes=self.logo_bytes,
                pie_pagina=self.footer_input.toPlainText().strip() or None,
                iva_activo=self.iva_activo_check.isChecked(),
                iva_porcentaje=Decimal(str(self.iva_porcentaje_input.value())),
                impresora_predeterminada=self.impresora_combo.currentData(),
                modificado_por=self.usuario.id_usuario,
            )
            QMessageBox.information(self, "Éxito", "Configuración guardada correctamente.")

            # Actualizamos también en la ventana principal (sidebar)
            main_window = self.window()
            if hasattr(main_window, "sidebar"):
                nuevo_nombre = self.nombre_input.text().strip() or "Mi Empresa"
                main_window.sidebar.actualizar_empresa(nuevo_nombre)

            self.logo_bytes = _SENTINEL  # Reset sentinel para no re-guardar

        except PermisoDenegadoError:
            session.rollback()
            QMessageBox.warning(self, "Sin permiso", "No tienes permiso para editar la configuración de empresa.")
        except Exception:
            session.rollback()
            logger.exception("Fallo al guardar la configuración de empresa")
            QMessageBox.critical(self, "Error", "No se pudo guardar la configuración. Intente nuevamente.")
        finally:
            session.close()
