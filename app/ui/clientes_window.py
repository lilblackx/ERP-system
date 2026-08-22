from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import IntegrityError

from app.db.models import Cliente, Usuario
from app.services.clientes import cambiar_estado_cliente, create_cliente, list_clientes, update_cliente
from app.ui.cliente_form_dialog import ClienteFormDialog

COLUMNAS = [
    "ID",
    "Codigo",
    "Identificacion",
    "Razon social",
    "Telefono",
    "Vendedor",
    "Categoria",
    "Limite credito",
    "Estado",
]


class ClientesWindow(QWidget):
    def __init__(self, session_factory, usuario: Usuario):
        super().__init__()
        self.session_factory = session_factory
        self.usuario = usuario
        self.setWindowTitle("Clientes")
        self.resize(900, 500)

        self.buscar_input = QLineEdit()
        self.buscar_input.setPlaceholderText("Buscar por nombre, identificacion o codigo...")
        self.buscar_input.returnPressed.connect(self.cargar_clientes)

        buscar_btn = QPushButton("Buscar")
        buscar_btn.clicked.connect(self.cargar_clientes)

        nuevo_btn = QPushButton("Nuevo")
        nuevo_btn.clicked.connect(self.nuevo_cliente)

        editar_btn = QPushButton("Editar")
        editar_btn.clicked.connect(self.editar_cliente)

        estado_btn = QPushButton("Activar/Desactivar")
        estado_btn.clicked.connect(self.cambiar_estado_cliente_seleccionado)

        botones = QHBoxLayout()
        botones.addWidget(self.buscar_input)
        botones.addWidget(buscar_btn)
        botones.addStretch()
        botones.addWidget(nuevo_btn)
        botones.addWidget(editar_btn)
        botones.addWidget(estado_btn)

        self.tabla = QTableWidget(0, len(COLUMNAS))
        self.tabla.setHorizontalHeaderLabels(COLUMNAS)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tabla.setColumnHidden(0, True)

        layout = QVBoxLayout()
        layout.addLayout(botones)
        layout.addWidget(self.tabla)
        self.setLayout(layout)

        self.cargar_clientes()

    def cargar_clientes(self):
        session = self.session_factory()
        try:
            clientes = list_clientes(
                session, self.buscar_input.text().strip() or None, id_usuario=self.usuario.id_usuario
            )
            self.tabla.setRowCount(len(clientes))
            for fila, cliente in enumerate(clientes):
                valores = [
                    str(cliente.id_cliente),
                    cliente.codigo_cliente or "",
                    cliente.identificacion_cliente or "",
                    cliente.nombre_razon_social,
                    cliente.telefono or "",
                    cliente.vendedor.nombre_vendedor if cliente.vendedor else "",
                    cliente.categoria.nombre if cliente.categoria else "",
                    f"{cliente.limite_credito:,.2f}" if cliente.limite_credito is not None else "0.00",
                    cliente.estado_cliente or "ACTIVO",
                ]
                for columna, valor in enumerate(valores):
                    self.tabla.setItem(fila, columna, QTableWidgetItem(valor))
        except Exception as exc:
            QMessageBox.critical(self, "Error de conexion", str(exc))
        finally:
            session.close()

    def _fila_seleccionada_id(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            QMessageBox.information(self, "Seleccion requerida", "Selecciona un cliente de la lista.")
            return None
        return int(self.tabla.item(filas[0].row(), 0).text())

    def nuevo_cliente(self):
        session = self.session_factory()
        try:
            dialogo = ClienteFormDialog(session)
            if dialogo.exec():
                datos = dialogo.get_data()
                datos["creado_por"] = self.usuario.id_usuario
                create_cliente(session, **datos)
                self.cargar_clientes()
        except IntegrityError:
            session.rollback()
            QMessageBox.warning(self, "Dato duplicado", "El codigo o la identificacion ya estan registrados en otro cliente.")
        except Exception as exc:
            session.rollback()
            QMessageBox.critical(self, "Error", str(exc))
        finally:
            session.close()

    def editar_cliente(self):
        id_cliente = self._fila_seleccionada_id()
        if id_cliente is None:
            return

        session = self.session_factory()
        try:
            cliente = session.get(Cliente, id_cliente)
            dialogo = ClienteFormDialog(session, cliente)
            if dialogo.exec():
                update_cliente(session, id_cliente, id_usuario=self.usuario.id_usuario, **dialogo.get_data())
                self.cargar_clientes()
        except IntegrityError:
            session.rollback()
            QMessageBox.warning(self, "Dato duplicado", "El codigo o la identificacion ya estan registrados en otro cliente.")
        except Exception as exc:
            session.rollback()
            QMessageBox.critical(self, "Error", str(exc))
        finally:
            session.close()

    def cambiar_estado_cliente_seleccionado(self):
        id_cliente = self._fila_seleccionada_id()
        if id_cliente is None:
            return

        session = self.session_factory()
        try:
            cliente = session.get(Cliente, id_cliente)
            estado_actual = cliente.estado_cliente or "ACTIVO"
            nuevo_estado = "INACTIVO" if estado_actual == "ACTIVO" else "ACTIVO"

            respuesta = QMessageBox.question(
                self, "Confirmar", f"Cambiar el estado del cliente a {nuevo_estado}?"
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return

            cambiar_estado_cliente(session, id_cliente, nuevo_estado, id_usuario=self.usuario.id_usuario)
            self.cargar_clientes()
        except Exception as exc:
            session.rollback()
            QMessageBox.critical(self, "Error", str(exc))
        finally:
            session.close()
