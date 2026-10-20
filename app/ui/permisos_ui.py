"""Permisos en la interfaz: que botones se muestran y avisos ANTES de abrir un formulario.

Los servicios ya validan el permiso (require_permiso) al guardar, pero sin esto el usuario veia el
boton, abria el formulario, lo llenaba y recien al guardar se enteraba de que no podia (bug real del
rol CAJERO en Inventario). Los paneles y dialogos usan MixinPermisos para:

  - decidir al construirse que botones agregar (`self._puede("crear")`), y
  - volver a validar al hacer click (`self._exigir_permiso("crear", "No tienes permiso ...")`), porque
    la matriz de roles se puede cambiar con la pantalla abierta.

Esto es una ayuda de usabilidad, no la barrera de seguridad: la barrera sigue siendo el servicio.
"""

from sqlalchemy.orm import Session

from app.db.models import Rol, Usuario
from app.services.usuarios import UsuarioService
from app.ui.message_box import MessageBox


def tiene_permiso_en_sesion(session: Session, id_usuario: int | None, recurso: str, accion: str) -> bool:
    """recurso:accion del usuario (ADMIN siempre; el resto segun la matriz de su rol). No cierra la sesion."""
    if id_usuario is None:
        return False
    return UsuarioService.verificar_permiso(session, id_usuario, recurso, accion)


def es_admin_en_sesion(session: Session, id_usuario: int | None) -> bool:
    """Operaciones que los servicios restringen al rol ADMIN literal (abrir/cerrar turno, crear cajas,
    crear bancos, etc.), sin importar la matriz de permisos."""
    if id_usuario is None:
        return False
    usuario = session.get(Usuario, id_usuario)
    if usuario is None or usuario.id_rol is None or usuario.estado != "ACTIVO":
        return False
    rol = session.get(Rol, usuario.id_rol)
    return rol is not None and rol.nombre == "ADMIN"


def tiene_permiso(session_factory, id_usuario: int | None, recurso: str, accion: str) -> bool:
    session = session_factory()
    try:
        return tiene_permiso_en_sesion(session, id_usuario, recurso, accion)
    finally:
        session.close()


def es_admin(session_factory, id_usuario: int | None) -> bool:
    session = session_factory()
    try:
        return es_admin_en_sesion(session, id_usuario)
    finally:
        session.close()


class MixinPermisos:
    """Para QWidget con `session_factory` (paneles) o `session` (dialogos que reciben una sesion ya
    abierta) y el usuario en `usuario` o `id_usuario`. `recurso_permisos` es el recurso por defecto
    del widget (p. ej. "vendedores"); un permiso de otro recurso se pide con `recurso=`."""

    recurso_permisos: str = ""

    def _id_usuario_permisos(self) -> int | None:
        usuario = getattr(self, "usuario", None)
        if usuario is not None:
            return usuario.id_usuario
        return getattr(self, "id_usuario", None)

    def _puede(self, accion: str, recurso: str | None = None) -> bool:
        recurso = recurso or self.recurso_permisos
        id_usuario = self._id_usuario_permisos()
        fabrica = getattr(self, "session_factory", None)
        if fabrica is not None:
            return tiene_permiso(fabrica, id_usuario, recurso, accion)
        return tiene_permiso_en_sesion(self.session, id_usuario, recurso, accion)  # type: ignore[attr-defined]

    def _es_admin(self) -> bool:
        id_usuario = self._id_usuario_permisos()
        fabrica = getattr(self, "session_factory", None)
        if fabrica is not None:
            return es_admin(fabrica, id_usuario)
        return es_admin_en_sesion(self.session, id_usuario)  # type: ignore[attr-defined]

    def _exigir_permiso(self, accion: str, mensaje: str, recurso: str | None = None) -> bool:
        """True si puede; si no, avisa y devuelve False (el handler debe retornar sin abrir nada)."""
        if self._puede(accion, recurso):
            return True
        MessageBox.warning(self, "Sin permiso", mensaje)  # type: ignore[arg-type]
        return False

    def _exigir_admin(self, mensaje: str) -> bool:
        if self._es_admin():
            return True
        MessageBox.warning(self, "Sin permiso", mensaje)  # type: ignore[arg-type]
        return False
