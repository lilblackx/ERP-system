from datetime import datetime

import pytest

from app.services.auth import verify_password
from app.services.permisos import PermisoDenegadoError
from app.services.usuarios import UsuarioService
from tests.factories import (
    asignar_permiso,
    crear_permiso,
    crear_rol,
    crear_usuario,
    crear_usuario_admin,
    crear_vendedor,
)


def _datos_usuario(**overrides) -> dict:
    # email se deriva de nombre_usuario (en vez de un literal fijo) para que dos llamadas
    # con distinto nombre_usuario en el mismo test no choquen contra el nuevo requisito
    # de email unico (auditoria de Usuarios, 2026-08-27) -- overrides["email"] explicito
    # sigue ganando via el update() de abajo.
    nombre_usuario = overrides.get("nombre_usuario", "jperez")
    datos = {
        "nombre_usuario": nombre_usuario,
        "nombre": "Juan",
        "apellido": "Perez",
        "email": f"{nombre_usuario}@example.com",
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


def test_crear_usuario_requiere_email(db_session):
    """El correo es a donde RecuperacionAccesoService envia los codigos de desbloqueo y
    recuperacion de clave -- un usuario sin correo registrado queda sin forma de
    recuperar el acceso por si solo."""
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="email"):
        UsuarioService.crear_usuario(db_session, **_datos_usuario(email=""), realizado_por=admin.id_usuario)


def test_crear_usuario_nombre_duplicado(db_session):
    admin = crear_usuario_admin(db_session)
    UsuarioService.crear_usuario(db_session, **_datos_usuario(), realizado_por=admin.id_usuario)

    with pytest.raises(ValueError, match="ya esta en uso"):
        UsuarioService.crear_usuario(
            db_session, **_datos_usuario(email="otro@example.com"), realizado_por=admin.id_usuario
        )


def test_crear_usuario_email_duplicado(db_session):
    """Auditoria de Usuarios (2026-08-27): el correo identifica a donde van los codigos
    de desbloqueo/recuperacion -- dos usuarios con el mismo correo podrian recibir el
    codigo del otro."""
    admin = crear_usuario_admin(db_session)
    UsuarioService.crear_usuario(db_session, **_datos_usuario(), realizado_por=admin.id_usuario)

    with pytest.raises(ValueError, match="ya esta en uso"):
        UsuarioService.crear_usuario(
            db_session,
            **_datos_usuario(nombre_usuario="otro_user", email="jperez@example.com"),
            realizado_por=admin.id_usuario,
        )


def test_crear_usuario_nombre_usuario_muy_largo(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="nombre_usuario no puede superar"):
        UsuarioService.crear_usuario(
            db_session, **_datos_usuario(nombre_usuario="x" * 51), realizado_por=admin.id_usuario
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


def test_crear_usuario_vendedor_ya_vinculado_a_otro_usuario_falla(db_session):
    """Auditoria de Usuarios (2026-08-27): dos logins distintos vinculados al mismo
    Vendedor mezclarian reportes/comisiones entre ambos sin forma de distinguirlos."""
    admin = crear_usuario_admin(db_session)
    rol = crear_rol(db_session, nombre="VENDEDOR")
    vendedor = crear_vendedor(db_session)
    UsuarioService.crear_usuario(
        db_session,
        **_datos_usuario(id_rol=rol.id_rol, id_vendedor_usuario=vendedor.id_vendedor),
        realizado_por=admin.id_usuario,
    )

    with pytest.raises(ValueError, match="ya esta vinculado"):
        UsuarioService.crear_usuario(
            db_session,
            **_datos_usuario(
                nombre_usuario="otro_user",
                email="otro@example.com",
                id_rol=rol.id_rol,
                id_vendedor_usuario=vendedor.id_vendedor,
            ),
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


def test_editar_usuario_no_permite_vaciar_email(db_session):
    """Mismo motivo que test_crear_usuario_requiere_email: una edicion no debe poder
    dejar a un usuario existente sin correo registrado."""
    admin = crear_usuario_admin(db_session)
    usuario = UsuarioService.crear_usuario(db_session, **_datos_usuario(), realizado_por=admin.id_usuario)

    with pytest.raises(ValueError, match="email"):
        UsuarioService.editar_usuario(db_session, usuario.id_usuario, {"email": ""}, realizado_por=admin.id_usuario)


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


def test_editar_usuario_email_duplicado(db_session):
    admin = crear_usuario_admin(db_session)
    UsuarioService.crear_usuario(
        db_session, **_datos_usuario(nombre_usuario="usuario1", email="uno@example.com"), realizado_por=admin.id_usuario
    )
    otro = UsuarioService.crear_usuario(
        db_session, **_datos_usuario(nombre_usuario="usuario2", email="dos@example.com"), realizado_por=admin.id_usuario
    )

    with pytest.raises(ValueError, match="ya esta en uso"):
        UsuarioService.editar_usuario(
            db_session, otro.id_usuario, {"email": "uno@example.com"}, realizado_por=admin.id_usuario
        )


def test_editar_usuario_mismo_email_no_falla(db_session):
    admin = crear_usuario_admin(db_session)
    usuario = UsuarioService.crear_usuario(
        db_session, **_datos_usuario(email="uno@example.com"), realizado_por=admin.id_usuario
    )

    actualizado = UsuarioService.editar_usuario(
        db_session,
        usuario.id_usuario,
        {"email": "uno@example.com", "nombre": "X"},
        realizado_por=admin.id_usuario,
    )

    assert actualizado.email == "uno@example.com"


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

    actualizado = UsuarioService.cambiar_estado(
        db_session, usuario.id_usuario, "INACTIVO", realizado_por=admin.id_usuario
    )

    assert actualizado.estado == "INACTIVO"


def test_cambiar_estado_no_permite_auto_desactivarse(db_session):
    """Auditoria de Usuarios (2026-08-27): antes este guard solo existia en la UI
    (usuarios_panel.py) -- cualquier otro punto de entrada al servicio podia desactivar
    la propia cuenta sin aviso."""
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="No puedes desactivar tu propia cuenta"):
        UsuarioService.cambiar_estado(db_session, admin.id_usuario, "INACTIVO", realizado_por=admin.id_usuario)


def test_cambiar_estado_no_permite_desactivar_al_unico_admin_activo(db_session):
    """El guard de auto-desactivacion ya cubre el caso obvio (un ADMIN no puede
    desactivarse a si mismo). Este cubre el caso donde OTRO actor con 'usuarios'/
    'editar' (hoy nadie fuera de ADMIN lo tiene, pero un futuro rol Supervisor si podria)
    intenta desactivar al unico ADMIN activo restante, dejando el sistema sin nadie que
    pueda gestionar Usuarios/Permisos salvo tocando la base directo."""
    admin = crear_usuario_admin(db_session)
    rol_supervisor = crear_rol(db_session, nombre="SUPERVISOR")
    permiso = crear_permiso(db_session, recurso="usuarios", accion="editar")
    asignar_permiso(db_session, rol_supervisor, permiso)
    supervisor = crear_usuario(db_session, nombre_usuario="supervisor1", id_rol=rol_supervisor.id_rol)

    with pytest.raises(ValueError, match="unico administrador activo"):
        UsuarioService.cambiar_estado(db_session, admin.id_usuario, "INACTIVO", realizado_por=supervisor.id_usuario)


def test_cambiar_estado_permite_desactivar_admin_si_hay_otro_activo(db_session):
    admin_1 = crear_usuario_admin(db_session)
    admin_2 = crear_usuario_admin(db_session, nombre_usuario="admin2")

    actualizado = UsuarioService.cambiar_estado(
        db_session, admin_1.id_usuario, "INACTIVO", realizado_por=admin_2.id_usuario
    )

    assert actualizado.estado == "INACTIVO"
    assert admin_2.estado == "ACTIVO"


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
    UsuarioService.crear_usuario(db_session, **_datos_usuario(nombre_usuario="sinrol"), realizado_por=admin.id_usuario)

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
        db_session,
        **_datos_usuario(nombre="Juan", apellido="Perez", nombre_usuario="jperez2"),
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


def test_verificar_permiso_usuario_inactivo_es_false_aunque_tenga_el_permiso(db_session):
    """C17: un usuario desactivado no debe seguir pasando el chequeo de permisos aunque
    su rol si tenga el permiso concedido en la matriz."""
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session, recurso="clientes", accion="crear")
    asignar_permiso(db_session, rol, permiso)
    usuario = crear_usuario(db_session, id_rol=rol.id_rol, estado="INACTIVO")

    assert UsuarioService.verificar_permiso(db_session, usuario.id_usuario, "clientes", "crear") is False


def test_verificar_permiso_usuario_bloqueado_es_false_aunque_tenga_el_permiso(db_session):
    """C17: un usuario bloqueado (bloqueado_desde no nulo) no debe seguir pasando el
    chequeo de permisos aunque su rol si tenga el permiso concedido en la matriz."""
    rol = crear_rol(db_session)
    permiso = crear_permiso(db_session, recurso="clientes", accion="crear")
    asignar_permiso(db_session, rol, permiso)
    usuario = crear_usuario(db_session, id_rol=rol.id_rol, bloqueado_desde=datetime.now())

    assert UsuarioService.verificar_permiso(db_session, usuario.id_usuario, "clientes", "crear") is False


def test_verificar_permiso_admin_bypassa_sin_filas_en_rol_permisos(db_session):
    """Bug preexistente sin caller real hasta que app/ui/sidebar.py empezo a usar este
    metodo para filtrar el menu por rol (2026-08-27): a diferencia de
    PermisoService.require_permiso(), este metodo no tenia el bypass de ADMIN -- un ADMIN
    real (sin filas en rol_permisos, ver el seed de schema_sqlserver.sql) quedaba
    evaluado como si no tuviera ningun permiso."""
    admin = crear_usuario_admin(db_session)
    assert UsuarioService.verificar_permiso(db_session, admin.id_usuario, "clientes", "eliminar") is True
    assert UsuarioService.verificar_permiso(db_session, admin.id_usuario, "usuarios", "crear") is True
