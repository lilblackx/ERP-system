"""Tests de FacturaFormDialog tras migrar los QDoubleSpinBox/QSpinBox de la tarjeta de
carrito a NumericLineEdit: cantidad_input (QUANTITY, min_value=0.01 -- cantidad_producto
de factura_detalle es Numeric(12,2)), precio_input (AMOUNT, min_value=0.01 -- precio_unitario
es Numeric(18,2)), descuento_input (AMOUNT, sin overrides) y dias_credito_custom_input
(COUNT, min_value=1, max_value=365, suffix " dias"). Ver app/ui/factura_form_dialog.py.

A diferencia de compras.py, este dialogo NO arma la tabla del carrito con un
NumericLineEdit por fila -- cantidad/precio son campos unicos por encima de la tabla
("Agregar" los empuja a self.items, una lista de dicts) y la tabla en si solo pinta
QTableWidgetItem de solo lectura. El __init__ hace bastantes consultas de catalogo
(clientes/vendedores/productos/tasa/IVA/origenes de vuelto) -- se parchean todas a
resultados vacios/neutros via monkeypatch en vez de armar cadenas de mock de
session.query(), que no son el objeto de este test (los widgets numericos)."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import app.ui.factura_form_dialog as ffd
from tests.factories import (
    crear_cliente,
    crear_precio_producto,
    crear_producto,
    crear_usuario_admin,
    crear_vendedor,
    pago_contado,
)


def _mock_servicios(monkeypatch, productos=None):
    monkeypatch.setattr(ffd, "list_clientes", lambda *a, **k: {"items": []})
    monkeypatch.setattr(ffd.VendedorService, "listar", staticmethod(lambda *a, **k: {"items": []}))
    monkeypatch.setattr(ffd.ProductoService, "buscar", staticmethod(lambda *a, **k: {"items": productos or []}))
    monkeypatch.setattr(ffd.PrecioService, "obtener_precio", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(ffd.TasaService, "obtener_tasa_actual", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(ffd.EmpresaService, "obtener_iva_vigente", staticmethod(lambda *a: (False, Decimal("0"))))
    monkeypatch.setattr(ffd.CajaService, "listar_cajas", staticmethod(lambda *a, **k: []))
    monkeypatch.setattr(ffd.BancoService, "listar_cuentas", staticmethod(lambda *a, **k: []))


def _crear_dialogo(qtbot, monkeypatch, productos=None):
    _mock_servicios(monkeypatch, productos=productos)
    session = MagicMock()
    session.get.return_value = None
    dialogo = ffd.FacturaFormDialog(session, id_usuario=1)
    qtbot.addWidget(dialogo)
    return dialogo


def _dar_foco(qtbot, campo):
    campo.window().show()
    qtbot.waitExposed(campo.window())
    campo.setFocus()
    qtbot.waitUntil(campo.hasFocus)


def _escribir_y_perder_foco(qtbot, campo, texto):
    _dar_foco(qtbot, campo)
    qtbot.keyClicks(campo, texto)
    campo.clearFocus()


# --- cantidad_input / precio_input (fila "Agregar" del carrito) ------------------------


def test_cantidad_input_arranca_en_1(qtbot, monkeypatch):
    dialogo = _crear_dialogo(qtbot, monkeypatch)
    assert dialogo.cantidad_input.get_value() == Decimal("1")


def test_cantidad_input_no_admite_cero_ni_negativos(qtbot, monkeypatch):
    dialogo = _crear_dialogo(qtbot, monkeypatch)
    _escribir_y_perder_foco(qtbot, dialogo.cantidad_input, "0")
    assert dialogo.cantidad_input.get_value() == Decimal("0.01")


def test_precio_input_formatea_con_prefijo_y_miles(qtbot, monkeypatch):
    dialogo = _crear_dialogo(qtbot, monkeypatch)
    _escribir_y_perder_foco(qtbot, dialogo.precio_input, "1500,5")
    assert dialogo.precio_input.get_value() == Decimal("1500.50")
    assert dialogo.precio_input.text() == "$ 1.500,50"


def test_precio_input_no_admite_cero(qtbot, monkeypatch):
    dialogo = _crear_dialogo(qtbot, monkeypatch)
    _escribir_y_perder_foco(qtbot, dialogo.precio_input, "0")
    assert dialogo.precio_input.get_value() == Decimal("0.01")


# --- descuento_input ---------------------------------------------------------------------


def test_descuento_input_arranca_en_cero_formateado(qtbot, monkeypatch):
    dialogo = _crear_dialogo(qtbot, monkeypatch)
    assert dialogo.descuento_input.text() == "$ 0,00"
    assert dialogo.descuento_input.get_value() == Decimal("0")


def test_descuento_input_admite_valores_grandes(qtbot, monkeypatch):
    dialogo = _crear_dialogo(qtbot, monkeypatch)
    _escribir_y_perder_foco(qtbot, dialogo.descuento_input, "2500")
    assert dialogo.descuento_input.get_value() == Decimal("2500.00")


# --- dias_credito_custom_input -----------------------------------------------------------


def test_dias_credito_custom_input_rango_1_a_365(qtbot, monkeypatch):
    dialogo = _crear_dialogo(qtbot, monkeypatch)
    dialogo.dias_credito_custom_input.set_value(400)
    assert dialogo.dias_credito_custom_input.get_value() == Decimal("365")
    dialogo.dias_credito_custom_input.set_value(0)
    assert dialogo.dias_credito_custom_input.get_value() == Decimal("1")


def test_dias_credito_custom_input_muestra_sufijo(qtbot, monkeypatch):
    dialogo = _crear_dialogo(qtbot, monkeypatch)
    dialogo.dias_credito_custom_input.set_value(45)
    assert dialogo.dias_credito_custom_input.text() == "45 días"


# --- Carrito: _agregar_item usa cantidad_input.get_value()/precio_input.get_value() -------


def test_agregar_item_usa_cantidad_y_precio_tecleados(qtbot, monkeypatch):
    producto = SimpleNamespace(
        id_producto=1,
        cod_producto="PROD-1",
        nombre_producto="Producto Uno",
        cantidad_unidad=Decimal("1000.00"),
        estado_producto="ACTIVO",
    )
    dialogo = _crear_dialogo(qtbot, monkeypatch, productos=[producto])
    indice = dialogo.producto_combo.findData(1)
    assert indice >= 0
    dialogo.producto_combo.setCurrentIndex(indice)

    _escribir_y_perder_foco(qtbot, dialogo.cantidad_input, "3,5")
    _escribir_y_perder_foco(qtbot, dialogo.precio_input, "10,25")
    dialogo._agregar_item()

    assert len(dialogo.items) == 1
    item = dialogo.items[0]
    assert item["cantidad"] == 3.5
    assert item["precio_unitario"] == 10.25
    assert isinstance(item["cantidad"], float)
    assert isinstance(item["precio_unitario"], float)


# --- get_data(): dias_credito_personalizados debe ser int, monto_descuento Decimal --------


def test_get_data_dias_credito_personalizados_es_int(qtbot, monkeypatch):
    dialogo = _crear_dialogo(qtbot, monkeypatch)
    indice_credito = dialogo.condicion_combo.findData("credito")
    dialogo.condicion_combo.setCurrentIndex(indice_credito)
    dialogo.chk_dias_configurados.setChecked(False)
    dialogo.dias_credito_custom_input.set_value(60)

    datos = dialogo.get_data()

    assert datos["dias_credito_personalizados"] == 60
    assert isinstance(datos["dias_credito_personalizados"], int)


def test_get_data_monto_descuento_es_decimal(qtbot, monkeypatch):
    dialogo = _crear_dialogo(qtbot, monkeypatch)
    _escribir_y_perder_foco(qtbot, dialogo.descuento_input, "99,99")

    datos = dialogo.get_data()

    assert datos["monto_descuento"] == Decimal("99.99")


# --- pagos: PagoLineaDialog.get_data() devuelve monto_moneda_origen como Decimal ----------
# desde la migracion a NumericLineEdit -- _convertir_pago_a_usd/_refrescar_tabla_pagos
# siguen siendo float de punta a punta (se suman con otros totales float), asi que deben
# aceptar un pago con monto Decimal sin romper. Bug real reportado por el usuario: agregar
# una forma de pago lanzaba "TypeError: unsupported operand type(s) for +=: 'float' and
# 'decimal.Decimal'" en _refrescar_tabla_pagos.


def _pago_usd(monto: str) -> dict:
    """Misma forma que PagoLineaDialog.get_data() para un pago en USD en efectivo."""
    return {
        "metodo_pago": "efectivo",
        "moneda": "USD",
        "monto_moneda_origen": Decimal(monto),
        "id_caja": 1,
        "id_cuenta_bancaria": None,
        "referencia": None,
    }


def test_convertir_pago_a_usd_acepta_decimal(qtbot, monkeypatch):
    dialogo = _crear_dialogo(qtbot, monkeypatch)

    resultado = dialogo._convertir_pago_a_usd(_pago_usd("50.00"))

    assert resultado == 50.0
    assert isinstance(resultado, float)


def test_refrescar_tabla_pagos_con_monto_decimal_no_lanza(qtbot, monkeypatch):
    dialogo = _crear_dialogo(qtbot, monkeypatch)
    dialogo.pagos.append(_pago_usd("125.50"))

    dialogo._refrescar_tabla_pagos()  # no debe lanzar TypeError

    assert dialogo.tabla_pagos.rowCount() == 1
    assert "125.50" in dialogo.tabla_pagos.item(0, 2).text()


# --- cliente_combo: nunca preseleccionado, boton "+" crea sin salir de la factura --------
# Pedido del usuario 2026-09-09: un cliente equivocado quedando preseleccionado sin que el
# cajero lo haya elegido a proposito es un riesgo real de facturar a quien no es.


def _cliente_fake(id_cliente: int, nombre: str) -> SimpleNamespace:
    return SimpleNamespace(
        id_cliente=id_cliente,
        nombre_razon_social=nombre,
        id_legal="J",
        identificacion_cliente="07000750",
        estado_cliente="ACTIVO",
        dias_credito=0,
    )


def test_cliente_combo_no_preselecciona_ningun_cliente(qtbot, monkeypatch):
    _mock_servicios(monkeypatch)
    monkeypatch.setattr(ffd, "list_clientes", lambda *a, **k: {"items": [_cliente_fake(1, "Cliente Prueba")]})
    session = MagicMock()
    session.get.return_value = None
    dialogo = ffd.FacturaFormDialog(session, id_usuario=1)
    qtbot.addWidget(dialogo)

    assert dialogo.cliente_combo.itemText(0) == "Seleccione un cliente…"
    assert dialogo.cliente_combo.currentIndex() == 0
    assert dialogo.cliente_combo.currentData() is None


def test_abrir_nuevo_cliente_lo_deja_seleccionado_sin_perder_la_factura(qtbot, monkeypatch):
    _mock_servicios(monkeypatch)
    monkeypatch.setattr(ffd, "list_clientes", lambda *a, **k: {"items": []})
    session = MagicMock()
    session.get.return_value = None
    dialogo = ffd.FacturaFormDialog(session, id_usuario=1)
    qtbot.addWidget(dialogo)

    # Simula que el cajero ya venia escribiendo algo en la busqueda de cliente cuando
    # decide crear uno nuevo -- no debe sobrevivir a la seleccion final.
    dialogo.cliente_buscar_input.setText("algo que no matchea")

    nuevo = _cliente_fake(555, "Cliente Nuevo, C.A.")

    dialogo_cliente_mock = MagicMock()
    dialogo_cliente_mock.exec.return_value = ffd.QDialog.DialogCode.Accepted
    dialogo_cliente_mock.get_data.return_value = {
        "codigo_cliente": "CLI-099",
        "nombre_razon_social": nuevo.nombre_razon_social,
        "id_legal": "J",
        "identificacion_cliente": "07000750",
    }
    monkeypatch.setattr(ffd, "ClienteFormDialog", lambda *a, **k: dialogo_cliente_mock)
    monkeypatch.setattr(ffd, "create_cliente", lambda session, **datos: nuevo)
    monkeypatch.setattr(
        ffd,
        "list_clientes",
        lambda session, texto, **k: {"items": [nuevo]} if texto == nuevo.nombre_razon_social else {"items": []},
    )

    dialogo._abrir_nuevo_cliente()

    assert dialogo.cliente_buscar_input.text() == nuevo.nombre_razon_social
    assert dialogo.cliente_combo.currentData() == nuevo.id_cliente


def test_filtrar_clientes_abre_el_desplegable_con_resultados(qtbot, monkeypatch):
    """Sacar la preseleccion automatica (test de arriba) dejo el combo siempre mostrando
    "Seleccione un cliente…" cerrado, sin ninguna senal de que la busqueda encontro algo
    -- reportado por el usuario: "la barra de busqueda parece que no funciona, no me
    muestra ninguna sugerencia cuando escribo". Fix: abrir el desplegable con las
    coincidencias (sin seleccionar ninguna) cuando el debounce de tipeo repuebla el
    combo."""
    _mock_servicios(monkeypatch)
    monkeypatch.setattr(ffd, "list_clientes", lambda *a, **k: {"items": [_cliente_fake(1, "Cliente Prueba")]})
    session = MagicMock()
    session.get.return_value = None
    dialogo = ffd.FacturaFormDialog(session, id_usuario=1)
    qtbot.addWidget(dialogo)

    llamadas = []
    monkeypatch.setattr(type(dialogo.cliente_combo), "showPopup", lambda self: llamadas.append(True))

    dialogo.cliente_buscar_input.setText("prueba")
    qtbot.wait(ffd.DEBOUNCE_BUSQUEDA_MS + 50)

    assert llamadas == [True]
    assert dialogo.cliente_combo.currentData() is None


def test_enter_con_un_solo_resultado_lo_selecciona_y_avanza_foco(qtbot, monkeypatch):
    """Enter sigue siendo una accion explicita e inequivoca del cajero (a diferencia de
    tipear, que solo abre sugerencias) -- con un unico resultado, seleccionarlo y saltar
    a la busqueda de producto restaura el flujo rapido sin mouse documentado en
    _on_cliente_buscar_return_pressed."""
    _mock_servicios(monkeypatch)
    monkeypatch.setattr(ffd, "list_clientes", lambda *a, **k: {"items": [_cliente_fake(7, "Unico Cliente")]})
    session = MagicMock()
    session.get.return_value = None
    dialogo = ffd.FacturaFormDialog(session, id_usuario=1)
    qtbot.addWidget(dialogo)

    dialogo.show()
    qtbot.waitExposed(dialogo)
    dialogo.cliente_buscar_input.setText("Unico")
    dialogo._on_cliente_buscar_return_pressed()
    qtbot.waitUntil(dialogo.producto_buscar_input.hasFocus)

    assert dialogo.cliente_combo.currentData() == 7


def test_enter_con_varios_resultados_abre_desplegable_sin_seleccionar(qtbot, monkeypatch):
    _mock_servicios(monkeypatch)
    monkeypatch.setattr(
        ffd,
        "list_clientes",
        lambda *a, **k: {"items": [_cliente_fake(1, "Cliente Uno"), _cliente_fake(2, "Cliente Dos")]},
    )
    session = MagicMock()
    session.get.return_value = None
    dialogo = ffd.FacturaFormDialog(session, id_usuario=1)
    qtbot.addWidget(dialogo)

    llamadas = []
    monkeypatch.setattr(type(dialogo.cliente_combo), "showPopup", lambda self: llamadas.append(True))

    dialogo.cliente_buscar_input.setText("Cliente")
    dialogo._on_cliente_buscar_return_pressed()

    assert dialogo.cliente_combo.currentData() is None
    assert llamadas == [True]


def test_abrir_nuevo_cliente_cancelado_no_cambia_nada(qtbot, monkeypatch):
    _mock_servicios(monkeypatch)
    monkeypatch.setattr(ffd, "list_clientes", lambda *a, **k: {"items": []})
    session = MagicMock()
    session.get.return_value = None
    dialogo = ffd.FacturaFormDialog(session, id_usuario=1)
    qtbot.addWidget(dialogo)

    dialogo_cliente_mock = MagicMock()
    dialogo_cliente_mock.exec.return_value = ffd.QDialog.DialogCode.Rejected
    monkeypatch.setattr(ffd, "ClienteFormDialog", lambda *a, **k: dialogo_cliente_mock)
    creado = MagicMock()
    monkeypatch.setattr(ffd, "create_cliente", creado)

    dialogo._abrir_nuevo_cliente()

    creado.assert_not_called()
    assert dialogo.cliente_combo.currentData() is None


# --- _tarea_emitir_factura: corre en el QThread de QueryWorker (hallazgo 2.5/#7 de la ---
# auditoria -- emitir_factura() ya no bloquea el hilo de UI). Es una funcion de modulo sin
# dependencias de Qt (solo session + datos primitivos), asi que se prueba igual que un
# metodo de servicio, contra la base de datos real de test (no MagicMock).


def test_tarea_emitir_factura_ok_devuelve_factura(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session)

    resultado = ffd._tarea_emitir_factura(
        db_session,
        id_usuario=admin.id_usuario,
        id_cliente=cliente.id_cliente,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 5, "precio_unitario": "20.00"}],
        fecha_vencimiento=None,
        observaciones=None,
        monto_descuento=Decimal("0.00"),
        motivo_descuento=None,
        id_autorizador_descuento=None,
        dias_credito_personalizados=None,
        motivo_dias_credito=None,
        id_autorizador_dias_credito=None,
        metodo_vuelto=None,
        id_caja_vuelto=None,
        id_cuenta_bancaria_vuelto=None,
        referencia_vuelto=None,
        id_autorizador_vuelto=None,
    )

    assert resultado["ok"] is True
    assert resultado["factura"].total_venta == Decimal("100.00")


def test_tarea_emitir_factura_value_error_devuelve_mensaje_sin_lanzar(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session)
    cliente = crear_cliente(db_session)

    resultado = ffd._tarea_emitir_factura(
        db_session,
        id_usuario=admin.id_usuario,
        id_cliente=cliente.id_cliente,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="otra",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )

    assert resultado == {
        "ok": False,
        "titulo": "No se pudo emitir la factura",
        "mensaje": "condicion_pago debe ser 'contado' o 'credito'",
    }


def test_tarea_emitir_factura_sin_permiso_devuelve_mensaje_sin_lanzar(db_session):
    producto = crear_producto(db_session)
    cliente = crear_cliente(db_session)

    resultado = ffd._tarea_emitir_factura(
        db_session,
        id_usuario=None,
        id_cliente=cliente.id_cliente,
        id_vendedor=None,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )

    assert resultado == {
        "ok": False,
        "titulo": "Sin permiso",
        "mensaje": "No tienes permiso para emitir facturas.",
    }


# --- _validar_y_aceptar: manejo async del resultado del worker (mismo hallazgo 2.5) -----
# Se prueban los handlers/guardas directo (sin levantar un QThread real ni pegarle a la
# base de datos) -- lo que importa aca es el cableado de señales/estado de UI, no
# VentaService.emitir_factura en si (ya cubierto arriba y en test_ventas.py).


def test_iniciar_y_finalizar_emision_ui_alternan_estado(qtbot, monkeypatch):
    dialogo = _crear_dialogo(qtbot, monkeypatch)

    dialogo._iniciar_emision_ui()
    assert dialogo._emitiendo_factura is True
    assert dialogo.btn_emitir.isEnabled() is False
    assert dialogo.btn_cancelar.isEnabled() is False
    assert ffd.QApplication.overrideCursor() is not None

    dialogo._finalizar_emision_ui()
    assert dialogo._emitiendo_factura is False
    assert dialogo.btn_emitir.isEnabled() is True
    assert dialogo.btn_cancelar.isEnabled() is True
    assert ffd.QApplication.overrideCursor() is None


def test_reject_bloqueado_mientras_emite_factura(qtbot, monkeypatch):
    dialogo = _crear_dialogo(qtbot, monkeypatch)
    llamadas = []
    monkeypatch.setattr(ffd.QDialog, "reject", lambda self: llamadas.append(True))

    dialogo._emitiendo_factura = True
    dialogo.reject()
    assert llamadas == []

    dialogo._emitiendo_factura = False
    dialogo.reject()
    assert llamadas == [True]


def test_close_event_bloqueado_mientras_emite_factura(qtbot, monkeypatch):
    dialogo = _crear_dialogo(qtbot, monkeypatch)
    llamadas = []
    monkeypatch.setattr(ffd.QDialog, "closeEvent", lambda self, event: llamadas.append(event))
    evento = MagicMock()

    dialogo._emitiendo_factura = True
    dialogo.closeEvent(evento)
    evento.ignore.assert_called_once()
    assert llamadas == []

    dialogo._emitiendo_factura = False
    dialogo.closeEvent(evento)
    assert llamadas == [evento]


def test_on_resultado_emitir_factura_ok_acepta_dialogo(qtbot, monkeypatch):
    dialogo = _crear_dialogo(qtbot, monkeypatch)
    dialogo._iniciar_emision_ui()
    aceptado = []
    monkeypatch.setattr(dialogo, "accept", lambda: aceptado.append(True))
    factura_fake = SimpleNamespace(id_factura=1, numero_factura="F-000001")

    dialogo._on_resultado_emitir_factura({"ok": True, "factura": factura_fake})

    assert dialogo.factura_emitida is factura_fake
    assert aceptado == [True]
    assert dialogo._emitiendo_factura is False
    assert dialogo.btn_emitir.isEnabled() is True


def test_on_resultado_emitir_factura_fallo_muestra_mensaje_y_no_cierra(qtbot, monkeypatch):
    dialogo = _crear_dialogo(qtbot, monkeypatch)
    dialogo._iniciar_emision_ui()
    avisos = []
    monkeypatch.setattr(ffd.MessageBox, "warning", lambda *a, **k: avisos.append((a, k)))
    aceptado = []
    monkeypatch.setattr(dialogo, "accept", lambda: aceptado.append(True))

    dialogo._on_resultado_emitir_factura(
        {"ok": False, "titulo": "Sin permiso", "mensaje": "No tienes permiso para emitir facturas."}
    )

    assert dialogo.factura_emitida is None
    assert aceptado == []
    assert dialogo._emitiendo_factura is False
    assert dialogo.btn_emitir.isEnabled() is True
    assert len(avisos) == 1
    assert avisos[0][0][1:] == ("Sin permiso", "No tienes permiso para emitir facturas.")


def test_on_error_emitir_factura_muestra_mensaje_generico(qtbot, monkeypatch):
    dialogo = _crear_dialogo(qtbot, monkeypatch)
    dialogo._iniciar_emision_ui()
    avisos = []
    monkeypatch.setattr(ffd.MessageBox, "critical", lambda *a, **k: avisos.append((a, k)))

    dialogo._on_error_emitir_factura("TCP Provider: conexion perdida")

    assert dialogo._emitiendo_factura is False
    assert dialogo.btn_emitir.isEnabled() is True
    assert avisos[0][0][1:] == ("Error", "No se pudo emitir la factura.")
