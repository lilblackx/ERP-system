"""Diseño del PDF del corte de caja."""

from datetime import datetime
from types import SimpleNamespace as NS

from app.ui.corte_caja_pdf import _FILA_ALTERNA, _fila_movimiento


def _movimiento():
    return NS(
        tipo_movimiento="entrada",
        fecha_registro=datetime(2026, 11, 10, 9, 30),
        descripcion_movimiento="x",
        monto_movimiento=1,
    )


def test_las_filas_impares_van_sombreadas_y_las_pares_no():
    assert _FILA_ALTERNA in _fila_movimiento(_movimiento(), 1)
    assert _FILA_ALTERNA not in _fila_movimiento(_movimiento(), 0)
