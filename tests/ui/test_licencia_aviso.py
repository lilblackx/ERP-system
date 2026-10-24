"""AvisoLicencia: muestra un dialogo claro al bloquearse una escritura, pero no uno por cada
sentencia bloqueada (un guardado dispara varias seguidas)."""

from app.services.licencia import ESTADO_ACTIVA, ESTADO_REVOCADA, EstadoLicencia
from app.ui import licencia_aviso
from app.ui.licencia_aviso import AvisoLicencia


def test_avisa_una_sola_vez_por_intervalo(qtbot, monkeypatch):
    mostrados = []
    monkeypatch.setattr(licencia_aviso.MessageBox, "warning", lambda parent, titulo, texto: mostrados.append(texto))
    aviso = AvisoLicencia()
    estado = EstadoLicencia(ESTADO_REVOCADA, "Esta licencia fue revocada.")

    aviso.notificar(estado)
    aviso.notificar(estado)
    aviso.notificar(estado)

    assert len(mostrados) == 1
    assert "revocada" in mostrados[0]
    assert "solo lectura" in mostrados[0]


def test_vuelve_a_avisar_pasado_el_intervalo(qtbot, monkeypatch):
    mostrados = []
    monkeypatch.setattr(licencia_aviso.MessageBox, "warning", lambda parent, titulo, texto: mostrados.append(texto))
    aviso = AvisoLicencia()
    estado = EstadoLicencia(ESTADO_REVOCADA, "x")

    aviso.notificar(estado)
    aviso._ultimo_aviso -= licencia_aviso.INTERVALO_ENTRE_AVISOS_SEG + 1
    aviso.notificar(estado)

    assert len(mostrados) == 2


def test_no_apila_avisos_mientras_uno_sigue_abierto(qtbot, monkeypatch):
    """El dialogo es modal: mientras esta abierto los hilos de fondo siguen mandando avisos. Aunque ya haya
    pasado el intervalo, no se abre otro encima (en el servidor se apilaban uno cada 30 s)."""
    mostrados = []
    estado = EstadoLicencia(ESTADO_REVOCADA, "x")

    def _abierto_mucho_rato(parent, titulo, texto):
        mostrados.append(texto)
        aviso._ultimo_aviso -= licencia_aviso.INTERVALO_ENTRE_AVISOS_SEG + 1
        aviso.notificar(estado)  # llega con el dialogo todavia en pantalla

    monkeypatch.setattr(licencia_aviso.MessageBox, "warning", _abierto_mucho_rato)
    aviso = AvisoLicencia()

    aviso.notificar(estado)

    assert len(mostrados) == 1


def test_el_intervalo_cuenta_desde_que_el_usuario_cierra_el_aviso(qtbot, monkeypatch):
    mostrados = []
    estado = EstadoLicencia(ESTADO_REVOCADA, "x")

    def _abierto_mucho_rato(parent, titulo, texto):
        mostrados.append(texto)
        aviso._ultimo_aviso -= licencia_aviso.INTERVALO_ENTRE_AVISOS_SEG + 1  # estuvo abierto mas que el intervalo

    monkeypatch.setattr(licencia_aviso.MessageBox, "warning", _abierto_mucho_rato)
    aviso = AvisoLicencia()

    aviso.notificar(estado)
    aviso.notificar(estado)  # recien cerrado: no vuelve a salir

    assert len(mostrados) == 1


def _despachar_correos_con_licencia(qtbot, monkeypatch, estado: EstadoLicencia) -> dict[str, int]:
    from types import SimpleNamespace

    from app.ui import main_window

    llamadas = {"clave": 0, "smtp": 0, "cola": 0}
    monkeypatch.setattr(main_window.datos_estaciones, "borrar_si_vencido", lambda: None)
    monkeypatch.setattr(main_window.LicenciaService, "estado_actual", staticmethod(lambda: estado))
    monkeypatch.setattr(
        main_window.cifrado_servidor, "asegurar_clave", lambda session: llamadas.update(clave=llamadas["clave"] + 1)
    )
    monkeypatch.setattr(
        main_window.SmtpConfigService, "migrar_password", lambda session: llamadas.update(smtp=llamadas["smtp"] + 1)
    )
    monkeypatch.setattr(
        main_window.CorreoService, "procesar_pendientes", lambda session: llamadas.update(cola=llamadas["cola"] + 1)
    )
    ventana = SimpleNamespace(_worker_correos=None)
    main_window.MainWindow._despachar_correos(ventana)
    qtbot.waitUntil(ventana._worker_correos.isFinished, timeout=3000)
    return llamadas


def test_el_despacho_de_correos_no_escribe_sin_licencia_activa(qtbot, monkeypatch):
    """Sin licencia el gate bloquea la cola y avisaria al usuario en cada pasada (cada 20 s)."""
    llamadas = _despachar_correos_con_licencia(qtbot, monkeypatch, EstadoLicencia(ESTADO_REVOCADA, "x"))
    assert llamadas == {"clave": 0, "smtp": 0, "cola": 0}


def test_el_despacho_de_correos_corre_con_licencia_activa(qtbot, monkeypatch):
    llamadas = _despachar_correos_con_licencia(qtbot, monkeypatch, EstadoLicencia(ESTADO_ACTIVA, "ok"))
    assert llamadas == {"clave": 1, "smtp": 1, "cola": 1}
