import logging
import os
import sys
from pathlib import Path

# Debe fijarse ANTES de importar cualquier modulo Qt: los imports de mas abajo (via
# LoginWindow/MainWindow -> ClienteFormDialog/RutaFormDialog -> mapa_widget.py) ya
# arrastran PySide6.QtWebEngineWidgets transitivamente, y este flag se lee al
# inicializar ese modulo.
#
# 2026-09-01: REVERTIDO el intento de forzar `--use-gl=swiftshader` -- el propio
# Chromium de este build lo rechazo en consola ("is not supported with the current
# configuration") y cerro la app entera. Este build de QtWebEngine no trae ese backend
# ANGLE compilado; forzarlo es peor que el problema original. `--disable-gpu` solo NO
# crashea (confirmado) aunque tampoco alcanzo por si solo para que el mapa pinte -- ver
# el fix real en app/ui/mapa_widget.py (WA_DontCreateNativeAncestors, el ancestro con
# `border-radius` es la sospecha principal ahora, no la GPU).
#
# 2026-09-01: TAMBIEN PROBADO Y REVERTIDO `--in-process-gpu` (sumado a --disable-gpu) --
# la idea era evitar el parpadeo de toda la ventana que se ve la primera vez que se crea
# un QWebEngineView en el proceso (Chromium falla al negociar un contexto compartido con
# la ventana principal, "Failed to create shared context for virtualization" en los
# logs). Confirmado en la maquina real del usuario: el parpadeo sigue igual con el flag
# puesto, asi que no aporta nada -- se saca para no cargar un flag sin efecto. El
# parpadeo en si no es un crash (confirmado, la app sigue funcionando bien despues) y
# solo pasa una vez por sesion, la primera vez que se abre una pantalla con mapa --
# tratado como una limitacion conocida de esta maquina/driver, no como bug pendiente.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

# Agregar la raíz del proyecto (ERP-system) al PYTHONPATH para permitir ejecución directa
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from app.config import validar_configuracion
from app.db.migrar import verificar_migraciones_al_dia
from app.logging_config import setup_logging
from app.ui.geo_http import esperar_workers_pendientes
from app.ui.login_window import LoginWindow
from app.ui.main_window import MainWindow
from app.ui.message_box import MessageBox
from app.ui.styles import COLOR_TEXT_DARK, GLOBAL_QSS, generar_iconos_qss


def _manejar_excepcion_no_capturada(tipo, valor, tb):
    """P-01: sin esto, una excepcion no capturada en un slot de Qt tira la app entera
    al escritorio sin quedar en log -- solo QueryWorker.run() capturaba errores hasta
    ahora, y solo lo que pasaba por ahi."""
    logging.getLogger(__name__).critical("Excepcion no capturada", exc_info=(tipo, valor, tb))
    sys.__excepthook__(tipo, valor, tb)
    if QApplication.instance() is not None:
        MessageBox.critical(
            None,
            "Error inesperado",
            "Ocurrio un error inesperado. Revise logs/app.log o contacte a soporte.",
        )


def main():
    setup_logging()
    sys.excepthook = _manejar_excepcion_no_capturada
    validar_configuracion()
    verificar_migraciones_al_dia()
    # Requisito documentado de Qt/PySide6 para QWebEngineView (app/ui/mapa_widget.py,
    # 2026-09-01): sin este atributo fijado ANTES de crear QApplication, el mapa puede
    # renderizar en blanco en Windows (el contexto OpenGL del widget no queda compartido
    # con el compositor de Chromium) -- hallazgo real, no un caso hipotetico.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    # QToolTip es una ventana emergente aparte, no un hijo normal del widget que la
    # dispara -- fijar GLOBAL_QSS solo en MainWindow.setStyleSheet() (como se hacia antes)
    # no le llega de forma confiable, y el tooltip caia al estilo nativo de Windows
    # (fondo claro sin el texto/color definidos aca, casi ilegible). Fijarlo tambien a
    # nivel QApplication garantiza que cualquier tooltip de la app -- LoginWindow incluida,
    # que ni siquiera es hija de MainWindow -- se vea consistente.
    app.setStyleSheet(GLOBAL_QSS)
    # El QSS de arriba (regla `QToolTip {...}`) no alcanza por si solo en Windows 11: el
    # estilo nativo "windows11" de Qt6 no respeta background-color/color en el tooltip via
    # stylesheet (reportado por el usuario, 2026-09-08 -- seguia ilegible incluso despues
    # de reiniciar la app con el fix de arriba ya aplicado). El tooltip SI respeta la
    # paleta (QPalette.ToolTip*), asi que se fija tambien de forma explicita como refuerzo.
    paleta = app.palette()
    paleta.setColor(QPalette.ColorRole.ToolTipBase, QColor(COLOR_TEXT_DARK))
    paleta.setColor(QPalette.ColorRole.ToolTipText, QColor("white"))
    app.setPalette(paleta)
    # Ver app/ui/geo_http.py::esperar_workers_pendientes -- evita que cerrar la app
    # mientras una busqueda/geolocalizacion en el mapa sigue en vuelo destruya un QThread
    # todavia corriendo (fatal en Qt).
    app.aboutToQuit.connect(esperar_workers_pendientes)
    # qtawesome necesita una QApplication ya creada para renderizar el PNG que usan las
    # flechas de QComboBox/QDateEdit (GLOBAL_QSS y los QSS locales de los dialogos) --
    # ver el comentario junto a generar_iconos_qss() en app/ui/styles.py.
    generar_iconos_qss()

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
