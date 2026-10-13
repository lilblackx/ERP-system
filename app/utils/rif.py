"""Formato de RIF y cedula venezolanos.

RIF: letra (J, G, V, E, P, C) + 8 digitos + 1 digito verificador -> "J-07000750-8".
Cedula: V/E + hasta 8 digitos, sin verificador -> "V-12345678".

Todo es tolerante con lo que escribe el usuario ("j07000750-8", "070007508", "J 07.000.750-8") y
nunca inventa datos: si el texto no se parece a un RIF/cedula se devuelve tal cual, sin tocarlo.
Sin dependencias de Qt ni de la base: lo usan la UI, los PDF y las exportaciones.
"""

import re

LETRAS_RIF = ("J", "G", "V", "E", "P", "C")

# letra opcional, numero (1 a 9 digitos, con puntos/espacios/guiones de por medio) y verificador opcional
_PATRON = re.compile(r"^\s*(?:([JGVEPC])[\s.\-]*)?(\d[\d\s.]{0,14}?)(?:\s*-\s*(\d))?\s*$", re.IGNORECASE)


def partir(texto: str | None) -> tuple[str | None, str, str | None] | None:
    """(letra, numero, verificador) o None si `texto` no es un RIF/cedula reconocible.

    Con 9 digitos y sin verificador explicito, el ultimo digito es el verificador
    ("070007508" -> numero "07000750", verificador "8"). El numero de un RIF (con verificador)
    se completa a 8 digitos con ceros a la izquierda; el de una cedula (sin verificador) no."""
    if not texto:
        return None
    m = _PATRON.match(texto)
    if m is None:
        return None
    letra = m.group(1).upper() if m.group(1) else None
    digitos = re.sub(r"\D", "", m.group(2))
    verificador = m.group(3)
    if not digitos or len(digitos) > 9:
        return None
    if verificador is None and len(digitos) == 9:
        digitos, verificador = digitos[:8], digitos[8]
    if verificador is not None and len(digitos) > 8:
        return None
    if verificador is not None:
        digitos = digitos.zfill(8)
    return letra, digitos, verificador


def formatear_numero(numero: str | None) -> str:
    """Numero de identificacion sin letra: "07000750-8" o "12345678". Si no se reconoce, tal cual."""
    texto = (numero or "").strip()
    partes = partir(texto)
    if partes is None:
        return texto
    _, digitos, verificador = partes
    return f"{digitos}-{verificador}" if verificador is not None else digitos


def formatear_rif(texto: str | None, letra_defecto: str | None = None) -> str:
    """ "070007508" -> "J-07000750-8" (con letra_defecto="J"); "j07000750-8" -> "J-07000750-8".

    `letra_defecto` solo se usa cuando el texto no trae letra: el RIF de la empresa, por ejemplo,
    se asume juridico (J). Sin letra ni defecto queda sin letra. Texto no reconocible: tal cual."""
    original = (texto or "").strip()
    partes = partir(original)
    if partes is None:
        return original
    letra, digitos, verificador = partes
    letra = letra or (letra_defecto.upper() if letra_defecto else None)
    cuerpo = f"{digitos}-{verificador}" if verificador is not None else digitos
    return f"{letra}-{cuerpo}" if letra else cuerpo


def formatear_identificacion(id_legal: str | None, numero: str | None) -> str:
    """Para mostrar un cliente/proveedor guardado como letra + numero por separado:
    ("J", "07000750-8") -> "J-07000750-8"; ("V", "12345678") -> "V-12345678"."""
    numero = formatear_numero(numero)
    letra = (id_legal or "").strip().upper()
    return "-".join(p for p in (letra, numero) if p)
