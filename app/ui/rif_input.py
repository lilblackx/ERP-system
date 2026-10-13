"""Campos de RIF / cedula con formato automatico (ver app/utils/rif.py).

Se aplica al terminar de editar el campo (perder foco o Enter), no tecla a tecla: reformatear
mientras se escribe mueve el cursor y estorba al corregir. El formateo tambien se puede forzar a
mano (la funcion devuelta) para quien lee el campo antes de que pierda el foco."""

from collections.abc import Callable

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QComboBox, QLineEdit

from app.utils.rif import formatear_numero, formatear_rif, partir

# Letra opcional, separadores y hasta 12 digitos/puntos/espacios, con verificador "-d" opcional.
# Deja pegar "J-07000750-8", "j07000750-8" o "070007508"; lo demas lo ordena el formateador.
_PATRON_ENTRADA = QRegularExpression(r"^[JGVEPCjgvepc]?[\s.\-]*[0-9.\s]{1,12}(-[0-9])?$")


def conectar_formato_identificacion(
    campo: QLineEdit,
    tipo_combo: QComboBox | None = None,
    letra_defecto: str | None = None,
) -> Callable[[], None]:
    """Da formato al texto de `campo` al terminar de editarlo.

    Con `tipo_combo` (cliente/proveedor: la letra va en su propio combo) el campo queda solo con
    el numero ("07000750-8") y, si el usuario pego o escribio la letra, el combo se pone en ella.
    Sin `tipo_combo` (RIF completo en un solo campo) queda "J-07000750-8", usando `letra_defecto`
    cuando el texto no trae letra. Un texto que no parece RIF/cedula no se toca.
    Devuelve la funcion que aplica el formato, por si hay que forzarlo antes de leer el campo."""
    campo.setValidator(QRegularExpressionValidator(_PATRON_ENTRADA, campo))

    def formatear() -> None:
        texto = campo.text().strip()
        partes = partir(texto)
        if partes is None:
            return
        if tipo_combo is None:
            campo.setText(formatear_rif(texto, letra_defecto))
            return
        letra = partes[0]
        if letra:
            indice = tipo_combo.findText(letra)
            if indice >= 0:
                tipo_combo.setCurrentIndex(indice)
        campo.setText(formatear_numero(texto))

    campo.editingFinished.connect(formatear)
    return formatear
