import sys
from pathlib import Path

# Agregar la raíz del proyecto (ERP-system) al PYTHONPATH para permitir ejecución directa
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from app.ui.login_window import LoginWindow
from app.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)

    login = LoginWindow()
    if login.exec() != LoginWindow.DialogCode.Accepted:
        sys.exit(0)

    window = MainWindow(login.usuario_autenticado)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
