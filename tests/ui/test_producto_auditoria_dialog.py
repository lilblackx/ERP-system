"""Auditoria de productos: tabla de solo lectura, sin barra horizontal ni numeracion, fechas por defecto sanas y
sin cajas alrededor de cada texto de las tarjetas."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QLabel, QTableWidget, QWidget

from app.ui.producto_auditoria_dialog import ProductoAuditoriaDialog


def _aud(accion, minuto):
    return SimpleNamespace(
        fecha_evento=datetime(2026, 9, 8, 11, minuto),
        usuario=SimpleNamespace(nombre_usuario="admin"),
        accion=accion,
        modulo="INVENTARIO",
        detalle='{"id_producto": 1}',
    )


def _respuesta(items):
    return {
        "items": items,
        "total": len(items),
        "pagina": 1,
        "por_pagina": 50,
        "total_paginas": 1,
        "por_accion": {"CAMBIO_PRECIO": 1, "CREAR_PRODUCTO": 1},
    }


@pytest.fixture
def dialogo(qtbot, monkeypatch):
    monkeypatch.setattr(
        "app.ui.producto_auditoria_dialog.AuditoriaService.consultar_auditoria_producto",
        lambda session, **kw: _respuesta([_aud("CAMBIO_PRECIO", 59), _aud("CREAR_PRODUCTO", 40)]),
    )
    d = ProductoAuditoriaDialog(MagicMock(), MagicMock(), None)
    qtbot.addWidget(d)
    return d


def test_la_tabla_es_de_solo_lectura(dialogo):
    assert dialogo.table.editTriggers() == QTableWidget.EditTrigger.NoEditTriggers
    assert dialogo.table.rowCount() == 2


def test_la_tabla_sigue_el_estandar_de_la_app(dialogo):
    assert not dialogo.table.verticalHeader().isVisible()  # sin numeracion de filas
    assert not dialogo.table.showGrid()
    assert dialogo.table.alternatingRowColors()
    assert dialogo.table.horizontalScrollBarPolicy().name == "ScrollBarAlwaysOff"


def test_el_rango_de_fechas_por_defecto_sale_de_hoy_y_no_de_1999(dialogo):
    hoy = QDate.currentDate()

    assert dialogo.fecha_fin.date() == hoy
    assert dialogo.fecha_inicio.date() == hoy.addYears(-1)


def test_limpiar_filtros_no_retrocede_la_fecha_cada_vez(dialogo):
    dialogo._limpiar_filtros()
    dialogo._limpiar_filtros()

    assert dialogo.fecha_inicio.date() == QDate.currentDate().addYears(-1)


def test_las_tarjetas_no_heredan_borde_ni_relleno_a_sus_textos(dialogo):
    """Antes `border/padding` sin selector en la tarjeta se aplicaban a CADA QLabel hijo y se dibujaba una caja
    alrededor de cada texto. Ahora la tarjeta se estiliza por su objectName."""
    tarjetas = [w for w in dialogo.findChildren(QWidget) if w.objectName() == "SectionCard"]

    assert len(tarjetas) == 2  # filtros y resumen
    for tarjeta in tarjetas:
        assert tarjeta.styleSheet() == ""  # ninguna regla sin selector sobre la tarjeta
    etiquetas_de_filtro = [lbl for lbl in tarjetas[0].findChildren(QLabel)]
    assert etiquetas_de_filtro
    assert all("border" not in lbl.styleSheet() for lbl in etiquetas_de_filtro)


# -- Detalle completo de un registro ---------------------------------------------------------------------------

import json  # noqa: E402

from app.ui.producto_auditoria_dialog import DetalleAuditoriaDialog, filas_de_cambios  # noqa: E402

DESC_LARGA = "Gaseosa sabor cola en botella retornable de 1.5 litros, presentación familiar para consumo en el hogar"


def test_filas_de_cambios_trae_cada_campo_con_su_valor_anterior_y_nuevo_sin_truncar():
    detalle = json.dumps(
        {
            "id_producto": 1,
            "campos": ["cod_producto", "nombre_producto", "descripcion_producto"],
            "cambios_relevantes": [
                {"campo": "cod_producto", "valor_anterior": "PROD-001", "valor_nuevo": "COCA-15"},
                {"campo": "nombre_producto", "valor_anterior": "Coca-Cola 1.5L", "valor_nuevo": "Coca-Cola 1.5 L"},
                {"campo": "descripcion_producto", "valor_anterior": "None", "valor_nuevo": DESC_LARGA},
            ],
        }
    )

    assert filas_de_cambios(detalle) == [
        ("Código", "PROD-001", "COCA-15"),
        ("Nombre", "Coca-Cola 1.5L", "Coca-Cola 1.5 L"),
        ("Descripción", "—", DESC_LARGA),  # la descripcion larga completa; "None" se muestra como guion
    ]


def test_filas_de_cambios_cubre_stock_precios_y_estado():
    stock = json.dumps(
        {
            "movimientos": [
                {
                    "campo": "cantidad_unidad",
                    "valor_anterior": "10",
                    "valor_nuevo": "25",
                    "diferencia": "15.0",
                    "tipo_movimiento": "AUMENTO",
                }
            ]
        }
    )
    precios = json.dumps(
        {"cambios_precio": {"precio_1": {"anterior": "1.50", "nuevo": "2.00"}, "precio_2": {"nuevo": "3"}}}
    )
    estado = json.dumps({"nuevo_estado": "INACTIVO"})

    assert filas_de_cambios(stock) == [("Cantidad (unidades)", "10", "25  (AUMENTO: 15.0)")]
    assert filas_de_cambios(precios) == [("Precio 1", "$1.50", "$2.00"), ("Precio 2", "—", "$3")]
    assert filas_de_cambios(estado) == [("Estado", "—", "INACTIVO")]


@pytest.mark.parametrize(
    "detalle", [None, "", "Recepción OC ODC-000004: 1.0 unidades (ID: 1)", "{no es json", '["lista"]', "{}"]
)
def test_filas_de_cambios_sin_cambios_estructurados_devuelve_lista_vacia(detalle):
    assert filas_de_cambios(detalle) == []


def test_el_detalle_completo_se_abre_desde_la_fila_seleccionada(dialogo, monkeypatch):
    abiertos = []
    monkeypatch.setattr(DetalleAuditoriaDialog, "exec", lambda self: abiertos.append(self))
    dialogo.table.selectRow(0)

    dialogo._ver_detalle()

    assert len(abiertos) == 1
    assert abiertos[0].windowTitle() == "Detalle del cambio"


def test_la_ventana_de_detalle_muestra_la_tabla_de_cambios_y_el_texto_completo(qtbot):
    datos = {
        "fecha": "08/09/2026 11:58:00",
        "usuario": "admin",
        "accion": "Actualización",
        "modulo": "INVENTARIO",
        "extras": [("Producto", "Coca-Cola 1.5L"), ("ID producto", 1)],
        "cambios": [("Descripción", "—", DESC_LARGA), ("Código", "PROD-001", "COCA-15")],
        "detalle": "Producto ID: 1\nCambios: Descripción: None → " + DESC_LARGA,
    }

    d = DetalleAuditoriaDialog(datos)
    qtbot.addWidget(d)

    assert d.tabla_cambios.rowCount() == 2
    assert d.tabla_cambios.item(0, 2).text() == DESC_LARGA  # completa, sin cortar
    assert d.tabla_cambios.editTriggers() == QTableWidget.EditTrigger.NoEditTriggers
    assert DESC_LARGA in d.texto_detalle.toPlainText()
    assert d.texto_detalle.isReadOnly()


def test_en_la_tabla_de_cambios_los_encabezados_se_alinean_como_sus_celdas(qtbot):
    from PySide6.QtCore import Qt

    datos = {
        "fecha": "x",
        "usuario": "admin",
        "accion": "Actualización",
        "modulo": "INVENTARIO",
        "extras": [],
        "cambios": [("Código", "A", "B")],
        "detalle": "t",
    }
    d = DetalleAuditoriaDialog(datos)
    qtbot.addWidget(d)

    for col in range(3):
        encabezado = d.tabla_cambios.horizontalHeaderItem(col).textAlignment()
        celda = d.tabla_cambios.item(0, col).textAlignment()
        assert encabezado & Qt.AlignmentFlag.AlignLeft and celda & Qt.AlignmentFlag.AlignLeft


# -- Paginacion y filtros en la base -------------------------------------------------------------------


def test_el_resumen_cuenta_todo_lo_filtrado_no_solo_la_pagina(dialogo, monkeypatch):
    monkeypatch.setattr(
        "app.ui.producto_auditoria_dialog.AuditoriaService.consultar_auditoria_producto",
        lambda session, **kw: {
            **_respuesta([_aud("CAMBIO_PRECIO", 1)]),
            "total": 120,
            "total_paginas": 3,
            "por_accion": {"CAMBIO_PRECIO": 80, "MOVIMIENTO_STOCK": 40},
        },
    )

    dialogo._cargar_datos()

    assert dialogo.table.rowCount() == 1  # solo la pagina
    assert dialogo.lbl_total_registros.text() == "Total registros: 120"
    assert dialogo.lbl_cambios_precio.text() == "Cambios de precio: 80"
    assert dialogo.lbl_movimientos_stock.text() == "Movimientos de stock: 40"
    assert dialogo.paginacion.total_paginas == 3


def test_la_consulta_pide_la_pagina_actual_con_el_tamano_de_pagina(dialogo, monkeypatch):
    pedidos = []

    def _consulta(session, **kw):
        pedidos.append(kw)
        return {**_respuesta([]), "total_paginas": 5}

    monkeypatch.setattr("app.ui.producto_auditoria_dialog.AuditoriaService.consultar_auditoria_producto", _consulta)
    dialogo.nombre_input.setText("aceite")
    dialogo._aplicar_filtros()
    dialogo.paginacion.fijar_pagina(2)

    dialogo._cargar_datos()

    assert pedidos[-1]["pagina"] == 2 and pedidos[-1]["por_pagina"] == 50
    assert pedidos[-1]["texto"] == "aceite"


def test_cambiar_un_filtro_vuelve_a_la_pagina_1(dialogo, monkeypatch):
    monkeypatch.setattr(
        "app.ui.producto_auditoria_dialog.AuditoriaService.consultar_auditoria_producto",
        lambda session, **kw: {**_respuesta([]), "total_paginas": 5, "pagina": kw["pagina"]},
    )
    dialogo.paginacion.fijar_pagina(4)

    dialogo._aplicar_filtros()

    assert dialogo.pagina_actual == 1


def test_escribir_en_el_filtro_de_nombre_consulta_una_vez_por_pausa(qtbot, dialogo, monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        "app.ui.producto_auditoria_dialog.AuditoriaService.consultar_auditoria_producto",
        lambda session, **kw: llamadas.append(kw) or _respuesta([]),
    )

    for letra in "aceite":
        dialogo.nombre_input.setText(dialogo.nombre_input.text() + letra)

    assert llamadas == []  # ninguna consulta mientras se escribe
    qtbot.waitUntil(lambda: len(llamadas) == 1, timeout=2000)
    assert llamadas[0]["texto"] == "aceite"


def test_limpiar_filtros_consulta_una_sola_vez(dialogo, monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        "app.ui.producto_auditoria_dialog.AuditoriaService.consultar_auditoria_producto",
        lambda session, **kw: llamadas.append(kw) or _respuesta([]),
    )
    dialogo.nombre_input.blockSignals(True)
    dialogo.nombre_input.setText("x")
    dialogo.nombre_input.blockSignals(False)

    dialogo._limpiar_filtros()

    assert len(llamadas) == 1 and llamadas[0]["texto"] is None
