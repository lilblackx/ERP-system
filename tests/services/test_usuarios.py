from datetime import datetime

import pytest

from app.services.auth import verify_password
from app.services.permisos import PermisoDenegadoError
from app.services.usuarios import UsuarioService
from tests.factories import asignar_permiso, crear_permiso, crear_rol, crear_usuario, crear_usuario_admin, crear_vendedor


def _datos_usuario(**overrides) -> dict:
    datos = {
        "nombre_usuario": "jperez",
        "nombre": "Juan",
        "apellido": "Perez",
        "email": "jperez@example.com",
        "clave": "Secreta123!",
        "id_rol": None,
    }
    datos.update(overrides)
    return datos


# --- crear_usuario --------------------------------------------------------------


def test_crear_usuario(db_session):
    admin = crear_usuario_admin(db_session)

    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario(), realizado_por=admin.id_usuario)

    assert usuario.id_usuario is not None
    assert usuario.nombre_usuario == "jperez"
    assert usuario.clave != "Secreta123!"
    assert verify_password("Secreta123!", usuario.clave)


def test_crear_usuario_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        UsuarioService.crear_usuario(db_session, **_datos_usuario())


def test_crear_usuario_requiere_nombre_usuario(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="nombre_usuario"):
        UsuarioService.crear_usuario(db_session, **_datos_usuario(nombre_usuario=""), realizado_por=admin.id_usuario)


def test_crear_usuario_requiere_clave(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="clave"):
        UsuarioService.crear_usuario(db_session, **_datos_usuario(clave=""), realizado_por=admin.id_usuario)


def test_crear_usuario_nombre_duplicado(db_session):
    admin = crear_usuario_admin(db_session)
    UsuarioService.crear_usuario(db_session, **_datos_usuario(), realizado_por=admin.id_usuario)

    with pytest.raises(ValueError, match="ya esta en uso"):
        UsuarioService.crear_usuario(
            db_session, **_datos_usuario(email="otro@example.com"), realizado_por=admin.id_usuario
        )


def test_crear_usuario_vincula_vendedor_si_rol_es_vendedor(db_session):
    admin = crear_usuario_admin(db_session)
    rol = crear_rol(db_session, nombre="VENDEDOR")
    vendedor = crear_vendedor(db_session)

    usuario = UsuarioService.crear_usuario(
        db_session,
        **_datos_usuario(id_rol=rol.id_rol, id_vendedor_usuario=vendedor.id_vendedor),
        realizado_por=admin.id_usuario,
    )

    assert usuario.id_vendedor_usuario == vendedor.id_vendedor


def test_crear_usuario_no_vincula_vendedor_si_rol_no_es_vendedor(db_session):
    admin = crear_usuario_admin(db_session)
    rol = crear_rol(db_session, nombre="SUPERVISOR")
    vendedor = crear_vendedor(db_session)

    usuario = UsuarioService.crear_usuario(
        db_session,
        **_datos_usuario(id_rol=rol.id_rol, id_vendedor_usuario=vendedor.id_vendedor),
        realizado_por=admin.id_usuario,
    )

    assert usuario.id_vendedor_usuario is None


def test_crear_usuario_rechaza_clave_debil(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="politica de seguridad"):
        UsuarioService.crear_usuario(db_session, **_datos_usuario(clave="debil"), realizado_por=admin.id_usuario)


def test_crear_usuario_rol_vendedor_pero_vendedor_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    rol = crear_rol(db_session, nombre="VENDEDOR")

    with pytest.raises(ValueError, match="Vendedor no encontrado"):
        UsuarioService.crear_usuario(
            db_session,
            **_datos_usuario(id_rol=rol.id_rol, id_vendedor_usuario=999999),
            realizado_por=admin.id_usuario,
        )


# --- editar_usuario --------------------------------------------------------------


def test_editar_usuario_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Usuario no encontrado"):
        UsuarioService.editar_usuario(db_session, 999999, {"nombre": "X"}, realizado_por=admin.id_usuario)


def test_editar_usuario_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario(), realizado_por=admin.id_usuario)

    with pytest.raises(PermisoDenegadoError):
        UsuarioService.editar_usuario(db_session, usuario.id_usuario, {"nombre": "Carlos"})


def test_editar_usuario_actualiza_campos(db_session):
    admin = crear_usuario_admin(db_session)
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario(), realizado_por=admin.id_usuario)

    actualizado = UsuarioService.editar_usuario(
        db_session, usuario.id_usuario, {"nombre": "Carlos"}, realizado_por=admin.id_usuario
    )

    assert actualizado.nombre == "Carlos"


def test_editar_usuario_ignora_clave_en_datos(db_session):
    admin = crear_usuario_admin(db_session)
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario(), realizado_por=admin.id_usuario)
    clave_original = usuario.clave

    actualizado = UsuarioService.editar_usuario(
        db_session, usuario.id_usuario, {"clave": "otra_clave_directa"}, realizado_por=admin.id_usuario
    )

    assert actualizado.clave == clave_original


def test_editar_usuario_nueva_clave_la_hashea(db_session):
    admin = crear_usuario_admin(db_session)
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario(), realizado_por=admin.id_usuario)

    actualizado = UsuarioService.editar_usuario(
        db_session, usuario.id_usuario, {}, nueva_clave="NuevaClave456!", realizado_por=admin.id_usuario
    )

    assert verify_password("NuevaClave456!", actualizado.clave)
    assert not verify_password("Secreta123!", actualizado.clave)


def test_editar_usuario_rechaza_clave_debil(db_session):
    admin = crear_usuario_admin(db_session)
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario(), realizado_por=admin.id_usuario)

    with pytest.raises(ValueError, match="politica de seguridad"):
        UsuarioService.editar_usuario(
            db_session, usuario.id_usuario, {}, nueva_clave="debil", realizado_por=admin.id_usuario
        )


def test_editar_usuario_nombre_usuario_duplicado(db_session):
    admin = crear_usuario_admin(db_session)
    UsuarioService.crear_usuario(
        db_session, **_datos_usuario(nombre_usuario="usuario1"), realizado_por=admin.id_usuario
    )
    otro = UsuarioService.crear_usuario(
        db_session, **_datos_usuario(nombre_usuario="usuario2"), realizado_por=admin.id_usuario
    )

    with pytest.raises(ValueError, match="ya esta en uso"):
        UsuarioService.editar_usuario(
            db_session, otro.id_usuario, {"nombre_usuario": "usuario1"}, realizado_por=admin.id_usuario
        )


def test_editar_usuario_mismo_nombre_usuario_no_falla(db_session):
    admin = crear_usuario_admin(db_session)
    usuario = UsuarioService.crear_usuario(
        db_session, **_datos_usuario(nombre_usuario="usuario1"), realizado_por=admin.id_usuario
    )

    actualizado = UsuarioService.editar_usuario(
        db_session,
        usuario.id_usuario,
        {"nombre_usuario": "usuario1", "nombre": "X"},
        realizado_por=admin.id_usuario,
    )

    assert actualizado.nombre_usuario == "usuario1"


# --- cambiar_estado --------------------------------------------------------------


def test_cambiar_estado_invalido(db_session):
    admin = crear_usuario_admin(db_session)
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario(), realizado_por=admin.id_usuario)
    with pytest.raises(ValueError, match="nuevo_estado"):
        UsuarioService.cambiar_estado(db_session, usuario.id_usuario, "BLOQUEADO", realizado_por=admin.id_usuario)


def test_cambiar_estado_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario(), realizado_por=admin.id_usuario)

    with pytest.raises(PermisoDenegadoError):
        UsuarioService.cambiar_estado(db_session, usuario.id_usuario, "INACTIVO")


def test_cambiar_estado_usuario_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Usuario no encontrado"):
        UsuarioService.cambiar_estado(db_session, 999999, "INACTIVO", realizado_por=admin.id_usuario)


def test_cambiar_estado_ok(db_session):
    admin = crear_usuario_admin(db_session)
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario(), realizado_por=admin.id_usuario)

    actualizado = UsuarioService.cambiar_estado(db_session, usuario.id_usuario, "INACTIVO", realizado_por=admin.id_usuario)

    assert actualizado.estado == "INACTIVO"


# --- desbloquear_usuario (C7: via de escape manual, sin correo) --------------------


def test_desbloquear_usuario_limpia_bloqueo_e_intentos(db_session):
    admin = crear_usuario_admin(db_session)
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario(), realizado_por=admin.id_usuario)
    usuario.intentos_fallidos = 5
    usuario.bloqueado_desde = datetime.now()
    db_session.commit()

    actualizado = UsuarioService.desbloquear_usuario(db_session, usuario.id_usuario, realizado_por=admin.id_usuario)

    assert actualizado.bloqueado_desde is None
    assert actualizado.intentos_fallidos == 0


def test_desbloquear_usuario_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario(), realizado_por=admin.id_usuario)

    with pytest.raises(PermisoDenegadoError):
        UsuarioService.desbloquear_usuario(db_session, usuario.id_usuario)


def test_desbloquear_usuario_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Usuario no encontrado"):
        UsuarioService.desbloquear_usuario(db_session, 999999, realizado_por=admin.id_usuario)


# --- listar_usuarios --------------------------------------------------------------


def test_listar_usuarios_filtra_por_texto(db_session):
    admin = crear_usuario_admin(db_session)
    UsuarioService.crear_usuario(
        db_session, **_datos_usuario(nombre_usuario="jperez", nombre="Juan"), realizado_por=admin.id_usuario
    )
    UsuarioService.crear_usuario(
        db_session, **_datos_usuario(nombre_usuario="mgomez", nombre="Maria"), realizado_por=admin.id_usuario
    )

    resultado = UsuarioService.listar_usuarios(db_session, texto_busqueda="Juan", id_usuario=admin.id_usuario)

    assert len(resultado) == 1
    assert resultado[0]["nombre_usuario"] == "jperez"


def test_listar_usuarios_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        UsuarioService.listar_usuarios(db_session)


def test_listar_usuarios_filtra_por_rol(db_session):
    admin = crear_usuario_admin(db_session)
    rol = crear_rol(db_session, nombre="SUPERVISOR")
    UsuarioService.crear_usuario(
        db_session, **_datos_usuario(nombre_usuario="admin1", id_rol=rol.id_rol), realizado_por=admin.id_usuario
    )
    UsuarioService.crear_usuario(
        db_session, **_datos_usuario(nombre_usuario="sinrol"), realizado_por=admin.id_usuario
    )

    resultado = UsuarioService.listar_usuarios(db_session, id_rol=rol.id_rol, id_usuario=admin.id_usuario)

    assert len(resultado) == 1
    assert resultado[0]["nombre_usuario"] == "admin1"
    assert resultado[0]["rol"] == "SUPERVISOR"


def test_listar_usuarios_filtra_por_estado(db_session):
    admin = crear_usuario_admin(db_session)
    activo = UsuarioService.crear_usuario(
        db_session, **_datos_usuario(nombre_usuario="activo1"), realizado_por=admin.id_usuario
    )
    inactivo = UsuarioService.crear_usuario(
        db_session, **_datos_usuario(nombre_usuario="inactivo1"), realizado_por=admin.id_usuario
    )
    UsuarioService.cambiar_estado(db_session, inactivo.id_usuario, "INACTIVO", realizado_por=admin.id_usuario)

    resultado = UsuarioService.listar_usuarios(db_session, estado="ACTIVO", id_usuario=admin.id_usuario)

    assert [u["nombre_usuario"] for u in resultado if u["nombre_usuario"] in ("activo1", "inactivo1")] == ["activo1"]
    assert activo.estado == "ACTIVO"


def test_listar_usuarios_nombre_completo(db_session):
    admin = crear_usuario_admin(db_session)
    UsuarioService.crear_usuario(
        db_session, **_datos_usuario(nombre="Juan", apellido="Perez", nombre_usuario="jperez2"),
        realizado_por=admin.id_usuario,
    )

    resultado = UsuarioService.listar_usuarios(db_session, texto_busqueda="jperez2", id_usuario=admin.id_usuario)

    assert resultado[0]["nombre_completo"] == "Juan Perez"


# --- verificar_permiso --------------------------------------------------------------
# Prueban la funcion de bajo nivel en si (usada tambien por PermisoService.require_permiso,
# duplicada ahi para evitar un import circular -- ver la nota en app/services/permisos.py),
# insertando usuarios directo por factory en vez de via el servicio: no es necesario un
# actor autorizado para construir el escenario, solo para las escrituras reales.


def test_verificar_permiso_usuario_inexistente(db_session):
    assert UsuarioService.verificar_permiso(db_session, 999999, "clientes", "crear") is False


def test_verificar_permiso_usuario_sin_rol(db_session):
    usuario = crear_usuario(db_session)
    assert UsuarioService.verificar_permiso(db_session, usuario.id_usuario, "clientes", "crear") is False


def test_verificar_permiso_concedido(db_session):
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session, recurso="clientes", accion="crear")
    asignar_permiso(db_session, rol, permiso)
    usuario = crear_usuario(db_session, id_rol=rol.id_rol)

    assert UsuarioService.verificar_permiso(db_session, usuario.id_usuario, "clientes", "crear") is True


def test_verificar_permiso_no_concedido(db_session):
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session, recurso="clientes", accion="crear")
    asignar_permiso(db_session, rol, permiso)
    usuario = crear_usuario(db_session, id_rol=rol.id_rol)

    assert UsuarioService.verificar_permiso(db_session, usuario.id_usuario, "clientes", "eliminar") is False
