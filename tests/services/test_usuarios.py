import pytest

from app.services.auth import verify_password
from app.services.usuarios import UsuarioService
from tests.factories import asignar_permiso, crear_permiso, crear_rol, crear_vendedor


def _datos_usuario(**overrides) -> dict:
    datos = {
        "nombre_usuario": "jperez",
        "nombre": "Juan",
        "apellido": "Perez",
        "email": "jperez@example.com",
        "clave": "Secreta123",
        "id_rol": None,
    }
    datos.update(overrides)
    return datos


# --- crear_usuario --------------------------------------------------------------


def test_crear_usuario(db_session):
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario())

    assert usuario.id_usuario is not None
    assert usuario.nombre_usuario == "jperez"
    assert usuario.clave != "Secreta123"
    assert verify_password("Secreta123", usuario.clave)


def test_crear_usuario_requiere_nombre_usuario(db_session):
    with pytest.raises(ValueError, match="nombre_usuario"):
        UsuarioService.crear_usuario(db_session, **_datos_usuario(nombre_usuario=""))


def test_crear_usuario_requiere_clave(db_session):
    with pytest.raises(ValueError, match="clave"):
        UsuarioService.crear_usuario(db_session, **_datos_usuario(clave=""))


def test_crear_usuario_nombre_duplicado(db_session):
    UsuarioService.crear_usuario(db_session, **_datos_usuario())

    with pytest.raises(ValueError, match="ya esta en uso"):
        UsuarioService.crear_usuario(db_session, **_datos_usuario(email="otro@example.com"))


def test_crear_usuario_vincula_vendedor_si_rol_es_vendedor(db_session):
    rol = crear_rol(db_session, nombre="VENDEDOR")
    vendedor = crear_vendedor(db_session)

    usuario = UsuarioService.crear_usuario(
        db_session, **_datos_usuario(id_rol=rol.id_rol, id_vendedor_usuario=vendedor.id_vendedor)
    )

    assert usuario.id_vendedor_usuario == vendedor.id_vendedor


def test_crear_usuario_no_vincula_vendedor_si_rol_no_es_vendedor(db_session):
    rol = crear_rol(db_session, nombre="ADMIN")
    vendedor = crear_vendedor(db_session)

    usuario = UsuarioService.crear_usuario(
        db_session, **_datos_usuario(id_rol=rol.id_rol, id_vendedor_usuario=vendedor.id_vendedor)
    )

    assert usuario.id_vendedor_usuario is None


def test_crear_usuario_rol_vendedor_pero_vendedor_inexistente(db_session):
    rol = crear_rol(db_session, nombre="VENDEDOR")

    with pytest.raises(ValueError, match="Vendedor no encontrado"):
        UsuarioService.crear_usuario(db_session, **_datos_usuario(id_rol=rol.id_rol, id_vendedor_usuario=999999))


# --- editar_usuario --------------------------------------------------------------


def test_editar_usuario_inexistente(db_session):
    with pytest.raises(ValueError, match="Usuario no encontrado"):
        UsuarioService.editar_usuario(db_session, 999999, {"nombre": "X"})


def test_editar_usuario_actualiza_campos(db_session):
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario())

    actualizado = UsuarioService.editar_usuario(db_session, usuario.id_usuario, {"nombre": "Carlos"})

    assert actualizado.nombre == "Carlos"


def test_editar_usuario_ignora_clave_en_datos(db_session):
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario())
    clave_original = usuario.clave

    actualizado = UsuarioService.editar_usuario(db_session, usuario.id_usuario, {"clave": "otra_clave_directa"})

    assert actualizado.clave == clave_original


def test_editar_usuario_nueva_clave_la_hashea(db_session):
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario())

    actualizado = UsuarioService.editar_usuario(db_session, usuario.id_usuario, {}, nueva_clave="NuevaClave456")

    assert verify_password("NuevaClave456", actualizado.clave)
    assert not verify_password("Secreta123", actualizado.clave)


def test_editar_usuario_nombre_usuario_duplicado(db_session):
    UsuarioService.crear_usuario(db_session, **_datos_usuario(nombre_usuario="usuario1"))
    otro = UsuarioService.crear_usuario(db_session, **_datos_usuario(nombre_usuario="usuario2"))

    with pytest.raises(ValueError, match="ya esta en uso"):
        UsuarioService.editar_usuario(db_session, otro.id_usuario, {"nombre_usuario": "usuario1"})


def test_editar_usuario_mismo_nombre_usuario_no_falla(db_session):
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario(nombre_usuario="usuario1"))

    actualizado = UsuarioService.editar_usuario(
        db_session, usuario.id_usuario, {"nombre_usuario": "usuario1", "nombre": "X"}
    )

    assert actualizado.nombre_usuario == "usuario1"


# --- cambiar_estado --------------------------------------------------------------


def test_cambiar_estado_invalido(db_session):
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario())
    with pytest.raises(ValueError, match="nuevo_estado"):
        UsuarioService.cambiar_estado(db_session, usuario.id_usuario, "BLOQUEADO")


def test_cambiar_estado_usuario_inexistente(db_session):
    with pytest.raises(ValueError, match="Usuario no encontrado"):
        UsuarioService.cambiar_estado(db_session, 999999, "INACTIVO")


def test_cambiar_estado_ok(db_session):
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario())

    actualizado = UsuarioService.cambiar_estado(db_session, usuario.id_usuario, "INACTIVO")

    assert actualizado.estado == "INACTIVO"


# --- listar_usuarios --------------------------------------------------------------


def test_listar_usuarios_filtra_por_texto(db_session):
    UsuarioService.crear_usuario(db_session, **_datos_usuario(nombre_usuario="jperez", nombre="Juan"))
    UsuarioService.crear_usuario(db_session, **_datos_usuario(nombre_usuario="mgomez", nombre="Maria"))

    resultado = UsuarioService.listar_usuarios(db_session, texto_busqueda="Juan")

    assert len(resultado) == 1
    assert resultado[0]["nombre_usuario"] == "jperez"


def test_listar_usuarios_filtra_por_rol(db_session):
    rol = crear_rol(db_session, nombre="ADMIN")
    UsuarioService.crear_usuario(db_session, **_datos_usuario(nombre_usuario="admin1", id_rol=rol.id_rol))
    UsuarioService.crear_usuario(db_session, **_datos_usuario(nombre_usuario="sinrol"))

    resultado = UsuarioService.listar_usuarios(db_session, id_rol=rol.id_rol)

    assert len(resultado) == 1
    assert resultado[0]["nombre_usuario"] == "admin1"
    assert resultado[0]["rol"] == "ADMIN"


def test_listar_usuarios_filtra_por_estado(db_session):
    activo = UsuarioService.crear_usuario(db_session, **_datos_usuario(nombre_usuario="activo1"))
    inactivo = UsuarioService.crear_usuario(db_session, **_datos_usuario(nombre_usuario="inactivo1"))
    UsuarioService.cambiar_estado(db_session, inactivo.id_usuario, "INACTIVO")

    resultado = UsuarioService.listar_usuarios(db_session, estado="ACTIVO")

    assert [u["nombre_usuario"] for u in resultado] == ["activo1"]
    assert activo.estado == "ACTIVO"


def test_listar_usuarios_nombre_completo(db_session):
    UsuarioService.crear_usuario(db_session, **_datos_usuario(nombre="Juan", apellido="Perez"))

    resultado = UsuarioService.listar_usuarios(db_session)

    assert resultado[0]["nombre_completo"] == "Juan Perez"


# --- verificar_permiso --------------------------------------------------------------


def test_verificar_permiso_usuario_inexistente(db_session):
    assert UsuarioService.verificar_permiso(db_session, 999999, "clientes", "crear") is False


def test_verificar_permiso_usuario_sin_rol(db_session):
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario())
    assert UsuarioService.verificar_permiso(db_session, usuario.id_usuario, "clientes", "crear") is False


def test_verificar_permiso_concedido(db_session):
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session, recurso="clientes", accion="crear")
    asignar_permiso(db_session, rol, permiso)
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario(id_rol=rol.id_rol))

    assert UsuarioService.verificar_permiso(db_session, usuario.id_usuario, "clientes", "crear") is True


def test_verificar_permiso_no_concedido(db_session):
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session, recurso="clientes", accion="crear")
    asignar_permiso(db_session, rol, permiso)
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario(id_rol=rol.id_rol))

    assert UsuarioService.verificar_permiso(db_session, usuario.id_usuario, "clientes", "eliminar") is False
