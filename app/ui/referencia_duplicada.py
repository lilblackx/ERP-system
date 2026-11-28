"""Aviso de referencia bancaria repetida al registrar un cobro de cliente.

Cuando el usuario digita en el campo Referencia un valor que ya tiene un pago
registrado (cartera normal o BCV, cualquier banco), se le muestra una ventana con
los datos de ese pago anterior -- monto, cliente, fecha y banco -- para que pueda
detectar un cobro duplicado o un error de digitacion antes de confirmar. No bloquea:
el usuario decide si registra igual (referencias reutilizadas legitimamente existen,
p. ej. una misma transferencia que cubre varias facturas en abonos distintos).
"""

import logging
from decimal import Decimal

from PySide6.QtWidgets import QMessageBox

from app.services.pagos import PagoService
from app.ui.message_box import MessageBox

logger = logging.getLogger(__name__)

_METODOS = {
    "efectivo": "Efectivo",
    "transferencia": "Transferencia",
    "zelle": "Zelle",
    "usdt": "USDT",
    "binance": "Binance",
    "pago_movil": "Pago móvil",
    "punto_de_venta": "Punto de venta",
}


def _formatear_monto(fila: dict) -> str:
    """El monto como se recibio: en la moneda original si la hubo (Bs en pagos VES,
    USD en Zelle/USDT), si no el equivalente en dolares."""
    moneda = fila.get("moneda") or "USD"
    origen = fila.get("monto_moneda_origen")
    if moneda != "USD" and origen is not None:
        if moneda in ("VES", "BS", "BOLIVARES"):
            return f"Bs {Decimal(origen):,.2f}"
        return f"{moneda} {Decimal(origen):,.2f}"
    return f"${Decimal(fila['monto']):,.2f}"


def advertir_referencia_duplicada(parent, session, referencia) -> bool:
    """True si se puede seguir con el registro (sin coincidencias o el usuario
    confirmo); False si el usuario cancelo tras ver el aviso."""
    try:
        pagos = PagoService.buscar_pagos_por_referencia(session, referencia)
    except Exception:
        # El aviso es una ayuda, no una validacion: si la busqueda falla no se
        # bloquea el cobro por ella.
        logger.exception("No se pudo verificar la referencia duplicada")
        return True
    if not pagos:
        return True

    lineas = []
    for pago in pagos:
        fecha = pago["fecha"].strftime("%d/%m/%Y %H:%M") if pago["fecha"] else ""
        metodo = _METODOS.get(pago["metodo"] or "", pago["metodo"] or "")
        lineas.append(
            f"• {_formatear_monto(pago)} - {pago['cliente']}\n"
            f"  {fecha} | {pago['banco']} | {metodo} ({pago['cartera']})"
        )
    texto = (
        f'La referencia "{(referencia or "").strip()}" ya está registrada en '
        f"{len(pagos)} pago(s):\n\n" + "\n".join(lineas) + "\n\n"
        "¿Desea registrar el pago de todos modos?"
    )
    return MessageBox.question(parent, "Referencia ya registrada", texto) == QMessageBox.StandardButton.Yes
