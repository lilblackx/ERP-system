from app.services.auditoria import AuditoriaService
from app.services.auth import authenticate, hash_password, verify_password
from tests.factories import crear_usuario, crear_usuario_admin


def _crear_usuario_activo(session, **overrides):
    datos = {
        "nombre_usuario": "jperez",
        "nombre": "Juan",
        "apellido": "Perez",
        "email": "jperez@example.com",
        "clave": hash_password("Secreta123"),
        "estado": "ACTIVO",
    }
    datos.update(overrides)
    return crear_usuario(session, **datos)


# --- hash_password / verify_password --------------------------------------------------


def test_hash_password_no_devuelve_texto_plano():
    hashed = hash_password("Secreta123")

    assert hashed != "Secreta123"
    assert verify_password("Secreta123", hashed)


def test_verify_password_rechaza_clave_incorrecta():
    hashed = hash_password("Secreta123")

    assert not verify_password("OtraClave", hashed)


def test_verify_password_hash_invalido_no_lanza():
    assert verify_password("Secreta123", "no-es-un-hash-bcrypt") is False


# --- authenticate --------------------------------------------------------------
# Los usuarios de setup se insertan directo via la factory (no UsuarioService.crear_usuario):
# estos tests prueban authenticate(), no la autorizacion de creacion de usuarios.


def test_authenticate_credenciales_validas(db_session):
    _crear_usuario_activo(db_session)

    usuario = authenticate(db_session, "jperez", "Secreta123")

    assert usuario is not None
    assert usuario.nombre_usuario == "jperez"


def test_authenticate_clave_incorrecta(db_session):
    _crear_usuario_activo(db_session)

    assert authenticate(db_session, "jperez", "ClaveMala") is None


def test_authenticate_usuario_inexistente(db_session):
    assert authenticate(db_session, "no_existe", "Secreta123") is None


def test_authenticate_usuario_inactivo(db_session):
    _crear_usuario_activo(db_session, estado="INACTIVO")

    assert authenticate(db_session, "jperez", "Secreta123") is None


def test_authenticate_usuario_sin_clave(db_session):
    usuario = crear_usuario(db_session, nombre_usuario="sinclave", clave=None)

    assert authenticate(db_session, usuario.nombre_usuario, "cualquier_cosa") is None


def test_authenticate_exitoso_registra_auditoria(db_session):
    admin = crear_usuario_admin(db_session)
    _crear_usuario_activo(db_session)

    usuario = authenticate(db_session, "jperez", "Secreta123")

    resultado = AuditoriaService.consultar_auditoria(
        db_session, modulo="AUTH", accion="LOGIN", id_usuario_actor=admin.id_usuario
    )
    assert resultado["total"] == 1
    assert resultado["items"][0].id_usuario == usuario.id_usuario


def test_authenticate_fallido_no_registra_auditoria(db_session):
    admin = crear_usuario_admin(db_session)
    _crear_usuario_activo(db_session)

    authenticate(db_session, "jperez", "ClaveMala")

    resultado = AuditoriaService.consultar_auditoria(
        db_session, modulo="AUTH", accion="LOGIN", id_usuario_actor=admin.id_usuario
    )
    assert resultado["total"] == 0
