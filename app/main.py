import sys
from pathlib import Path

# Agregar la raíz del proyecto (ERP-system) al PYTHONPATH para permitir ejecución directa
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from app.config import validar_configuracion
from app.db.migrar import verificar_migraciones_al_dia
from app.logging_config import setup_logging
from app.ui.login_window import LoginWindow
from app.ui.main_window import MainWindow


def main():
    setup_logging()
    validar_configuracion()
    verificar_migraciones_al_dia()
    app = QApplication(sys.argv)

    while True:
        login = LoginWindow()
        if login.exec() != LoginWindow.DialogCode.Accepted:
            break

        window = MainWindow(login.usuario_autenticado)
        # Maximizada al abrir (pedido del usuario, 2026-08-27): evita problemas de
        # resolucion -- usa siempre el espacio disponible real de la pantalla en vez de
        # depender del tamaño fijo de MainWindow.resize(1200, 720), que en monitores mas
        # chicos podia dejar la ventana con menos espacio del ideal y en monitores mas
        # grandes la dejaba con bordes muertos alrededor. setMinimumSize(900, 600) sigue
        # protegiendo el piso si el usuario la restaura/desmaximiza a mano.
        window.showMaximized()
        app.exec()

    sys.exit(0)


if __name__ == "__main__":
    main()
