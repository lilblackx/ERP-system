"""
Panel para el módulo de Configuración de Empresa.
Permite editar los datos de la empresa (RIF, Nombre, Dirección, Teléfono, Logo).
"""

from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.db.models import Usuario
from app.services.empresa import EmpresaService, _SENTINEL
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_PRIMARY,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
)


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
        
        # Tarjeta principal
        card = QWidget()
        card.setStyleSheet(f"""
            QWidget {{
                background-color: {COLOR_CARD_BG};
                border: 1px solid {COLOR_BORDER};
                border-radius: 12px;
            }}
        """)
        
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 32, 32, 32)
        card_layout.setSpacing(24)
        
        # Título
        lbl_titulo = QLabel("Configuración de la Empresa")
        lbl_titulo.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {COLOR_TEXT_DARK}; border: none;")
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
        lbl_logo_hint.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; border: none;")
        
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
        
        lbl_style = f"font-weight: bold; color: {COLOR_TEXT_DARK}; font-size: 14px; border: none;"
        
        lbl_rif = QLabel("RF Empresa:")
        lbl_rif.setStyleSheet(lbl_style)
        
        lbl_nombre = QLabel("Nombre Empresa:")
        lbl_nombre.setStyleSheet(lbl_style)
        
        lbl_direccion = QLabel("Dirección:")
        lbl_direccion.setStyleSheet(lbl_style)
        
        lbl_telefono = QLabel("Teléfono:")
        lbl_telefono.setStyleSheet(lbl_style)
        
        form.addRow(lbl_rif, self.rif_input)
        form.addRow(lbl_nombre, self.nombre_input)
        form.addRow(lbl_direccion, self.direccion_input)
        form.addRow(lbl_telefono, self.telefono_input)
        
        card_layout.addLayout(form)
        
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
        
        root.addWidget(card)
        root.addStretch()
        
        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

    def cargar_datos(self) -> None:
        session = self.session_factory()
        try:
            config = EmpresaService.obtener_configuracion(session, self.usuario.id_usuario)
            if config:
                self.rif_input.setText(config.rif_empresa or "")
                self.nombre_input.setText(config.razon_social_empresa or "")
                self.direccion_input.setText(config.direccion_empresa or "")
                self.telefono_input.setText(config.telefono_empresa or "")
                
                if config.logotipo_empresa:
                    self._mostrar_logo(config.logotipo_empresa)
                else:
                    self.lbl_logo_preview.clear()
                    self.lbl_logo_preview.setText("Sin Logo")
        except Exception as exc:
            # Si no tiene permiso o error, mostramos en consola/log (o pasamos)
            pass
        finally:
            session.close()

    def seleccionar_logo(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar Logo", "", "Images (*.png *.jpg *.jpeg)"
        )
        if not file_path:
            return
            
        try:
            with open(file_path, "rb") as f:
                img_data = f.read()
                
            # Validar tamaño (opcional, por ej 2MB max)
            if len(img_data) > 2 * 1024 * 1024:
                QMessageBox.warning(self, "Error", "La imagen es muy pesada. Máximo 2MB.")
                return
                
            self.logo_bytes = img_data
            self._mostrar_logo(img_data)
        except Exception as exc:
            QMessageBox.warning(self, "Error al cargar logo", str(exc))
            
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
                modificado_por=self.usuario.id_usuario
            )
            QMessageBox.information(self, "Éxito", "Configuración guardada correctamente.")
            
            # Actualizamos también en la ventana principal (sidebar)
            main_window = self.window()
            if hasattr(main_window, "sidebar"):
                nuevo_nombre = self.nombre_input.text().strip() or "Mi Empresa"
                main_window.sidebar.actualizar_empresa(nuevo_nombre)
                
            self.logo_bytes = _SENTINEL  # Reset sentinel para no re-guardar
            
        except Exception as exc:
            session.rollback()
            QMessageBox.critical(self, "Error", f"No se pudo guardar la configuración:\n{str(exc)}")
        finally:
            session.close()
