import pytest

from app.services.permisos import PermisoDenegadoError, PermisoService, RolService
from app.services.usuarios import UsuarioService
from tests.factories import crear_permiso, crear_rol, crear_usuario, crear_usuario_admin


# --- RolService -------------------------------------------------------------------


def test_crear_rol(db_session):
    admin = crear_usuario_admin(db_session)
    rol = RolService.crear_rol(db_session, nombre="SUPERVISOR", descripcion="Supervisa cajas", id_usuario=admin.id_usuario)
    assert rol.id_rol is not None
    assert rol.nombre == "SUPERVISOR"


def test_crear_rol_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        RolService.crear_rol(db_session, nombre="SUPERVISOR")


def test_crear_rol_requiere_nombre(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="nombre es requerido"):
        RolService.crear_rol(db_session, nombre="", id_usuario=admin.id_usuario)


def test_crear_rol_nombre_duplicado(db_session):
    admin = crear_usuario_admin(db_session)
    RolService.crear_rol(db_session, nombre="SUPERVISOR", id_usuario=admin.id_usuario)
    with pytest.raises(ValueError, match="Ya existe un rol"):
        RolService.crear_rol(db_session, nombre="SUPERVISOR", id_usuario=admin.id_usuario)


def test_listar_roles_ordenados(db_session):
    admin = crear_usuario_admin(db_session)
    RolService.crear_rol(db_session, nombre="ZETA", id_usuario=admin.id_usuario)
    RolService.crear_rol(db_session, nombre="ALFA", id_usuario=admin.id_usuario)

    resultado = RolService.listar_roles(db_session, id_usuario=admin.id_usuario)

    assert [r.nombre for r in resultado if r.nombre in ("ALFA", "ZETA")] == ["ALFA", "ZETA"]


def test_listar_roles_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        RolService.listar_roles(db_session)


def test_obtener_rol_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    assert RolService.obtener_rol(db_session, 999999, id_usuario=admin.id_usuario) is None


def test_obtener_rol_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        RolService.obtener_rol(db_session, 999999)


def test_actualizar_rol(db_session):
    admin = crear_usuario_admin(db_session)
    rol = RolService.crear_rol(db_session, nombre="SUPERVISOR", id_usuario=admin.id_usuario)
    actualizado = RolService.actualizar_rol(db_session, rol.id_rol, id_usuario=admin.id_usuario, descripcion="Nueva descripcion")
    assert actualizado.descripcion == "Nueva descripcion"


def test_actualizar_rol_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    rol = RolService.crear_rol(db_session, nombre="SUPERVISOR", id_usuario=admin.id_usuario)
    with pytest.raises(PermisoDenegadoError):
        RolService.actualizar_rol(db_session, rol.id_rol, descripcion="X")


def test_actualizar_rol_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Rol no encontrado"):
        RolService.actualizar_rol(db_session, 999999, id_usuario=admin.id_usuario, descripcion="X")


def test_actualizar_rol_nombre_duplicado(db_session):
    admin = crear_usuario_admin(db_session)
    RolService.crear_rol(db_session, nombre="SUPERVISOR", id_usuario=admin.id_usuario)
    otro = RolService.crear_rol(db_session, nombre="CAJERO_JR", id_usuario=admin.id_usuario)

    with pytest.raises(ValueError, match="Ya existe un rol"):
        RolService.actualizar_rol(db_session, otro.id_rol, id_usuario=admin.id_usuario, nombre="SUPERVISOR")


def test_actualizar_rol_no_permite_vaciar_nombre(db_session):
    admin = crear_usuario_admin(db_session)
    rol = RolService.crear_rol(db_session, nombre="SUPERVISOR", id_usuario=admin.id_usuario)
    with pytest.raises(ValueError, match="nombre es requerido"):
        RolService.actualizar_rol(db_session, rol.id_rol, id_usuario=admin.id_usuario, nombre="")


def test_eliminar_rol(db_session):
    admin = crear_usuario_admin(db_session)
    rol = RolService.crear_rol(db_session, nombre="SUPERVISOR", id_usuario=admin.id_usuario)
    RolService.eliminar_rol(db_session, rol.id_rol, id_usuario=admin.id_usuario)
    assert RolService.obtener_rol(db_session, rol.id_rol, id_usuario=admin.id_usuario) is None


def test_eliminar_rol_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    rol = RolService.crear_rol(db_session, nombre="SUPERVISOR", id_usuario=admin.id_usuario)
    with pytest.raises(PermisoDenegadoError):
        RolService.eliminar_rol(db_session, rol.id_rol)


def test_eliminar_rol_inexistente_no_falla(db_session):
    admin = crear_usuario_admin(db_session)
    RolService.eliminar_rol(db_session, 999999, id_usuario=admin.id_usuario)


def test_eliminar_rol_con_usuarios_asignados_falla(db_session):
    admin = crear_usuario_admin(db_session)
    rol = RolService.crear_rol(db_session, nombre="SUPERVISOR", id_usuario=admin.id_usuario)
    crear_usuario(db_session, nombre_usuario="jperez", id_rol=rol.id_rol)

    with pytest.raises(ValueError, match="hay 1 usuario"):
        RolService.eliminar_rol(db_session, rol.id_rol, id_usuario=admin.id_usuario)

    assert RolService.obtener_rol(db_session, rol.id_rol, id_usuario=admin.id_usuario) is not None


# --- PermisoService: catalogo -------------------------------------------------------


def test_listar_permisos_filtra_por_recurso(db_session):
    admin = crear_usuario_admin(db_session)
    crear_permiso(db_session, recurso="clientes", accion="ver")
    crear_permiso(db_session, recurso="clientes", accion="crear")
    crear_permiso(db_session, recurso="ventas", accion="ver")

    resultado = PermisoService.listar_permisos(db_session, recurso="clientes", id_usuario=admin.id_usuario)

    assert len(resultado) == 2
    assert {p.accion for p in resultado} == {"ver", "crear"}


def test_listar_permisos_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        PermisoService.listar_permisos(db_session)


# --- PermisoService: matriz ----------------------------------------------------------


def test_obtener_matriz_rol_marca_asignados(db_session):
    admin = crear_usuario_admin(db_session)
    rol = crear_rol(db_session)
    permiso_asignado = crear_permiso(db_session, recurso="clientes", accion="ver")
    permiso_sin_asignar = crear_permiso(db_session, recurso="clientes", accion="eliminar")
    PermisoService.asignar_permiso(db_session, rol.id_rol, permiso_asignado.id_permiso, id_usuario=admin.id_usuario)

    matriz = PermisoService.obtener_matriz_rol(db_session, rol.id_rol, id_usuario=admin.id_usuario)

    por_id = {fila["id_permiso"]: fila["asignado"] for fila in matriz}
    assert por_id[permiso_asignado.id_permiso] is True
    assert por_id[permiso_sin_asignar.id_permiso] is False


def test_obtener_matriz_rol_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Rol no encontrado"):
        PermisoService.obtener_matriz_rol(db_session, 999999, id_usuario=admin.id_usuario)


def test_obtener_matriz_rol_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        PermisoService.obtener_matriz_rol(db_session, 999999)


def test_asignar_permiso(db_session):
    admin = crear_usuario_admin(db_session)
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session, recurso="clientes", accion="crear")

    PermisoService.asignar_permiso(db_session, rol.id_rol, permiso.id_permiso, id_usuario=admin.id_usuario)

    matriz = PermisoService.obtener_matriz_rol(db_session, rol.id_rol, id_usuario=admin.id_usuario)
    assert next(f for f in matriz if f["id_permiso"] == permiso.id_permiso)["asignado"] is True


def test_asignar_permiso_sin_usuario_autorizado_falla(db_session):
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session, recurso="clientes", accion="crear")

    with pytest.raises(PermisoDenegadoError):
        PermisoService.asignar_permiso(db_session, rol.id_rol, permiso.id_permiso)


def test_asignar_permiso_es_idempotente(db_session):
    admin = crear_usuario_admin(db_session)
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session, recurso="clientes", accion="crear")

    PermisoService.asignar_permiso(db_session, rol.id_rol, permiso.id_permiso, id_usuario=admin.id_usuario)
    PermisoService.asignar_permiso(db_session, rol.id_rol, permiso.id_permiso, id_usuario=admin.id_usuario)  # no debe fallar

    matriz = PermisoService.obtener_matriz_rol(db_session, rol.id_rol, id_usuario=admin.id_usuario)
    assert sum(1 for f in matriz if f["asignado"]) == 1


def test_asignar_permiso_rol_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    permiso = crear_permiso(db_session)
    with pytest.raises(ValueError, match="Rol no encontrado"):
        PermisoService.asignar_permiso(db_session, 999999, permiso.id_permiso, id_usuario=admin.id_usuario)


def test_asignar_permiso_permiso_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    rol = crear_rol(db_session)
    with pytest.raises(ValueError, match="Permiso no encontrado"):
        PermisoService.asignar_permiso(db_session, rol.id_rol, 999999, id_usuario=admin.id_usuario)


def test_revocar_permiso(db_session):
    admin = crear_usuario_admin(db_session)
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session)
    PermisoService.asignar_permiso(db_session, rol.id_rol, permiso.id_permiso, id_usuario=admin.id_usuario)

    PermisoService.revocar_permiso(db_session, rol.id_rol, permiso.id_permiso, id_usuario=admin.id_usuario)

    matriz = PermisoService.obtener_matriz_rol(db_session, rol.id_rol, id_usuario=admin.id_usuario)
    assert next(f for f in matriz if f["id_permiso"] == permiso.id_permiso)["asignado"] is False


def test_revocar_permiso_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session)
    PermisoService.asignar_permiso(db_session, rol.id_rol, permiso.id_permiso, id_usuario=admin.id_usuario)

    with pytest.raises(PermisoDenegadoError):
        PermisoService.revocar_permiso(db_session, rol.id_rol, permiso.id_permiso)


def test_revocar_permiso_no_asignado_no_falla(db_session):
    admin = crear_usuario_admin(db_session)
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session)
    PermisoService.revocar_permiso(db_session, rol.id_rol, permiso.id_permiso, id_usuario=admin.id_usuario)


def test_asignar_y_revocar_permiso_reflejan_en_verificar_permiso(db_session):
    admin = crear_usuario_admin(db_session)
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session, recurso="clientes", accion="crear")
    usuario = crear_usuario(db_session, nombre_usuario="jperez", id_rol=rol.id_rol)

    assert UsuarioService.verificar_permiso(db_session, usuario.id_usuario, "clientes", "crear") is False

    PermisoService.asignar_permiso(db_session, rol.id_rol, permiso.id_permiso, id_usuario=admin.id_usuario)
    assert UsuarioService.verificar_permiso(db_session, usuario.id_usuario, "clientes", "crear") is True

    PermisoService.revocar_permiso(db_session, rol.id_rol, permiso.id_permiso, id_usuario=admin.id_usuario)
    assert UsuarioService.verificar_permiso(db_session, usuario.id_usuario, "clientes", "crear") is False


def test_establecer_permisos_rol_reemplaza_conjunto_completo(db_session):
    admin = crear_usuario_admin(db_session)
    rol = crear_rol(db_session)
    permiso_a = crear_permiso(db_session, recurso="clientes", accion="ver")
    permiso_b = crear_permiso(db_session, recurso="clientes", accion="crear")
    permiso_c = crear_permiso(db_session, recurso="clientes", accion="eliminar")
    PermisoService.asignar_permiso(db_session, rol.id_rol, permiso_a.id_permiso, id_usuario=admin.id_usuario)

    PermisoService.establecer_permisos_rol(
        db_session, rol.id_rol, [permiso_b.id_permiso, permiso_c.id_permiso], id_usuario=admin.id_usuario
    )

    matriz = {f["id_permiso"]: f["asignado"] for f in PermisoService.obtener_matriz_rol(db_session, rol.id_rol, id_usuario=admin.id_usuario)}
    assert matriz[permiso_a.id_permiso] is False
    assert matriz[permiso_b.id_permiso] is True
    assert matriz[permiso_c.id_permiso] is True


def test_establecer_permisos_rol_sin_usuario_autorizado_falla(db_session):
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session)

    with pytest.raises(PermisoDenegadoError):
        PermisoService.establecer_permisos_rol(db_session, rol.id_rol, [permiso.id_permiso])


def test_establecer_permisos_rol_lista_vacia_quita_todos(db_session):
    admin = crear_usuario_admin(db_session)
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session)
    PermisoService.asignar_permiso(db_session, rol.id_rol, permiso.id_permiso, id_usuario=admin.id_usuario)

    PermisoService.establecer_permisos_rol(db_session, rol.id_rol, [], id_usuario=admin.id_usuario)

    matriz = PermisoService.obtener_matriz_rol(db_session, rol.id_rol, id_usuario=admin.id_usuario)
    assert all(not f["asignado"] for f in matriz)


def test_establecer_permisos_rol_rol_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Rol no encontrado"):
        PermisoService.establecer_permisos_rol(db_session, 999999, [], id_usuario=admin.id_usuario)


def test_establecer_permisos_rol_permiso_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    rol = crear_rol(db_session)
    with pytest.raises(ValueError, match="no encontrado"):
        PermisoService.establecer_permisos_rol(db_session, rol.id_rol, [999999], id_usuario=admin.id_usuario)
