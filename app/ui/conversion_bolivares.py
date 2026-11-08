"""Conversion USD <-> Bs/COP de los dialogos de cobro a clientes (CxC y CxC BCV).

Segun el metodo de pago hay un solo campo que se escribe y el otro se calcula:

  * Metodos en dolares (Zelle, Binance): el cliente paga en dolares y el dinero entra a una cuenta en dolares. Se
    escribe el monto en $ (precargado con la deuda) y NO hay bloque de Bs ni de tasa: no hay nada que convertir.
  * Metodos en bolivares (transferencia, punto de venta): se escribe el monto en Bs y el monto en $ sale de
    dividirlo entre la tasa (solo lectura). Si se elige la tasa COP el bloque habla de pesos y la cuenta de
    origen debe ser una cuenta en pesos.

Antes TODO metodo bancario trabajaba en el segundo modo: al elegir Zelle el monto en $ pasaba a ser un calculo
sobre los Bs (en 0 al abrir) y la tasa, y quedaba bloqueado -- un monto en dolares que el cajero no podia
escribir y que cualquier cambio de la tasa o de los Bs alteraba en silencio. Ademas se ofrecian cuentas en
bolivares para cobrar en dolares (ver moneda_cuentas.py).
"""

from decimal import Decimal

from app.services.moneda_cuentas import METODOS_EN_DOLARES, moneda_pago_por_tasa

_ESTILO_SOLO_LECTURA = "background-color: #F1F5F9;"


class ConversionBolivaresMixin:
    """Va ANTES de QDialog en las bases. Espera `metodo_combo`, `origen_combo`, `monto_input`, `bolivares_input`,
    `tasa_input` y `lbl_bolivares`."""

    _convirtiendo = False  # evita que escribir un campo dispare el recalculo del otro en bucle

    def _cambio_la_moneda_de_la_tasa(self) -> bool:
        """True si la tasa elegida paso a (o dejo de) ser la de pesos: la cuenta de origen debe ser en la moneda
        del pago, asi que la lista de cuentas hay que volver a armarla."""
        es_cop = moneda_pago_por_tasa(self.tasa_combo.currentText()) is not None
        cambio = es_cop != getattr(self, "_tasa_es_cop", False)
        self._tasa_es_cop = es_cop
        return cambio

    def _es_pago_bancario(self) -> bool:
        origen = self.origen_combo.currentData()
        return self.metodo_combo.currentData() != "efectivo" and bool(origen) and origen[0] == "banco"

    def _es_metodo_en_dolares(self) -> bool:
        return self.metodo_combo.currentData() in METODOS_EN_DOLARES

    def _aplicar_modo_conversion(self, mostrar_bolivares: bool) -> None:
        """Deja editable el campo que es la fuente del monto y en solo lectura el derivado. En los metodos en
        dolares se oculta el bloque de bolivares (la cuenta es en dolares y no hay nada que convertir); si se paga
        en pesos (tasa COP) el bloque habla de pesos."""
        en_dolares = bool(mostrar_bolivares) and self._es_metodo_en_dolares()
        en_pesos = bool(mostrar_bolivares) and not en_dolares and moneda_pago_por_tasa(self.tasa_combo.currentText())
        usd_derivado = bool(mostrar_bolivares) and not en_dolares

        self.campos_bolivares_widget.setVisible(bool(mostrar_bolivares) and not en_dolares)
        self.monto_input.setReadOnly(usd_derivado)
        self.monto_input.setStyleSheet(_ESTILO_SOLO_LECTURA if usd_derivado else "")
        self.bolivares_input.setReadOnly(False)
        self.bolivares_input.setStyleSheet("")
        self.lbl_bolivares.setText("Monto (COP)" if en_pesos else "Monto (Bs)")
        self.lbl_tasa_campo.setText("Tasa del día (COP/USD)" if en_pesos else "Tasa del día (Bs/USD)")
        if mostrar_bolivares:
            self._calcular_bolivares_desde_usd()

    def _calcular_monto_usd(self) -> None:
        """Monto en bolivares (o pesos) / tasa -> monto en $, solo en los metodos que no son en dolares. En los
        metodos en dolares el $ no se toca."""
        if self._convirtiendo or not self._es_pago_bancario() or self._es_metodo_en_dolares():
            return
        bolivares = self.bolivares_input.get_value() or Decimal("0")
        tasa = self.tasa_input.get_value() or Decimal("0")
        if tasa <= 0:
            return
        self._convirtiendo = True
        try:
            # Sin Bs no hay monto: el campo queda vacio y el dialogo lo rechaza al aplicar (antes quedaba en 0,01).
            self.monto_input.set_value(bolivares / tasa if bolivares > 0 else None)
            if self.monto_input.isReadOnly():
                # set_value() reaplica el estilo base del widget
                self.monto_input.setStyleSheet(_ESTILO_SOLO_LECTURA)
        finally:
            self._convirtiendo = False

    def _calcular_bolivares_desde_usd(self) -> None:
        """Monto en $ x tasa -> monto en bolivares (la referencia de los metodos en dolares; en los de bolivares solo
        sirve para precargar el campo al abrir o al cambiar de metodo)."""
        if self._convirtiendo or not self._es_pago_bancario():
            return
        monto_usd = self.monto_input.get_value() or Decimal("0")
        tasa = self.tasa_input.get_value() or Decimal("0")
        if tasa <= 0 or monto_usd <= 0:
            return
        self._convirtiendo = True
        try:
            self.bolivares_input.set_value(monto_usd * tasa)
            if self.bolivares_input.isReadOnly():
                self.bolivares_input.setStyleSheet(_ESTILO_SOLO_LECTURA)
        finally:
            self._convirtiendo = False
