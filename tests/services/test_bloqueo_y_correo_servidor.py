"""Bloqueo temporal y escalonado de cuentas + correo enviado solo por el servidor
(contrasena SMTP cifrada con llave del servidor, cola de correos, avisos a los ADMIN)."""

from datetime import datetime, timedelta
from decimal import Decimal  # noqa: F401  (simetria con el resto de la suite)

import pytest
from sqlalchemy import text

from app import config
from app.db.models import ColaCorreo, ConfiguracionSmtp, Usuario
from app.services import cifrado_servidor
from app.services.auth import CuentaBloqueadaError, authenticate, hash_password
from app.services.bloqueo import (
    MAX_INTENTOS_FALLIDOS,
    bloqueado_hasta,
    duracion_bloqueo,
    esta_bloqueado,
)
from app.services.cola_correos import MAX_INTENTOS_ENVIO, CorreoService
from app.services.notificaciones import NotificacionesService
from app.services.permisos import PermisoDenegadoError, require_permiso
from app.services.smtp_config import SmtpConfigService
from tests.factories import crear_usuario, crear_usuario_admin

CLAVE = "Secreta123!"


@pytest.fixture(autouse=True)
def _llave_en_carpeta_temporal(tmp_path, monkeypatch):
    """Nunca tocar la llave privada real del equipo."""
    monkeypatch.setenv("CLAVE_SERVIDOR_RUTA", str(tmp_path / "clave_servidor.bin"))


@pytest.fixture()
def como_estacion(monkeypatch):
    monkeypatch.setattr(config, "MODO_INSTALACION", "ESTACION")


def _usuario(db_session, **extra):
    return crear_usuario(
        db_session, nombre_usuario="jperez", clave=hash_password(CLAVE), estado="ACTIVO", email="j@example.com", **extra
    )


def _fallar(db_session, veces):
    for _ in range(veces):
        authenticate(db_session, "jperez", "ClaveMala1!")


# ── Bloqueo temporal y escalonado ───────────────────────────────────────────────


def test_duracion_crece_con_los_bloqueos_seguidos_hasta_un_tope():
    assert duracion_bloqueo(MAX_INTENTOS_FALLIDOS) == timedelta(minutes=5)
    assert duracion_bloqueo(MAX_INTENTOS_FALLIDOS + 1) == timedelta(minutes=15)
    assert duracion_bloqueo(MAX_INTENTOS_FALLIDOS + 2) == timedelta(minutes=60)
    assert duracion_bloqueo(MAX_INTENTOS_FALLIDOS + 20) == timedelta(minutes=60)


def test_cuenta_sin_bloqueo_no_esta_bloqueada():
    class _U:
        bloqueado_desde = None

    assert bloqueado_hasta(_U()) is None
    assert not esta_bloqueado(_U())


def test_el_bloqueo_vence_solo_y_el_login_correcto_vuelve_a_funcionar(db_session):
    usuario = _usuario(db_session)
    _fallar(db_session, MAX_INTENTOS_FALLIDOS)
    with pytest.raises(CuentaBloqueadaError) as exc:
        authenticate(db_session, "jperez", CLAVE)
    assert exc.value.bloqueado_hasta is not None
    assert "Intente de nuevo en" in str(exc.value)

    # Pasaron 6 minutos: el bloqueo de 5 ya venció.
    usuario.bloqueado_desde = datetime.now() - timedelta(minutes=6)
    db_session.commit()

    assert authenticate(db_session, "jperez", CLAVE) is not None
    db_session.refresh(usuario)
    assert usuario.bloqueado_desde is None
    assert usuario.intentos_fallidos == 0


def test_tras_vencer_un_solo_fallo_mas_aplica_un_bloqueo_mas_largo(db_session):
    usuario = _usuario(db_session)
    _fallar(db_session, MAX_INTENTOS_FALLIDOS)
    usuario.bloqueado_desde = datetime.now() - timedelta(minutes=6)
    db_session.commit()

    authenticate(db_session, "jperez", "ClaveMala1!")  # un fallo mas
    db_session.refresh(usuario)

    assert esta_bloqueado(usuario)
    assert bloqueado_hasta(usuario) - usuario.bloqueado_desde == timedelta(minutes=15)


def test_un_bloqueo_vencido_no_corta_la_sesion_de_un_usuario_ya_logueado(db_session):
    admin = crear_usuario_admin(db_session, bloqueado_desde=datetime.now() - timedelta(minutes=10), intentos_fallidos=5)
    require_permiso(db_session, admin.id_usuario, "ventas", "ver")  # no lanza


def test_un_bloqueo_vigente_si_corta_la_sesion(db_session):
    admin = crear_usuario_admin(db_session, bloqueado_desde=datetime.now(), intentos_fallidos=5)
    with pytest.raises(PermisoDenegadoError, match="bloqueado"):
        require_permiso(db_session, admin.id_usuario, "ventas", "ver")


def test_la_auditoria_del_fallo_indica_desde_que_equipo(db_session):
    from app.db.models import Auditoria

    _usuario(db_session)
    _fallar(db_session, 1)

    detalle = db_session.query(Auditoria).filter_by(accion="LOGIN_FALLIDO").one().detalle
    assert " desde " in detalle


def test_la_campana_avisa_de_cuentas_bloqueadas_solo_mientras_dura(db_session):
    admin = crear_usuario_admin(db_session)
    usuario = _usuario(db_session)
    _fallar(db_session, MAX_INTENTOS_FALLIDOS)

    claves = [n.clave for n in NotificacionesService.obtener(db_session, admin.id_usuario)]
    assert "cuentas_bloqueadas" in claves

    usuario.bloqueado_desde = datetime.now() - timedelta(minutes=10)
    db_session.commit()
    claves = [n.clave for n in NotificacionesService.obtener(db_session, admin.id_usuario)]
    assert "cuentas_bloqueadas" not in claves


# ── Aviso a los administradores ─────────────────────────────────────────────────


def test_el_bloqueo_encola_aviso_a_los_admin_desde_una_estacion(db_session, como_estacion):
    crear_usuario_admin(db_session, email="admin@example.com")
    _usuario(db_session)

    _fallar(db_session, MAX_INTENTOS_FALLIDOS)

    avisos = db_session.query(ColaCorreo).filter_by(tipo="AVISO_BLOQUEO", estado="PENDIENTE").all()
    assert [a.destinatario for a in avisos] == ["admin@example.com"]
    assert "jperez" in avisos[0].asunto


def test_el_aviso_de_bloqueo_no_se_repite_en_30_minutos(db_session, como_estacion):
    crear_usuario_admin(db_session, email="admin@example.com")
    usuario = _usuario(db_session)
    _fallar(db_session, MAX_INTENTOS_FALLIDOS)
    usuario.bloqueado_desde = datetime.now() - timedelta(minutes=6)
    db_session.commit()

    _fallar(db_session, 1)  # nuevo bloqueo, pero hace pocos minutos que ya se aviso

    assert db_session.query(ColaCorreo).filter_by(tipo="AVISO_BLOQUEO").count() == 1


def test_un_fallo_del_aviso_nunca_rompe_el_login(db_session, monkeypatch):
    crear_usuario_admin(db_session, email="admin@example.com")
    _usuario(db_session)

    def _revienta(*a, **k):
        raise RuntimeError("SMTP caido")

    monkeypatch.setattr("app.services.cola_correos.enviar_correo", _revienta)
    _fallar(db_session, MAX_INTENTOS_FALLIDOS)  # no lanza

    with pytest.raises(CuentaBloqueadaError):
        authenticate(db_session, "jperez", CLAVE)


# ── Contrasena SMTP cifrada ─────────────────────────────────────────────────────


def _guardar_smtp(db_session, admin, password="abcd efgh ijkl mnop"):
    return SmtpConfigService.guardar_configuracion(
        db_session,
        host="smtp.gmail.com",
        puerto=587,
        usuario="empresa@gmail.com",
        password=password,
        modificado_por=admin.id_usuario,
    )


def test_la_contrasena_smtp_se_guarda_cifrada_y_el_servidor_la_lee(db_session):
    admin = crear_usuario_admin(db_session)

    fila = _guardar_smtp(db_session, admin, "abcd efgh ijkl mnop")

    assert fila.password is None
    assert fila.password_cifrada
    assert "abcd" not in fila.password_cifrada
    assert SmtpConfigService.obtener_efectiva(db_session).password == "abcd efgh ijkl mnop"


def test_una_contrasena_larga_tambien_se_cifra(db_session):
    admin = crear_usuario_admin(db_session)
    larga = "Ñandú-" + "x" * 240

    _guardar_smtp(db_session, admin, larga)

    assert SmtpConfigService.obtener_efectiva(db_session).password == larga


def test_una_estacion_guarda_la_contrasena_pero_no_puede_leerla(db_session, monkeypatch, tmp_path):
    admin = crear_usuario_admin(db_session)
    _guardar_smtp(db_session, admin)  # el servidor ya creo la llave publica

    monkeypatch.setattr(config, "MODO_INSTALACION", "ESTACION")
    monkeypatch.setenv("CLAVE_SERVIDOR_RUTA", str(tmp_path / "otra_pc" / "clave.bin"))  # esta PC no tiene la privada
    _guardar_smtp(db_session, admin, "otra-clave-123456")

    fila = db_session.query(ConfiguracionSmtp).one()
    assert fila.password_cifrada and fila.password is None
    assert SmtpConfigService.obtener_efectiva(db_session).password == ""
    assert not SmtpConfigService.obtener_efectiva(db_session).configurado


def test_una_estacion_no_puede_guardar_si_el_servidor_nunca_creo_la_llave(db_session, como_estacion):
    admin = crear_usuario_admin(db_session)

    with pytest.raises(ValueError, match="servidor"):
        _guardar_smtp(db_session, admin)


def test_la_contrasena_en_texto_plano_de_antes_se_migra_a_cifrada(db_session):
    admin = crear_usuario_admin(db_session)
    db_session.add(
        ConfiguracionSmtp(host="smtp.gmail.com", puerto=587, usuario="e@gmail.com", password="vieja-plana-1234")
    )
    db_session.commit()
    # Mientras no se migra, sigue funcionando.
    assert SmtpConfigService.obtener_efectiva(db_session).password == "vieja-plana-1234"

    assert SmtpConfigService.migrar_password(db_session) is True

    fila = db_session.query(ConfiguracionSmtp).one()
    assert fila.password is None and fila.password_cifrada
    assert SmtpConfigService.obtener_efectiva(db_session).password == "vieja-plana-1234"
    assert SmtpConfigService.migrar_password(db_session) is False  # idempotente
    del admin


def test_si_el_servidor_pierde_su_llave_la_contrasena_se_descarta_y_se_pide_de_nuevo(db_session, tmp_path, monkeypatch):
    admin = crear_usuario_admin(db_session)
    _guardar_smtp(db_session, admin)

    monkeypatch.setenv("CLAVE_SERVIDOR_RUTA", str(tmp_path / "reinstalado" / "clave.bin"))
    cifrado_servidor.asegurar_clave(db_session)

    fila = db_session.query(ConfiguracionSmtp).one()
    assert fila.password_cifrada is None
    assert not SmtpConfigService.tiene_password(fila)


def test_vaciar_la_contrasena_borra_las_dos_columnas(db_session):
    admin = crear_usuario_admin(db_session)
    _guardar_smtp(db_session, admin)

    fila = _guardar_smtp(db_session, admin, password=None)

    assert fila.password is None and fila.password_cifrada is None


# ── Cola de correos ─────────────────────────────────────────────────────────────


def _encolar(db_session, destinatario="a@example.com", asunto="Codigo", cuerpo="Tu codigo es: 123456", **kw):
    return CorreoService.enviar_o_encolar(db_session, destinatario, asunto, cuerpo, tipo="CODIGO_TEST", **kw)


def test_el_servidor_envia_directo_sin_pasar_por_la_cola(db_session, monkeypatch):
    enviados = []
    monkeypatch.setattr("app.services.cola_correos.enviar_correo", lambda *a, **k: enviados.append(a))

    resultado = _encolar(db_session)

    assert resultado is True
    assert len(enviados) == 1
    assert db_session.query(ColaCorreo).count() == 0


def test_una_estacion_deja_el_correo_en_la_cola_sin_enviarlo(db_session, como_estacion, monkeypatch):
    monkeypatch.setattr(
        "app.services.cola_correos.enviar_correo", lambda *a, **k: pytest.fail("una estacion no debe enviar")
    )

    resultado = _encolar(db_session)

    assert resultado is False
    correo = db_session.query(ColaCorreo).one()
    assert correo.estado == "PENDIENTE" and correo.cuerpo == "Tu codigo es: 123456"


def test_el_servidor_despacha_la_cola_y_borra_el_contenido(db_session, monkeypatch):
    admin = crear_usuario_admin(db_session)
    _guardar_smtp(db_session, admin)
    ahora = datetime.now()
    db_session.add(
        ColaCorreo(
            tipo="CODIGO_TEST",
            destinatario="a@example.com",
            asunto="Codigo",
            cuerpo="Tu codigo es: 123456",
            fecha_vencimiento=ahora + timedelta(minutes=15),
        )
    )
    db_session.commit()
    enviados = []
    monkeypatch.setattr(
        "app.services.cola_correos.enviar_correo",
        lambda dest, asunto, cuerpo, cuerpo_html=None, ajustes=None: enviados.append((dest, cuerpo, ajustes.password)),
    )

    resultado = CorreoService.procesar_pendientes(db_session)

    assert resultado["enviados"] == 1
    assert enviados == [("a@example.com", "Tu codigo es: 123456", "abcd efgh ijkl mnop")]
    correo = db_session.query(ColaCorreo).one()
    assert correo.estado == "ENVIADO" and correo.cuerpo == "" and correo.fecha_envio is not None


def test_una_estacion_no_despacha_la_cola(db_session, como_estacion):
    _encolar(db_session)

    assert CorreoService.procesar_pendientes(db_session) == {"enviados": 0, "errores": 0, "vencidos": 0}
    assert db_session.query(ColaCorreo).one().estado == "PENDIENTE"


def test_un_correo_que_falla_se_reintenta_y_tras_3_intentos_queda_en_error(db_session, monkeypatch):
    admin = crear_usuario_admin(db_session)
    _guardar_smtp(db_session, admin)
    db_session.add(
        ColaCorreo(
            tipo="CODIGO_TEST",
            destinatario="a@example.com",
            asunto="Codigo",
            cuerpo="123456",
            fecha_vencimiento=datetime.now() + timedelta(minutes=15),
        )
    )
    db_session.commit()

    def _falla(*a, **k):
        raise RuntimeError("SMTP caido")

    monkeypatch.setattr("app.services.cola_correos.enviar_correo", _falla)

    for intento in range(1, MAX_INTENTOS_ENVIO + 1):
        CorreoService.procesar_pendientes(db_session)
        db_session.expire_all()
        correo = db_session.query(ColaCorreo).one()
        assert correo.intentos == intento

    assert correo.estado == "ERROR"
    assert correo.cuerpo == ""  # no queda el codigo en la base
    assert "SMTP caido" in correo.error
    # Un 4to pase ya no lo toca.
    CorreoService.procesar_pendientes(db_session)
    db_session.expire_all()
    assert db_session.query(ColaCorreo).one().intentos == MAX_INTENTOS_ENVIO


def test_un_codigo_vencido_se_descarta_sin_enviarse(db_session, monkeypatch):
    admin = crear_usuario_admin(db_session)
    _guardar_smtp(db_session, admin)
    db_session.add(
        ColaCorreo(
            tipo="CODIGO_TEST",
            destinatario="a@example.com",
            asunto="Codigo",
            cuerpo="123456",
            fecha_vencimiento=datetime.now() - timedelta(minutes=1),
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        "app.services.cola_correos.enviar_correo", lambda *a, **k: pytest.fail("no debe enviar un codigo vencido")
    )

    resultado = CorreoService.procesar_pendientes(db_session)

    assert resultado["vencidos"] == 1
    correo = db_session.query(ColaCorreo).one()
    assert correo.estado == "ERROR" and correo.cuerpo == ""


def test_un_correo_colgado_en_enviando_se_recupera(db_session, monkeypatch):
    admin = crear_usuario_admin(db_session)
    _guardar_smtp(db_session, admin)
    hace_10 = datetime.now() - timedelta(minutes=10)
    db_session.add(
        ColaCorreo(
            tipo="CODIGO_TEST",
            destinatario="a@example.com",
            asunto="Codigo",
            cuerpo="123456",
            estado="ENVIANDO",
            intentos=1,
            fecha_actualizacion=hace_10,
            fecha_vencimiento=datetime.now() + timedelta(minutes=5),
        )
    )
    db_session.commit()
    enviados = []
    monkeypatch.setattr("app.services.cola_correos.enviar_correo", lambda *a, **k: enviados.append(a))

    CorreoService.procesar_pendientes(db_session)

    assert len(enviados) == 1


def test_dos_despachadores_a_la_vez_no_envian_dos_veces_el_mismo_correo(db_session, test_engine, monkeypatch):
    """El UPDATE ... OUTPUT que reclama los correos es atomico: lo que ya reclamo uno, el otro
    no lo ve."""
    admin = crear_usuario_admin(db_session)
    _guardar_smtp(db_session, admin)
    for i in range(4):
        db_session.add(
            ColaCorreo(
                tipo="CODIGO_TEST",
                destinatario=f"u{i}@example.com",
                asunto="Codigo",
                cuerpo="123456",
                fecha_vencimiento=datetime.now() + timedelta(minutes=15),
            )
        )
    db_session.commit()
    enviados = []
    monkeypatch.setattr("app.services.cola_correos.enviar_correo", lambda dest, *a, **k: enviados.append(dest))

    from sqlalchemy.orm import sessionmaker

    otra = sessionmaker(bind=test_engine)()
    try:
        CorreoService.procesar_pendientes(db_session, limite=2)
        CorreoService.procesar_pendientes(otra, limite=10)
    finally:
        otra.close()

    assert sorted(enviados) == [f"u{i}@example.com" for i in range(4)]


def test_la_cola_purga_el_historial_viejo(db_session, monkeypatch):
    admin = crear_usuario_admin(db_session)
    _guardar_smtp(db_session, admin)
    viejo = datetime.now() - timedelta(days=10)
    db_session.add(
        ColaCorreo(
            tipo="X",
            destinatario="a@example.com",
            asunto="Viejo",
            cuerpo="",
            estado="ENVIADO",
            fecha_actualizacion=viejo,
            fecha_vencimiento=viejo,
        )
    )
    db_session.commit()
    monkeypatch.setattr("app.services.cola_correos.enviar_correo", lambda *a, **k: None)
    _encolar_pendiente = ColaCorreo(
        tipo="Y",
        destinatario="b@example.com",
        asunto="Nuevo",
        cuerpo="1",
        fecha_vencimiento=datetime.now() + timedelta(minutes=5),
    )
    db_session.add(_encolar_pendiente)
    db_session.commit()

    CorreoService.procesar_pendientes(db_session)

    asuntos = [c.asunto for c in db_session.query(ColaCorreo).all()]
    assert "Viejo" not in asuntos and "Nuevo" in asuntos


# ── Recuperacion de clave por estacion ──────────────────────────────────────────


def test_la_estacion_encola_el_codigo_de_desbloqueo_y_el_servidor_lo_manda(db_session, monkeypatch, tmp_path):
    from app.services.recuperacion_acceso import RecuperacionAccesoService

    admin = crear_usuario_admin(db_session)
    _guardar_smtp(db_session, admin)
    usuario = _usuario(db_session)
    _fallar(db_session, MAX_INTENTOS_FALLIDOS)

    monkeypatch.setattr(config, "MODO_INSTALACION", "ESTACION")
    RecuperacionAccesoService.solicitar_codigo_desbloqueo(db_session, "jperez")
    correo = db_session.query(ColaCorreo).filter_by(tipo="CODIGO_DESBLOQUEO").one()
    codigo = correo.cuerpo.split(":")[1].split("\n")[0].strip()
    assert correo.destinatario == "j@example.com"

    monkeypatch.setattr(config, "MODO_INSTALACION", "SERVIDOR")
    enviados = []
    monkeypatch.setattr("app.services.cola_correos.enviar_correo", lambda dest, *a, **k: enviados.append(dest))
    CorreoService.procesar_pendientes(db_session)
    assert enviados == ["j@example.com"]

    RecuperacionAccesoService.verificar_codigo_desbloqueo(db_session, "jperez", codigo)
    db_session.refresh(usuario)
    assert usuario.bloqueado_desde is None


def test_los_tests_no_dejan_bloqueos_ajenos(db_session):
    assert db_session.query(Usuario).filter(Usuario.bloqueado_desde.isnot(None)).count() == 0
    assert db_session.execute(text("SELECT COUNT(*) FROM dbo.cola_correos")).scalar() == 0
