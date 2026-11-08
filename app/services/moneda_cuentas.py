"""Moneda en la que se cobra/paga, y la que debe tener la cuenta bancaria que lo recibe.

La cuenta bancaria tiene su moneda (`cuentas_bancarias.moneda`, migracion 0096) y solo puede recibir pagos en esa
moneda:

  * 'USD': metodos en dolares (Zelle, Binance/USDT).
  * 'COP': pagos en pesos colombianos (la tasa COP).
  * 'VES': el resto de los metodos bancarios (transferencia, punto de venta, pago movil).

El efectivo no usa cuenta bancaria.
"""

MONEDA_BS = "VES"
MONEDA_USD = "USD"
MONEDA_COP = "COP"
MONEDAS_CUENTA = (MONEDA_BS, MONEDA_USD, MONEDA_COP)
METODOS_EN_DOLARES = frozenset({"zelle", "binance"})
_NOMBRES = {
    MONEDA_BS: "bolívares (VES)",
    MONEDA_USD: "dólares (USD)",
    MONEDA_COP: "pesos colombianos (COP)",
}
_ETIQUETAS = {
    MONEDA_BS: "Bolívares (VES)",
    MONEDA_USD: "Dólares (USD)",
    MONEDA_COP: "Pesos colombianos (COP)",
}


def moneda_para_metodo(metodo_pago: str | None, moneda_pago: str | None = None) -> str:
    """Moneda que debe tener la cuenta. Un pago en pesos (`moneda_pago='COP'`) va a una cuenta en pesos. Para
    todo lo demas manda el metodo: Zelle/Binance a una cuenta en dolares y cualquier otro metodo bancario a una
    en bolivares. (`moneda_pago` no decide entre USD y VES: los cobros a clientes registran el monto en USD
    aunque se pague por transferencia en bolivares.)"""
    if moneda_pago == MONEDA_COP:
        return MONEDA_COP
    return MONEDA_USD if metodo_pago in METODOS_EN_DOLARES else MONEDA_BS


def nombre_moneda(moneda: str | None) -> str:
    """Para frases: "dólares (USD)"."""
    return _NOMBRES.get(moneda or MONEDA_BS, str(moneda))


def etiqueta_moneda(moneda: str | None) -> str:
    """Para listas y combos: "Dólares (USD)"."""
    return _ETIQUETAS.get(moneda or MONEDA_BS, str(moneda))


def filtrar_cuentas_por_metodo(cuentas, metodo_pago: str | None, moneda_pago: str | None = None) -> list:
    """Solo las cuentas cuya moneda coincide con la del pago."""
    esperada = moneda_para_metodo(metodo_pago, moneda_pago)
    return [c for c in cuentas if (getattr(c, "moneda", None) or MONEDA_BS) == esperada]


def moneda_pago_por_tasa(texto_tasa: str | None) -> str | None:
    """'COP' si la tasa elegida en el combo de un dialogo de cobro es la de pesos ("COP: 4.000,00"); None si no."""
    return MONEDA_COP if (texto_tasa or "").strip().upper().startswith("COP") else None
