"""La ventana del historial ante un usuario sin permiso (ver tests/services/test_historial_cliente_permisos.py)."""

from types import SimpleNamespace

from sqlalchemy.orm import sessionmaker

import app.ui.historial_cliente_window as hw
from tests.factories import crear_usuario_admin
from tests.services.test_historial_cliente_permisos import _cliente_con_factura, _usuario_con


def _ventana(qtbot, db_session, monkeypatch, usuario):
    avisos = []
    monkeypatch.setattr(
        hw.MessageBox, "warning", staticmethod(lambda parent, titulo, texto: avisos.append((titulo, texto)))
    )
    admin = crear_usuario_admin(db_session)
    cliente = _cliente_con_factura(db_session, admin)
    fabrica = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)
    ventana = hw.HistorialClienteWindow(
        fabrica, cliente.id_cliente, SimpleNamespace(nombre_razon_social="X"), id_usuario=usuario(db_session).id_usuario
    )
    qtbot.addWidget(ventana)
    return ventana, avisos


def test_la_ventana_avisa_que_no_tiene_permiso_en_vez_de_mostrar_el_historial(qtbot, db_session, monkeypatch):
    """La pantalla recibe el rechazo del servicio como un aviso, igual que cualquier otra carga sin permiso."""
    ventana, avisos = _ventana(qtbot, db_session, monkeypatch, lambda db: _usuario_con(db, ("ventas", "ver")))

    assert avisos and avisos[0][0] == "Sin permiso"
    assert ventana.tabla.rowCount() == 0


def test_con_clientes_ver_la_ventana_muestra_el_historial(qtbot, db_session, monkeypatch):
    ventana, avisos = _ventana(qtbot, db_session, monkeypatch, lambda db: _usuario_con(db, ("clientes", "ver")))

    assert avisos == []
    assert ventana.tabla.rowCount() == 1  # la factura (los abonos y notas aplicadas quedan para otras vistas)
