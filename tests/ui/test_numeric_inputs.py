"""Tests de NumericLineEdit/NumericValidator (app/ui/numeric_inputs.py) -- widget puro,
sin base de datos: usa pytest-qt (qtbot) para simular tecleo/foco/blur reales sobre un
QApplication offscreen en vez de llamar a los metodos internos directo, asi cubre el
mismo camino (validator -> editingFinished -> reformateo) que recorre un usuario real.

show()+waitExposed() y un qtbot.waitUntil() despues de setFocus() son necesarios: bajo
QT_QPA_PLATFORM=offscreen (CI, ver .github/workflows/tests.yml) el foco logico de Qt
(QApplication.focusWidget) recien se resuelve al procesar el event loop, no de forma
sincronica dentro de la misma llamada a setFocus() -- sin esperarlo, clearFocus()
despues no dispara editingFinished y los asserts de valor ven el campo todavia en None."""

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.ui.numeric_inputs import NumericFieldType, NumericLineEdit


def _mostrar(qtbot, campo: NumericLineEdit) -> None:
    campo.show()
    qtbot.waitExposed(campo)


def _dar_foco(qtbot, campo: NumericLineEdit) -> None:
    _mostrar(qtbot, campo)
    campo.setFocus()
    qtbot.waitUntil(campo.hasFocus)


def _escribir_y_perder_foco(qtbot, campo: NumericLineEdit, texto: str) -> None:
    _dar_foco(qtbot, campo)
    qtbot.keyClicks(campo, texto)
    campo.clearFocus()  # dispara editingFinished, igual que Tab/click afuera


# --- formateo on-blur ------------------------------------------------------------------


def test_formatea_miles_y_decimales_al_perder_foco(qtbot):
    campo = NumericLineEdit(NumericFieldType.AMOUNT)
    qtbot.addWidget(campo)
    _escribir_y_perder_foco(qtbot, campo, "1000,5")
    assert campo.text() == "1.000,50"
    assert campo.get_value() == Decimal("1000.50")


def test_acepta_punto_como_decimal_igual_que_coma(qtbot):
    campo = NumericLineEdit(NumericFieldType.AMOUNT)
    qtbot.addWidget(campo)
    _escribir_y_perder_foco(qtbot, campo, "250.75")
    assert campo.get_value() == Decimal("250.75")
    assert campo.text() == "250,75"


def test_focus_in_quita_agrupador_de_miles_para_editar(qtbot):
    campo = NumericLineEdit(NumericFieldType.AMOUNT)
    qtbot.addWidget(campo)
    campo.set_value(Decimal("1000.50"))
    assert campo.text() == "1.000,50"
    _dar_foco(qtbot, campo)
    assert campo.text() == "1000,50"


# --- get_value/set_value: ida y vuelta DB <-> UI ----------------------------------------


def test_set_value_luego_get_value_devuelve_decimal_exacto(qtbot):
    campo = NumericLineEdit(NumericFieldType.QUANTITY, decimals=4)
    qtbot.addWidget(campo)
    campo.set_value(Decimal("12.3456"))
    assert campo.get_value() == Decimal("12.3456")


def test_get_value_sin_texto_es_none_si_allow_empty(qtbot):
    campo = NumericLineEdit(NumericFieldType.AMOUNT, allow_empty=True)
    qtbot.addWidget(campo)
    assert campo.get_value() is None


def test_campo_vacio_sin_allow_empty_se_normaliza_a_cero(qtbot):
    campo = NumericLineEdit(NumericFieldType.AMOUNT)
    qtbot.addWidget(campo)
    _dar_foco(qtbot, campo)
    campo.clearFocus()
    assert campo.get_value() == Decimal("0")
    assert campo.text() == "0,00"


# --- validador: rechaza caracteres invalidos --------------------------------------------


def test_validador_rechaza_letras(qtbot):
    campo = NumericLineEdit(NumericFieldType.AMOUNT)
    qtbot.addWidget(campo)
    _dar_foco(qtbot, campo)  # selecciona el "0,00" inicial -- letras rechazadas lo dejan intacto
    qtbot.keyClicks(campo, "abc")
    assert campo.text() == "0,00"


def test_validador_rechaza_doble_separador_decimal(qtbot):
    campo = NumericLineEdit(NumericFieldType.AMOUNT)
    qtbot.addWidget(campo)
    _dar_foco(qtbot, campo)
    qtbot.keyClicks(campo, "1,000,50")
    assert campo.text() != "1,000,50"


def test_validador_limita_decimales_segun_field_type(qtbot):
    campo = NumericLineEdit(NumericFieldType.PERCENTAGE)  # 2 decimales
    qtbot.addWidget(campo)
    _dar_foco(qtbot, campo)
    qtbot.keyClicks(campo, "12,345")
    assert campo.text() == "12,34"


def test_count_no_admite_separador_decimal(qtbot):
    campo = NumericLineEdit(NumericFieldType.COUNT)
    qtbot.addWidget(campo)
    _dar_foco(qtbot, campo)
    qtbot.keyClicks(campo, "3,5")
    assert campo.text() == "35"


# --- signo negativo ----------------------------------------------------------------------


def test_quantity_rechaza_signo_negativo_por_defecto(qtbot):
    campo = NumericLineEdit(NumericFieldType.QUANTITY)
    qtbot.addWidget(campo)
    _dar_foco(qtbot, campo)
    qtbot.keyClicks(campo, "-5")
    # el "-" se descarta tecla a tecla (no se inserta nunca); el "5" que sigue si es valido.
    assert campo.text() == "5"


def test_amount_con_allow_negative_acepta_signo(qtbot):
    campo = NumericLineEdit(NumericFieldType.AMOUNT, allow_negative=True)
    qtbot.addWidget(campo)
    _escribir_y_perder_foco(qtbot, campo, "-100")
    assert campo.get_value() == Decimal("-100")
    assert campo.text() == "-100,00"


# --- rango min/max -----------------------------------------------------------------------


def test_percentage_se_ajusta_a_100_si_excede(qtbot):
    campo = NumericLineEdit(NumericFieldType.PERCENTAGE)
    qtbot.addWidget(campo)
    _dar_foco(qtbot, campo)
    qtbot.keyClicks(campo, "150")
    campo.clearFocus()
    assert campo.get_value() == Decimal("100")
    assert campo.toolTip() != ""


def test_dentro_de_rango_no_marca_error(qtbot):
    campo = NumericLineEdit(NumericFieldType.PERCENTAGE)
    qtbot.addWidget(campo)
    _escribir_y_perder_foco(qtbot, campo, "50")
    assert campo.toolTip() == ""


def test_min_value_explicito_pisa_default_del_field_type(qtbot):
    campo = NumericLineEdit(NumericFieldType.AMOUNT, min_value=Decimal("10"))
    qtbot.addWidget(campo)
    _escribir_y_perder_foco(qtbot, campo, "5")
    assert campo.get_value() == Decimal("10")


# --- prefijo/sufijo ------------------------------------------------------------------------


def test_prefijo_y_sufijo_se_muestran_sin_foco_y_se_ocultan_editando(qtbot):
    campo = NumericLineEdit(NumericFieldType.AMOUNT, prefix="$ ")
    qtbot.addWidget(campo)
    campo.set_value(Decimal("1000"))
    assert campo.text() == "$ 1.000,00"
    _dar_foco(qtbot, campo)
    assert campo.text() == "1000,00"


def test_dias_credito_con_sufijo(qtbot):
    campo = NumericLineEdit(NumericFieldType.COUNT, suffix=" dias")
    qtbot.addWidget(campo)
    campo.set_value(30)
    assert campo.text() == "30 dias"
    assert campo.get_value() == Decimal("30")


# --- copiar/pegar ---------------------------------------------------------------------------


def test_pegar_texto_valido_via_clipboard_se_parsea_igual_que_tecleado(qtbot):
    QApplication.clipboard().setText("1234,56")
    campo = NumericLineEdit(NumericFieldType.AMOUNT)
    qtbot.addWidget(campo)
    _dar_foco(qtbot, campo)
    qtbot.keyClick(campo, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    campo.clearFocus()
    assert campo.get_value() == Decimal("1234.56")


def test_pegar_texto_invalido_via_clipboard_es_rechazado(qtbot):
    QApplication.clipboard().setText("12ab34")
    campo = NumericLineEdit(NumericFieldType.AMOUNT)
    qtbot.addWidget(campo)
    _dar_foco(qtbot, campo)  # selecciona el "0,00" inicial
    qtbot.keyClick(campo, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert campo.text() == "0,00"  # paste invalido rechazado entero, selección intacta


# --- Enter: returnPressed debe ver el valor recien tecleado, no el anterior -------------


def test_return_pressed_ve_el_valor_recien_tecleado(qtbot):
    """Regresion reportada por el usuario en Nueva Factura: al editar el precio y
    presionar Enter, el item se agregaba con el precio VIEJO -- recien al presionar
    Enter una segunda vez tomaba el nuevo precio. Causa: QLineEdit nativo emite
    returnPressed() ANTES que editingFinished(), y factura_form_dialog.py conecta
    returnPressed a "agregar item de la fila" -- ese handler leia get_value() antes de
    que el texto recien tecleado se hubiera parseado a self._value. Ver
    NumericLineEdit.keyPressEvent/_commit_value en app/ui/numeric_inputs.py."""
    campo = NumericLineEdit(NumericFieldType.AMOUNT, prefix="$ ")
    campo.set_value(Decimal("1.00"))
    qtbot.addWidget(campo)

    valores_vistos = []
    campo.returnPressed.connect(lambda: valores_vistos.append(campo.get_value()))

    _dar_foco(qtbot, campo)
    qtbot.keyClicks(campo, "25,75")
    qtbot.keyClick(campo, Qt.Key.Key_Return)

    assert valores_vistos == [Decimal("25.75")]
    assert campo.get_value() == Decimal("25.75")
    assert campo.text() == "$ 25,75"  # el reformateo con prefijo tambien llega, despues


def test_return_pressed_se_sigue_emitiendo_con_prefijo(qtbot):
    """Guarda contra la regresion intermedia descubierta al arreglar el bug de arriba:
    comitear el valor reformateando el display (con prefijo/sufijo) ANTES de que Qt
    procese la tecla Enter deja el texto invalido para el validador en ese instante
    (`hasAcceptableInput()` en falso), y QLineEdit directamente deja de emitir
    returnPressed -- peor que el bug original. El commit debe actualizar self._value
    sin tocar el texto mostrado todavia."""
    campo = NumericLineEdit(NumericFieldType.AMOUNT, prefix="$ ")
    qtbot.addWidget(campo)

    disparos = []
    campo.returnPressed.connect(lambda: disparos.append(True))

    _dar_foco(qtbot, campo)
    qtbot.keyClicks(campo, "10")
    qtbot.keyClick(campo, Qt.Key.Key_Return)

    assert disparos == [True]
