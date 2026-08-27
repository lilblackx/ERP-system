import pytest

from app.services.auditoria import AuditoriaService
from app.services.auth import (
    MAX_INTENTOS_FALLIDOS,
    PASSWORD_MAX_BYTES,
    PASSWORD_MIN_LENGTH,
    CuentaBloqueadaError,
    authenticate,
    hash_password,
    validar_password_policy,
    verify_password,
)
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


def test_authenticate_accion_exito_personalizada(db_session):
    """AutorizacionDescuentoDialog reusa authenticate() con accion_exito distinta de
    'LOGIN' para no ensuciar la auditoria con inicios de sesion que nunca ocurrieron
    (ver app/ui/autorizacion_dialog.py)."""
    admin = crear_usuario_admin(db_session)
    _crear_usuario_activo(db_session)

    authenticate(db_session, "jperez", "Secreta123", accion_exito="AUTORIZACION_DESCUENTO")

    sin_login = AuditoriaService.consultar_auditoria(
        db_session, modulo="AUTH", accion="LOGIN", id_usuario_actor=admin.id_usuario
    )
    con_accion_custom = AuditoriaService.consultar_auditoria(
        db_session, modulo="AUTH", accion="AUTORIZACION_DESCUENTO", id_usuario_actor=admin.id_usuario
    )
    assert sin_login["total"] == 0
    assert con_accion_custom["total"] == 1


def test_authenticate_accion_fallo_personalizada(db_session):
    admin = crear_usuario_admin(db_session)
    _crear_usuario_activo(db_session)

    authenticate(db_session, "jperez", "ClaveMala", accion_fallo="AUTORIZACION_DESCUENTO_FALLIDA")

    sin_login_fallido = AuditoriaService.consultar_auditoria(
        db_session, modulo="AUTH", accion="LOGIN_FALLIDO", id_usuario_actor=admin.id_usuario
    )
    con_accion_custom = AuditoriaService.consultar_auditoria(
        db_session, modulo="AUTH", accion="AUTORIZACION_DESCUENTO_FALLIDA", id_usuario_actor=admin.id_usuario
    )
    assert sin_login_fallido["total"] == 0
    assert con_accion_custom["total"] == 1


# --- lockout tras intentos fallidos (C7) ----------------------------------------------


def test_authenticate_fallido_registra_auditoria_login_fallido(db_session):
    admin = crear_usuario_admin(db_session)
    _crear_usuario_activo(db_session)

    authenticate(db_session, "jperez", "ClaveMala")

    resultado = AuditoriaService.consultar_auditoria(
        db_session, modulo="AUTH", accion="LOGIN_FALLIDO", id_usuario_actor=admin.id_usuario
    )
    assert resultado["total"] == 1


def test_authenticate_incrementa_intentos_fallidos(db_session):
    usuario = _crear_usuario_activo(db_session)

    authenticate(db_session, "jperez", "ClaveMala")
    authenticate(db_session, "jperez", "ClaveMala")

    db_session.refresh(usuario)
    assert usuario.intentos_fallidos == 2


def test_authenticate_exitoso_resetea_intentos_fallidos(db_session):
    usuario = _crear_usuario_activo(db_session)

    authenticate(db_session, "jperez", "ClaveMala")
    authenticate(db_session, "jperez", "Secreta123")

    db_session.refresh(usuario)
    assert usuario.intentos_fallidos == 0
    assert usuario.bloqueado_desde is None


def test_authenticate_bloquea_tras_max_intentos_fallidos(db_session):
    usuario = _crear_usuario_activo(db_session)

    for _ in range(MAX_INTENTOS_FALLIDOS):
        authenticate(db_session, "jperez", "ClaveMala")

    db_session.refresh(usuario)
    assert usuario.bloqueado_desde is not None

    with pytest.raises(CuentaBloqueadaError):
        authenticate(db_session, "jperez", "Secreta123")


# --- validar_password_policy (C6) -----------------------------------------------------
# Se ejercita indirectamente via UsuarioService/RecuperacionAccesoService, pero ningun
# test la llamaba por nombre -- estos cubren cada regla por separado.


def test_validar_password_policy_clave_valida_no_lanza():
    validar_password_policy("Secreta123!")


def test_validar_password_policy_muy_corta():
    assert len("Aa1!") < PASSWORD_MIN_LENGTH
    with pytest.raises(ValueError, match=f"minimo {PASSWORD_MIN_LENGTH} caracteres"):
        validar_password_policy("Aa1!")


def test_validar_password_policy_sin_mayuscula():
    with pytest.raises(ValueError, match="una mayuscula"):
        validar_password_policy("secreta123!")


def test_validar_password_policy_sin_minuscula():
    with pytest.raises(ValueError, match="una minuscula"):
        validar_password_policy("SECRETA123!")


def test_validar_password_policy_sin_numero():
    with pytest.raises(ValueError, match="un numero"):
        validar_password_policy("Secretaaa!")


def test_validar_password_policy_sin_caracter_especial():
    with pytest.raises(ValueError, match="un caracter especial"):
        validar_password_policy("Secreta123")


def test_validar_password_policy_acumula_todas_las_faltantes():
    with pytest.raises(ValueError) as exc_info:
        validar_password_policy("abc")
    mensaje = str(exc_info.value)
    assert "mayuscula" in mensaje
    assert "numero" in mensaje
    assert "caracter especial" in mensaje


def test_validar_password_policy_rechaza_clave_mas_larga_que_72_bytes():
    """bcrypt (hash_password) exige <=72 bytes utf-8 -- sin este tope, una clave mas
    larga fallaba con un ValueError crudo de la libreria bcrypt en vez de un mensaje
    claro, o en versiones viejas la truncaba en silencio sin avisar."""
    clave_larga = "Aa1!" + "x" * (PASSWORD_MAX_BYTES)
    assert len(clave_larga.encode("utf-8")) > PASSWORD_MAX_BYTES
    with pytest.raises(ValueError, match=f"maximo {PASSWORD_MAX_BYTES} bytes"):
        validar_password_policy(clave_larga)


def test_authenticate_bloqueado_no_verifica_clave_correcta(db_session):
    """Mientras la cuenta esta bloqueada, ni siquiera una clave correcta debe pasar --
    de lo contrario el bloqueo seria inutil (bastaria con la clave real para saltarselo)."""
    usuario = _crear_usuario_activo(db_session)
    for _ in range(MAX_INTENTOS_FALLIDOS):
        authenticate(db_session, "jperez", "ClaveMala")
    db_session.refresh(usuario)
    assert usuario.bloqueado_desde is not None

    with pytest.raises(CuentaBloqueadaError):
        authenticate(db_session, "jperez", "Secreta123")
