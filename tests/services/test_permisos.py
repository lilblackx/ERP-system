import pytest

from app.services.permisos import PermisoService, RolService
from app.services.usuarios import UsuarioService
from tests.factories import crear_permiso, crear_rol


# --- RolService -------------------------------------------------------------------


def test_crear_rol(db_session):
    rol = RolService.crear_rol(db_session, nombre="SUPERVISOR", descripcion="Supervisa cajas")
    assert rol.id_rol is not None
    assert rol.nombre == "SUPERVISOR"


def test_crear_rol_requiere_nombre(db_session):
    with pytest.raises(ValueError, match="nombre es requerido"):
        RolService.crear_rol(db_session, nombre="")


def test_crear_rol_nombre_duplicado(db_session):
    RolService.crear_rol(db_session, nombre="SUPERVISOR")
    with pytest.raises(ValueError, match="Ya existe un rol"):
        RolService.crear_rol(db_session, nombre="SUPERVISOR")


def test_listar_roles_ordenados(db_session):
    RolService.crear_rol(db_session, nombre="ZETA")
    RolService.crear_rol(db_session, nombre="ALFA")

    resultado = RolService.listar_roles(db_session)

    assert [r.nombre for r in resultado] == ["ALFA", "ZETA"]


def test_obtener_rol_inexistente(db_session):
    assert RolService.obtener_rol(db_session, 999999) is None


def test_actualizar_rol(db_session):
    rol = RolService.crear_rol(db_session, nombre="SUPERVISOR")
    actualizado = RolService.actualizar_rol(db_session, rol.id_rol, descripcion="Nueva descripcion")
    assert actualizado.descripcion == "Nueva descripcion"


def test_actualizar_rol_inexistente(db_session):
    with pytest.raises(ValueError, match="Rol no encontrado"):
        RolService.actualizar_rol(db_session, 999999, descripcion="X")


def test_actualizar_rol_nombre_duplicado(db_session):
    RolService.crear_rol(db_session, nombre="SUPERVISOR")
    otro = RolService.crear_rol(db_session, nombre="CAJERO_JR")

    with pytest.raises(ValueError, match="Ya existe un rol"):
        RolService.actualizar_rol(db_session, otro.id_rol, nombre="SUPERVISOR")


def test_actualizar_rol_no_permite_vaciar_nombre(db_session):
    rol = RolService.crear_rol(db_session, nombre="SUPERVISOR")
    with pytest.raises(ValueError, match="nombre es requerido"):
        RolService.actualizar_rol(db_session, rol.id_rol, nombre="")


def test_eliminar_rol(db_session):
    rol = RolService.crear_rol(db_session, nombre="SUPERVISOR")
    RolService.eliminar_rol(db_session, rol.id_rol)
    assert RolService.obtener_rol(db_session, rol.id_rol) is None


def test_eliminar_rol_inexistente_no_falla(db_session):
    RolService.eliminar_rol(db_session, 999999)


def test_eliminar_rol_con_usuarios_asignados_falla(db_session):
    rol = RolService.crear_rol(db_session, nombre="SUPERVISOR")
    UsuarioService.crear_usuario(
        db_session, nombre_usuario="jperez", nombre=None, apellido=None, email=None, clave="Secreta123", id_rol=rol.id_rol
    )

    with pytest.raises(ValueError, match="hay 1 usuario"):
        RolService.eliminar_rol(db_session, rol.id_rol)

    assert RolService.obtener_rol(db_session, rol.id_rol) is not None


# --- PermisoService: catalogo -------------------------------------------------------


def test_listar_permisos_filtra_por_recurso(db_session):
    crear_permiso(db_session, recurso="clientes", accion="ver")
    crear_permiso(db_session, recurso="clientes", accion="crear")
    crear_permiso(db_session, recurso="ventas", accion="ver")

    resultado = PermisoService.listar_permisos(db_session, recurso="clientes")

    assert len(resultado) == 2
    assert {p.accion for p in resultado} == {"ver", "crear"}


# --- PermisoService: matriz ----------------------------------------------------------


def test_obtener_matriz_rol_marca_asignados(db_session):
    rol = crear_rol(db_session)
    permiso_asignado = crear_permiso(db_session, recurso="clientes", accion="ver")
    permiso_sin_asignar = crear_permiso(db_session, recurso="clientes", accion="eliminar")
    PermisoService.asignar_permiso(db_session, rol.id_rol, permiso_asignado.id_permiso)

    matriz = PermisoService.obtener_matriz_rol(db_session, rol.id_rol)

    por_id = {fila["id_permiso"]: fila["asignado"] for fila in matriz}
    assert por_id[permiso_asignado.id_permiso] is True
    assert por_id[permiso_sin_asignar.id_permiso] is False


def test_obtener_matriz_rol_inexistente(db_session):
    with pytest.raises(ValueError, match="Rol no encontrado"):
        PermisoService.obtener_matriz_rol(db_session, 999999)


def test_asignar_permiso(db_session):
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session, recurso="clientes", accion="crear")

    PermisoService.asignar_permiso(db_session, rol.id_rol, permiso.id_permiso)

    matriz = PermisoService.obtener_matriz_rol(db_session, rol.id_rol)
    assert next(f for f in matriz if f["id_permiso"] == permiso.id_permiso)["asignado"] is True


def test_asignar_permiso_es_idempotente(db_session):
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session, recurso="clientes", accion="crear")

    PermisoService.asignar_permiso(db_session, rol.id_rol, permiso.id_permiso)
    PermisoService.asignar_permiso(db_session, rol.id_rol, permiso.id_permiso)  # no debe fallar

    matriz = PermisoService.obtener_matriz_rol(db_session, rol.id_rol)
    assert sum(1 for f in matriz if f["asignado"]) == 1


def test_asignar_permiso_rol_inexistente(db_session):
    permiso = crear_permiso(db_session)
    with pytest.raises(ValueError, match="Rol no encontrado"):
        PermisoService.asignar_permiso(db_session, 999999, permiso.id_permiso)


def test_asignar_permiso_permiso_inexistente(db_session):
    rol = crear_rol(db_session)
    with pytest.raises(ValueError, match="Permiso no encontrado"):
        PermisoService.asignar_permiso(db_session, rol.id_rol, 999999)


def test_revocar_permiso(db_session):
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session)
    PermisoService.asignar_permiso(db_session, rol.id_rol, permiso.id_permiso)

    PermisoService.revocar_permiso(db_session, rol.id_rol, permiso.id_permiso)

    matriz = PermisoService.obtener_matriz_rol(db_session, rol.id_rol)
    assert next(f for f in matriz if f["id_permiso"] == permiso.id_permiso)["asignado"] is False


def test_revocar_permiso_no_asignado_no_falla(db_session):
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session)
    PermisoService.revocar_permiso(db_session, rol.id_rol, permiso.id_permiso)


def test_asignar_y_revocar_permiso_reflejan_en_verificar_permiso(db_session):
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session, recurso="clientes", accion="crear")
    usuario = UsuarioService.crear_usuario(
        db_session, nombre_usuario="jperez", nombre=None, apellido=None, email=None, clave="Secreta123", id_rol=rol.id_rol
    )

    assert UsuarioService.verificar_permiso(db_session, usuario.id_usuario, "clientes", "crear") is False

    PermisoService.asignar_permiso(db_session, rol.id_rol, permiso.id_permiso)
    assert UsuarioService.verificar_permiso(db_session, usuario.id_usuario, "clientes", "crear") is True

    PermisoService.revocar_permiso(db_session, rol.id_rol, permiso.id_permiso)
    assert UsuarioService.verificar_permiso(db_session, usuario.id_usuario, "clientes", "crear") is False


def test_establecer_permisos_rol_reemplaza_conjunto_completo(db_session):
    rol = crear_rol(db_session)
    permiso_a = crear_permiso(db_session, recurso="clientes", accion="ver")
    permiso_b = crear_permiso(db_session, recurso="clientes", accion="crear")
    permiso_c = crear_permiso(db_session, recurso="clientes", accion="eliminar")
    PermisoService.asignar_permiso(db_session, rol.id_rol, permiso_a.id_permiso)

    PermisoService.establecer_permisos_rol(db_session, rol.id_rol, [permiso_b.id_permiso, permiso_c.id_permiso])

    matriz = {f["id_permiso"]: f["asignado"] for f in PermisoService.obtener_matriz_rol(db_session, rol.id_rol)}
    assert matriz[permiso_a.id_permiso] is False
    assert matriz[permiso_b.id_permiso] is True
    assert matriz[permiso_c.id_permiso] is True


def test_establecer_permisos_rol_lista_vacia_quita_todos(db_session):
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session)
    PermisoService.asignar_permiso(db_session, rol.id_rol, permiso.id_permiso)

    PermisoService.establecer_permisos_rol(db_session, rol.id_rol, [])

    matriz = PermisoService.obtener_matriz_rol(db_session, rol.id_rol)
    assert all(not f["asignado"] for f in matriz)


def test_establecer_permisos_rol_rol_inexistente(db_session):
    with pytest.raises(ValueError, match="Rol no encontrado"):
        PermisoService.establecer_permisos_rol(db_session, 999999, [])


def test_establecer_permisos_rol_permiso_inexistente(db_session):
    rol = crear_rol(db_session)
    with pytest.raises(ValueError, match="no encontrado"):
        PermisoService.establecer_permisos_rol(db_session, rol.id_rol, [999999])
