"""Input numerico de reemplazo para QSpinBox/QDoubleSpinBox en toda la UI.

NumericLineEdit valida caracter a caracter mientras se tipea (solo digitos, un signo
opcional, un separador decimal), y recien al perder el foco normaliza el texto a formato
con separador de miles + decimal (es_VE: "." miles, "," decimal) y expone el valor como
Decimal via get_value()/set_value() -- listo para las columnas Numeric() de SQL Server
(ver docs/ESTADO_DEL_PROYECTO.md, seccion de modelos). Formatear solo on-blur (no en cada
tecla) evita el salto de cursor que produce reformatear un QLineEdit mientras el usuario
sigue escribiendo.

El prefijo/sufijo (ej. "$ ", " dias") se maneja igual que QAbstractSpinBox: visible con el
campo sin foco, se retira automaticamente al entrar a editar y se vuelve a agregar al
salir -- asi el validador de tecleo nunca necesita lidiar con texto no numerico.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import Enum

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QLineEdit

from app.ui.styles import COLOR_BORDER, COLOR_DANGER, COLOR_PRIMARY, COLOR_TEXT_DARK

_GROUP_SEP = "."
_DECIMAL_SEP = ","


class NumericFieldType(Enum):
    AMOUNT = "amount"
    QUANTITY = "quantity"
    PERCENTAGE = "percentage"
    COUNT = "count"
    RATE = "rate"


# Defaults por tipo de campo -- todos pisables via los parametros del constructor
# (ej. cantidad_solicitada de compra_oc_detalle usa 4 decimales en vez de los 2 de
# QUANTITY, ver app/db/models.py).
_DEFAULTS: dict[NumericFieldType, dict[str, object]] = {
    NumericFieldType.AMOUNT: {"decimals": 2, "min_value": Decimal("0"), "max_value": Decimal("999999999.99")},
    NumericFieldType.QUANTITY: {"decimals": 2, "min_value": Decimal("0"), "max_value": Decimal("999999.99")},
    NumericFieldType.PERCENTAGE: {"decimals": 2, "min_value": Decimal("0"), "max_value": Decimal("100")},
    NumericFieldType.COUNT: {"decimals": 0, "min_value": Decimal("0"), "max_value": Decimal("999999")},
    NumericFieldType.RATE: {"decimals": 2, "min_value": Decimal("0.01"), "max_value": Decimal("999999")},
}


def _formatear(valor: Decimal, decimals: int, agrupar: bool) -> str:
    if decimals:
        valor = valor.quantize(Decimal(1).scaleb(-decimals))
    else:
        valor = valor.to_integral_value()
    negativo = valor < 0
    texto = f"{abs(valor):.{decimals}f}"
    entero, _, frac = texto.partition(".")
    if agrupar and len(entero) > 3:
        grupos = []
        while len(entero) > 3:
            grupos.insert(0, entero[-3:])
            entero = entero[:-3]
        grupos.insert(0, entero)
        entero = _GROUP_SEP.join(grupos)
    resultado = f"{entero}{_DECIMAL_SEP}{frac}" if decimals else entero
    return f"-{resultado}" if negativo else resultado


def _parse_raw(texto: str, decimals: int) -> Decimal | None:
    """Parsea texto crudo tecleado por el usuario -- el validador nunca deja pasar mas de
    un separador (',' o '.', cualquiera de los dos vale como decimal mientras se tipea),
    asi que a diferencia de get_value() esto no necesita distinguir agrupador de miles."""
    texto = texto.strip()
    if not texto or texto == "-":
        return None
    negativo = texto.startswith("-")
    cuerpo = texto[1:] if negativo else texto
    if not cuerpo:
        return None
    for sep in (",", "."):
        if sep in cuerpo:
            entero, _, frac = cuerpo.partition(sep)
            cuerpo = f"{entero or '0'}.{frac}"
            break
    try:
        valor = Decimal(cuerpo)
    except InvalidOperation:
        return None
    valor = valor.to_integral_value() if decimals == 0 else valor.quantize(Decimal(1).scaleb(-decimals))
    return -valor if negativo else valor


class NumericValidator(QValidator):
    """Acepta cualquier prefijo parcial de un numero valido mientras se tipea. La
    validacion de RANGO (min/max) se hace aparte, on-blur (NumericLineEdit), no aca:
    bloquear por rango tecla a tecla impediria borrar un digito de un numero fuera de
    rango para corregirlo."""

    def __init__(self, decimals: int, allow_negative: bool, parent=None):
        super().__init__(parent)
        self.decimals = decimals
        self.allow_negative = allow_negative

    def validate(self, text: str, pos: int):  # noqa: N802 (override de Qt)
        if text in ("", "-"):
            if text == "-" and not self.allow_negative:
                return QValidator.State.Invalid, text, pos
            return QValidator.State.Intermediate, text, pos

        cuerpo = text
        if cuerpo[0] in "+-":
            if cuerpo[0] == "+" or (cuerpo[0] == "-" and not self.allow_negative):
                return QValidator.State.Invalid, text, pos
            cuerpo = cuerpo[1:]

        if cuerpo == "":
            return QValidator.State.Intermediate, text, pos

        num_separadores = cuerpo.count(",") + cuerpo.count(".")
        if num_separadores > 1:
            return QValidator.State.Invalid, text, pos

        entero, frac = cuerpo, ""
        if num_separadores == 1:
            if self.decimals == 0:
                return QValidator.State.Invalid, text, pos
            for sep in (",", "."):
                if sep in cuerpo:
                    entero, _, frac = cuerpo.partition(sep)
                    break
            if len(frac) > self.decimals:
                return QValidator.State.Invalid, text, pos

        if (entero and not entero.isdigit()) or (frac and not frac.isdigit()):
            return QValidator.State.Invalid, text, pos

        return QValidator.State.Acceptable, text, pos


class NumericLineEdit(QLineEdit):
    """QLineEdit con formateo/validacion numerica. Uso tipico::

    self.costo_input = NumericLineEdit(NumericFieldType.AMOUNT, prefix="$ ")
    ...
    self.costo_input.set_value(producto.costo_producto)
    ...
    producto.costo_producto = self.costo_input.get_value()
    """

    valueChanged = Signal(object)  # Decimal | None

    _ESTILO_BASE = f"""
        QLineEdit {{
            background-color: #FFFFFF;
            border: 1px solid {COLOR_BORDER};
            border-radius: 6px;
            padding: 5px 10px;
            font-size: 13px;
            color: {COLOR_TEXT_DARK};
            min-height: 20px;
        }}
        QLineEdit:focus {{
            border: 1.5px solid {COLOR_PRIMARY};
        }}
    """
    _ESTILO_ERROR = f"""
        QLineEdit {{
            background-color: #FEF2F2;
            border: 1.5px solid {COLOR_DANGER};
            border-radius: 6px;
            padding: 5px 10px;
            font-size: 13px;
            color: {COLOR_TEXT_DARK};
            min-height: 20px;
        }}
    """

    def __init__(
        self,
        field_type: NumericFieldType,
        *,
        decimals: int | None = None,
        min_value: Decimal | None = ...,
        max_value: Decimal | None = ...,
        allow_negative: bool = False,
        allow_empty: bool = False,
        prefix: str = "",
        suffix: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        defaults = _DEFAULTS[field_type]
        self.field_type = field_type
        self.decimals = defaults["decimals"] if decimals is None else decimals
        if min_value is ...:
            # Si el caller pide negativos pero no fija un piso explicito, el piso >=0 del
            # field_type por defecto los volveria a bloquear en la practica (se tipean,
            # pero el clamp de rango los sube de nuevo a 0 al perder el foco) -- sin piso
            # en ese caso en vez de heredar el default pensado para el caso no-negativo.
            self.min_value = None if allow_negative else defaults["min_value"]
        else:
            self.min_value = min_value
        self.max_value = defaults["max_value"] if max_value is ... else max_value
        self.allow_negative = allow_negative
        self.allow_empty = allow_empty
        self.prefix = prefix
        self.suffix = suffix
        self._value: Decimal | None = None if allow_empty else Decimal(0)
        self._tooltip_normal = ""

        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setValidator(NumericValidator(self.decimals, self.allow_negative, self))
        self.setStyleSheet(self._ESTILO_BASE)
        self.editingFinished.connect(self._on_editing_finished)

        self._refresh_display()

    def focusInEvent(self, event) -> None:  # noqa: N802 (override de Qt)
        super().focusInEvent(event)
        if self._value is not None:
            super().setText(_formatear(self._value, self.decimals, agrupar=False))
        self.selectAll()

    def keyPressEvent(self, event) -> None:  # noqa: N802 (override de Qt)
        # Enter/Return: QLineEdit nativo emite returnPressed() ANTES que editingFinished()
        # (fuente de Qt, keyPressEvent de QLineEdit) -- un caller tipico conecta
        # returnPressed a "agregar item de la fila" (factura_form_dialog.py,
        # compras.py), y ese handler llamaria get_value() leyendo todavia el valor
        # VIEJO, porque el commit del texto recien tecleado a self._value no habia
        # corrido aun. Bug real reportado por el usuario: el precio tecleado no se
        # tomaba hasta presionar Enter una segunda vez. Se comitea el VALOR a mano antes
        # de dejar que Qt dispare returnPressed -- pero sin reformatear el display
        # todavia (eso incluiria prefix/suffix, ej. "$ "), porque el propio keyPressEvent
        # nativo de QLineEdit solo emite returnPressed si el texto ACTUAL sigue siendo
        # valido para el validador (`hasAcceptableInput()`) -- un texto ya reformateado
        # con prefijo lo haria fallar y returnPressed nunca se emitiria, peor que el bug
        # original. El reformateo completo llega de todos modos via editingFinished
        # nativo, que Qt dispara justo despues.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._commit_value()
            super().keyPressEvent(event)
            # En una fila de factura/compra (cantidad -> precio -> siguiente linea)
            # forzar al usuario a usar el mouse o Tab despues de cada Enter rompe el
            # flujo de carga rapida por teclado -- avanzar al siguiente widget en el
            # tab-order imita la tecla Enter de una calculadora/POS real.
            self.focusNextChild()
            return
        super().keyPressEvent(event)

    def _commit_value(self) -> None:
        """Parsea el texto crudo actual a self._value (con clamp de rango) y actualiza
        estilo/tooltip/signal -- sin tocar el texto mostrado. Separado de
        _on_editing_finished para que Enter pueda comitear el valor ANTES de que Qt
        dispare returnPressed, sin todavia reformatear con prefix/suffix (ver
        keyPressEvent)."""
        crudo = self.text()
        valor = _parse_raw(crudo, self.decimals)
        if valor is None:
            valor = None if self.allow_empty else Decimal(0)

        fuera_de_rango = False
        if valor is not None:
            if self.min_value is not None and valor < self.min_value:
                valor = self.min_value
                fuera_de_rango = True
            if self.max_value is not None and valor > self.max_value:
                valor = self.max_value
                fuera_de_rango = True

        self._value = valor
        self.setStyleSheet(self._ESTILO_ERROR if fuera_de_rango else self._ESTILO_BASE)
        if fuera_de_rango:
            super().setToolTip(f"Ajustado al rango permitido: {self.min_value} - {self.max_value}")
        else:
            super().setToolTip(self._tooltip_normal)
        self.valueChanged.emit(self._value)

    def _on_editing_finished(self) -> None:
        self._commit_value()
        self._refresh_display()

    def setToolTip(self, tooltip: str) -> None:  # noqa: N802 (override de Qt)
        # Recuerda el tooltip "normal" puesto por el caller (ej. una ayuda fija como "0 =
        # contado") por separado del tooltip dinamico de rango-excedido -- sin esto,
        # _on_editing_finished lo pisaria con "" en el primer blur sin error.
        self._tooltip_normal = tooltip
        super().setToolTip(tooltip)

    def _refresh_display(self) -> None:
        if self._value is None:
            super().setText("")
            return
        super().setText(f"{self.prefix}{_formatear(self._value, self.decimals, agrupar=True)}{self.suffix}")

    def get_value(self) -> Decimal | None:
        return self._value

    def set_value(self, value: Decimal | int | float | str | None) -> None:
        if value is None:
            self._value = None
        else:
            valor = value if isinstance(value, Decimal) else Decimal(str(value))
            if self.min_value is not None and valor < self.min_value:
                valor = self.min_value
            if self.max_value is not None and valor > self.max_value:
                valor = self.max_value
            self._value = (
                valor.quantize(Decimal(1).scaleb(-self.decimals)) if self.decimals else valor.to_integral_value()
            )
        self._refresh_display()
        self.setStyleSheet(self._ESTILO_BASE)
        super().setToolTip(self._tooltip_normal)
