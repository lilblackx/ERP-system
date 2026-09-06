import qtawesome as qta
from PySide6.QtCore import QRegularExpression, QSize, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from app.db.models import CategoriaCliente, Cliente, Vendedor
from app.services.rutas import RutaService
from app.ui.mapa_widget import MapaWidget
from app.ui.message_box import MessageBox
from app.ui.styles import (
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_FIELD_BG,
    COLOR_PRIMARY,
    COLOR_PRIMARY_DARK,
    COLOR_PRIMARY_LIGHT,
    COLOR_TABLE_HEADER,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    FONT_FAMILY,
    ICON_CHEVRON_DOWN_URL,
    ICON_CHEVRON_UP_URL,
    aplicar_sombra,
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
QLabel.FormLabel {{
    font-size: 12px;
    font-weight: 600;
    color: #334155;
    margin-bottom: 2px;
}}
QLabel.SectionTitle {{
    font-size: 11px;
    font-weight: bold;
    color: {COLOR_PRIMARY};
    letter-spacing: 0.8px;
    padding-bottom: 2px;
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: #FFFFFF;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 13px;
    color: {COLOR_TEXT_DARK};
    min-height: 20px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1.5px solid {COLOR_PRIMARY};
    background-color: #FFFFFF;
}}
QLineEdit::placeholder {{
    color: #94A3B8;
    font-size: 12px;
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox::down-arrow {{
    image: url({ICON_CHEVRON_DOWN_URL});
    width: 12px;
    height: 12px;
    margin-right: 6px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    border: none;
    border-left: 1px solid {COLOR_BORDER};
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    border: none;
    border-left: 1px solid {COLOR_BORDER};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url({ICON_CHEVRON_UP_URL});
    width: 10px;
    height: 10px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url({ICON_CHEVRON_DOWN_URL});
    width: 10px;
    height: 10px;
}}
QComboBox QAbstractItemView {{
    background-color: #FFFFFF;
    border: 1px solid {COLOR_BORDER};
    selection-background-color: #DBEAFE;
    selection-color: {COLOR_TEXT_DARK};
    padding: 4px;
}}
QPushButton#BtnPrimary {{
    background-color: {COLOR_PRIMARY};
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 8px 22px;
    font-size: 13px;
    font-weight: bold;
}}
QPushButton#BtnPrimary:hover {{
    background-color: {COLOR_PRIMARY_LIGHT};
}}
QPushButton#BtnPrimary:pressed {{
    background-color: {COLOR_PRIMARY_DARK};
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


class ClienteFormDialog(QDialog):
    """
    Diálogo moderno, horizontal y centrado para la creación y edición de clientes.
    Utiliza Font Awesome para todos los íconos y cuenta con selector fiscal (J, G, V, E, P).
    """

    def __init__(self, session: Session, cliente: Cliente | None = None, parent=None):
        super().__init__(parent)
        self.session = session
        self.cliente = cliente
        self.setWindowTitle("Editar Cliente" if cliente else "Nuevo Cliente")
        # Un poco mas ancho/alto que antes (860x740) -- pedido del usuario 2026-09-03:
        # mas area de mapa hace mas facil marcar la ubicacion con precision.
        self.setFixedSize(920, 800)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()

        if cliente:
            self._precargar(cliente)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # ── Encabezado Corporativo ──
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        icon_lbl = QLabel()
        fa_icon_name = "fa5s.user-edit" if self.cliente else "fa5s.user-plus"
        icon_lbl.setPixmap(qta.icon(fa_icon_name, color=COLOR_PRIMARY).pixmap(QSize(22, 22)))
        icon_lbl.setStyleSheet(
            "background-color: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 8px; padding: 6px;"
        )
        icon_lbl.setFixedSize(38, 38)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titles_layout = QVBoxLayout()
        titles_layout.setSpacing(1)
        titles_layout.setContentsMargins(0, 0, 0, 0)

        titulo_text = "Editar Cliente" if self.cliente else "Nuevo Cliente"
        lbl_titulo = QLabel(titulo_text)
        lbl_titulo.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT_DARK};")

        lbl_subtitulo = QLabel("Complete los datos requeridos para registrar la ficha comercial del cliente.")
        lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")

        titles_layout.addWidget(lbl_titulo)
        titles_layout.addWidget(lbl_subtitulo)

        header_layout.addWidget(icon_lbl)
        header_layout.addLayout(titles_layout)
        header_layout.addStretch()

        root.addWidget(header_widget)

        # ── Contenido Horizontal: 2 Columnas de Tarjetas ──
        content_layout = QHBoxLayout()
        content_layout.setSpacing(14)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # ── COLUMNA 1: Datos Generales y Fiscales ──
        card_col1 = QWidget()
        card_col1.setObjectName("SectionCard")
        aplicar_sombra(card_col1)
        col1_layout = QVBoxLayout(card_col1)
        col1_layout.setContentsMargins(16, 12, 16, 14)
        col1_layout.setSpacing(8)

        sec1_title = QLabel("DATOS GENERALES Y FISCALES")
        sec1_title.setProperty("class", "SectionTitle")
        col1_layout.addWidget(sec1_title)

        grid1 = QGridLayout()
        grid1.setSpacing(8)
        grid1.setColumnStretch(0, 1)
        grid1.setColumnStretch(1, 1)

        # Código
        lbl_cod = QLabel("Código <span style='color: #DC2626;'>*</span>")
        lbl_cod.setProperty("class", "FormLabel")
        self.codigo_input = QLineEdit()
        self.codigo_input.setPlaceholderText("Ej: CLI-001")
        self.codigo_input.setMaxLength(20)
        self.codigo_input.setFixedHeight(32)
        grid1.addWidget(lbl_cod, 0, 0)
        grid1.addWidget(self.codigo_input, 1, 0)

        # ID Fiscal
        lbl_id = QLabel("ID Fiscal / Identificación <span style='color: #DC2626;'>*</span>")
        lbl_id.setProperty("class", "FormLabel")
        grid1.addWidget(lbl_id, 0, 1)

        id_hbox = QHBoxLayout()
        id_hbox.setSpacing(4)
        id_hbox.setContentsMargins(0, 0, 0, 0)

        self.tipo_id_combo = QComboBox()
        self.tipo_id_combo.addItems(["J", "G", "V", "E", "P"])
        self.tipo_id_combo.setFixedWidth(52)
        self.tipo_id_combo.setFixedHeight(32)

        self.identificacion_input = QLineEdit()
        self.identificacion_input.setPlaceholderText("Ej: 30489713 / 12345678-0")
        self.identificacion_input.setMaxLength(20)
        self.identificacion_input.setFixedHeight(32)
        # Validador para RIF/Cédula: 1-8 dígitos opcionalmente seguidos de guión y un dígito
        id_validator = QRegularExpressionValidator(QRegularExpression(r"^[0-9]{1,8}(-[0-9])?$"))
        self.identificacion_input.setValidator(id_validator)

        id_hbox.addWidget(self.tipo_id_combo)
        id_hbox.addWidget(self.identificacion_input)
        grid1.addLayout(id_hbox, 1, 1)

        # Razón Social
        lbl_nom = QLabel("Razón Social o Nombre Completo <span style='color: #DC2626;'>*</span>")
        lbl_nom.setProperty("class", "FormLabel")
        self.nombre_input = QLineEdit()
        self.nombre_input.setPlaceholderText("Ej: Distribuidora Central, C.A.")
        self.nombre_input.setMaxLength(200)
        self.nombre_input.setFixedHeight(32)
        grid1.addWidget(lbl_nom, 2, 0, 1, 2)
        grid1.addWidget(self.nombre_input, 3, 0, 1, 2)

        # Vendedor Asignado
        lbl_vend = QLabel("Vendedor Asignado")
        lbl_vend.setProperty("class", "FormLabel")
        self.vendedor_combo = QComboBox()
        self.vendedor_combo.setFixedHeight(32)
        self.vendedor_combo.addItem("Sin asignar", None)
        for vendedor in (
            self.session.query(Vendedor).filter(Vendedor.estado_vendedor == "ACTIVO").order_by(Vendedor.nombre_vendedor)
        ):
            self.vendedor_combo.addItem(vendedor.nombre_vendedor, vendedor.id_vendedor)

        grid1.addWidget(lbl_vend, 4, 0)
        grid1.addWidget(self.vendedor_combo, 5, 0)

        # Categoría
        lbl_cat = QLabel("Categoría de Cliente")
        lbl_cat.setProperty("class", "FormLabel")
        self.categoria_combo = QComboBox()
        self.categoria_combo.setFixedHeight(32)
        self.categoria_combo.addItem("Sin asignar", None)
        for categoria in self.session.query(CategoriaCliente).order_by(CategoriaCliente.nombre):
            self.categoria_combo.addItem(categoria.nombre, categoria.id_categoria_cliente)

        grid1.addWidget(lbl_cat, 4, 1)
        grid1.addWidget(self.categoria_combo, 5, 1)

        col1_layout.addLayout(grid1)
        col1_layout.addStretch()

        # ── COLUMNA 2: Contacto y Condiciones Comerciales ──
        card_col2 = QWidget()
        card_col2.setObjectName("SectionCard")
        aplicar_sombra(card_col2)
        col2_layout = QVBoxLayout(card_col2)
        col2_layout.setContentsMargins(16, 12, 16, 14)
        col2_layout.setSpacing(8)

        sec2_title = QLabel("CONTACTO Y CONDICIONES COMERCIALES")
        sec2_title.setProperty("class", "SectionTitle")
        col2_layout.addWidget(sec2_title)

        grid2 = QGridLayout()
        grid2.setSpacing(8)
        grid2.setColumnStretch(0, 1)
        grid2.setColumnStretch(1, 1)

        # Teléfono
        lbl_tel = QLabel("Teléfono")
        lbl_tel.setProperty("class", "FormLabel")
        self.telefono_input = QLineEdit()
        self.telefono_input.setPlaceholderText("Ej: 0414-1234567")
        self.telefono_input.setMaxLength(20)
        self.telefono_input.setFixedHeight(32)
        grid2.addWidget(lbl_tel, 0, 0)
        grid2.addWidget(self.telefono_input, 1, 0)

        # Email
        lbl_email = QLabel("Correo Electrónico")
        lbl_email.setProperty("class", "FormLabel")
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("Ej: contacto@cliente.com")
        self.email_input.setMaxLength(150)
        self.email_input.setFixedHeight(32)
        # Validador para email: patrón básico user@domain.ext
        email_validator = QRegularExpressionValidator(
            QRegularExpression(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
        )
        self.email_input.setValidator(email_validator)
        grid2.addWidget(lbl_email, 0, 1)
        grid2.addWidget(self.email_input, 1, 1)

        # Dirección
        lbl_dir = QLabel("Dirección Fiscal / Entrega")
        lbl_dir.setProperty("class", "FormLabel")
        self.direccion_input = QLineEdit()
        self.direccion_input.setPlaceholderText("Ej: Av. Principal, Edificio Central, Piso 2")
        self.direccion_input.setMaxLength(255)
        self.direccion_input.setFixedHeight(32)
        grid2.addWidget(lbl_dir, 2, 0, 1, 2)
        grid2.addWidget(self.direccion_input, 3, 0, 1, 2)

        # Límite de Crédito
        lbl_limite = QLabel("Límite de Crédito ($)")
        lbl_limite.setProperty("class", "FormLabel")
        self.limite_credito_input = QDoubleSpinBox()
        self.limite_credito_input.setRange(0, 999999999.99)
        self.limite_credito_input.setDecimals(2)
        self.limite_credito_input.setPrefix("$ ")
        self.limite_credito_input.setFixedHeight(32)
        grid2.addWidget(lbl_limite, 4, 0)
        grid2.addWidget(self.limite_credito_input, 5, 0)

        # Días de Crédito
        lbl_dias = QLabel("Días de Crédito")
        lbl_dias.setProperty("class", "FormLabel")
        self.dias_credito_input = QSpinBox()
        self.dias_credito_input.setRange(0, 365)
        self.dias_credito_input.setSuffix(" días")
        self.dias_credito_input.setFixedHeight(32)
        self.dias_credito_input.setToolTip("0 = cliente de contado, no podrá facturarse a crédito")
        grid2.addWidget(lbl_dias, 4, 1)
        grid2.addWidget(self.dias_credito_input, 5, 1)

        col2_layout.addLayout(grid2)
        col2_layout.addStretch()

        content_layout.addWidget(card_col1, 1)
        content_layout.addWidget(card_col2, 1)

        root.addLayout(content_layout)
        root.addWidget(self._make_card_ubicacion())

        # ── Footer con Botones de Acción ──
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 4, 0, 0)
        footer_layout.setSpacing(10)

        footer_layout.addStretch()

        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.setIcon(qta.icon("fa5s.times", color="#475569"))
        self.btn_cancelar.setObjectName("BtnSecondary")
        self.btn_cancelar.setFixedHeight(36)
        self.btn_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancelar.clicked.connect(self.reject)

        self.btn_guardar = QPushButton("Guardar Cliente")
        self.btn_guardar.setIcon(qta.icon("fa5s.save", color="#FFFFFF"))
        self.btn_guardar.setObjectName("BtnPrimary")
        self.btn_guardar.setFixedHeight(36)
        self.btn_guardar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guardar.clicked.connect(self._validar_y_aceptar)

        footer_layout.addWidget(self.btn_cancelar)
        footer_layout.addWidget(self.btn_guardar)

        root.addLayout(footer_layout)

    def _make_card_ubicacion(self) -> QWidget:
        card = QWidget()
        card.setObjectName("SectionCard")
        # SIN aplicar_sombra() a proposito, a diferencia del resto de las tarjetas de
        # este dialogo: QGraphicsDropShadowEffect (como cualquier QGraphicsEffect) obliga
        # a Qt a renderizar el widget completo -- y todos sus descendientes -- en un
        # buffer offscreen para componer el efecto, pero la ventana nativa de
        # QWebEngineView (el mapa, mas abajo) no se puede capturar asi y directamente
        # deja de pintarse. Diagnosticado 2026-09-01: el mapa cargaba bien
        # (loadFinished=True) pero quedaba completamente en blanco solo dentro de este
        # dialogo -- un test aislado sin esta sombra mostro el mapa perfecto.
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 14)
        card_layout.setSpacing(8)

        titulo = QLabel("UBICACIÓN <span style='color: #DC2626;'>*</span>")
        titulo.setProperty("class", "SectionTitle")
        titulo.setTextFormat(Qt.TextFormat.RichText)
        card_layout.addWidget(titulo)

        contenido = QHBoxLayout()
        contenido.setSpacing(14)

        self.mapa = MapaWidget(editable=True, centrar_en_dispositivo=self.cliente is None)
        self.mapa.setMinimumSize(440, 300)
        self.mapa.coordenadas_cambiadas.connect(self._on_mapa_click)
        contenido.addWidget(self.mapa, 1)

        campos = QVBoxLayout()
        campos.setSpacing(8)

        lbl_lat = QLabel("Latitud <span style='color: #DC2626;'>*</span>")
        lbl_lat.setProperty("class", "FormLabel")
        self.latitud_input = QLineEdit()
        self.latitud_input.setPlaceholderText("Ej: 10.4806")
        self.latitud_input.setFixedHeight(32)
        self.latitud_input.editingFinished.connect(self._on_coordenadas_editadas)

        lbl_lng = QLabel("Longitud <span style='color: #DC2626;'>*</span>")
        lbl_lng.setProperty("class", "FormLabel")
        self.longitud_input = QLineEdit()
        self.longitud_input.setPlaceholderText("Ej: -66.9036")
        self.longitud_input.setFixedHeight(32)
        self.longitud_input.editingFinished.connect(self._on_coordenadas_editadas)

        lbl_ayuda = QLabel("Busca un lugar por nombre, hace click en el mapa o ingresa las coordenadas manualmente.")
        lbl_ayuda.setWordWrap(True)
        lbl_ayuda.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_MUTED};")

        # Sugerencia (no forzada) de vendedor segun la zona de ruta que contiene el punto
        # marcado -- ver _sugerir_vendedor_por_ubicacion(). Oculta hasta que haya una
        # coordenada que evaluar.
        self.lbl_sugerencia_ruta = QLabel()
        self.lbl_sugerencia_ruta.setWordWrap(True)
        self.lbl_sugerencia_ruta.setStyleSheet(f"font-size: 11px; color: {COLOR_PRIMARY}; font-weight: 600;")
        self.lbl_sugerencia_ruta.setVisible(False)

        campos.addWidget(lbl_lat)
        campos.addWidget(self.latitud_input)
        campos.addWidget(lbl_lng)
        campos.addWidget(self.longitud_input)
        campos.addWidget(lbl_ayuda)
        campos.addWidget(self.lbl_sugerencia_ruta)
        campos.addStretch()

        contenido.addLayout(campos, 1)
        card_layout.addLayout(contenido)
        return card

    def _on_mapa_click(self, lat: float, lng: float) -> None:
        self.latitud_input.setText(f"{lat:.7f}")
        self.longitud_input.setText(f"{lng:.7f}")
        self.mapa.set_coordenadas(lat, lng)
        self._sugerir_vendedor_por_ubicacion(lat, lng)

    def _on_coordenadas_editadas(self) -> None:
        lat, lng = self._leer_coordenadas()
        if lat is not None and lng is not None:
            self.mapa.set_coordenadas(lat, lng)
            self._sugerir_vendedor_por_ubicacion(lat, lng)

    def _leer_coordenadas(self) -> tuple[float | None, float | None]:
        lat_texto = self.latitud_input.text().strip()
        lng_texto = self.longitud_input.text().strip()
        if not lat_texto and not lng_texto:
            return None, None
        try:
            return float(lat_texto), float(lng_texto)
        except ValueError:
            return None, None

    def _precargar(self, cliente: Cliente):
        self.codigo_input.setText(cliente.codigo_cliente or "")

        # id_legal contiene solo la letra (V, J, G, E, P)
        # identificacion_cliente contiene solo el número
        prefix = (cliente.id_legal or "").strip().upper() or "V"
        numero = cliente.identificacion_cliente or ""

        idx_pref = self.tipo_id_combo.findText(prefix)
        if idx_pref >= 0:
            self.tipo_id_combo.setCurrentIndex(idx_pref)
        self.identificacion_input.setText(numero)

        self.nombre_input.setText(cliente.nombre_razon_social or "")
        self.telefono_input.setText(cliente.telefono or "")
        self.email_input.setText(cliente.email or "")
        self.direccion_input.setText(cliente.direccion or "")
        self.limite_credito_input.setValue(float(cliente.limite_credito or 0))
        self.dias_credito_input.setValue(cliente.dias_credito or 0)

        idx_vendedor = self.vendedor_combo.findData(cliente.vendedor_cliente)
        self.vendedor_combo.setCurrentIndex(idx_vendedor if idx_vendedor >= 0 else 0)

        idx_categoria = self.categoria_combo.findData(cliente.id_categoria_cliente)
        self.categoria_combo.setCurrentIndex(idx_categoria if idx_categoria >= 0 else 0)

        if cliente.latitud is not None and cliente.longitud is not None:
            lat, lng = float(cliente.latitud), float(cliente.longitud)
            self.latitud_input.setText(f"{lat:.7f}")
            self.longitud_input.setText(f"{lng:.7f}")
            self.mapa.set_coordenadas(lat, lng)
            self._sugerir_vendedor_por_ubicacion(lat, lng)

    def _validar_y_aceptar(self):
        if not self.codigo_input.text().strip():
            MessageBox.warning(self, "Dato requerido", "El código del cliente es obligatorio.")
            self.codigo_input.setFocus()
            return
        if not self.identificacion_input.text().strip():
            MessageBox.warning(self, "Dato requerido", "El número de ID Fiscal / Identificación es obligatorio.")
            self.identificacion_input.setFocus()
            return
        if not self.nombre_input.text().strip():
            MessageBox.warning(self, "Dato requerido", "La razón social o nombre del cliente es obligatoria.")
            self.nombre_input.setFocus()
            return

        lat_texto = self.latitud_input.text().strip()
        lng_texto = self.longitud_input.text().strip()
        if not lat_texto or not lng_texto:
            MessageBox.warning(
                self,
                "Dato requerido",
                "La ubicación es obligatoria. Busca un lugar, hace click en el mapa o ingresa las coordenadas.",
            )
            return
        lat, lng = self._leer_coordenadas()
        if lat is None or lng is None:
            MessageBox.warning(self, "Dato inválido", "La latitud y la longitud deben ser números válidos.")
            return
        if not (-90 <= lat <= 90):
            MessageBox.warning(self, "Dato inválido", "La latitud debe estar entre -90 y 90.")
            return
        if not (-180 <= lng <= 180):
            MessageBox.warning(self, "Dato inválido", "La longitud debe estar entre -180 y 180.")
            return

        self.accept()

    def _sugerir_vendedor_por_ubicacion(self, lat: float, lng: float) -> None:
        """Sugiere (nunca fuerza) el vendedor segun en que zona de ruta cae el punto
        marcado -- decision de negocio 2026-09-03: la asignacion puede ser automatica por
        geografia, pero siempre editable a mano. Solo PRESELECCIONA el combo cuando se
        esta creando un cliente NUEVO y el usuario todavia no eligio vendedor a mano (el
        combo sigue en "Sin asignar") -- en edicion, o si ya se eligio uno, nunca
        reasigna solo: aca solo se actualiza el texto informativo."""
        ruta = RutaService.sugerir_ruta_por_ubicacion(self.session, lat, lng)
        if ruta is None:
            self.lbl_sugerencia_ruta.setVisible(False)
            return

        vendedores_zona = (
            self.session.query(Vendedor)
            .filter(Vendedor.id_ruta == ruta.id_ruta, Vendedor.estado_vendedor == "ACTIVO")
            .order_by(Vendedor.nombre_vendedor)
            .all()
        )
        if len(vendedores_zona) == 1:
            vendedor = vendedores_zona[0]
            self.lbl_sugerencia_ruta.setText(
                f"📍 Dentro de la zona '{ruta.nombre_ruta}' — vendedor sugerido: {vendedor.nombre_vendedor}."
            )
            if self.cliente is None and self.vendedor_combo.currentData() is None:
                idx = self.vendedor_combo.findData(vendedor.id_vendedor)
                if idx >= 0:
                    self.vendedor_combo.setCurrentIndex(idx)
        elif vendedores_zona:
            nombres = ", ".join(v.nombre_vendedor for v in vendedores_zona)
            self.lbl_sugerencia_ruta.setText(
                f"📍 Dentro de la zona '{ruta.nombre_ruta}', con varios vendedores asignados ({nombres}) — elige uno."
            )
        else:
            self.lbl_sugerencia_ruta.setText(
                f"📍 Dentro de la zona '{ruta.nombre_ruta}', sin vendedor asignado todavía."
            )
        self.lbl_sugerencia_ruta.setVisible(True)

    def get_data(self) -> dict:
        tipo = self.tipo_id_combo.currentText().strip()
        num = self.identificacion_input.text().strip()
        lat, lng = self._leer_coordenadas()

        return {
            "codigo_cliente": self.codigo_input.text().strip() or None,
            "id_legal": tipo if tipo else None,
            "identificacion_cliente": num if num else None,
            "nombre_razon_social": self.nombre_input.text().strip(),
            "telefono": self.telefono_input.text().strip() or None,
            "email": self.email_input.text().strip() or None,
            "direccion": self.direccion_input.text().strip() or None,
            "limite_credito": self.limite_credito_input.value(),
            "dias_credito": self.dias_credito_input.value(),
            "vendedor_cliente": self.vendedor_combo.currentData(),
            "id_categoria_cliente": self.categoria_combo.currentData(),
            "latitud": lat,
            "longitud": lng,
        }
