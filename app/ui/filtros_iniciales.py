"""Valor inicial de los filtros de un panel, para devolverlos a como estaban al salir del modulo.

Se guarda en el propio widget (propiedad dinamica de Qt) y no en el panel porque hay paneles que crean filtros mas
tarde, al pedirlos (ver ReportesPanel._asegurar_pagina): basta con registrarlos cuando nacen."""

from PySide6.QtCore import QDate, QSignalBlocker
from PySide6.QtWidgets import QCheckBox, QDateEdit, QWidget

# Las fechas se guardan como distancia a hoy: "desde hace 30 dias" sigue siendo eso si la app queda abierta
# pasada la medianoche.
_DIAS_DESDE_HOY = "filtro_inicial_dias"
_MARCADO = "filtro_inicial_marcado"


def recordar_filtros_iniciales(raiz: QWidget) -> None:
    """Registra fechas y checks de `raiz`. Llamar apenas se construyen; los ya registrados no se tocan."""
    for fecha in raiz.findChildren(QDateEdit):
        if fecha.property(_DIAS_DESDE_HOY) is None:
            fecha.setProperty(_DIAS_DESDE_HOY, QDate.currentDate().daysTo(fecha.date()))
    for check in raiz.findChildren(QCheckBox):
        if check.property(_MARCADO) is None:
            check.setProperty(_MARCADO, check.isChecked())


def restaurar_filtros_iniciales(raiz: QWidget) -> None:
    """Devuelve fechas y checks a lo registrado. Lo que nunca se registro se deja como esta. No emite senales."""
    for fecha in raiz.findChildren(QDateEdit):
        dias = fecha.property(_DIAS_DESDE_HOY)
        if dias is not None:
            with QSignalBlocker(fecha):
                fecha.setDate(QDate.currentDate().addDays(dias))
    for check in raiz.findChildren(QCheckBox):
        marcado = check.property(_MARCADO)
        if marcado is not None:
            with QSignalBlocker(check):
                check.setChecked(marcado)
