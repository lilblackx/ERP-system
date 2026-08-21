from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)
from sqlalchemy.orm import Session

from app.db.models import CategoriaCliente, Cliente, Vendedor


class ClienteFormDialog(QDialog):
    def __init__(self, session: Session, cliente: Cliente | None = None, parent=None):
        super().__init__(parent)
        self.session = session
        self.cliente = cliente
        self.setWindowTitle("Editar cliente" if cliente else "Nuevo cliente")
        self.setMinimumWidth(400)

        self.codigo_input = QLineEdit()
        self.identificacion_input = QLineEdit()
        self.nombre_input = QLineEdit()
        self.telefono_input = QLineEdit()
        self.email_input = QLineEdit()
        self.direccion_input = QLineEdit()

        self.limite_credito_input = QDoubleSpinBox()
        self.limite_credito_input.setRange(0, 999999999.99)
        self.limite_credito_input.setDecimals(2)

        self.dias_credito_input = QSpinBox()
        self.dias_credito_input.setRange(0, 365)

        self.vendedor_combo = QComboBox()
        self.vendedor_combo.addItem("Sin asignar", None)
        for vendedor in session.query(Vendedor).filter(Vendedor.estado_vendedor == "ACTIVO").order_by(Vendedor.nombre_vendedor):
            self.vendedor_combo.addItem(vendedor.nombre_vendedor, vendedor.id_vendedor)

        self.categoria_combo = QComboBox()
        self.categoria_combo.addItem("Sin asignar", None)
        for categoria in session.query(CategoriaCliente).order_by(CategoriaCliente.nombre):
            self.categoria_combo.addItem(categoria.nombre, categoria.id_categoria_cliente)

        form = QFormLayout()
        form.addRow("Codigo:", self.codigo_input)
        form.addRow("Identificacion:", self.identificacion_input)
        form.addRow("Razon social:*", self.nombre_input)
        form.addRow("Telefono:", self.telefono_input)
        form.addRow("Email:", self.email_input)
        form.addRow("Direccion:", self.direccion_input)
        form.addRow("Limite de credito:", self.limite_credito_input)
        form.addRow("Dias de credito:", self.dias_credito_input)
        form.addRow("Vendedor:", self.vendedor_combo)
        form.addRow("Categoria:", self.categoria_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validar_y_aceptar)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

        if cliente:
            self._precargar(cliente)

    def _precargar(self, cliente: Cliente):
        self.codigo_input.setText(cliente.codigo_cliente or "")
        self.identificacion_input.setText(cliente.identificacion_cliente or "")
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

    def _validar_y_aceptar(self):
        if not self.nombre_input.text().strip():
            QMessageBox.warning(self, "Dato requerido", "La razon social es obligatoria.")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "codigo_cliente": self.codigo_input.text().strip() or None,
            "identificacion_cliente": self.identificacion_input.text().strip() or None,
            "nombre_razon_social": self.nombre_input.text().strip(),
            "telefono": self.telefono_input.text().strip() or None,
            "email": self.email_input.text().strip() or None,
            "direccion": self.direccion_input.text().strip() or None,
            "limite_credito": self.limite_credito_input.value(),
            "dias_credito": self.dias_credito_input.value(),
            "vendedor_cliente": self.vendedor_combo.currentData(),
            "id_categoria_cliente": self.categoria_combo.currentData(),
        }
