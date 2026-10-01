"""
Pestaña "Licencia" del módulo Configuración: muestra el estado de la licencia, deja
activar una clave y forzar una validación en línea. La lógica vive en
app/services/licencia.py; esto es solo presentación. Activar/validar hablan con la red,
así que corren en un QueryWorker para no congelar la ventana (mismo motivo que el resto
de la app, ver app/ui/workers.py).
"""

import logging

from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
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
from app.ui.message_box import MessageBox
from app.ui.styles import (
    BUTTON_PRIMARY_QSS,
    BUTTON_SECONDARY_QSS,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_CONTENT_BG,
    COLOR_DANGER,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
)
from app.ui.workers import QueryWorker

logger = logging.getLogger(__name__)

_TITULOS_ESTADO = {
    "ACTIVA": "Licencia activa",
    "SIN_LICENCIA": "Sin licencia",
    "VENCIDA": "Licencia vencida",
    "REVOCADA": "Licencia revocada",
    "VALIDAR_EN_LINEA": "Validación pendiente",
    "INVALIDA": "Licencia no válida",
    "LIMITE_ESTACIONES": "Límite de estaciones alcanzado",
}


def color_estado(estado: str) -> str:
    if estado == ESTADO_ACTIVA:
        return COLOR_SUCCESS
    if estado in (ESTADO_SIN_LICENCIA, "VALIDAR_EN_LINEA"):
        return COLOR_WARNING
    return COLOR_DANGER


def _formato_fecha(valor) -> str:
    return valor.strftime("%d/%m/%Y") if valor else "—"


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

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 40, 40, 40)

        card = QWidget()
        card.setObjectName("SectionCard")
        card.setStyleSheet(f"""
            QWidget#SectionCard {{
                background-color: {COLOR_CARD_BG};
                border: 1px solid {COLOR_BORDER};
                border-radius: 12px;
            }}
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(16)

        titulo = QLabel("Licencia")
        titulo.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {COLOR_TEXT_DARK}; border: none; background: transparent;"
        )
        layout.addWidget(titulo)

        self.lbl_estado = QLabel()
        layout.addWidget(self.lbl_estado)

        self.lbl_mensaje = QLabel()
        self.lbl_mensaje.setWordWrap(True)
        self.lbl_mensaje.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 13px; background: transparent;")
        layout.addWidget(self.lbl_mensaje)

        self.lbl_detalle = QLabel()
        self.lbl_detalle.setStyleSheet(f"color: {COLOR_TEXT_DARK}; font-size: 14px; background: transparent;")
        layout.addWidget(self.lbl_detalle)

        self.lbl_rol = QLabel(
            "Este equipo: ESTACIÓN — la licencia la gestiona el servidor."
            if self._es_estacion
            else "Este equipo: SERVIDOR — activa y renueva la licencia de toda la red."
        )
        self.lbl_rol.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 13px; background: transparent;")
        layout.addWidget(self.lbl_rol)

        self.lbl_estaciones = QLabel()
        self.lbl_estaciones.setWordWrap(True)
        self.lbl_estaciones.setStyleSheet(f"color: {COLOR_TEXT_DARK}; font-size: 13px; background: transparent;")
        layout.addWidget(self.lbl_estaciones)

        # ID de este equipo: el proveedor lo necesita para "liberar" la licencia si el
        # cliente cambia de PC o reinstala Windows.
        fila_equipo = QHBoxLayout()
        lbl_equipo = QLabel(f"ID de este equipo: {hw_id()[:16]}…")
        lbl_equipo.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px; background: transparent;")
        btn_copiar = QPushButton("Copiar")
        btn_copiar.setStyleSheet(BUTTON_SECONDARY_QSS)
        btn_copiar.clicked.connect(lambda: QGuiApplication.clipboard().setText(hw_id()))
        fila_equipo.addWidget(lbl_equipo)
        fila_equipo.addWidget(btn_copiar)
        fila_equipo.addStretch()
        layout.addLayout(fila_equipo)

        self.lbl_clave = lbl_clave = QLabel("Clave de licencia:")
        lbl_clave.setStyleSheet(
            f"font-weight: bold; color: {COLOR_TEXT_DARK}; font-size: 14px; border: none; background: transparent;"
        )
        layout.addWidget(lbl_clave)

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
        layout.addWidget(self.clave_input)

        botones = QHBoxLayout()
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
        layout.addLayout(botones)
        layout.addStretch()

        root.addWidget(card)
        self.setStyleSheet(f"background-color: {COLOR_CONTENT_BG};")

        # Una estacion no activa ni renueva nada: solo relee el estado desde el servidor.
        if self._es_estacion:
            for control in (self.lbl_clave, self.clave_input, self.btn_activar):
                control.setVisible(False)
            self.btn_validar.setText("Actualizar estado")

        # Sin licenciamiento (desarrollo/tests) no hay nada que activar.
        if not LicenciaService.habilitada():
            for control in (self.clave_input, self.btn_activar, self.btn_validar):
                control.setEnabled(False)

    # ── Estado ──────────────────────────────────────────────────────────────

    def refrescar(self, estado: EstadoLicencia | None = None) -> None:
        estado = estado or LicenciaService.estado_actual()
        color = color_estado(estado.estado)
        self.lbl_estado.setText(_TITULOS_ESTADO.get(estado.estado, estado.estado))
        self.lbl_estado.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {color}; background: transparent;")
        self.lbl_mensaje.setText(estado.mensaje)
        if estado.plan or estado.cliente:
            self.lbl_detalle.setText(
                f"Cliente: {estado.cliente or '—'}    Plan: {estado.plan or '—'}    "
                f"Vence: {_formato_fecha(estado.expira) if estado.expira else 'Sin vencimiento'}"
            )
        else:
            self.lbl_detalle.setText("")
        self._mostrar_estaciones(estado)

    def _mostrar_estaciones(self, estado: EstadoLicencia) -> None:
        try:
            estaciones = LicenciaService.estaciones_registradas() if LicenciaService.habilitada() else []
        except Exception:
            logger.exception("No se pudieron listar las estaciones")
            estaciones = []
        if not estaciones:
            self.lbl_estaciones.setText("")
            return
        limitada = estado.max_estaciones is not None
        con_puesto = sum(1 for e in estaciones if e["autorizada"])
        titulo = (
            f"Estaciones registradas: {len(estaciones)} (la licencia permite {estado.max_estaciones})"
            if limitada
            else f"Estaciones registradas: {len(estaciones)}"
        )
        lineas = [titulo]
        for e in estaciones:
            marca = " (este equipo)" if e["esta_pc"] else ""
            puesto = (" — con puesto" if e["autorizada"] else " — sin puesto") if limitada else ""
            lineas.append(f"•  {e['nombre']}{marca} — último uso {e['ultima_vez']:%d/%m/%Y %H:%M}{puesto}")
        if limitada and con_puesto == 0 and estado.estado == "ACTIVA":
            lineas.append("Los puestos se asignan al renovar la licencia (en unos minutos).")
        self.lbl_estaciones.setText("\n".join(lineas))

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
