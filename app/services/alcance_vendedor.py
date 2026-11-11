"""Alcance de un usuario VENDEDOR: ve solo lo suyo.

Un usuario con rol VENDEDOR esta vinculado a su vendedor (`Usuario.id_vendedor_usuario`, ver usuarios.py). Antes ese
vinculo solo preseleccionaba el vendedor al facturar y abria "Mis comisiones"; Clientes, Facturacion, Cuentas por Cobrar
y los reportes le mostraban TODO el negocio. Ahora los servicios lo acotan, con dos criterios (los mismos que usan los
filtros de vendedor de esas pantallas):

  * lo que se mide por FACTURA (facturas, libro de ventas, ventas por periodo, productos vendidos): las facturas cuyo
    `id_vendedor` es el suyo;
  * lo que se mide por CLIENTE (clientes, cuentas por cobrar, cobros, morosos, aging, estado de cuenta): los
    clientes que tiene asignados (`Cliente.vendedor_cliente`).

El filtro se aplica en el servicio, no solo en la pantalla: `vendedor_efectivo` IGNORA el vendedor que pida la
pantalla y devuelve el del usuario, asi que un vendedor no puede ver lo de otro cambiando un combo ni llamando al
servicio con otro id. Los usuarios sin vendedor vinculado (ADMIN, CAJERO) no tienen alcance y siguen eligiendo
el filtro libremente.
"""

from sqlalchemy.orm import Session

from app.db.models import Usuario
from app.services.permisos import PermisoDenegadoError

_CLAVE_CACHE = "_alcance_vendedor"


def vendedor_propio(session: Session, id_usuario: int | None) -> int | None:
    """Id del vendedor al que esta vinculado el usuario (`None` si no es un usuario vendedor: sin alcance). Se consulta
    una vez por sesion y usuario."""
    if id_usuario is None:
        return None
    cache = session.info.setdefault(_CLAVE_CACHE, {})
    if id_usuario not in cache:
        # session.get reutiliza el usuario que el chequeo de permisos ya cargo (sin otra consulta a la base).
        usuario = session.get(Usuario, id_usuario)
        cache[id_usuario] = usuario.id_vendedor_usuario if usuario is not None else None
    return cache[id_usuario]


def vendedor_efectivo(session: Session, id_usuario: int | None, id_vendedor: int | None = None) -> int | None:
    """El vendedor por el que hay que filtrar: el propio del usuario si es un vendedor (aunque la pantalla pida otro o
    ninguno); si no, el que pidio la pantalla."""
    propio = vendedor_propio(session, id_usuario)
    return propio if propio is not None else id_vendedor


def es_usuario_vendedor(session: Session, id_usuario: int | None) -> bool:
    return vendedor_propio(session, id_usuario) is not None


def exigir_sin_alcance(session: Session, id_usuario: int | None, que: str = "Este reporte") -> None:
    """Para lo que mide el negocio ENTERO (compras, bancos, caja, inventario valorizado...): un usuario vendedor no
    puede pedirlo, ni llamando al servicio directo. Los reportes que se acotan a lo suyo no lo llaman."""
    if vendedor_propio(session, id_usuario) is not None:
        raise PermisoDenegadoError(f"{que} es del negocio completo: tu usuario solo ve lo suyo.")
