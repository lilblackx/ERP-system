"""Tests de ConfigSmtpPanel: el usuario solo elige su servicio de correo (Gmail, Outlook,
...) y servidor/puerto/TLS salen del catalogo; solo "Otro" muestra los campos manuales.

SmtpConfigService se monkeypatchea directo (misma razon que test_config_empresa_panel.py):
lo que se prueba aca es el mapeo formulario <-> servicio, no la logica del servicio, que ya
cubre tests/services/test_smtp_config.py."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.smtp_config import PROVEEDOR_OTRO
from app.ui import config_smtp_panel
from app.ui.config_smtp_panel import ConfigSmtpPanel


def _crear_panel(qtbot, monkeypatch, fila=None):
    monkeypatch.setattr(
        config_smtp_panel.SmtpConfigService,
        "obtener_configuracion",
        lambda session, id_usuario=None: fila,
    )
    panel = ConfigSmtpPanel(MagicMock(return_value=MagicMock()), MagicMock(id_usuario=1))
    qtbot.addWidget(panel)
    return panel


def _fila(**overrides):
    datos = {
        "host": "smtp.gmail.com",
        "puerto": 587,
        "usuario": "cuenta@gmail.com",
        "password": "clave-guardada",
        "remitente": None,
        "usar_tls": True,
    }
    datos.update(overrides)
    return SimpleNamespace(**datos)


def _elegir(panel, clave):
    panel.proveedor_combo.setCurrentIndex(panel.proveedor_combo.findData(clave))


def _capturar_guardado(monkeypatch):
    guardados = []
    monkeypatch.setattr(
        config_smtp_panel.SmtpConfigService,
        "guardar_configuracion",
        lambda **kwargs: guardados.append(kwargs),
    )
    monkeypatch.setattr(config_smtp_panel.MessageBox, "information", lambda *a, **k: None)
    return guardados


def _capturar_avisos(monkeypatch):
    avisos = []
    monkeypatch.setattr(config_smtp_panel.MessageBox, "warning", lambda parent, titulo, texto: avisos.append(texto))
    return avisos


def test_sin_configuracion_no_hay_servicio_elegido_ni_campos_manuales(qtbot, monkeypatch):
    panel = _crear_panel(qtbot, monkeypatch, fila=None)

    assert panel.proveedor_combo.currentData() is None
    assert panel.avanzado.isHidden()


def test_el_selector_ofrece_gmail_outlook_y_otro(qtbot, monkeypatch):
    panel = _crear_panel(qtbot, monkeypatch)

    nombres = [panel.proveedor_combo.itemText(i) for i in range(panel.proveedor_combo.count())]
    assert "Gmail" in nombres
    assert "Outlook / Hotmail" in nombres
    assert panel.proveedor_combo.findData(PROVEEDOR_OTRO) >= 0


def test_elegir_un_servicio_muestra_su_ayuda_y_oculta_lo_manual(qtbot, monkeypatch):
    panel = _crear_panel(qtbot, monkeypatch)

    _elegir(panel, "gmail")

    assert "contraseña de aplicación" in panel.lbl_ayuda.text()
    assert panel.avanzado.isHidden()


def test_elegir_otro_muestra_los_campos_manuales(qtbot, monkeypatch):
    panel = _crear_panel(qtbot, monkeypatch)

    _elegir(panel, PROVEEDOR_OTRO)

    assert not panel.avanzado.isHidden()


def test_guardar_gmail_usa_servidor_y_puerto_del_catalogo(qtbot, monkeypatch):
    panel = _crear_panel(qtbot, monkeypatch)
    guardados = _capturar_guardado(monkeypatch)
    _elegir(panel, "gmail")
    panel.usuario_input.setText("cuenta@gmail.com")
    panel.password_input.setText("abcd efgh ijkl mnop")

    panel.guardar_cambios()

    assert len(guardados) == 1
    assert guardados[0]["host"] == "smtp.gmail.com"
    assert guardados[0]["puerto"] == 587
    assert guardados[0]["usar_tls"] is True
    assert guardados[0]["usuario"] == "cuenta@gmail.com"
    assert guardados[0]["password"] == "abcd efgh ijkl mnop"


def test_guardar_outlook_usa_servidor_del_catalogo(qtbot, monkeypatch):
    panel = _crear_panel(qtbot, monkeypatch)
    guardados = _capturar_guardado(monkeypatch)
    _elegir(panel, "outlook")
    panel.usuario_input.setText("cuenta@outlook.com")
    panel.password_input.setText("clave")

    panel.guardar_cambios()

    assert guardados[0]["host"] == "smtp-mail.outlook.com"
    assert guardados[0]["puerto"] == 587


def test_guardar_otro_usa_los_campos_manuales(qtbot, monkeypatch):
    panel = _crear_panel(qtbot, monkeypatch)
    guardados = _capturar_guardado(monkeypatch)
    _elegir(panel, PROVEEDOR_OTRO)
    panel.host_input.setText("mail.miempresa.com")
    panel.puerto_input.set_value(465)
    panel.remitente_input.setText("no-responder@miempresa.com")
    panel.tls_check.setChecked(False)
    panel.usuario_input.setText("ventas@miempresa.com")
    panel.password_input.setText("clave")

    panel.guardar_cambios()

    assert guardados[0]["host"] == "mail.miempresa.com"
    assert guardados[0]["puerto"] == 465
    assert guardados[0]["usar_tls"] is False
    assert guardados[0]["remitente"] == "no-responder@miempresa.com"


def test_guardar_sin_elegir_servicio_avisa_y_no_guarda(qtbot, monkeypatch):
    panel = _crear_panel(qtbot, monkeypatch)
    guardados = _capturar_guardado(monkeypatch)
    avisos = _capturar_avisos(monkeypatch)
    panel.usuario_input.setText("cuenta@gmail.com")
    panel.password_input.setText("clave")

    panel.guardar_cambios()

    assert guardados == []
    assert avisos == ["Seleccione su servicio de correo."]


def test_guardar_sin_correo_o_sin_clave_avisa_y_no_guarda(qtbot, monkeypatch):
    panel = _crear_panel(qtbot, monkeypatch)
    guardados = _capturar_guardado(monkeypatch)
    avisos = _capturar_avisos(monkeypatch)
    _elegir(panel, "gmail")

    panel.guardar_cambios()  # sin correo
    panel.usuario_input.setText("cuenta@gmail.com")
    panel.guardar_cambios()  # sin contraseña, y no hay una guardada

    assert guardados == []
    assert avisos == ["Ingrese su correo electrónico.", "Ingrese la contraseña de la cuenta de correo."]


def test_configuracion_guardada_de_un_servicio_conocido_se_muestra_como_ese_servicio(qtbot, monkeypatch):
    panel = _crear_panel(qtbot, monkeypatch, fila=_fila())

    assert panel.proveedor_combo.currentData() == "gmail"
    assert panel.usuario_input.text() == "cuenta@gmail.com"
    assert panel.avanzado.isHidden()
    # La clave guardada nunca se muestra.
    assert panel.password_input.text() == ""


def test_configuracion_guardada_de_servidor_propio_se_muestra_como_otro(qtbot, monkeypatch):
    panel = _crear_panel(
        qtbot,
        monkeypatch,
        fila=_fila(host="mail.miempresa.com", puerto=25, usar_tls=False, remitente="yo@miempresa.com"),
    )

    assert panel.proveedor_combo.currentData() == PROVEEDOR_OTRO
    assert not panel.avanzado.isHidden()
    assert panel.host_input.text() == "mail.miempresa.com"
    assert panel.puerto_input.get_value() == 25
    assert panel.remitente_input.text() == "yo@miempresa.com"
    assert not panel.tls_check.isChecked()


def test_guardar_con_clave_ya_guardada_y_campo_vacio_la_conserva(qtbot, monkeypatch):
    panel = _crear_panel(qtbot, monkeypatch, fila=_fila())
    guardados = _capturar_guardado(monkeypatch)
    # guardar_cambios() recarga el formulario: que no pise la fila falsa con otra consulta.
    panel.password_input.clear()

    panel.guardar_cambios()

    assert len(guardados) == 1
    # El sentinel de "no tocar la contraseña", no una cadena vacia que la borraria.
    assert guardados[0]["password"] is config_smtp_panel._SENTINEL
