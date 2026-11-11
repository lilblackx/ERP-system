"""Blindaje contra una conexion cortada (10054 / 08S01 "Communication link failure").

La red, un firewall o el servidor pueden cerrar una conexion inactiva mientras un dialogo la tiene en su poder: la
primera consulta del siguiente clic fallaba con el SQL crudo en pantalla. Ahora:
  * `es_conexion_perdida` reconoce el corte (no un error de la consulta);
  * `reintentar_en_deadlock(..., session=...)` repite la operacion una vez con una conexion nueva;
  * `SesionResiliente` repite sola una LECTURA fallida (si la transaccion no tiene nada que perder);
  * `MessageBox` nunca muestra el SQL ni el texto del driver.
"""

from unittest.mock import MagicMock

import pyodbc
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import sessionmaker

from app.db.models import Usuario
from app.db.session import SesionResiliente
from app.services import db_utils
from app.services.db_utils import (
    MENSAJE_BD_GENERICO,
    MENSAJE_BD_OCUPADA,
    MENSAJE_CONEXION_PERDIDA,
    es_conexion_perdida,
    mensaje_de_error_bd,
    mensaje_de_texto_bd,
    reintentar_en_deadlock,
)
from app.ui.message_box import depurar_mensaje_error

TEXTO_10054 = (
    "('08S01', '[08S01] [Microsoft][ODBC Driver 18 for SQL Server]TCP Provider: Se ha forzado la interrupción de una "
    "conexión existente por el host remoto.\r\n (10054); [08S01] [Microsoft][ODBC Driver 18 for SQL Server]"
    "Communication link failure (10054)')"
)


def _error_conexion_perdida() -> OperationalError:
    """Lo que SQLAlchemy levanta cuando pyodbc informa el corte."""
    return OperationalError("SELECT usuarios.id_usuario FROM usuarios", (3,), pyodbc.OperationalError(TEXTO_10054))


def _error_deadlock() -> OperationalError:
    return OperationalError("UPDATE x", (), pyodbc.OperationalError("('40001', 'Transaction was deadlocked')"))


def _error_de_consulta() -> DBAPIError:
    return DBAPIError("SELECT", (), pyodbc.ProgrammingError("('42S02', \"Invalid object name 'xyz'\")"))


# -- Reconocer el corte ------------------------------------------------------------------------------------------------


def test_un_corte_de_conexion_se_reconoce_por_sqlstate_y_por_texto():
    assert es_conexion_perdida(_error_conexion_perdida())
    assert es_conexion_perdida(pyodbc.OperationalError("('08S01', 'Communication link failure')"))
    assert es_conexion_perdida(pyodbc.OperationalError("('08001', 'Login timeout expired')"))
    assert es_conexion_perdida(pyodbc.Error("TCP Provider: connection reset (10054)"))


def test_sqlalchemy_marca_como_invalidada_la_conexion_y_eso_basta():
    error = OperationalError("SELECT 1", (), Exception("lo que sea"), connection_invalidated=True)

    assert es_conexion_perdida(error)


@pytest.mark.parametrize(
    "error",
    [_error_deadlock(), _error_de_consulta(), ValueError("El cliente excede su limite"), Exception("boom")],
)
def test_lo_que_no_es_un_corte_no_se_confunde_con_uno(error):
    assert not es_conexion_perdida(error)


# -- Mensajes para el usuario ------------------------------------------------------------------------------------------


def test_mensaje_de_error_bd_clasifica_sin_enseñar_el_sql():
    assert mensaje_de_error_bd(_error_conexion_perdida()) == MENSAJE_CONEXION_PERDIDA
    assert mensaje_de_error_bd(_error_deadlock()) == MENSAJE_BD_OCUPADA
    assert mensaje_de_error_bd(_error_de_consulta()) == MENSAJE_BD_GENERICO
    assert mensaje_de_error_bd(ValueError("x")) is None


def test_un_texto_normal_no_se_toca():
    assert mensaje_de_texto_bd("El cliente excede su limite de credito") is None
    assert depurar_mensaje_error("No se pudo cargar el listado.") == "No se pudo cargar el listado."


def test_el_aviso_del_cobro_no_muestra_el_sql_y_conserva_lo_que_decia_antes():
    crudo = (
        f"No se pudo registrar el cobro: (pyodbc.OperationalError) {TEXTO_10054} "
        "[SQL: SELECT usuarios.id_usuario FROM usuarios WHERE usuarios.id_usuario = ?]\n[parameters: (3,)]\n"
        "(Background on this error at: https://sqlalche.me/e/20/e3q8)"
    )

    texto = depurar_mensaje_error(crudo)

    assert texto == f"No se pudo registrar el cobro. {MENSAJE_CONEXION_PERDIDA}"
    for filtrado in ("SELECT", "pyodbc", "ODBC", "10054", "sqlalche"):
        assert filtrado not in texto


def test_el_aviso_de_una_carga_en_hilo_con_error_de_bd_tampoco_muestra_el_sql():
    crudo = "No se pudo cargar el listado.\n\nError: (pyodbc.ProgrammingError) ('42000', 'x') [SQL: SELECT 1]"

    assert depurar_mensaje_error(crudo) == f"No se pudo cargar el listado. {MENSAJE_BD_GENERICO}"


def test_un_deadlock_o_un_bloqueo_se_explican_como_sistema_ocupado():
    assert depurar_mensaje_error(
        "No se pudo anular: (pyodbc.OperationalError) ('40001', 'deadlock') [SQL: x]"
    ).endswith(MENSAJE_BD_OCUPADA)


def test_message_box_aplica_el_saneado_a_errores_y_avisos_pero_no_a_confirmaciones(qtbot):
    from PySide6.QtWidgets import QLabel

    from app.ui.message_box import MessageBox

    crudo = "No se pudo guardar: (pyodbc.Error) [SQL: INSERT INTO x VALUES (?)]"

    def texto_mostrado(tipo):
        dialogo = MessageBox(None, "Aviso", crudo, tipo=tipo)
        qtbot.addWidget(dialogo)
        return " ".join(etiqueta.text() for etiqueta in dialogo.findChildren(QLabel))

    for tipo in ("critical", "warning"):
        mostrado = texto_mostrado(tipo)
        assert "INSERT" not in mostrado and "pyodbc" not in mostrado and "No se pudo guardar" in mostrado
    assert "pyodbc" in texto_mostrado("information")  # un aviso informativo no es un error: se muestra tal cual


# -- Repetir la operacion con una conexion nueva ----------------------------------------------------------------


def test_la_operacion_se_repite_una_vez_con_rollback_si_se_perdio_la_conexion():
    sesion = MagicMock()
    llamadas = []

    def operacion():
        llamadas.append(1)
        if len(llamadas) == 1:
            raise _error_conexion_perdida()
        return "cobro registrado"

    assert reintentar_en_deadlock(operacion, session=sesion) == "cobro registrado"
    assert len(llamadas) == 2
    sesion.rollback.assert_called_once()  # descarta la conexion muerta antes de repetir


def test_sin_sesion_no_se_repite_porque_repetir_sobre_una_sesion_invalida_fallaria_otra_vez():
    llamadas = []

    def operacion():
        llamadas.append(1)
        raise _error_conexion_perdida()

    with pytest.raises(OperationalError):
        reintentar_en_deadlock(operacion)
    assert len(llamadas) == 1


def test_si_la_conexion_se_pierde_otra_vez_el_error_sube_en_vez_de_repetir_sin_fin():
    sesion = MagicMock()
    llamadas = []

    def operacion():
        llamadas.append(1)
        raise _error_conexion_perdida()

    with pytest.raises(OperationalError):
        reintentar_en_deadlock(operacion, session=sesion)
    assert len(llamadas) == 2 and sesion.rollback.call_count == 1  # una repeticion, no mas


def test_un_deadlock_sigue_reintentandose_como_antes(monkeypatch):
    monkeypatch.setattr(db_utils.time, "sleep", lambda s: None)
    llamadas = []

    def operacion():
        llamadas.append(1)
        if len(llamadas) < 3:
            raise _error_deadlock()
        return "ok"

    assert reintentar_en_deadlock(operacion) == "ok" and len(llamadas) == 3


def test_un_error_de_consulta_no_se_reintenta():
    llamadas = []

    def operacion():
        llamadas.append(1)
        raise _error_de_consulta()

    with pytest.raises(DBAPIError):
        reintentar_en_deadlock(operacion, session=MagicMock())
    assert len(llamadas) == 1


def test_si_el_rollback_tambien_falla_se_sube_el_error_original():
    sesion = MagicMock()
    sesion.rollback.side_effect = RuntimeError("rollback roto")

    def operacion():
        raise _error_conexion_perdida()

    with pytest.raises(OperationalError):
        reintentar_en_deadlock(operacion, session=sesion)


# -- SesionResiliente contra el servidor de pruebas: se mata la conexion de verdad ------------------------------


@pytest.fixture()
def sesion_resiliente(test_engine):
    fabrica = sessionmaker(bind=test_engine, class_=SesionResiliente, autoflush=False, autocommit=False)
    with fabrica() as sesion:
        yield sesion


def _matar_la_conexion_de(sesion, test_engine):
    """Cierra desde el servidor la conexion que tiene la sesion (como lo hace un firewall o un reinicio)."""
    spid = sesion.execute(text("SELECT @@SPID")).scalar()
    with test_engine.connect() as admin:
        admin.execution_options(isolation_level="AUTOCOMMIT").execute(text(f"KILL {int(spid)}"))
    return spid


def test_una_lectura_se_repite_sola_si_la_conexion_de_la_sesion_murio(sesion_resiliente, test_engine, db_session):
    spid_viejo = _matar_la_conexion_de(sesion_resiliente, test_engine)

    resultado = sesion_resiliente.execute(text("SELECT @@SPID")).scalar()  # el "siguiente clic" del dialogo

    assert resultado != spid_viejo  # la repeticion fue por una conexion nueva


def test_get_y_query_tambien_se_recuperan(sesion_resiliente, test_engine, db_session):
    from tests.factories import crear_usuario_admin

    admin = crear_usuario_admin(db_session)
    sesion_resiliente.query(Usuario).count()  # la sesion toma su conexion
    _matar_la_conexion_de(sesion_resiliente, test_engine)

    assert sesion_resiliente.get(Usuario, admin.id_usuario).id_usuario == admin.id_usuario
    _matar_la_conexion_de(sesion_resiliente, test_engine)
    assert sesion_resiliente.query(Usuario).count() >= 1


def test_con_una_escritura_ya_enviada_no_se_repite_en_silencio(sesion_resiliente, test_engine, db_session):
    """La transaccion con la escritura se perdio en el servidor: repetir solo la lectura haria creer que sigue ahi."""
    sesion_resiliente.execute(
        text("SET LOCK_TIMEOUT 5000")
    )  # no es una consulta: la transaccion ya no es de solo lectura
    _matar_la_conexion_de(sesion_resiliente, test_engine)

    with pytest.raises(DBAPIError):
        sesion_resiliente.execute(text("SELECT 1"))


def test_despues_de_un_commit_o_rollback_la_sesion_vuelve_a_ser_resiliente(sesion_resiliente, test_engine, db_session):
    sesion_resiliente.execute(text("SET LOCK_TIMEOUT 5000"))
    sesion_resiliente.rollback()
    _matar_la_conexion_de(sesion_resiliente, test_engine)

    assert sesion_resiliente.execute(text("SELECT 1")).scalar() == 1


def test_con_cambios_pendientes_en_la_sesion_no_se_repite(sesion_resiliente, test_engine, db_session):
    sesion_resiliente.execute(text("SELECT 1"))
    _matar_la_conexion_de(sesion_resiliente, test_engine)
    sesion_resiliente.add(Usuario(nombre_usuario="pendiente", clave="x"))  # un cambio que un rollback descartaria

    with pytest.raises(DBAPIError):
        sesion_resiliente.execute(text("SELECT 1"))


def test_un_error_de_consulta_no_se_confunde_con_un_corte(sesion_resiliente):
    with pytest.raises(DBAPIError):
        sesion_resiliente.execute(text("SELECT * FROM tabla_que_no_existe"))


def test_la_sesion_de_la_app_es_resiliente():
    from app.db.session import SessionLocal

    sesion = SessionLocal()
    try:
        assert isinstance(sesion, SesionResiliente)
    finally:
        sesion.close()


def test_un_motor_sin_servidor_levanta_el_error_original_sin_bucle():
    motor = create_engine("mssql+pyodbc://sa:x@127.0.0.1,1/x?driver=ODBC+Driver+18+for+SQL+Server&LoginTimeout=1")
    fabrica = sessionmaker(bind=motor, class_=SesionResiliente)

    with fabrica() as sesion, pytest.raises(DBAPIError):
        sesion.execute(text("SELECT 1"))


# -- Arranque de la app: el servidor apagado no enseña el SQL ni el texto del driver ---------------------------------


def test_el_error_de_arranque_por_servidor_inaccesible_no_muestra_el_driver(qtbot, monkeypatch):
    from app import main

    mostrados = []
    monkeypatch.setattr(
        main.QMessageBox, "critical", staticmethod(lambda parent, titulo, texto: mostrados.append(texto))
    )

    main._error_de_arranque(
        pyodbc.OperationalError("('08001', '[08001] TCP Provider: No se puede establecer una conexión (10061)')")
    )

    assert "No se pudo conectar con la base de datos" in mostrados[0]
    assert "TCP Provider" not in mostrados[0] and "08001" not in mostrados[0]


def test_el_error_de_arranque_que_no_es_de_la_base_conserva_su_detalle(qtbot, monkeypatch):
    from app import main

    mostrados = []
    monkeypatch.setattr(
        main.QMessageBox, "critical", staticmethod(lambda parent, titulo, texto: mostrados.append(texto))
    )

    main._error_de_arranque(RuntimeError("Falta DB_PASSWORD en el archivo .env"))

    assert "Falta DB_PASSWORD en el archivo .env" in mostrados[0]
