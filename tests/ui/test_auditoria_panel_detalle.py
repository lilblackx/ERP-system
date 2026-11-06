"""Auditoria general: "Detalle del cambio" completo (doble clic / boton), con los datos del registro, los cambios
antes/despues y todo como TEXTO PLANO (un "<a href>" escrito en un motivo no debe renderizarse como enlace)."""

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from app.ui import auditoria_panel as ap
from app.ui.auditoria_detalle_dialog import DetalleAuditoriaDialog


def _evento(accion="CREAR_FACTURA", modulo="VENTAS", detalle=None, usuario="admin"):
    return SimpleNamespace(
        fecha_evento=datetime(2026, 11, 5, 21, 30, 15),
        usuario=SimpleNamespace(nombre_usuario=usuario) if usuario else None,
        accion=accion,
        modulo=modulo,
        detalle=detalle,
    )


def test_un_evento_de_creacion_muestra_sus_datos_traducidos_y_completos():
    detalle = json.dumps(
        {"numero_factura": "FV-000123", "id_cliente": 5, "condicion_pago": "credito", "iva_activo": True, "pago": None}
    )

    d = ap.datos_de_detalle(_evento(detalle=detalle))

    assert d["registro"] == [
        ("N.º de factura", "FV-000123"),
        ("Cliente (ID)", "5"),
        ("Condición de pago", "credito"),
        ("IVA activo", "Sí"),
    ]
    assert d["cambios"] == []
    assert d["usuario"] == "admin" and d["modulo"] == "VENTAS" and d["fecha"] == "05/11/2026 21:30:15"
    assert "N.º de factura: FV-000123" in d["detalle"]


def test_los_montos_en_bolivares_llevan_el_sufijo_bs():
    d = ap.datos_de_detalle(_evento(detalle=json.dumps({"monto_abono": "150.00", "monto": "10"})))

    assert ("Monto abono", "150.00 Bs") in d["registro"]
    assert ("Monto", "10") in d["registro"]


def test_un_evento_con_cambios_antes_despues_los_separa_de_los_datos_del_registro():
    detalle = json.dumps(
        {
            "id_cliente": 5,
            "cambios_relevantes": [{"campo": "limite_credito", "valor_anterior": "100", "valor_nuevo": "500"}],
        }
    )

    d = ap.datos_de_detalle(_evento(accion="ACTUALIZAR_CLIENTE", modulo="CLIENTES", detalle=detalle))

    assert d["cambios"] == [("Límite de crédito", "100", "500")]
    assert d["registro"] == [("Cliente (ID)", "5")]  # los cambios no se repiten entre los datos del registro
    assert "Límite de crédito: 100 → 500" in d["detalle"]


def test_un_evento_de_texto_plano_se_muestra_tal_cual():
    d = ap.datos_de_detalle(_evento(accion="LOGIN", modulo="AUTH", detalle="Usuario 'admin' inició sesión"))

    assert d["registro"] == [] and d["cambios"] == []
    assert d["detalle"] == "Usuario 'admin' inició sesión"


def test_un_evento_sin_detalle_ni_usuario():
    d = ap.datos_de_detalle(_evento(detalle=None, usuario=None))

    assert d["detalle"] == "Sin información adicional." and d["usuario"] == "Sistema"


def test_el_texto_con_html_no_se_interpreta_en_la_ventana_de_detalle(qtbot):
    malicioso = "<a href='http://sitio-falso.example'>Haz clic aquí</a> <b>urgente</b>"
    d = ap.datos_de_detalle(_evento(detalle=json.dumps({"descripcion": malicioso})))

    ventana = DetalleAuditoriaDialog(d)
    qtbot.addWidget(ventana)

    # Todas las etiquetas que muestran datos van como texto plano (nunca HTML) ...
    for etiqueta in ventana.findChildren(QLabel):
        if etiqueta.pixmap().isNull():
            assert etiqueta.textFormat() == Qt.TextFormat.PlainText, etiqueta.text()
    # ... y el valor llega literal a la tabla y al cuadro de texto
    assert ventana.tabla_registro.item(0, 1).text() == malicioso
    assert malicioso in ventana.texto_detalle.toPlainText()


def test_doble_clic_o_boton_abren_el_detalle_del_evento_seleccionado(qtbot, monkeypatch):
    panel = ap.AuditoriaPanel(MagicMock(return_value=MagicMock()), MagicMock(id_usuario=1))
    qtbot.addWidget(panel)
    eventos = [_evento(detalle=json.dumps({"numero_factura": "FV-1"})), _evento(accion="ANULAR_FACTURA")]
    panel._poblar_tabla({"items": eventos, "total": 2, "pagina": 1, "por_pagina": 50, "total_paginas": 1})
    abiertos = []
    monkeypatch.setattr(DetalleAuditoriaDialog, "exec", lambda self: abiertos.append(self))

    panel.tabla.selectRow(1)
    panel.ver_detalle_seleccionado()

    assert len(abiertos) == 1
    assert any(
        "ANULAR_FACTURA" in lbl.text() for lbl in abiertos[0].findChildren(QLabel)
    )  # el subtitulo lleva la accion


def test_sin_seleccion_avisa_en_vez_de_abrir_nada(qtbot, monkeypatch):
    panel = ap.AuditoriaPanel(MagicMock(return_value=MagicMock()), MagicMock(id_usuario=1))
    qtbot.addWidget(panel)
    avisos = []
    monkeypatch.setattr(ap.MessageBox, "information", staticmethod(lambda *a, **k: avisos.append(a)))
    monkeypatch.setattr(DetalleAuditoriaDialog, "exec", lambda self: avisos.append("abrio"))

    panel.ver_detalle_seleccionado()

    assert len(avisos) == 1 and avisos[0] != "abrio"


def test_la_celda_de_detalle_trae_el_texto_completo_en_el_tooltip(qtbot):
    panel = ap.AuditoriaPanel(MagicMock(return_value=MagicMock()), MagicMock(id_usuario=1))
    qtbot.addWidget(panel)
    largo = "x" * 300
    panel._poblar_tabla(
        {
            "items": [_evento(detalle=json.dumps({"descripcion": largo}))],
            "total": 1,
            "pagina": 1,
            "por_pagina": 50,
            "total_paginas": 1,
        }
    )

    celda = panel.tabla.item(0, 4)

    assert len(celda.text()) < 100 and largo in celda.toolTip()  # la celda se resume; el tooltip la trae entera
