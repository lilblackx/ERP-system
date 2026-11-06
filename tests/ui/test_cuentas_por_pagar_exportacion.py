"""Total de la exportacion de cuentas por pagar: las celdas de saldo ya son numeros (no el texto "$1,234.50"
de la pantalla), asi que el total las suma sin parsear texto y conserva el signo."""

from decimal import Decimal

from app.services.exportacion import valor_para_exportar
from app.ui.cuentas_por_pagar_panel import CuentasPorPagarPanel


def test_total_suma_los_saldos_numericos_incluidos_los_negativos():
    filas = [["C-1", "Prov A", Decimal("100.50")], ["C-2", "Prov B", Decimal("-20.25")], ["C-3", "Prov C", 10]]

    assert CuentasPorPagarPanel._total_saldo_pendiente(filas) == Decimal("90.25")


def test_total_ignora_filas_sin_saldo_o_con_texto_no_reconocible():
    filas = [["C-1", "Prov A", "N/A"], ["C-2", "Prov B"], ["C-3", "Prov C", Decimal("5.00")]]

    assert CuentasPorPagarPanel._total_saldo_pendiente(filas) == Decimal("5.00")


def test_el_texto_de_la_pantalla_pasa_a_numero_antes_de_totalizar():
    # Lo que _obtener_filas_para_exportar() hace con cada celda de la tabla.
    filas = [["C-1", "Prov A", valor_para_exportar("$1,234.50")], ["C-2", "Prov B", valor_para_exportar("$-34.50")]]

    assert CuentasPorPagarPanel._total_saldo_pendiente(filas) == Decimal("1200.00")
