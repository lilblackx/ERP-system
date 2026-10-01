"""Tests de app/services/licencia.py. La red se simula (se firman tokens con una clave
Ed25519 de prueba y se monkeypatchea `_post`); el almacen es en memoria salvo en los tests
marcados "SQL Server", que ejercitan AlmacenDB contra la base de pruebas. El gate se prueba
contra SQLite en memoria (el hook es a nivel de motor SQLAlchemy, no depende de SQL Server)."""

import base64
import json
import time
from datetime import datetime

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app import config
from app.services import licencia
from app.services.licencia import (
    ESTADO_ACTIVA,
    ESTADO_INVALIDA,
    ESTADO_LIMITE_ESTACIONES,
    ESTADO_REVOCADA,
    ESTADO_SIN_LICENCIA,
    ESTADO_VALIDAR_EN_LINEA,
    ESTADO_VENCIDA,
    AlmacenDB,
    LicenciaError,
    LicenciaService,
    LicenciaSoloLecturaError,
)

CLAVE = "ABCDE-FGHJK-MNPQR-STVWX"
DIA = 86400
OTRA_PC = "b" * 64


def _b64u(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode("ascii")


class AlmacenMemoria:
    """Hace de SQL Server para los tests: una fila de licencia + las estaciones."""

    def __init__(self):
        self.datos: dict | None = None
        self.filas: dict[str, dict] = {}

    marcas: dict
    desfase_hora = 0.0  # segundos que el "SQL Server" adelanta/atrasa respecto al reloj real

    def leer(self):
        if not self.datos:
            return None
        return {**self.datos, **getattr(self, "marcas", {})}

    def guardar(self, datos):
        self.datos = dict(datos)

    def guardar_marcas(self, marcas, reemplazar=False):
        if self.datos is None:
            return
        actuales = getattr(self, "marcas", {})
        if reemplazar:
            self.marcas = {k: int(v) for k, v in marcas.items()}
        else:
            self.marcas = {
                **actuales,
                "ultimo_visto": max(int(marcas["ultimo_visto"]), actuales.get("ultimo_visto", 0)),
            }

    def hora_servidor(self):
        return time.time() + self.desfase_hora

    def estaciones(self):
        return [{"hw_id": hw, **f} for hw, f in self.filas.items()]

    def registrar_estacion(self, hw, nombre):
        self.filas[hw] = {"nombre": nombre, "primera_vez": datetime.now(), "ultima_vez": datetime.now()}


@pytest.fixture()
def servidor(monkeypatch, tmp_path):
    """Entorno de licenciamiento aislado + un 'servidor de licencias' que firma tokens."""
    privada = Ed25519PrivateKey.generate()
    publica_b64 = base64.b64encode(privada.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    monkeypatch.setattr(config, "LICENCIA_URL", "https://licencias.test")
    monkeypatch.setattr(config, "LICENCIA_PUBLIC_KEY_B64", publica_b64)
    monkeypatch.setattr(config, "MODO_INSTALACION", "SERVIDOR")
    monkeypatch.setattr(licencia, "RUTA_RELOJ", tmp_path / "reloj.dat")
    monkeypatch.setattr(licencia, "_almacen", AlmacenMemoria())
    monkeypatch.setattr(licencia, "_marcas_cache", (dict(licencia._MARCAS_VACIAS), 0.0))
    monkeypatch.setattr(licencia, "CLAVE_REGISTRO", None)  # las pruebas no tocan el registro real
    monkeypatch.setattr(licencia, "_ancla_hora", None)
    monkeypatch.setattr(licencia, "_ultimo_reloj_persistido", 0.0)
    monkeypatch.setattr(licencia, "_ultimo_registro_estacion", 0.0)
    licencia.invalidar_cache()

    class Servidor:
        respuesta: tuple[int, dict] = (200, {})
        llamadas: list = []

        def firmar(self, **campos):
            ahora = int(time.time())
            payload = {
                "v": 1,
                "hw": licencia.hw_id(),
                "plan": "pro",
                "cliente": "Cliente SA",
                "expira": ahora + 30 * DIA,
                "max_estaciones": 3,
                "estaciones": [],
                "emitido": ahora,
                "valido_hasta": ahora + 7 * DIA,
                **campos,
            }
            cuerpo = _b64u(json.dumps(payload).encode())
            return f"{cuerpo}.{_b64u(privada.sign(cuerpo.encode('ascii')))}"

    srv = Servidor()
    srv.llamadas = []

    def falso_post(ruta, cuerpo):
        srv.llamadas.append((ruta, cuerpo))
        return srv.respuesta

    monkeypatch.setattr(licencia, "_post", falso_post)
    return srv


def _como_estacion(monkeypatch):
    monkeypatch.setattr(config, "MODO_INSTALACION", "ESTACION")
    licencia.invalidar_cache()


# ── Servidor: activar / validar ────────────────────────────────────────────


def test_sin_licencia_al_inicio(servidor):
    assert LicenciaService.estado_actual().estado == ESTADO_SIN_LICENCIA


def test_deshabilitada_sin_url_permite_escribir(monkeypatch):
    monkeypatch.setattr(config, "LICENCIA_URL", "")
    assert LicenciaService.estado_actual().permite_escritura


def test_activar_guarda_token_y_deja_activa(servidor):
    servidor.respuesta = (200, {"token": servidor.firmar()})
    estado = LicenciaService.activar(CLAVE)
    assert estado.estado == ESTADO_ACTIVA
    assert estado.plan == "pro"
    assert estado.max_estaciones == 3
    ruta, cuerpo = servidor.llamadas[0]
    assert ruta == "/v1/activar"
    assert cuerpo["clave"] == "ABCDEFGHJKMNPQRSTVWX"
    assert cuerpo["hw_id"] == licencia.hw_id()


def test_activar_reporta_a_esta_pc_como_estacion(servidor):
    servidor.respuesta = (200, {"token": servidor.firmar()})
    LicenciaService.activar(CLAVE)
    reportadas = servidor.llamadas[0][1]["estaciones"]
    assert [e["hw"] for e in reportadas] == [licencia.hw_id()]


def test_activar_rechazada_muestra_el_error_del_servidor(servidor):
    servidor.respuesta = (409, {"error": "Esta licencia ya esta activada en otra computadora."})
    with pytest.raises(LicenciaError, match="otra computadora"):
        LicenciaService.activar(CLAVE)
    assert LicenciaService.estado_actual().estado == ESTADO_SIN_LICENCIA


def test_activar_clave_con_formato_invalido_ni_llama_al_servidor(servidor):
    with pytest.raises(LicenciaError):
        LicenciaService.activar("abc")
    assert servidor.llamadas == []


def test_token_con_firma_ajena_no_se_guarda(servidor):
    otra = Ed25519PrivateKey.generate()
    cuerpo = _b64u(json.dumps({"hw": licencia.hw_id(), "valido_hasta": time.time() + DIA}).encode())
    falso = f"{cuerpo}.{_b64u(otra.sign(cuerpo.encode('ascii')))}"
    servidor.respuesta = (200, {"token": falso})
    with pytest.raises(LicenciaError):
        LicenciaService.activar(CLAVE)


def test_en_el_servidor_un_token_de_otra_pc_es_invalido(servidor):
    servidor.respuesta = (200, {"token": servidor.firmar(hw="otra-pc")})
    LicenciaService.activar(CLAVE)
    assert LicenciaService.estado_actual().estado == ESTADO_INVALIDA


def test_vence_por_fecha_de_expiracion(servidor):
    servidor.respuesta = (200, {"token": servidor.firmar()})
    LicenciaService.activar(CLAVE)
    assert LicenciaService.estado_actual(time.time() + 31 * DIA).estado == ESTADO_VENCIDA


def test_gracia_sin_conexion_dura_siete_dias(servidor):
    servidor.respuesta = (200, {"token": servidor.firmar(expira=None)})
    LicenciaService.activar(CLAVE)
    assert LicenciaService.estado_actual(time.time() + 6 * DIA).estado == ESTADO_ACTIVA
    assert LicenciaService.estado_actual(time.time() + 8 * DIA).estado == ESTADO_VALIDAR_EN_LINEA


def test_retroceder_el_reloj_invalida(servidor):
    servidor.respuesta = (200, {"token": servidor.firmar(expira=None)})
    LicenciaService.activar(CLAVE)
    # La app "vio" el dia 3 y luego alguien devuelve el reloj al dia 0.
    licencia._guardar_marcas_locales({"ultimo_visto": time.time() + 3 * DIA})
    assert LicenciaService.estado_actual().estado == ESTADO_INVALIDA


def test_validar_en_linea_renueva_el_token_y_manda_las_estaciones(servidor):
    servidor.respuesta = (200, {"token": servidor.firmar(valido_hasta=int(time.time()) + 60)})
    LicenciaService.activar(CLAVE)
    licencia._almacen.registrar_estacion(OTRA_PC, "CAJA-2")
    servidor.respuesta = (200, {"token": servidor.firmar()})
    LicenciaService.validar_en_linea()
    assert LicenciaService.estado_actual(time.time() + 5 * DIA).estado == ESTADO_ACTIVA
    ruta, cuerpo = servidor.llamadas[-1]
    assert ruta == "/v1/validar"
    assert {e["nombre"] for e in cuerpo["estaciones"]} >= {"CAJA-2"}


def test_validar_en_linea_sin_internet_conserva_el_token(servidor, monkeypatch):
    servidor.respuesta = (200, {"token": servidor.firmar()})
    LicenciaService.activar(CLAVE)

    def sin_red(ruta, cuerpo):
        raise licencia.LicenciaRedError("sin internet")

    monkeypatch.setattr(licencia, "_post", sin_red)
    with pytest.raises(licencia.LicenciaRedError):
        LicenciaService.validar_en_linea()
    assert LicenciaService.estado_actual().estado == ESTADO_ACTIVA


def test_revocada_corta_de_inmediato(servidor):
    servidor.respuesta = (200, {"token": servidor.firmar()})
    LicenciaService.activar(CLAVE)
    servidor.respuesta = (403, {"codigo": "REVOCADA", "error": "Licencia revocada."})
    assert LicenciaService.validar_en_linea().estado == ESTADO_REVOCADA
    assert not LicenciaService.estado_actual().permite_escritura


def test_el_estado_sobrevive_a_reiniciar_la_app(servidor):
    servidor.respuesta = (200, {"token": servidor.firmar()})
    LicenciaService.activar(CLAVE)
    licencia.invalidar_cache()
    assert LicenciaService.estado_actual().estado == ESTADO_ACTIVA


def test_reloj_corrupto_no_bloquea(servidor):
    servidor.respuesta = (200, {"token": servidor.firmar()})
    LicenciaService.activar(CLAVE)
    licencia.RUTA_RELOJ.write_text("basura", encoding="utf-8")
    licencia._marcas_cache = (dict(licencia._MARCAS_VACIAS), 0.0)
    assert LicenciaService.estado_actual().estado == ESTADO_ACTIVA


def test_si_la_base_no_responde_y_no_hay_cache_no_deja_escribir(servidor, monkeypatch):
    class Caida(AlmacenMemoria):
        def leer(self):
            raise RuntimeError("SQL Server caido")

    monkeypatch.setattr(licencia, "_almacen", Caida())
    licencia.invalidar_cache()
    assert LicenciaService.estado_actual().estado == ESTADO_INVALIDA


# ── Estaciones ──────────────────────────────────────────────────────────────


def test_la_estacion_lee_el_token_del_servidor_sin_chequear_hardware(servidor, monkeypatch):
    # El token es de la PC servidor ("hw" ajeno): una estacion igual lo acepta.
    LicenciaService._guardar_token(CLAVE, servidor.firmar(hw="la-pc-del-servidor"))
    _como_estacion(monkeypatch)
    estado = LicenciaService.estado_actual()
    assert estado.estado == ESTADO_ACTIVA
    assert estado.cliente == "Cliente SA"


def test_la_estacion_no_puede_activar_ni_validar(servidor, monkeypatch):
    _como_estacion(monkeypatch)
    with pytest.raises(LicenciaError, match="servidor"):
        LicenciaService.activar(CLAVE)
    with pytest.raises(LicenciaError, match="servidor"):
        LicenciaService.validar_en_linea()
    assert servidor.llamadas == []


def test_la_estacion_ve_la_revocacion_que_aplico_el_servidor(servidor, monkeypatch):
    servidor.respuesta = (200, {"token": servidor.firmar()})
    LicenciaService.activar(CLAVE)
    servidor.respuesta = (403, {"codigo": "REVOCADA", "error": "Licencia revocada."})
    LicenciaService.validar_en_linea()
    _como_estacion(monkeypatch)
    assert LicenciaService.estado_actual().estado == ESTADO_REVOCADA


def test_estacion_sin_puesto_queda_en_solo_lectura(servidor, monkeypatch):
    LicenciaService._guardar_token(CLAVE, servidor.firmar(max_estaciones=1, estaciones=[OTRA_PC]))
    _como_estacion(monkeypatch)
    estado = LicenciaService.estado_actual()
    assert estado.estado == ESTADO_LIMITE_ESTACIONES
    assert not estado.permite_escritura


def test_estacion_con_puesto_asignado_trabaja(servidor, monkeypatch):
    LicenciaService._guardar_token(CLAVE, servidor.firmar(max_estaciones=1, estaciones=[licencia.hw_id()]))
    _como_estacion(monkeypatch)
    assert LicenciaService.estado_actual().estado == ESTADO_ACTIVA


def test_hay_puesto_libre_aunque_el_token_aun_no_liste_a_la_estacion(servidor, monkeypatch):
    # 3 puestos, solo 1 ocupado: una estacion recien registrada entra sin esperar al servicio.
    LicenciaService._guardar_token(CLAVE, servidor.firmar(max_estaciones=3, estaciones=[OTRA_PC]))
    _como_estacion(monkeypatch)
    assert LicenciaService.estado_actual().estado == ESTADO_ACTIVA


def test_token_sin_max_estaciones_no_limita(servidor, monkeypatch):
    LicenciaService._guardar_token(CLAVE, servidor.firmar(max_estaciones=None, estaciones=None))
    _como_estacion(monkeypatch)
    assert LicenciaService.estado_actual().estado == ESTADO_ACTIVA


def test_registrar_estacion_anota_esta_pc_una_vez_por_intervalo(servidor):
    LicenciaService.registrar_estacion()
    assert list(licencia._almacen.filas) == [licencia.hw_id()]
    primera = licencia._almacen.filas[licencia.hw_id()]["ultima_vez"]
    LicenciaService.registrar_estacion()  # dentro del intervalo: no vuelve a escribir
    assert licencia._almacen.filas[licencia.hw_id()]["ultima_vez"] == primera


def test_un_fallo_al_registrar_estacion_no_rompe_nada(servidor, monkeypatch):
    def roto(hw, nombre):
        raise RuntimeError("sin base")

    monkeypatch.setattr(licencia._almacen, "registrar_estacion", roto)
    LicenciaService.registrar_estacion()  # no lanza


def test_estaciones_registradas_marca_cuales_tienen_puesto(servidor):
    licencia._almacen.registrar_estacion(OTRA_PC, "CAJA-2")
    servidor.respuesta = (200, {"token": servidor.firmar(max_estaciones=1, estaciones=[licencia.hw_id()])})
    LicenciaService.activar(CLAVE)  # tambien registra esta PC, con el nombre del equipo
    estaciones = LicenciaService.estaciones_registradas()
    esta_pc = next(e for e in estaciones if e["esta_pc"])
    caja_2 = next(e for e in estaciones if e["nombre"] == "CAJA-2")
    assert esta_pc["autorizada"]
    assert not caja_2["autorizada"]


def test_refrescar_periodico_en_estacion_relee_la_base_sin_llamar_al_servidor(servidor, monkeypatch):
    servidor.respuesta = (200, {"token": servidor.firmar()})
    LicenciaService.activar(CLAVE)
    servidor.llamadas.clear()
    _como_estacion(monkeypatch)
    assert LicenciaService.refrescar_periodico().estado == ESTADO_ACTIVA
    assert servidor.llamadas == []


# ── Gate de solo lectura ────────────────────────────────────────────────────


@pytest.fixture()
def motor_con_gate(servidor):
    motor = create_engine("sqlite://")
    with motor.begin() as c:
        c.execute(text("CREATE TABLE factura_venta (id INTEGER PRIMARY KEY, total INTEGER)"))
        c.execute(text("CREATE TABLE usuarios (id INTEGER PRIMARY KEY, intentos INTEGER)"))
        c.execute(text("CREATE TABLE licencia_sistema (id INTEGER PRIMARY KEY, token TEXT)"))
        c.execute(text("INSERT INTO usuarios VALUES (1, 0)"))
    licencia.instalar_gate(motor)
    return motor


def test_gate_bloquea_escritura_sin_licencia_pero_deja_leer(motor_con_gate):
    with motor_con_gate.begin() as c:
        assert c.execute(text("SELECT COUNT(*) FROM factura_venta")).scalar() == 0
    for sql in (
        "INSERT INTO factura_venta VALUES (1, 10)",
        "UPDATE factura_venta SET total = 1",
        "DELETE FROM factura_venta",
        "INSERT INTO dbo.factura_venta VALUES (2, 10)",
    ):
        with pytest.raises(LicenciaSoloLecturaError):
            with motor_con_gate.begin() as c:
                c.execute(text(sql))


def test_gate_deja_escribir_tablas_exentas_incluida_la_licencia(motor_con_gate):
    with motor_con_gate.begin() as c:
        c.execute(text("UPDATE usuarios SET intentos = intentos + 1"))
        c.execute(text("INSERT INTO licencia_sistema VALUES (1, 'x')"))


def test_gate_deja_escribir_con_licencia_activa(servidor, motor_con_gate):
    servidor.respuesta = (200, {"token": servidor.firmar()})
    LicenciaService.activar(CLAVE)
    with motor_con_gate.begin() as c:
        c.execute(text("INSERT INTO factura_venta VALUES (1, 10)"))


def test_gate_bloquea_a_una_estacion_sin_puesto(servidor, motor_con_gate, monkeypatch):
    LicenciaService._guardar_token(CLAVE, servidor.firmar(max_estaciones=1, estaciones=[OTRA_PC]))
    _como_estacion(monkeypatch)
    with pytest.raises(LicenciaSoloLecturaError):
        with motor_con_gate.begin() as c:
            c.execute(text("INSERT INTO factura_venta VALUES (1, 10)"))


def test_gate_avisa_a_la_ui_cuando_bloquea(motor_con_gate, monkeypatch):
    avisos = []
    monkeypatch.setattr(licencia, "_aviso_bloqueo", avisos.append)
    with pytest.raises(LicenciaSoloLecturaError):
        with motor_con_gate.begin() as c:
            c.execute(text("INSERT INTO factura_venta VALUES (1, 10)"))
    assert len(avisos) == 1
    assert avisos[0].estado == ESTADO_SIN_LICENCIA


def test_gate_no_avisa_en_lecturas_ni_tablas_exentas(motor_con_gate, monkeypatch):
    avisos = []
    monkeypatch.setattr(licencia, "_aviso_bloqueo", avisos.append)
    with motor_con_gate.begin() as c:
        c.execute(text("SELECT COUNT(*) FROM factura_venta"))
        c.execute(text("UPDATE usuarios SET intentos = intentos + 1"))
    assert avisos == []


def test_un_aviso_que_falla_no_cambia_el_bloqueo(motor_con_gate, monkeypatch):
    def roto(_estado):
        raise RuntimeError("la UI exploto")

    monkeypatch.setattr(licencia, "_aviso_bloqueo", roto)
    with pytest.raises(LicenciaSoloLecturaError):
        with motor_con_gate.begin() as c:
            c.execute(text("INSERT INTO factura_venta VALUES (1, 10)"))


# ── AlmacenDB contra SQL Server (base de pruebas) ──────────────────────────


@pytest.fixture()
def almacen_db(monkeypatch, test_engine, db_session):
    """AlmacenDB apuntando a la base de pruebas (db_session limpia las tablas antes de cada test)."""
    monkeypatch.setattr("app.db.session.SessionLocal", sessionmaker(bind=test_engine, autoflush=False))
    return AlmacenDB()


def test_sql_server_licencia_vacia_al_inicio(almacen_db):
    assert almacen_db.leer() is None


def test_sql_server_guardar_y_leer_la_licencia(almacen_db):
    almacen_db.guardar({"clave": "ABC", "token": "t" * 3000, "rechazo": None, "mensaje": None})
    fila = almacen_db.leer()
    assert (fila["clave"], fila["token"], fila["rechazo"], fila["mensaje"]) == ("ABC", "t" * 3000, None, None)
    assert fila["ultimo_visto"] is None  # sin marcas hasta la primera validacion
    almacen_db.guardar({"clave": "ABC", "token": None, "rechazo": "REVOCADA", "mensaje": "Revocada."})
    assert almacen_db.leer()["rechazo"] == "REVOCADA"


def test_sql_server_la_licencia_es_una_sola_fila(almacen_db, test_engine):
    almacen_db.guardar({"clave": "A", "token": "x"})
    almacen_db.guardar({"clave": "B", "token": "y"})
    with test_engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM dbo.licencia_sistema")).scalar() == 1
    with pytest.raises(IntegrityError):  # CHECK id = 1
        with test_engine.begin() as c:
            c.execute(text("INSERT INTO dbo.licencia_sistema (id) VALUES (2)"))


def test_sql_server_registrar_estacion_inserta_y_luego_actualiza(almacen_db):
    almacen_db.registrar_estacion("a" * 64, "CAJA-1")
    almacen_db.registrar_estacion("a" * 64, "CAJA-1-RENOMBRADA")
    almacen_db.registrar_estacion("c" * 64, "CAJA-3")
    filas = almacen_db.estaciones()
    assert [f["nombre"] for f in filas] == ["CAJA-1-RENOMBRADA", "CAJA-3"]
    assert filas[0]["hw_id"].strip() == "a" * 64
    assert isinstance(filas[0]["ultima_vez"], datetime)


# ── Endurecimiento contra la manipulacion del reloj ────────────────────────


def _olvidar_marcas_locales():
    """Simula que alguien borro reloj.dat (y el registro): solo quedan las marcas de la base de datos."""
    licencia.RUTA_RELOJ.unlink(missing_ok=True)
    licencia._marcas_cache = (dict(licencia._MARCAS_VACIAS), 0.0)
    licencia.invalidar_cache()  # el ataque tarda mas de los 30 s que dura el cache de la fila de licencia


def test_borrar_reloj_dat_no_reinicia_la_proteccion(servidor):
    servidor.respuesta = (200, {"token": servidor.firmar(expira=None)})
    LicenciaService.activar(CLAVE)
    # La app se uso 3 dias y dejo su ultima hora vista en las tres copias...
    licencia._ultimo_reloj_persistido = 0.0
    assert LicenciaService.estado_actual(time.time() + 3 * DIA).estado == ESTADO_ACTIVA
    # ...alguien borra reloj.dat y devuelve el reloj al dia 0: la copia de la base de datos lo delata.
    _olvidar_marcas_locales()
    assert LicenciaService.estado_actual().estado == ESTADO_INVALIDA


def test_reloj_atrasado_mas_que_la_tolerancia_respecto_al_servidor_de_licencias(servidor):
    servidor.respuesta = (200, {"token": servidor.firmar(expira=None)})
    LicenciaService.activar(CLAVE)
    una_hora_atras = time.time() - 3600
    assert LicenciaService.estado_actual(una_hora_atras).estado == ESTADO_INVALIDA


def test_un_desajuste_pequeno_del_reloj_no_bloquea(servidor):
    servidor.respuesta = (200, {"token": servidor.firmar(expira=None)})
    LicenciaService.activar(CLAVE)
    cinco_minutos_atras = time.time() - 300
    assert LicenciaService.estado_actual(cinco_minutos_atras).estado == ESTADO_ACTIVA


def test_tras_reiniciar_el_equipo_el_ancla_sigue_detectando_el_reloj_atrasado(servidor, monkeypatch):
    servidor.respuesta = (200, {"token": servidor.firmar(expira=None)})
    LicenciaService.activar(CLAVE)
    # Reinicio: el contador de arranque vuelve a casi 0. La cota baja, pero el servidor de licencias
    # ya vio esta hora: un reloj atrasado respecto a ella sigue siendo invalido.
    monkeypatch.setattr(licencia, "_tick_ms", lambda: 5_000)
    _olvidar_marcas_locales()
    assert LicenciaService.estado_actual(time.time() - 3 * 3600).estado == ESTADO_INVALIDA


def test_la_cota_del_ancla_no_da_falsos_positivos_tras_reiniciar(servidor, monkeypatch):
    servidor.respuesta = (200, {"token": servidor.firmar(expira=None)})
    LicenciaService.activar(CLAVE)
    tick_actual = licencia._tick_ms()
    monkeypatch.setattr(licencia, "_tick_ms", lambda: max(0, tick_actual // 2))  # contador "reiniciado"
    _olvidar_marcas_locales()
    assert LicenciaService.estado_actual().estado == ESTADO_ACTIVA


def test_la_cota_del_ancla_cuenta_el_tiempo_aunque_se_atrase_el_reloj_de_windows(servidor, monkeypatch):
    # Ataque principal: la licencia vence en 2 dias. Pasan 3 dias REALES (el contador de arranque avanza
    # 3 dias) y el usuario deja la fecha de Windows en el dia 1: sin la cota seguiria "vigente".
    servidor.respuesta = (200, {"token": servidor.firmar(expira=int(time.time()) + 2 * DIA)})
    LicenciaService.activar(CLAVE)
    tick_inicial = licencia._tick_ms()
    monkeypatch.setattr(licencia, "_tick_ms", lambda: tick_inicial + 3 * DIA * 1000)
    reloj_atrasado = time.time() + 1 * DIA
    estado = LicenciaService.estado_actual(reloj_atrasado)
    assert estado.estado == ESTADO_INVALIDA  # detectado: el reloj esta 2 dias por debajo de la hora real minima


def test_una_validacion_en_linea_borra_las_marcas_adelantadas_por_un_reloj_mal_puesto(servidor):
    servidor.respuesta = (200, {"token": servidor.firmar(expira=None)})
    LicenciaService.activar(CLAVE)
    licencia._guardar_marcas_locales({"ultimo_visto": time.time() + 10 * DIA})  # reloj adelantado por error
    assert LicenciaService.estado_actual().estado == ESTADO_INVALIDA
    servidor.respuesta = (200, {"token": servidor.firmar(expira=None)})
    LicenciaService.validar_en_linea()  # la hora del servidor de licencias es la verdad
    assert LicenciaService.estado_actual().estado == ESTADO_ACTIVA


def test_la_licencia_vencida_se_nota_aun_con_el_reloj_atrasado_dentro_de_la_tolerancia(servidor):
    servidor.respuesta = (200, {"token": servidor.firmar(expira=int(time.time()) + 600)})
    LicenciaService.activar(CLAVE)
    # 10 minutos despues de vencer y con el reloj 10 minutos atrasado (dentro de la tolerancia): vencida igual,
    # porque se usa la cota del ancla y no el reloj atrasado.
    tick_inicial = licencia._tick_ms()
    estado = None
    from unittest import mock

    with mock.patch.object(licencia, "_tick_ms", lambda: tick_inicial + 20 * 60 * 1000):
        estado = LicenciaService.estado_actual(time.time() + 600)
    assert estado.estado == ESTADO_VENCIDA


# ── Estaciones: la hora la da el SQL Server ────────────────────────────────


def test_la_estacion_ignora_el_reloj_de_su_propia_pc(servidor, monkeypatch):
    LicenciaService._guardar_token(CLAVE, servidor.firmar(expira=int(time.time()) + 2 * DIA))
    _como_estacion(monkeypatch)
    assert LicenciaService.estado_actual().estado == ESTADO_ACTIVA
    # El usuario de la estacion adelanta o atrasa 30 dias el reloj de Windows: no cambia nada.
    for desfase in (30 * DIA, -30 * DIA):
        monkeypatch.setattr(time, "time", lambda d=desfase: _TIEMPO_REAL() + d)
        assert LicenciaService.estado_actual().estado == ESTADO_ACTIVA


def test_la_estacion_se_rige_por_la_hora_del_sql_server(servidor, monkeypatch):
    LicenciaService._guardar_token(CLAVE, servidor.firmar(expira=int(time.time()) + 2 * DIA))
    _como_estacion(monkeypatch)
    assert LicenciaService.estado_actual().estado == ESTADO_ACTIVA
    # El servidor SQL (el reloj que si importa) pasa a marcar 3 dias despues: la licencia esta vencida.
    licencia._almacen.desfase_hora = 3 * DIA
    licencia.invalidar_cache()
    assert LicenciaService.estado_actual().estado == ESTADO_VENCIDA


def test_la_estacion_sin_conexion_a_la_hora_del_sql_usa_su_reloj(servidor, monkeypatch):
    LicenciaService._guardar_token(CLAVE, servidor.firmar())
    _como_estacion(monkeypatch)

    def sin_hora():
        raise RuntimeError("sin hora")

    monkeypatch.setattr(licencia._almacen, "hora_servidor", sin_hora)
    assert LicenciaService.estado_actual().estado == ESTADO_ACTIVA


_TIEMPO_REAL = time.time


def test_fusionar_marcas_toma_la_mas_reciente():
    a = {"ultimo_visto": 100, "ancla_servidor": 50, "ancla_tick": 7}
    b = {"ultimo_visto": 80, "ancla_servidor": 90, "ancla_tick": 3}
    fusion = licencia._fusionar_marcas(a, b)
    assert fusion == {"ultimo_visto": 100.0, "ancla_servidor": 90.0, "ancla_tick": 3}


def test_marcas_corruptas_se_normalizan():
    assert licencia._normalizar_marcas({"ultimo_visto": "x", "ancla_tick": None}) == licencia._MARCAS_VACIAS
    assert licencia._normalizar_marcas(None) == licencia._MARCAS_VACIAS


def test_el_contador_de_arranque_no_depende_de_la_fecha_de_windows():
    a = licencia._tick_ms()
    b = licencia._tick_ms()
    assert b >= a


def test_sql_server_guardar_y_leer_las_marcas_de_tiempo(almacen_db):
    almacen_db.guardar({"clave": "A", "token": "x"})
    almacen_db.guardar_marcas({"ultimo_visto": 500, "ancla_servidor": 400, "ancla_tick": 12345}, reemplazar=True)
    fila = almacen_db.leer()
    assert (fila["ultimo_visto"], fila["ancla_servidor"], fila["ancla_tick"]) == (500, 400, 12345)
    # sin reemplazar solo sube ultimo_visto y nunca baja
    almacen_db.guardar_marcas({"ultimo_visto": 100, "ancla_servidor": 0, "ancla_tick": 0})
    assert almacen_db.leer()["ultimo_visto"] == 500
    almacen_db.guardar_marcas({"ultimo_visto": 900, "ancla_servidor": 0, "ancla_tick": 0})
    fila = almacen_db.leer()
    assert (fila["ultimo_visto"], fila["ancla_servidor"]) == (900, 400)
    # guardar la licencia no borra las marcas
    almacen_db.guardar({"clave": "B", "token": "y"})
    assert almacen_db.leer()["ultimo_visto"] == 900


def test_sql_server_hora_servidor_es_utc_y_cercana_a_la_real(almacen_db):
    assert abs(almacen_db.hora_servidor() - time.time()) < 300
