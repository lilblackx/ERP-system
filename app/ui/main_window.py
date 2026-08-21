from PySide6.QtWidgets import QLabel, QMainWindow

from app.db.models import Usuario
from app.db.session import SessionLocal
from app.ui.clientes_window import ClientesWindow


class MainWindow(QMainWindow):
    def __init__(self, usuario: Usuario):
        super().__init__()
        self.usuario = usuario
        self.setWindowTitle("Distribuidora DJ")
        self.resize(1000, 650)
        self._clientes_window = None

        menubar = self.menuBar()
        menubar.addMenu("Catalogo")

        menu_clientes = menubar.addMenu("Clientes")
        menu_clientes.addAction("Gestionar clientes", self.abrir_clientes)

        menubar.addMenu("Proveedores")
        menubar.addMenu("Ventas")
        menubar.addMenu("Compras")
        menubar.addMenu("Caja y Bancos")
        menubar.addMenu("Reportes")

        rol_nombre = usuario.rol.nombre if usuario.rol else "sin rol"
        bienvenida = QLabel(f"Bienvenido, {usuario.nombre or usuario.nombre_usuario} ({rol_nombre})")
        bienvenida.setContentsMargins(20, 20, 20, 20)
        self.setCentralWidget(bienvenida)

        self.statusBar().showMessage(f"Conectado como {usuario.nombre_usuario}")

    def abrir_clientes(self):
        if self._clientes_window is None:
            self._clientes_window = ClientesWindow(SessionLocal, self.usuario)
        self._clientes_window.show()
        self._clientes_window.raise_()
        self._clientes_window.activateWindow()
