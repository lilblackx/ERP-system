"""Bloqueo de cuentas por intentos fallidos: temporal y escalonado.

Antes el bloqueo era permanente (solo se salia con un codigo al correo o con otro ADMIN), asi
que cualquiera que conociera un nombre de usuario podia dejar fuera a todos los
administradores a proposito, en plena jornada, con 5 claves malas. Ahora cada bloqueo dura
un tiempo que crece con los fallos seguidos (5 min, luego 15, luego 1 hora): frena la
adivinacion de claves igual de bien, pero nadie queda fuera de forma indefinida. El desbloqueo
inmediato (codigo al correo, o un ADMIN) sigue disponible.

No hay columna "bloqueado_hasta": se calcula desde bloqueado_desde + la duracion que
corresponde a intentos_fallidos, asi que el esquema no cambia y las cuentas ya bloqueadas
quedan cubiertas (su bloqueo vence a los 5 min). Este modulo no importa nada de app.services
a proposito: lo usan permisos, auth, usuarios y tesoreria, y un import cruzado crearia ciclos.
"""

from datetime import datetime, timedelta

MAX_INTENTOS_FALLIDOS = 5
# Minutos de bloqueo del 1er, 2do y 3er bloqueo seguido (y todos los siguientes).
DURACIONES_BLOQUEO_MIN = (5, 15, 60)


def duracion_bloqueo(intentos_fallidos: int | None) -> timedelta:
    """Duracion del bloqueo que se acaba de aplicar con `intentos_fallidos` fallos seguidos.
    El 5to fallo es el 1er bloqueo (5 min); tras vencer, UN fallo mas ya aplica el 2do
    (15 min), y asi hasta el tope de 1 hora. Un login correcto pone la cuenta en cero."""
    nivel = max(1, (intentos_fallidos or 0) - MAX_INTENTOS_FALLIDOS + 1)
    return timedelta(minutes=DURACIONES_BLOQUEO_MIN[min(nivel, len(DURACIONES_BLOQUEO_MIN)) - 1])


def bloqueado_hasta(usuario) -> datetime | None:
    """Hasta cuando dura el bloqueo del usuario, o None si no esta bloqueado."""
    desde = getattr(usuario, "bloqueado_desde", None)
    if desde is None:
        return None
    return desde + duracion_bloqueo(getattr(usuario, "intentos_fallidos", 0))


def esta_bloqueado(usuario, ahora: datetime | None = None) -> bool:
    """True si el bloqueo sigue vigente. Un bloqueo vencido no cuenta, aunque la columna
    bloqueado_desde siga con valor hasta el proximo login (que la limpia)."""
    hasta = bloqueado_hasta(usuario)
    return hasta is not None and (ahora or datetime.now()) < hasta
