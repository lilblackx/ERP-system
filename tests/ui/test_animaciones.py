"""Tests de app/ui/animaciones.py y de lo que se apoya en el: aviso (toast), barra de carga, confirmaciones de
exito de MessageBox, cifras del panel general y boton ocupado.

El conftest de UI deja las animaciones apagadas; los tests que prueban el movimiento las encienden con
animaciones.forzar(True). Las esperas son por estado final (qtbot.waitUntil), nunca por tiempo fijo."""

import pytest
from PySide6.QtCore import QAbstractAnimation, QPoint, Qt
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QWidget

from app.ui import animaciones, message_box, toast
from app.ui.animaciones import (
    FiltroFundidoDialogos,
    animar_propiedad,
    contar,
    destello,
    destello_fila,
    fundido_entrada,
    liberar_boton,
    marcar_error,
    ocupar_boton,
    sacudir,
)
from app.ui.carga import BarraCarga, GestorActividad
from app.ui.dashboard_panel import KpiCard, VentasSemanaChart, _parsear_cifra
from app.ui.toast import Toast, es_confirmacion_de_exito


def _esperar_sin_animaciones(qtbot, widget):
    """Espera a que no quede ninguna animacion corriendo bajo `widget`: si el test termina antes, qtbot destruye el
    widget con la animacion a medias (cierre inestable)."""
    qtbot.waitUntil(
        lambda: not any(a.state() == QAbstractAnimation.State.Running for a in widget.findChildren(QAbstractAnimation)),
        timeout=3000,
    )


# ── Interruptor general ─────────────────────────────────────────────────────


def test_sin_animaciones_aplica_el_estado_final_de_inmediato(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)
    llamado = []
    assert animar_propiedad(widget, b"windowOpacity", 0.0, 0.5, al_terminar=lambda: llamado.append(1)) is None
    assert widget.windowOpacity() == pytest.approx(0.5, abs=0.01)
    assert llamado == [1]


def test_el_interruptor_se_apaga_por_variable_de_entorno(monkeypatch):
    animaciones.forzar(None)
    monkeypatch.setattr(animaciones, "_sesion_remota_cache", False)
    monkeypatch.delenv("NEXO_SIN_ANIMACIONES", raising=False)
    assert animaciones.animaciones_activas() is True
    monkeypatch.setenv("NEXO_SIN_ANIMACIONES", "1")
    assert animaciones.animaciones_activas() is False


def test_el_interruptor_se_apaga_en_escritorio_remoto(monkeypatch):
    animaciones.forzar(None)
    monkeypatch.delenv("NEXO_SIN_ANIMACIONES", raising=False)
    monkeypatch.setattr(animaciones, "_sesion_remota_cache", True)
    assert animaciones.animaciones_activas() is False


def test_la_preferencia_reducir_animaciones_se_guarda_y_apaga_el_interruptor(monkeypatch, tmp_path):
    animaciones.forzar(None)
    monkeypatch.delenv("NEXO_SIN_ANIMACIONES", raising=False)
    monkeypatch.setattr(animaciones, "_sesion_remota_cache", False)
    archivo = tmp_path / "prefs.json"
    animaciones.establecer_reducir_animaciones(True, archivo)
    assert animaciones.animaciones_activas() is False
    assert animaciones._leer_preferencias(archivo) == {"reducir_animaciones": True}
    animaciones.establecer_reducir_animaciones(False, archivo)
    assert animaciones.animaciones_activas() is True


def test_archivo_de_preferencias_ilegible_no_rompe(tmp_path):
    archivo = tmp_path / "prefs.json"
    archivo.write_text("{ esto no es json", encoding="utf-8")
    assert animaciones._leer_preferencias(archivo) == {}


# ── Primitivas con animacion encendida ──────────────────────────────────────


def test_fundido_entrada_termina_con_opacidad_completa(qtbot):
    animaciones.forzar(True)
    dialogo = QDialog()
    qtbot.addWidget(dialogo)
    fundido_entrada(dialogo, ms=30)
    assert dialogo.windowOpacity() < 1.0
    qtbot.waitUntil(lambda: dialogo.windowOpacity() == 1.0, timeout=2000)


@pytest.mark.parametrize("crear", ["fundido", "contar", "sacudir"])
def test_los_callbacks_de_una_animacion_no_mantienen_vivo_a_su_objetivo(qtbot, crear):
    """Regresion: el cierre conectado a `finished` capturaba al objetivo (que es el padre de la animacion). Al
    borrarse la animacion se soltaba esa ultima referencia y el objetivo se destruia a mitad de la destruccion de
    su hija: Qt abortaba al azar (~1 de cada 8 corridas de esta suite). Ahora el cierre guarda solo una
    referencia debil: soltar el objetivo lo libera aunque la animacion siga en curso."""
    import gc
    import weakref

    animaciones.forzar(True)
    objetivo = QLabel() if crear == "contar" else QDialog()
    referencia = weakref.ref(objetivo)
    if crear == "fundido":
        fundido_entrada(objetivo, ms=500)
    elif crear == "contar":
        contar(objetivo, 10.0, lambda v: f"{v:.0f}", ms=500)
    else:
        sacudir(objetivo, ms=500)
    del objetivo
    gc.collect()
    assert referencia() is None


def test_sacudir_vuelve_a_la_posicion_original(qtbot):
    animaciones.forzar(True)
    ventana = QWidget()
    qtbot.addWidget(ventana)
    ventana.move(QPoint(120, 80))
    sacudir(ventana, ms=40)
    qtbot.waitUntil(lambda: not ventana.property("_sacudiendo"), timeout=2000)
    assert ventana.pos() == QPoint(120, 80)


def test_sacudir_apagado_no_mueve_nada(qtbot):
    ventana = QWidget()
    qtbot.addWidget(ventana)
    ventana.move(QPoint(10, 10))
    sacudir(ventana)
    assert ventana.property("_sacudiendo") in (None, False)
    assert ventana.pos() == QPoint(10, 10)


def test_marcar_error_pone_y_quita_la_propiedad(qtbot):
    campo = QLineEdit()
    qtbot.addWidget(campo)
    marcar_error(campo, ms=30)
    assert campo.property("error") == "true"
    qtbot.waitUntil(lambda: campo.property("error") == "false", timeout=2000)


def test_destello_crea_una_capa_que_se_borra_sola(qtbot):
    animaciones.forzar(True)
    etiqueta = QLabel("Total")
    qtbot.addWidget(etiqueta)
    etiqueta.show()
    destello(etiqueta, ms=30)
    assert etiqueta.findChildren(animaciones._Destello)
    qtbot.waitUntil(lambda: not etiqueta.findChildren(animaciones._Destello), timeout=2000)


def test_destello_apagado_no_crea_nada(qtbot):
    etiqueta = QLabel("Total")
    qtbot.addWidget(etiqueta)
    etiqueta.show()
    destello(etiqueta)
    assert not etiqueta.findChildren(animaciones._Destello)


def test_destello_fila_vive_en_el_viewport_y_no_toca_los_items(qtbot):
    animaciones.forzar(True)
    tabla = QTableWidget(3, 2)
    for fila in range(3):
        for columna in range(2):
            tabla.setItem(fila, columna, QTableWidgetItem(f"{fila}-{columna}"))
    qtbot.addWidget(tabla)
    tabla.show()
    qtbot.waitExposed(tabla)
    destello_fila(tabla, 1, ms=30)
    assert tabla.viewport().findChildren(animaciones._Destello)
    assert tabla.item(1, 0).background().style() == Qt.BrushStyle.NoBrush
    qtbot.waitUntil(lambda: not tabla.viewport().findChildren(animaciones._Destello), timeout=2000)


def test_destello_fila_fuera_de_rango_no_falla(qtbot):
    animaciones.forzar(True)
    tabla = QTableWidget(1, 1)
    qtbot.addWidget(tabla)
    tabla.show()
    destello_fila(tabla, 5)
    destello_fila(tabla, -1)


def test_contar_sube_hasta_el_valor_final_con_su_formato(qtbot):
    animaciones.forzar(True)
    etiqueta = QLabel("—")
    qtbot.addWidget(etiqueta)
    contar(etiqueta, 1234.5, lambda v: f"${v:,.2f}", ms=40)
    qtbot.waitUntil(lambda: etiqueta.text() == "$1,234.50", timeout=2000)
    _esperar_sin_animaciones(qtbot, etiqueta)
    assert etiqueta.minimumWidth() == 0


def test_contar_apagado_o_en_cero_muestra_el_valor_de_una_vez(qtbot):
    etiqueta = QLabel("—")
    qtbot.addWidget(etiqueta)
    contar(etiqueta, 7, lambda v: f"{int(v)}")
    assert etiqueta.text() == "7"
    animaciones.forzar(True)
    contar(etiqueta, 0, lambda v: f"{int(v)}")
    assert etiqueta.text() == "0"


# ── Boton ocupado ───────────────────────────────────────────────────────────


def test_boton_ocupado_se_deshabilita_gira_y_se_restaura(qtbot):
    animaciones.forzar(True)
    boton = QPushButton("Exportar")
    qtbot.addWidget(boton)
    ocupar_boton(boton)
    assert boton.isEnabled() is False
    assert boton.property("_ocupado") is True
    giro = boton._giro
    assert giro is not None
    ocupar_boton(boton)  # idempotente: no apila otro giro
    assert boton._giro is giro
    liberar_boton(boton)
    assert boton.isEnabled() is True
    assert boton.property("_ocupado") is False
    assert boton._giro is None


def test_boton_ocupado_sin_animaciones_solo_se_deshabilita(qtbot):
    boton = QPushButton("Exportar")
    qtbot.addWidget(boton)
    ocupar_boton(boton)
    assert boton.isEnabled() is False
    assert getattr(boton, "_giro", None) is None
    liberar_boton(boton)
    assert boton.isEnabled() is True


# ── Fundido de dialogos ─────────────────────────────────────────────────────


class FacturaFormDialog(QDialog):  # mismo nombre que el real: debe quedar fuera del fundido
    pass


def test_el_filtro_aplica_fundido_a_un_dialogo_nuevo(qtbot):
    animaciones.forzar(True)
    filtro = FiltroFundidoDialogos()
    dialogo = QDialog()
    qtbot.addWidget(dialogo)
    dialogo.installEventFilter(filtro)
    dialogo.show()
    assert dialogo.windowOpacity() < 1.0
    qtbot.waitUntil(lambda: dialogo.windowOpacity() == 1.0, timeout=2000)


def test_el_filtro_respeta_las_exclusiones(qtbot):
    animaciones.forzar(True)
    filtro = FiltroFundidoDialogos()
    excluido = FacturaFormDialog()
    marcado = QDialog()
    marcado.setProperty("sin_fundido", True)
    for dialogo in (excluido, marcado):
        qtbot.addWidget(dialogo)
        dialogo.installEventFilter(filtro)
        dialogo.show()
        assert dialogo.windowOpacity() == 1.0


def test_el_filtro_no_anima_si_las_animaciones_estan_apagadas(qtbot):
    filtro = FiltroFundidoDialogos()
    dialogo = QDialog()
    qtbot.addWidget(dialogo)
    dialogo.installEventFilter(filtro)
    dialogo.show()
    assert dialogo.windowOpacity() == 1.0


# ── Aviso (toast) ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "titulo",
    [
        "Factura emitida",
        "Exportación completa",
        "Exportación exitosa",
        "Pago registrado",
        "Caja creada",
        "Abono aplicado",
        "Conciliación Exitosa",
        "Permisos guardados",
        "Usuario desbloqueado",
        "Turno cerrado",
        "Listo",
        "Éxito",
        "Nota de crédito devuelta",
    ],
)
def test_titulos_de_confirmacion_son_aviso(titulo):
    assert es_confirmacion_de_exito(titulo, "Texto corto.") is True


@pytest.mark.parametrize(
    "titulo",
    [
        "Selección requerida",
        "Sin datos",
        "Sin cajas",
        "Nada que facturar",
        "Caja requerida",
        "Error de selección",
        "Ya pagada",
        "Sesión cerrada",
        "Codigo enviado",
    ],
)
def test_titulos_que_piden_lectura_siguen_siendo_modales(titulo):
    assert es_confirmacion_de_exito(titulo, "Texto corto.") is False


def test_un_texto_muy_largo_no_va_como_aviso():
    assert es_confirmacion_de_exito("Exportación completa", "x" * (toast.LARGO_MAXIMO_TOAST + 1)) is False


def test_message_box_information_de_exito_muestra_aviso_y_no_bloquea(qtbot, monkeypatch):
    avisos = []
    monkeypatch.setattr(toast.Toast, "mostrar", staticmethod(lambda *a, **k: avisos.append(a)))
    monkeypatch.setattr(QDialog, "exec", lambda self: pytest.fail("no debe abrir un dialogo modal"))
    padre = QWidget()
    qtbot.addWidget(padre)
    message_box.MessageBox.information(padre, "Factura emitida", "La factura 1 se emitio.")
    assert avisos == [(padre, "Factura emitida", "La factura 1 se emitio.")]


def test_message_box_information_que_pide_lectura_sigue_siendo_modal(qtbot, monkeypatch):
    abiertos = []
    monkeypatch.setattr(QDialog, "exec", lambda self: abiertos.append(self.windowTitle()) or 0)
    monkeypatch.setattr(toast.Toast, "mostrar", staticmethod(lambda *a, **k: pytest.fail("no es un aviso")))
    padre = QWidget()
    qtbot.addWidget(padre)
    message_box.MessageBox.information(padre, "Selección requerida", "Selecciona una fila.")
    assert abiertos == ["Selección requerida"]


def test_toast_muestra_titulo_y_texto_y_se_cierra_solo(qtbot, monkeypatch):
    monkeypatch.setattr(toast, "DURACION_BASE_MS", 30)
    aviso = Toast.mostrar(None, "Factura emitida", "La factura 15 se emitio.")
    assert Toast._actual is aviso
    assert aviso.lbl_titulo.text() == "Factura emitida"
    assert aviso.lbl_texto.text() == "La factura 15 se emitio."
    assert aviso.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert aviso.isVisible()
    qtbot.waitUntil(lambda: Toast._actual is None, timeout=3000)


def test_un_aviso_nuevo_reemplaza_al_anterior(qtbot):
    primero = Toast.mostrar(None, "Uno", "")
    segundo = Toast.mostrar(None, "Dos", "")
    assert Toast._actual is segundo
    assert primero is not segundo
    assert segundo.lbl_texto.isHidden()  # sin texto no ocupa una linea vacia
    segundo._cerrar_ya()
    assert Toast._actual is None


def test_la_duracion_del_aviso_crece_con_el_texto_hasta_un_tope():
    corto = Toast(None, "T", "ok")
    largo = Toast(None, "T", "x" * 280)
    assert corto.duracion_ms == toast.DURACION_BASE_MS
    assert toast.DURACION_BASE_MS < largo.duracion_ms <= toast.DURACION_MAXIMA_MS


def test_el_alto_del_aviso_crece_con_las_lineas_del_texto(qtbot):
    una_linea = Toast(None, "Listo", "Hecho")
    texto_largo = "Se exportaron 128 productos a: C:\\Users\\Luis F\\Documents\\inventario.xlsx " * 2
    varias = Toast(None, "Exportación completa", texto_largo)
    assert varias.width() <= toast.ANCHO_MAXIMO
    assert varias.height() > una_linea.height()
    # El texto cabe entero: la etiqueta recibe al menos el alto que pide a ese ancho.
    assert varias.lbl_texto.height() >= varias.lbl_texto.heightForWidth(varias.lbl_texto.width()) - 1


def test_el_aviso_se_ancla_a_la_esquina_de_la_ventana_principal(qtbot):
    ventana = QWidget()
    qtbot.addWidget(ventana)
    ventana.resize(800, 600)
    ventana.move(100, 100)
    ventana.show()
    qtbot.waitExposed(ventana)
    dialogo_hijo = QDialog(ventana)
    aviso = Toast.mostrar(dialogo_hijo, "Listo", "Hecho")  # el padre es un dialogo: se ancla a la ventana raiz
    marco = ventana.frameGeometry()
    assert aviso.x() + aviso.width() == marco.right() - toast.MARGEN
    assert aviso.y() + aviso.height() == marco.bottom() - toast.MARGEN
    aviso._cerrar_ya()


# ── Barra de carga ──────────────────────────────────────────────────────────


def test_gestor_cuenta_las_tareas_y_avisa_solo_en_los_extremos():
    gestor = GestorActividad()
    eventos = []
    gestor.actividad.connect(eventos.append)
    gestor.iniciar()
    gestor.iniciar()
    gestor.terminar()
    assert eventos == [True]
    gestor.terminar()
    gestor.terminar()  # de mas: no baja de cero ni vuelve a avisar
    assert eventos == [True, False]
    assert gestor.hay_actividad is False


def test_la_barra_espera_antes_de_mostrarse_y_se_apaga_al_terminar(qtbot, monkeypatch):
    gestor = GestorActividad()
    barra = BarraCarga(gestor)
    qtbot.addWidget(barra)
    barra._retraso.setInterval(20)
    gestor.iniciar()
    assert barra.visible_ocupada is False  # una consulta rapida no la enciende
    qtbot.waitUntil(lambda: barra.visible_ocupada, timeout=2000)
    gestor.terminar()
    assert barra.visible_ocupada is False


def test_una_tarea_rapida_nunca_enciende_la_barra(qtbot):
    gestor = GestorActividad()
    barra = BarraCarga(gestor)
    qtbot.addWidget(barra)
    gestor.iniciar()
    gestor.terminar()
    assert not barra._retraso.isActive()
    assert barra.visible_ocupada is False


def test_la_barra_que_nace_con_actividad_en_curso_arranca_en_espera(qtbot):
    gestor = GestorActividad()
    gestor.iniciar()
    barra = BarraCarga(gestor)
    qtbot.addWidget(barra)
    assert barra._retraso.isActive()
    gestor.terminar()


def test_los_query_worker_encienden_el_gestor_salvo_los_silenciosos(qtbot):
    from app.ui.workers import QueryWorker

    gestor = GestorActividad.instancia()
    eventos = []
    gestor.actividad.connect(eventos.append)
    try:
        normal = QueryWorker(lambda: _SesionFalsa(), lambda session: 1)
        normal.start()
        qtbot.waitUntil(lambda: normal.isFinished() and eventos[-1:] == [False], timeout=3000)
        assert eventos[:1] == [True]

        eventos.clear()
        silencioso = QueryWorker(lambda: _SesionFalsa(), lambda session: 1)
        silencioso.silencioso = True
        silencioso.start()
        qtbot.waitUntil(silencioso.isFinished, timeout=3000)
        qtbot.wait(50)
        assert eventos == []
    finally:
        gestor.actividad.disconnect(eventos.append)


def test_reemplazar_el_worker_apenas_termina_no_deja_la_barra_encendida(qtbot):
    """Regresion: DashboardPanel.cargar_datos crea otro QueryWorker apenas el anterior deja de correr
    (isRunning() False). Antes la cuenta de la barra se cerraba con la señal `finished`, encolada al propio
    worker: si el panel lo soltaba antes de entregarla, se perdia y la barra quedaba cargando para siempre."""
    from PySide6.QtCore import QTimer

    from app.ui.workers import QueryWorker

    class _Panel:
        worker: QueryWorker | None = None
        lanzados = 0

        def cargar_datos(self):
            if self.worker is not None and self.worker.isRunning():
                return
            self.worker = QueryWorker(lambda: _SesionFalsa(), lambda session: 1)
            self.worker.start()
            self.lanzados += 1

    gestor = GestorActividad.instancia()
    base = gestor._cuenta
    panel = _Panel()
    timer = QTimer()
    timer.setInterval(0)
    timer.timeout.connect(panel.cargar_datos)
    timer.start()
    qtbot.wait(1000)
    timer.stop()
    qtbot.waitUntil(lambda: panel.worker is not None and not panel.worker.isRunning(), timeout=3000)
    qtbot.wait(50)
    assert panel.lanzados > 20
    assert gestor._cuenta == base


def test_un_worker_que_falla_tambien_apaga_la_barra(qtbot):
    from app.ui.workers import QueryWorker

    def _falla(_session):
        raise RuntimeError("sin base")

    gestor = GestorActividad.instancia()
    base = gestor._cuenta
    worker = QueryWorker(lambda: _SesionFalsa(), _falla)
    errores = []
    worker.error.connect(errores.append)
    worker.start()
    qtbot.waitUntil(lambda: worker.isFinished() and gestor._cuenta == base, timeout=3000)
    qtbot.waitUntil(lambda: errores == ["sin base"], timeout=3000)


class _SesionFalsa:
    def close(self):
        pass


# ── Panel general: cifras y grafico ─────────────────────────────────────────


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("$1,234.50", ("$", 1234.5, 2, "")),
        ("$0.00", ("$", 0.0, 2, "")),
        ("12", ("", 12.0, 0, "")),
        ("—", None),
        ("N/A", None),
    ],
)
def test_parsear_cifra(texto, esperado):
    assert _parsear_cifra(texto) == esperado


def test_kpi_con_animar_apagado_muestra_el_texto_exacto(qtbot):
    tarjeta = KpiCard("Ventas", "fa5s.dollar-sign", "#2563eb")
    qtbot.addWidget(tarjeta)
    tarjeta.set_valor("$1,234.50", animar=True)
    assert tarjeta.lbl_valor.text() == "$1,234.50"


def test_kpi_animado_termina_en_el_texto_exacto(qtbot):
    animaciones.forzar(True)
    tarjeta = KpiCard("Ventas", "fa5s.dollar-sign", "#2563eb")
    qtbot.addWidget(tarjeta)
    tarjeta.set_valor("$1,234.50", animar=True)
    qtbot.waitUntil(lambda: tarjeta.lbl_valor.text() == "$1,234.50", timeout=3000)
    _esperar_sin_animaciones(qtbot, tarjeta.lbl_valor)


def test_kpi_texto_no_numerico_no_se_anima(qtbot):
    animaciones.forzar(True)
    tarjeta = KpiCard("Ventas", "fa5s.dollar-sign", "#2563eb")
    qtbot.addWidget(tarjeta)
    tarjeta.set_valor("N/A", animar=True)
    assert tarjeta.lbl_valor.text() == "N/A"


def test_grafico_se_revela_hasta_el_final(qtbot):
    animaciones.forzar(True)
    grafico = VentasSemanaChart()
    qtbot.addWidget(grafico)
    grafico.set_datos([{"monto": 10}, {"monto": 20}], animar=True)
    assert grafico._revelado < 1.0
    qtbot.waitUntil(lambda: grafico._revelado == 1.0, timeout=3000)
    _esperar_sin_animaciones(qtbot, grafico)


def test_grafico_sin_animar_se_dibuja_completo(qtbot):
    grafico = VentasSemanaChart()
    qtbot.addWidget(grafico)
    grafico.set_datos([{"monto": 10}, {"monto": 20}], animar=True)  # animaciones apagadas
    assert grafico._revelado == 1.0


def test_una_tarea_lenta_queda_en_el_log_con_su_nombre(qtbot, monkeypatch, caplog):
    """La barra de carga sigue encendida mientras una tarea corre: si una consulta se bloquea, el log dice cual."""
    import logging
    import time

    from app.ui import workers
    from app.ui.workers import QueryWorker

    monkeypatch.setattr(workers, "SEGUNDOS_TAREA_LENTA", 0.05)

    def _tarea_lenta(session):
        time.sleep(0.3)
        return 1

    with caplog.at_level(logging.WARNING, logger="app.ui.workers"):
        worker = QueryWorker(lambda: _SesionFalsa(), _tarea_lenta)
        worker.start()
        qtbot.waitUntil(worker.isFinished, timeout=3000)
    avisos = [r.getMessage() for r in caplog.records]
    assert any("_tarea_lenta" in m and "sin terminar" in m for m in avisos)
    assert any("_tarea_lenta" in m and "termino tras" in m for m in avisos)


def test_una_tarea_rapida_no_deja_aviso_en_el_log(qtbot, caplog):
    import logging

    from app.ui.workers import QueryWorker

    with caplog.at_level(logging.WARNING, logger="app.ui.workers"):
        worker = QueryWorker(lambda: _SesionFalsa(), lambda session: 1)
        worker.start()
        qtbot.waitUntil(worker.isFinished, timeout=3000)
    assert caplog.records == []
