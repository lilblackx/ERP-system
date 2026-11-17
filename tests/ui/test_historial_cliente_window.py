"""Historial del cliente: por defecto ("Todos los movimientos") los abonos quedan arriba y las
facturas pendientes abajo; las pagadas se ocultan salvo "Ver todos los movimientos". La
exportacion (Excel/PDF) sigue la vista activa, y el detalle de factura sale de los datos de la
fila (no de su posicion, que cambia al ocultar filas)."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openpyxl import load_workbook

from app.services.historial_cliente import VISTA_FACTURAS, VISTA_PAGOS, VISTA_TODOS, agrupar_pagos_solidos
from app.ui import historial_cliente_window as hw
from app.ui.historial_cliente_window import (
    COLS_HISTORIAL,
    HistorialClienteWindow,
    _filas_historial_para_exportar,
    _tarea_exportar_historial_excel,
)


def _item(tipo, id_factura, numero, monto, **extra):
    base = {
        "tipo_transaccion": tipo,
        "id_cuenta": 1,
        "id_factura": id_factura,
        "id_pago": None,
        "id_nota_credito": None,
        "numero_factura": numero,
        "fecha": "2026-11-01 10:00",
        "fecha_vencimiento": None,
        "monto": Decimal(monto),
        "estado_factura": "EMITIDA" if tipo == "factura" else None,
        "condicion_pago": "credito" if tipo == "factura" else None,
        "dias_credito": None,
        "observaciones": "",
        "metodo_pago": "efectivo" if tipo == "pago" else None,
        "monto_vuelto": Decimal("0.00"),
        "metodo_vuelto": None,
        "saldo_corrido": Decimal("0.00"),
        "monto_pagado": Decimal("0.00"),
        "saldo_factura": Decimal("0.00"),
    }
    base.update(extra)
    return base


# Orden de pantalla (mas reciente arriba): abono, factura 2 con abono, nota de credito, factura 1.
HISTORIAL = [
    _item("pago", 2, "FV-2", "-40.00"),
    _item(
        "factura",
        2,
        "FV-2",
        "100.00",
        monto_pagado=Decimal("40.00"),
        saldo_factura=Decimal("60.00"),
        saldo_corrido=Decimal("60.00"),
    ),
    _item("nota_credito", 1, "NC-1", "15.00", saldo_corrido=Decimal("15.00"), estado_factura="disponible"),
    _item("pago", 1, "FV-1", "-25.00"),
    _item("pago", 1, "FV-1", "-10.00"),
    _item(
        "factura",
        1,
        "FV-1",
        "50.00",
        monto_pagado=Decimal("35.00"),
        saldo_factura=Decimal("15.00"),
        saldo_corrido=Decimal("15.00"),
    ),
]


@pytest.fixture
def ventana(qtbot, monkeypatch):
    monkeypatch.setattr(hw, "obtener_historial_cliente", lambda session, id_cliente, id_usuario: HISTORIAL)
    monkeypatch.setattr(hw, "obtener_saldo_total_pendiente", lambda session, id_cliente, id_usuario: Decimal("75.00"))
    monkeypatch.setattr(hw, "obtener_saldo_total_positivo", lambda session, id_cliente, id_usuario: Decimal("15.00"))
    monkeypatch.setattr(hw.NotaCreditoService, "listar_notas_credito_cliente", lambda *a, **k: [])
    cliente = SimpleNamespace(nombre_razon_social="Cliente de Prueba")
    win = HistorialClienteWindow(MagicMock(return_value=MagicMock()), 1, cliente, id_usuario=1)
    qtbot.addWidget(win)
    return win


def _tipos(win):
    return [win.tabla.item(f, 0).text() for f in range(win.tabla.rowCount())]


def _elegir_vista(win, vista):
    win.vista_combo.setCurrentIndex(win.vista_combo.findData(vista))


def test_por_defecto_muestra_todos_los_movimientos_con_pendientes_abajo(ventana):
    """Vista por defecto "Todos los movimientos": abonos y notas arriba en su lugar;
    solo las facturas pendientes (FV-2 y FV-1, ambas con saldo) bajan al final."""
    assert ventana._vista == VISTA_TODOS
    assert _tipos(ventana) == ["Abono", "Nota Crédito", "Abono", "Abono", "Factura", "Factura"]
    assert not ventana.lbl_total_pagado.isVisible()


def test_la_vista_facturas_sigue_ocultando_los_abonos(ventana):
    _elegir_vista(ventana, VISTA_FACTURAS)
    assert _tipos(ventana) == ["Nota Crédito", "Factura", "Factura"]


def test_la_factura_muestra_cuanto_se_pago_y_cuanto_falta_aunque_los_abonos_esten_ocultos(ventana):
    col_pagado, col_saldo = COLS_HISTORIAL.index("Pagado"), COLS_HISTORIAL.index("Saldo Factura")

    # En la vista por defecto (todos) las facturas pendientes son las filas 4 y 5.
    assert ventana.tabla.item(4, col_pagado).text() == "$40.00"  # FV-2
    assert ventana.tabla.item(4, col_saldo).text() == "$60.00"
    assert ventana.tabla.item(5, col_pagado).text() == "$35.00"  # FV-1
    assert ventana.tabla.item(0, col_pagado).text() == "—"  # el abono no lleva pagado/saldo


def test_todos_los_movimientos_muestra_todo_con_los_abonos_en_negativo(ventana):
    _elegir_vista(ventana, VISTA_TODOS)

    # Los abonos quedan arriba en su lugar; solo las facturas pendientes bajan al final.
    assert _tipos(ventana) == ["Abono", "Nota Crédito", "Abono", "Abono", "Factura", "Factura"]
    assert ventana.tabla.item(0, COLS_HISTORIAL.index("Monto")).text() == "$-40.00"


def test_solo_pagos_muestra_los_abonos_en_positivo_y_el_total(ventana):
    _elegir_vista(ventana, VISTA_PAGOS)

    assert _tipos(ventana) == ["Abono", "Abono", "Abono"]
    montos = [ventana.tabla.item(f, COLS_HISTORIAL.index("Monto")).text() for f in range(3)]
    assert montos == ["$40.00", "$25.00", "$10.00"]
    assert ventana.lbl_total_pagado.isVisibleTo(ventana)
    assert "75.00" in ventana.lbl_total_pagado.text()  # 40 + 25 + 10


def test_agrupar_pagos_solidos_fusiona_el_abono_general_en_un_solo_pago():
    """Un abono general crea un pago por factura en la BD; en "Solo pagos" debe verse
    como un solo monto. Los pagos con distinto grupo (o sin grupo) quedan separados."""
    grupo_abono = ("2026-11-01 10:00", "transferencia", "VES", 7, None, 900, "REF-1")
    otro_grupo = ("2026-11-01 11:00", "efectivo", "USD", None, 2, None, None)
    items = [
        _item(
            "pago",
            1,
            "FV-1",
            "-40.00",
            grupo_abono=grupo_abono,
            monto_bolivares=Decimal("36000.00"),
            tasa_cambio=Decimal("900.00"),
            banco="Banesco",
        ),
        _item(
            "pago",
            2,
            "FV-2",
            "-60.00",
            grupo_abono=grupo_abono,
            monto_bolivares=Decimal("54000.00"),
            tasa_cambio=Decimal("900.00"),
            banco="Banesco",
        ),
        _item("pago", 3, "FV-3", "-25.00", grupo_abono=otro_grupo),
        _item("pago", 4, "FV-4", "-10.00"),  # sin grupo: pago individual
    ]

    resultado = agrupar_pagos_solidos(items)

    assert len(resultado) == 3
    solido = resultado[0]
    assert solido["numero_factura"] == "Varios"
    assert solido["id_factura"] is None
    assert solido["monto"] == Decimal("-100.00")  # -40 + -60
    assert solido["observaciones"] == "Bs. 90,000.00 - 900.00 - Banesco"
    assert resultado[1]["monto"] == Decimal("-25.00")
    assert resultado[1]["numero_factura"] == "FV-3"  # grupo de uno: no se toca
    assert resultado[2]["numero_factura"] == "FV-4"


def test_volver_a_facturas_vuelve_a_ocultar_los_abonos_y_el_total(ventana):
    _elegir_vista(ventana, VISTA_PAGOS)
    _elegir_vista(ventana, VISTA_FACTURAS)

    assert _tipos(ventana) == ["Nota Crédito", "Factura", "Factura"]
    assert not ventana.lbl_total_pagado.isVisibleTo(ventana)


def test_el_saldo_pendiente_no_depende_de_la_vista(ventana):
    texto = ventana.lbl_saldo_pendiente.text()
    _elegir_vista(ventana, VISTA_PAGOS)

    assert ventana.lbl_saldo_pendiente.text() == texto


def test_la_factura_pagada_se_oculta_solo_si_no_se_piden_todos_los_movimientos():
    """_ordenar_historial: por defecto las facturas liquidadas (saldo 0) no aparecen;
    con ver_todos=True vuelven a su lugar cronologico. Las pendientes van siempre al
    final, de la mas antigua a la mas reciente."""
    historial = [
        _item(
            "factura",
            3,
            "FV-3",
            "80.00",
            fecha="2026-11-01 10:00",
            saldo_factura=Decimal("0.00"),
            saldo_corrido=Decimal("0.00"),
        ),  # pagada
        _item(
            "factura",
            2,
            "FV-2",
            "100.00",
            fecha="2026-10-01 10:00",
            saldo_factura=Decimal("40.00"),
            saldo_corrido=Decimal("40.00"),
        ),  # parcial
        _item(
            "factura",
            1,
            "FV-1",
            "50.00",
            fecha="2026-09-01 10:00",
            saldo_factura=Decimal("50.00"),
            saldo_corrido=Decimal("90.00"),
        ),  # pendiente
    ]

    sin_todos = [item["numero_factura"] for item in hw._ordenar_historial(historial, ver_todos=False)]
    con_todos = [item["numero_factura"] for item in hw._ordenar_historial(historial, ver_todos=True)]

    assert sin_todos == ["FV-1", "FV-2"]  # FV-3 oculta; pendientes: la mas antigua primero
    assert con_todos == ["FV-3", "FV-1", "FV-2"]  # FV-3 arriba en su lugar; pendientes abajo


def test_el_detalle_sale_de_los_datos_de_la_fila_no_de_su_posicion(ventana, monkeypatch):
    """Con la vista por defecto las pendientes van al final (filas 4 y 5) y los abonos
    arriba. El detalle sale de los datos guardados en la fila, no de su posicion."""
    avisos = []
    monkeypatch.setattr(hw.MessageBox, "information", staticmethod(lambda *a, **k: avisos.append(a)))

    ventana.tabla.selectRow(5)
    assert ventana._fila_seleccionada_id_factura() == 1  # FV-1

    ventana.tabla.selectRow(4)
    assert ventana._fila_seleccionada_id_factura() == 2  # FV-2

    ventana.tabla.selectRow(1)  # nota de credito: no abre factura
    assert ventana._fila_seleccionada_id_factura() is None
    assert avisos


def test_en_solo_pagos_el_detalle_abre_la_factura_del_pago(ventana):
    _elegir_vista(ventana, VISTA_PAGOS)

    ventana.tabla.selectRow(1)  # abono de 25.00 a FV-1
    assert ventana._fila_seleccionada_id_factura() == 1


# -- Exportacion: sigue la vista activa -----------------------------------------------------------------


@pytest.fixture
def _sin_bd(monkeypatch):
    monkeypatch.setattr(hw, "obtener_historial_cliente", lambda session, id_cliente, id_usuario: HISTORIAL)


def test_la_exportacion_sigue_la_vista(_sin_bd):
    tipos = lambda vista: [f[0] for f in _filas_historial_para_exportar(None, 1, 1, vista)]  # noqa: E731

    assert tipos(VISTA_FACTURAS) == ["Nota Crédito", "Factura", "Factura"]
    assert tipos(VISTA_PAGOS) == ["Abono", "Abono", "Abono"]
    assert len(tipos(VISTA_TODOS)) == 6


def test_las_filas_exportadas_tienen_una_celda_por_columna_y_tipo_en_la_primera(_sin_bd):
    filas = _filas_historial_para_exportar(None, 1, 1, VISTA_TODOS)

    assert all(len(f) == len(COLS_HISTORIAL) for f in filas)
    assert COLS_HISTORIAL[0] == "Tipo"
    assert {f[0] for f in filas} == {"Factura", "Abono", "Nota Crédito"}  # antes salia el id de cuenta


def test_en_solo_pagos_los_montos_exportados_son_positivos_y_numericos(_sin_bd):
    filas = _filas_historial_para_exportar(None, 1, 1, VISTA_PAGOS)

    montos = [f[COLS_HISTORIAL.index("Monto")] for f in filas]
    assert montos == [Decimal("40.00"), Decimal("25.00"), Decimal("10.00")]


def test_el_excel_de_facturas_trae_pagado_y_saldo_y_el_titulo_indica_la_vista(_sin_bd, tmp_path):
    ruta = tmp_path / "h.xlsx"

    _tarea_exportar_historial_excel(None, str(ruta), 1, 1, VISTA_FACTURAS, "Cliente de Prueba")

    hoja = load_workbook(ruta).active
    assert hoja is not None
    filas = [[c.value for c in fila] for fila in hoja.iter_rows()]
    assert filas[0][0] == "Historial del Cliente: Cliente de Prueba - Facturas y notas de crédito"
    cabecera = next(i for i, f in enumerate(filas) if f[0] == "Tipo")
    datos = filas[cabecera + 1 :]
    assert [f[0] for f in datos] == ["Nota Crédito", "Factura", "Factura"]  # sin abonos, pendientes al final
    col_pagado, col_saldo = COLS_HISTORIAL.index("Pagado"), COLS_HISTORIAL.index("Saldo Factura")
    assert (datos[1][col_pagado], datos[1][col_saldo]) == (40, 60)  # FV-2, numeros no texto
