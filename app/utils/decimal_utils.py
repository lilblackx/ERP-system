from decimal import Decimal, getcontext

getcontext().prec = 28  # ajustar precisión si es necesario


def to_decimal(value, default=Decimal("0")):
    """Convierte varios tipos a Decimal de forma segura.

    Convierte float/int/str/Decimal a Decimal, usando str(float) para evitar
    artefactos de precisión binaria. Returns default si value es None.
    """
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # convertir vía str para evitar problemas de precisión binaria
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value)
    raise TypeError(f"Can't convert {type(value)} to Decimal")


def formatear_usd(valor) -> str:
    """'$1,234.56' / '-$1,234.56': signo delante del simbolo, para montos que pueden
    quedar negativos (p. ej. el saldo a favor en el estado de cuenta del cliente)."""
    v = float(to_decimal(valor))
    return f"-${abs(v):,.2f}" if v < 0 else f"${v:,.2f}"
