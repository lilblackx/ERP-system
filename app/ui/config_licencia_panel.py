"""
Pestaña "Licencia" del módulo Configuración: muestra el estado de la licencia, deja
activar una clave y forzar una validación en línea. La lógica vive en
app/services/licencia.py; esto es solo presentación. Activar/validar hablan con la red,
así que corren en un QueryWorker para no congelar la ventana (mismo motivo que el resto
de la app, ver app/ui/workers.py).

Estructura (de lo que se mira siempre a lo que casi nunca se toca): título con el estado como
etiqueta, aviso (solo si hay algo que avisar), resumen (cliente / plan / vence), este equipo,
estaciones y, plegado, el formulario para renovar o cambiar la licencia.
"""

import logging
from datetime import date, datetime

import qtawesome as qta
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.db.models import Rol, Usuario
from app.services.licencia import (
    ESTADO_ACTIVA,
    ESTADO_SIN_LICENCIA,
    EstadoLicencia,
    LicenciaService,
    hw_id,
)
from app.services.notificaciones import DIAS_AVISO_LICENCIA
from app.ui.message_box import MessageBox
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_DANGER_BG,
    COLOR_INFO_BG,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_SUCCESS_BG,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
    aplicar_sombra,
)
from app.ui.workers import QueryWorker

logger = logging.getLogger(__name__)

_FONDO_ADVERTENCIA = "#FEF3C7"

# Etiqueta corta junto al titulo (antes era un encabezado verde grande que repetia el mensaje).
_ETIQUETAS_ESTADO = {
    "ACTIVA": "Activa",
    "SIN_LICENCIA": "Sin licencia",
    "VENCIDA": "Vencida",
    "REVOCADA": "Revocada",
    "VALIDAR_EN_LINEA": "Validación pendiente",
    "INVALIDA": "No válida",
    "LIMITE_ESTACIONES": "Límite de estaciones",
}

NIVEL_OK = "ok"
NIVEL_ADVERTENCIA = "advertencia"
NIVEL_PELIGRO = "peligro"
_COLOR_NIVEL = {NIVEL_OK: COLOR_SUCCESS, NIVEL_ADVERTENCIA: COLOR_WARNING, NIVEL_PELIGRO: COLOR_DANGER}
_FONDO_NIVEL = {NIVEL_OK: COLOR_SUCCESS_BG, NIVEL_ADVERTENCIA: _FONDO_ADVERTENCIA, NIVEL_PELIGRO: COLOR_DANGER_BG}


def color_estado(estado: str) -> str:
    if estado == ESTADO_ACTIVA:
        return COLOR_SUCCESS
    if estado in (ESTADO_SIN_LICENCIA, "VALIDAR_EN_LINEA"):
        return COLOR_WARNING
    return COLOR_DANGER


def nivel_estado(estado: str) -> str:
    if estado == ESTADO_ACTIVA:
        return NIVEL_OK
    if estado in (ESTADO_SIN_LICENCIA, "VALIDAR_EN_LINEA"):
        return NIVEL_ADVERTENCIA
    return NIVEL_PELIGRO


def _formato_fecha(valor) -> str:
    return valor.strftime("%d/%m/%Y") if valor else "—"


def _plural_dias(n: int) -> str:
    return f"{n} día" if n == 1 else f"{n} días"


def describir_vencimiento(expira: datetime | date | None, hoy: date | None = None) -> tuple[str, str]:
    """(texto, nivel) para la linea bajo la fecha de vencimiento: "vence mañana", "en 40 días"...
    El nivel pasa a advertencia dentro de DIAS_AVISO_LICENCIA dias (mismo umbral que la campana)."""
    if expira is None:
        return "Sin vencimiento", NIVEL_OK
    hoy = hoy or date.today()
    fecha = expira.date() if isinstance(expira, datetime) else expira
    dias = (fecha - hoy).days
    if dias < 0:
        return f"Vencida hace {_plural_dias(-dias)}", NIVEL_PELIGRO
    if dias == 0:
        return "Vence hoy", NIVEL_PELIGRO
    if dias == 1:
        return "Vence mañana", NIVEL_ADVERTENCIA
    if dias <= DIAS_AVISO_LICENCIA:
        return f"Vence en {_plural_dias(dias)}", NIVEL_ADVERTENCIA
    return f"Faltan {_plural_dias(dias)}", NIVEL_OK


def texto_aviso(estado: EstadoLicencia, hoy: date | None = None) -> tuple[str, str]:
    """(texto, nivel) del aviso bajo el titulo, o ("", ...) si no hay nada que avisar.
    Con la licencia activa y lejos de vencer, el mensaje del servicio ("Licencia activa.") solo
    repetiria la etiqueta de estado, asi que no se muestra."""
    if estado.estado == ESTADO_ACTIVA:
        texto, nivel = describir_vencimiento(estado.expira, hoy)
        if nivel in (NIVEL_ADVERTENCIA, NIVEL_PELIGRO):
            return f"{texto}. Renueva la licencia para no perder la posibilidad de registrar operaciones.", nivel
        mensaje = (estado.mensaje or "").strip()
        if mensaje.rstrip(".").lower() in ("", "licencia activa"):
            return "", NIVEL_OK
        return mensaje, NIVEL_OK
    return (estado.mensaje or _ETIQUETAS_ESTADO.get(estado.estado, estado.estado)), nivel_estado(estado.estado)


def _chip(texto: str, color: str, fondo: str) -> QLabel:
    etiqueta = QLabel(texto)
    etiqueta.setStyleSheet(
        f"color: {color}; background-color: {fondo}; border: none; border-radius: 10px;"
        " padding: 2px 10px; font-size: 11px; font-weight: bold;"
    )
    etiqueta.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return etiqueta


def _subtitulo(texto: str) -> QLabel:
    etiqueta = QLabel(texto.upper())
    etiqueta.setStyleSheet(
        f"color: {COLOR_TEXT_MUTED}; font-size: 11px; font-weight: bold; letter-spacing: 0.5px;"
        " border: none; background: transparent;"
    )
    return etiqueta


class LicenciaPanel(QWidget):
    """Emite `estado_cambiado` tras activar/validar, para que MainWindow refresque su
    banner de solo lectura sin esperar al siguiente chequeo periódico."""

    estado_cambiado = Signal(object)

    def __init__(self, session_factory, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.usuario = usuario
        self._worker: QueryWorker | None = None
        self._es_estacion = config.MODO_INSTALACION == "ESTACION"
        self.setObjectName("ContentArea")
        self._build_ui()
        self.refrescar()

    # ── UI ──────────────────────────────────────────────────────────────────

    def _tarjeta(self, titulo: str | None = None) -> tuple[QFrame, QVBoxLayout, QHBoxLayout | None]:
        """Tarjeta con borde y sombra suave; devuelve (tarjeta, layout del cuerpo, fila del encabezado)."""
        tarjeta = QFrame()
        tarjeta.setObjectName("TarjetaLicencia")
        tarjeta.setStyleSheet(f"""
            QFrame#TarjetaLicencia {{
                background-color: {COLOR_CARD_BG};
                border: 1px solid {COLOR_BORDER};
                border-radius: 12px;
            }}
        """)
        aplicar_sombra(tarjeta)
        cuerpo = QVBoxLayout(tarjeta)
        cuerpo.setContentsMargins(24, 20, 24, 20)
        cuerpo.setSpacing(14)
        encabezado = None
        if titulo:
            encabezado = QHBoxLayout()
            encabezado.setSpacing(10)
            etiqueta = QLabel(titulo)
            etiqueta.setStyleSheet(
                f"font-size: 14px; font-weight: bold; color: {COLOR_TEXT_DARK}; border: none; background: transparent;"
            )
            encabezado.addWidget(etiqueta)
            encabezado.addStretch()
            cuerpo.addLayout(encabezado)
        return tarjeta, cuerpo, encabezado

    def _dato(self, titulo: str) -> tuple[QWidget, QLabel, QLabel]:
        """Una columna del resumen: etiqueta pequeña, valor grande y una linea de detalle."""
        caja = QWidget()
        caja.setStyleSheet("background: transparent;")
        v = QVBoxLayout(caja)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        valor = QLabel("—")
        valor.setStyleSheet(
            f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT_DARK}; border: none; background: transparent;"
        )
        detalle = QLabel("")
        detalle.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED}; border: none; background: transparent;")
        v.addWidget(_subtitulo(titulo))
        v.addWidget(valor)
        v.addWidget(detalle)
        return caja, valor, detalle

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        root.addWidget(scroll)

        contenido = QWidget()
        contenido.setObjectName("LicenciaContenido")
        contenido.setStyleSheet("QWidget#LicenciaContenido { background: transparent; }")
        scroll.setWidget(contenido)
        layout = QVBoxLayout(contenido)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)

        # ── Titulo + estado como etiqueta ───────────────────────────────────
        fila_titulo = QHBoxLayout()
        fila_titulo.setSpacing(12)
        titulo = QLabel("Licencia")
        titulo.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {COLOR_TEXT_DARK}; border: none; background: transparent;"
        )
        self.lbl_estado = QLabel()
        fila_titulo.addWidget(titulo)
        fila_titulo.addWidget(self.lbl_estado)
        fila_titulo.addStretch()
        layout.addLayout(fila_titulo)

        # ── Aviso (solo si hay algo que avisar) ─────────────────────────────
        self.lbl_aviso = QLabel()
        self.lbl_aviso.setWordWrap(True)
        self.lbl_aviso.hide()
        layout.addWidget(self.lbl_aviso)

        # ── Resumen: cliente / plan / vence ─────────────────────────────────
        tarjeta_resumen, cuerpo_resumen, _ = self._tarjeta()
        fila_resumen = QHBoxLayout()
        fila_resumen.setSpacing(24)
        caja_cliente, self.lbl_cliente, _ = self._dato("Cliente")
        caja_plan, self.lbl_plan, _ = self._dato("Plan")
        caja_vence, self.lbl_vence, self.lbl_vence_detalle = self._dato("Vence")
        for caja in (caja_cliente, caja_plan, caja_vence):
            fila_resumen.addWidget(caja, stretch=1)
        cuerpo_resumen.addLayout(fila_resumen)
        layout.addWidget(tarjeta_resumen)

        # ── Este equipo ─────────────────────────────────────────────────────
        tarjeta_equipo, cuerpo_equipo, _ = self._tarjeta("Este equipo")
        fila_rol = QHBoxLayout()
        fila_rol.setSpacing(10)
        self.lbl_rol_chip = _chip("ESTACIÓN" if self._es_estacion else "SERVIDOR", COLOR_PRIMARY, COLOR_INFO_BG)
        self.lbl_rol = QLabel(
            "La licencia la gestiona el servidor."
            if self._es_estacion
            else "Activa y renueva la licencia de toda la red."
        )
        self.lbl_rol.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 13px; border: none; background: transparent;"
        )
        fila_rol.addWidget(self.lbl_rol_chip)
        fila_rol.addWidget(self.lbl_rol)
        fila_rol.addStretch()
        cuerpo_equipo.addLayout(fila_rol)

        # ID de este equipo: el proveedor lo necesita para "liberar" la licencia si el
        # cliente cambia de PC o reinstala Windows.
        fila_id = QHBoxLayout()
        fila_id.setSpacing(10)
        lbl_id = QLabel("ID del equipo")
        lbl_id.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px; border: none; background: transparent;")
        self.lbl_id_equipo = QLabel(f"{hw_id()[:16]}…")
        self.lbl_id_equipo.setToolTip(hw_id())
        self.lbl_id_equipo.setStyleSheet(
            f"color: {COLOR_TEXT_DARK}; font-family: Consolas, 'Courier New', monospace; font-size: 13px;"
            " border: none; background: transparent;"
        )
        btn_copiar = QPushButton(" Copiar")
        btn_copiar.setIcon(qta.icon("fa5s.copy", color=COLOR_TEXT_MUTED))
        btn_copiar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_copiar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copiar.clicked.connect(lambda: QGuiApplication.clipboard().setText(hw_id()))
        fila_id.addWidget(lbl_id)
        fila_id.addWidget(self.lbl_id_equipo)
        fila_id.addWidget(btn_copiar)
        fila_id.addStretch()
        cuerpo_equipo.addLayout(fila_id)
        layout.addWidget(tarjeta_equipo)

        # ── Estaciones ──────────────────────────────────────────────────────
        self.tarjeta_estaciones, cuerpo_estaciones, encabezado_estaciones = self._tarjeta("Estaciones")
        self.lbl_cuenta_estaciones = QLabel()
        encabezado_estaciones.insertWidget(1, self.lbl_cuenta_estaciones)
        self.filas_estaciones = QVBoxLayout()
        self.filas_estaciones.setSpacing(0)
        cuerpo_estaciones.addLayout(self.filas_estaciones)
        self.lbl_nota_estaciones = QLabel()
        self.lbl_nota_estaciones.setWordWrap(True)
        self.lbl_nota_estaciones.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 12px; border: none; background: transparent;"
        )
        cuerpo_estaciones.addWidget(self.lbl_nota_estaciones)
        layout.addWidget(self.tarjeta_estaciones)

        # ── Renovar o cambiar la licencia (plegado) ─────────────────────────
        self.btn_renovar = QPushButton()
        self.btn_renovar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_renovar.setFlat(True)
        self.btn_renovar.setStyleSheet(f"""
            QPushButton {{
                color: {COLOR_PRIMARY}; font-size: 13px; font-weight: 600; text-align: left;
                border: none; background: transparent; padding: 4px 0;
            }}
            QPushButton:hover {{ color: {COLOR_TEXT_DARK}; }}
        """)
        self.btn_renovar.clicked.connect(lambda: self._plegar_renovacion(self.panel_renovar.isVisible()))
        layout.addWidget(self.btn_renovar)

        self.panel_renovar, cuerpo_renovar, _ = self._tarjeta()
        self.lbl_clave = QLabel("Clave de licencia")
        self.lbl_clave.setStyleSheet(
            f"font-weight: bold; color: {COLOR_TEXT_DARK}; font-size: 13px; border: none; background: transparent;"
        )
        cuerpo_renovar.addWidget(self.lbl_clave)

        self.clave_input = QLineEdit()
        self.clave_input.setPlaceholderText("XXXXX-XXXXX-XXXXX-XXXXX")
        self.clave_input.setMinimumHeight(38)
        self.clave_input.setStyleSheet(f"""
            QLineEdit {{
                border: 1px solid {COLOR_BORDER};
                border-radius: 6px;
                padding: 0 12px;
                font-size: 14px;
            }}
            QLineEdit:focus {{ border: 1px solid {COLOR_PRIMARY}; }}
        """)
        self.clave_input.returnPressed.connect(self._activar)
        cuerpo_renovar.addWidget(self.clave_input)
        cuerpo_renovar.addSpacing(10)  # aire entre la clave y los botones

        botones = QHBoxLayout()
        botones.setSpacing(12)
        self.btn_validar = QPushButton("Validar ahora")
        self.btn_validar.setStyleSheet(BUTTON_SECONDARY_QSS)
        self.btn_validar.setMinimumHeight(44)
        self.btn_validar.clicked.connect(self._validar)
        self.btn_activar = QPushButton("Activar licencia")
        self.btn_activar.setStyleSheet(BUTTON_PRIMARY_QSS)
        self.btn_activar.setMinimumHeight(44)
        self.btn_activar.setMinimumWidth(200)
        self.btn_activar.clicked.connect(self._activar)
        botones.addStretch()
        botones.addWidget(self.btn_validar)
        botones.addWidget(self.btn_activar)
        cuerpo_renovar.addLayout(botones)
        layout.addWidget(self.panel_renovar)
        layout.addStretch()

        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

        # Una estacion no activa ni renueva nada: solo relee el estado desde el servidor, asi que
        # no hay formulario que plegar: queda unicamente el boton, siempre visible.
        if self._es_estacion:
            self.btn_renovar.setVisible(False)
            for control in (self.lbl_clave, self.clave_input, self.btn_activar):
                control.setVisible(False)
            self.btn_validar.setText("Actualizar estado")
            self.panel_renovar.setVisible(True)
            botones.setAlignment(self.btn_validar, Qt.AlignmentFlag.AlignRight)

        # Sin licenciamiento (desarrollo/tests) no hay nada que activar.
        if not LicenciaService.habilitada():
            for control in (self.clave_input, self.btn_activar, self.btn_validar):
                control.setEnabled(False)

    def _plegar_renovacion(self, plegar: bool) -> None:
        """Muestra u oculta el formulario de renovacion (solo servidor)."""
        if self._es_estacion:
            return
        self.panel_renovar.setVisible(not plegar)
        icono = "fa5s.chevron-right" if plegar else "fa5s.chevron-down"
        self.btn_renovar.setIcon(qta.icon(icono, color=COLOR_PRIMARY))
        self.btn_renovar.setText("  Renovar o cambiar licencia")

    # ── Estado ──────────────────────────────────────────────────────────────

    def refrescar(self, estado: EstadoLicencia | None = None) -> None:
        estado = estado or LicenciaService.estado_actual()
        color = color_estado(estado.estado)
        nivel = nivel_estado(estado.estado)
        self.lbl_estado.setText(_ETIQUETAS_ESTADO.get(estado.estado, estado.estado))
        self.lbl_estado.setStyleSheet(
            f"color: {color}; background-color: {_FONDO_NIVEL[nivel]}; border: none; border-radius: 12px;"
            " padding: 4px 14px; font-size: 13px; font-weight: bold;"
        )

        aviso, nivel_aviso = texto_aviso(estado)
        self.lbl_aviso.setVisible(bool(aviso))
        self.lbl_aviso.setText(aviso)
        if aviso:
            self.lbl_aviso.setStyleSheet(
                f"color: {_COLOR_NIVEL[nivel_aviso]}; background-color: {_FONDO_NIVEL[nivel_aviso]};"
                f" border: 1px solid {_COLOR_NIVEL[nivel_aviso]}; border-radius: 8px;"
                " padding: 10px 14px; font-size: 13px; font-weight: 600;"
            )

        self.lbl_cliente.setText(estado.cliente or "—")
        self.lbl_plan.setText((estado.plan or "—").capitalize())
        if estado.expira:
            self.lbl_vence.setText(_formato_fecha(estado.expira))
            texto_vence, nivel_vence = describir_vencimiento(estado.expira)
        else:
            self.lbl_vence.setText("Sin vencimiento" if (estado.plan or estado.cliente) else "—")
            texto_vence, nivel_vence = "", NIVEL_OK
        self.lbl_vence_detalle.setText(texto_vence)
        self.lbl_vence_detalle.setStyleSheet(
            f"font-size: 12px; font-weight: {'bold' if nivel_vence != NIVEL_OK else 'normal'};"
            f" color: {_COLOR_NIVEL[nivel_vence] if nivel_vence != NIVEL_OK else COLOR_TEXT_MUTED};"
            " border: none; background: transparent;"
        )

        self._mostrar_estaciones(estado)
        # El formulario de renovacion se abre solo cuando hace falta (nada activo o por vencer).
        necesita_accion = estado.estado != ESTADO_ACTIVA or nivel_aviso != NIVEL_OK
        self._plegar_renovacion(plegar=not necesita_accion)

    def _fila_estacion(self, e: dict, limitada: bool, ultima: bool) -> QWidget:
        fila = QWidget()
        fila.setStyleSheet(
            "background: transparent;" + ("" if ultima else f" border-bottom: 1px solid {COLOR_CONTENT_BG};")
        )
        h = QHBoxLayout(fila)
        h.setContentsMargins(0, 10, 0, 10)
        h.setSpacing(10)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        nombre = QLabel(e["nombre"])
        nombre.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {COLOR_TEXT_DARK}; border: none; background: transparent;"
        )
        uso = QLabel(f"Último uso {e['ultima_vez']:%d/%m/%Y %H:%M}")
        uso.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED}; border: none; background: transparent;")
        textos.addWidget(nombre)
        textos.addWidget(uso)
        h.addLayout(textos)
        h.addStretch()
        if e["esta_pc"]:
            h.addWidget(_chip("Este equipo", COLOR_PRIMARY, COLOR_INFO_BG))
        if limitada:
            if e["autorizada"]:
                h.addWidget(_chip("Con puesto", COLOR_SUCCESS, COLOR_SUCCESS_BG))
            else:
                h.addWidget(_chip("Sin puesto", COLOR_TEXT_MUTED, COLOR_CONTENT_BG))
        return fila

    def _mostrar_estaciones(self, estado: EstadoLicencia) -> None:
        try:
            estaciones = LicenciaService.estaciones_registradas() if LicenciaService.habilitada() else []
        except Exception:
            logger.exception("No se pudieron listar las estaciones")
            estaciones = []
        while self.filas_estaciones.count():
            item = self.filas_estaciones.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.tarjeta_estaciones.setVisible(bool(estaciones))
        if not estaciones:
            return
        limitada = estado.max_estaciones is not None
        con_puesto = sum(1 for e in estaciones if e["autorizada"])
        if limitada:
            # Completo (1 de 1) es normal; ambar solo si hay mas estaciones que puestos.
            excedido = len(estaciones) > estado.max_estaciones
            texto, color, fondo = (
                f"{len(estaciones)} de {estado.max_estaciones}",
                COLOR_WARNING if excedido else COLOR_PRIMARY,
                _FONDO_ADVERTENCIA if excedido else COLOR_INFO_BG,
            )
        else:
            texto, color, fondo = f"{len(estaciones)} registradas", COLOR_PRIMARY, COLOR_INFO_BG
        self.lbl_cuenta_estaciones.setText(texto)
        self.lbl_cuenta_estaciones.setStyleSheet(
            f"color: {color}; background-color: {fondo}; border: none; border-radius: 10px;"
            " padding: 2px 10px; font-size: 11px; font-weight: bold;"
        )
        for i, e in enumerate(estaciones):
            self.filas_estaciones.addWidget(self._fila_estacion(e, limitada, ultima=i == len(estaciones) - 1))
        hay_nota = limitada and con_puesto == 0 and estado.estado == "ACTIVA"
        self.lbl_nota_estaciones.setVisible(hay_nota)
        if hay_nota:
            self.lbl_nota_estaciones.setText("Los puestos se asignan al renovar la licencia (en unos minutos).")

    def _es_admin(self) -> bool:
        session = self.session_factory()
        try:
            rol = session.get(Rol, self.usuario.id_rol) if self.usuario.id_rol is not None else None
            return rol is not None and rol.nombre == "ADMIN"
        finally:
            session.close()

    def _ocupado(self, ocupado: bool) -> None:
        for control in (self.btn_activar, self.btn_validar, self.clave_input):
            control.setEnabled(not ocupado and LicenciaService.habilitada())
        self.btn_activar.setText("Procesando..." if ocupado else "Activar licencia")

    # ── Acciones (en segundo plano) ─────────────────────────────────────────

    def _lanzar(self, tarea, al_terminar, requiere_admin: bool = True) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        if requiere_admin and not self._es_admin():
            MessageBox.warning(self, "Sin permiso", "Solo un administrador puede gestionar la licencia.")
            return
        self._ocupado(True)
        self._worker = QueryWorker(self.session_factory, tarea)
        self._worker.resultado.connect(al_terminar)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _activar(self) -> None:
        clave = self.clave_input.text().strip()
        if not clave:
            MessageBox.warning(self, "Dato requerido", "Ingrese la clave de licencia.")
            return
        self._lanzar(lambda session: LicenciaService.activar(clave), self._on_activada)

    def _validar(self) -> None:
        if self._es_estacion:
            # Cualquier usuario puede refrescar el estado; no toca la red ni cambia nada.
            self._lanzar(lambda session: LicenciaService.refrescar_periodico(), self._on_validada, requiere_admin=False)
            return
        self._lanzar(lambda session: LicenciaService.validar_en_linea(), self._on_validada)

    def _on_activada(self, estado: EstadoLicencia) -> None:
        self._ocupado(False)
        self.clave_input.clear()
        self.refrescar(estado)
        self.estado_cambiado.emit(estado)
        MessageBox.information(self, "Licencia activada", "La licencia se activó correctamente en este equipo.")

    def _on_validada(self, estado: EstadoLicencia) -> None:
        self._ocupado(False)
        self.refrescar(estado)
        self.estado_cambiado.emit(estado)

    def _on_error(self, mensaje: str) -> None:
        # QueryWorker solo pasa str(excepcion): los LicenciaError ya traen un texto
        # pensado para el usuario; cualquier otro error inesperado ya quedo en el log.
        self._ocupado(False)
        titulo = "Sin conexión" if "conectar" in mensaje or "servidor de licencias" in mensaje else "Licencia"
        MessageBox.warning(self, titulo, mensaje or "No se pudo completar la operación.")
        self.refrescar()
